"""Standalone Metrika analysis over the public module contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Tuple

from mox_adv.metrika_metrics import calculate_metrika_metrics
from mox_adv.metrika_provider import (
    AuthorizedMetrikaReadProviderV1,
    MetrikaObservationReaderV1,
    MetrikaProviderUnavailable,
    MetrikaReadAuthorizationError,
)
from mox_adv.module_analysis import (
    failed_provider_read,
    normalized_utc_now,
    terminal_module_result,
    validate_closed_period,
)
from mox_adv.module_api.v1 import (
    MODULE_RESULT_SCHEMA_VERSION,
    MetricValueV1,
    ModuleAssessmentV1,
    ModuleDecisionFactsV1,
    ModuleDecisionRecordStoreV1,
    ModuleDecisionV1,
    ModuleErrorV1,
    ModuleIdentityV1,
    ModuleRecommendationV1,
    ModuleRequestV1,
    ModuleResultV1,
    ModuleWarningV1,
)

METRIKA_IDENTITY = ModuleIdentityV1(
    module_id="YANDEX_METRIKA",
    module_version="1.0.0",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StandaloneMetrikaAnalysisV1:
    """Validate one source, calculate metrics, and record a safe conclusion."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        decision_records: ModuleDecisionRecordStoreV1,
        provider_reader: Optional[AuthorizedMetrikaReadProviderV1],
    ) -> None:
        self._clock = clock
        self._decision_records = decision_records
        self._observations = MetrikaObservationReaderV1(provider_reader)
        self._provider_reader_available = provider_reader is not None

    def invoke(self, request: ModuleRequestV1) -> ModuleResultV1:
        error = self._validate_request(request)
        if error is not None:
            return terminal_module_result(
                module=METRIKA_IDENTITY,
                request=request,
                status="REJECTED",
                error=error,
            )
        try:
            now = normalized_utc_now(self._clock, module_name="Metrika")
            validate_closed_period(request, now, module_name="Metrika")
            observation = self._observations.read(request, now)
        except MetrikaReadAuthorizationError as authorization_error:
            return terminal_module_result(
                module=METRIKA_IDENTITY,
                request=request,
                status="REJECTED",
                error=ModuleErrorV1(
                    code="METRIKA_SCOPE_REJECTED",
                    message=str(authorization_error),
                    field="scope",
                    retryable=False,
                ),
            )
        except MetrikaProviderUnavailable:
            return failed_provider_read(
                module=METRIKA_IDENTITY,
                request=request,
                error_code="METRIKA_PROVIDER_READ_FAILED",
                message="The authorized Metrika read failed before analysis.",
            )
        except ValueError as error_value:
            return terminal_module_result(
                module=METRIKA_IDENTITY,
                request=request,
                status="REJECTED",
                error=ModuleErrorV1(
                    code="METRIKA_EVIDENCE_REJECTED",
                    message=str(error_value),
                    field="external_evidence",
                    retryable=False,
                ),
            )

        calculated = calculate_metrika_metrics(
            visits=observation.visits,
            goal_visits=observation.goal_visits,
        )
        metrics = (
            MetricValueV1("visits", calculated["visits"], "COUNT"),
            MetricValueV1(
                "goal_visits",
                calculated["goal_visits"],
                "COUNT",
            ),
            MetricValueV1(
                "conversion_rate_percent",
                calculated["conversion_rate_percent"],
                "PERCENT",
            ),
        )
        warnings = self._warnings(
            goal_visits=observation.goal_visits,
            observed_at=observation.observed_at,
            now=now,
        )
        confidence_status = self._confidence_status(warnings)
        recommendation = ModuleRecommendationV1(
            code="CAMPAIGN_CONTEXT_REQUIRED",
            summary="Supply campaign spend and state for a financial conclusion.",
            rationale=(
                "Metrika conversion evidence is valid, but campaign context "
                "is required before recommending a financial action."
            ),
            executable=False,
        )
        assessment = ModuleAssessmentV1(
            summary=(
                "Metrika conversion performance was calculated, but campaign "
                "spend and state are unavailable."
            ),
            data_quality_status="PARTIAL",
            confidence_status=confidence_status,
        )
        receipt = self._decision_records.record_module_decision(
            METRIKA_IDENTITY,
            request,
            ModuleDecisionV1(
                outcome="PARTIAL",
                reason_codes=tuple(item.code for item in warnings),
                facts=ModuleDecisionFactsV1(
                    metrics=metrics,
                    assessment=assessment,
                    recommendations=(recommendation,),
                    provenance=(observation.provenance,),
                ),
            ),
        )
        return ModuleResultV1(
            schema_version=MODULE_RESULT_SCHEMA_VERSION,
            run_id="metrika-" + receipt.decision_id[:24],
            module=METRIKA_IDENTITY,
            status="PARTIAL",
            metrics=metrics,
            assessment=assessment,
            recommendations=(recommendation,),
            proposal=None,
            execution_result=None,
            provenance=(observation.provenance,),
            warnings=warnings,
            errors=(),
            decision_record_ref=receipt.reference,
        )

    def _validate_request(
        self,
        request: ModuleRequestV1,
    ) -> Optional[ModuleErrorV1]:
        if (
            request.operation.kind != "ANALYZE"
            or request.operation.operation_type != "ANALYZE_PERFORMANCE"
        ):
            return ModuleErrorV1(
                code="METRIKA_OPERATION_UNSUPPORTED",
                message=(
                    "Standalone Metrika analysis supports ANALYZE_PERFORMANCE."
                ),
                field="operation",
                retryable=False,
            )
        if request.scope.counter_id is None or request.scope.goal_id is None:
            return ModuleErrorV1(
                code="METRIKA_SCOPE_REJECTED",
                message="Standalone Metrika analysis requires a counter and goal.",
                field="scope",
                retryable=False,
            )
        if request.period.timezone != "UTC":
            return ModuleErrorV1(
                code="METRIKA_EVIDENCE_REJECTED",
                message="Standalone Metrika analysis requires a UTC period.",
                field="period.timezone",
                retryable=False,
            )
        if request.external_evidence is None and not self._provider_reader_available:
            return ModuleErrorV1(
                code="METRIKA_PROVIDER_READER_UNAVAILABLE",
                message="No authorized Metrika provider reader is configured.",
                field="connection_ref",
                retryable=False,
            )
        return None

    @staticmethod
    def _warnings(
        *,
        goal_visits: int,
        observed_at: datetime,
        now: datetime,
    ) -> Tuple[ModuleWarningV1, ...]:
        warnings = [
            ModuleWarningV1(
                code="CAMPAIGN_SPEND_UNAVAILABLE",
                message=(
                    "Campaign spend was not supplied, so financial metrics "
                    "and proposals are unavailable."
                ),
            ),
            ModuleWarningV1(
                code="CAMPAIGN_STATE_UNAVAILABLE",
                message=(
                    "Campaign state was not supplied, so no campaign action "
                    "can be evaluated."
                ),
            ),
        ]
        if goal_visits < 3:
            warnings.append(
                ModuleWarningV1(
                    code="INSUFFICIENT_SAMPLE",
                    message=(
                        "At least three goal visits are required for a "
                        "performance conclusion."
                    ),
                )
            )
        if now - observed_at > timedelta(hours=6):
            warnings.append(
                ModuleWarningV1(
                    code="METRIKA_DATA_STALE",
                    message=(
                        "Metrika evidence is older than the supported "
                        "six-hour freshness window."
                    ),
                )
            )
        return tuple(warnings)

    @staticmethod
    def _confidence_status(warnings: Tuple[ModuleWarningV1, ...]) -> str:
        codes = {item.code for item in warnings}
        if "INSUFFICIENT_SAMPLE" in codes:
            return "INSUFFICIENT_DATA"
        if "METRIKA_DATA_STALE" in codes:
            return "STALE_DATA"
        return "READY"
