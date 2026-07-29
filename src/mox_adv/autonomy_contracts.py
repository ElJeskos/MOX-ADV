"""Typed contracts and deterministic values for bounded autonomy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping, Optional

from mox_adv.commands import ACTION_SPECS
from mox_adv.control_state import (
    ControlRejected,
    ExecutionStatus,
    PreparedChange,
    TrustedScope,
)


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_hash(value: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return "sha256:" + digest


def utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ControlRejected("INVALID_INPUT", "timestamp must be timezone-aware.")
    return value.astimezone(timezone.utc).isoformat()


def parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ControlRejected("INVALID_INPUT", "timestamp must be an ISO string.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ControlRejected("INVALID_INPUT", "timestamp must be ISO UTC.") from error
    if parsed.tzinfo is None:
        raise ControlRejected("INVALID_INPUT", "timestamp must be timezone-aware.")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class MandateRecord:
    mandate_id: str
    canonical: Mapping[str, Any]
    canonical_hash: str
    signature: str
    status: str
    activation_version: int
    revocation_version: int
    activated_at: Optional[str]
    revoked_at: Optional[str]
    revocation_reason: Optional[str]


@dataclass(frozen=True)
class MandateUsage:
    action_count: int
    total_monetary_exposure_rub: int
    daily_cumulative_change_percent: int
    latest_observation_until: Optional[str]


@dataclass(frozen=True)
class BoundedAutonomyRequest:
    mandate_id: str
    proposal_id: str
    execution_key: str
    scope: TrustedScope
    mode: str
    automation_enabled: bool
    comparability_status: str
    confidence_status: str
    financial_recommendations_allowed: bool
    direct_age_minutes: int
    metrika_age_minutes: int
    watermark_skew_minutes: int
    clicks: int
    conversions: int
    spend_rub: int
    cpa_rub: str
    budget_utilization_percent: str
    campaign_state: str
    campaign_strategy: str
    current_fingerprint: str


@dataclass(frozen=True)
class BoundedAutonomyOutcome:
    status: ExecutionStatus
    reason_code: Optional[str]
    observed_value: Any


@dataclass(frozen=True)
class ReadbackClassification:
    status: ExecutionStatus
    reason_code: Optional[str]


def deterministic_monetary_exposure_rub(prepared: PreparedChange) -> int:
    """Derive quota exposure from the immutable canonical current→target diff."""

    spec = ACTION_SPECS[prepared.action]
    if spec.relative_percent is None:
        return 0
    current = prepared.current_value
    target = prepared.target_value
    if (
        isinstance(current, bool)
        or not isinstance(current, int)
        or isinstance(target, bool)
        or not isinstance(target, int)
    ):
        raise ControlRejected(
            "INVALID_INPUT",
            "numeric autonomy action must bind integer current and target values.",
        )
    micros = abs(current - target)
    return int(
        (Decimal(micros) / Decimal(1_000_000)).quantize(
            Decimal(1),
            rounding=ROUND_HALF_UP,
        )
    )


def classify_readback(
    prepared: PreparedChange,
    observed: Any,
    *,
    source_reason: str,
    unknown_reason: str,
) -> ReadbackClassification:
    if observed == prepared.target_value:
        return ReadbackClassification(ExecutionStatus.APPLIED, None)
    if observed == prepared.current_value:
        return ReadbackClassification(ExecutionStatus.FAILED, source_reason)
    return ReadbackClassification(ExecutionStatus.UNKNOWN_RESULT, unknown_reason)
