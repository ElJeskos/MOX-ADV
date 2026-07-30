"""Durable operator settings and deterministic UI trigger evaluation."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

DEFAULT_SCENARIO: dict[str, Any] = {
    "impressions": 10_000,
    "clicks": 100,
    "spend_rub": 1_900,
    "visits": 100,
    "conversions": 12,
    "weekly_budget_rub": 2_000,
    "baseline_spend_rub": 1_800,
    "baseline_conversions": 10,
    "expected_spend_rub": 1_600,
    "baseline_impressions": 10_000,
    "baseline_clicks": 100,
    "baseline_visits": 100,
    "hours_since_last_conversion": 1,
    "source_mismatch_percent": 0,
    "direct_age_minutes": 1,
    "metrika_age_minutes": 1,
    "watermark_skew_minutes": 0,
    "external_change": 0,
    "campaign_state": "ON",
}

_BASE_SCENARIO_FIELDS = {
    "impressions",
    "clicks",
    "spend_rub",
    "visits",
    "conversions",
    "weekly_budget_rub",
    "baseline_spend_rub",
    "baseline_conversions",
}

OPERATING_MODES = {
    "OBSERVE",
    "RECOMMEND",
    "APPROVAL_REQUIRED",
    "BOUNDED_AUTONOMY",
}


def default_recommendation_rules(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Return the editable test recommendation thresholds."""

    thresholds = policy["monitoring"]["anomaly_thresholds"]
    return {
        "minimum_clicks": int(policy["mandate"]["minimum_sample"]["clicks"]),
        "minimum_conversions": int(policy["mandate"]["minimum_sample"]["conversions"]),
        "target_cpa_rub": int(policy["mandate"]["kpi"]["target_maximum"]),
        "budget_pressure_percent": int(thresholds["budget_pressure_usage_percent"]),
        "no_conversion_spend_rub": int(
            policy["limits"]["no_conversion_stop_spend_rub"]
        ),
        "low_ctr_percent": float(thresholds["low_ctr_percent"]),
        "low_ctr_minimum_impressions": int(thresholds["low_ctr_minimum_impressions"]),
        "bid_increase_maximum_clicks": int(
            thresholds.get("bid_increase_maximum_clicks", 99)
        ),
    }


class AutomationConfigurationError(ValueError):
    """Operator automation settings do not satisfy the trusted boundary."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise AutomationConfigurationError(
            "INVALID_TIMESTAMP",
            "Automation timestamps must be timezone-aware.",
        )
    return value.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return _utc(value).isoformat()


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AutomationConfigurationError(
            "INVALID_TIMESTAMP",
            "Stored automation timestamp is invalid.",
        ) from error
    return _utc(parsed)


def _integer(
    value: object,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AutomationConfigurationError(
            "INVALID_SCENARIO",
            f"{name} must be an integer.",
        )
    if value < minimum or value > maximum:
        raise AutomationConfigurationError(
            "INVALID_SCENARIO",
            f"{name} must be between {minimum} and {maximum}.",
        )
    return value


def validate_scenario(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate coherent raw facts used to build a linked test fixture."""

    if value is None:
        return deepcopy(DEFAULT_SCENARIO)
    if not _BASE_SCENARIO_FIELDS.issubset(value) or not set(value).issubset(
        DEFAULT_SCENARIO
    ):
        raise AutomationConfigurationError(
            "INVALID_SCENARIO",
            "The test scenario fields do not match the supported metric facts.",
        )
    merged = deepcopy(DEFAULT_SCENARIO)
    merged.update(value)
    scenario: dict[str, Any] = {
        "impressions": _integer(
            merged["impressions"],
            name="impressions",
            minimum=1,
            maximum=100_000_000,
        ),
        "clicks": _integer(
            merged["clicks"],
            name="clicks",
            minimum=0,
            maximum=100_000_000,
        ),
        "spend_rub": _integer(
            merged["spend_rub"],
            name="spend_rub",
            minimum=0,
            maximum=100_000_000,
        ),
        "visits": _integer(
            merged["visits"],
            name="visits",
            minimum=0,
            maximum=100_000_000,
        ),
        "conversions": _integer(
            merged["conversions"],
            name="conversions",
            minimum=0,
            maximum=100_000_000,
        ),
        "weekly_budget_rub": _integer(
            merged["weekly_budget_rub"],
            name="weekly_budget_rub",
            minimum=1,
            maximum=100_000_000,
        ),
        "baseline_spend_rub": _integer(
            merged["baseline_spend_rub"],
            name="baseline_spend_rub",
            minimum=0,
            maximum=100_000_000,
        ),
        "baseline_conversions": _integer(
            merged["baseline_conversions"],
            name="baseline_conversions",
            minimum=0,
            maximum=100_000_000,
        ),
    }
    for name, minimum in (
        ("expected_spend_rub", 1),
        ("baseline_impressions", 1),
        ("baseline_clicks", 0),
        ("baseline_visits", 1),
        ("hours_since_last_conversion", 0),
        ("source_mismatch_percent", 0),
        ("direct_age_minutes", 0),
        ("metrika_age_minutes", 0),
        ("watermark_skew_minutes", 0),
        ("external_change", 0),
    ):
        maximum = 1 if name == "external_change" else 100_000_000
        scenario[name] = _integer(
            merged[name],
            name=name,
            minimum=minimum,
            maximum=maximum,
        )
    campaign_state = merged["campaign_state"]
    if campaign_state not in {"ON", "SUSPENDED"}:
        raise AutomationConfigurationError(
            "INVALID_SCENARIO",
            "campaign_state must be ON or SUSPENDED.",
        )
    scenario["campaign_state"] = campaign_state
    if scenario["clicks"] > scenario["impressions"]:
        raise AutomationConfigurationError(
            "INVALID_SCENARIO",
            "Clicks cannot exceed impressions.",
        )
    if scenario["conversions"] > scenario["visits"]:
        raise AutomationConfigurationError(
            "INVALID_SCENARIO",
            "Conversions cannot exceed visits.",
        )
    if scenario["baseline_conversions"] > scenario["visits"]:
        raise AutomationConfigurationError(
            "INVALID_SCENARIO",
            "Baseline conversions cannot exceed the scenario visits.",
        )
    if scenario["baseline_clicks"] > scenario["baseline_impressions"]:
        raise AutomationConfigurationError(
            "INVALID_SCENARIO",
            "Baseline clicks cannot exceed baseline impressions.",
        )
    if scenario["baseline_conversions"] > scenario["baseline_visits"]:
        raise AutomationConfigurationError(
            "INVALID_SCENARIO",
            "Baseline conversions cannot exceed baseline visits.",
        )
    return scenario


