"""Typed goal-lifecycle payloads composed into the module API v1 boundary."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

GOAL_LIFECYCLE_COMMAND_SCHEMA_VERSION = "goal-lifecycle-command-v1"
GOAL_LIFECYCLE_ACTION_FIELDS = {
    "CREATE_CANDIDATE": (
        "run_id",
        "proposal_id",
        "reservation_id",
        "authority_id",
        "candidate",
    ),
    "PUBLISH_EVENT": (
        "candidate_id",
        "authority_id",
        "site_zone",
        "expected_version",
    ),
    "VERIFY_DELIVERY": ("candidate_id", "event_evidence"),
    "DECIDE_BUSINESS_SEMANTICS": ("candidate_id", "approved", "reviewer"),
    "EVALUATE_OPTIMIZATION_ELIGIBILITY": (
        "candidate_id",
        "observed_at",
        "sample_clicks",
        "sample_conversions",
    ),
    "CLEANUP_REJECTED_CANDIDATE": ("candidate_id", "run_id"),
}


class GoalLifecycleContractError(ValueError):
    """A goal lifecycle value cannot cross the public module boundary."""


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GoalLifecycleContractError(f"{field} must be an object")
    return value


def _array(value: Any, field: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise GoalLifecycleContractError(f"{field} must be an array")
    return value


def _exact_fields(
    value: Mapping[str, Any],
    *,
    field: str,
    required: Sequence[str],
) -> None:
    unexpected = sorted(set(value) - set(required))
    if unexpected:
        raise GoalLifecycleContractError(
            f"{field} has unexpected field: {unexpected[0]}"
        )
    missing = sorted(set(required) - set(value))
    if missing:
        raise GoalLifecycleContractError(
            f"{field} is missing field: {missing[0]}"
        )


def _text(
    value: Any,
    field: str,
    *,
    minimum: int = 1,
    maximum: int = 500,
) -> str:
    if not isinstance(value, str):
        raise GoalLifecycleContractError(f"{field} must be a string")
    if not minimum <= len(value) <= maximum:
        raise GoalLifecycleContractError(
            f"{field} length must be between {minimum} and {maximum}"
        )
    return value


def _one_of(
    value: Any,
    field: str,
    allowed: Sequence[str],
) -> str:
    parsed = _text(value, field)
    if parsed not in allowed:
        raise GoalLifecycleContractError(
            f"{field} must be one of: {', '.join(allowed)}"
        )
    return parsed


def _timestamp(value: Any, field: str) -> str:
    parsed = _text(value, field)
    try:
        timestamp = datetime.fromisoformat(parsed.replace("Z", "+00:00"))
    except ValueError as error:
        raise GoalLifecycleContractError(
            f"{field} must be an ISO-8601 timestamp"
        ) from error
    if timestamp.tzinfo is None:
        raise GoalLifecycleContractError(f"{field} must include a UTC offset")
    return parsed


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise GoalLifecycleContractError(f"{field} must be boolean")
    return value


def _count(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GoalLifecycleContractError(
            f"{field} must be a non-negative integer"
        )
    return value


@dataclass(frozen=True)
class GoalCandidateInputV1:
    """Closed candidate input without provider transport details."""

    schema_version: str
    name: str
    event: str
    site_location: str
    goal_type: str
    business_meaning: str
    priority: int
    duplicate_signals: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> GoalCandidateInputV1:
        field = "goal_lifecycle_command.candidate"
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
        _exact_fields(value, field=field, required=fields)
        priority = _count(value["priority"], f"{field}.priority")
        if priority < 1:
            raise GoalLifecycleContractError(
                f"{field}.priority must be a positive integer"
            )
        duplicate_signals = tuple(
            _text(item, f"{field}.duplicate_signals[]", maximum=500)
            for item in _array(
                value["duplicate_signals"],
                f"{field}.duplicate_signals",
            )
        )
        if len(duplicate_signals) > 128 or len(set(duplicate_signals)) != len(
            duplicate_signals
        ):
            raise GoalLifecycleContractError(
                f"{field}.duplicate_signals must contain at most 128 "
                "unique values"
            )
        return cls(
            schema_version=_one_of(
                value["schema_version"],
                f"{field}.schema_version",
                ("goal-candidate-v1",),
            ),
            name=_text(value["name"], f"{field}.name", maximum=128),
            event=_text(value["event"], f"{field}.event", maximum=128),
            site_location=_text(
                value["site_location"],
                f"{field}.site_location",
                maximum=500,
            ),
            goal_type=_text(value["type"], f"{field}.type", maximum=64),
            business_meaning=_text(
                value["business_meaning"],
                f"{field}.business_meaning",
                maximum=500,
            ),
            priority=priority,
            duplicate_signals=duplicate_signals,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "event": self.event,
            "site_location": self.site_location,
            "type": self.goal_type,
            "business_meaning": self.business_meaning,
            "priority": self.priority,
            "duplicate_signals": list(self.duplicate_signals),
        }


@dataclass(frozen=True)
class GoalEventEvidenceV1:
    """Browser evidence accepted by technical lifecycle verification."""

    event: str
    selector: str
    trigger_selector: str
    counter_id: str
    http_method: str
    request_url: str
    emitted_count: int
    intercepted_locally: bool
    real_network_requests: int

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> GoalEventEvidenceV1:
        field = "goal_lifecycle_command.event_evidence"
        fields = (
            "event",
            "selector",
            "trigger_selector",
            "counter_id",
            "http_method",
            "request_url",
            "emitted_count",
            "intercepted_locally",
            "real_network_requests",
        )
        _exact_fields(value, field=field, required=fields)
        return cls(
            event=_text(value["event"], f"{field}.event", maximum=128),
            selector=_text(value["selector"], f"{field}.selector", maximum=500),
            trigger_selector=_text(
                value["trigger_selector"],
                f"{field}.trigger_selector",
                maximum=500,
            ),
            counter_id=_text(
                value["counter_id"],
                f"{field}.counter_id",
                maximum=128,
            ),
            http_method=_one_of(
                value["http_method"],
                f"{field}.http_method",
                ("POST",),
            ),
            request_url=_text(
                value["request_url"],
                f"{field}.request_url",
                maximum=2_000,
            ),
            emitted_count=_count(
                value["emitted_count"],
                f"{field}.emitted_count",
            ),
            intercepted_locally=_boolean(
                value["intercepted_locally"],
                f"{field}.intercepted_locally",
            ),
            real_network_requests=_count(
                value["real_network_requests"],
                f"{field}.real_network_requests",
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "selector": self.selector,
            "trigger_selector": self.trigger_selector,
            "counter_id": self.counter_id,
            "http_method": self.http_method,
            "request_url": self.request_url,
            "emitted_count": self.emitted_count,
            "intercepted_locally": self.intercepted_locally,
            "real_network_requests": self.real_network_requests,
        }


@dataclass(frozen=True)
class GoalLifecycleCommandV1:
    """One high-level lifecycle action, never a Yandex HTTP payload."""

    schema_version: str
    action: str
    values: Mapping[str, Any]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> GoalLifecycleCommandV1:
        action = _one_of(
            value.get("action"),
            "goal_lifecycle_command.action",
            tuple(GOAL_LIFECYCLE_ACTION_FIELDS),
        )
        action_fields = GOAL_LIFECYCLE_ACTION_FIELDS[action]
        _exact_fields(
            value,
            field="goal_lifecycle_command",
            required=("schema_version", "action", *action_fields),
        )
        _one_of(
            value["schema_version"],
            "goal_lifecycle_command.schema_version",
            (GOAL_LIFECYCLE_COMMAND_SCHEMA_VERSION,),
        )
        parsed: dict[str, Any] = {}
        for field in action_fields:
            item = value[field]
            field_name = f"goal_lifecycle_command.{field}"
            if field == "candidate":
                parsed[field] = GoalCandidateInputV1.from_dict(
                    _object(item, field_name)
                )
            elif field == "event_evidence":
                parsed[field] = GoalEventEvidenceV1.from_dict(
                    _object(item, field_name)
                )
            elif field == "approved":
                parsed[field] = _boolean(item, field_name)
            elif field in ("sample_clicks", "sample_conversions"):
                parsed[field] = _count(item, field_name)
            elif field == "observed_at":
                parsed[field] = _timestamp(item, field_name)
            else:
                parsed[field] = _text(item, field_name, maximum=500)
        return cls(
            schema_version=GOAL_LIFECYCLE_COMMAND_SCHEMA_VERSION,
            action=action,
            values=parsed,
        )

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": self.schema_version,
            "action": self.action,
        }
        for field, item in self.values.items():
            value[field] = item.as_dict() if hasattr(item, "as_dict") else item
        return value


@dataclass(frozen=True)
class GoalLifecycleEvidenceOutcomeV1:
    """Sanitized event and polling facts preserved in the public result."""

    event: str
    counter_id: str
    emitted_count: int
    duplicate_event_absent: bool
    intercepted_locally: bool
    real_network_requests: int
    delivery_observed: bool
    virtual_elapsed_minutes: int
    poll_count: int
    checked_at: str

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> GoalLifecycleEvidenceOutcomeV1:
        field = "lifecycle_outcome.event_evidence"
        fields = (
            "event",
            "counter_id",
            "emitted_count",
            "duplicate_event_absent",
            "intercepted_locally",
            "real_network_requests",
            "delivery_observed",
            "virtual_elapsed_minutes",
            "poll_count",
            "checked_at",
        )
        _exact_fields(value, field=field, required=fields)
        return cls(
            event=_text(value["event"], f"{field}.event", maximum=128),
            counter_id=_text(
                value["counter_id"],
                f"{field}.counter_id",
                maximum=128,
            ),
            emitted_count=_count(
                value["emitted_count"],
                f"{field}.emitted_count",
            ),
            duplicate_event_absent=_boolean(
                value["duplicate_event_absent"],
                f"{field}.duplicate_event_absent",
            ),
            intercepted_locally=_boolean(
                value["intercepted_locally"],
                f"{field}.intercepted_locally",
            ),
            real_network_requests=_count(
                value["real_network_requests"],
                f"{field}.real_network_requests",
            ),
            delivery_observed=_boolean(
                value["delivery_observed"],
                f"{field}.delivery_observed",
            ),
            virtual_elapsed_minutes=_count(
                value["virtual_elapsed_minutes"],
                f"{field}.virtual_elapsed_minutes",
            ),
            poll_count=_count(value["poll_count"], f"{field}.poll_count"),
            checked_at=_timestamp(value["checked_at"], f"{field}.checked_at"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "counter_id": self.counter_id,
            "emitted_count": self.emitted_count,
            "duplicate_event_absent": self.duplicate_event_absent,
            "intercepted_locally": self.intercepted_locally,
            "real_network_requests": self.real_network_requests,
            "delivery_observed": self.delivery_observed,
            "virtual_elapsed_minutes": self.virtual_elapsed_minutes,
            "poll_count": self.poll_count,
            "checked_at": self.checked_at,
        }


@dataclass(frozen=True)
class GoalLifecycleOutcomeV1:
    """Typed lifecycle state with a digest over all returned evidence."""

    action: str
    lifecycle_status: str
    candidate_id: str
    goal_id: str
    candidate_status: str
    technical_status: str
    optimization_eligible: bool
    cleaned_up: bool
    event_evidence: GoalLifecycleEvidenceOutcomeV1 | None
    evidence_digest: str

    def __post_init__(self) -> None:
        _one_of(
            self.action,
            "lifecycle_outcome.action",
            tuple(GOAL_LIFECYCLE_ACTION_FIELDS),
        )
        _one_of(
            self.lifecycle_status,
            "lifecycle_outcome.lifecycle_status",
            (
                "CANDIDATE",
                "EVENT_PUBLISHED",
                "TECHNICALLY_VERIFIED",
                "TECHNICALLY_INCONCLUSIVE",
                "APPROVED",
                "REJECTED",
                "OPTIMIZATION_ELIGIBLE",
                "OPTIMIZATION_INELIGIBLE",
                "CLEANED_UP",
            ),
        )
        _one_of(
            self.candidate_status,
            "lifecycle_outcome.candidate_status",
            ("CANDIDATE", "APPROVED", "REJECTED"),
        )
        _one_of(
            self.technical_status,
            "lifecycle_outcome.technical_status",
            ("PENDING", "VERIFIED", "INCONCLUSIVE"),
        )
        _boolean(
            self.optimization_eligible,
            "lifecycle_outcome.optimization_eligible",
        )
        _boolean(self.cleaned_up, "lifecycle_outcome.cleaned_up")
        if len(self.evidence_digest) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.evidence_digest
        ):
            raise GoalLifecycleContractError(
                "lifecycle_outcome.evidence_digest must be a SHA-256 hex digest"
            )

    @classmethod
    def create(
        cls,
        *,
        action: str,
        lifecycle_status: str,
        candidate_id: str,
        goal_id: str,
        candidate_status: str,
        technical_status: str,
        optimization_eligible: bool,
        cleaned_up: bool,
        event_evidence: GoalLifecycleEvidenceOutcomeV1 | None,
    ) -> GoalLifecycleOutcomeV1:
        outcome = cls(
            action=action,
            lifecycle_status=lifecycle_status,
            candidate_id=candidate_id,
            goal_id=goal_id,
            candidate_status=candidate_status,
            technical_status=technical_status,
            optimization_eligible=optimization_eligible,
            cleaned_up=cleaned_up,
            event_evidence=event_evidence,
            evidence_digest="0" * 64,
        )
        return replace(
            outcome,
            evidence_digest=outcome.computed_evidence_digest(),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> GoalLifecycleOutcomeV1:
        fields = (
            "action",
            "lifecycle_status",
            "candidate_id",
            "goal_id",
            "candidate_status",
            "technical_status",
            "optimization_eligible",
            "cleaned_up",
            "event_evidence",
            "evidence_digest",
        )
        _exact_fields(value, field="lifecycle_outcome", required=fields)
        event_evidence = value["event_evidence"]
        outcome = cls(
            action=_text(
                value["action"],
                "lifecycle_outcome.action",
                maximum=128,
            ),
            lifecycle_status=_text(
                value["lifecycle_status"],
                "lifecycle_outcome.lifecycle_status",
                maximum=128,
            ),
            candidate_id=_text(
                value["candidate_id"],
                "lifecycle_outcome.candidate_id",
                maximum=128,
            ),
            goal_id=_text(
                value["goal_id"],
                "lifecycle_outcome.goal_id",
                maximum=128,
            ),
            candidate_status=_text(
                value["candidate_status"],
                "lifecycle_outcome.candidate_status",
                maximum=32,
            ),
            technical_status=_text(
                value["technical_status"],
                "lifecycle_outcome.technical_status",
                maximum=32,
            ),
            optimization_eligible=_boolean(
                value["optimization_eligible"],
                "lifecycle_outcome.optimization_eligible",
            ),
            cleaned_up=_boolean(
                value["cleaned_up"],
                "lifecycle_outcome.cleaned_up",
            ),
            event_evidence=(
                None
                if event_evidence is None
                else GoalLifecycleEvidenceOutcomeV1.from_dict(
                    _object(event_evidence, "lifecycle_outcome.event_evidence")
                )
            ),
            evidence_digest=_text(
                value["evidence_digest"],
                "lifecycle_outcome.evidence_digest",
                minimum=64,
                maximum=64,
            ),
        )
        if outcome.evidence_digest != outcome.computed_evidence_digest():
            raise GoalLifecycleContractError(
                "lifecycle_outcome evidence digest does not match its facts"
            )
        return outcome

    def evidence_facts(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "lifecycle_status": self.lifecycle_status,
            "candidate_id": self.candidate_id,
            "goal_id": self.goal_id,
            "candidate_status": self.candidate_status,
            "technical_status": self.technical_status,
            "optimization_eligible": self.optimization_eligible,
            "cleaned_up": self.cleaned_up,
            "event_evidence": (
                None
                if self.event_evidence is None
                else self.event_evidence.as_dict()
            ),
        }

    def computed_evidence_digest(self) -> str:
        canonical = json.dumps(
            self.evidence_facts(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.evidence_facts(),
            "evidence_digest": self.evidence_digest,
        }
