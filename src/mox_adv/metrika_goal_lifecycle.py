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
    CandidateGoalLifecycleCommandV1,
    CleanupRejectedGoalCommandV1,
    CreateGoalCandidateCommandV1,
    DecideGoalSemanticsCommandV1,
    EvaluateGoalEligibilityCommandV1,
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
    PublishGoalEventCommandV1,
    VerifyGoalDeliveryCommandV1,
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

    def __post_init__(self) -> None:
        try:
            test_counter = self.lifecycle.policy["bindings"]["simulation"][
                "test_counter"
            ]
        except (KeyError, TypeError) as error:
            raise MetrikaGoalLifecycleAuthorizationError(
                "The stored test connection is not bound to a test counter."
            ) from error
        if (
            self.counter_id != test_counter
            or self.credential_profile != "METRIKA_TEST_WRITE"
        ):
            raise MetrikaGoalLifecycleAuthorizationError(
                "The stored connection must use METRIKA_TEST_WRITE for the "
                "configured test counter."
            )

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
        technical_evidence = None
        if isinstance(command, CreateGoalCandidateCommandV1):
            candidate = self.lifecycle.create_candidate(
                run_id=command.run_id,
                proposal_id=command.proposal_id,
                reservation_id=command.reservation_id,
                authority_id=command.authority_id,
                counter_id=counter_id,
                credential_profile=self.credential_profile,
                payload=command.candidate.as_legacy_payload(),
                now=now,
            )
            lifecycle_status = "CANDIDATE"
        else:
            if not isinstance(command, CandidateGoalLifecycleCommandV1):
                raise MetrikaGoalLifecycleAuthorizationError(
                    "The goal lifecycle command type is unsupported."
                )
            candidate = self._bound_candidate(command.candidate_id)
        if isinstance(command, PublishGoalEventCommandV1):
            self.lifecycle.publish_candidate_event(
                command.candidate_id,
                authority_id=command.authority_id,
                site_zone=command.site_zone,
                expected_version=command.expected_version,
                now=now,
            )
            candidate = self._bound_candidate(command.candidate_id)
            lifecycle_status = "EVENT_PUBLISHED"
        elif isinstance(command, VerifyGoalDeliveryCommandV1):
            technical_evidence = self.lifecycle.verify_candidate_delivery(
                command.candidate_id,
                self._event_evidence(command.event_evidence),
                now=now,
            )
            candidate = self._bound_candidate(command.candidate_id)
            lifecycle_status = (
                "TECHNICALLY_VERIFIED"
                if technical_evidence.delivery_observed
                else "TECHNICALLY_INCONCLUSIVE"
            )
        elif isinstance(command, DecideGoalSemanticsCommandV1):
            candidate = self.lifecycle.decide_business_semantics(
                command.candidate_id,
                approved=command.approved,
                reviewer=command.reviewer,
                now=now,
            )
            lifecycle_status = candidate.status.value
        elif isinstance(command, EvaluateGoalEligibilityCommandV1):
            candidate = self.lifecycle.evaluate_optimization_eligibility(
                command.candidate_id,
                observed_at=datetime.fromisoformat(
                    command.observed_at.replace("Z", "+00:00")
                ),
                sample_clicks=command.sample_clicks,
                sample_conversions=command.sample_conversions,
            )
            lifecycle_status = (
                "OPTIMIZATION_ELIGIBLE"
                if candidate.optimization_eligible
                else "OPTIMIZATION_INELIGIBLE"
            )
        elif isinstance(command, CleanupRejectedGoalCommandV1):
            self.lifecycle.cleanup_rejected_candidate(
                command.candidate_id,
                run_id=command.run_id,
            )
            candidate = self._bound_candidate(command.candidate_id)
            lifecycle_status = "CLEANED_UP"
        return self._outcome(
            action=command.action,
            lifecycle_status=lifecycle_status,
            candidate=candidate,
            technical_evidence=technical_evidence,
        )

    def _bound_candidate(self, candidate_id: str) -> GoalCandidateRecord:
        candidate = self.lifecycle.store.load_candidate(candidate_id)
        if candidate.counter_id != self.counter_id:
            raise MetrikaGoalLifecycleAuthorizationError(
                "The stored test connection does not authorize this candidate."
            )
        return candidate

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
                virtual_elapsed_minutes=(technical_evidence.virtual_elapsed_minutes),
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
        if request.goal_lifecycle_command is None:
            return self._rejected(
                request,
                code="METRIKA_GOAL_COMMAND_REQUIRED",
                message="A typed goal lifecycle command is required.",
            )
        if request.scope.counter_id is None:
            return self._rejected(
                request,
                code="METRIKA_GOAL_SCOPE_REJECTED",
                message="A test counter is required.",
            )
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
