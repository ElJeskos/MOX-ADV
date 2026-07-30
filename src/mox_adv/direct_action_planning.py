"""Immutable proposal preparation for standalone Direct actions."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Mapping, Tuple

from mox_adv.approval_execution import deterministic_action_is_eligible
from mox_adv.commands import calculate_relative_target
from mox_adv.control_state import (
    ControlRejected,
    PreparedChange,
    canonical_hash,
)
from mox_adv.direct_action_common import (
    ACTION_OPERATION_TYPE,
    SUPPORTED_ACTION,
    TRIGGER_REASON_CODE,
    DirectActionContext,
    decision_summary,
    eligibility_snapshot,
    proposal_projection,
    result_metrics,
    state_fingerprint,
    trusted_scope,
)
from mox_adv.direct_action_runtime import DirectActionRuntimeV1
from mox_adv.direct_analysis import DIRECT_IDENTITY
from mox_adv.direct_conclusions import direct_hypotheses
from mox_adv.environment import ExecutionEnvironment
from mox_adv.module_api.v1 import (
    MODULE_RESULT_SCHEMA_VERSION,
    ModuleAssessmentV1,
    ModuleDecisionFactsV1,
    ModuleDecisionRecordStoreV1,
    ModuleDecisionV1,
    ModuleErrorV1,
    ModuleHypothesisV1,
    ModuleProposalV1,
    ModuleRecommendationV1,
    ModuleResultV1,
    PlanDirectActionCommandV1,
)
from mox_adv.recommend_contracts import (
    OptimizationProposalV1,
    ProviderMetadata,
)


class DirectActionPlanningV1:
    """Persist one deterministic proposal and its exact prepared change."""

    def __init__(
        self,
        runtime: DirectActionRuntimeV1,
        decision_records: ModuleDecisionRecordStoreV1,
    ) -> None:
        self._runtime = runtime
        self._decision_records = decision_records

    def plan(
        self,
        context: DirectActionContext,
    ) -> ModuleResultV1:
        request = context.request
        now = context.now
        evidence = context.evidence
        current = context.current
        metrics = context.metrics
        command = request.direct_action_command
        assert isinstance(command, PlanDirectActionCommandV1)
        if not deterministic_action_is_eligible(
            SUPPORTED_ACTION,
            eligibility_snapshot(context),
        ):
            return self._policy_rejected(context)
        fingerprint = state_fingerprint(request, current)
        projection = proposal_projection(self._runtime, metrics)
        trigger_store = self._runtime.trigger_store
        assert trigger_store is not None
        active_trigger = trigger_store.activate_proposal(
            fingerprint,
            TRIGGER_REASON_CODE,
            now,
        )
        identifier = active_trigger.proposal_id
        existing = self._runtime.proposal_store.load_active(
            identifier,
            projection,
            at=now,
        )
        if (
            existing is None
            and self._runtime.proposal_store.load(identifier, projection)
            is not None
        ):
            active_trigger = trigger_store.rotate_active_proposal(
                fingerprint,
                TRIGGER_REASON_CODE,
                identifier,
                now,
            )
            identifier = active_trigger.proposal_id
            existing = self._runtime.proposal_store.load_active(
                identifier,
                projection,
                at=now,
            )
        deduplicated = active_trigger.deduplicated or existing is not None
        hypotheses = direct_hypotheses(metrics)
        if existing is None:
            proposal = self._new_proposal(
                identifier,
                fingerprint,
                command,
                projection,
                datetime.fromisoformat(active_trigger.created_at),
                hypotheses,
            )
            stored = self._runtime.proposal_store.save(
                proposal,
                ProviderMetadata(
                    provider="DETERMINISTIC_POLICY",
                    model_id="approval-required-policy",
                    input_tokens=0,
                    output_tokens=0,
                    cost_rub="0",
                    duration_ms=0,
                ),
            )
            proposal_hash = stored.canonical_hash
            deduplicated = deduplicated or stored.deduplicated
        else:
            proposal = existing
            proposal_hash = canonical_hash(proposal.as_dict())
        try:
            prepared = self._runtime.state.load_prepared_change(
                proposal.proposal_id
            )
        except ControlRejected as error:
            if error.reason_code != "APPROVAL_NOT_FOUND":
                raise
            prepared = PreparedChange(
                proposal_id=proposal.proposal_id,
                proposal_hash=proposal_hash,
                scope=trusted_scope(self._runtime, request),
                action=SUPPORTED_ACTION,
                current_value=current.state.current_weekly_budget_micros,
                target_value=calculate_relative_target(
                    current.state.current_weekly_budget_micros,
                    command.relative_step_percent,
                ),
                expected_diff=dict(proposal.expected_diff),
                snapshot_id=fingerprint,
                snapshot_generated_at=proposal.created_at,
                direct_watermark=current.provenance[-1].watermark,
                metrika_watermark=evidence.provenance[0].watermark,
                policy_version=str(self._runtime.policy["policy_id"]),
                expected_fingerprint=fingerprint,
                risk="WEEKLY_BUDGET_INCREASE",
            )
            self._runtime.state.register_prepared_change(prepared)
        if (
            prepared.proposal_hash != proposal_hash
            or prepared.expected_fingerprint != proposal.expected_fingerprint
            or prepared.expected_diff != proposal.expected_diff
        ):
            raise ControlRejected(
                "IMMUTABLE_PROPOSAL_CONFLICT",
                "The prepared change does not match the stored proposal.",
            )
        assessment, recommendations = decision_summary(self._runtime)
        public_metrics = result_metrics(metrics, current, prepared.target_value)
        provenance = evidence.provenance + current.provenance
        receipt = self._decision_records.record_module_decision(
            DIRECT_IDENTITY,
            request,
            ModuleDecisionV1(
                outcome="SUCCEEDED",
                reason_codes=(),
                facts=ModuleDecisionFactsV1(
                    metrics=public_metrics,
                    assessment=assessment,
                    recommendations=recommendations,
                    provenance=provenance,
                    hypotheses=hypotheses,
                ),
            ),
        )
        return ModuleResultV1(
            schema_version=MODULE_RESULT_SCHEMA_VERSION,
            run_id="direct-plan-" + receipt.decision_id[:24],
            module=DIRECT_IDENTITY,
            status="SUCCEEDED",
            metrics=public_metrics,
            assessment=assessment,
            recommendations=recommendations,
            proposal=ModuleProposalV1(
                proposal_id=proposal.proposal_id,
                operation_type=ACTION_OPERATION_TYPE,
                status=(
                    "PROPOSED"
                    if self._runtime.environment is ExecutionEnvironment.TEST
                    else "DRY_RUN"
                ),
                snapshot_id=fingerprint,
                reason_code=TRIGGER_REASON_CODE,
                deduplicated=deduplicated,
                cooldown_hours=int(
                    self._runtime.policy["timing"]["cooldown_hours"]
                ),
                observation_window_hours=int(
                    self._runtime.policy["timing"]["observation_window_hours"]
                ),
                hypotheses=hypotheses,
            ),
            execution_result=None,
            provenance=provenance,
            warnings=(),
            errors=(),
            decision_record_ref=receipt.reference,
            hypotheses=hypotheses,
        )

    def _policy_rejected(
        self,
        context: DirectActionContext,
    ) -> ModuleResultV1:
        current = context.current
        metrics = context.metrics
        command = context.request.direct_action_command
        assert isinstance(command, PlanDirectActionCommandV1)
        target = calculate_relative_target(
            current.state.current_weekly_budget_micros,
            command.relative_step_percent,
        )
        public_metrics = result_metrics(metrics, current, target)
        assessment = ModuleAssessmentV1(
            summary=(
                "Validated evidence does not satisfy the deterministic "
                "budget-increase policy."
            ),
            data_quality_status="READY",
            confidence_status="READY",
        )
        recommendations = (
            ModuleRecommendationV1(
                code="KEEP_CURRENT_BUDGET",
                summary="Keep the current weekly budget.",
                rationale=(
                    "The shared deterministic policy rejected the requested "
                    "increase."
                ),
                executable=False,
            ),
        )
        provenance = (
            context.evidence.provenance + context.current.provenance
        )
        receipt = self._decision_records.record_module_decision(
            DIRECT_IDENTITY,
            context.request,
            ModuleDecisionV1(
                outcome="BLOCKED",
                reason_codes=("ACTION_POLICY_REJECTED",),
                facts=ModuleDecisionFactsV1(
                    metrics=public_metrics,
                    assessment=assessment,
                    recommendations=recommendations,
                    provenance=provenance,
                ),
            ),
        )
        return ModuleResultV1(
            schema_version=MODULE_RESULT_SCHEMA_VERSION,
            run_id="direct-plan-" + receipt.decision_id[:24],
            module=DIRECT_IDENTITY,
            status="BLOCKED",
            metrics=public_metrics,
            assessment=assessment,
            recommendations=recommendations,
            proposal=None,
            execution_result=None,
            provenance=provenance,
            warnings=(),
            errors=(
                ModuleErrorV1(
                    code="ACTION_POLICY_REJECTED",
                    message=(
                        "Validated evidence does not authorize the requested "
                        "Direct action."
                    ),
                    field="direct_action_command",
                    retryable=False,
                ),
            ),
            decision_record_ref=receipt.reference,
        )

    def _new_proposal(
        self,
        identifier: str,
        fingerprint: str,
        command: PlanDirectActionCommandV1,
        projection: Mapping[str, object],
        now: datetime,
        hypotheses: Tuple[ModuleHypothesisV1, ...],
    ) -> OptimizationProposalV1:
        return OptimizationProposalV1.from_mapping(
            {
                "proposal_id": identifier,
                "proposal_version": "optimization-proposal-v1",
                "run_id": "direct-plan-" + identifier[-24:],
                "snapshot_id": fingerprint,
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=30)).isoformat(),
                "status": "EFFECTIVE",
                "observed_facts": [
                    "BUDGET_UTILIZATION_AT_OR_ABOVE_THRESHOLD"
                ],
                "hypotheses": [
                    {
                        "rank": hypothesis.rank,
                        "code": hypothesis.code,
                    }
                    for hypothesis in hypotheses
                ],
                "actions": [
                    {
                        "action": command.action,
                        "parameters": {},
                        "dependencies": ["APPROVAL_REQUIRED"],
                        "limits": ["MAXIMUM_STEP_PERCENT"],
                        "rollback_conditions": ["CPA_WORSE"],
                    }
                ],
                "evidence_fields": [
                    "budget_utilization",
                    "policy_limits",
                ],
                "expected_effect_direction": "POSITIVE",
                "minimum_observation_window_hours": int(
                    self._runtime.policy["timing"]["observation_window_hours"]
                ),
                "risks": ["MONETARY_EXPOSURE"],
                "preconditions": [
                    "FINGERPRINT_MATCH",
                    "READBACK_REQUIRED",
                ],
                "rollback_condition": "CPA_WORSE",
                "missing_data_requests": [],
                "expected_diff": {
                    "operation": command.action,
                    "relative_step_percent": command.relative_step_percent,
                },
                "expected_fingerprint": fingerprint,
                "explanation_ru": (
                    "Предложено увеличить недельный бюджет в пределах "
                    "детерминированной политики."
                ),
            },
            projection,
        )