def _recommendation_integer(
    value: object,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise AutomationConfigurationError(
            "INVALID_RECOMMENDATION_RULES",
            f"{name} must be an integer between {minimum} and {maximum}.",
        )
    return value


def validate_recommendation_rules(
    policy: Mapping[str, Any],
    value: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate test-only thresholds without weakening the Gate 0 boundary."""

    defaults = default_recommendation_rules(policy)
    rules = defaults if value is None else deepcopy(dict(value))
    if set(rules) != set(defaults):
        raise AutomationConfigurationError(
            "INVALID_RECOMMENDATION_RULES",
            "The recommendation-rule fields do not match the supported matrix.",
        )
    minimum_clicks = _recommendation_integer(
        rules["minimum_clicks"],
        name="minimum_clicks",
        minimum=defaults["minimum_clicks"],
        maximum=1_000_000,
    )
    minimum_conversions = _recommendation_integer(
        rules["minimum_conversions"],
        name="minimum_conversions",
        minimum=defaults["minimum_conversions"],
        maximum=1_000_000,
    )
    target_cpa = _recommendation_integer(
        rules["target_cpa_rub"],
        name="target_cpa_rub",
        minimum=1,
        maximum=defaults["target_cpa_rub"],
    )
    budget_pressure = _recommendation_integer(
        rules["budget_pressure_percent"],
        name="budget_pressure_percent",
        minimum=defaults["budget_pressure_percent"],
        maximum=500,
    )
    no_conversion_spend = _recommendation_integer(
        rules["no_conversion_spend_rub"],
        name="no_conversion_spend_rub",
        minimum=defaults["no_conversion_spend_rub"],
        maximum=100_000_000,
    )
    low_ctr = _decimal(rules["low_ctr_percent"], "low_ctr_percent")
    if low_ctr < Decimal("0.1") or low_ctr > Decimal(str(defaults["low_ctr_percent"])):
        raise AutomationConfigurationError(
            "INVALID_RECOMMENDATION_RULES",
            "low_ctr_percent must be between 0.1 and the Gate 0 maximum.",
        )
    low_ctr_impressions = _recommendation_integer(
        rules["low_ctr_minimum_impressions"],
        name="low_ctr_minimum_impressions",
        minimum=defaults["low_ctr_minimum_impressions"],
        maximum=100_000_000,
    )
    bid_clicks = _recommendation_integer(
        rules["bid_increase_maximum_clicks"],
        name="bid_increase_maximum_clicks",
        minimum=defaults["minimum_clicks"],
        maximum=defaults["bid_increase_maximum_clicks"],
    )
    return {
        "minimum_clicks": minimum_clicks,
        "minimum_conversions": minimum_conversions,
        "target_cpa_rub": target_cpa,
        "budget_pressure_percent": budget_pressure,
        "no_conversion_spend_rub": no_conversion_spend,
        "low_ctr_percent": float(low_ctr),
        "low_ctr_minimum_impressions": low_ctr_impressions,
        "bid_increase_maximum_clicks": bid_clicks,
    }


def recommendation_policy(
    policy: Mapping[str, Any],
    rules: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply validated test thresholds to a recommendation-only policy copy."""

    result = deepcopy(dict(policy))
    result["mandate"]["minimum_sample"] = {
        "clicks": rules["minimum_clicks"],
        "conversions": rules["minimum_conversions"],
    }
    result["mandate"]["kpi"]["target_maximum"] = rules["target_cpa_rub"]
    thresholds = result["monitoring"]["anomaly_thresholds"]
    thresholds["budget_pressure_usage_percent"] = rules["budget_pressure_percent"]
    thresholds["low_ctr_percent"] = rules["low_ctr_percent"]
    thresholds["low_ctr_minimum_impressions"] = rules["low_ctr_minimum_impressions"]
    thresholds["bid_increase_maximum_clicks"] = rules["bid_increase_maximum_clicks"]
    result["limits"]["no_conversion_stop_spend_rub"] = rules["no_conversion_spend_rub"]
    return result


def default_rules(policy: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    thresholds = policy["monitoring"]["anomaly_thresholds"]
    timing = policy["timing"]
    return {
        "budget_pressure": {
            "enabled": True,
            "threshold_percent": int(thresholds["budget_pressure_usage_percent"]),
        },
        "spend_growth_without_conversion": {
            "enabled": True,
            "threshold_rub": int(thresholds["spend_growth_without_conversion_rub"]),
            "maximum_conversion_growth_percent": 0,
        },
        "no_conversion_spend": {
            "enabled": True,
            "threshold_rub": int(thresholds["no_conversion_spend_rub"]),
        },
        "pacing_ahead": {
            "enabled": True,
            "threshold_percent": 100 + int(thresholds["pacing_ahead_percent"]),
        },
        "cpc_deviation": {
            "enabled": True,
            "threshold_percent": int(thresholds["cpc_deviation_from_baseline_percent"]),
        },
        "ctr_deviation": {
            "enabled": True,
            "threshold_percent": int(thresholds["ctr_deviation_from_baseline_percent"]),
        },
        "conversion_rate_deviation": {
            "enabled": True,
            "threshold_percent": int(
                thresholds["conversion_rate_deviation_from_baseline_percent"]
            ),
        },
        "goal_cessation": {
            "enabled": True,
            "threshold_hours": int(thresholds["goal_cessation_hours"]),
            "minimum_visits": int(thresholds["goal_cessation_minimum_visits"]),
        },
        "source_mismatch": {
            "enabled": True,
            "threshold_percent": int(thresholds["source_mismatch_percent"]),
        },
        "external_change": {"enabled": True},
        "freshness": {
            "enabled": True,
            "direct_minutes": int(timing["direct_freshness_minutes"]),
            "metrika_minutes": int(timing["metrika_freshness_hours"]) * 60,
            "watermark_skew_minutes": int(timing["maximum_watermark_skew_hours"]) * 60,
        },
    }


def _enabled(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise AutomationConfigurationError(
            "INVALID_RULES",
            f"{name}.enabled must be boolean.",
        )
    return value


def validate_rules(
    policy: Mapping[str, Any],
    value: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Allow operator tuning only when it preserves Gate 0 safety floors."""

    rules = default_rules(policy) if value is None else deepcopy(dict(value))
    expected = set(default_rules(policy))
    if set(rules) != expected:
        raise AutomationConfigurationError(
            "INVALID_RULES",
            "The decision-rule set does not match the supported rules.",
        )
    budget = rules["budget_pressure"]
    spend_growth = rules["spend_growth_without_conversion"]
    no_conversion = rules["no_conversion_spend"]
    pacing = rules["pacing_ahead"]
    cpc_deviation = rules["cpc_deviation"]
    ctr_deviation = rules["ctr_deviation"]
    conversion_deviation = rules["conversion_rate_deviation"]
    goal_cessation = rules["goal_cessation"]
    source_mismatch = rules["source_mismatch"]
    external_change = rules["external_change"]
    freshness = rules["freshness"]
    if set(budget) != {"enabled", "threshold_percent"}:
        raise AutomationConfigurationError(
            "INVALID_RULES",
            "Budget-pressure rule fields are invalid.",
        )
    if set(spend_growth) != {
        "enabled",
        "threshold_rub",
        "maximum_conversion_growth_percent",
    }:
        raise AutomationConfigurationError(
            "INVALID_RULES",
            "Spend-growth rule fields are invalid.",
        )
    if set(no_conversion) != {"enabled", "threshold_rub"}:
        raise AutomationConfigurationError(
            "INVALID_RULES",
            "No-conversion rule fields are invalid.",
        )
    for name, rule in (
        ("pacing_ahead", pacing),
        ("cpc_deviation", cpc_deviation),
        ("ctr_deviation", ctr_deviation),
        ("conversion_rate_deviation", conversion_deviation),
        ("source_mismatch", source_mismatch),
    ):
        if set(rule) != {"enabled", "threshold_percent"}:
            raise AutomationConfigurationError(
                "INVALID_RULES",
                f"{name} rule fields are invalid.",
            )
    if set(goal_cessation) != {
        "enabled",
        "threshold_hours",
        "minimum_visits",
    }:
        raise AutomationConfigurationError(
            "INVALID_RULES",
            "Goal-cessation rule fields are invalid.",
        )
    if set(external_change) != {"enabled"}:
        raise AutomationConfigurationError(
            "INVALID_RULES",
            "External-change rule fields are invalid.",
        )
    if set(freshness) != {
        "enabled",
        "direct_minutes",
        "metrika_minutes",
        "watermark_skew_minutes",
    }:
        raise AutomationConfigurationError(
            "INVALID_RULES",
            "Freshness rule fields are invalid.",
        )
    _enabled(budget["enabled"], "budget_pressure")
    _enabled(spend_growth["enabled"], "spend_growth_without_conversion")
    _enabled(no_conversion["enabled"], "no_conversion_spend")
    for name, rule in (
        ("pacing_ahead", pacing),
        ("cpc_deviation", cpc_deviation),
        ("ctr_deviation", ctr_deviation),
        ("conversion_rate_deviation", conversion_deviation),
        ("goal_cessation", goal_cessation),
        ("source_mismatch", source_mismatch),
        ("external_change", external_change),
        ("freshness", freshness),
    ):
        _enabled(rule["enabled"], name)
    budget_floor = int(
        policy["monitoring"]["anomaly_thresholds"]["budget_pressure_usage_percent"]
    )
    growth_floor = int(
        policy["monitoring"]["anomaly_thresholds"][
            "spend_growth_without_conversion_rub"
        ]
    )
    no_conversion_floor = int(
        policy["monitoring"]["anomaly_thresholds"]["no_conversion_spend_rub"]
    )
    safety_floor_checks = (
        (budget["threshold_percent"], budget_floor),
        (spend_growth["threshold_rub"], growth_floor),
        (no_conversion["threshold_rub"], no_conversion_floor),
    )
    if any(
        isinstance(value, int) and not isinstance(value, bool) and value < floor
        for value, floor in safety_floor_checks
    ):
        raise AutomationConfigurationError(
            "RULE_OUTSIDE_SAFETY_BOUNDARY",
            "Operator rules may tighten but cannot weaken Gate 0 thresholds.",
        )
    budget_threshold = _integer(
        budget["threshold_percent"],
        name="budget_pressure.threshold_percent",
        minimum=budget_floor,
        maximum=500,
    )
    growth_threshold = _integer(
        spend_growth["threshold_rub"],
        name="spend_growth_without_conversion.threshold_rub",
        minimum=growth_floor,
        maximum=100_000_000,
    )
    conversion_ceiling = _integer(
        spend_growth["maximum_conversion_growth_percent"],
        name="spend_growth_without_conversion.maximum_conversion_growth_percent",
        minimum=-100,
        maximum=0,
    )
    no_conversion_threshold = _integer(
        no_conversion["threshold_rub"],
        name="no_conversion_spend.threshold_rub",
        minimum=no_conversion_floor,
        maximum=100_000_000,
    )
    defaults = default_rules(policy)
    threshold_rules = {
        "pacing_ahead": pacing,
        "cpc_deviation": cpc_deviation,
        "ctr_deviation": ctr_deviation,
        "conversion_rate_deviation": conversion_deviation,
        "source_mismatch": source_mismatch,
    }
    validated_thresholds = {
        name: _integer(
            rule["threshold_percent"],
            name=f"{name}.threshold_percent",
            minimum=int(defaults[name]["threshold_percent"]),
            maximum=10_000,
        )
        for name, rule in threshold_rules.items()
    }
    goal_hours = _integer(
        goal_cessation["threshold_hours"],
        name="goal_cessation.threshold_hours",
        minimum=int(defaults["goal_cessation"]["threshold_hours"]),
        maximum=8_760,
    )
    goal_visits = _integer(
        goal_cessation["minimum_visits"],
        name="goal_cessation.minimum_visits",
        minimum=int(defaults["goal_cessation"]["minimum_visits"]),
        maximum=100_000_000,
    )
    freshness_values = {
        name: _integer(
            freshness[name],
            name=f"freshness.{name}",
            minimum=1,
            maximum=int(defaults["freshness"][name]),
        )
        for name in (
            "direct_minutes",
            "metrika_minutes",
            "watermark_skew_minutes",
        )
    }
    return {
        "budget_pressure": {
            "enabled": budget["enabled"],
            "threshold_percent": budget_threshold,
        },
        "spend_growth_without_conversion": {
            "enabled": spend_growth["enabled"],
            "threshold_rub": growth_threshold,
            "maximum_conversion_growth_percent": conversion_ceiling,
        },
        "no_conversion_spend": {
            "enabled": no_conversion["enabled"],
            "threshold_rub": no_conversion_threshold,
        },
        **{
            name: {
                "enabled": threshold_rules[name]["enabled"],
                "threshold_percent": value,
            }
            for name, value in validated_thresholds.items()
        },
        "goal_cessation": {
            "enabled": goal_cessation["enabled"],
            "threshold_hours": goal_hours,
            "minimum_visits": goal_visits,
        },
        "external_change": {
            "enabled": external_change["enabled"],
        },
        "freshness": {
            "enabled": freshness["enabled"],
            **freshness_values,
        },
    }


def _decimal(value: object, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise AutomationConfigurationError(
            "INVALID_METRICS",
            f"{name} is not a decimal metric.",
        ) from error
    if not parsed.is_finite():
        raise AutomationConfigurationError(
            "INVALID_METRICS",
            f"{name} is not finite.",
        )
    return parsed


def evaluate_triggers(
    snapshot: Mapping[str, Any],
    scenario: Mapping[str, Any],
    rules: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return all deterministic triggers matched by one trusted snapshot."""

    matched: list[dict[str, Any]] = []
    utilization = _decimal(
        snapshot["metrics"]["budget_utilization_percent"],
        "budget utilization",
    )
    utilization_text = format(utilization.normalize(), "f")
    budget_rule = rules["budget_pressure"]
    if budget_rule["enabled"] and utilization >= int(budget_rule["threshold_percent"]):
        matched.append(
            {
                "rule_id": "budget_pressure",
                "reason_code": "BUDGET_PRESSURE",
                "label": "Давление бюджета",
                "observed": f"{utilization_text}%",
                "threshold": f"≥ {budget_rule['threshold_percent']}%",
                "reason": (
                    "Использование недельного бюджета достигло "
                    f"{utilization_text}% при пороге "
                    f"{budget_rule['threshold_percent']}%."
                ),
            }
        )
    pacing = (
        Decimal(scenario["spend_rub"])
        / Decimal(scenario["expected_spend_rub"])
        * Decimal(100)
    )
    pacing_rule = rules["pacing_ahead"]
    if pacing_rule["enabled"] and pacing >= int(pacing_rule["threshold_percent"]):
        matched.append(
            {
                "rule_id": "pacing_ahead",
                "reason_code": "PACING_AHEAD",
                "label": "Расход опережает pacing",
                "observed": f"{pacing.quantize(Decimal('0.01'))}%",
                "threshold": f"≥ {pacing_rule['threshold_percent']}%",
                "reason": "Фактический расход опережает ожидаемый расход периода.",
            }
        )

    def deviation(
        *,
        rule_id: str,
        reason_code: str,
        label: str,
        current: Decimal | None,
        baseline: Decimal | None,
    ) -> None:
        rule = rules[rule_id]
        if not rule["enabled"] or current is None or baseline is None or baseline == 0:
            return
        value = abs((current - baseline) / baseline * Decimal(100))
        if value >= int(rule["threshold_percent"]):
            matched.append(
                {
                    "rule_id": rule_id,
                    "reason_code": reason_code,
                    "label": label,
                    "observed": f"{value.quantize(Decimal('0.01'))}%",
                    "threshold": f"≥ {rule['threshold_percent']}%",
                    "reason": f"{label} превысило заданный порог.",
                }
            )

    clicks = Decimal(scenario["clicks"])
    impressions = Decimal(scenario["impressions"])
    visits = Decimal(scenario["visits"])
    baseline_clicks = Decimal(scenario["baseline_clicks"])
    baseline_impressions = Decimal(scenario["baseline_impressions"])
    baseline_visits = Decimal(scenario["baseline_visits"])
    deviation(
        rule_id="cpc_deviation",
        reason_code="CPC_DEVIATION_FROM_BASELINE",
        label="Отклонение CPC от baseline",
        current=(Decimal(scenario["spend_rub"]) / clicks if clicks else None),
        baseline=(
            Decimal(scenario["baseline_spend_rub"]) / baseline_clicks
            if baseline_clicks
            else None
        ),
    )
    deviation(
        rule_id="ctr_deviation",
        reason_code="CTR_DEVIATION_FROM_BASELINE",
        label="Отклонение CTR от baseline",
        current=clicks / impressions * Decimal(100),
        baseline=baseline_clicks / baseline_impressions * Decimal(100),
    )
    deviation(
        rule_id="conversion_rate_deviation",
        reason_code="CONVERSION_RATE_DEVIATION_FROM_BASELINE",
        label="Отклонение conversion rate от baseline",
        current=(
            Decimal(scenario["conversions"]) / visits * Decimal(100) if visits else None
        ),
        baseline=(
            Decimal(scenario["baseline_conversions"]) / baseline_visits * Decimal(100)
        ),
    )
    goal_rule = rules["goal_cessation"]
    if (
        goal_rule["enabled"]
        and scenario["hours_since_last_conversion"] >= int(goal_rule["threshold_hours"])
        and scenario["visits"] >= int(goal_rule["minimum_visits"])
    ):
        matched.append(
            {
                "rule_id": "goal_cessation",
                "reason_code": "GOAL_CESSATION",
                "label": "Цель перестала срабатывать",
                "observed": (
                    f"{scenario['hours_since_last_conversion']} ч; "
                    f"{scenario['visits']} визитов"
                ),
                "threshold": (
                    f"≥ {goal_rule['threshold_hours']} ч; "
                    f"≥ {goal_rule['minimum_visits']} визитов"
                ),
                "reason": "Цель не срабатывала дольше допустимого окна.",
            }
        )
    mismatch_rule = rules["source_mismatch"]
    if mismatch_rule["enabled"] and scenario["source_mismatch_percent"] >= int(
        mismatch_rule["threshold_percent"]
    ):
        matched.append(
            {
                "rule_id": "source_mismatch",
                "reason_code": "SOURCE_MISMATCH",
                "label": "Расхождение источников",
                "observed": f"{scenario['source_mismatch_percent']}%",
                "threshold": f"≥ {mismatch_rule['threshold_percent']}%",
                "reason": "Расхождение Direct и Метрики превысило порог.",
            }
        )
    if rules["external_change"]["enabled"] and scenario["external_change"]:
        matched.append(
            {
                "rule_id": "external_change",
                "reason_code": "UNKNOWN_EXTERNAL_CHANGE",
                "label": "Внешнее изменение кампании",
                "observed": "обнаружено",
                "threshold": "отсутствует",
                "reason": "Fingerprint кампании изменён другим writer.",
            }
        )
    freshness_rule = rules["freshness"]
    if freshness_rule["enabled"]:
        for field, reason_code, label in (
            ("direct_age_minutes", "DIRECT_DATA_STALE", "Direct устарел"),
            ("metrika_age_minutes", "METRIKA_DATA_STALE", "Метрика устарела"),
            (
                "watermark_skew_minutes",
                "WATERMARK_SKEW_EXCEEDED",
                "Watermark источников расходится",
            ),
        ):
            threshold_name = {
                "direct_age_minutes": "direct_minutes",
                "metrika_age_minutes": "metrika_minutes",
                "watermark_skew_minutes": "watermark_skew_minutes",
            }[field]
            threshold = int(freshness_rule[threshold_name])
            if scenario[field] > threshold:
                matched.append(
                    {
                        "rule_id": "freshness",
                        "reason_code": reason_code,
                        "label": label,
                        "observed": f"{scenario[field]} мин",
                        "threshold": f"≤ {threshold} мин",
                        "reason": f"{label}: безопасная граница freshness нарушена.",
                    }
                )
    growth_rule = rules["spend_growth_without_conversion"]
    spend_growth = scenario["spend_rub"] - scenario["baseline_spend_rub"]
    baseline_conversions = scenario["baseline_conversions"]
    if baseline_conversions == 0:
        conversion_growth: Decimal | None = (
            Decimal(0) if scenario["conversions"] == 0 else None
        )
    else:
        conversion_growth = (
            Decimal(scenario["conversions"] - baseline_conversions)
            / Decimal(baseline_conversions)
            * Decimal(100)
        )
    if (
        growth_rule["enabled"]
        and spend_growth >= int(growth_rule["threshold_rub"])
        and conversion_growth is not None
        and conversion_growth <= int(growth_rule["maximum_conversion_growth_percent"])
    ):
        matched.append(
            {
                "rule_id": "spend_growth_without_conversion",
                "reason_code": "SPEND_GROWTH_WITHOUT_CONVERSION",
                "label": "Расход растёт без роста конверсий",
                "observed": (
                    f"+{spend_growth} ₽; конверсии "
                    f"{conversion_growth.quantize(Decimal('0.01'))}%"
                ),
                "threshold": (
                    f"≥ {growth_rule['threshold_rub']} ₽; конверсии "
                    f"≤ {growth_rule['maximum_conversion_growth_percent']}%"
                ),
                "reason": (
                    f"Расход вырос на {spend_growth} ₽, а изменение числа "
                    "конверсий не превысило заданный предел."
                ),
            }
        )
    no_conversion_rule = rules["no_conversion_spend"]
    if (
        no_conversion_rule["enabled"]
        and scenario["conversions"] == 0
        and scenario["spend_rub"] >= int(no_conversion_rule["threshold_rub"])
    ):
        matched.append(
            {
                "rule_id": "no_conversion_spend",
                "reason_code": "NO_CONVERSION_SPEND",
                "label": "Расход без конверсий",
                "observed": f"{scenario['spend_rub']} ₽; 0 конверсий",
                "threshold": f"≥ {no_conversion_rule['threshold_rub']} ₽",
                "reason": (
                    f"Расход достиг {scenario['spend_rub']} ₽, "
                    "но подтверждённых конверсий нет."
                ),
            }
        )
    return matched


class AutomationStore:
    """Persist one operator automation policy and its decision ledger."""

    def __init__(self, path: Path, policy: Mapping[str, Any]) -> None:
        self.path = path
        self.policy = policy
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute(
                "INSERT OR IGNORE INTO automation_settings "
                "(singleton, enabled, mode, operating_mode, interval_minutes, "
                "next_run_at, last_run_at, updated_at, rules_json, scenario_json, "
                "recommendation_rules_json) "
                "VALUES (1, 0, 'test', 'OBSERVE', 60, NULL, NULL, ?, ?, ?, ?)",
                (
                    _utc_text(datetime.now(timezone.utc)),
                    json.dumps(default_rules(policy), sort_keys=True),
                    json.dumps(DEFAULT_SCENARIO, sort_keys=True),
                    json.dumps(
                        default_recommendation_rules(policy),
                        sort_keys=True,
                    ),
                ),
            )
            connection.execute(
                "UPDATE automation_settings SET recommendation_rules_json = ? "
                "WHERE recommendation_rules_json IS NULL",
                (
                    json.dumps(
                        default_recommendation_rules(policy),
                        sort_keys=True,
                    ),
                ),
            )

    def settings(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT enabled, mode, operating_mode, interval_minutes, "
                "next_run_at, last_run_at, updated_at, rules_json, scenario_json, "
                "recommendation_rules_json "
                "FROM automation_settings WHERE singleton = 1"
            ).fetchone()
        if row is None:
            raise AutomationConfigurationError(
                "AUTOMATION_STATE_UNAVAILABLE",
                "Automation settings are unavailable.",
            )
        stored_rules = json.loads(row[7])
        merged_rules = default_rules(self.policy)
        for name, fields in stored_rules.items():
            if name in merged_rules and isinstance(fields, dict):
                merged_rules[name].update(fields)
        merged_scenario = deepcopy(DEFAULT_SCENARIO)
        merged_scenario.update(json.loads(row[8]))
        return {
            "enabled": bool(row[0]),
            "mode": row[1],
            "operating_mode": row[2],
            "interval_minutes": row[3],
            "next_run_at": row[4],
            "last_run_at": row[5],
            "updated_at": row[6],
            "rules": merged_rules,
            "scenario": merged_scenario,
            "recommendation_rules": json.loads(row[9]),
        }

    def configure(
        self,
        value: Mapping[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        allowed = {
            "enabled",
            "mode",
            "operating_mode",
            "interval_minutes",
            "next_run_at",
            "last_run_at",
            "updated_at",
            "rules",
            "scenario",
            "recommendation_rules",
        }
        required = {
            "enabled",
            "mode",
            "operating_mode",
            "interval_minutes",
            "rules",
            "scenario",
            "recommendation_rules",
        }
        if not required.issubset(value) or not set(value).issubset(allowed):
            raise AutomationConfigurationError(
                "INVALID_AUTOMATION_SETTINGS",
                "Automation settings contain unsupported fields.",
            )
        enabled = value["enabled"]
        if not isinstance(enabled, bool):
            raise AutomationConfigurationError(
                "INVALID_AUTOMATION_SETTINGS",
                "Automation enabled must be boolean.",
            )
        mode = value["mode"]
        if mode != "test":
            raise AutomationConfigurationError(
                "TEST_AUTOMATION_ONLY",
                "Automation settings support only the test mode.",
            )
        operating_mode = value["operating_mode"]
        if operating_mode not in OPERATING_MODES:
            raise AutomationConfigurationError(
                "INVALID_OPERATING_MODE",
                "Automation settings contain an unknown operating mode.",
            )
        interval = _integer(
            value["interval_minutes"],
            name="interval_minutes",
            minimum=1,
            maximum=10_080,
        )
        rules = validate_rules(self.policy, value["rules"])
        scenario = validate_scenario(value["scenario"])
        recommendation_rules = validate_recommendation_rules(
            self.policy,
            value["recommendation_rules"],
        )
        current = self.settings()
        changed = (
            current["mode"] != mode
            or current["operating_mode"] != operating_mode
            or current["interval_minutes"] != interval
            or current["rules"] != rules
            or current["scenario"] != scenario
            or current["recommendation_rules"] != recommendation_rules
        )
        at = _utc(now)
        if not enabled:
            next_run_at = None
        elif not current["enabled"] or changed:
            next_run_at = _utc_text(at)
        else:
            next_run_at = current["next_run_at"] or _utc_text(at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE automation_settings SET enabled = ?, mode = ?, "
                "operating_mode = ?, interval_minutes = ?, next_run_at = ?, "
                "updated_at = ?, "
                "rules_json = ?, scenario_json = ?, "
                "recommendation_rules_json = ? WHERE singleton = 1",
                (
                    int(enabled),
                    mode,
                    operating_mode,
                    interval,
                    next_run_at,
                    _utc_text(at),
                    json.dumps(rules, sort_keys=True),
                    json.dumps(scenario, sort_keys=True),
                    json.dumps(recommendation_rules, sort_keys=True),
                ),
            )
            connection.commit()
        return self.settings()

    def claim_due(self, now: datetime) -> dict[str, Any] | None:
        at = _utc(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT enabled, interval_minutes, next_run_at "
                "FROM automation_settings WHERE singleton = 1"
            ).fetchone()
            if row is None or not bool(row[0]):
                connection.rollback()
                return None
            next_at = at if row[2] is None else _parse_utc(row[2])
            if next_at > at:
                connection.rollback()
                return None
            following = at + timedelta(minutes=int(row[1]))
            connection.execute(
                "UPDATE automation_settings SET last_run_at = ?, "
                "next_run_at = ? WHERE singleton = 1",
                (_utc_text(at), _utc_text(following)),
            )
            connection.commit()
        return self.settings()

    def record_report(self, report: Mapping[str, Any]) -> None:
        decision = report["decision"]
        recommendation = report["recommendation"]
        execution = report["execution"]
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO decision_history "
                "(run_id, created_at, origin, mode, status, "
                "matched_triggers_json, reason, action, execution_status, "
                "report_href) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    report["run_id"],
                    report["created_at"],
                    report["origin"],
                    report["mode"],
                    report["status"],
                    json.dumps(
                        decision["matched_triggers"],
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    decision["reason"],
                    recommendation["action"],
                    execution["status"],
                    report["artifacts"]["html"],
                ),
            )

    def record_failure(
        self,
        *,
        occurred_at: datetime,
        reason_code: str,
        message: str,
    ) -> None:
        """Persist a visible ledger entry when a scheduled cycle cannot run."""

        at = _utc(occurred_at)
        run_id = "automation-error-" + at.strftime("%Y%m%dT%H%M%S%fZ")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO decision_history "
                "(run_id, created_at, origin, mode, status, "
                "matched_triggers_json, reason, action, execution_status, "
                "report_href) VALUES (?, ?, 'SCHEDULED', 'TEST', 'FAILED', "
                "'[]', ?, 'NO_CHANGE', 'BLOCKED', '')",
                (
                    run_id,
                    _utc_text(at),
                    f"{reason_code}: {message}",
                ),
            )

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int):
            limit = 20
        limit = min(max(limit, 1), 100)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT run_id, created_at, origin, mode, status, "
                "matched_triggers_json, reason, action, execution_status, "
                "report_href FROM decision_history "
                "ORDER BY created_at DESC, run_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "run_id": row[0],
                "created_at": row[1],
                "origin": row[2],
                "mode": row[3],
                "status": row[4],
                "matched_triggers": json.loads(row[5]),
                "reason": row[6],
                "action": row[7],
                "execution_status": row[8],
                "report_href": row[9],
            }
            for row in rows
        ]

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=5)
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS automation_settings ("
            "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
            "enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)), "
            "mode TEXT NOT NULL CHECK (mode IN ('test', 'production')), "
            "operating_mode TEXT NOT NULL DEFAULT 'OBSERVE', "
            "interval_minutes INTEGER NOT NULL, "
            "next_run_at TEXT, "
            "last_run_at TEXT, "
            "updated_at TEXT NOT NULL, "
            "rules_json TEXT NOT NULL, "
            "scenario_json TEXT NOT NULL, "
            "recommendation_rules_json TEXT)"
        )
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(automation_settings)"
            ).fetchall()
        }
        if "recommendation_rules_json" not in columns:
            connection.execute(
                "ALTER TABLE automation_settings "
                "ADD COLUMN recommendation_rules_json TEXT"
            )
        if "operating_mode" not in columns:
            connection.execute(
                "ALTER TABLE automation_settings "
                "ADD COLUMN operating_mode TEXT NOT NULL DEFAULT 'OBSERVE'"
            )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS decision_history ("
            "run_id TEXT PRIMARY KEY, "
            "created_at TEXT NOT NULL, "
            "origin TEXT NOT NULL, "
            "mode TEXT NOT NULL, "
            "status TEXT NOT NULL, "
            "matched_triggers_json TEXT NOT NULL, "
            "reason TEXT NOT NULL, "
            "action TEXT NOT NULL, "
            "execution_status TEXT NOT NULL, "
            "report_href TEXT NOT NULL)"
        )
