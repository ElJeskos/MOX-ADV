"""Standalone Metrika analysis over the public module contract."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Tuple
from zoneinfo import ZoneInfo

from mox_adv.analytics import calculate_metrika_metrics
from mox_adv.metrika_provider import (
    AuthorizedMetrikaReadProviderV1,
    MetrikaObservationReaderV1,
    MetrikaProviderUnavailable,
    MetrikaReadAuthorizationError,
)
from mox_adv.module_api.v1 import (
    MODULE_RESULT_SCHEMA_VERSION,
    MetricValueV1,
    ModuleAssessmentV1,
    ModuleDecisionRecordStoreV1,
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
            return self._rejected(request, *error)
        try:
            now = self._normalized_now()
            self._validate_period_is_closed(request, now)
            observation = self._observations.read(request, now)
        except MetrikaReadAuthorizationError as authorization_error:
            return self._rejected(
                request,
                "METRIKA_SCOPE_REJECTED",
                str(authorization_error),
                "scope",
            )
        except MetrikaProviderUnavailable:
            return self._failed_provider_read(request)
        except ValueError as error_value:
            return self._rejected(
                request,
                "METRIKA_EVIDENCE_REJECTED",
                str(error_value),
                "external_evidence",
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
            outcome="PARTIAL",
            reason_codes=tuple(item.code for item in warnings),
            facts={
                "metrics": [item.as_dict() for item in metrics],
                "assessment": assessment.as_dict(),
                "recommendations": [recommendation.as_dict()],
                "provenance": [observation.provenance.as_dict()],
            },
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
    ) -> Optional[Tuple[str, str, Optional[str]]]:
        if (
            request.operation.kind != "ANALYZE"
            or request.operation.operation_type != "ANALYZE_PERFORMANCE"
        ):
            return (
                "METRIKA_OPERATION_UNSUPPORTED",
                "Standalone Metrika analysis supports ANALYZE_PERFORMANCE.",
                "operation",
            )
        if request.scope.counter_id is None or request.scope.goal_id is None:
            return (
                "METRIKA_SCOPE_REJECTED",
                "Standalone Metrika analysis requires a counter and goal.",
                "scope",
            )
        if request.external_evidence is None and not self._provider_reader_available:
            return (
                "METRIKA_PROVIDER_READER_UNAVAILABLE",
                "No authorized Metrika provider reader is configured.",
                "connection_ref",
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
        elif now - observed_at > timedelta(hours=6):
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

    def _normalized_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("The Metrika module clock must be timezone-aware.")
        return now.astimezone(timezone.utc)

    @staticmethod
    def _validate_period_is_closed(
        request: ModuleRequestV1,
        now: datetime,
    ) -> None:
        local_date = now.astimezone(ZoneInfo(request.period.timezone)).date()
        if datetime.fromisoformat(request.period.end_date).date() >= local_date:
            raise ValueError("The requested Metrika period must be closed.")

    @classmethod
    def _rejected(
        cls,
        request: ModuleRequestV1,
        code: str,
        message: str,
        field: Optional[str],
    ) -> ModuleResultV1:
        return ModuleResultV1(
            schema_version=MODULE_RESULT_SCHEMA_VERSION,
            run_id=cls._bounded_run_id("rejected", request),
            module=METRIKA_IDENTITY,
            status="REJECTED",
            metrics=(),
            assessment=None,
            recommendations=(),
            proposal=None,
            execution_result=None,
            provenance=(),
            warnings=(),
            errors=(
                ModuleErrorV1(
                    code=code,
                    message=message,
                    field=field,
                    retryable=False,
                ),
            ),
            decision_record_ref=None,
        )

    @classmethod
    def _failed_provider_read(
        cls,
        request: ModuleRequestV1,
    ) -> ModuleResultV1:
        return ModuleResultV1(
            schema_version=MODULE_RESULT_SCHEMA_VERSION,
            run_id=cls._bounded_run_id("failed", request),
            module=METRIKA_IDENTITY,
            status="FAILED",
            metrics=(),
            assessment=None,
            recommendations=(),
            proposal=None,
            execution_result=None,
            provenance=(),
            warnings=(),
            errors=(
                ModuleErrorV1(
                    code="METRIKA_PROVIDER_READ_FAILED",
                    message=("The authorized Metrika read failed before analysis."),
                    field="connection_ref",
                    retryable=True,
                ),
            ),
            decision_record_ref=None,
        )

    @staticmethod
    def _bounded_run_id(prefix: str, request: ModuleRequestV1) -> str:
        digest = hashlib.sha256(request.idempotency_key.encode("utf-8")).hexdigest()[
            :24
        ]
        return prefix + "-metrika-" + digest
