"""Closed contracts and projection validation for LLM recommendations."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, Optional, Protocol, Tuple


class SchemaValidationError(ValueError):
    """A closed contract or sanitized projection is invalid."""


class ProposalConflictError(RuntimeError):
    """An immutable proposal identifier was reused for different content."""


_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SAFE_IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$")
_SAFE_FIELD_PATH = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_CYRILLIC = re.compile(r"[А-Яа-яЁё]")
_OPTIMIZATION_ACTIONS = frozenset(
    {
        "KEEP",
        "INCREASE_WEEKLY_BUDGET",
        "DECREASE_WEEKLY_BUDGET",
        "INCREASE_SEARCH_BID",
        "DECREASE_SEARCH_BID",
        "SET_AD_VARIANT",
        "SUSPEND_CAMPAIGN",
        "RESUME_CAMPAIGN",
        "REQUEST_HUMAN_HELP",
    }
)
_STATUS_ACTIONS = {
    "EFFECTIVE": frozenset(
        {
            "KEEP",
            "INCREASE_WEEKLY_BUDGET",
            "INCREASE_SEARCH_BID",
            "RESUME_CAMPAIGN",
        }
    ),
    "INEFFECTIVE": frozenset(
        {
            "KEEP",
            "DECREASE_WEEKLY_BUDGET",
            "DECREASE_SEARCH_BID",
            "SET_AD_VARIANT",
            "SUSPEND_CAMPAIGN",
        }
    ),
    "INSUFFICIENT_DATA": frozenset({"KEEP"}),
    "NEEDS_HUMAN": frozenset({"REQUEST_HUMAN_HELP"}),
}
_MODEL_PAYLOAD_FIELDS = frozenset(
    {
        "status",
        "observed_facts",
        "hypotheses",
        "actions",
        "evidence_fields",
        "expected_effect_direction",
        "minimum_observation_window_hours",
        "risks",
        "preconditions",
        "rollback_condition",
        "missing_data_requests",
        "expected_diff",
        "explanation_ru",
    }
)
_PROPOSAL_FIELDS = frozenset(
    {
        "proposal_id",
        "proposal_version",
        "run_id",
        "snapshot_id",
        "created_at",
        "expires_at",
        "status",
        "observed_facts",
        "hypotheses",
        "actions",
        "evidence_fields",
        "expected_effect_direction",
        "minimum_observation_window_hours",
        "risks",
        "preconditions",
        "rollback_condition",
        "missing_data_requests",
        "expected_diff",
        "expected_fingerprint",
        "explanation_ru",
    }
)
_ACTION_FIELDS = frozenset(
    {
        "action",
        "parameters",
        "dependencies",
        "limits",
        "rollback_conditions",
    }
)
_HYPOTHESIS_FIELDS = frozenset({"rank", "code"})
_REASON_CODES = frozenset(
    {
        "INVALID_INPUT",
        "AMBIGUOUS_DATA",
        "UNSUPPORTED_STATE",
        "UNSUPPORTED_ACTION",
        "AGENT_ERROR",
        "API_ERROR",
        "OUT_OF_BOUNDS",
        "UNKNOWN_RESULT",
    }
)
_FACT_EVIDENCE = {
    "BUDGET_UTILIZATION_AT_OR_ABOVE_THRESHOLD": frozenset(
        {"budget_utilization", "policy_limits"}
    ),
    "CPA_AT_OR_BELOW_TARGET": frozenset({"cpa", "policy_limits"}),
    "NO_CONVERSIONS": frozenset({"goal_visits"}),
    "NO_CONVERSION_SPEND_AT_OR_ABOVE_THRESHOLD": frozenset(
        {"cost_micros", "policy_limits"}
    ),
    "SAMPLE_BELOW_GATE0_MINIMUM": frozenset(
        {"clicks", "goal_visits", "policy_limits"}
    ),
    "SOURCE_MISMATCH": frozenset({"comparability"}),
}


def _closed(
    value: Mapping[str, Any],
    fields: Iterable[str],
    label: str,
    required: Optional[Iterable[str]] = None,
) -> None:
    if not isinstance(value, Mapping):
        raise SchemaValidationError(label + " must be an object.")
    allowed = set(fields)
    actual = set(value)
    unknown = actual - allowed
    required_fields = allowed if required is None else set(required)
    missing = required_fields - actual
    if unknown:
        raise SchemaValidationError(
            label + " contains unknown fields: " + ", ".join(sorted(unknown)) + "."
        )
    if missing:
        raise SchemaValidationError(
            label + " is missing fields: " + ", ".join(sorted(missing)) + "."
        )


def _text(
    value: Any,
    label: str,
    minimum: int = 1,
    maximum: int = 500,
) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise SchemaValidationError(
            label + " must be a string with an allowed length."
        )
    return value


def _integer(
    value: Any,
    label: str,
    minimum: int = 0,
    maximum: Optional[int] = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SchemaValidationError(label + " must be an allowed integer.")
    if maximum is not None and value > maximum:
        raise SchemaValidationError(label + " exceeds the allowed maximum.")
    return value


def _code(value: Any, label: str) -> str:
    text = _text(value, label, maximum=64)
    if _SAFE_CODE.fullmatch(text) is None:
        raise SchemaValidationError(label + " must be a closed reason code.")
    return text


def _code_list(
    value: Any,
    label: str,
    maximum: int = 32,
    nonempty: bool = False,
) -> Tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum:
        raise SchemaValidationError(label + " must be an allowed array.")
    if nonempty and not value:
        raise SchemaValidationError(label + " must not be empty.")
    result = tuple(_code(item, label + " item") for item in value)
    if len(set(result)) != len(result):
        raise SchemaValidationError(label + " must contain unique values.")
    return result


def _evidence_list(value: Any) -> Tuple[str, ...]:
    if not isinstance(value, list) or not value or len(value) > 32:
        raise SchemaValidationError("Evidence fields must be a non-empty array.")
    result = tuple(_text(item, "Evidence field", maximum=64) for item in value)
    if any(_SAFE_FIELD_PATH.fullmatch(item) is None for item in result):
        raise SchemaValidationError("Evidence field path is invalid.")
    if len(set(result)) != len(result):
        raise SchemaValidationError("Evidence fields must contain unique values.")
    return result


def _parse_utc(value: Any, label: str) -> datetime:
    text = _text(value, label, maximum=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise SchemaValidationError(label + " must be an ISO timestamp.") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise SchemaValidationError(label + " must use UTC.")
    return parsed.astimezone(timezone.utc)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _canonical_hash(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _copy_json(value: Any, label: str) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError) as error:
        raise SchemaValidationError(label + " must contain JSON values.") from error


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(nested) for key, nested in value.items()}
        )
    if isinstance(value, list) or isinstance(value, tuple):
        return tuple(_freeze_json(nested) for nested in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(nested) for nested in value]
    return value


@dataclass(frozen=True)
class ProviderMetadata:
    provider: str
    model_id: str
    input_tokens: int
    output_tokens: int
    cost_rub: str
    duration_ms: int

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelResponse:
    payload: Mapping[str, Any]
    provider: str
    model_id: str
    input_tokens: int
    output_tokens: int
    cost_rub: str
    duration_ms: int

    def metadata(self) -> ProviderMetadata:
        _text(self.provider, "Provider", maximum=128)
        _text(self.model_id, "Model ID", maximum=128)
        _integer(self.input_tokens, "Input tokens")
        _integer(self.output_tokens, "Output tokens")
        _text(self.cost_rub, "Provider cost", maximum=32)
        _integer(self.duration_ms, "Provider duration")
        return ProviderMetadata(
            provider=self.provider,
            model_id=self.model_id,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cost_rub=self.cost_rub,
            duration_ms=self.duration_ms,
        )


class ModelProvider(Protocol):
    """A model boundary that receives only a sanitized projection."""

    def generate(self, projection: Mapping[str, Any]) -> ModelResponse: ...


def _validate_action(value: Any, status: str) -> Dict[str, Any]:
    _closed(value, _ACTION_FIELDS, "Atomic action")
    action = value["action"]
    if action not in _OPTIMIZATION_ACTIONS:
        raise SchemaValidationError("Atomic action is unsupported.")
    if action not in _STATUS_ACTIONS[status]:
        raise SchemaValidationError("Atomic action is invalid for proposal status.")
    parameters = value["parameters"]
    if not isinstance(parameters, Mapping):
        raise SchemaValidationError("Action parameters must be an object.")
    if action == "SET_AD_VARIANT":
        _closed(parameters, ("variant_id",), "SET_AD_VARIANT parameters")
        if parameters["variant_id"] not in {"A", "B"}:
            raise SchemaValidationError("Ad variant must be A or B.")
    elif action == "REQUEST_HUMAN_HELP":
        _closed(parameters, ("reason_code",), "Human help parameters")
        if parameters["reason_code"] not in _REASON_CODES:
            raise SchemaValidationError("Human help reason code is unsupported.")
    else:
        _closed(parameters, (), "Action parameters")
    dependencies = _code_list(value["dependencies"], "Action dependencies")
    limits = _code_list(value["limits"], "Action limits")
    rollback = _code_list(
        value["rollback_conditions"],
        "Action rollback conditions",
    )
    return {
        "action": action,
        "parameters": dict(parameters),
        "dependencies": list(dependencies),
        "limits": list(limits),
        "rollback_conditions": list(rollback),
    }


def _validate_expected_diff(value: Any, action: str) -> Dict[str, Any]:
    allowed_by_action = {
        "KEEP": ("operation",),
        "REQUEST_HUMAN_HELP": ("operation",),
        "INCREASE_WEEKLY_BUDGET": ("operation", "relative_step_percent"),
        "DECREASE_WEEKLY_BUDGET": ("operation", "relative_step_percent"),
        "INCREASE_SEARCH_BID": ("operation", "relative_step_percent"),
        "DECREASE_SEARCH_BID": ("operation", "relative_step_percent"),
        "SET_AD_VARIANT": ("operation", "variant_id"),
        "SUSPEND_CAMPAIGN": ("operation", "target_state"),
        "RESUME_CAMPAIGN": ("operation", "target_state"),
    }
    _closed(value, allowed_by_action[action], "Expected diff")
    if value["operation"] != (
        "NO_CHANGE" if action in {"KEEP", "REQUEST_HUMAN_HELP"} else action
    ):
        raise SchemaValidationError("Expected diff operation does not match action.")
    if "relative_step_percent" in value:
        _integer(
            value["relative_step_percent"],
            "Expected relative step",
            minimum=1,
            maximum=100,
        )
    if action == "SET_AD_VARIANT" and value["variant_id"] not in {"A", "B"}:
        raise SchemaValidationError("Expected diff ad variant is invalid.")
    if action == "SUSPEND_CAMPAIGN" and value["target_state"] != "SUSPENDED":
        raise SchemaValidationError("Suspend diff target is invalid.")
    if action == "RESUME_CAMPAIGN" and value["target_state"] != "ON":
        raise SchemaValidationError("Resume diff target is invalid.")
    return dict(value)


def _validate_model_payload(
    value: Mapping[str, Any],
    projection: Mapping[str, Any],
) -> Dict[str, Any]:
    _closed(value, _MODEL_PAYLOAD_FIELDS, "Model payload")
    status = value["status"]
    if status not in _STATUS_ACTIONS:
        raise SchemaValidationError("Proposal status is unsupported.")
    observed_facts = _code_list(
        value["observed_facts"],
        "Observed facts",
        nonempty=True,
    )
    projected_facts = _code_list(
        projection.get("observed_facts"),
        "Projected observed facts",
        nonempty=True,
    )
    if not set(observed_facts).issubset(projected_facts):
        raise SchemaValidationError(
            "Observed facts must be supported by the sanitized projection."
        )
    hypotheses_value = value["hypotheses"]
    if not isinstance(hypotheses_value, list) or len(hypotheses_value) > 3:
        raise SchemaValidationError("Hypotheses must contain at most three items.")
    hypotheses = []
    for expected_rank, hypothesis in enumerate(hypotheses_value, start=1):
        _closed(hypothesis, _HYPOTHESIS_FIELDS, "Hypothesis")
        if hypothesis["rank"] != expected_rank:
            raise SchemaValidationError("Hypotheses must use consecutive ranks.")
        hypotheses.append(
            {
                "rank": expected_rank,
                "code": _code(hypothesis["code"], "Hypothesis code"),
            }
        )
    actions_value = value["actions"]
    if not isinstance(actions_value, list) or not actions_value:
        raise SchemaValidationError("Proposal actions must not be empty.")
    actions = [_validate_action(item, status) for item in actions_value]
    evidence = _evidence_list(value["evidence_fields"])
    if not set(evidence).issubset(projection):
        raise SchemaValidationError(
            "Evidence fields must reference fields present in the projection."
        )
    required_evidence: set[str] = set()
    for fact in observed_facts:
        required_evidence.update(_FACT_EVIDENCE[fact])
    if not required_evidence.issubset(evidence):
        raise SchemaValidationError(
            "Evidence fields do not support every observed fact."
        )
    effect = value["expected_effect_direction"]
    if effect not in {"POSITIVE", "NEGATIVE", "NO_CHANGE", "UNKNOWN"}:
        raise SchemaValidationError("Expected effect direction is invalid.")
    first_action = actions[0]["action"]
    if first_action in {"KEEP", "REQUEST_HUMAN_HELP"} and effect != "NO_CHANGE":
        raise SchemaValidationError(
            "No-change actions must declare no expected effect."
        )
    if first_action not in {"KEEP", "REQUEST_HUMAN_HELP"} and effect != "POSITIVE":
        raise SchemaValidationError(
            "A proposed change must declare a positive expected direction."
        )
    observation_window = _integer(
        value["minimum_observation_window_hours"],
        "Minimum observation window",
        minimum=1,
    )
    risks = _code_list(value["risks"], "Risks")
    preconditions = _code_list(value["preconditions"], "Preconditions")
    rollback_condition = _code(
        value["rollback_condition"],
        "Rollback condition",
    )
    missing = _code_list(value["missing_data_requests"], "Missing data requests")
    expected_diff = _validate_expected_diff(
        value["expected_diff"],
        actions[0]["action"],
    )
    explanation = _text(value["explanation_ru"], "Russian explanation")
    if _CYRILLIC.search(explanation) is None:
        raise SchemaValidationError("Explanation must be written in Russian.")
    return {
        "status": status,
        "observed_facts": list(observed_facts),
        "hypotheses": hypotheses,
        "actions": actions,
        "evidence_fields": list(evidence),
        "expected_effect_direction": effect,
        "minimum_observation_window_hours": observation_window,
        "risks": list(risks),
        "preconditions": list(preconditions),
        "rollback_condition": rollback_condition,
        "missing_data_requests": list(missing),
        "expected_diff": expected_diff,
        "explanation_ru": explanation,
    }


@dataclass(frozen=True)
class OptimizationProposalV1:
    proposal_id: str
    proposal_version: str
    run_id: str
    snapshot_id: str
    created_at: str
    expires_at: str
    status: str
    observed_facts: Tuple[str, ...]
    hypotheses: Tuple[Mapping[str, Any], ...]
    actions: Tuple[Mapping[str, Any], ...]
    evidence_fields: Tuple[str, ...]
    expected_effect_direction: str
    minimum_observation_window_hours: int
    risks: Tuple[str, ...]
    preconditions: Tuple[str, ...]
    rollback_condition: str
    missing_data_requests: Tuple[str, ...]
    expected_diff: Mapping[str, Any]
    expected_fingerprint: str
    explanation_ru: str

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        projection: Mapping[str, Any],
    ) -> "OptimizationProposalV1":
        _closed(value, _PROPOSAL_FIELDS, "OptimizationProposalV1")
        if (
            not isinstance(value["proposal_id"], str)
            or _SAFE_IDENTIFIER.fullmatch(value["proposal_id"]) is None
        ):
            raise SchemaValidationError("Proposal ID is invalid.")
        if value["proposal_version"] != "optimization-proposal-v1":
            raise SchemaValidationError("Proposal version is unsupported.")
        if (
            not isinstance(value["run_id"], str)
            or _SAFE_IDENTIFIER.fullmatch(value["run_id"]) is None
        ):
            raise SchemaValidationError("Run ID is invalid.")
        if not isinstance(value["snapshot_id"], str) or _SHA256.fullmatch(
            value["snapshot_id"]
        ) is None:
            raise SchemaValidationError("Snapshot ID is invalid.")
        if not isinstance(value["expected_fingerprint"], str) or _SHA256.fullmatch(
            value["expected_fingerprint"]
        ) is None:
            raise SchemaValidationError("Expected fingerprint is invalid.")
        created = _parse_utc(value["created_at"], "Proposal created_at")
        expires = _parse_utc(value["expires_at"], "Proposal expires_at")
        if expires <= created:
            raise SchemaValidationError("Proposal expiry must be after creation.")
        model_payload = _validate_model_payload(
            {name: value[name] for name in _MODEL_PAYLOAD_FIELDS},
            projection,
        )
        return cls(
            proposal_id=value["proposal_id"],
            proposal_version=value["proposal_version"],
            run_id=value["run_id"],
            snapshot_id=value["snapshot_id"],
            created_at=created.isoformat(),
            expires_at=expires.isoformat(),
            expected_fingerprint=value["expected_fingerprint"],
            status=model_payload["status"],
            observed_facts=tuple(model_payload["observed_facts"]),
            hypotheses=tuple(
                _freeze_json(item) for item in model_payload["hypotheses"]
            ),
            actions=tuple(_freeze_json(item) for item in model_payload["actions"]),
            evidence_fields=tuple(model_payload["evidence_fields"]),
            expected_effect_direction=model_payload["expected_effect_direction"],
            minimum_observation_window_hours=model_payload[
                "minimum_observation_window_hours"
            ],
            risks=tuple(model_payload["risks"]),
            preconditions=tuple(model_payload["preconditions"]),
            rollback_condition=model_payload["rollback_condition"],
            missing_data_requests=tuple(model_payload["missing_data_requests"]),
            expected_diff=_freeze_json(model_payload["expected_diff"]),
            explanation_ru=model_payload["explanation_ru"],
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "proposal_version": self.proposal_version,
            "run_id": self.run_id,
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "status": self.status,
            "observed_facts": list(self.observed_facts),
            "hypotheses": [_thaw_json(item) for item in self.hypotheses],
            "actions": [_thaw_json(item) for item in self.actions],
            "evidence_fields": list(self.evidence_fields),
            "expected_effect_direction": self.expected_effect_direction,
            "minimum_observation_window_hours": (
                self.minimum_observation_window_hours
            ),
            "risks": list(self.risks),
            "preconditions": list(self.preconditions),
            "rollback_condition": self.rollback_condition,
            "missing_data_requests": list(self.missing_data_requests),
            "expected_diff": _thaw_json(self.expected_diff),
            "expected_fingerprint": self.expected_fingerprint,
            "explanation_ru": self.explanation_ru,
        }


@dataclass(frozen=True)
class CampaignDraftV1:
    schema_version: str
    draft_id: str
    business_goal: Mapping[str, Any]
    primary_conversion: Mapping[str, Any]
    campaign_type: str
    strategy: Mapping[str, Any]
    geography: Tuple[str, ...]
    schedule: Mapping[str, Any]
    budget: Mapping[str, Any]
    limits: Mapping[str, Any]
    groups: Tuple[Mapping[str, Any], ...]
    landing_page: str
    media_references: Tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CampaignDraftV1":
        fields = (
            "schema_version",
            "draft_id",
            "business_goal",
            "primary_conversion",
            "campaign_type",
            "strategy",
            "geography",
            "schedule",
            "budget",
            "limits",
            "groups",
            "landing_page",
            "media_references",
        )
        _closed(value, fields, "CampaignDraftV1")
        if value["schema_version"] != "campaign-draft-v1":
            raise SchemaValidationError("Campaign draft version is unsupported.")
        _text(value["draft_id"], "Campaign draft ID", maximum=128)
        _closed(
            value["business_goal"],
            ("event", "meaning"),
            "Campaign business goal",
        )
        _text(value["business_goal"]["event"], "Campaign goal event", maximum=128)
        _text(value["business_goal"]["meaning"], "Campaign goal meaning")
        _closed(
            value["primary_conversion"],
            ("event",),
            "Campaign primary conversion",
        )
        _text(
            value["primary_conversion"]["event"],
            "Campaign primary conversion event",
            maximum=128,
        )
        _text(value["campaign_type"], "Campaign type", maximum=64)
        _closed(
            value["strategy"],
            ("placement", "search", "network"),
            "Campaign strategy",
        )
        for item in value["strategy"].values():
            _text(item, "Campaign strategy value", maximum=64)
        geography = _string_array(value["geography"], "Campaign geography")
        schedule = value["schedule"]
        _closed(
            schedule,
            ("timezone", "days", "start", "end"),
            "Campaign schedule",
        )
        _text(schedule["timezone"], "Campaign schedule timezone", maximum=64)
        _string_array(schedule["days"], "Campaign schedule days", nonempty=True)
        _text(schedule["start"], "Campaign schedule start", maximum=5)
        _text(schedule["end"], "Campaign schedule end", maximum=5)
        budget = value["budget"]
        _closed(budget, ("currency", "weekly_micros"), "Campaign budget")
        if budget["currency"] != "RUB":
            raise SchemaValidationError("Campaign currency must be RUB.")
        _integer(budget["weekly_micros"], "Campaign weekly budget", minimum=1)
        limits = value["limits"]
        _closed(
            limits,
            ("maximum_weekly_micros", "maximum_bid_micros"),
            "Campaign limits",
        )
        for name, item in limits.items():
            _integer(item, "Campaign limit " + name, minimum=1)
        groups = _validate_campaign_groups(value["groups"])
        landing_page = _text(
            value["landing_page"],
            "Campaign landing page",
            maximum=2048,
        )
        media_references = _string_array(
            value["media_references"],
            "Campaign media references",
        )
        return cls(
            schema_version=value["schema_version"],
            draft_id=value["draft_id"],
            business_goal=_freeze_json(value["business_goal"]),
            primary_conversion=_freeze_json(value["primary_conversion"]),
            campaign_type=value["campaign_type"],
            strategy=_freeze_json(value["strategy"]),
            geography=geography,
            schedule=_freeze_json(schedule),
            budget=_freeze_json(budget),
            limits=_freeze_json(limits),
            groups=tuple(_freeze_json(item) for item in groups),
            landing_page=landing_page,
            media_references=media_references,
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "draft_id": self.draft_id,
            "business_goal": _thaw_json(self.business_goal),
            "primary_conversion": _thaw_json(self.primary_conversion),
            "campaign_type": self.campaign_type,
            "strategy": _thaw_json(self.strategy),
            "geography": list(self.geography),
            "schedule": _thaw_json(self.schedule),
            "budget": _thaw_json(self.budget),
            "limits": _thaw_json(self.limits),
            "groups": [_thaw_json(item) for item in self.groups],
            "landing_page": self.landing_page,
            "media_references": list(self.media_references),
        }


def _string_array(
    value: Any,
    label: str,
    nonempty: bool = False,
    maximum: int = 128,
) -> Tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum:
        raise SchemaValidationError(label + " must be an allowed array.")
    if nonempty and not value:
        raise SchemaValidationError(label + " must not be empty.")
    result = tuple(_text(item, label + " item", maximum=2048) for item in value)
    if len(set(result)) != len(result):
        raise SchemaValidationError(label + " must contain unique values.")
    return result


def _validate_campaign_groups(value: Any) -> Tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or not value:
        raise SchemaValidationError("Campaign groups must not be empty.")
    result = []
    for group in value:
        _closed(
            group,
            ("name", "keywords", "negative_keywords", "audiences", "ads"),
            "Campaign group",
        )
        _text(group["name"], "Campaign group name", maximum=128)
        _string_array(group["keywords"], "Campaign keywords")
        _string_array(group["negative_keywords"], "Campaign negative keywords")
        _string_array(group["audiences"], "Campaign audiences")
        ads = group["ads"]
        if not isinstance(ads, list) or not ads:
            raise SchemaValidationError("Campaign ads must not be empty.")
        validated_ads = []
        for ad in ads:
            _closed(
                ad,
                (
                    "variant_id",
                    "title",
                    "text",
                    "landing_page",
                    "utm",
                    "media_reference",
                ),
                "Campaign ad",
            )
            if ad["variant_id"] not in {"A", "B"}:
                raise SchemaValidationError("Campaign ad variant must be A or B.")
            for name in ("title", "text", "landing_page", "utm", "media_reference"):
                _text(ad[name], "Campaign ad " + name, maximum=2048)
            validated_ads.append(deepcopy(dict(ad)))
        validated_group = deepcopy(dict(group))
        validated_group["ads"] = validated_ads
        result.append(validated_group)
    return tuple(result)


@dataclass(frozen=True)
class GoalCandidate:
    schema_version: str
    name: str
    event: str
    site_location: str
    type: str
    business_meaning: str
    priority: int
    duplicate_signals: Tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GoalCandidate":
        fields = (
            "schema_version",
            "name",
            "event",
            "site_location",
            "type",
            "business_meaning",
            "priority",
            "duplicate_signals",
        )
        _closed(value, fields, "GoalCandidate")
        if value["schema_version"] != "goal-candidate-v1":
            raise SchemaValidationError("Goal candidate version is unsupported.")
        return cls(
            schema_version=value["schema_version"],
            name=_text(value["name"], "Goal candidate name", maximum=128),
            event=_text(value["event"], "Goal candidate event", maximum=128),
            site_location=_text(
                value["site_location"],
                "Goal candidate site location",
                maximum=500,
            ),
            type=_text(value["type"], "Goal candidate type", maximum=64),
            business_meaning=_text(
                value["business_meaning"],
                "Goal candidate business meaning",
            ),
            priority=_integer(
                value["priority"],
                "Goal candidate priority",
                minimum=1,
            ),
            duplicate_signals=_string_array(
                value["duplicate_signals"],
                "Goal candidate duplicate signals",
            ),
        )

    def as_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["duplicate_signals"] = list(self.duplicate_signals)
        return value
