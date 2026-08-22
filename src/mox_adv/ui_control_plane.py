"""JSON-safe Dashboard facade for durable control-plane capabilities.

This module presents existing approval, Mandate, kill-switch, and execution
state without crossing the external write boundary.  Every authority mutation
is delegated to the existing durable backend; this facade never sends a Yandex
command and never claims that an external execution has been authorized.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from mox_adv.autonomy_contracts import MandateRecord, parse_utc
from mox_adv.control_state import (
    ApprovalRecord,
    AuthenticatedPrincipal,
    ControlRejected,
    DurableControlState,
    ElevatedAuthenticatedPrincipal,
    ExecutionRecord,
    ExecutionStatus,
    TrustedScope,
)
from mox_adv.mandate_store import DurableMandateAuthority


class OperatingMode(str, Enum):
    OBSERVE = "OBSERVE"
    RECOMMEND = "RECOMMEND"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    BOUNDED_AUTONOMY = "BOUNDED_AUTONOMY"


_MODE_PRESENTATION = {
    OperatingMode.OBSERVE: {
        "write_capable": False,
        "authority": "NONE",
        "effect": "READ_ONLY_ANALYTICS",
    },
    OperatingMode.RECOMMEND: {
        "write_capable": False,
        "authority": "NONE",
        "effect": "READ_ONLY_RECOMMENDATIONS",
    },
    OperatingMode.APPROVAL_REQUIRED: {
        "write_capable": True,
        "authority": "EXACT_IMMUTABLE_APPROVAL",
        "effect": "EXECUTOR_POLICY_RECHECK_REQUIRED",
    },
    OperatingMode.BOUNDED_AUTONOMY: {
        "write_capable": True,
        "authority": "ACTIVE_SCOPED_MANDATE",
        "effect": "EXECUTOR_POLICY_RECHECK_REQUIRED",
    },
}
_TERMINAL_EXECUTION_STATUSES = {
    ExecutionStatus.APPLIED,
    ExecutionStatus.NO_CHANGE,
    ExecutionStatus.BLOCKED,
    ExecutionStatus.FAILED,
}
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(token|secret|password|authorization|api[_-]?key)"
    r"\s*[:=]\s*[^\s,;]+"
)
_SENSITIVE_AUTH_VALUE = re.compile(r"(?i)\b(bearer|oauth)\s+[^\s,;]+")


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ControlRejected("INVALID_INPUT", "timestamp must be timezone-aware.")
    return value.astimezone(timezone.utc).isoformat()


def _redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    redacted = _SENSITIVE_ASSIGNMENT.sub(
        lambda match: match.group(1) + "=[REDACTED]",
        value,
    )
    return _SENSITIVE_AUTH_VALUE.sub(
        lambda match: match.group(1) + " [REDACTED]",
        redacted,
    )


class DashboardControlPlane:
    """Public, localhost-oriented JSON facade over durable safety state."""

    schema_version = "dashboard-control-plane-v1"

    def __init__(
        self,
        control_state: DurableControlState,
        mandate_authority: DurableMandateAuthority,
        policy: Mapping[str, Any],
    ) -> None:
        self.control_state = control_state
        self.mandate_authority = mandate_authority
        self.policy = policy
        self.path = Path(control_state.path)
        if self.path.resolve() != Path(mandate_authority.path).resolve():
            raise ControlRejected(
                "CONTROL_STATE_MISMATCH",
                "approval and Mandate authorities must share one durable store.",
            )
        self._initialize()

    def overview(
        self,
        *,
        now: datetime,
        proposal_id: str | None = None,
        binding_hash: str | None = None,
        mandate_id: str | None = None,
        scope: TrustedScope | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        """Return the complete JSON-safe control-plane projection."""

        _utc_text(now)
        mode = self.operating_mode()
        return {
            "schema_version": self.schema_version,
            "operating_mode": mode,
            "operating_modes": self.operating_modes(),
            "gates": self.gate_state(),
            "preconditions": self.precondition_state(
                now=now,
                proposal_id=proposal_id,
                binding_hash=binding_hash,
                mandate_id=mandate_id,
                scope=scope,
                environment=environment,
            ),
            "approvals": self.list_approvals(now=now),
            "mandates": self.list_mandates(now=now),
            "kill_switches": self.list_kill_switches(),
            "executions": self.list_executions(),
            "execution_authorized": False,
            "authorization_boundary": "BACKEND_EXECUTOR_POLICY_RECHECK",
        }

    @staticmethod
    def operating_modes() -> list[dict[str, Any]]:
        return [
            {
                "name": mode.value,
                **_MODE_PRESENTATION[mode],
            }
            for mode in OperatingMode
        ]

    def operating_mode(self) -> dict[str, Any]:
        row = self._read_one(
            "SELECT mode, updated_at, principal, version "
            "FROM dashboard_control_plane WHERE singleton = 1"
        )
        if row is None:
            raise ControlRejected(
                "CONTROL_STATE_UNAVAILABLE",
                "durable operating-mode state is missing.",
            )
        try:
            selected = OperatingMode(str(row["mode"]))
        except ValueError as error:
            raise ControlRejected(
                "CONTROL_STATE_INTEGRITY_FAILURE",
                "durable operating mode is invalid.",
            ) from error
        return {
            "selected": selected.value,
            "write_capable": _MODE_PRESENTATION[selected]["write_capable"],
            "authority": _MODE_PRESENTATION[selected]["authority"],
            "updated_at": str(row["updated_at"]),
            "principal": str(row["principal"]),
            "version": int(row["version"]),
        }

    def select_mode(
        self,
        mode: str,
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> dict[str, Any]:
        try:
            selected = OperatingMode(mode)
        except ValueError as error:
            raise ControlRejected(
                "INVALID_OPERATING_MODE",
                "operating mode is not part of the v2 contract.",
            ) from error
        self._require_policy_principal("owner", principal)
        now_text = _utc_text(now)
        try:
            with (
                closing(sqlite3.connect(str(self.path), timeout=0.25)) as connection,
                connection,
            ):
                changed = connection.execute(
                    "UPDATE dashboard_control_plane "
                    "SET mode = ?, updated_at = ?, principal = ?, "
                    "version = version + 1 WHERE singleton = 1",
                    (selected.value, now_text, principal.identity),
                ).rowcount
                if changed != 1:
                    raise ControlRejected(
                        "CONTROL_STATE_UNAVAILABLE",
                        "durable operating mode could not be updated.",
                    )
        except ControlRejected:
            raise
        except sqlite3.Error as error:
            raise ControlRejected(
                "CONTROL_STATE_UNAVAILABLE",
                "durable operating mode could not be updated.",
            ) from error
        return self.operating_mode()

    def grant_approval(
        self,
        *,
        proposal_id: str,
        expires_at: datetime,
        reason: str,
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> dict[str, Any]:
        self._require_policy_principal("approver", principal)
        record = self.control_state.grant_approval(
            proposal_id,
            expires_at,
            reason,
            principal,
            now,
        )
        return self._approval_summary(record, now)

    def revoke_approval(
        self,
        approval_id: str,
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> dict[str, Any]:
        self._require_policy_principal("approver", principal)
        self.control_state.revoke_approval(approval_id, principal, now)
        return self._approval_summary(
            self.control_state.load_approval(approval_id),
            now,
        )

    def list_approvals(self, *, now: datetime) -> list[dict[str, Any]]:
        _utc_text(now)
        rows = self._read_all(
            "SELECT approval_id FROM approvals ORDER BY granted_at DESC, approval_id"
        )
        return [
            self._approval_summary(
                self.control_state.load_approval(str(row["approval_id"])),
                now,
            )
            for row in rows
        ]

    def issue_mandate(
        self,
        payload: Mapping[str, Any],
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> dict[str, Any]:
        record = self.mandate_authority.issue(payload, principal, now)
        return self._mandate_summary(record, now)

    def activate_mandate(
        self,
        mandate_id: str,
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> dict[str, Any]:
        record = self.mandate_authority.activate(mandate_id, principal, now)
        return self._mandate_summary(record, now)

    def revoke_mandate(
        self,
        mandate_id: str,
        reason: str,
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> dict[str, Any]:
        record = self.mandate_authority.revoke(
            mandate_id,
            reason,
            principal,
            now,
        )
        return self._mandate_summary(record, now)

    def list_mandates(self, *, now: datetime) -> list[dict[str, Any]]:
        _utc_text(now)
        return [
            self._mandate_summary(record, now)
            for record in self.mandate_authority.list_records()
        ]

    def engage_kill_switch(
        self,
        scope: str,
        reason: str,
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> dict[str, Any]:
        self.control_state.engage_kill_switch(scope, reason, principal, now)
        return self._kill_switch_summary(scope)

    def release_kill_switch(
        self,
        scope: str,
        reason: str,
        principal: ElevatedAuthenticatedPrincipal,
        now: datetime,
    ) -> dict[str, Any]:
        self.control_state.release_kill_switch(scope, reason, principal, now)
        return self._kill_switch_summary(scope)

    def list_kill_switches(self) -> list[dict[str, Any]]:
        rows = self._read_all(
            "SELECT scope, active, reason, principal, updated_at "
            "FROM kill_switches ORDER BY scope"
        )
        return [self._kill_switch_row_summary(row) for row in rows]

    def list_executions(self) -> list[dict[str, Any]]:
        rows = self._read_all(
            "SELECT execution_key FROM executions "
            "ORDER BY created_at DESC, execution_key"
        )
        return [
            self._execution_summary(
                self.control_state.load_execution(str(row["execution_key"]))
            )
            for row in rows
        ]

    def gate_state(self) -> dict[str, Any]:
        """Present policy gates without silently upgrading blocked authority."""

        record = self.policy.get("record")
        if not isinstance(record, Mapping):
            return {
                "policy": {
                    "status": "BLOCKED",
                    "reason_code": "POLICY_RECORD_MISSING",
                },
                "simulation": {
                    "status": "BLOCKED",
                    "reason_code": "POLICY_RECORD_MISSING",
                },
                "controlled_pilot": {
                    "status": "BLOCKED",
                    "reason_code": "POLICY_RECORD_MISSING",
                },
                "production_write": {
                    "authorized": False,
                    "reason_code": "POLICY_RECORD_MISSING",
                },
            }
        policy_ready = record.get("policy_decisions_status") == "APPROVED"
        simulation_ready = record.get("simulation_status") == "READY"
        production_authorized = record.get("production_write_authorized") is True
        pilot_source = str(record.get("controlled_pilot_status", "BLOCKED_BY_DEFAULT"))
        pilot_ready = pilot_source == "READY" and production_authorized
        return {
            "policy": {
                "status": "READY" if policy_ready else "BLOCKED",
                "policy_id": self.policy.get("policy_id"),
                "reason_code": None if policy_ready else "POLICY_NOT_APPROVED",
            },
            "simulation": {
                "status": "READY" if simulation_ready else "BLOCKED",
                "source_status": record.get("simulation_status"),
                "reason_code": None if simulation_ready else "SIMULATION_NOT_READY",
            },
            "controlled_pilot": {
                "status": "READY" if pilot_ready else "BLOCKED",
                "source_status": pilot_source,
                "reason_code": (
                    None if pilot_ready else "CONTROLLED_PILOT_NOT_AUTHORIZED"
                ),
            },
            "production_write": {
                "authorized": production_authorized,
                "reason_code": (
                    None if production_authorized else "PRODUCTION_WRITE_NOT_AUTHORIZED"
                ),
            },
        }

    def precondition_state(
        self,
        *,
        now: datetime,
        proposal_id: str | None = None,
        binding_hash: str | None = None,
        mandate_id: str | None = None,
        scope: TrustedScope | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        """Fail closed while leaving final authorization to the executor policy."""

        _utc_text(now)
        mode = OperatingMode(self.operating_mode()["selected"])
        reasons: list[str] = []
        gates = self.gate_state()
        if gates["policy"]["status"] != "READY":
            reasons.append(str(gates["policy"]["reason_code"]))
        if _MODE_PRESENTATION[mode]["write_capable"]:
            if environment is None:
                reasons.append("MISSING_ENVIRONMENT_CONTEXT")
            elif environment == "SIMULATION":
                if gates["simulation"]["status"] != "READY":
                    reasons.append(str(gates["simulation"]["reason_code"]))
            elif environment == "CONTROLLED_PILOT":
                if gates["controlled_pilot"]["status"] != "READY":
                    reasons.append(str(gates["controlled_pilot"]["reason_code"]))
                if not gates["production_write"]["authorized"]:
                    reasons.append(str(gates["production_write"]["reason_code"]))
            else:
                reasons.append("UNSUPPORTED_EXECUTION_ENVIRONMENT")
        elif environment not in {None, "SIMULATION", "CONTROLLED_PILOT"}:
            reasons.append("UNSUPPORTED_EXECUTION_ENVIRONMENT")

        if mode is OperatingMode.APPROVAL_REQUIRED:
            effective_scope = scope
            if not proposal_id or not binding_hash:
                reasons.append("MISSING_PROPOSAL_CONTEXT")
            else:
                try:
                    prepared = self.control_state.load_prepared_change(proposal_id)
                    self.control_state.load_active_approval(
                        proposal_id,
                        binding_hash,
                        now,
                    )
                    if scope is not None and scope != prepared.scope:
                        reasons.append("PROPOSAL_SCOPE_MISMATCH")
                    effective_scope = prepared.scope
                except ControlRejected as error:
                    reasons.append(error.reason_code)
            self._append_kill_switch_reason(reasons, effective_scope)
        elif mode is OperatingMode.BOUNDED_AUTONOMY:
            if not mandate_id or scope is None:
                reasons.append("MISSING_MANDATE_CONTEXT")
            else:
                self._append_mandate_reasons(reasons, mandate_id, scope, now)
            self._append_kill_switch_reason(reasons, scope)

        reasons = list(dict.fromkeys(reasons))
        if reasons:
            status = "BLOCKED"
        elif _MODE_PRESENTATION[mode]["write_capable"]:
            status = "READY_TO_REQUEST_EXECUTION"
        else:
            status = "READY_READ_ONLY"
        return {
            "mode": mode.value,
            "environment": environment,
            "status": status,
            "reason_codes": reasons,
            "required_authority": _MODE_PRESENTATION[mode]["authority"],
            "execution_authorized": False,
            "authorization_boundary": "BACKEND_EXECUTOR_POLICY_RECHECK",
        }

    def _approval_summary(
        self,
        record: ApprovalRecord,
        now: datetime,
    ) -> dict[str, Any]:
        prepared = self.control_state.load_prepared_change(record.proposal_id)
        if record.revoked_at is not None:
            status = "REVOKED"
        elif record.used:
            status = "USED"
        elif record.reserved_at is not None:
            status = "RESERVED"
        elif parse_utc(record.expires_at) <= now.astimezone(timezone.utc):
            status = "EXPIRED"
        else:
            status = "AVAILABLE"
        return {
            "approval_id": record.approval_id,
            "proposal_id": record.proposal_id,
            "binding_hash": record.binding_hash,
            "status": status,
            "approver": record.approver,
            "reason": _redact_text(record.reason),
            "granted_at": record.granted_at,
            "expires_at": record.expires_at,
            "revoked_at": record.revoked_at,
            "used_at": record.used_at,
            "execution_key": record.execution_key,
            "scope": {
                "organization": prepared.scope.organization,
                "connection": prepared.scope.connection,
                "account": prepared.scope.account,
                "campaign": prepared.scope.campaign,
            },
            "change": {
                "action": prepared.action.value,
                "current_value": prepared.current_value,
                "target_value": prepared.target_value,
                "diff": dict(prepared.expected_diff),
                "risk": prepared.risk,
            },
        }

    def _mandate_summary(
        self,
        record: MandateRecord,
        now: datetime,
    ) -> dict[str, Any]:
        canonical = record.canonical
        total_usage = self.mandate_authority.usage(record.mandate_id)
        daily_usage = self.mandate_authority.usage(record.mandate_id, now)
        return {
            "mandate_id": record.mandate_id,
            "canonical_hash": record.canonical_hash,
            "signature_verified": True,
            "status": record.status,
            "activation_version": record.activation_version,
            "revocation_version": record.revocation_version,
            "issued_at": canonical["issued_at"],
            "expires_at": canonical["expiry"],
            "activated_at": record.activated_at,
            "revoked_at": record.revoked_at,
            "revocation_reason": _redact_text(record.revocation_reason),
            "scope": {
                "organization": canonical["organization"],
                "connection": canonical["connection"],
                "account": canonical["account"],
                "environment": canonical["environment"],
                "targets": list(canonical["targets"]),
            },
            "actions": {
                "allowed": list(canonical["allowed_action_classes"]),
                "prohibited": list(canonical["prohibited_action_classes"]),
            },
            "quotas": {
                "actions_per_24h": {
                    "used": daily_usage.action_count,
                    "limit": canonical["action_quotas"]["actions_per_24h"],
                },
                "total_monetary_rub": {
                    "used": total_usage.total_monetary_exposure_rub,
                    "limit": canonical["total_monetary_limit"],
                },
                "daily_monetary_rub": {
                    "used": daily_usage.total_monetary_exposure_rub,
                    "limit": canonical["daily_monetary_limit"],
                },
                "daily_change_percent": {
                    "used": daily_usage.daily_cumulative_change_percent,
                    "limit": canonical["maximum_daily_change"],
                },
            },
            "cooldown": dict(canonical["cooldown"]),
            "latest_observation_until": total_usage.latest_observation_until,
        }

    def _kill_switch_summary(self, scope: str) -> dict[str, Any]:
        row = self._read_one(
            "SELECT scope, active, reason, principal, updated_at "
            "FROM kill_switches WHERE scope = ?",
            (scope,),
        )
        if row is None:
            raise ControlRejected(
                "KILL_SWITCH_UNAVAILABLE",
                "durable kill-switch state is missing after update.",
            )
        return self._kill_switch_row_summary(row)

    @staticmethod
    def _kill_switch_row_summary(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "scope": str(row["scope"]),
            "active": bool(row["active"]),
            "reason": _redact_text(str(row["reason"])),
            "principal": str(row["principal"]),
            "updated_at": str(row["updated_at"]),
        }

    @staticmethod
    def _execution_summary(record: ExecutionRecord) -> dict[str, Any]:
        return {
            "execution_key": record.execution_key,
            "proposal_id": record.proposal_id,
            "status": record.status.value,
            "target_key": record.target_key,
            "current_value": record.current_value,
            "target_value": record.target_value,
            "detail": _redact_text(record.detail),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "terminal": record.status in _TERMINAL_EXECUTION_STATUSES,
            "requires_reconciliation": (
                record.status is ExecutionStatus.UNKNOWN_RESULT
            ),
        }

    def _append_mandate_reasons(
        self,
        reasons: list[str],
        mandate_id: str,
        scope: TrustedScope,
        now: datetime,
    ) -> None:
        try:
            record = self.mandate_authority.load(mandate_id)
            if self.mandate_authority.interrupts.any_active(
                "mandate",
                (mandate_id,),
            ):
                reasons.append("MANDATE_REVOKED")
            if record.status == "REVOKED":
                reasons.append("MANDATE_REVOKED")
            elif record.status != "ACTIVE":
                reasons.append("MANDATE_INACTIVE")
            if parse_utc(record.canonical["expiry"]) <= now.astimezone(timezone.utc):
                reasons.append("MANDATE_EXPIRED")
            if (
                record.canonical["organization"] != scope.organization
                or record.canonical["connection"] != scope.connection
                or record.canonical["account"] != scope.account
                or scope.campaign not in record.canonical["targets"]
            ):
                reasons.append("MANDATE_SCOPE_MISMATCH")
            usage = self.mandate_authority.usage(mandate_id, now)
            if (
                usage.action_count
                >= record.canonical["action_quotas"]["actions_per_24h"]
            ):
                reasons.append("ACTION_QUOTA_REACHED")
        except ControlRejected as error:
            reasons.append(error.reason_code)
        except (OSError, sqlite3.Error, TypeError, ValueError):
            reasons.append("MANDATE_STATE_UNAVAILABLE")

    def _append_kill_switch_reason(
        self,
        reasons: list[str],
        scope: TrustedScope | None,
    ) -> None:
        try:
            if scope is None:
                if any(item["active"] for item in self.list_kill_switches()):
                    reasons.append("KILL_SWITCH_ACTIVE")
            elif self.control_state.any_kill_switch_active(scope):
                reasons.append("KILL_SWITCH_ACTIVE")
        except ControlRejected as error:
            reasons.append(
                "KILL_SWITCH_ACTIVE"
                if error.reason_code == "KILL_SWITCH_ACTIVE"
                else "KILL_SWITCH_UNAVAILABLE"
            )
        except (OSError, sqlite3.Error, TypeError, ValueError):
            reasons.append("KILL_SWITCH_UNAVAILABLE")

    def _require_policy_principal(
        self,
        role: str,
        principal: AuthenticatedPrincipal,
    ) -> None:
        principals = self.policy.get("principals")
        expected = principals.get(role) if isinstance(principals, Mapping) else None
        if (
            not isinstance(expected, Mapping)
            or principal.identity != expected.get("identity")
            or principal.authentication != expected.get("authentication")
        ):
            raise ControlRejected(
                "UNAUTHENTICATED_PRINCIPAL",
                "principal is not authorized to change the operating mode.",
            )

    def _initialize(self) -> None:
        try:
            with (
                closing(sqlite3.connect(str(self.path), timeout=0.25)) as connection,
                connection,
            ):
                connection.execute("PRAGMA busy_timeout = 250")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS dashboard_control_plane (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        mode TEXT NOT NULL CHECK (
                            mode IN (
                                'OBSERVE',
                                'RECOMMEND',
                                'APPROVAL_REQUIRED',
                                'BOUNDED_AUTONOMY'
                            )
                        ),
                        updated_at TEXT NOT NULL,
                        principal TEXT NOT NULL,
                        version INTEGER NOT NULL CHECK (version >= 0)
                    );
                    INSERT OR IGNORE INTO dashboard_control_plane
                        (singleton, mode, updated_at, principal, version)
                    VALUES
                        (1, 'OBSERVE', '1970-01-01T00:00:00+00:00', 'system', 0);
                    """
                )
        except sqlite3.Error as error:
            raise ControlRejected(
                "CONTROL_STATE_UNAVAILABLE",
                "durable operating-mode state is unavailable.",
            ) from error

    def _read_all(
        self,
        query: str,
        parameters: Sequence[object] = (),
    ) -> list[sqlite3.Row]:
        try:
            connection = sqlite3.connect(str(self.path), timeout=0.25)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA query_only = ON")
                return list(connection.execute(query, parameters).fetchall())
            finally:
                connection.close()
        except sqlite3.Error as error:
            raise ControlRejected(
                "CONTROL_STATE_UNAVAILABLE",
                "durable control-plane state cannot be read.",
            ) from error

    def _read_one(
        self,
        query: str,
        parameters: Sequence[object] = (),
    ) -> sqlite3.Row | None:
        rows = self._read_all(query, parameters)
        return rows[0] if rows else None
