"""Deterministic Direct hypotheses, warnings, and recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Mapping, Optional, Tuple

from mox_adv.direct_metrics import NOT_APPLICABLE, DirectMetric
from mox_adv.module_api.v1 import (
    ModuleHypothesisV1,
    ModuleRecommendationV1,
    ModuleStatus,
    ModuleWarningV1,
)


@dataclass(frozen=True)
class DirectAnalysisConditionsV1:
    """One evaluated condition set projected consistently across the result."""

    conversion_context_missing: bool
    insufficient_sample: bool
    stale: bool

    @property
    def status(self) -> ModuleStatus:
        return (
            "PARTIAL"
            if (
                self.conversion_context_missing
                or self.insufficient_sample
                or self.stale
            )
            else "SUCCEEDED"
        )

    @property
    def data_quality_status(self) -> str:
        return (
            "PARTIAL"
            if self.conversion_context_missing or self.stale
            else "READY"
        )

    @property
    def confidence_status(self) -> str:
        if self.insufficient_sample:
            return "INSUFFICIENT_DATA"
        if self.stale:
            return "STALE_DATA"
        return "READY"

    @property
    def assessment_summary(self) -> str:
        if self.conversion_context_missing:
            return (
                "Direct-native performance and campaign state were calculated, "
                "but conversion-dependent conclusions remain partial."
            )
        if self.stale:
            return (
                "Direct performance was calculated, but the evidence must be "
                "refreshed before a current conclusion."
            )
        if self.insufficient_sample:
            return (
                "Direct performance was calculated, but the neutral conversion "
                "sample is insufficient."
            )
        return (
            "Direct-native performance, campaign state, and neutral conversion "
            "context were calculated successfully."
        )

    def warnings(self) -> Tuple[ModuleWarningV1, ...]:
        warnings = []
        if self.conversion_context_missing:
            warnings.append(
                ModuleWarningV1(
                    code="CONVERSION_CONTEXT_UNAVAILABLE",
                    message=(
                        "No provider-neutral conversion count was supplied, "
                        "so conversion-dependent conclusions remain partial."
                    ),
                )
            )
        if self.insufficient_sample:
            warnings.append(
                ModuleWarningV1(
                    code="INSUFFICIENT_SAMPLE",
                    message=(
                        "At least 50 clicks and three conversions are required "
                        "for a conversion-dependent conclusion."
                    ),
                )
            )
        if self.stale:
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

    def recommendations(self) -> Tuple[ModuleRecommendationV1, ...]:
        if self.conversion_context_missing:
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
        if self.insufficient_sample:
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
        if self.stale:
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


def evaluate_direct_conditions(
    *,
    clicks: int,
    conversions: Optional[int],
    observed_at: datetime,
    now: datetime,
) -> DirectAnalysisConditionsV1:
    return DirectAnalysisConditionsV1(
        conversion_context_missing=conversions is None,
        insufficient_sample=(
            conversions is not None and (clicks < 50 or conversions < 3)
        ),
        stale=now - observed_at > timedelta(minutes=30),
    )


def direct_hypotheses(
    calculated: Mapping[str, DirectMetric],
) -> Tuple[ModuleHypothesisV1, ...]:
    hypotheses = []
    ctr = _decimal(calculated["ctr_percent"])
    utilization = _decimal(calculated["budget_utilization_percent"])
    pacing = _decimal(calculated["pacing_percent"])
    if (
        ctr is not None
        and _integer(calculated["impressions"]) >= 5_000
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


def _decimal(value: object) -> Optional[Decimal]:
    if value == NOT_APPLICABLE:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _integer(value: DirectMetric) -> int:
    if not isinstance(value, int):
        raise ValueError("The calculated Direct count is not an integer.")
    return value
