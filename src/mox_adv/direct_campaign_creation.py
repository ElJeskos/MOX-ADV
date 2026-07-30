"""Headless Direct adapter over the existing campaign-creation saga."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, cast

from mox_adv.campaign_lifecycle import (
    CampaignCreationRequest,
    CampaignDraftSafetyBindings,
    CampaignLifecycleService,
    CampaignSagaState,
    CampaignSagaStep,
    CampaignSagaStore,
    LifecycleRejected,
)
from mox_adv.direct_analysis import DIRECT_IDENTITY
from mox_adv.direct_management import (
    DirectManagementConnectorV1,
    FakeDirectManagementAdapter,
)
from mox_adv.environment import (
    ExecutionEnvironment,
    parse_execution_environment,
)
from mox_adv.module_api.v1 import (
    MODULE_RESULT_SCHEMA_VERSION,
    CampaignCreatedObjectV1,
    CampaignCreationOutcomeV1,
    CampaignReadbackV1,
    CreateCampaignCommandV1,
    ModuleAssessmentV1,
    ModuleDecisionFactsV1,
    ModuleDecisionRecordStoreV1,
    ModuleDecisionV1,
    ModuleErrorV1,
    ModuleExecutionResultV1,
    ModuleRequestV1,
    ModuleResultV1,
    ModuleStatus,
)


@dataclass(frozen=True)
class DirectCampaignCreationRuntimeV1:
    """Bind campaign creation to one stored connection and sealed TEST adapter."""

    connection_id: str
    account_id: str
    policy: Mapping[str, Any]
    store: CampaignSagaStore
    safety_bindings: CampaignDraftSafetyBindings
    test_adapter: FakeDirectManagementAdapter
    environment: ExecutionEnvironment

    def __post_init__(self) -> None:
        trusted_environment = parse_execution_environment(self.environment)
        object.__setattr__(self, "environment", trusted_environment)
        if trusted_environment is not ExecutionEnvironment.TEST:
            raise ValueError(
                "Campaign creation is available only through the TEST runtime."
            )
        if type(self.test_adapter) is not FakeDirectManagementAdapter:
            raise ValueError(
                "Campaign creation accepts only the sealed socket-free "
                "Direct TEST adapter."
            )
        if not self.connection_id or not self.account_id:
            raise ValueError(
                "Campaign creation requires a stored connection and account."
            )

    def execute(
        self,
        connection_id: str,
        account_id: str,
        command: CreateCampaignCommandV1,
        now: datetime,
    ) -> CampaignCreationOutcomeV1:
        if connection_id != self.connection_id or account_id != self.account_id:
            raise DirectCampaignCreationAuthorizationError(
                "The stored TEST connection does not authorize this account."
            )
        legacy_request = CampaignCreationRequest(
            run_id=command.run_id,
            execution_key=command.execution_key,
            proposal_id=command.proposal_id,
            approval_id=command.approval_id,
            account=account_id,
            credential_profile="DIRECT_PILOT_WRITE",
            reservation_id=command.reservation_id,
            draft=command.draft,
        )
        service = CampaignLifecycleService(
            policy=self.policy,
            store=self.store,
            connector=DirectManagementConnectorV1(
                self.policy,
                self.test_adapter,
                self.store,
                environment=ExecutionEnvironment.TEST,
            ),
            safety_bindings=self.safety_bindings,
        )
        result = service.execute(legacy_request, now)
        status = {
            CampaignSagaState.APPLIED: "APPLIED",
            CampaignSagaState.ALREADY_PROCESSED: "NO_CHANGE",
            CampaignSagaState.UNKNOWN_RESULT: "UNKNOWN_RESULT",
            CampaignSagaState.PARTIALLY_APPLIED: "PARTIALLY_APPLIED",
            CampaignSagaState.COMPENSATION_REQUIRED: "COMPENSATION_REQUIRED",
            CampaignSagaState.FAILED: "FAILED",
        }[result.status]
        full_readback = self.store.step_response(
            command.execution_key,
            CampaignSagaStep.FULL_READBACK,
        )
        return CampaignCreationOutcomeV1.create(
            execution_key=command.execution_key,
            status=status,
            saga_status=result.status.value,
            completed_steps=tuple(step.value for step in result.completed_steps),
            created_objects=tuple(
                CampaignCreatedObjectV1(
                    service=item.service.value,
                    object_id=item.object_id,
                    actual_type=item.actual_type,
                    compensated=item.compensated,
                )
                for item in self.store.created_object_evidence(command.run_id)
            ),
            readback=(
                None
                if full_readback is None
                else CampaignReadbackV1.from_dict(full_readback)
            ),
            detail=result.detail,
        )


class DirectCampaignCreationAuthorizationError(ValueError):
    """A stored TEST connection does not authorize campaign creation."""


class StandaloneDirectCampaignCreationV1:
    """Invoke one typed campaign-creation command through the module contract."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        decision_records: ModuleDecisionRecordStoreV1,
        runtime: DirectCampaignCreationRuntimeV1,
    ) -> None:
        self._clock = clock
        self._decision_records = decision_records
        self._runtime = runtime

    def invoke(self, request: ModuleRequestV1) -> ModuleResultV1:
        command = request.campaign_creation_command
        if command is None:
            return self._rejected(
                request,
                "DIRECT_CAMPAIGN_CREATION_COMMAND_REQUIRED",
                "A typed campaign creation command is required.",
            )
        if request.scope.account_id is None:
            return self._rejected(
                request,
                "DIRECT_CAMPAIGN_SCOPE_REJECTED",
                "Campaign creation requires an account scope.",
            )
        try:
            outcome = self._runtime.execute(
                request.connection_ref.connection_id,
                request.scope.account_id,
                command,
                self._now(),
            )
        except DirectCampaignCreationAuthorizationError:
            return self._rejected(
                request,
                "DIRECT_CAMPAIGN_SCOPE_REJECTED",
                "The stored TEST connection does not authorize this account.",
            )
        except LifecycleRejected as error:
            code = str(error).split(":", 1)[0]
            return self._rejected(
                request,
                code,
                "The campaign creation request was rejected before execution.",
            )
        return self._result(request, outcome)

    def _result(
        self,
        request: ModuleRequestV1,
        outcome: CampaignCreationOutcomeV1,
    ) -> ModuleResultV1:
        succeeded = outcome.status in {"APPLIED", "NO_CHANGE"}
        assessment = ModuleAssessmentV1(
            summary=(
                "The typed campaign creation action completed in the TEST contour."
                if succeeded
                else "Campaign creation requires reconciliation or manual review."
            ),
            data_quality_status="READY" if succeeded else "INCOMPATIBLE",
            confidence_status="READY" if succeeded else "INSUFFICIENT_DATA",
        )
        module_status = cast(
            ModuleStatus,
            "SUCCEEDED" if succeeded else "FAILED",
        )
        reason_codes = (outcome.status,)
        receipt = self._decision_records.record_module_decision(
            DIRECT_IDENTITY,
            request,
            ModuleDecisionV1(
                outcome=module_status,
                reason_codes=reason_codes,
                facts=ModuleDecisionFactsV1(
                    metrics=(),
                    assessment=assessment,
                    recommendations=(),
                    provenance=(),
                    campaign_creation_outcome=outcome,
                ),
            ),
        )
        provider_reference = next(
            (
                item.object_id
                for item in outcome.created_objects
                if item.service == "Campaigns" and not item.compensated
            ),
            None,
        )
        errors = (
            ()
            if succeeded
            else (
                ModuleErrorV1(
                    code=outcome.status,
                    message=(
                        outcome.detail
                        or "Campaign creation did not reach a successful state."
                    ),
                    field=None,
                    retryable=False,
                ),
            )
        )
        return ModuleResultV1(
            schema_version=MODULE_RESULT_SCHEMA_VERSION,
            run_id=request.idempotency_key,
            module=DIRECT_IDENTITY,
            status=module_status,
            metrics=(),
            assessment=assessment,
            recommendations=(),
            proposal=None,
            execution_result=ModuleExecutionResultV1(
                execution_id=outcome.execution_key,
                operation_type="CREATE_CAMPAIGN",
                status=outcome.status,
                applied=outcome.status == "APPLIED",
                provider_reference=provider_reference,
            ),
            provenance=(),
            warnings=(),
            errors=errors,
            decision_record_ref=receipt.reference,
            campaign_creation_outcome=outcome,
        )

    def _rejected(
        self,
        request: ModuleRequestV1,
        code: str,
        message: str,
    ) -> ModuleResultV1:
        assessment = ModuleAssessmentV1(
            summary="Campaign creation was rejected before execution.",
            data_quality_status="INCOMPATIBLE",
            confidence_status="INSUFFICIENT_DATA",
        )
        receipt = self._decision_records.record_module_decision(
            DIRECT_IDENTITY,
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
            module=DIRECT_IDENTITY,
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
            raise ValueError("Campaign creation clock must be timezone-aware.")
        return value.astimezone(timezone.utc)


__all__ = [
    "DirectCampaignCreationAuthorizationError",
    "DirectCampaignCreationRuntimeV1",
    "StandaloneDirectCampaignCreationV1",
]
