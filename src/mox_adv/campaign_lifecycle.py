"""Durable, restart-safe campaign creation saga for the controlled prototype."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

from mox_adv.direct_management import (
    CreatedDirectObject,
    DirectAdapterFailure,
    DirectManagementConnectorV1,
    DirectOutcomeUnknown,
    DirectService,
    ProductionPilotAuthority,
)
from mox_adv.control_state import ControlRejected, DurableControlState
from mox_adv.recommend_contracts import CampaignDraftV1, SchemaValidationError


class LifecycleRejected(RuntimeError):
    """A campaign lifecycle request failed a deterministic boundary."""


class CampaignSagaState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_FLIGHT = "IN_FLIGHT"
    APPLIED = "APPLIED"
    ALREADY_PROCESSED = "ALREADY_PROCESSED"
    UNKNOWN_RESULT = "UNKNOWN_RESULT"
    FAILED = "FAILED"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"


class CampaignSagaStep(str, Enum):
    CAMPAIGN_ADD = "CAMPAIGN_ADD"
    AD_GROUP_ADD = "AD_GROUP_ADD"
    ADS_ADD = "ADS_ADD"
    KEYWORD_ADD = "KEYWORD_ADD"
    MODERATION_SUBMIT = "MODERATION_SUBMIT"
    MODERATION_READBACK = "MODERATION_READBACK"
    CAMPAIGN_LAUNCH = "CAMPAIGN_LAUNCH"
    FULL_READBACK = "FULL_READBACK"


class CreationReservationStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    USED = "USED"


SAGA_STEPS = (
    CampaignSagaStep.CAMPAIGN_ADD,
    CampaignSagaStep.AD_GROUP_ADD,
    CampaignSagaStep.ADS_ADD,
    CampaignSagaStep.KEYWORD_ADD,
    CampaignSagaStep.MODERATION_SUBMIT,
    CampaignSagaStep.MODERATION_READBACK,
    CampaignSagaStep.CAMPAIGN_LAUNCH,
    CampaignSagaStep.FULL_READBACK,
)

TERMINAL_STATES = {
    CampaignSagaState.APPLIED,
    CampaignSagaState.UNKNOWN_RESULT,
    CampaignSagaState.FAILED,
    CampaignSagaState.PARTIALLY_APPLIED,
    CampaignSagaState.COMPENSATION_REQUIRED,
}


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise LifecycleRejected("INVALID_TIMESTAMP: timezone-aware value required.")
    return value.astimezone(timezone.utc).isoformat()


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _canonical_hash(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CreationReservation:
    reservation_id: str
    status: CreationReservationStatus
    scope_binding: str
    object_type: str
    proposal_id: str
    credential_profile: str
    expires_at: datetime


@dataclass(frozen=True)
class CampaignApproval:
    approval_id: str
    proposal_id: str
    binding_hash: str
    approver: str
    authentication: str
    expires_at: datetime


@dataclass(frozen=True)
class CampaignDraftSafetyBindings:
    allowed_landing_hosts: Tuple[str, ...]
    prohibited_phrases: Tuple[str, ...]
    prepared_media_references: Tuple[str, ...]


@dataclass(frozen=True)
class CampaignCreationRequest:
    run_id: str
    execution_key: str
    proposal_id: str
    approval_id: str
    account: str
    credential_profile: str
    reservation_id: str
    draft: CampaignDraftV1

    def canonical_plan(self, policy_id: str) -> Dict[str, Any]:
        return {
            "schema_version": "campaign-creation-plan-v1",
            "run_id": self.run_id,
            "execution_key": self.execution_key,
            "proposal_id": self.proposal_id,
            "approval_id": self.approval_id,
            "account": self.account,
            "credential_profile": self.credential_profile,
            "reservation_id": self.reservation_id,
            "policy_id": policy_id,
            "draft": self.draft.as_dict(),
        }

    def approval_binding(self, policy_id: str) -> str:
        plan = self.canonical_plan(policy_id)
        plan.pop("approval_id")
        return _canonical_hash(plan)


@dataclass(frozen=True)
class CampaignSagaResult:
    run_id: str
    execution_key: str
    status: CampaignSagaState
    completed_steps: Tuple[CampaignSagaStep, ...]
    created_objects: Tuple[CreatedDirectObject, ...]
    detail: Optional[str]


def validate_campaign_draft(
    value: Mapping[str, Any],
    policy: Mapping[str, Any],
    safety_bindings: CampaignDraftSafetyBindings,
) -> CampaignDraftV1:
    """Validate the exact Gate 0 unified Search prototype shape."""

    try:
        draft = CampaignDraftV1.from_mapping(value)
    except (SchemaValidationError, KeyError, TypeError) as error:
        raise LifecycleRejected("CAMPAIGN_DRAFT_INVALID: " + str(error)) from error
    campaign_policy = policy["campaign"]
    primary = policy["conversion"]["primary"]
    expected_strategy = {
        "placement": campaign_policy["placement"],
        "search": campaign_policy["search_strategy"],
        "network": campaign_policy["network_strategy"],
    }
    checks = (
        (
            draft.campaign_type == campaign_policy["type"],
            "CAMPAIGN_TYPE_NOT_APPROVED",
        ),
        (
            dict(draft.strategy) == expected_strategy,
            "CAMPAIGN_STRATEGY_NOT_APPROVED",
        ),
        (
            draft.primary_conversion["event"] == primary["event"],
            "PRIMARY_CONVERSION_NOT_APPROVED",
        ),
        (
            draft.business_goal["event"] == primary["event"],
            "BUSINESS_GOAL_NOT_APPROVED",
        ),
        (bool(draft.geography), "GEOGRAPHY_REQUIRED"),
        (len(draft.groups) == 1, "ONE_AD_GROUP_REQUIRED"),
        (
            int(draft.budget["weekly_micros"])
            <= int(draft.limits["maximum_weekly_micros"]),
            "WEEKLY_BUDGET_EXCEEDS_DRAFT_LIMIT",
        ),
        (
            int(draft.limits["maximum_weekly_micros"])
            <= int(policy["limits"]["platform_weekly_spend_rub"]) * 1_000_000,
            "WEEKLY_BUDGET_EXCEEDS_GATE0_LIMIT",
        ),
    )
    for passed, reason in checks:
        if not passed:
            raise LifecycleRejected(reason)

    group = draft.groups[0]
    ads = group["ads"]
    if len(group["keywords"]) != 1 or group["audiences"]:
        raise LifecycleRejected("ONE_SEARCH_KEYWORD_REQUIRED")
    if len(ads) != 2 or {item["variant_id"] for item in ads} != {"A", "B"}:
        raise LifecycleRejected("ACTIVE_AND_RESERVE_ADS_REQUIRED")
    copy_keys = {
        (
            str(item["title"]).strip().casefold(),
            str(item["text"]).strip().casefold(),
        )
        for item in ads
    }
    if len(copy_keys) != 2:
        raise LifecycleRejected("DUPLICATE_AD_COPY")

    if (
        not safety_bindings.allowed_landing_hosts
        or not safety_bindings.prepared_media_references
    ):
        raise LifecycleRejected("TRUSTED_CAMPAIGN_SAFETY_BINDINGS_REQUIRED")
    landing = _validated_https_landing(draft.landing_page)
    if landing.hostname not in set(safety_bindings.allowed_landing_hosts):
        raise LifecycleRejected("LANDING_PAGE_NOT_ALLOWLISTED")
    prohibited = tuple(
        phrase.strip().casefold()
        for phrase in safety_bindings.prohibited_phrases
        if phrase.strip()
    )
    prepared_media = set(safety_bindings.prepared_media_references)
    for ad in ads:
        ad_landing = _validated_https_landing(str(ad["landing_page"]))
        if (
            ad_landing.hostname != landing.hostname
            or ad_landing.path != landing.path
        ):
            raise LifecycleRejected("LANDING_PAGE_OUTSIDE_DRAFT_SCOPE")
        copy_text = (str(ad["title"]) + " " + str(ad["text"])).casefold()
        if any(phrase in copy_text for phrase in prohibited):
            raise LifecycleRejected("PROHIBITED_AD_FORMULATION")
        if (
            ad["media_reference"] not in draft.media_references
            or ad["media_reference"] not in prepared_media
        ):
            raise LifecycleRejected("MEDIA_REFERENCE_NOT_PREPARED")
    if not set(draft.media_references).issubset(prepared_media):
        raise LifecycleRejected("MEDIA_REFERENCE_NOT_PREPARED")
    start_hour, start_minute = _time_parts(str(draft.schedule["start"]))
    end_hour, end_minute = _time_parts(str(draft.schedule["end"]))
    if (start_hour, start_minute) >= (end_hour, end_minute):
        raise LifecycleRejected("CAMPAIGN_SCHEDULE_INVALID")
    return draft


def _validated_https_landing(value: str) -> Any:
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise LifecycleRejected("LANDING_PAGE_INVALID") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise LifecycleRejected("LANDING_PAGE_INVALID")
    return parsed


def _time_parts(value: str) -> Tuple[int, int]:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (ValueError, AttributeError) as error:
        raise LifecycleRejected("CAMPAIGN_SCHEDULE_INVALID") from error
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise LifecycleRejected("CAMPAIGN_SCHEDULE_INVALID")
    return hour, minute


class CampaignSagaStore:
    """SQLite state for reservations, ordered steps, and created object ownership."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=1)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        DurableControlState(self.path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS creation_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    scope_binding TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    proposal_id TEXT NOT NULL,
                    credential_profile TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    reserved_execution_key TEXT,
                    used_at TEXT
                );
                CREATE TABLE IF NOT EXISTS campaign_sagas (
                    execution_key TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE,
                    proposal_id TEXT NOT NULL,
                    reservation_id TEXT NOT NULL,
                    plan_hash TEXT NOT NULL,
                    canonical_plan TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(reservation_id)
                        REFERENCES creation_reservations(reservation_id)
                );
                CREATE TABLE IF NOT EXISTS campaign_saga_steps (
                    execution_key TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    step_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    PRIMARY KEY(execution_key, step_name),
                    UNIQUE(execution_key, ordinal),
                    FOREIGN KEY(execution_key)
                        REFERENCES campaign_sagas(execution_key)
                );
                CREATE TABLE IF NOT EXISTS campaign_saga_dispatches (
                    execution_key TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    step_name TEXT NOT NULL,
                    dispatched_at TEXT NOT NULL,
                    completed_at TEXT,
                    PRIMARY KEY(execution_key, step_name),
                    UNIQUE(execution_key, ordinal),
                    FOREIGN KEY(execution_key)
                        REFERENCES campaign_sagas(execution_key)
                );
                CREATE TABLE IF NOT EXISTS campaign_created_objects (
                    run_id TEXT NOT NULL,
                    execution_key TEXT NOT NULL,
                    service TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    actual_type TEXT NOT NULL,
                    created_step TEXT NOT NULL,
                    compensated_at TEXT,
                    PRIMARY KEY(service, object_id)
                );
                """
            )

    def begin_step(
        self,
        execution_key: str,
        step_name: CampaignSagaStep,
        now: datetime,
    ) -> None:
        step = CampaignSagaStep(step_name)
        ordinal = SAGA_STEPS.index(step)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            completed_count = connection.execute(
                "SELECT COUNT(*) FROM campaign_saga_steps "
                "WHERE execution_key = ?",
                (execution_key,),
            ).fetchone()[0]
            if completed_count != ordinal:
                raise LifecycleRejected("SAGA_STEP_ORDER_VIOLATION")
            existing = connection.execute(
                "SELECT completed_at FROM campaign_saga_dispatches "
                "WHERE execution_key = ? AND step_name = ?",
                (execution_key, step.value),
            ).fetchone()
            if existing is not None:
                if existing["completed_at"] is None:
                    raise LifecycleRejected("SAGA_STEP_OUTCOME_REQUIRES_RECONCILIATION")
                return
            connection.execute(
                "INSERT INTO campaign_saga_dispatches "
                "(execution_key, ordinal, step_name, dispatched_at) "
                "VALUES (?, ?, ?, ?)",
                (execution_key, ordinal, step.value, _utc_text(now)),
            )

    def pending_dispatched_step(
        self,
        execution_key: str,
    ) -> Optional[CampaignSagaStep]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT step_name FROM campaign_saga_dispatches "
                "WHERE execution_key = ? AND completed_at IS NULL "
                "ORDER BY ordinal LIMIT 1",
                (execution_key,),
            ).fetchone()
        return None if row is None else CampaignSagaStep(row["step_name"])

    def register_creation_reservation(
        self,
        reservation: CreationReservation,
        now: datetime,
    ) -> None:
        del now
        try:
            reservation_status = CreationReservationStatus(reservation.status)
        except ValueError as error:
            raise LifecycleRejected("CREATION_RESERVATION_INVALID") from error
        if (
            not reservation.reservation_id
            or reservation_status != CreationReservationStatus.AVAILABLE
            or not reservation.scope_binding
            or not reservation.proposal_id
            or not reservation.credential_profile
        ):
            raise LifecycleRejected("CREATION_RESERVATION_INVALID")
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM creation_reservations WHERE reservation_id = ?",
                (reservation.reservation_id,),
            ).fetchone()
            values = (
                reservation_status.value,
                reservation.scope_binding,
                reservation.object_type,
                reservation.proposal_id,
                reservation.credential_profile,
                _utc_text(reservation.expires_at),
            )
            if existing is not None:
                if tuple(existing[name] for name in (
                    "status",
                    "scope_binding",
                    "object_type",
                    "proposal_id",
                    "credential_profile",
                    "expires_at",
                )) != values:
                    raise LifecycleRejected("IMMUTABLE_RESERVATION_CONFLICT")
                return
            connection.execute(
                "INSERT INTO creation_reservations "
                "(reservation_id, status, scope_binding, object_type, proposal_id, "
                "credential_profile, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (reservation.reservation_id,) + values,
            )

    def register_campaign_approval(self, approval: CampaignApproval) -> None:
        try:
            DurableControlState(self.path).register_campaign_approval_authority(
                approval_id=approval.approval_id,
                proposal_id=approval.proposal_id,
                binding_hash=approval.binding_hash,
                approver=approval.approver,
                authentication=approval.authentication,
                expires_at=approval.expires_at,
            )
        except ControlRejected as error:
            raise LifecycleRejected(
                "CAMPAIGN_APPROVAL_INVALID: " + error.reason_code
            ) from error

    def start_or_load(
        self,
        request: CampaignCreationRequest,
        canonical_plan: Mapping[str, Any],
        now: datetime,
        expected_approver: str,
        expected_authentication: str,
    ) -> CampaignSagaState:
        digest = _canonical_hash(canonical_plan)
        now_text = _utc_text(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            saga = connection.execute(
                "SELECT plan_hash, status FROM campaign_sagas WHERE execution_key = ?",
                (request.execution_key,),
            ).fetchone()
            if saga is not None:
                if saga["plan_hash"] != digest:
                    raise LifecycleRejected(
                        "NEW_PROPOSAL_AND_APPROVAL_REQUIRED: canonical plan changed."
                    )
                return CampaignSagaState(saga["status"])
            reservation = connection.execute(
                "SELECT * FROM creation_reservations WHERE reservation_id = ?",
                (request.reservation_id,),
            ).fetchone()
            if reservation is None:
                raise LifecycleRejected("CREATION_RESERVATION_NOT_FOUND")
            self._validate_reservation(reservation, request, now_text)
            approval = connection.execute(
                "SELECT * FROM campaign_approvals WHERE approval_id = ?",
                (request.approval_id,),
            ).fetchone()
            if approval is None:
                raise LifecycleRejected("CAMPAIGN_APPROVAL_NOT_FOUND")
            expected_binding = request.approval_binding(
                str(canonical_plan["policy_id"])
            )
            if (
                approval["status"] != "AVAILABLE"
                or approval["proposal_id"] != request.proposal_id
                or approval["binding_hash"] != expected_binding
                or approval["approver"] != expected_approver
                or approval["authentication"] != expected_authentication
                or approval["expires_at"] <= now_text
            ):
                raise LifecycleRejected("CAMPAIGN_APPROVAL_NOT_AUTHORIZED")
            connection.execute(
                "UPDATE creation_reservations SET status = 'RESERVED', "
                "reserved_execution_key = ? WHERE reservation_id = ? AND status = 'AVAILABLE'",
                (request.execution_key, request.reservation_id),
            )
            if connection.total_changes != 1:
                raise LifecycleRejected("CREATION_RESERVATION_ALREADY_USED")
            updated_approval = connection.execute(
                "UPDATE campaign_approvals SET status = 'RESERVED', "
                "reserved_execution_key = ? WHERE approval_id = ? "
                "AND status = 'AVAILABLE'",
                (request.execution_key, request.approval_id),
            ).rowcount
            if updated_approval != 1:
                raise LifecycleRejected("CAMPAIGN_APPROVAL_ALREADY_USED")
            connection.execute(
                "INSERT INTO campaign_sagas "
                "(execution_key, run_id, proposal_id, reservation_id, plan_hash, "
                "canonical_plan, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request.execution_key,
                    request.run_id,
                    request.proposal_id,
                    request.reservation_id,
                    digest,
                    _canonical(canonical_plan),
                    CampaignSagaState.IN_FLIGHT.value,
                    now_text,
                    now_text,
                ),
            )
        return CampaignSagaState.IN_FLIGHT

    @staticmethod
    def _validate_reservation(
        row: sqlite3.Row,
        request: CampaignCreationRequest,
        now_text: str,
    ) -> None:
        if row["status"] != "AVAILABLE":
            raise LifecycleRejected("CREATION_RESERVATION_ALREADY_USED")
        if row["scope_binding"] != request.account:
            raise LifecycleRejected("CREATION_RESERVATION_SCOPE_MISMATCH")
        if row["object_type"] != request.draft.campaign_type:
            raise LifecycleRejected("CREATION_RESERVATION_TYPE_MISMATCH")
        if row["proposal_id"] != request.proposal_id:
            raise LifecycleRejected("CREATION_RESERVATION_PROPOSAL_MISMATCH")
        if row["credential_profile"] != request.credential_profile:
            raise LifecycleRejected("CREATION_RESERVATION_CREDENTIAL_MISMATCH")
        if row["expires_at"] <= now_text:
            raise LifecycleRejected("CREATION_RESERVATION_EXPIRED")

    def complete_step(
        self,
        request: CampaignCreationRequest,
        step_name: CampaignSagaStep,
        response: Mapping[str, Any],
        now: datetime,
        created_objects: Sequence[CreatedDirectObject] = (),
    ) -> None:
        step = CampaignSagaStep(step_name)
        ordinal = SAGA_STEPS.index(step)
        now_text = _utc_text(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior_count = connection.execute(
                "SELECT COUNT(*) FROM campaign_saga_steps "
                "WHERE execution_key = ?",
                (request.execution_key,),
            ).fetchone()[0]
            if prior_count != ordinal:
                existing = connection.execute(
                    "SELECT 1 FROM campaign_saga_steps "
                    "WHERE execution_key = ? AND step_name = ?",
                    (request.execution_key, step.value),
                ).fetchone()
                if existing is not None:
                    return
                raise LifecycleRejected("SAGA_STEP_ORDER_VIOLATION")
            for item in created_objects:
                connection.execute(
                    "INSERT INTO campaign_created_objects "
                    "(run_id, execution_key, service, object_id, actual_type, "
                    "created_step) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        request.run_id,
                        request.execution_key,
                        item.service.value,
                        item.object_id,
                        item.actual_type,
                        step.value,
                    ),
                )
            connection.execute(
                "INSERT INTO campaign_saga_steps "
                "(execution_key, ordinal, step_name, status, response_json, "
                "completed_at) VALUES (?, ?, ?, 'APPLIED', ?, ?)",
                (
                    request.execution_key,
                    ordinal,
                    step.value,
                    _canonical(dict(response)),
                    now_text,
                ),
            )
            updated = connection.execute(
                "UPDATE campaign_saga_dispatches SET completed_at = ? "
                "WHERE execution_key = ? AND step_name = ? "
                "AND completed_at IS NULL",
                (now_text, request.execution_key, step.value),
            ).rowcount
            if updated != 1:
                raise LifecycleRejected("SAGA_STEP_WAS_NOT_DISPATCHED")
            if ordinal == 0:
                connection.execute(
                    "UPDATE creation_reservations SET status = 'USED', used_at = ? "
                    "WHERE reservation_id = ? AND reserved_execution_key = ?",
                    (
                        now_text,
                        request.reservation_id,
                        request.execution_key,
                    ),
                )
                used_approval = connection.execute(
                    "UPDATE campaign_approvals SET status = 'USED', used_at = ? "
                    "WHERE approval_id = ? AND status = 'RESERVED' "
                    "AND reserved_execution_key = ?",
                    (now_text, request.approval_id, request.execution_key),
                ).rowcount
                if used_approval != 1:
                    raise LifecycleRejected("CAMPAIGN_APPROVAL_USE_FAILED")
            connection.execute(
                "UPDATE campaign_sagas SET updated_at = ? WHERE execution_key = ?",
                (now_text, request.execution_key),
            )

    def register_dispatched_objects(
        self,
        request: CampaignCreationRequest,
        step_name: CampaignSagaStep,
        created_objects: Sequence[CreatedDirectObject],
    ) -> None:
        step = CampaignSagaStep(step_name)
        if not created_objects:
            raise LifecycleRejected("CREATED_OBJECT_SET_EMPTY")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            dispatch = connection.execute(
                "SELECT completed_at FROM campaign_saga_dispatches "
                "WHERE execution_key = ? AND step_name = ?",
                (request.execution_key, step.value),
            ).fetchone()
            if dispatch is None or dispatch["completed_at"] is not None:
                raise LifecycleRejected("SAGA_STEP_WAS_NOT_DISPATCHED")
            for item in created_objects:
                connection.execute(
                    "INSERT INTO campaign_created_objects "
                    "(run_id, execution_key, service, object_id, actual_type, "
                    "created_step) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        request.run_id,
                        request.execution_key,
                        item.service.value,
                        item.object_id,
                        str(item.actual_type),
                        step.value,
                    ),
                )

    def finish(
        self,
        execution_key: str,
        status: CampaignSagaState,
        detail: Optional[str],
        now: datetime,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE campaign_sagas SET status = ?, detail = ?, updated_at = ? "
                "WHERE execution_key = ?",
                (status.value, detail, _utc_text(now), execution_key),
            )

    def completed_steps(
        self,
        execution_key: str,
    ) -> Tuple[CampaignSagaStep, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT step_name FROM campaign_saga_steps "
                "WHERE execution_key = ? ORDER BY ordinal",
                (execution_key,),
            ).fetchall()
        return tuple(CampaignSagaStep(row["step_name"]) for row in rows)

    def created_objects(
        self,
        run_id: str,
        *,
        include_compensated: bool = False,
    ) -> Tuple[CreatedDirectObject, ...]:
        query = (
            "SELECT service, object_id, actual_type FROM campaign_created_objects "
            "WHERE run_id = ?"
        )
        if not include_compensated:
            query += " AND compensated_at IS NULL"
        query += " ORDER BY rowid"
        with self._connect() as connection:
            rows = connection.execute(query, (run_id,)).fetchall()
        return tuple(
            CreatedDirectObject(
                service=DirectService(row["service"]),
                object_id=row["object_id"],
                actual_type=row["actual_type"],
            )
            for row in rows
        )

    def register_created_objects(
        self,
        run_id: str,
        operation_key: str,
        objects: Sequence[CreatedDirectObject],
    ) -> None:
        """Register matrix-fixture ownership without creating a lifecycle saga."""

        with self._connect() as connection:
            for item in objects:
                connection.execute(
                    "INSERT OR IGNORE INTO campaign_created_objects "
                    "(run_id, execution_key, service, object_id, actual_type, "
                    "created_step) VALUES (?, ?, ?, ?, ?, 'MATRIX_FIXTURE')",
                    (
                        run_id,
                        operation_key,
                        item.service.value,
                        item.object_id,
                        item.actual_type,
                    ),
                )

    def object_belongs_to_run(
        self,
        run_id: str,
        service: str,
        object_id: str,
    ) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM campaign_created_objects "
                "WHERE run_id = ? AND service = ? AND object_id = ? "
                "AND compensated_at IS NULL",
                (run_id, service, object_id),
            ).fetchone()
        return row is not None

    def production_authority_is_valid(
        self,
        authority: ProductionPilotAuthority,
    ) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT proposal_id, binding_hash, status, reserved_execution_key "
                "FROM campaign_approvals WHERE approval_id = ?",
                (authority.approval_id,),
            ).fetchone()
        return bool(
            row is not None
            and row["proposal_id"] == authority.proposal_id
            and row["binding_hash"] == authority.binding_hash
            and row["status"] in {"RESERVED", "USED"}
            and row["reserved_execution_key"] == authority.execution_key
        )

    def campaign_approval_status(self, approval_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM campaign_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        if row is None:
            raise LifecycleRejected("CAMPAIGN_APPROVAL_NOT_FOUND")
        return str(row["status"])

    def mark_compensated(
        self,
        run_id: str,
        service: str,
        object_id: str,
        now: datetime,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE campaign_created_objects SET compensated_at = ? "
                "WHERE run_id = ? AND service = ? AND object_id = ?",
                (_utc_text(now), run_id, service, object_id),
            )

    def result(
        self,
        run_id: str,
        execution_key: str,
        *,
        repeat_completed: bool = False,
    ) -> CampaignSagaResult:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status, detail FROM campaign_sagas WHERE execution_key = ?",
                (execution_key,),
            ).fetchone()
        if row is None:
            raise LifecycleRejected("SAGA_NOT_FOUND")
        status = CampaignSagaState(row["status"])
        if repeat_completed and status == CampaignSagaState.APPLIED:
            status = CampaignSagaState.ALREADY_PROCESSED
        return CampaignSagaResult(
            run_id=run_id,
            execution_key=execution_key,
            status=status,
            completed_steps=self.completed_steps(execution_key),
            created_objects=self.created_objects(run_id),
            detail=row["detail"],
        )


class CampaignLifecycleService:
    """Execute one canonical campaign plan through an ordered durable saga."""

    def __init__(
        self,
        policy: Mapping[str, Any],
        store: CampaignSagaStore,
        connector: DirectManagementConnectorV1,
        safety_bindings: CampaignDraftSafetyBindings,
    ) -> None:
        self.policy = policy
        self.store = store
        self.connector = connector
        self.safety_bindings = safety_bindings

    def execute(
        self,
        request: CampaignCreationRequest,
        now: datetime,
        *,
        max_steps: Optional[int] = None,
    ) -> CampaignSagaResult:
        self._validate_request(request)
        canonical_plan = request.canonical_plan(str(self.policy["policy_id"]))
        approver = self.policy["principals"]["approver"]
        existing = self.store.start_or_load(
            request,
            canonical_plan,
            now,
            str(approver["identity"]),
            str(approver["authentication"]),
        )
        if existing in TERMINAL_STATES:
            return self.store.result(
                request.run_id,
                request.execution_key,
                repeat_completed=True,
            )
        pending_step = self.store.pending_dispatched_step(request.execution_key)
        if pending_step is not None:
            self.store.finish(
                request.execution_key,
                CampaignSagaState.UNKNOWN_RESULT,
                "DISPATCHED_STEP_REQUIRES_RECONCILIATION: " + pending_step.value,
                now,
            )
            return self.store.result(request.run_id, request.execution_key)
        if max_steps is not None and max_steps < 1:
            raise LifecycleRejected("MAX_STEPS_INVALID")
        completed = self.store.completed_steps(request.execution_key)
        steps_run = 0
        try:
            for step_name in SAGA_STEPS[len(completed) :]:
                self._run_step(request, step_name, now)
                steps_run += 1
                if max_steps is not None and steps_run >= max_steps:
                    break
        except DirectOutcomeUnknown as error:
            self.store.finish(
                request.execution_key,
                CampaignSagaState.UNKNOWN_RESULT,
                str(error),
                now,
            )
        except DirectAdapterFailure as error:
            self._finish_after_definite_failure(request, str(error), now)

        if len(self.store.completed_steps(request.execution_key)) == len(SAGA_STEPS):
            self.store.finish(
                request.execution_key,
                CampaignSagaState.APPLIED,
                None,
                now,
            )
        return self.store.result(request.run_id, request.execution_key)

    def _validate_request(self, request: CampaignCreationRequest) -> None:
        text_values = (
            request.run_id,
            request.execution_key,
            request.proposal_id,
            request.approval_id,
            request.account,
            request.credential_profile,
            request.reservation_id,
        )
        if any(not isinstance(value, str) or not value for value in text_values):
            raise LifecycleRejected("CAMPAIGN_CREATION_REQUEST_INVALID")
        validate_campaign_draft(
            request.draft.as_dict(),
            self.policy,
            self.safety_bindings,
        )
        if request.credential_profile != "DIRECT_PILOT_WRITE":
            raise LifecycleRejected("CAMPAIGN_CREDENTIAL_PROFILE_INVALID")
        simulation = self.policy["bindings"]["simulation"]
        pilot = self.policy["bindings"]["pilot"]
        if request.account not in {
            simulation["direct_account"],
            pilot.get("direct_account"),
        }:
            raise LifecycleRejected("CAMPAIGN_ACCOUNT_NOT_ALLOWLISTED")

    def _run_step(
        self,
        request: CampaignCreationRequest,
        step_name: CampaignSagaStep,
        now: datetime,
    ) -> None:
        self.store.begin_step(request.execution_key, step_name, now)
        objects = self.store.created_objects(request.run_id)
        by_service: Dict[str, Tuple[CreatedDirectObject, ...]] = {}
        for service in ("Campaigns", "AdGroups", "Ads", "Keywords"):
            by_service[service] = tuple(
                item for item in objects if item.service == DirectService(service)
            )
        operation_key = request.execution_key + ":" + step_name
        group = request.draft.groups[0]
        handlers = {
            CampaignSagaStep.CAMPAIGN_ADD: self._step_campaign_add,
            CampaignSagaStep.AD_GROUP_ADD: self._step_ad_group_add,
            CampaignSagaStep.ADS_ADD: self._step_ads_add,
            CampaignSagaStep.KEYWORD_ADD: self._step_keyword_add,
            CampaignSagaStep.MODERATION_SUBMIT: self._step_moderation_submit,
            CampaignSagaStep.MODERATION_READBACK: self._step_moderation_readback,
            CampaignSagaStep.CAMPAIGN_LAUNCH: self._step_campaign_launch,
            CampaignSagaStep.FULL_READBACK: self._step_full_readback,
        }
        handlers[step_name](request, now, by_service, group, operation_key)

    def _complete_add_step(
        self,
        request: CampaignCreationRequest,
        step: CampaignSagaStep,
        now: datetime,
        created: Sequence[CreatedDirectObject],
        expected_types: Sequence[Tuple[str, str]],
    ) -> None:
        self.store.register_dispatched_objects(request, step, created)
        self._require_created_types(created, expected_types)
        self.store.complete_step(
            request,
            step,
            {"ids": [item.object_id for item in created]},
            now,
        )

    def _step_campaign_add(
        self,
        request: CampaignCreationRequest,
        now: datetime,
        by_service: Mapping[str, Sequence[CreatedDirectObject]],
        group: Mapping[str, Any],
        operation_key: str,
    ) -> None:
        del by_service, group
        created = self.connector.campaigns_add(
            request.run_id,
            operation_key,
            {
                "type": request.draft.campaign_type,
                "state": "SUSPENDED",
                "strategy": dict(request.draft.strategy),
                "geography": list(request.draft.geography),
                "schedule": dict(request.draft.schedule),
                "WeeklySpendLimit": request.draft.budget["weekly_micros"],
            },
        )
        self._complete_add_step(
            request,
            CampaignSagaStep.CAMPAIGN_ADD,
            now,
            created,
            (("Campaigns", "UNIFIED_CAMPAIGN"),),
        )

    def _step_ad_group_add(
        self,
        request: CampaignCreationRequest,
        now: datetime,
        by_service: Mapping[str, Sequence[CreatedDirectObject]],
        group: Mapping[str, Any],
        operation_key: str,
    ) -> None:
        created = self.connector.adgroups_add(
            request.run_id,
            operation_key,
            {
                "campaign_id": self._one(by_service, "Campaigns").object_id,
                "name": group["name"],
                "negative_keywords": list(group["negative_keywords"]),
            },
        )
        self._complete_add_step(
            request,
            CampaignSagaStep.AD_GROUP_ADD,
            now,
            created,
            (("AdGroups", "UNIFIED_AD_GROUP"),),
        )

    def _step_ads_add(
        self,
        request: CampaignCreationRequest,
        now: datetime,
        by_service: Mapping[str, Sequence[CreatedDirectObject]],
        group: Mapping[str, Any],
        operation_key: str,
    ) -> None:
        created = self.connector.ads_add(
            request.run_id,
            operation_key,
            {
                "ad_group_id": self._one(by_service, "AdGroups").object_id,
                "items": [dict(item) for item in group["ads"]],
            },
        )
        self._complete_add_step(
            request,
            CampaignSagaStep.ADS_ADD,
            now,
            created,
            (("Ads", "TEXT_AD"), ("Ads", "TEXT_AD")),
        )

    def _step_keyword_add(
        self,
        request: CampaignCreationRequest,
        now: datetime,
        by_service: Mapping[str, Sequence[CreatedDirectObject]],
        group: Mapping[str, Any],
        operation_key: str,
    ) -> None:
        created = self.connector.keywords_add(
            request.run_id,
            operation_key,
            {
                "ad_group_id": self._one(by_service, "AdGroups").object_id,
                "keyword": group["keywords"][0],
            },
        )
        self._complete_add_step(
            request,
            CampaignSagaStep.KEYWORD_ADD,
            now,
            created,
            (("Keywords", "KEYWORD"),),
        )

    def _step_moderation_submit(
        self,
        request: CampaignCreationRequest,
        now: datetime,
        by_service: Mapping[str, Sequence[CreatedDirectObject]],
        group: Mapping[str, Any],
        operation_key: str,
    ) -> None:
        del group, operation_key
        response = self.connector.ads_moderate(
            request.run_id,
            (item.object_id for item in by_service["Ads"]),
        )
        self.store.complete_step(
            request,
            CampaignSagaStep.MODERATION_SUBMIT,
            {"states": [item["state"] for item in response]},
            now,
        )

    def _step_moderation_readback(
        self,
        request: CampaignCreationRequest,
        now: datetime,
        by_service: Mapping[str, Sequence[CreatedDirectObject]],
        group: Mapping[str, Any],
        operation_key: str,
    ) -> None:
        del group, operation_key
        response = self.connector.ads_get(
            request.run_id,
            (item.object_id for item in by_service["Ads"]),
        )
        if any(item.get("state") != "MODERATION" for item in response):
            raise DirectAdapterFailure("MODERATION_REQUEST_NOT_ACCEPTED")
        self.store.complete_step(
            request,
            CampaignSagaStep.MODERATION_READBACK,
            {"states": [item["state"] for item in response]},
            now,
        )

    def _step_campaign_launch(
        self,
        request: CampaignCreationRequest,
        now: datetime,
        by_service: Mapping[str, Sequence[CreatedDirectObject]],
        group: Mapping[str, Any],
        operation_key: str,
    ) -> None:
        del group, operation_key
        response = self.connector.campaigns_resume(
            request.run_id,
            self._one(by_service, "Campaigns").object_id,
        )
        if response.get("state") != "ON":
            raise DirectAdapterFailure("CAMPAIGN_LAUNCH_READBACK_FAILED")
        self.store.complete_step(
            request,
            CampaignSagaStep.CAMPAIGN_LAUNCH,
            {"state": response["state"]},
            now,
        )

    def _step_full_readback(
        self,
        request: CampaignCreationRequest,
        now: datetime,
        by_service: Mapping[str, Sequence[CreatedDirectObject]],
        group: Mapping[str, Any],
        operation_key: str,
    ) -> None:
        del group, operation_key
        response = {
            "campaigns": self.connector.campaigns_get(
                request.run_id,
                self._ids(by_service["Campaigns"]),
            ),
            "ad_groups": self.connector.adgroups_get(
                request.run_id,
                self._ids(by_service["AdGroups"]),
            ),
            "ads": self.connector.ads_get(
                request.run_id,
                self._ids(by_service["Ads"]),
            ),
            "keywords": self.connector.keywords_get(
                request.run_id,
                self._ids(by_service["Keywords"]),
            ),
        }
        if not self._full_readback_matches(request, response):
            raise DirectAdapterFailure("FULL_CAMPAIGN_READBACK_FAILED")
        self.store.complete_step(
            request,
            CampaignSagaStep.FULL_READBACK,
            {
                "campaign_ids": [item["id"] for item in response["campaigns"]],
                "ad_group_ids": [item["id"] for item in response["ad_groups"]],
                "ad_ids": [item["id"] for item in response["ads"]],
                "keyword_ids": [item["id"] for item in response["keywords"]],
            },
            now,
        )

    @staticmethod
    def _full_readback_matches(
        request: CampaignCreationRequest,
        response: Mapping[str, Sequence[Mapping[str, Any]]],
    ) -> bool:
        campaigns = response["campaigns"]
        ad_groups = response["ad_groups"]
        ads = response["ads"]
        keywords = response["keywords"]
        if (
            len(campaigns) != 1
            or len(ad_groups) != 1
            or len(ads) != 2
            or len(keywords) != 1
        ):
            return False
        campaign = campaigns[0]
        expected_group = request.draft.groups[0]
        ad_group = ad_groups[0]
        if any(
            (
                campaign.get("type") != "UNIFIED_CAMPAIGN",
                campaign.get("state") != "ON",
                campaign.get("strategy") != dict(request.draft.strategy),
                campaign.get("geography") != list(request.draft.geography),
                campaign.get("schedule") != dict(request.draft.schedule),
                campaign.get("WeeklySpendLimit")
                != request.draft.budget["weekly_micros"],
                ad_group.get("type") != "UNIFIED_AD_GROUP",
                ad_group.get("campaign_id") != campaign.get("id"),
                ad_group.get("name") != expected_group["name"],
                ad_group.get("negative_keywords")
                != list(expected_group["negative_keywords"]),
            )
        ):
            return False
        expected_ads = {
            str(item["variant_id"]): dict(item) for item in expected_group["ads"]
        }
        observed_ads = {str(item.get("variant_id")): item for item in ads}
        if set(observed_ads) != set(expected_ads):
            return False
        for variant_id, expected_ad in expected_ads.items():
            observed = observed_ads[variant_id]
            if (
                observed.get("type") != "TEXT_AD"
                or observed.get("state") != "MODERATION"
                or observed.get("ad_group_id") != ad_group.get("id")
                or any(
                    observed.get(field) != expected_ad[field]
                    for field in (
                        "variant_id",
                        "title",
                        "text",
                        "landing_page",
                        "utm",
                        "media_reference",
                    )
                )
            ):
                return False
        keyword = keywords[0]
        return (
            keyword.get("type") == "KEYWORD"
            and keyword.get("state") == "SUSPENDED"
            and keyword.get("ad_group_id") == ad_group.get("id")
            and keyword.get("keyword") == expected_group["keywords"][0]
        )

    @staticmethod
    def _require_created_types(
        created: Sequence[CreatedDirectObject],
        expected: Sequence[Tuple[str, str]],
    ) -> None:
        observed = tuple((item.service, item.actual_type) for item in created)
        if observed != tuple(expected):
            raise DirectAdapterFailure("CREATED_OBJECT_TYPE_MISMATCH")

    @staticmethod
    def _one(
        by_service: Mapping[str, Sequence[CreatedDirectObject]],
        service: str,
    ) -> CreatedDirectObject:
        values = by_service[service]
        if len(values) != 1:
            raise LifecycleRejected("SAGA_CREATED_OBJECT_SET_INVALID")
        return values[0]

    @staticmethod
    def _ids(objects: Sequence[CreatedDirectObject]) -> Tuple[str, ...]:
        return tuple(item.object_id for item in objects)

    def _finish_after_definite_failure(
        self,
        request: CampaignCreationRequest,
        detail: str,
        now: datetime,
    ) -> None:
        created = self.store.created_objects(request.run_id)
        if not created:
            self.store.finish(
                request.execution_key,
                CampaignSagaState.FAILED,
                detail,
                now,
            )
            return
        failed_compensations = []
        for item in reversed(created):
            try:
                self._delete_created(request.run_id, item)
                self.store.mark_compensated(
                    request.run_id,
                    item.service,
                    item.object_id,
                    now,
                )
            except (DirectAdapterFailure, DirectOutcomeUnknown, RuntimeError) as error:
                failed_compensations.append(
                    item.service.value + ":" + item.object_id + ":" + str(error)
                )
        if failed_compensations:
            status = CampaignSagaState.COMPENSATION_REQUIRED
            outcome_detail = detail + "; " + "; ".join(failed_compensations)
        else:
            status = CampaignSagaState.PARTIALLY_APPLIED
            outcome_detail = detail
        self.store.finish(request.execution_key, status, outcome_detail, now)

    def _delete_created(self, run_id: str, item: CreatedDirectObject) -> None:
        methods = {
            "Campaigns": self.connector.campaigns_delete,
            "AdGroups": self.connector.adgroups_delete,
            "Ads": self.connector.ads_delete,
            "Keywords": self.connector.keywords_delete,
        }
        methods[item.service.value](run_id, item.object_id)
