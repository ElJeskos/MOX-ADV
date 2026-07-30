"""Closed contracts and canonical bindings for candidate-goal operations."""

# ruff: noqa: UP045

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class GoalLifecycleRejected(RuntimeError):
    """A goal lifecycle request failed a deterministic boundary."""


class AuthorityKind(str, Enum):
    APPROVAL = "APPROVAL"
    MANDATE = "MANDATE"


class GoalCandidateStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class GoalTechnicalStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    INCONCLUSIVE = "INCONCLUSIVE"


class GoalExecutionStatus(str, Enum):
    IN_FLIGHT = "IN_FLIGHT"
    APPLIED = "APPLIED"
    FAILED = "FAILED"
    UNKNOWN_RESULT = "UNKNOWN_RESULT"


@dataclass(frozen=True)
class CreationReservation:
    reservation_id: str
    scope_binding: str
    object_type: str
    proposal_id: str
    credential_profile: str
    expires_at: datetime


@dataclass(frozen=True)
class GoalAuthority:
    authority_id: str
    kind: AuthorityKind
    principal: str
    authentication: str
    proposal_id: str
    counter_id: str
    site_zone: str
    allowed_actions: tuple[str, ...]
    expires_at: datetime
    policy_id: str
    binding_hash: str
    action_quota: int = 1


@dataclass(frozen=True)
class GoalCandidateRecord:
    candidate_id: str
    run_id: str
    proposal_id: str
    counter_id: str
    goal_id: str
    name: str
    event: str
    site_location: str
    goal_type: str
    business_meaning: str
    priority: int
    status: GoalCandidateStatus
    technical_status: GoalTechnicalStatus
    created_at: datetime
    optimization_gate_passed: bool = False
    semantic_reviewer: Optional[str] = None

    @property
    def optimization_eligible(self) -> bool:
        return (
            self.status == GoalCandidateStatus.APPROVED
            and self.technical_status == GoalTechnicalStatus.VERIFIED
            and self.optimization_gate_passed
        )


@dataclass(frozen=True)
class SitePublication:
    candidate_id: str
    run_id: str
    site_zone: str
    event: str
    selector: str
    previous_version: str
    published_version: str
    author: str
    exact_diff: Mapping[str, Any]


@dataclass(frozen=True)
class GoalExecutionRecord:
    execution_key: str
    operation: str
    candidate_id: str
    run_id: str
    proposal_id: str
    counter_id: str
    plan_hash: str
    status: GoalExecutionStatus
    external_id: Optional[str]
    detail: Optional[str]


@dataclass(frozen=True)
class BeginExecution:
    record: GoalExecutionRecord
    newly_started: bool


def validate_candidate(
    payload: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    required = {
        "schema_version",
        "name",
        "event",
        "site_location",
        "type",
        "business_meaning",
        "priority",
        "duplicate_signals",
    }
    if set(payload) != required or payload.get("schema_version") != "goal-candidate-v1":
        raise GoalLifecycleRejected("GOAL_CANDIDATE_INVALID")
    allowed_events = {
        policy["conversion"]["primary"]["event"],
        *(item["event"] for item in policy["conversion"]["microconversions"]),
    }
    if payload.get("event") not in allowed_events:
        raise GoalLifecycleRejected("GOAL_EVENT_NOT_ALLOWLISTED")
    text_limits = {
        "name": 128,
        "event": 128,
        "site_location": 500,
        "type": 64,
        "business_meaning": 500,
    }
    if any(
        not isinstance(payload.get(field), str)
        or not 1 <= len(payload[field]) <= maximum
        for field, maximum in text_limits.items()
    ):
        raise GoalLifecycleRejected("GOAL_CANDIDATE_INVALID")
    duplicate_signals = payload.get("duplicate_signals")
    if (
        isinstance(payload.get("priority"), bool)
        or not isinstance(payload.get("priority"), int)
        or payload["priority"] < 1
        or not isinstance(duplicate_signals, list)
        or len(duplicate_signals) > 128
        or any(
            not isinstance(item, str) or not 1 <= len(item) <= 500
            for item in duplicate_signals
        )
        or len(set(duplicate_signals)) != len(duplicate_signals)
    ):
        raise GoalLifecycleRejected("GOAL_CANDIDATE_INVALID")
    return dict(payload)


def goal_signature(payload: Mapping[str, Any]) -> str:
    return canonical_hash(
        {
            "event": str(payload["event"]).strip().casefold(),
        }
    )


def goal_creation_plan(
    *,
    policy_id: str,
    run_id: str,
    candidate_id: str,
    proposal_id: str,
    reservation_id: str,
    counter_id: str,
    site_zone: str,
    credential_profile: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "goal-creation-plan-v1",
        "action": "GOAL_AUTHORING",
        "policy_id": policy_id,
        "run_id": run_id,
        "candidate_id": candidate_id,
        "proposal_id": proposal_id,
        "reservation_id": reservation_id,
        "counter_id": counter_id,
        "site_zone": site_zone,
        "credential_profile": credential_profile,
        "goal_signature": goal_signature(payload),
        "candidate": dict(payload),
    }


def goal_creation_binding(**kwargs: Any) -> str:
    return canonical_hash(goal_creation_plan(**kwargs))


def site_publish_diff(
    candidate: GoalCandidateRecord,
    site_zone: str,
    expected_version: str,
) -> dict[str, Any]:
    return {
        "schema_version": "site-publish-diff-v1",
        "operation": "INSTALL_REACH_GOAL",
        "candidate_id": candidate.candidate_id,
        "site_zone": site_zone,
        "selector": candidate.site_location,
        "event": candidate.event,
        "before": {
            "page_version": expected_version,
            "reach_goal": None,
        },
        "after": {
            "page_version": expected_version + "+" + candidate.run_id,
            "reach_goal": {
                "event": candidate.event,
                "selector": candidate.site_location,
            },
        },
    }


def site_publish_plan(
    *,
    policy_id: str,
    candidate: GoalCandidateRecord,
    exact_diff: Mapping[str, Any],
    credential_profile: str = "TEST_SITE_PUBLISH",
) -> dict[str, Any]:
    if credential_profile != "TEST_SITE_PUBLISH":
        raise GoalLifecycleRejected("TEST_SITE_PUBLISH_PROFILE_REQUIRED")
    return {
        "schema_version": "site-publish-plan-v1",
        "action": "SITE_PUBLISH",
        "credential_profile": credential_profile,
        "policy_id": policy_id,
        "run_id": candidate.run_id,
        "proposal_id": candidate.proposal_id,
        "candidate_id": candidate.candidate_id,
        "counter_id": candidate.counter_id,
        "exact_diff": dict(exact_diff),
    }


def site_publish_binding(**kwargs: Any) -> str:
    return canonical_hash(site_publish_plan(**kwargs))


def canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise GoalLifecycleRejected("TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(timezone.utc).isoformat()


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)
