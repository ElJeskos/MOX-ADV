"""Durable authority and execution state for approval-required changes."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import sqlite3
import subprocess
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Protocol, Tuple

from mox_adv.commands import OptimizationAction
from mox_adv.interrupt_state import (
    DurableInterruptState,
    InterruptStateUnavailable,
    kill_switch_scopes,
)


class ControlRejected(RuntimeError):
    """A control-plane operation failed closed."""

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(reason_code + ": " + detail)
        self.reason_code = reason_code


class ExecutionStatus(str, Enum):
    RESERVED = "RESERVED"
    IN_FLIGHT = "IN_FLIGHT"
    APPLIED = "APPLIED"
    NO_CHANGE = "NO_CHANGE"
    BLOCKED = "BLOCKED"
    ALREADY_PROCESSED = "ALREADY_PROCESSED"
    UNKNOWN_RESULT = "UNKNOWN_RESULT"
    FAILED = "FAILED"


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ControlRejected("INVALID_INPUT", "timestamp must be timezone-aware.")
    return value.astimezone(timezone.utc).isoformat()


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ControlRejected("INVALID_INPUT", "timestamp must be ISO UTC.") from error
    if parsed.tzinfo is None:
        raise ControlRejected("INVALID_INPUT", "timestamp must be timezone-aware.")
    return parsed.astimezone(timezone.utc)


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_hash(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    identity: str
    authentication: str


class ElevatedReauthenticationVerifier(Protocol):
    def verify(self, principal: AuthenticatedPrincipal) -> bool: ...


class MacOSElevatedSecurityVerifier:
    """Use the OS authorization cache without reading or accepting a secret."""

    def verify(self, principal: AuthenticatedPrincipal) -> bool:
        if principal.authentication != "authenticated_macos_user":
            return False
        try:
            completed = subprocess.run(
                ["/usr/bin/sudo", "-n", "-v"],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0


class MacOSLocalPrincipalAuthenticator:
    """Authenticate the Gate 0 control principal at the local OS seam."""

    def __init__(
        self,
        expected_identity: str = "sviridov",
        elevated_verifier: Optional[ElevatedReauthenticationVerifier] = None,
    ) -> None:
        self.expected_identity = expected_identity
        self.elevated_verifier = (
            MacOSElevatedSecurityVerifier()
            if elevated_verifier is None
            else elevated_verifier
        )

    def authenticate(self) -> AuthenticatedPrincipal:
        identity = getpass.getuser()
        if identity != self.expected_identity:
            raise ControlRejected(
                "UNAUTHENTICATED_PRINCIPAL",
                "local macOS user does not match the Gate 0 principal.",
            )
        return AuthenticatedPrincipal(
            identity=identity,
            authentication="authenticated_macos_user",
        )

    def elevated_reauthenticate(self) -> AuthenticatedPrincipal:
        principal = self.authenticate()
        if not self.elevated_verifier.verify(principal):
            raise ControlRejected(
                "ELEVATED_REAUTHENTICATION_FAILED",
                "macOS elevated reauthentication did not succeed.",
            )
        return principal


class CampaignApprovalRepository:
    """Own every persistence transition for campaign-creation approvals."""

    @staticmethod
    def reserve(
        connection: sqlite3.Connection,
        *,
        approval_id: str,
        proposal_id: str,
        binding_hash: str,
        approver: str,
        authentication: str,
        execution_key: str,
        now_text: str,
    ) -> None:
        approval = connection.execute(
            "SELECT * FROM campaign_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        if approval is None:
            raise ControlRejected(
                "CAMPAIGN_APPROVAL_NOT_FOUND",
                "campaign approval does not exist.",
            )
        if (
            approval["status"] != "AVAILABLE"
            or approval["proposal_id"] != proposal_id
            or approval["binding_hash"] != binding_hash
            or approval["approver"] != approver
            or approval["authentication"] != authentication
            or approval["expires_at"] <= now_text
        ):
            raise ControlRejected(
                "CAMPAIGN_APPROVAL_NOT_AUTHORIZED",
                "campaign approval is not bound, current, and available.",
            )
        updated = connection.execute(
            "UPDATE campaign_approvals SET status = 'RESERVED', "
            "reserved_execution_key = ? WHERE approval_id = ? "
            "AND status = 'AVAILABLE'",
            (execution_key, approval_id),
        ).rowcount
        if updated != 1:
            raise ControlRejected(
                "CAMPAIGN_APPROVAL_ALREADY_USED",
                "campaign approval could not be reserved.",
            )

    @staticmethod
    def consume(
        connection: sqlite3.Connection,
        *,
        approval_id: str,
        execution_key: str,
        now_text: str,
    ) -> None:
        updated = connection.execute(
            "UPDATE campaign_approvals SET status = 'USED', used_at = ? "
            "WHERE approval_id = ? AND status = 'RESERVED' "
            "AND reserved_execution_key = ?",
            (now_text, approval_id, execution_key),
        ).rowcount
        if updated != 1:
            raise ControlRejected(
                "CAMPAIGN_APPROVAL_USE_FAILED",
                "campaign approval could not be consumed.",
            )

    @staticmethod
    def authority_is_valid(
        connection: sqlite3.Connection,
        *,
        approval_id: str,
        proposal_id: str,
        binding_hash: str,
        execution_key: str,
    ) -> bool:
        row = connection.execute(
            "SELECT proposal_id, binding_hash, status, reserved_execution_key "
            "FROM campaign_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        return bool(
            row is not None
            and row["proposal_id"] == proposal_id
            and row["binding_hash"] == binding_hash
            and row["status"] in {"RESERVED", "USED"}
            and row["reserved_execution_key"] == execution_key
        )

    @staticmethod
    def status(connection: sqlite3.Connection, approval_id: str) -> str:
        row = connection.execute(
            "SELECT status FROM campaign_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        if row is None:
            raise ControlRejected(
                "CAMPAIGN_APPROVAL_NOT_FOUND",
                "campaign approval does not exist.",
            )
        return str(row["status"])


@dataclass(frozen=True)
class TrustedScope:
    organization: str
    connection: str
    account: str
    campaign: str
    writer: str


@dataclass(frozen=True)
class PreparedChange:
    proposal_id: str
    proposal_hash: str
    scope: TrustedScope
    action: OptimizationAction
    current_value: Any
    target_value: Any
    expected_diff: Mapping[str, Any]
    snapshot_id: str
    snapshot_generated_at: str
    direct_watermark: str
    metrika_watermark: str
    policy_version: str
    expected_fingerprint: str
    risk: str

    def as_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["expected_diff"] = dict(self.expected_diff)
        return value

    def binding_hash(self) -> str:
        return canonical_hash(self.as_dict())

    def execution_key(self) -> str:
        return canonical_hash(
            {
                "organization": self.scope.organization,
                "connection": self.scope.connection,
                "campaign": self.scope.campaign,
                "proposal_id": self.proposal_id,
                "proposal_hash": self.proposal_hash,
                "action": self.action,
                "target_value": self.target_value,
                "expected_fingerprint": self.expected_fingerprint,
                "policy_version": self.policy_version,
            }
        )

    def target_key(self) -> str:
        return ":".join(
            (
                self.scope.organization,
                self.scope.connection,
                self.scope.account,
                self.scope.campaign,
                self.action,
            )
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PreparedChange":
        scope = value["scope"]
        if not isinstance(scope, Mapping):
            raise ControlRejected("INVALID_INPUT", "prepared scope is invalid.")
        return cls(
            proposal_id=str(value["proposal_id"]),
            proposal_hash=str(value["proposal_hash"]),
            scope=TrustedScope(
                organization=str(scope["organization"]),
                connection=str(scope["connection"]),
                account=str(scope["account"]),
                campaign=str(scope["campaign"]),
                writer=str(scope["writer"]),
            ),
            action=OptimizationAction(value["action"]),
            current_value=value["current_value"],
            target_value=value["target_value"],
            expected_diff=dict(value["expected_diff"]),
            snapshot_id=str(value["snapshot_id"]),
            snapshot_generated_at=str(value["snapshot_generated_at"]),
            direct_watermark=str(value["direct_watermark"]),
            metrika_watermark=str(value["metrika_watermark"]),
            policy_version=str(value["policy_version"]),
            expected_fingerprint=str(value["expected_fingerprint"]),
            risk=str(value["risk"]),
        )


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    proposal_id: str
    binding_hash: str
    canonical_hash: str
    approver: str
    reason: str
    granted_at: str
    expires_at: str
    revoked_at: Optional[str]
    reserved_at: Optional[str]
    reserved_execution_key: Optional[str]
    used_at: Optional[str]
    execution_key: Optional[str]

    @property
    def used(self) -> bool:
        return self.used_at is not None


@dataclass(frozen=True)
class ExecutionRecord:
    execution_key: str
    proposal_id: str
    status: ExecutionStatus
    target_key: str
    current_value: Any
    target_value: Any
    detail: Optional[str]
    created_at: str
    updated_at: str


class DurableControlState:
    """SQLite-backed approval, kill-switch, and single-writer ledger."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.interrupts = DurableInterruptState(path)
        except InterruptStateUnavailable as error:
            raise ControlRejected(
                "KILL_SWITCH_UNAVAILABLE",
                "durable interrupt state is unavailable.",
            ) from error
        self._initialize()
        with suppress(OSError):
            os.chmod(self.path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=0.25)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 250")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS prepared_changes (
                    proposal_id TEXT PRIMARY KEY,
                    canonical_json TEXT NOT NULL,
                    canonical_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    binding_hash TEXT NOT NULL,
                    canonical_hash TEXT NOT NULL UNIQUE,
                    approver TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    granted_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    reserved_at TEXT,
                    reserved_execution_key TEXT,
                    used_at TEXT,
                    execution_key TEXT,
                    FOREIGN KEY(proposal_id) REFERENCES prepared_changes(proposal_id)
                );
                CREATE TABLE IF NOT EXISTS campaign_approvals (
                    approval_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    binding_hash TEXT NOT NULL,
                    approver TEXT NOT NULL,
                    authentication TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reserved_execution_key TEXT,
                    used_at TEXT
                );
                CREATE TABLE IF NOT EXISTS kill_switches (
                    scope TEXT PRIMARY KEY,
                    active INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    principal TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS executions (
                    execution_key TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    target_key TEXT NOT NULL,
                    current_value_json TEXT NOT NULL,
                    target_value_json TEXT NOT NULL,
                    detail TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(proposal_id) REFERENCES prepared_changes(proposal_id)
                );
                CREATE TRIGGER IF NOT EXISTS approvals_immutable_fields
                BEFORE UPDATE OF
                    proposal_id,
                    binding_hash,
                    canonical_hash,
                    approver,
                    reason,
                    granted_at,
                    expires_at
                ON approvals
                BEGIN
                    SELECT RAISE(ABORT, 'immutable approval fields');
                END;
                """
            )

    def register_campaign_approval_authority(
        self,
        *,
        approval_id: str,
        proposal_id: str,
        binding_hash: str,
        approver: str,
        authentication: str,
        expires_at: datetime,
    ) -> None:
        immutable = (
            proposal_id,
            binding_hash,
            approver,
            authentication,
            _utc_text(expires_at),
        )
        if (
            not approval_id
            or not proposal_id
            or not binding_hash.startswith("sha256:")
            or not approver
            or not authentication
        ):
            raise ControlRejected(
                "INVALID_INPUT",
                "campaign approval authority is invalid.",
            )
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM campaign_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if existing is not None:
                if (
                    tuple(
                        existing[name]
                        for name in (
                            "proposal_id",
                            "binding_hash",
                            "approver",
                            "authentication",
                            "expires_at",
                        )
                    )
                    != immutable
                ):
                    raise ControlRejected(
                        "IMMUTABLE_APPROVAL_CONFLICT",
                        "campaign approval binding changed.",
                    )
                return
            connection.execute(
                "INSERT INTO campaign_approvals "
                "(approval_id, proposal_id, binding_hash, approver, authentication, "
                "expires_at, status) VALUES (?, ?, ?, ?, ?, ?, 'AVAILABLE')",
                (approval_id,) + immutable,
            )

    def register_prepared_change(self, prepared: PreparedChange) -> None:
        canonical_json = _canonical(prepared.as_dict())
        digest = canonical_hash(prepared.as_dict())
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT canonical_json, canonical_hash "
                "FROM prepared_changes WHERE proposal_id = ?",
                (prepared.proposal_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["canonical_json"] != canonical_json
                    or existing["canonical_hash"] != digest
                ):
                    raise ControlRejected(
                        "IMMUTABLE_PROPOSAL_CONFLICT",
                        "proposal scope, diff, snapshot, or fingerprint changed.",
                    )
                return
            connection.execute(
                "INSERT INTO prepared_changes "
                "(proposal_id, canonical_json, canonical_hash) VALUES (?, ?, ?)",
                (prepared.proposal_id, canonical_json, digest),
            )

    def load_prepared_change(self, proposal_id: str) -> PreparedChange:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT canonical_json, canonical_hash "
                "FROM prepared_changes WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            raise ControlRejected("APPROVAL_NOT_FOUND", "proposal is not prepared.")
        value = json.loads(row["canonical_json"])
        if canonical_hash(value) != row["canonical_hash"]:
            raise ControlRejected(
                "IMMUTABLE_PROPOSAL_CONFLICT",
                "prepared proposal canonical hash is invalid.",
            )
        return PreparedChange.from_dict(value)

    def grant_approval(
        self,
        proposal_id: str,
        expires_at: datetime,
        reason: str,
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> ApprovalRecord:
        if (
            principal.identity != "sviridov"
            or principal.authentication != "authenticated_macos_user"
        ):
            raise ControlRejected(
                "UNAUTHENTICATED_PRINCIPAL",
                "only the Gate 0 approver may grant approval.",
            )
        if not reason.strip():
            raise ControlRejected("INVALID_INPUT", "approval reason is required.")
        if expires_at <= now:
            raise ControlRejected("APPROVAL_EXPIRED", "approval expiry must be future.")
        prepared = self.load_prepared_change(proposal_id)
        granted_at_text = _utc_text(now)
        expires_at_text = _utc_text(expires_at)
        immutable = {
            "schema_version": "approval-v1",
            "proposal_id": proposal_id,
            "binding_hash": prepared.binding_hash(),
            "approver": principal.identity,
            "authentication": principal.authentication,
            "reason": reason,
            "granted_at": granted_at_text,
            "expires_at": expires_at_text,
        }
        digest = canonical_hash(immutable)
        approval_id = "approval-" + digest.removeprefix("sha256:")[:24]
        with self._connect() as connection, suppress(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO approvals "
                "(approval_id, proposal_id, binding_hash, canonical_hash, "
                "approver, reason, granted_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    approval_id,
                    proposal_id,
                    prepared.binding_hash(),
                    digest,
                    principal.identity,
                    reason,
                    granted_at_text,
                    expires_at_text,
                ),
            )
        return self.load_approval(approval_id)

    def load_approval(self, approval_id: str) -> ApprovalRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        if row is None:
            raise ControlRejected("APPROVAL_NOT_FOUND", "approval does not exist.")
        return self._approval_from_row(row)

    def load_active_approval(
        self,
        proposal_id: str,
        binding_hash: str,
        now: datetime,
    ) -> ApprovalRecord:
        approval = self.load_bound_approval(proposal_id, binding_hash)
        if approval.revoked_at is not None:
            raise ControlRejected("APPROVAL_REVOKED", "approval was revoked.")
        if approval.used:
            raise ControlRejected("APPROVAL_ALREADY_USED", "approval is single-use.")
        if _parse_utc(approval.expires_at) <= now.astimezone(timezone.utc):
            raise ControlRejected("APPROVAL_EXPIRED", "approval has expired.")
        return approval

    def load_bound_approval(
        self,
        proposal_id: str,
        binding_hash: str,
    ) -> ApprovalRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE proposal_id = ? "
                "ORDER BY granted_at DESC LIMIT 1",
                (proposal_id,),
            ).fetchone()
        if row is None:
            raise ControlRejected("APPROVAL_NOT_FOUND", "approval does not exist.")
        approval = self._approval_from_row(row)
        if approval.binding_hash != binding_hash:
            raise ControlRejected(
                "APPROVAL_SCOPE_MISMATCH",
                "approval does not bind the current exact proposal.",
            )
        return approval

    def revoke_approval(
        self,
        approval_id: str,
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT approver, used_at, revoked_at FROM approvals "
                "WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None or row["approver"] != principal.identity:
                raise ControlRejected(
                    "APPROVAL_NOT_FOUND",
                    "approval is not revocable.",
                )
            if row["used_at"] is not None:
                raise ControlRejected(
                    "APPROVAL_ALREADY_USED",
                    "used approval cannot be revoked.",
                )
            if row["revoked_at"] is None:
                connection.execute(
                    "UPDATE approvals SET revoked_at = ? WHERE approval_id = ?",
                    (_utc_text(now), approval_id),
                )

    def reserve_execution(
        self,
        prepared: PreparedChange,
        now: datetime,
    ) -> Tuple[ExecutionStatus, ExecutionRecord]:
        now_text = _utc_text(now)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            unresolved = connection.execute(
                "SELECT execution_key FROM executions "
                "WHERE status = 'UNKNOWN_RESULT' LIMIT 1"
            ).fetchone()
            if unresolved is not None:
                connection.rollback()
                raise ControlRejected(
                    "UNKNOWN_RESULT",
                    "an unresolved execution blocks the next write.",
                )
            existing = connection.execute(
                "SELECT * FROM executions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            if existing is not None:
                record = self._execution_from_row(existing)
                connection.rollback()
                outcome = (
                    ExecutionStatus.ALREADY_PROCESSED
                    if record.status in {"APPLIED", "NO_CHANGE"}
                    else record.status
                )
                return outcome, record
            other = connection.execute(
                "SELECT * FROM executions "
                "WHERE status IN ('RESERVED', 'IN_FLIGHT') LIMIT 1"
            ).fetchone()
            if other is not None:
                record = self._execution_from_row(other)
                connection.rollback()
                return ExecutionStatus.BLOCKED, record
            connection.execute(
                "INSERT INTO executions "
                "(execution_key, proposal_id, status, target_key, "
                "current_value_json, target_value_json, created_at, updated_at) "
                "VALUES (?, ?, 'RESERVED', ?, ?, ?, ?, ?)",
                (
                    prepared.execution_key(),
                    prepared.proposal_id,
                    prepared.target_key(),
                    json.dumps(prepared.current_value),
                    json.dumps(prepared.target_value),
                    now_text,
                    now_text,
                ),
            )
            row = connection.execute(
                "SELECT * FROM executions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            connection.commit()
            return ExecutionStatus.RESERVED, self._execution_from_row(row)
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def begin_execution(
        self,
        prepared: PreparedChange,
        approval: ApprovalRecord,
        now: datetime,
    ) -> ExecutionRecord:
        now_text = _utc_text(now)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval.approval_id,),
            ).fetchone()
            current = self._approval_from_row(row) if row is not None else None
            if (
                current is None
                or current.used
                or current.revoked_at is not None
                or current.reserved_at is not None
                or current.binding_hash != prepared.binding_hash()
                or _parse_utc(current.expires_at) <= now.astimezone(timezone.utc)
            ):
                raise ControlRejected(
                    "APPROVAL_NOT_APPLICABLE",
                    "approval changed, expired, or was already consumed.",
                )
            updated = connection.execute(
                "UPDATE approvals SET reserved_at = ?, reserved_execution_key = ? "
                "WHERE approval_id = ? AND reserved_at IS NULL "
                "AND used_at IS NULL AND revoked_at IS NULL",
                (now_text, prepared.execution_key(), approval.approval_id),
            )
            if updated.rowcount != 1:
                raise ControlRejected(
                    "APPROVAL_ALREADY_USED",
                    "approval was consumed concurrently.",
                )
            changed = connection.execute(
                "UPDATE executions SET status = 'IN_FLIGHT', updated_at = ? "
                "WHERE execution_key = ? AND status = 'RESERVED'",
                (now_text, prepared.execution_key()),
            )
            if changed.rowcount != 1:
                raise ControlRejected(
                    "EXECUTION_CONFLICT",
                    "execution reservation is no longer available.",
                )
            execution_row = connection.execute(
                "SELECT * FROM executions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            connection.commit()
            return self._execution_from_row(execution_row)
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def send_once(
        self,
        prepared: PreparedChange,
        approval: ApprovalRecord,
        now: datetime,
        sender: Callable[[], None],
        at_dispatch_boundary: Optional[Callable[[], None]] = None,
    ) -> Tuple[ExecutionStatus, ExecutionRecord]:
        """Commit authority and IN_FLIGHT before the immediate dispatch boundary."""

        now_text = _utc_text(now)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            unresolved = connection.execute(
                "SELECT execution_key FROM executions "
                "WHERE status = 'UNKNOWN_RESULT' LIMIT 1"
            ).fetchone()
            if unresolved is not None:
                raise ControlRejected(
                    "UNKNOWN_RESULT",
                    "an unresolved execution blocks the next write.",
                )
            existing = connection.execute(
                "SELECT * FROM executions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            if existing is not None:
                record = self._execution_from_row(existing)
                connection.rollback()
                outcome = (
                    ExecutionStatus.ALREADY_PROCESSED
                    if record.status
                    in {
                        ExecutionStatus.RESERVED,
                        ExecutionStatus.IN_FLIGHT,
                        ExecutionStatus.APPLIED,
                        ExecutionStatus.NO_CHANGE,
                    }
                    else record.status
                )
                return outcome, record
            other = connection.execute(
                "SELECT * FROM executions "
                "WHERE status IN ('RESERVED', 'IN_FLIGHT') LIMIT 1"
            ).fetchone()
            if other is not None:
                record = self._execution_from_row(other)
                connection.rollback()
                return ExecutionStatus.BLOCKED, record
            if self._kill_switch_active_in_connection(connection, prepared.scope):
                raise ControlRejected(
                    "KILL_SWITCH_ACTIVE",
                    "durable kill switch blocks the unsent command.",
                )
            self._require_no_interrupt(prepared.scope)
            approval_row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval.approval_id,),
            ).fetchone()
            current = (
                self._approval_from_row(approval_row)
                if approval_row is not None
                else None
            )
            if (
                current is None
                or current.used
                or current.revoked_at is not None
                or current.reserved_at is not None
                or current.binding_hash != prepared.binding_hash()
                or _parse_utc(current.expires_at) <= now.astimezone(timezone.utc)
            ):
                raise ControlRejected(
                    "APPROVAL_NOT_APPLICABLE",
                    "approval changed, expired, or was already consumed.",
                )
            connection.execute(
                "INSERT INTO executions "
                "(execution_key, proposal_id, status, target_key, "
                "current_value_json, target_value_json, created_at, updated_at) "
                "VALUES (?, ?, 'RESERVED', ?, ?, ?, ?, ?)",
                (
                    prepared.execution_key(),
                    prepared.proposal_id,
                    prepared.target_key(),
                    json.dumps(prepared.current_value),
                    json.dumps(prepared.target_value),
                    now_text,
                    now_text,
                ),
            )
            reserved = connection.execute(
                "UPDATE approvals SET reserved_at = ?, reserved_execution_key = ? "
                "WHERE approval_id = ? AND reserved_at IS NULL "
                "AND used_at IS NULL AND revoked_at IS NULL",
                (now_text, prepared.execution_key(), approval.approval_id),
            )
            if reserved.rowcount != 1:
                raise ControlRejected(
                    "APPROVAL_ALREADY_USED",
                    "approval was reserved concurrently.",
                )
            moved = connection.execute(
                "UPDATE executions SET status = 'IN_FLIGHT', updated_at = ? "
                "WHERE execution_key = ? AND status = 'RESERVED'",
                (now_text, prepared.execution_key()),
            )
            if moved.rowcount != 1:
                raise ControlRejected(
                    "EXECUTION_CONFLICT",
                    "execution reservation is no longer available.",
                )
            if self._kill_switch_active_in_connection(connection, prepared.scope):
                raise ControlRejected(
                    "KILL_SWITCH_ACTIVE",
                    "durable kill switch blocks the unsent command.",
                )
            self._require_no_interrupt(prepared.scope)
            consumed = connection.execute(
                "UPDATE approvals SET used_at = ?, execution_key = ? "
                "WHERE approval_id = ? AND reserved_execution_key = ? "
                "AND used_at IS NULL",
                (
                    now_text,
                    prepared.execution_key(),
                    approval.approval_id,
                    prepared.execution_key(),
                ),
            )
            if consumed.rowcount != 1:
                raise ControlRejected(
                    "APPROVAL_NOT_APPLICABLE",
                    "approval reservation cannot be consumed.",
                )
            row = connection.execute(
                "SELECT * FROM executions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            connection.commit()
            record = self._execution_from_row(row)
        except ControlRejected:
            if connection.in_transaction:
                connection.rollback()
            raise
        except sqlite3.Error as error:
            if connection.in_transaction:
                connection.rollback()
            raise ControlRejected(
                "CONTROL_STATE_UNAVAILABLE",
                "durable authority state is unavailable.",
            ) from error
        finally:
            connection.close()

        try:
            self._require_no_interrupt(prepared.scope)
            with self._connect() as dispatch_connection:
                if self._kill_switch_active_in_connection(
                    dispatch_connection,
                    prepared.scope,
                ):
                    raise ControlRejected(
                        "KILL_SWITCH_ACTIVE",
                        "durable kill switch blocks the unsent command.",
                    )
            if at_dispatch_boundary is not None:
                at_dispatch_boundary()
        except ControlRejected as error:
            self.finish_execution(
                prepared.execution_key(),
                ExecutionStatus.BLOCKED,
                error.reason_code,
                now,
            )
            raise
        sender()
        return ExecutionStatus.IN_FLIGHT, record

    def mark_approval_used(
        self,
        approval_id: str,
        execution_key: str,
        now: datetime,
    ) -> None:
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE approvals SET used_at = ?, execution_key = ? "
                "WHERE approval_id = ? AND reserved_execution_key = ? "
                "AND used_at IS NULL",
                (_utc_text(now), execution_key, approval_id, execution_key),
            )
            if changed.rowcount != 1:
                raise ControlRejected(
                    "APPROVAL_NOT_APPLICABLE",
                    "approval reservation cannot be consumed.",
                )

    def release_approval_reservation(
        self,
        approval_id: str,
        execution_key: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE approvals SET reserved_at = NULL, "
                "reserved_execution_key = NULL "
                "WHERE approval_id = ? AND reserved_execution_key = ? "
                "AND used_at IS NULL",
                (approval_id, execution_key),
            )

    def finish_execution(
        self,
        execution_key: str,
        status: ExecutionStatus,
        detail: Optional[str],
        now: datetime,
    ) -> ExecutionRecord:
        try:
            terminal_status = ExecutionStatus(status)
        except ValueError as error:
            raise ControlRejected(
                "INVALID_INPUT",
                "execution status is invalid.",
            ) from error
        if terminal_status not in {
            ExecutionStatus.APPLIED,
            ExecutionStatus.NO_CHANGE,
            ExecutionStatus.BLOCKED,
            ExecutionStatus.UNKNOWN_RESULT,
            ExecutionStatus.FAILED,
        }:
            raise ControlRejected("INVALID_INPUT", "execution status is not terminal.")
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE executions SET status = ?, detail = ?, updated_at = ? "
                "WHERE execution_key = ? "
                "AND status IN ('RESERVED', 'IN_FLIGHT')",
                (
                    terminal_status.value,
                    detail,
                    _utc_text(now),
                    execution_key,
                ),
            )
            if changed.rowcount != 1:
                existing = connection.execute(
                    "SELECT status FROM executions WHERE execution_key = ?",
                    (execution_key,),
                ).fetchone()
                if existing is None or existing["status"] != terminal_status.value:
                    raise ControlRejected(
                        "ILLEGAL_EXECUTION_TRANSITION",
                        "terminal execution state is immutable.",
                    )
        return self.load_execution(execution_key)

    def load_execution(self, execution_key: str) -> ExecutionRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM executions WHERE execution_key = ?",
                (execution_key,),
            ).fetchone()
        if row is None:
            raise ControlRejected("EXECUTION_NOT_FOUND", "execution does not exist.")
        return self._execution_from_row(row)

    def engage_kill_switch(
        self,
        scope: str,
        reason: str,
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> None:
        self._validate_incident_control(scope, reason, principal)
        try:
            self.interrupts.engage("kill_switch", scope, reason, now)
        except InterruptStateUnavailable as error:
            raise ControlRejected(
                "KILL_SWITCH_UNAVAILABLE",
                "durable interrupt state is unavailable.",
            ) from error
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO kill_switches "
                "(scope, active, reason, principal, updated_at) "
                "VALUES (?, 1, ?, ?, ?) "
                "ON CONFLICT(scope) DO UPDATE SET active = 1, "
                "reason = excluded.reason, "
                "principal = excluded.principal, updated_at = excluded.updated_at",
                (scope, reason, principal.identity, _utc_text(now)),
            )

    def release_kill_switch(
        self,
        scope: str,
        reason: str,
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> None:
        self._validate_incident_control(scope, reason, principal)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO kill_switches "
                "(scope, active, reason, principal, updated_at) "
                "VALUES (?, 0, ?, ?, ?) "
                "ON CONFLICT(scope) DO UPDATE SET active = 0, "
                "reason = excluded.reason, "
                "principal = excluded.principal, updated_at = excluded.updated_at",
                (scope, reason, principal.identity, _utc_text(now)),
            )
        try:
            self.interrupts.release("kill_switch", scope, reason, now)
        except InterruptStateUnavailable as error:
            raise ControlRejected(
                "KILL_SWITCH_UNAVAILABLE",
                "durable interrupt state remains engaged.",
            ) from error

    def kill_switch_active(self, scope: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT active FROM kill_switches WHERE scope = ?",
                (scope,),
            ).fetchone()
        return row is not None and bool(row["active"])

    def any_kill_switch_active(self, scope: TrustedScope) -> bool:
        try:
            self._require_no_interrupt(scope)
            with self._connect() as connection:
                return self._kill_switch_active_in_connection(connection, scope)
        except sqlite3.Error as error:
            raise ControlRejected(
                "KILL_SWITCH_UNAVAILABLE",
                "durable kill-switch state is unavailable.",
            ) from error

    def _require_no_interrupt(self, scope: TrustedScope) -> None:
        try:
            active = self.interrupts.any_active(
                "kill_switch",
                kill_switch_scopes(
                    scope.organization,
                    scope.connection,
                    scope.campaign,
                ),
            )
        except InterruptStateUnavailable as error:
            raise ControlRejected(
                "KILL_SWITCH_UNAVAILABLE",
                "durable interrupt state is unavailable.",
            ) from error
        if active:
            raise ControlRejected(
                "KILL_SWITCH_ACTIVE",
                "durable kill switch blocks the unsent command.",
            )

    @staticmethod
    def _kill_switch_active_in_connection(
        connection: sqlite3.Connection,
        scope: TrustedScope,
    ) -> bool:
        scopes = (
            "global",
            "organization:" + scope.organization,
            "connection:" + scope.connection,
            "campaign:" + scope.campaign,
        )
        placeholders = ",".join("?" for _ in scopes)
        row = connection.execute(
            "SELECT 1 FROM kill_switches "
            f"WHERE active = 1 AND scope IN ({placeholders}) LIMIT 1",
            scopes,
        ).fetchone()
        return row is not None

    @staticmethod
    def _validate_incident_control(
        scope: str,
        reason: str,
        principal: AuthenticatedPrincipal,
    ) -> None:
        valid_scope = scope == "global" or scope.startswith(
            ("organization:", "connection:", "campaign:")
        )
        if not valid_scope or not reason.strip():
            raise ControlRejected(
                "INVALID_INPUT",
                "kill-switch scope or reason invalid.",
            )
        if (
            principal.identity != "sviridov"
            or principal.authentication != "authenticated_macos_user"
        ):
            raise ControlRejected(
                "UNAUTHENTICATED_PRINCIPAL",
                "only the incident principal may control the kill switch.",
            )

    @staticmethod
    def _approval_from_row(row: sqlite3.Row) -> ApprovalRecord:
        record = ApprovalRecord(
            approval_id=row["approval_id"],
            proposal_id=row["proposal_id"],
            binding_hash=row["binding_hash"],
            canonical_hash=row["canonical_hash"],
            approver=row["approver"],
            reason=row["reason"],
            granted_at=row["granted_at"],
            expires_at=row["expires_at"],
            revoked_at=row["revoked_at"],
            reserved_at=row["reserved_at"],
            reserved_execution_key=row["reserved_execution_key"],
            used_at=row["used_at"],
            execution_key=row["execution_key"],
        )
        immutable = {
            "schema_version": "approval-v1",
            "proposal_id": record.proposal_id,
            "binding_hash": record.binding_hash,
            "approver": record.approver,
            "authentication": "authenticated_macos_user",
            "reason": record.reason,
            "granted_at": record.granted_at,
            "expires_at": record.expires_at,
        }
        if canonical_hash(immutable) != record.canonical_hash:
            raise ControlRejected(
                "APPROVAL_INTEGRITY_FAILURE",
                "approval canonical hash is invalid.",
            )
        return record

    @staticmethod
    def _execution_from_row(row: sqlite3.Row) -> ExecutionRecord:
        return ExecutionRecord(
            execution_key=row["execution_key"],
            proposal_id=row["proposal_id"],
            status=ExecutionStatus(row["status"]),
            target_key=row["target_key"],
            current_value=json.loads(row["current_value_json"]),
            target_value=json.loads(row["target_value_json"]),
            detail=row["detail"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
