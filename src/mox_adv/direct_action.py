"""Standalone Direct action orchestration over the public module contract."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Callable, Optional, Tuple

from mox_adv.control_state import ControlRejected
from mox_adv.direct_action_common import calculated_metrics
from mox_adv.direct_action_execution import DirectActionExecutionV1
from mox_adv.direct_action_planning import DirectActionPlanningV1
from mox_adv.direct_action_runtime import DirectActionRuntimeV1
from mox_adv.direct_analysis import DIRECT_IDENTITY
from mox_adv.direct_provider import (
    AuthorizedDirectReadProviderV1,
    DirectObservationReaderV1,
    DirectObservationV1,
    DirectProviderUnavailable,
    DirectReadAuthorizationError,
)
from mox_adv.module_analysis import (
    normalized_utc_now,
    terminal_module_result,
    validate_closed_period,
)
from mox_adv.module_api.v1 import (
    ExecuteDirectActionCommandV1,
    ModuleDecisionRecordStoreV1,
    ModuleErrorV1,
    ModuleRequestV1,
    ModuleResultV1,
    PlanDirectActionCommandV1,
)
from mox_adv.recommend_contracts import (
    ProposalConflictError,
    SchemaValidationError,
)


class StandaloneDirectActionV1:
    """Validate evidence, reread Direct, then route plan or execution."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        decision_records: ModuleDecisionRecordStoreV1,
        provider_reader: Optional[AuthorizedDirectReadProviderV1],
        runtime: DirectActionRuntimeV1,
    ) -> None:
        self._clock = clock
        self._provider_reader = provider_reader
        self._observations = DirectObservationReaderV1(provider_reader)
        self._planning = DirectActionPlanningV1(runtime, decision_records)
        self._execution = DirectActionExecutionV1(runtime, decision_records)

    def invoke(self, request: ModuleRequestV1) -> ModuleResultV1:
        error = self._validate_request(request)
        if error is not None:
            return terminal_module_result(
                module=DIRECT_IDENTITY,
                request=request,
                status="REJECTED",
                error=error,
            )
        try:
            now = normalized_utc_now(self._clock, module_name="Direct")
            validate_closed_period(request, now, module_name="Direct")
            evidence, current = self._validated_evidence_and_current_state(
                request,
                now,
            )
            metrics = calculated_metrics(evidence, current, now)
            if isinstance(
                request.direct_action_command,
                PlanDirectActionCommandV1,
            ):
                return self._planning.plan(
                    request,
                    now,
                    evidence,
                    current,
                    metrics,
                )
            assert isinstance(
                request.direct_action_command,
                ExecuteDirectActionCommandV1,
            )
            return self._execution.execute(
                request,
                now,
                evidence,
                current,
                metrics,
            )
        except DirectReadAuthorizationError as error:
            return self._rejected(
                request,
                "DIRECT_SCOPE_REJECTED",
                str(error),
                "scope",
            )
        except DirectProviderUnavailable:
            return self._failed(
                request,
                "DIRECT_PROVIDER_READ_FAILED",
                "The authorized Direct reread failed before the action decision.",
            )
        except (ValueError, SchemaValidationError) as error:
            return self._rejected(
                request,
                "DIRECT_EVIDENCE_REJECTED",
                str(error),
                "external_evidence",
            )
        except ProposalConflictError as error:
            return self._blocked(
                request,
                "IMMUTABLE_PROPOSAL_CONFLICT",
                str(error),
            )
        except ControlRejected as error:
            return self._blocked(request, error.reason_code, str(error))

    def _validate_request(
        self,
        request: ModuleRequestV1,
    ) -> Optional[ModuleErrorV1]:
        if request.operation.operation_type not in {
            "PLAN_OPTIMIZATION",
            "APPLY_OPTIMIZATION",
        }:
            return ModuleErrorV1(
                code="DIRECT_OPERATION_UNSUPPORTED",
                message=(
                    "Standalone Direct actions support PLAN_OPTIMIZATION "
                    "and APPLY_OPTIMIZATION."
                ),
                field="operation",
                retryable=False,
            )
        if request.direct_action_command is None:
            return ModuleErrorV1(
                code="DIRECT_ACTION_COMMAND_REQUIRED",
                message="A typed Direct action command is required.",
                field="direct_action_command",
                retryable=False,
            )
        if request.scope.account_id is None or request.scope.campaign_id is None:
            return ModuleErrorV1(
                code="DIRECT_SCOPE_REJECTED",
                message="Standalone Direct actions require an account and campaign.",
                field="scope",
                retryable=False,
            )
        if request.period.timezone != "UTC":
            return ModuleErrorV1(
                code="DIRECT_EVIDENCE_REJECTED",
                message="Standalone Direct actions require a UTC period.",
                field="period.timezone",
                retryable=False,
            )
        if request.external_evidence is None:
            return ModuleErrorV1(
                code="DIRECT_EVIDENCE_REJECTED",
                message="Standalone Direct actions require typed customer evidence.",
                field="external_evidence",
                retryable=False,
            )
        if self._provider_reader is None:
            return ModuleErrorV1(
                code="DIRECT_PROVIDER_READER_UNAVAILABLE",
                message=(
                    "An authorized Direct reader is required to reread the target."
                ),
                field="connection_ref",
                retryable=False,
            )
        return None

    def _validated_evidence_and_current_state(
        self,
        request: ModuleRequestV1,
        now: datetime,
    ) -> Tuple[DirectObservationV1, DirectObservationV1]:
        evidence = self._observations.read(request, now)
        current = self._observations.read(
            replace(request, external_evidence=None),
            now,
        )
        if evidence.conversions is None:
            raise ValueError("Direct action evidence requires conversions.")
        return evidence, current

    @staticmethod
    def _rejected(
        request: ModuleRequestV1,
        code: str,
        message: str,
        field: str,
    ) -> ModuleResultV1:
        return terminal_module_result(
            module=DIRECT_IDENTITY,
            request=request,
            status="REJECTED",
            error=ModuleErrorV1(
                code=code,
                message=message,
                field=field,
                retryable=False,
            ),
        )

    @staticmethod
    def _failed(
        request: ModuleRequestV1,
        code: str,
        message: str,
    ) -> ModuleResultV1:
        return terminal_module_result(
            module=DIRECT_IDENTITY,
            request=request,
            status="FAILED",
            error=ModuleErrorV1(
                code=code,
                message=message,
                field=None,
                retryable=True,
            ),
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


__all__ = [
    "DirectActionRuntimeV1",
    "StandaloneDirectActionV1",
]
