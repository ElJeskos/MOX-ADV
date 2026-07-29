"""Sanitized, aggregate-only projection for the model boundary."""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator, Mapping, Optional

from mox_adv.recommend_contracts import (
    _OPTIMIZATION_ACTIONS,
    SchemaValidationError,
    _closed,
    _code,
    _code_list,
    _copy_json,
    _integer,
    _parse_utc,
    _text,
)

_URL = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
_PROHIBITED_TEXT = re.compile(
    r"(?:"
    r"\b(?:bearer|oauth|token|secret|credential|endpoint)\b"
    r"|(?:raw\s+)?search\s+quer"
    r"|\butm_[a-z_]*\b"
    r"|\byclid\b"
    r"|\bapi\.[a-z0-9.-]+"
    r"|\b(?:ignore|disregard)\s+(?:all|any|the|previous)\b"
    r"|\b(?:system\s+prompt|developer\s+message)\b"
    r")",
    re.IGNORECASE,
)
_COMPLEX_FIELDS = frozenset(
    {
        "attribution",
        "freshness",
        "comparability",
        "observed_facts",
        "business_goal",
        "allowed_change_history",
        "policy_limits",
    }
)
_SCALAR_FIELDS = frozenset(
    {
        "schema_version",
        "period_start",
        "period_end",
        "timezone",
        "campaign_state",
        "campaign_strategy",
        "current_budget",
        "current_bid",
        "current_ad_variant",
        "impressions",
        "clicks",
        "cost_micros",
        "visits",
        "goal_visits",
        "ctr",
        "cpc",
        "conversion_rate",
        "cpa",
        "budget_utilization",
    }
)
PROJECTION_FIELDS = _COMPLEX_FIELDS | _SCALAR_FIELDS
_POLICY_LIMIT_FIELDS = frozenset(
    {
        "budget_pressure_usage_percent",
        "cpa_target_rub",
        "maximum_step_percent",
        "observation_window_hours",
        "no_conversion_stop_spend_rub",
        "minimum_clicks",
        "minimum_conversions",
        "source_mismatch_percent",
    }
)
_PROHIBITED_KEYS = frozenset(
    {
        "organization",
        "connection",
        "account",
        "campaign",
        "counter",
        "goal",
        "id",
        "object_id",
        "oauth_token",
        "token",
        "secret",
        "credential",
        "credential_profile",
        "endpoint",
        "url",
        "raw_url",
        "search_query",
        "raw_search_query",
        "source_text",
        "http_payload",
        "payload",
    }
)
_CHANGE_OUTCOMES = frozenset(
    {
        "APPLIED",
        "NO_CHANGE",
        "BLOCKED",
        "ALREADY_PROCESSED",
        "UNKNOWN_RESULT",
        "FAILED",
        "PARTIALLY_APPLIED",
        "COMPENSATION_REQUIRED",
    }
)
_PROJECTION_CONSTRUCTION_TOKEN = object()


class SanitizedProjection(Mapping[str, Any]):
    """Read-only projection created only by the trusted Gate 0 builder."""

    def __init__(
        self,
        value: Mapping[str, Any],
        token: object,
    ) -> None:
        if token is not _PROJECTION_CONSTRUCTION_TOKEN:
            raise TypeError("Use build_sanitized_projection.")
        self._data = deepcopy(dict(value))

    def __getitem__(self, key: str) -> Any:
        return deepcopy(self._data[key])

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


def _reject_prohibited_content(value: Any, path: str = "projection") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            lowered = str(key).lower()
            if (
                lowered in _PROHIBITED_KEYS
                or lowered.endswith("_id")
                or lowered.endswith("_url")
                or "token" in lowered
                or "secret" in lowered
                or "credential" in lowered
                or "endpoint" in lowered
                or "query" in lowered
            ):
                raise SchemaValidationError(path + " contains prohibited content.")
            _reject_prohibited_content(nested, path + "." + str(key))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_prohibited_content(nested, path + "[" + str(index) + "]")
    elif isinstance(value, str):
        if _URL.search(value):
            raise SchemaValidationError(path + " contains a raw URL.")
        if _PROHIBITED_TEXT.search(value):
            raise SchemaValidationError(path + " contains prohibited text.")


