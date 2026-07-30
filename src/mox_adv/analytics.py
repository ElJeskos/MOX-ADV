"""Deterministic analytics for safe bootstrap and OBSERVE snapshots."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Mapping, Union

from mox_adv.contracts import (
    AnalyticsSummary,
    BaselineAggregate,
    IntegratedPerformanceSnapshot,
    IntegratedSnapshotDraft,
    NormalizedSnapshot,
    RunContext,
)
from mox_adv.direct_metrics import calculate_direct_metric_values
from mox_adv.normalization import IntegratedSnapshotNormalizerV1


class AnalyticsEngineV1:
    def calculate(
        self,
        context: RunContext,
        snapshot: NormalizedSnapshot,
    ) -> AnalyticsSummary:
        del context
        impressions = sum(record.impressions for record in snapshot.records)
        clicks = sum(record.clicks for record in snapshot.records)
        conversions = sum(record.conversions for record in snapshot.records)
        cost_rub = sum((record.cost_rub for record in snapshot.records), Decimal("0"))
        ctr = Decimal(clicks) / Decimal(impressions) if impressions else Decimal("0")
        return AnalyticsSummary(
            snapshot_id=snapshot.snapshot_id,
            impressions=impressions,
            clicks=clicks,
            conversions=conversions,
            cost_rub=cost_rub,
            ctr=ctr,
        )


MetricValue = Union[Decimal, str]
NOT_APPLICABLE = "NOT_APPLICABLE"
ONE_MILLION = Decimal(1_000_000)
ONE_HUNDRED = Decimal(100)


def _ratio(
    numerator: int,
    denominator: int,
    multiplier: Decimal = Decimal(1),
) -> MetricValue:
    if denominator == 0:
        return NOT_APPLICABLE
    return Decimal(numerator) / Decimal(denominator) * multiplier


def _money(cost_micros: int, denominator: int) -> MetricValue:
    if denominator == 0:
        return NOT_APPLICABLE
    return Decimal(cost_micros) / Decimal(denominator) / ONE_MILLION


def _decimal_text(value: MetricValue) -> str:
    if isinstance(value, str):
        return value
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal(1)))
    return format(normalized, "f")


def _display(value: MetricValue) -> str:
    if isinstance(value, str):
        return value
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _baseline_metrics(baseline: BaselineAggregate) -> Mapping[str, MetricValue]:
    return {
        "ctr_percent": _ratio(
            baseline.clicks,
            baseline.impressions,
            ONE_HUNDRED,
        ),
        "cpc_rub": _money(baseline.cost_micros, baseline.clicks),
        "conversion_rate_percent": _ratio(
            baseline.goal_visits,
            baseline.visits,
            ONE_HUNDRED,
        ),
        "cpa_rub": _money(baseline.cost_micros, baseline.goal_visits),
    }


def _deviation(
    current: MetricValue,
    baseline: MetricValue,
) -> MetricValue:
    if isinstance(current, str) or isinstance(baseline, str) or baseline == 0:
        return NOT_APPLICABLE
    return (current - baseline) / baseline * ONE_HUNDRED


class IntegratedAnalyticsEngineV1:
    """Calculate exact OBSERVE metrics and seal the normative fingerprint."""

    def calculate(
        self,
        snapshot: IntegratedSnapshotDraft,
    ) -> IntegratedPerformanceSnapshot:
        impressions = sum(row.impressions for row in snapshot.grain_records)
        clicks = sum(row.clicks for row in snapshot.grain_records)
        cost_micros = sum(row.cost_micros for row in snapshot.grain_records)
        visits = sum(row.visits for row in snapshot.grain_records)
        goal_visits = sum(row.goal_visits for row in snapshot.grain_records)
        leads_values = [
            row.leads for row in snapshot.grain_records if row.leads is not None
        ]
        leads = sum(int(value) for value in leads_values) if leads_values else None
        current_weekly_budget = snapshot.campaign.current_weekly_budget_micros
        direct = calculate_direct_metric_values(
            impressions=impressions,
            clicks=clicks,
            cost_micros=cost_micros,
            current_weekly_budget_micros=current_weekly_budget,
            budget_period_start=datetime.fromisoformat(
                snapshot.campaign.budget_period_start.replace("Z", "+00:00")
            ).astimezone(timezone.utc),
            budget_period_end=datetime.fromisoformat(
                snapshot.campaign.budget_period_end.replace("Z", "+00:00")
            ).astimezone(timezone.utc),
            observed_at=datetime.fromisoformat(
                snapshot.generated_at.replace("Z", "+00:00")
            ).astimezone(timezone.utc),
        )
        calculated: Dict[str, MetricValue] = {
            "ctr_percent": direct.ctr_percent,
            "cpc_rub": direct.cpc_rub,
            "conversion_rate_percent": _ratio(
                goal_visits,
                visits,
                ONE_HUNDRED,
            ),
            "cpa_rub": _money(cost_micros, goal_visits),
            "cpl_rub": (
                NOT_APPLICABLE if leads is None else _money(cost_micros, leads)
            ),
            "budget_utilization_percent": direct.budget_utilization_percent,
            "pacing_percent": direct.pacing_percent,
        }
        metrics: Dict[str, Any] = {
            "impressions": impressions,
            "clicks": clicks,
            "cost_micros": cost_micros,
            "visits": visits,
            "goal_visits": goal_visits,
            "leads": leads,
        }
        metrics.update(
            {name: _decimal_text(value) for name, value in calculated.items()}
        )
        display_metrics = {name: _display(value) for name, value in calculated.items()}
        if snapshot.baseline is None:
            baseline_deviation = {
                name: NOT_APPLICABLE
                for name in (
                    "ctr_percent",
                    "cpc_rub",
                    "conversion_rate_percent",
                    "cpa_rub",
                )
            }
        else:
            baseline = _baseline_metrics(snapshot.baseline)
            baseline_deviation = {
                name: _decimal_text(_deviation(calculated[name], value))
                for name, value in baseline.items()
            }
        result = IntegratedPerformanceSnapshot(
            snapshot_id="",
            schema_version=snapshot.schema_version,
            policy_version=snapshot.policy_version,
            observation_id=snapshot.observation_id,
            generated_at=snapshot.generated_at,
            scope=snapshot.scope,
            period_start=snapshot.period_start,
            period_end=snapshot.period_end,
            timezone=snapshot.timezone,
            attribution=snapshot.attribution,
            grain="campaign × goal × day",
            provenance=snapshot.provenance,
            records=snapshot.grain_records,
            currency="RUB",
            metrics=metrics,
            display_metrics=display_metrics,
            baseline_deviation=baseline_deviation,
            campaign=snapshot.campaign,
            last_change=snapshot.last_change,
            business_goal=snapshot.business_goal,
            target_kpi=snapshot.target_kpi,
            data_quality_gaps=snapshot.data_quality_gaps,
            comparability_status=snapshot.comparability_status,
            confidence_status=snapshot.confidence_status,
            financial_recommendations_allowed=(
                snapshot.financial_recommendations_allowed
            ),
        )
        return replace(
            result,
            snapshot_id=IntegratedSnapshotNormalizerV1.fingerprint(result.as_dict()),
        )
