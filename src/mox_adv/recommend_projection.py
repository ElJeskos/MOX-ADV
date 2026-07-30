"""Sanitized, aggregate-only projection for the model boundary."""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import date, datetime, timezone
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
    _canonical_hash,
)
from mox_adv.contracts import IntegratedPerformanceSnapshot
from mox_adv.normalization import IntegratedSnapshotNormalizerV1

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


def campaign_fingerprint(snapshot: IntegratedPerformanceSnapshot) -> str:
    """Seal the exact trusted campaign state used by executor readback."""

    if (
        type(snapshot) is not IntegratedPerformanceSnapshot
        or not IntegratedSnapshotNormalizerV1.verify_fingerprint(snapshot.as_dict())
    ):
        raise SchemaValidationError("Trusted snapshot fingerprint is invalid.")
    return campaign_fingerprint_mapping(snapshot.as_dict())


def campaign_fingerprint_mapping(snapshot: Mapping[str, Any]) -> str:
    """Verify and fingerprint a persisted integrated snapshot mapping."""

    if not IntegratedSnapshotNormalizerV1.verify_fingerprint(snapshot):
        raise SchemaValidationError("Trusted snapshot fingerprint is invalid.")
    try:
        scope = snapshot["scope"]
        campaign = snapshot["campaign"]
        policy_version = snapshot["policy_version"]
    except (KeyError, TypeError) as error:
        raise SchemaValidationError("Trusted snapshot campaign is invalid.") from error
    return _canonical_hash(
        {
            "policy_version": policy_version,
            "scope": {
                "organization": scope["organization"],
                "connection": scope["connection"],
                "account": scope["account"],
                "campaign": scope["campaign"],
            },
            "campaign": {
                "state": campaign["state"],
                "strategy": campaign["strategy"],
                "current_weekly_budget_micros": (
                    campaign["current_weekly_budget_micros"]
                ),
                "current_search_bid_micros": (
                    campaign["current_search_bid_micros"]
                ),
                "current_ad_variant": campaign["current_ad_variant"],
                "object_config_version": campaign["object_config_version"],
            },
        }
    )


def projection_from_integrated_snapshot(
    snapshot: IntegratedPerformanceSnapshot,
    policy: Mapping[str, Any],
    evaluated_at: datetime,
) -> SanitizedProjection:
    """Derive the model projection only from one verified integrated snapshot."""

    campaign_fingerprint(snapshot)
    if evaluated_at.tzinfo is None:
        raise SchemaValidationError("Projection evaluation time must be aware.")
    evaluated = evaluated_at.astimezone(timezone.utc)

    def parsed(value: str) -> datetime:
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as error:
            raise SchemaValidationError(
                "Trusted snapshot timestamp is invalid."
            ) from error
        if result.tzinfo is None:
            raise SchemaValidationError(
                "Trusted snapshot timestamp must be timezone-aware."
            )
        return result.astimezone(timezone.utc)

    generated_at = parsed(snapshot.generated_at)
    direct_times = (
        parsed(snapshot.provenance.direct_report.retrieved_at),
        parsed(snapshot.provenance.direct_state.retrieved_at),
    )
    metrika_time = parsed(snapshot.provenance.metrika_report.retrieved_at)
    watermarks = (
        parsed(snapshot.provenance.direct_report.watermark),
        parsed(snapshot.provenance.direct_state.watermark),
        parsed(snapshot.provenance.metrika_report.watermark),
    )
    if evaluated < generated_at or any(
        value > evaluated
        for value in (*direct_times, metrika_time, *watermarks)
    ):
        raise SchemaValidationError(
            "Projection evaluation cannot precede trusted snapshot evidence."
        )

    def age_minutes(value: datetime) -> int:
        return max(0, int((evaluated - value).total_seconds() // 60))

    metrics = snapshot.metrics
    seed = {
        "schema_version": "llm-projection-v1",
        "period_start": snapshot.period_start,
        "period_end": snapshot.period_end,
        "timezone": snapshot.timezone,
        "attribution": {
            "direct": snapshot.attribution.direct,
            "metrika": snapshot.attribution.metrika,
        },
        "campaign_state": snapshot.campaign.state,
        "campaign_strategy": snapshot.campaign.strategy,
        "current_budget": snapshot.campaign.current_weekly_budget_micros,
        "current_bid": snapshot.campaign.current_search_bid_micros,
        "current_ad_variant": snapshot.campaign.current_ad_variant,
        "impressions": metrics["impressions"],
        "clicks": metrics["clicks"],
        "cost_micros": metrics["cost_micros"],
        "visits": metrics["visits"],
        "goal_visits": metrics["goal_visits"],
        "ctr": metrics["ctr_percent"],
        "cpc": metrics["cpc_rub"],
        "conversion_rate": metrics["conversion_rate_percent"],
        "cpa": metrics["cpa_rub"],
        "budget_utilization": metrics["budget_utilization_percent"],
        "freshness": {
            "direct_minutes": max(age_minutes(value) for value in direct_times),
            "metrika_minutes": age_minutes(metrika_time),
            "watermark_skew_minutes": int(
                (max(watermarks) - min(watermarks)).total_seconds() // 60
            ),
        },
        "comparability": {
            "status": snapshot.comparability_status,
            "confidence": snapshot.confidence_status,
            "financial_recommendations_allowed": (
                snapshot.financial_recommendations_allowed
            ),
        },
        "observed_facts": [],
        "business_goal": {
            "event": snapshot.business_goal.event,
            "meaning": snapshot.business_goal.meaning,
        },
        "allowed_change_history": [],
        "policy_limits": {},
    }
    return build_sanitized_projection(seed, policy)