def _metric_decimal(value: Any, label: str) -> Optional[Decimal]:
    if value == "NOT_APPLICABLE":
        return None
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise SchemaValidationError(label + " must be a decimal metric.") from error
    if not parsed.is_finite() or parsed < 0:
        raise SchemaValidationError(
            label + " must be a finite non-negative metric."
        )
    return parsed


def supported_facts(projection: Mapping[str, Any]) -> frozenset[str]:
    limits = projection["policy_limits"]
    comparability = projection["comparability"]
    if comparability["status"] != "COMPARABLE":
        return frozenset({"SOURCE_MISMATCH"})
    if comparability["confidence"] == "INSUFFICIENT_DATA":
        return frozenset({"SAMPLE_BELOW_GATE0_MINIMUM"})
    facts = set()
    utilization = _metric_decimal(
        projection["budget_utilization"],
        "Projection budget_utilization",
    )
    cpa = _metric_decimal(projection["cpa"], "Projection cpa")
    if (
        utilization is not None
        and utilization >= limits["budget_pressure_usage_percent"]
    ):
        facts.add("BUDGET_UTILIZATION_AT_OR_ABOVE_THRESHOLD")
    if cpa is not None and cpa <= limits["cpa_target_rub"]:
        facts.add("CPA_AT_OR_BELOW_TARGET")
    if projection["goal_visits"] == 0:
        facts.add("NO_CONVERSIONS")
        if projection["cost_micros"] >= (
            limits["no_conversion_stop_spend_rub"] * 1_000_000
        ):
            facts.add("NO_CONVERSION_SPEND_AT_OR_ABOVE_THRESHOLD")
    return frozenset(facts)


def validate_projection(projection: Mapping[str, Any]) -> None:
    _closed(projection, PROJECTION_FIELDS, "Sanitized projection")
    _reject_prohibited_content(projection)
    for name in _SCALAR_FIELDS:
        value = projection[name]
        if name in {
            "current_budget",
            "current_bid",
            "impressions",
            "clicks",
            "cost_micros",
            "visits",
            "goal_visits",
        }:
            _integer(value, "Projection " + name)
        else:
            _text(value, "Projection " + name, maximum=128)
    if projection["schema_version"] != "llm-projection-v1":
        raise SchemaValidationError("Projection schema version is unsupported.")
    for name in ("period_start", "period_end"):
        try:
            date.fromisoformat(projection[name])
        except ValueError as error:
            raise SchemaValidationError(
                "Projection " + name + " must be an ISO date."
            ) from error
    if projection["timezone"] != "UTC":
        raise SchemaValidationError("Projection timezone must be UTC.")
    if projection["campaign_state"] not in {"ON", "SUSPENDED"}:
        raise SchemaValidationError("Projection campaign state is unsupported.")
    if projection["campaign_strategy"] != "HIGHEST_POSITION":
        raise SchemaValidationError("Projection campaign strategy is unsupported.")
    if projection["current_ad_variant"] not in {"A", "B"}:
        raise SchemaValidationError("Projection ad variant is unsupported.")
    for name in ("ctr", "cpc", "conversion_rate", "cpa", "budget_utilization"):
        _metric_decimal(projection[name], "Projection " + name)
    attribution = projection["attribution"]
    _closed(attribution, ("direct", "metrika"), "Projection attribution")
    if attribution != {"direct": "AUTO", "metrika": "automatic"}:
        raise SchemaValidationError("Projection attribution is unsupported.")
    freshness = projection["freshness"]
    _closed(
        freshness,
        ("direct_minutes", "metrika_minutes", "watermark_skew_minutes"),
        "Projection freshness",
    )
    for name in freshness:
        _integer(freshness[name], "Projection freshness " + name)
    comparability = projection["comparability"]
    _closed(
        comparability,
        ("status", "confidence", "financial_recommendations_allowed"),
        "Projection comparability",
    )
    if comparability["status"] not in {"COMPARABLE", "PARTIAL", "INCOMPATIBLE"}:
        raise SchemaValidationError("Projection comparability status is invalid.")
    if comparability["confidence"] not in {
        "READY",
        "INSUFFICIENT_DATA",
        "STALE_DATA",
    }:
        raise SchemaValidationError("Projection confidence is invalid.")
    if not isinstance(comparability["financial_recommendations_allowed"], bool):
        raise SchemaValidationError(
            "Projection financial recommendation flag must be boolean."
        )
    _code_list(
        projection["observed_facts"],
        "Projection observed facts",
        nonempty=True,
    )
    business_goal = projection["business_goal"]
    _closed(business_goal, ("event", "meaning"), "Projection business goal")
    _text(business_goal["event"], "Business goal event", maximum=128)
    _text(business_goal["meaning"], "Business goal meaning", maximum=500)
    history = projection["allowed_change_history"]
    if not isinstance(history, list) or len(history) > 32:
        raise SchemaValidationError(
            "Projection allowed change history must be an array."
        )
    for item in history:
        _closed(
            item,
            ("action", "occurred_at", "outcome"),
            "Allowed change history item",
        )
        action = _code(item["action"], "Allowed change action")
        if action not in _OPTIMIZATION_ACTIONS:
            raise SchemaValidationError(
                "Allowed change history action is unsupported."
            )
        _parse_utc(item["occurred_at"], "Allowed change timestamp")
        outcome = _code(item["outcome"], "Allowed change outcome")
        if outcome not in _CHANGE_OUTCOMES:
            raise SchemaValidationError(
                "Allowed change history outcome is unsupported."
            )
    limits = projection["policy_limits"]
    _closed(
        limits,
        _POLICY_LIMIT_FIELDS,
        "Projection policy limits",
    )
    for name, value in limits.items():
        _integer(value, "Projection policy limit " + name)
    if set(projection["observed_facts"]) != supported_facts(projection):
        raise SchemaValidationError(
            "Projection observed facts are not supported by its metrics."
        )


