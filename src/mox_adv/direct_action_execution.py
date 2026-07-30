"""Approval-bound TEST execution for standalone Direct actions."""

from __future__ import annotations

from mox_adv.approval_execution import (
    ApprovalExecutionService,
    ExecutionFacts,
    ExecutionRequest,
)
from mox_adv.control_state import (
    ControlRejected,
    PreparedChange,
    canonical_hash,
)
from mox_adv.direct_action_common import (
    ACTION_OPERATION_TYPE,
    DirectActionContext,
    age_minutes,
    decision_summary,
    proposal_projection,
    public_execution_status,
    result_metrics,
    state_fingerprint,
    watermark_skew_minutes,
)
from mox_adv.direct_action_runtime import DirectActionRuntimeV1
from mox_adv.direct_analysis import DIRECT_IDENTITY
from mox_adv.module_analysis import terminal_module_result
from mox_adv.module_api.v1 import (
    MODULE_RESULT_SCHEMA_VERSION,
    ExecuteDirectActionCommandV1,
    ModuleDecisionFactsV1,
    ModuleDecisionRecordStoreV1,
    ModuleDecisionV1,
    ModuleErrorV1,
    ModuleExecutionResultV1,
    ModuleRequestV1,
    ModuleResultV1,
)


class DirectActionExecutionV1:
    """Load immutable authority, reread facts, then dispatch through the ledger."""

    def __init__(
        self,
        runtime: DirectActionRuntimeV1,
        decision_records: ModuleDecisionRecordStoreV1,
    ) -> None:
        self._runtime = runtime
        self._decision_records = decision_records

    def execute(
        self,
        context: DirectActionContext,
    ) -> ModuleResultV1:
        request = context.request
        now = context.now
        evidence = context.evidence
        current = context.current
        metrics = context.metrics
        command = request.direct_action_command
        assert isinstance(command, ExecuteDirectActionCommandV1)
        proposal = self._runtime.proposal_store.load_active(
            command.proposal_id,
            proposal_projection(self._runtime, metrics),
            at=now,
        )
        if proposal is None:
            return self._blocked(
                request,
                "APPROVAL_NOT_FOUND",
                "The immutable Direct proposal does not exist or has expired.",
            )
        prepared = self._runtime.state.load_prepared_change(proposal.proposal_id)
        if (
            prepared.proposal_hash != canonical_hash(proposal.as_dict())
            or prepared.expected_diff != proposal.expected_diff
            or prepared.expected_fingerprint != proposal.expected_fingerprint
        ):
            raise ControlRejected(
                "IMMUTABLE_PROPOSAL_CONFLICT",
                "The prepared change does not match the stored proposal.",
            )
        adapter = self._runtime.test_adapter
        if adapter is None:
            return self._blocked(
                request,
                "PRODUCTION_WRITE_FORBIDDEN",
                "No Direct write adapter is present outside TEST.",
            )
        executor = ApprovalExecutionService(
            self._runtime.policy,
            self._runtime.state,
            adapter,
            clock=lambda: now,
            environment=self._runtime.environment,
        )
        try:
            existing = self._runtime.state.load_execution(
                prepared.execution_key()
            )
        except ControlRejected as error:
            if error.reason_code != "EXECUTION_NOT_FOUND":
                raise
            existing = None
        if existing is not None:
            outcome = executor.reconcile(prepared.execution_key())
        else:
            outcome = executor.execute(
                ExecutionRequest(
                    proposal_id=proposal.proposal_id,
                    execution_key=prepared.execution_key(),
                    scope=prepared.scope,
                    facts=self._facts(
                        context,
                        prepared,
                        state_fingerprint(request, current),
                    ),
                )
            )
        status, execution_status, reason_code = public_execution_status(
            outcome.status,
            outcome.reason_code,
        )
        assessment, recommendations = decision_summary(self._runtime)
        public_metrics = result_metrics(
            metrics,
            current,
            prepared.target_value,
        )
        provenance = evidence.provenance + current.provenance
        receipt = self._decision_records.record_module_decision(
            DIRECT_IDENTITY,
            request,
            ModuleDecisionV1(
                outcome=status,
                reason_codes=(() if reason_code is None else (reason_code,)),
                facts=ModuleDecisionFactsV1(
                    metrics=public_metrics,
                    assessment=assessment,
                    recommendations=recommendations,
                    provenance=provenance,
                ),
            ),
        )
        errors = (
            ()
            if status == "SUCCEEDED"
            else (
                ModuleErrorV1(
                    code=reason_code or execution_status,
                    message="The Direct action failed closed.",
                    field=None,
                    retryable=execution_status in {
                        "UNKNOWN_RESULT",
                        "BLOCKED",
                    },
                ),
            )
        )
        return ModuleResultV1(
            schema_version=MODULE_RESULT_SCHEMA_VERSION,
            run_id="direct-execution-" + receipt.decision_id[:24],
            module=DIRECT_IDENTITY,
            status=status,
            metrics=public_metrics,
            assessment=assessment,
            recommendations=recommendations,
            proposal=None,
            execution_result=ModuleExecutionResultV1(
                execution_id=prepared.execution_key(),
                operation_type=ACTION_OPERATION_TYPE,
                status=execution_status,
                applied=execution_status == "APPLIED",
                provider_reference=(
                    None
                    if outcome.observed_value is None
                    else str(outcome.observed_value)
                ),
            ),
            provenance=provenance,
            warnings=(),
            errors=errors,
            decision_record_ref=receipt.reference,
        )

    def _facts(
        self,
        context: DirectActionContext,
        prepared: PreparedChange,
        fingerprint: str,
    ) -> ExecutionFacts:
        now = context.now
        evidence = context.evidence
        current = context.current
        metrics = context.metrics
        assert evidence.conversions is not None
        operational = self._runtime.state.load_operational_execution_facts(
            prepared.scope,
            now,
            cooldown_hours=int(
                self._runtime.policy["timing"]["cooldown_hours"]
            ),
        )
        return ExecutionFacts(
            mode="APPROVAL_REQUIRED",
            automation_enabled=True,
            comparability_status="COMPARABLE",
            confidence_status="READY",
            financial_recommendations_allowed=True,
            direct_age_minutes=age_minutes(now, current.observed_at),
            metrika_age_minutes=age_minutes(now, evidence.observed_at),
            watermark_skew_minutes=watermark_skew_minutes(
                current.provenance[-1].watermark,
                evidence.provenance[0].watermark,
            ),
            clicks=evidence.clicks,
            conversions=evidence.conversions,
            impressions=evidence.impressions,
            spend_rub=evidence.cost_micros // 1_000_000,
            cpa_rub=str(metrics["cpa_rub"]),
            budget_utilization_percent=str(
                metrics["budget_utilization_percent"]
            ),
            ctr_percent=str(metrics["ctr_percent"]),
            campaign_state=current.state.campaign_state,
            campaign_strategy=current.state.strategy,
            current_fingerprint=fingerprint,
            cooldown_active=operational.cooldown_active,
            actions_in_last_24h=operational.actions_in_last_24h,
            cumulative_daily_change_percent=(
                operational.cumulative_daily_change_percent
            ),
            monetary_exposure_rub=(
                abs(prepared.target_value - prepared.current_value)
                // 1_000_000
            ),
            kill_switch_available=operational.kill_switch_available,
        )

    @staticmethod
    def _blocked(
        request: ModuleRequestV1,
        code: str,
        message: str,
    ) -> ModuleResultV1:
        return terminal_module_result(
            module=DIRECT_IDENTITY,
            request=request,
            status="BLOCKED",
            error=ModuleErrorV1(
                code=code,
                message=message,
                field=None,
                retryable=False,
            ),
        )
