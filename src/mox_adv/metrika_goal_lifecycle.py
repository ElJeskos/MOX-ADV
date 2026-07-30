"""Headless adapter over the existing candidate-goal lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from mox_adv.goal_contracts import (
    GoalCandidateRecord,
    GoalLifecycleRejected,
)
from mox_adv.goal_evidence import GoalEventEvidence, GoalTechnicalEvidence
from mox_adv.goal_service import GoalLifecycleService
from mox_adv.module_api.v1 import (
    MODULE_RESULT_SCHEMA_VERSION,
    GoalEventEvidenceV1,
    GoalLifecycleCommandV1,
    GoalLifecycleEvidenceOutcomeV1,
    GoalLifecycleOutcomeV1,
    ModuleAssessmentV1,
    ModuleDecisionFactsV1,
    ModuleDecisionRecordStoreV1,
    ModuleDecisionV1,
    ModuleErrorV1,
    ModuleExecutionResultV1,
    ModuleIdentityV1,
    ModuleRequestV1,
    ModuleResultV1,
)


class MetrikaGoalLifecycleAuthorizationError(ValueError):
    """A stored TEST connection does not authorize the requested counter."""


class AuthorizedMetrikaGoalLifecycleProviderV1(Protocol):
    """Resolve a stored test connection and run one typed lifecycle action."""

    def manage_goal_candidate(
        self,
        connection_id: str,
        counter_id: str,
        command: GoalLifecycleCommandV1,
        now: datetime,
    ) -> GoalLifecycleOutcomeV1: ...


@dataclass(frozen=True)
class BoundMetrikaGoalLifecycleProviderV1:
    """Bind the lifecycle to one stored test connection and test counter."""

    connection_id: str
    counter_id: str
    credential_profile: str
    lifecycle: GoalLifecycleService

    def manage_goal_candidate(
        self,
        connection_id: str,
        counter_id: str,
        command: GoalLifecycleCommandV1,
        now: datetime,
    ) -> GoalLifecycleOutcomeV1:
        if connection_id != self.connection_id or counter_id != self.counter_id:
            raise MetrikaGoalLifecycleAuthorizationError(
                "The stored test connection does not authorize this counter."
            )
        action = command.action
        values = command.values
        technical_evidence = None
        if action == "CREATE_CANDIDATE":
            candidate = self.lifecycle.create_candidate(
                run_id=values["run_id"],
                proposal_id=values["proposal_id"],
                reservation_id=values["reservation_id"],
                authority_id=values["authority_id"],
                counter_id=counter_id,
                credential_profile=self.credential_profile,
                payload=values["candidate"].as_dict(),
                now=now,
            )
            lifecycle_status = "CANDIDATE"
        elif action == "PUBLISH_EVENT":
            self.lifecycle.publish_candidate_event(
                values["candidate_id"],
                authority_id=values["authority_id"],
                site_zone=values["site_zone"],
                expected_version=values["expected_version"],
                now=now,
            )
            candidate = self.lifecycle.store.load_candidate(values["candidate_id"])
            lifecycle_status = "EVENT_PUBLISHED"
        elif action == "VERIFY_DELIVERY":
            technical_evidence = self.lifecycle.verify_candidate_delivery(
                values["candidate_id"],
                self._event_evidence(values["event_evidence"]),
                now=now,
            )
            candidate = self.lifecycle.store.load_candidate(values["candidate_id"])
            lifecycle_status = (
                "TECHNICALLY_VERIFIED"
                if technical_evidence.delivery_observed
                else "TECHNICALLY_INCONCLUSIVE"
            )
        elif action == "DECIDE_BUSINESS_SEMANTICS":
            candidate = self.lifecycle.decide_business_semantics(
                values["candidate_id"],
                approved=values["approved"],
                reviewer=values["reviewer"],
                now=now,
            )
            lifecycle_status = candidate.status.value
        elif action == "EVALUATE_OPTIMIZATION_ELIGIBILITY":
            candidate = self.lifecycle.evaluate_optimization_eligibility(
                values["candidate_id"],
                observed_at=datetime.fromisoformat(
                    values["observed_at"].replace("Z", "+00:00")
                ),
                sample_clicks=values["sample_clicks"],
                sample_conversions=values["sample_conversions"],
            )
            lifecycle_status = (
                "OPTIMIZATION_ELIGIBLE"
                if candidate.optimization_eligible
                else "OPTIMIZATION_INELIGIBLE"
            )
        else:
            assert action == "CLEANUP_REJECTED_CANDIDATE"
            self.lifecycle.cleanup_rejected_candidate(
                values["candidate_id"],
                run_id=values["run_id"],
            )
            candidate = self.lifecycle.store.load_candidate(values["candidate_id"])
            lifecycle_status = "CLEANED_UP"
        return self._outcome(
            action=action,
            lifecycle_status=lifecycle_status,
            candidate=candidate,
            technical_evidence=technical_evidence,
        )

    @staticmethod
    def _event_evidence(value: GoalEventEvidenceV1) -> GoalEventEvidence:
        return GoalEventEvidence(**value.as_dict())

    @staticmethod
    def _outcome(
        *,
        action: str,
        lifecycle_status: str,
        candidate: GoalCandidateRecord,
        technical_evidence: GoalTechnicalEvidence | None,
    ) -> GoalLifecycleOutcomeV1:
        event_evidence = (
            None
            if technical_evidence is None
            else GoalLifecycleEvidenceOutcomeV1(
                event=technical_evidence.event,
                counter_id=technical_evidence.counter_id,
                emitted_count=technical_evidence.emitted_count,
                duplicate_event_absent=technical_evidence.duplicate_event_absent,
                intercepted_locally=technical_evidence.intercepted_locally,
                real_network_requests=technical_evidence.real_network_requests,
                delivery_observed=technical_evidence.delivery_observed,
                virtual_elapsed_minutes=(
                    technical_evidence.virtual_elapsed_minutes
                ),
                poll_count=technical_evidence.poll_count,
                checked_at=technical_evidence.checked_at,
            )
        )
        return GoalLifecycleOutcomeV1.create(
            action=action,
            lifecycle_status=lifecycle_status,
            candidate_id=candidate.candidate_id,
            goal_id=candidate.goal_id,
            candidate_status=candidate.status.value,
            technical_status=candidate.technical_status.value,
            optimization_eligible=candidate.optimization_eligible,
            cleaned_up=lifecycle_status == "CLEANED_UP",
            event_evidence=event_evidence,
        )


class StandaloneMetrikaGoalLifecycleV1:
    """Return lifecycle decisions through ModuleResultV1 without a UI."""

    def __init__(
        self,
        *,
        identity: ModuleIdentityV1,
        provider: AuthorizedMetrikaGoalLifecycleProviderV1,
        decision_records: ModuleDecisionRecordStoreV1,
        clock: Callable[[], datetime],
    ) -> None:
        self._identity = identity
        self._provider = provider
        self._decision_records = decision_records
        self._clock = clock

    def invoke(self, request: ModuleRequestV1) -> ModuleResultV1:
        assert request.goal_lifecycle_command is not None
        assert request.scope.counter_id is not None
        try:
            outcome = self._provider.manage_goal_candidate(
                request.connection_ref.connection_id,
                request.scope.counter_id,
                request.goal_lifecycle_command,
                self._now(),
            )
        except MetrikaGoalLifecycleAuthorizationError:
            return self._rejected(
                request,
                code="METRIKA_GOAL_SCOPE_REJECTED",
                message=(
                    "The stored test connection does not authorize the "
                    "requested counter."
                ),
            )
        except GoalLifecycleRejected as error:
            reason_code = str(error).split(":", 1)[0]
            return self._rejected(
                request,
                code=reason_code,
                message="The goal lifecycle action was rejected.",
            )

        assessment = ModuleAssessmentV1(
            summary="The typed goal lifecycle action completed in the test contour.",
            data_quality_status="READY",
            confidence_status="READY",
        )
        receipt = self._decision_records.record_module_decision(
            self._identity,
            request,
            ModuleDecisionV1(
                outcome="SUCCEEDED",
                reason_codes=(outcome.lifecycle_status,),
                facts=ModuleDecisionFactsV1(
                    metrics=(),
                    assessment=assessment,
                    recommendations=(),
                    provenance=(),
                    lifecycle_outcome=outcome,
                ),
            ),
        )
        return ModuleResultV1(
            schema_version=MODULE_RESULT_SCHEMA_VERSION,
            run_id=request.idempotency_key,
            module=self._identity,
            status="SUCCEEDED",
            metrics=(),
            assessment=assessment,
            recommendations=(),
            proposal=None,
            execution_result=ModuleExecutionResultV1(
                execution_id=request.idempotency_key,
                operation_type="MANAGE_GOAL_CANDIDATE",
                status="APPLIED",
                applied=True,
                provider_reference=outcome.candidate_id,
            ),
            provenance=(),
            warnings=(),
            errors=(),
            decision_record_ref=receipt.reference,
            lifecycle_outcome=outcome,
        )

    def _rejected(
        self,
        request: ModuleRequestV1,
        *,
        code: str,
        message: str,
    ) -> ModuleResultV1:
        assessment = ModuleAssessmentV1(
            summary="The goal lifecycle action was rejected before completion.",
            data_quality_status="INCOMPATIBLE",
            confidence_status="INSUFFICIENT_DATA",
        )
        receipt = self._decision_records.record_module_decision(
            self._identity,
            request,
            ModuleDecisionV1(
                outcome="REJECTED",
                reason_codes=(code,),
                facts=ModuleDecisionFactsV1(
                    metrics=(),
                    assessment=assessment,
                    recommendations=(),
                    provenance=(),
                ),
            ),
        )
        return ModuleResultV1(
            schema_version=MODULE_RESULT_SCHEMA_VERSION,
            run_id=request.idempotency_key,
            module=self._identity,
            status="REJECTED",
            metrics=(),
            assessment=assessment,
            recommendations=(),
            proposal=None,
            execution_result=None,
            provenance=(),
            warnings=(),
            errors=(
                ModuleErrorV1(
                    code=code,
                    message=message,
                    field=None,
                    retryable=False,
                ),
            ),
            decision_record_ref=receipt.reference,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("Goal lifecycle clock must be timezone-aware.")
        return value.astimezone(timezone.utc)