def build_sanitized_projection(
    snapshot: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> SanitizedProjection:
    """Copy only the Gate 0 allowlist and derive all trusted semantic fields."""

    try:
        allowed = set(policy["llm"]["allowed_projection_fields"])
    except (KeyError, TypeError) as error:
        raise SchemaValidationError(
            "Gate 0 does not define the LLM projection allowlist."
        ) from error
    if allowed != PROJECTION_FIELDS:
        raise SchemaValidationError(
            "Gate 0 LLM projection allowlist does not match this schema version."
        )
    projection = {
        key: _copy_json(snapshot[key], "Projection " + key)
        for key in snapshot
        if key in allowed
    }
    try:
        primary = policy["conversion"]["primary"]
        projection["business_goal"] = {
            "event": primary["event"],
            "meaning": primary["business_meaning"],
        }
        projection["policy_limits"] = {
            "budget_pressure_usage_percent": policy["monitoring"][
                "anomaly_thresholds"
            ]["budget_pressure_usage_percent"],
            "cpa_target_rub": policy["mandate"]["kpi"]["target_maximum"],
            "maximum_step_percent": policy["limits"]["maximum_step_percent"],
            "observation_window_hours": policy["timing"][
                "observation_window_hours"
            ],
            "no_conversion_stop_spend_rub": policy["limits"][
                "no_conversion_stop_spend_rub"
            ],
            "minimum_clicks": policy["mandate"]["minimum_sample"]["clicks"],
            "minimum_conversions": policy["mandate"]["minimum_sample"][
                "conversions"
            ],
            "source_mismatch_percent": policy["monitoring"]["anomaly_thresholds"][
                "source_mismatch_percent"
            ],
        }
    except (KeyError, TypeError) as error:
        raise SchemaValidationError(
            "Gate 0 does not define trusted LLM projection values."
        ) from error
    projection["observed_facts"] = list(supported_facts(projection))
    validate_projection(projection)
    return SanitizedProjection(projection, _PROJECTION_CONSTRUCTION_TOKEN)
