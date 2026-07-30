"""Deterministic Direct hypotheses, warnings, and recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Mapping, Optional, Tuple

from mox_adv.direct_metrics import NOT_APPLICABLE, DirectMetric
from mox_adv.module_api.v1 import (
    ModuleHypothesisV1,
    ModuleRecommendationV1,
    ModuleStatus,
    ModuleWarningV1,
)

READY_ASSESSMENT = (
    "Direct-native performance, campaign state, and neutral conversion "
    "context were calculated successfully."
)
READY_RECOMMENDATION = ModuleRecommendationV1(
    code="CONTINUE_MONITORING",
    summary="Continue monitoring the campaign without a write.",
    rationale=(
        "The validated Direct-native metrics and neutral conversion context "
        "support a complete read-only result."
    ),
    executable=False,
)


class DirectConditionV1(str, Enum):
    CONVERSION_CONTEXT_MISSING = "CONVERSION_CONTEXT_MISSING"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    STALE = "STALE"
    BUDGET_PERIOD_MISMATCH = "BUDGET_PERIOD_MISMATCH"
    WATERMARK_SKEW_EXCEEDED = "WATERMARK_SKEW_EXCEEDED"


@dataclass(frozen=True)
class DirectConditionPolicyV1:
    warning: ModuleWarningV1
    recommendation: ModuleRecommendationV1
    assessment_summary: str
    warning_order: int
    recommendation_priority: int
    assessment_priority: int
    data_quality_status: Optional[str] = None
    confidence_status: Optional[str] = None
    confidence_priority: int = 99


DIRECT_CONDITION_POLICIES = {
    DirectConditionV1.CONVERSION_CONTEXT_MISSING: DirectConditionPolicyV1(
        warning=ModuleWarningV1(
            code="CONVERSION_CONTEXT_UNAVAILABLE",
            message=(
                "No provider-neutral conversion count was supplied, so "
                "conversion-dependent conclusions remain partial."
            ),
        ),
        recommendation=ModuleRecommendationV1(
            code="CONVERSION_CONTEXT_REQUIRED",
            summary=(
                "Supply a provider-neutral conversion count before making a "
                "conversion-dependent campaign decision."
            ),
            rationale=(
                "CTR, CPC, utilization, and pacing are available, but CPA "
                "and conversion effectiveness cannot be derived."
            ),
            executable=False,
        ),
        assessment_summary=(
            "Direct-native performance and campaign state were calculated, "
            "but conversion-dependent conclusions remain partial."
        ),
        warning_order=0,
        recommendation_priority=2,
        assessment_priority=2,
        data_quality_status="PARTIAL",
    ),
    DirectConditionV1.INSUFFICIENT_SAMPLE: DirectConditionPolicyV1(
        warning=ModuleWarningV1(
            code="INSUFFICIENT_SAMPLE",
            message=(
                "At least 50 clicks and three conversions are required for a "
                "conversion-dependent conclusion."
            ),
        ),
        recommendation=ModuleRecommendationV1(
            code="COLLECT_MORE_DIRECT_EVIDENCE",
            summary="Collect a larger click and conversion sample.",
            rationale=(
                "The current sample is below the existing minimum of 50 "
                "clicks and three conversions."
            ),
            executable=False,
        ),
        assessment_summary=(
            "Direct performance was calculated, but the neutral conversion "
            "sample is insufficient."
        ),
        warning_order=1,
        recommendation_priority=3,
        assessment_priority=4,
        confidence_status="INSUFFICIENT_DATA",
        confidence_priority=0,
    ),
    DirectConditionV1.STALE: DirectConditionPolicyV1(
        warning=ModuleWarningV1(
            code="DIRECT_DATA_STALE",
            message=(
                "Direct evidence is older than the supported 30-minute "
                "freshness window."
            ),
        ),
        recommendation=ModuleRecommendationV1(
            code="REFRESH_DIRECT_EVIDENCE",
            summary="Refresh Direct evidence before taking action.",
            rationale=(
                "The evidence exceeds the supported 30-minute freshness "
                "window."
            ),
            executable=False,
        ),
        assessment_summary=(
            "Direct performance was calculated, but the evidence must be "
            "refreshed before a current conclusion."
        ),
        warning_order=2,
        recommendation_priority=4,
        assessment_priority=3,
        data_quality_status="PARTIAL",
        confidence_status="STALE_DATA",
        confidence_priority=1,
    ),
    DirectConditionV1.BUDGET_PERIOD_MISMATCH: DirectConditionPolicyV1(
        warning=ModuleWarningV1(
            code="BUDGET_PERIOD_MISMATCH",
            message=(
                "The managed weekly budget period has not started, so the "
                "campaign state is incompatible with the observation time."
            ),
        ),
        recommendation=ModuleRecommendationV1(
            code="REFRESH_DIRECT_MANAGED_STATE",
            summary="Refresh the managed Direct campaign state.",
            rationale=(
                "A future weekly budget period cannot support current "
                "utilization, pacing, or a financial recommendation."
            ),
            executable=False,
        ),
        assessment_summary=(
            "Direct performance was calculated, but the managed weekly budget "
            "period is incompatible with the observation time."
        ),
        warning_order=3,
        recommendation_priority=0,
        assessment_priority=0,
        data_quality_status="INCOMPATIBLE",
    ),
    DirectConditionV1.WATERMARK_SKEW_EXCEEDED: DirectConditionPolicyV1(
        warning=ModuleWarningV1(
            code="WATERMARK_SKEW_EXCEEDED",
            message=(
                "Direct report and campaign-state watermarks differ by more "
                "than the supported six-hour window."
            ),
        ),
        recommendation=ModuleRecommendationV1(
            code="REFRESH_DIRECT_EVIDENCE",
            summary="Refresh Direct report and campaign-state evidence.",
            rationale=(
                "Misaligned source watermarks cannot support a comparable "
                "campaign conclusion."
            ),
            executable=False,
        ),
        assessment_summary=(
            "Direct performance was calculated, but report and campaign-state "
            "watermarks are incompatible."
        ),
        warning_order=4,
        recommendation_priority=1,
        assessment_priority=1,
        data_quality_status="INCOMPATIBLE",
    ),
}

DATA_QUALITY_RANK = {
    None: 0,
    "READY": 0,
    "PARTIAL": 1,
    "INCOMPATIBLE": 2,
}


@dataclass(frozen=True)
class DirectAnalysisConditionsV1:
    """One evaluated policy set projected consistently across the result."""

    conditions: Tuple[DirectConditionV1, ...]

    @property
    def _policies(self) -> Tuple[DirectConditionPolicyV1, ...]:
        return tuple(DIRECT_CONDITION_POLICIES[item] for item in self.conditions)

    @property
    def status(self) -> ModuleStatus:
        return "PARTIAL" if self.conditions else "SUCCEEDED"

    @property
    def data_quality_status(self) -> str:
        statuses = tuple(
            item.data_quality_status
            for item in self._policies
            if item.data_quality_status is not None
        )
        if not statuses:
            return "READY"
        return max(statuses, key=lambda item: DATA_QUALITY_RANK[item])

    @property
    def confidence_status(self) -> str:
        candidates = tuple(
            item
            for item in self._policies
            if item.confidence_status is not None
        )
        if not candidates:
            return "READY"
        selected = min(candidates, key=lambda item: item.confidence_priority)
        assert selected.confidence_status is not None
        return selected.confidence_status

    @property
    def assessment_summary(self) -> str:
        if not self.conditions:
            return READY_ASSESSMENT
        return min(
            self._policies,
            key=lambda item: item.assessment_priority,
        ).assessment_summary

    def warnings(self) -> Tuple[ModuleWarningV1, ...]:
        return tuple(
            item.warning
            for item in sorted(
                self._policies,
                key=lambda item: item.warning_order,
            )
        )

    def recommendations(self) -> Tuple[ModuleRecommendationV1, ...]:
        if not self.conditions:
            return (READY_RECOMMENDATION,)
        selected = min(
            self._policies,
            key=lambda item: item.recommendation_priority,
        )
        return (selected.recommendation,)


def evaluate_direct_conditions(
    *,
    clicks: int,
    conversions: Optional[int],
    observed_at: datetime,
    now: datetime,
    budget_period_mismatch: bool,
    watermark_skew_exceeded: bool,
) -> DirectAnalysisConditionsV1:
    conditions = []
    if conversions is None:
        conditions.append(DirectConditionV1.CONVERSION_CONTEXT_MISSING)
    elif clicks < 50 or conversions < 3:
        conditions.append(DirectConditionV1.INSUFFICIENT_SAMPLE)
    if now - observed_at > timedelta(minutes=30):
        conditions.append(DirectConditionV1.STALE)
    if budget_period_mismatch:
        conditions.append(DirectConditionV1.BUDGET_PERIOD_MISMATCH)
    if watermark_skew_exceeded:
        conditions.append(DirectConditionV1.WATERMARK_SKEW_EXCEEDED)
    return DirectAnalysisConditionsV1(tuple(conditions))


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
                    "Low CTR may indicate that the ad or targeting does not "
                    "match current search intent."
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
                    "Spend may be progressing faster than the current weekly "
                    "budget period."
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
                    "The available Direct-native traffic metrics do not cross "
                    "the current anomaly thresholds."
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
