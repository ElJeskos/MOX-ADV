"""Standalone Direct analysis over the public module contract."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Literal, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo

from mox_adv.direct_metrics import (
    NOT_APPLICABLE,
    DirectMetric,
    calculate_direct_metrics,
)
from mox_adv.direct_provider import (
    AuthorizedDirectReadProviderV1,
    DirectObservationV1,
    DirectObservationReaderV1,
    DirectProviderUnavailable,
    DirectReadAuthorizationError,
)
from mox_adv.module_api.v1 import (
    MODULE_RESULT_SCHEMA_VERSION,
    MetricValueV1,
    ModuleAssessmentV1,
    ModuleDecisionFactsV1,
    ModuleDecisionRecordStoreV1,
    ModuleDecisionV1,
    ModuleErrorV1,
    ModuleHypothesisV1,
    ModuleIdentityV1,
    ModuleProvenanceV1,
    ModuleRecommendationV1,
    ModuleRequestV1,
    ModuleResultV1,
    ModuleStatus,
    ModuleWarningV1,
)

DIRECT_IDENTITY = ModuleIdentityV1(
    module_id="YANDEX_DIRECT",
    module_version="1.0.0",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StandaloneDirectAnalysisV1:
    """Validate one Direct source, calculate metrics, and record a conclusion."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        decision_records: ModuleDecisionRecordStoreV1,
        provider_reader: Optional[AuthorizedDirectReadProviderV1],
    ) -> None:
        self._clock = clock
        self._decision_records = decision_records
        self._observations = DirectObservationReaderV1(provider_reader)
        self._provider_reader_available = provider_reader is not None

    def invoke(self, request: ModuleRequestV1) -> ModuleResultV1:
        error = self._validate_request(request)
        if error is not None:
            return self._rejected(request, error)
        try:
            now = self._normalized_now()
            self._validate_period_is_closed(request, now)
            observation = self._observations.read(request, now)
        except DirectReadAuthorizationError as authorization_error:
            return self._rejected(
                request,
                ModuleErrorV1(
                    code="DIRECT_SCOPE_REJECTED",
                    message=str(authorization_error),
                    field="scope",
                    retryable=False,
                ),
            )
        except DirectProviderUnavailable:
            return self._failed_provider_read(request)
        except ValueError as error_value:
            return self._rejected(
                request,
                ModuleErrorV1(
                    code="DIRECT_EVIDENCE_REJECTED",
                    message=str(error_value),
                    field="external_evidence",
                    retryable=False,
                ),
            )

        calculated = calculate_direct_metrics(
            impressions=observation.impressions,
            clicks=observation.clicks,
            cost_micros=observation.cost_micros,
            current_weekly_budget_micros=(
                observation.current_weekly_budget_micros
            ),
            budget_period_start=observation.budget_period_start,
            budget_period_end=observation.budget_period_end,
            observed_at=now,
            conversions=(
                -1 if observation.conversions is None else observation.conversions
            ),
        )
        metrics = self._metrics(calculated, observation)
        warnings = self._warnings(
            clicks=observation.clicks,
            conversions=observation.conversions,
            observed_at=observation.observed_at,
            now=now,
        )
        hypotheses = self._hypotheses(calculated)
        recommendations = self._recommendations(calculated, warnings)
        status: ModuleStatus = "PARTIAL" if warnings else "SUCCEEDED"
        assessment = ModuleAssessmentV1(
            summary=self._assessment_summary(warnings),
            data_quality_status=(
                "PARTIAL"
                if {
                    "CONVERSION_CONTEXT_UNAVAILABLE",
                    "DIRECT_DATA_STALE",
                }
                & {item.code for item in warnings}
                else "READY"
            ),
            confidence_status=self._confidence_status(warnings),
        )
        receipt = self._decision_records.record_module_decision(
            DIRECT_IDENTITY,
            request,
            ModuleDecisionV1(
                outcome=status,
                reason_codes=tuple(item.code for item in warnings),
                facts=ModuleDecisionFactsV1(
                    metrics=metrics,
                    assessment=assessment,
                    recommendations=recommendations,
                    provenance=observation.provenance,
                    hypotheses=hypotheses,
                ),
            ),
        )
        return ModuleResultV1(
            schema_version=MODULE_RESULT_SCHEMA_VERSION,
            run_id="direct-" + receipt.decision_id[:24],
            module=DIRECT_IDENTITY,
            status=status,
            metrics=metrics,
            assessment=assessment,
            recommendations=recommendations,
            proposal=None,
            execution_result=None,
            provenance=observation.provenance,
            warnings=warnings,
            errors=(),
            decision_record_ref=receipt.reference,
            hypotheses=hypotheses,
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
                code="DIRECT_OPERATION_UNSUPPORTED",
                message="Standalone Direct analysis supports ANALYZE_PERFORMANCE.",
                field="operation",
                retryable=False,
            )
        if (
            request.scope.account_id is None
            or request.scope.campaign_id is None
        ):
            return ModuleErrorV1(
                code="DIRECT_SCOPE_REJECTED",
                message=(
                    "Standalone Direct analysis requires an account and campaign."
                ),
                field="scope",
                retryable=False,
            )
        if request.period.timezone != "UTC":
            return ModuleErrorV1(
                code="DIRECT_EVIDENCE_REJECTED",
                message="Standalone Direct analysis requires a UTC period.",
                field="period.timezone",
                retryable=False,
            )
        if request.external_evidence is None and not self._provider_reader_available:
            return ModuleErrorV1(
                code="DIRECT_PROVIDER_READER_UNAVAILABLE",
                message="No authorized Direct provider reader is configured.",
                field="connection_ref",
                retryable=False,
            )
        return None

    @staticmethod
    def _metrics(
        calculated: Mapping[str, DirectMetric],
        observation: DirectObservationV1,
    ) -> Tuple[MetricValueV1, ...]:
        values = [
            MetricValueV1("impressions", calculated["impressions"], "COUNT"),
            MetricValueV1("clicks", calculated["clicks"], "COUNT"),
            MetricValueV1(
                "cost_micros",
                calculated["cost_micros"],
                "MICROS_RUB",
            ),
            MetricValueV1(
                "ctr_percent",
                calculated["ctr_percent"],
                "PERCENT",
            ),
            MetricValueV1("cpc_rub", calculated["cpc_rub"], "RUB"),
            MetricValueV1(
                "budget_utilization_percent",
                calculated["budget_utilization_percent"],
                "PERCENT",
            ),
            MetricValueV1(
                "pacing_percent",
                calculated["pacing_percent"],
                "PERCENT",
            ),
            MetricValueV1(
                "campaign_state",
                observation.campaign_state,
                "CODE",
            ),
            MetricValueV1(
                "group_state",
                observation.group_state,
                "CODE",
            ),
            MetricValueV1(
                "ad_state",
                observation.ad_state,
                "CODE",
            ),
            MetricValueV1(
                "strategy",
                observation.strategy,
                "CODE",
            ),
            MetricValueV1(
                "current_weekly_budget_micros",
                observation.current_weekly_budget_micros,
                "MICROS_RUB",
            ),
            MetricValueV1(
                "current_search_bid_micros",
                observation.current_search_bid_micros,
                "MICROS_RUB",
            ),
            MetricValueV1(
                "ad_variant",
                observation.ad_variant,
                "CODE",
            ),
            MetricValueV1(
                "object_config_version",
                observation.object_config_version,
                "CODE",
            ),
        ]
        if "conversions" in calculated:
            values.extend(
                (
                    MetricValueV1(
                        "conversions",
                        calculated["conversions"],
                        "COUNT",
                    ),
                    MetricValueV1(
                        "cpa_rub",
                        calculated["cpa_rub"],
                        "RUB",
                    ),
                )
            )
        return tuple(values)

    @staticmethod
    def _warnings(
        *,
        clicks: int,
        conversions: Optional[int],
        observed_at: datetime,
        now: datetime,
    ) -> Tuple[ModuleWarningV1, ...]:
        warnings = []
        if conversions is None:
            warnings.append(
                ModuleWarningV1(
                    code="CONVERSION_CONTEXT_UNAVAILABLE",
                    message=(
                        "No provider-neutral conversion count was supplied, "
                        "so conversion-dependent conclusions remain partial."
                    ),
                )
            )
        elif clicks < 50 or conversions < 3:
            warnings.append(
                ModuleWarningV1(
                    code="INSUFFICIENT_SAMPLE",
                    message=(
                        "At least 50 clicks and three conversions are required "
                        "for a conversion-dependent conclusion."
                    ),
                )
            )
        if now - observed_at > timedelta(minutes=30):
            warnings.append(
                ModuleWarningV1(
                    code="DIRECT_DATA_STALE",
                    message=(
                        "Direct evidence is older than the supported "
                        "30-minute freshness window."
                    ),
                )
            )
        return tuple(warnings)

    @classmethod
    def _hypotheses(
        cls,
        calculated: Mapping[str, DirectMetric],
    ) -> Tuple[ModuleHypothesisV1, ...]:
        hypotheses = []
        ctr = cls._decimal(calculated["ctr_percent"])
        utilization = cls._decimal(calculated["budget_utilization_percent"])
        pacing = cls._decimal(calculated["pacing_percent"])
        if (
            ctr is not None
            and cls._integer(calculated["impressions"]) >= 5_000
            and ctr < Decimal(1)
        ):
            hypotheses.append(
                ModuleHypothesisV1(
                    code="LOW_CTR_MAY_REFLECT_AD_RELEVANCE",
                    summary=(
                        "Low CTR may indicate that the ad or targeting does "
                        "not match current search intent."
                    ),
                    evidence_metric_names=("ctr_percent", "impressions"),
                )
            )
        if utilization is not None and utilization >= Decimal(90):
            hypotheses.append(
                ModuleHypothesisV1(
                    code="BUDGET_PRESSURE_MAY_LIMIT_DELIVERY",
                    summary=(
                        "High budget utilization may limit campaign delivery "
                        "before the weekly period closes."
                    ),
                    evidence_metric_names=(
                        "budget_utilization_percent",
                        "current_weekly_budget_micros",
                    ),
                )
            )
        if pacing is not None and pacing >= Decimal(120):
            hypotheses.append(
                ModuleHypothesisV1(
                    code="SPEND_MAY_BE_AHEAD_OF_PACING",
                    summary=(
                        "Spend may be progressing faster than the current "
                        "weekly budget period."
                    ),
                    evidence_metric_names=(
                        "pacing_percent",
                        "cost_micros",
                        "current_weekly_budget_micros",
                    ),
                )
            )
        if not hypotheses:
            hypotheses.append(
                ModuleHypothesisV1(
                    code="DIRECT_TRAFFIC_EFFICIENCY_STABLE",
                    summary=(
                        "The available Direct-native traffic metrics do not "
                        "cross the current anomaly thresholds."
                    ),
                    evidence_metric_names=("ctr_percent", "cpc_rub"),
                )
            )
        return tuple(hypotheses[:3])

    @staticmethod
    def _recommendations(
        calculated: Mapping[str, DirectMetric],
        warnings: Tuple[ModuleWarningV1, ...],
    ) -> Tuple[ModuleRecommendationV1, ...]:
        codes = {item.code for item in warnings}
        if "CONVERSION_CONTEXT_UNAVAILABLE" in codes:
            return (
                ModuleRecommendationV1(
                    code="CONVERSION_CONTEXT_REQUIRED",
                    summary=(
                        "Supply a provider-neutral conversion count before "
                        "making a conversion-dependent campaign decision."
                    ),
                    rationale=(
                        "CTR, CPC, utilization, and pacing are available, but "
                        "CPA and conversion effectiveness cannot be derived."
                    ),
                    executable=False,
                ),
            )
        if "INSUFFICIENT_SAMPLE" in codes:
            return (
                ModuleRecommendationV1(
                    code="COLLECT_MORE_DIRECT_EVIDENCE",
                    summary="Collect a larger click and conversion sample.",
                    rationale=(
                        "The current sample is below the existing minimum of "
                        "50 clicks and three conversions."
                    ),
                    executable=False,
                ),
            )
        if "DIRECT_DATA_STALE" in codes:
            return (
                ModuleRecommendationV1(
                    code="REFRESH_DIRECT_EVIDENCE",
                    summary="Refresh Direct evidence before taking action.",
                    rationale=(
                        "The evidence exceeds the supported 30-minute "
                        "freshness window."
                    ),
                    executable=False,
                ),
            )
        return (
            ModuleRecommendationV1(
                code="CONTINUE_MONITORING",
                summary="Continue monitoring the campaign without a write.",
                rationale=(
                    "The validated Direct-native metrics and neutral "
                    "conversion context support a complete read-only result."
                ),
                executable=False,
            ),
        )

    @staticmethod
    def _assessment_summary(
        warnings: Tuple[ModuleWarningV1, ...],
    ) -> str:
        codes = {item.code for item in warnings}
        if "CONVERSION_CONTEXT_UNAVAILABLE" in codes:
            return (
                "Direct-native performance and campaign state were calculated, "
                "but conversion-dependent conclusions remain partial."
            )
        if "DIRECT_DATA_STALE" in codes:
            return (
                "Direct performance was calculated, but the evidence must be "
                "refreshed before a current conclusion."
            )
        if "INSUFFICIENT_SAMPLE" in codes:
            return (
                "Direct performance was calculated, but the neutral conversion "
                "sample is insufficient."
            )
        return (
            "Direct-native performance, campaign state, and neutral conversion "
            "context were calculated successfully."
        )

    @staticmethod
    def _confidence_status(
        warnings: Tuple[ModuleWarningV1, ...],
    ) -> str:
        codes = {item.code for item in warnings}
        if "INSUFFICIENT_SAMPLE" in codes:
            return "INSUFFICIENT_DATA"
        if "DIRECT_DATA_STALE" in codes:
            return "STALE_DATA"
        return "READY"

    @staticmethod
    def _decimal(value: object) -> Optional[Decimal]:
        if value == NOT_APPLICABLE:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _integer(value: DirectMetric) -> int:
        if not isinstance(value, int):
            raise ValueError("The calculated Direct count is not an integer.")
        return value

    def _normalized_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("The Direct module clock must be timezone-aware.")
        return now.astimezone(timezone.utc)

    @staticmethod
    def _validate_period_is_closed(
        request: ModuleRequestV1,
        now: datetime,
    ) -> None:
        local_date = now.astimezone(ZoneInfo(request.period.timezone)).date()
        if datetime.fromisoformat(request.period.end_date).date() >= local_date:
            raise ValueError("The requested Direct period must be closed.")

    @classmethod
    def _rejected(
        cls,
        request: ModuleRequestV1,
        error: ModuleErrorV1,
    ) -> ModuleResultV1:
        return cls._terminal_result(request, "REJECTED", error)

    @classmethod
    def _failed_provider_read(
        cls,
        request: ModuleRequestV1,
    ) -> ModuleResultV1:
        return cls._terminal_result(
            request,
            "FAILED",
            ModuleErrorV1(
                code="DIRECT_PROVIDER_READ_FAILED",
                message="The authorized Direct read failed before analysis.",
                field="connection_ref",
                retryable=True,
            ),
        )

    @classmethod
    def _terminal_result(
        cls,
        request: ModuleRequestV1,
        status: Literal["REJECTED", "FAILED"],
        error: ModuleErrorV1,
    ) -> ModuleResultV1:
        return ModuleResultV1(
            schema_version=MODULE_RESULT_SCHEMA_VERSION,
            run_id=cls._bounded_run_id(status.lower(), request),
            module=DIRECT_IDENTITY,
            status=status,
            metrics=(),
            assessment=None,
            recommendations=(),
            proposal=None,
            execution_result=None,
            provenance=(),
            warnings=(),
            errors=(error,),
            decision_record_ref=None,
        )

    @staticmethod
    def _bounded_run_id(prefix: str, request: ModuleRequestV1) -> str:
        digest = hashlib.sha256(
            request.idempotency_key.encode("utf-8")
        ).hexdigest()[:24]
        return prefix + "-direct-" + digest
