"""Standalone Direct analysis over the public module contract."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Mapping, Optional, Tuple

from mox_adv.direct_conclusions import (
    direct_hypotheses,
    evaluate_direct_conditions,
)
from mox_adv.direct_metrics import DirectMetric, calculate_direct_metrics
from mox_adv.direct_provider import (
    AuthorizedDirectReadProviderV1,
    DirectObservationV1,
    DirectObservationReaderV1,
    DirectProviderUnavailable,
    DirectReadAuthorizationError,
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
    ModuleRequestV1,
    ModuleResultV1,
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
            return terminal_module_result(
                module=DIRECT_IDENTITY,
                request=request,
                status="REJECTED",
                error=error,
            )
        try:
            now = normalized_utc_now(self._clock, module_name="Direct")
            validate_closed_period(request, now, module_name="Direct")
            observation = self._observations.read(request, now)
        except DirectReadAuthorizationError as authorization_error:
            return terminal_module_result(
                module=DIRECT_IDENTITY,
                request=request,
                status="REJECTED",
                error=ModuleErrorV1(
                    code="DIRECT_SCOPE_REJECTED",
                    message=str(authorization_error),
                    field="scope",
                    retryable=False,
                ),
            )
        except DirectProviderUnavailable:
            return failed_provider_read(
                module=DIRECT_IDENTITY,
                request=request,
                error_code="DIRECT_PROVIDER_READ_FAILED",
                message="The authorized Direct read failed before analysis.",
            )
        except ValueError as error_value:
            return terminal_module_result(
                module=DIRECT_IDENTITY,
                request=request,
                status="REJECTED",
                error=ModuleErrorV1(
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
                observation.state.current_weekly_budget_micros
            ),
            budget_period_start=observation.state.budget_period_start,
            budget_period_end=observation.state.budget_period_end,
            observed_at=now,
            conversions=observation.conversions,
        )
        metrics = self._metrics(calculated, observation)
        conditions = evaluate_direct_conditions(
            clicks=observation.clicks,
            conversions=observation.conversions,
            observed_at=observation.observed_at,
            now=now,
            budget_period_mismatch=observation.budget_period_mismatch,
            watermark_skew_exceeded=observation.watermark_skew_exceeded,
        )
        warnings = conditions.warnings()
        hypotheses = direct_hypotheses(calculated)
        recommendations = conditions.recommendations()
        status = conditions.status
        assessment = ModuleAssessmentV1(
            summary=conditions.assessment_summary,
            data_quality_status=conditions.data_quality_status,
            confidence_status=conditions.confidence_status,
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
                observation.state.campaign_state,
                "CODE",
            ),
            MetricValueV1(
                "group_state",
                observation.state.group_state,
                "CODE",
            ),
            MetricValueV1(
                "ad_state",
                observation.state.ad_state,
                "CODE",
            ),
            MetricValueV1(
                "strategy",
                observation.state.strategy,
                "CODE",
            ),
            MetricValueV1(
                "current_weekly_budget_micros",
                observation.state.current_weekly_budget_micros,
                "MICROS_RUB",
            ),
            MetricValueV1(
                "current_search_bid_micros",
                observation.state.current_search_bid_micros,
                "MICROS_RUB",
            ),
            MetricValueV1(
                "ad_variant",
                observation.state.ad_variant,
                "CODE",
            ),
            MetricValueV1(
                "object_config_version",
                observation.state.object_config_version,
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
