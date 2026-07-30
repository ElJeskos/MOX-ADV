"""Provider-native Metrika calculations shared by every product edition."""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Union

NOT_APPLICABLE = "NOT_APPLICABLE"
ONE_HUNDRED = Decimal(100)


def _decimal_text(value: Union[Decimal, str]) -> str:
    if isinstance(value, str):
        return value
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal(1)))
    return format(normalized, "f")


def calculate_metrika_metrics(
    *,
    visits: int,
    goal_visits: int,
) -> Mapping[str, Union[int, str]]:
    """Calculate the existing exact aggregate for standalone Metrika."""

    conversion_rate: Union[Decimal, str]
    if visits == 0:
        conversion_rate = NOT_APPLICABLE
    else:
        conversion_rate = Decimal(goal_visits) / Decimal(visits) * ONE_HUNDRED
    return {
        "visits": visits,
        "goal_visits": goal_visits,
        "conversion_rate_percent": _decimal_text(conversion_rate),
    }
