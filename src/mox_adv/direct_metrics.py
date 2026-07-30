"""Provider-native Direct calculations shared by every product edition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional, Union

NOT_APPLICABLE = "NOT_APPLICABLE"
ONE_HUNDRED = Decimal(100)
ONE_MILLION = Decimal(1_000_000)

DirectMetric = Union[int, str]
DirectCalculatedMetric = Union[Decimal, str]


@dataclass(frozen=True)
class DirectCalculatedValues:
    impressions: int
    clicks: int
    cost_micros: int
    ctr_percent: DirectCalculatedMetric
    cpc_rub: DirectCalculatedMetric
    budget_utilization_percent: DirectCalculatedMetric
    pacing_percent: DirectCalculatedMetric
    conversions: Optional[int] = None
    cpa_rub: DirectCalculatedMetric = NOT_APPLICABLE


def _decimal_text(value: Union[Decimal, str]) -> str:
    if isinstance(value, str):
        return value
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal(1)))
    return format(normalized, "f")


def _ratio(
    numerator: int,
    denominator: int,
    multiplier: Decimal = Decimal(1),
) -> Union[Decimal, str]:
    if denominator == 0:
        return NOT_APPLICABLE
    return Decimal(numerator) / Decimal(denominator) * multiplier


def _money(cost_micros: int, denominator: int) -> Union[Decimal, str]:
    if denominator == 0:
        return NOT_APPLICABLE
    return Decimal(cost_micros) / Decimal(denominator) / ONE_MILLION


def calculate_direct_metrics(
    *,
    impressions: int,
    clicks: int,
    cost_micros: int,
    current_weekly_budget_micros: int,
    budget_period_start: datetime,
    budget_period_end: datetime,
    observed_at: datetime,
    conversions: Optional[int] = None,
) -> Dict[str, DirectMetric]:
    """Calculate the existing exact Direct aggregate and optional neutral CPA."""

    calculated = calculate_direct_metric_values(
        impressions=impressions,
        clicks=clicks,
        cost_micros=cost_micros,
        current_weekly_budget_micros=current_weekly_budget_micros,
        budget_period_start=budget_period_start,
        budget_period_end=budget_period_end,
        observed_at=observed_at,
        conversions=conversions,
    )
    metrics: Dict[str, DirectMetric] = {
        "impressions": calculated.impressions,
        "clicks": calculated.clicks,
        "cost_micros": calculated.cost_micros,
        "ctr_percent": _decimal_text(calculated.ctr_percent),
        "cpc_rub": _decimal_text(calculated.cpc_rub),
        "budget_utilization_percent": _decimal_text(
            calculated.budget_utilization_percent
        ),
        "pacing_percent": _decimal_text(calculated.pacing_percent),
    }
    if calculated.conversions is not None:
        metrics["conversions"] = calculated.conversions
        metrics["cpa_rub"] = _decimal_text(calculated.cpa_rub)
    return metrics


def calculate_direct_metric_values(
    *,
    impressions: int,
    clicks: int,
    cost_micros: int,
    current_weekly_budget_micros: int,
    budget_period_start: datetime,
    budget_period_end: datetime,
    observed_at: datetime,
    conversions: Optional[int] = None,
) -> DirectCalculatedValues:
    """Return exact Decimal values for paired and standalone projections."""

    total_seconds = Decimal(
        str((budget_period_end - budget_period_start).total_seconds())
    )
    elapsed_seconds = Decimal(
        str(
            min(
                max(
                    (observed_at - budget_period_start).total_seconds(),
                    0,
                ),
                (budget_period_end - budget_period_start).total_seconds(),
            )
        )
    )
    expected_spend_micros = (
        Decimal(current_weekly_budget_micros) * elapsed_seconds / total_seconds
        if total_seconds > 0
        else Decimal(0)
    )
    pacing = (
        NOT_APPLICABLE
        if expected_spend_micros == 0
        else Decimal(cost_micros) / expected_spend_micros * ONE_HUNDRED
    )
    return DirectCalculatedValues(
        impressions=impressions,
        clicks=clicks,
        cost_micros=cost_micros,
        ctr_percent=_ratio(clicks, impressions, ONE_HUNDRED),
        cpc_rub=_money(cost_micros, clicks),
        budget_utilization_percent=_ratio(
            cost_micros,
            current_weekly_budget_micros,
            ONE_HUNDRED,
        ),
        pacing_percent=pacing,
        conversions=conversions,
        cpa_rub=(
            NOT_APPLICABLE
            if conversions is None
            else _money(cost_micros, conversions)
        ),
    )
