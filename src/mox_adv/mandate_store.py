"""Durable Mandate lifecycle, quota, and execution reservation store."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional

from mox_adv.autonomy_contracts import (
    MandateRecord,
    MandateUsage,
    canonical_hash,
    canonical_json,
    deterministic_monetary_exposure_rub,
    parse_utc,
    utc_text,
)
from mox_adv.commands import ACTION_SPECS
from mox_adv.control_state import (
    AuthenticatedPrincipal,
    ControlRejected,
    DurableControlState,
    ExecutionRecord,
    ExecutionStatus,
    PreparedChange,
    TrustedScope,
)
from mox_adv.interrupt_state import (
    DurableInterruptState,
    InterruptStateUnavailable,
    kill_switch_scopes,
)
from mox_adv.mandate_signing import MandateSigner

_canonical = canonical_json
_utc_text = utc_text
_parse_utc = parse_utc


class DurableMandateAuthority:
    """Persist immutable Mandates, authority events, quotas, and reservations."""

    def __init__(
        self,
        path: Path,
        policy: Mapping[str, Any],
        signer: MandateSigner,
    ) -> None:
        self.path = path
        self.policy = policy
        self.signer = signer
        DurableControlState(path)
        try:
            self.interrupts = DurableInterruptState(path)
        except InterruptStateUnavailable as error:
            raise ControlRejected(
                "KILL_SWITCH_UNAVAILABLE",
                "durable interrupt state is unavailable.",
            ) from error
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = self._new_connection()
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def _new_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=0.25)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 250")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS mandates (
                    mandate_id TEXT PRIMARY KEY,
                    canonical_json TEXT NOT NULL,
                    canonical_hash TEXT NOT NULL UNIQUE,
                    signature TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('ISSUED', 'ACTIVE', 'REVOKED')
                    ),
                    activation_version INTEGER NOT NULL DEFAULT 0,
                    revocation_version INTEGER NOT NULL DEFAULT 0,
                    activated_at TEXT,
                    revoked_at TEXT,
                    revocation_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS mandate_authority_events (
                    mandate_id TEXT NOT NULL,
                    event_version INTEGER NOT NULL,
                    event_type TEXT NOT NULL CHECK (
                        event_type IN ('ISSUED', 'ACTIVATED', 'REVOKED')
                    ),
                    principal TEXT NOT NULL,
                    authentication TEXT NOT NULL,
                    reason TEXT,
                    occurred_at TEXT NOT NULL,
                    PRIMARY KEY(mandate_id, event_version),
                    FOREIGN KEY(mandate_id) REFERENCES mandates(mandate_id)
                );
                CREATE TABLE IF NOT EXISTS mandate_consumptions (
                    execution_key TEXT PRIMARY KEY,
                    mandate_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL,
                    monetary_exposure_rub INTEGER NOT NULL,
                    step_change_percent INTEGER NOT NULL,
                    reserved_at TEXT NOT NULL,
                    observation_until TEXT NOT NULL,
                    FOREIGN KEY(mandate_id) REFERENCES mandates(mandate_id),
                    FOREIGN KEY(execution_key) REFERENCES executions(execution_key)
                );
                CREATE TABLE IF NOT EXISTS mandate_rechecks (
                    execution_key TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    mandate_id TEXT NOT NULL,
                    previous_status TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    PRIMARY KEY(execution_key, attempt),
                    FOREIGN KEY(mandate_id) REFERENCES mandates(mandate_id),
                    FOREIGN KEY(execution_key) REFERENCES executions(execution_key)
                );
                CREATE TRIGGER IF NOT EXISTS mandates_immutable_fields
                BEFORE UPDATE OF
                    mandate_id,
                    canonical_json,
                    canonical_hash,
                    signature
                ON mandates
                BEGIN
                    SELECT RAISE(ABORT, 'immutable mandate fields');
                END;
                CREATE TRIGGER IF NOT EXISTS mandates_state_transitions
                BEFORE UPDATE OF
                    status,
                    activation_version,
                    revocation_version,
                    activated_at,
                    revoked_at,
                    revocation_reason
                ON mandates
                WHEN NOT (
                    (
                        OLD.status = 'ISSUED'
                        AND NEW.status = 'ACTIVE'
                        AND NEW.activation_version = OLD.activation_version + 1
                        AND NEW.revocation_version = OLD.revocation_version
                        AND NEW.activated_at IS NOT NULL
                        AND NEW.revoked_at IS NULL
                        AND NEW.revocation_reason IS NULL
                    )
                    OR
                    (
                        OLD.status IN ('ISSUED', 'ACTIVE')
                        AND NEW.status = 'REVOKED'
                        AND NEW.activation_version = OLD.activation_version
                        AND NEW.revocation_version = OLD.revocation_version + 1
                        AND NEW.activated_at IS OLD.activated_at
                        AND NEW.revoked_at IS NOT NULL
                        AND length(trim(NEW.revocation_reason)) > 0
                    )
                )
                BEGIN
                    SELECT RAISE(ABORT, 'illegal mandate state transition');
                END;
                CREATE TRIGGER IF NOT EXISTS mandate_events_no_update
                BEFORE UPDATE ON mandate_authority_events
                BEGIN
                    SELECT RAISE(ABORT, 'immutable mandate event');
                END;
                CREATE TRIGGER IF NOT EXISTS mandate_events_no_delete
                BEFORE DELETE ON mandate_authority_events
                BEGIN
                    SELECT RAISE(ABORT, 'immutable mandate event');
                END;
                CREATE TRIGGER IF NOT EXISTS mandate_consumptions_no_update
                BEFORE UPDATE ON mandate_consumptions
                BEGIN
                    SELECT RAISE(ABORT, 'immutable mandate consumption');
                END;
                CREATE TRIGGER IF NOT EXISTS mandate_consumptions_no_delete
                BEFORE DELETE ON mandate_consumptions
                BEGIN
                    SELECT RAISE(ABORT, 'immutable mandate consumption');
                END;
                CREATE TRIGGER IF NOT EXISTS mandate_rechecks_no_update
                BEFORE UPDATE ON mandate_rechecks
                BEGIN
                    SELECT RAISE(ABORT, 'immutable mandate recheck');
                END;
                CREATE TRIGGER IF NOT EXISTS mandate_rechecks_no_delete
                BEFORE DELETE ON mandate_rechecks
                BEGIN
                    SELECT RAISE(ABORT, 'immutable mandate recheck');
                END;
                """
            )

    def issue(
        self,
        payload: Mapping[str, Any],
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> MandateRecord:
        canonical = self._validate_payload(payload, principal, now)
        canonical_json = _canonical(canonical)
        digest = canonical_hash(canonical)
        mandate_id = "mandate-" + digest.removeprefix("sha256:")
        signature = self.signer.sign(canonical_json.encode("utf-8"))
        now_text = _utc_text(now)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM mandates WHERE mandate_id = ?",
                (mandate_id,),
            ).fetchone()
            if existing is not None:
                record = self._record_from_row(existing)
                if (
                    record.canonical_hash != digest
                    or record.signature != signature
                    or dict(record.canonical) != canonical
                ):
                    raise ControlRejected(
                        "IMMUTABLE_MANDATE_CONFLICT",
                        "an existing Mandate cannot be widened or replaced.",
                    )
                return record
            connection.execute(
                "INSERT INTO mandates "
                "(mandate_id, canonical_json, canonical_hash, signature, status) "
                "VALUES (?, ?, ?, ?, 'ISSUED')",
                (mandate_id, canonical_json, digest, signature),
            )
            connection.execute(
                "INSERT INTO mandate_authority_events "
                "(mandate_id, event_version, event_type, principal, "
                "authentication, occurred_at) VALUES (?, 1, 'ISSUED', ?, ?, ?)",
                (
                    mandate_id,
                    principal.identity,
                    principal.authentication,
                    now_text,
                ),
            )
        return self.load(mandate_id)

    def activate(
        self,
        mandate_id: str,
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> MandateRecord:
        self._validate_issuer(principal)
        connection = self._new_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM mandates WHERE mandate_id = ?",
                (mandate_id,),
            ).fetchone()
            if row is None:
                raise ControlRejected(
                    "MANDATE_NOT_FOUND",
                    "Mandate does not exist.",
                )
            record = self._record_from_row(row)
            if record.status == "REVOKED":
                raise ControlRejected(
                    "MANDATE_REACTIVATION_FORBIDDEN",
                    "a revoked Mandate can never be reactivated.",
                )
            if record.status == "ACTIVE":
                connection.rollback()
                return record
            if _parse_utc(record.canonical["expiry"]) <= now.astimezone(timezone.utc):
                raise ControlRejected("MANDATE_EXPIRED", "Mandate has expired.")
            activation_version = record.activation_version + 1
            changed = connection.execute(
                "UPDATE mandates SET status = 'ACTIVE', activation_version = ?, "
                "activated_at = ? WHERE mandate_id = ? AND status = 'ISSUED'",
                (activation_version, _utc_text(now), mandate_id),
            ).rowcount
            if changed != 1:
                raise ControlRejected(
                    "MANDATE_ACTIVATION_CONFLICT",
                    "Mandate activation changed concurrently.",
                )
            self._append_event(
                connection,
                mandate_id,
                "ACTIVATED",
                principal,
                now,
            )
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        return self.load(mandate_id)

    def revoke(
        self,
        mandate_id: str,
        reason: str,
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> MandateRecord:
        self._validate_issuer(principal)
        if not reason.strip():
            raise ControlRejected("INVALID_INPUT", "revocation reason is required.")
        try:
            self.interrupts.engage("mandate", mandate_id, reason.strip(), now)
        except InterruptStateUnavailable as error:
            raise ControlRejected(
                "KILL_SWITCH_UNAVAILABLE",
                "durable revocation interrupt is unavailable.",
            ) from error
        connection = self._new_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM mandates WHERE mandate_id = ?",
                (mandate_id,),
            ).fetchone()
            if row is None:
                raise ControlRejected(
                    "MANDATE_NOT_FOUND",
                    "Mandate does not exist.",
                )
            record = self._record_from_row(row)
            if record.status == "REVOKED":
                connection.rollback()
                return record
            revocation_version = record.revocation_version + 1
            changed = connection.execute(
                "UPDATE mandates SET status = 'REVOKED', revocation_version = ?, "
                "revoked_at = ?, revocation_reason = ? "
                "WHERE mandate_id = ? AND status IN ('ISSUED', 'ACTIVE')",
                (
                    revocation_version,
                    _utc_text(now),
                    reason.strip(),
                    mandate_id,
                ),
            ).rowcount
            if changed != 1:
                raise ControlRejected(
                    "MANDATE_REVOCATION_CONFLICT",
                    "Mandate revocation changed concurrently.",
                )
            self._append_event(
                connection,
                mandate_id,
                "REVOKED",
                principal,
                now,
                reason.strip(),
            )
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        return self.load(mandate_id)

    def load(self, mandate_id: str) -> MandateRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM mandates WHERE mandate_id = ?",
                (mandate_id,),
            ).fetchone()
        if row is None:
            raise ControlRejected("MANDATE_NOT_FOUND", "Mandate does not exist.")
        return self._record_from_row(row)

    def load_active(self, mandate_id: str, now: datetime) -> MandateRecord:
        with self._connect() as connection:
            return self._load_active_in_connection(connection, mandate_id, now)

    def list_records(self) -> tuple[MandateRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM mandates ORDER BY rowid",
            ).fetchall()
        return tuple(self._record_from_row(row) for row in rows)

    def usage(
        self,
        mandate_id: str,
        now: Optional[datetime] = None,
    ) -> MandateUsage:
        query = (
            "SELECT COUNT(*) AS action_count, "
            "COALESCE(SUM(monetary_exposure_rub), 0) AS monetary, "
            "COALESCE(SUM(step_change_percent), 0) AS step, "
            "MAX(observation_until) AS observation_until "
            "FROM mandate_consumptions WHERE mandate_id = ?"
        )
        parameters: list[object] = [mandate_id]
        if now is not None:
            query += " AND substr(reserved_at, 1, 10) = ?"
            parameters.append(_utc_text(now)[:10])
        with self._connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        assert row is not None
        return MandateUsage(
            action_count=int(row["action_count"]),
            total_monetary_exposure_rub=int(row["monetary"]),
            daily_cumulative_change_percent=int(row["step"]),
            latest_observation_until=row["observation_until"],
        )

    def reserve_execution(
        self,
        prepared: PreparedChange,
        mandate_id: str,
        now: datetime,
    ) -> tuple[ExecutionStatus, ExecutionRecord]:
        monetary_exposure_rub = deterministic_monetary_exposure_rub(prepared)
        now_text = _utc_text(now)
        connection = self._new_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            mandate = self._load_active_in_connection(connection, mandate_id, now)
            self._validate_prepared_binding(mandate, prepared)
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
                    in {ExecutionStatus.APPLIED, ExecutionStatus.NO_CHANGE}
                    else record.status
                )
                return outcome, record
            unresolved = connection.execute(
                "SELECT execution_key FROM executions "
                "WHERE status = 'UNKNOWN_RESULT' LIMIT 1",
            ).fetchone()
            if unresolved is not None:
                raise ControlRejected(
                    "UNKNOWN_RESULT",
                    "an unresolved execution blocks the next write.",
                )
            other = connection.execute(
                "SELECT * FROM executions "
                "WHERE status IN ('RESERVED', 'IN_FLIGHT') LIMIT 1",
            ).fetchone()
            if other is not None:
                record = self._execution_from_row(other)
                connection.rollback()
                return ExecutionStatus.BLOCKED, record
            if self._kill_switch_active(connection, prepared.scope):
                raise ControlRejected(
                    "KILL_SWITCH_ACTIVE",
                    "durable kill switch blocks the unsent command.",
                )
            self._check_quota(
                connection,
                mandate,
                prepared,
                monetary_exposure_rub,
                now,
            )
            observation_hours = int(
                mandate.canonical["cooldown"]["observation_window_hours"]
            )
            observation_until = now + timedelta(hours=observation_hours)
            step = self._step_percent(prepared)
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
            connection.execute(
                "INSERT INTO mandate_consumptions "
                "(execution_key, mandate_id, action, target, "
                "monetary_exposure_rub, step_change_percent, reserved_at, "
                "observation_until) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    prepared.execution_key(),
                    mandate_id,
                    prepared.action.value,
                    prepared.scope.campaign,
                    monetary_exposure_rub,
                    step,
                    now_text,
                    _utc_text(observation_until),
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

    def send_once(
        self,
        prepared: PreparedChange,
        mandate_id: str,
        now: datetime,
        sender: Callable[[], None],
        before_dispatch: Optional[Callable[[], None]] = None,
        at_dispatch_boundary: Optional[Callable[[], datetime]] = None,
        immediate_pre_transport: Optional[Callable[[], datetime]] = None,
    ) -> tuple[ExecutionStatus, ExecutionRecord]:
        connection = self._new_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            mandate = self._load_active_in_connection(connection, mandate_id, now)
            self._validate_prepared_binding(mandate, prepared)
            row = connection.execute(
                "SELECT * FROM executions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            if row is None:
                raise ControlRejected(
                    "EXECUTION_NOT_FOUND",
                    "execution reservation does not exist.",
                )
            record = self._execution_from_row(row)
            if record.status != ExecutionStatus.RESERVED:
                connection.rollback()
                outcome = (
                    ExecutionStatus.ALREADY_PROCESSED
                    if record.status
                    in {ExecutionStatus.APPLIED, ExecutionStatus.NO_CHANGE}
                    else record.status
                )
                return outcome, record
            consumption = connection.execute(
                "SELECT mandate_id FROM mandate_consumptions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            if consumption is None or consumption["mandate_id"] != mandate_id:
                raise ControlRejected(
                    "MANDATE_RESERVATION_MISMATCH",
                    "execution quota reservation is not bound to this Mandate.",
                )
            if self._kill_switch_active(connection, prepared.scope):
                raise ControlRejected(
                    "KILL_SWITCH_ACTIVE",
                    "durable kill switch blocks the unsent command.",
                )
            connection.execute(
                "UPDATE executions SET status = 'IN_FLIGHT', updated_at = ? "
                "WHERE execution_key = ? AND status = 'RESERVED'",
                (_utc_text(now), prepared.execution_key()),
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
        except sqlite3.Error:
            if connection.in_transaction:
                connection.rollback()
            raise
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        if before_dispatch is not None:
            before_dispatch()
        dispatch_at = now
        self.require_dispatch_allowed(mandate_id, prepared.scope, dispatch_at)
        if at_dispatch_boundary is not None:
            dispatch_at = at_dispatch_boundary()
        self.require_dispatch_allowed(
            mandate_id,
            prepared.scope,
            dispatch_at,
        )
        immediate_at = (
            dispatch_at
            if immediate_pre_transport is None
            else immediate_pre_transport()
        )
        self.require_dispatch_allowed(
            mandate_id,
            prepared.scope,
            immediate_at,
        )
        sender()
        return ExecutionStatus.IN_FLIGHT, record

    def record_recheck_unknown(
        self,
        prepared: PreparedChange,
        mandate_id: str,
        now: datetime,
    ) -> ExecutionRecord:
        """Persist indeterminate terminal readback so every later write fails closed."""

        connection = self._new_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM executions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            if row is None:
                raise ControlRejected(
                    "EXECUTION_NOT_FOUND",
                    "execution does not exist.",
                )
            execution = self._execution_from_row(row)
            if execution.status not in {
                ExecutionStatus.BLOCKED,
                ExecutionStatus.FAILED,
            }:
                raise ControlRejected(
                    "EXECUTION_NOT_RECHECKABLE",
                    "execution is not a terminal recheck candidate.",
                )
            consumption = connection.execute(
                "SELECT mandate_id FROM mandate_consumptions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            if consumption is None or consumption["mandate_id"] != mandate_id:
                raise ControlRejected(
                    "MANDATE_RESERVATION_MISMATCH",
                    "recheck must use the original Mandate reservation.",
                )
            attempt = connection.execute(
                "SELECT COALESCE(MAX(attempt), 0) + 1 AS next_attempt "
                "FROM mandate_rechecks WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            connection.execute(
                "INSERT INTO mandate_rechecks "
                "(execution_key, attempt, mandate_id, previous_status, requested_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    prepared.execution_key(),
                    int(attempt["next_attempt"]),
                    mandate_id,
                    execution.status.value,
                    _utc_text(now),
                ),
            )
            connection.execute(
                "UPDATE executions SET status = 'UNKNOWN_RESULT', "
                "detail = 'RECHECK_READBACK_INDETERMINATE', updated_at = ? "
                "WHERE execution_key = ? AND status IN ('BLOCKED', 'FAILED')",
                (_utc_text(now), prepared.execution_key()),
            )
            row = connection.execute(
                "SELECT * FROM executions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            connection.commit()
            return self._execution_from_row(row)
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def validate_blocked_recheck(
        self,
        prepared: PreparedChange,
        mandate_id: str,
        now: datetime,
    ) -> None:
        """Re-evaluate authority and observation gates without reopening or sending."""

        with self._connect() as connection:
            mandate = self._load_active_in_connection(connection, mandate_id, now)
            self._validate_prepared_binding(mandate, prepared)
            consumption = connection.execute(
                "SELECT mandate_id, observation_until "
                "FROM mandate_consumptions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
        if consumption is None or consumption["mandate_id"] != mandate_id:
            raise ControlRejected(
                "MANDATE_RESERVATION_MISMATCH",
                "blocked recheck must use the original quota reservation.",
            )
        if _parse_utc(consumption["observation_until"]) > now.astimezone(timezone.utc):
            raise ControlRejected(
                "OBSERVATION_WINDOW_ACTIVE",
                "blocked execution cannot retry before observation closes.",
            )

    def record_recheck_applied(
        self,
        prepared: PreparedChange,
        mandate_id: str,
        now: datetime,
    ) -> ExecutionRecord:
        """Record target-state reconciliation without sending or consuming quota."""

        connection = self._new_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM executions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            if row is None:
                raise ControlRejected(
                    "EXECUTION_NOT_FOUND",
                    "execution does not exist.",
                )
            execution = self._execution_from_row(row)
            if execution.status not in {
                ExecutionStatus.BLOCKED,
                ExecutionStatus.FAILED,
            }:
                raise ControlRejected(
                    "EXECUTION_NOT_RECHECKABLE",
                    "only BLOCKED or FAILED execution can be rechecked.",
                )
            consumption = connection.execute(
                "SELECT mandate_id FROM mandate_consumptions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            if consumption is None or consumption["mandate_id"] != mandate_id:
                raise ControlRejected(
                    "MANDATE_RESERVATION_MISMATCH",
                    "recheck must use the original Mandate reservation.",
                )
            attempt = connection.execute(
                "SELECT COALESCE(MAX(attempt), 0) + 1 AS next_attempt "
                "FROM mandate_rechecks WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            connection.execute(
                "INSERT INTO mandate_rechecks "
                "(execution_key, attempt, mandate_id, previous_status, requested_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    prepared.execution_key(),
                    int(attempt["next_attempt"]),
                    mandate_id,
                    execution.status.value,
                    _utc_text(now),
                ),
            )
            connection.execute(
                "UPDATE executions SET status = 'APPLIED', "
                "detail = 'RECHECK_TARGET_STATE_CONFIRMED', updated_at = ? "
                "WHERE execution_key = ? AND status IN ('BLOCKED', 'FAILED')",
                (_utc_text(now), prepared.execution_key()),
            )
            row = connection.execute(
                "SELECT * FROM executions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            connection.commit()
            return self._execution_from_row(row)
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def _validate_payload(
        self,
        payload: Mapping[str, Any],
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> dict[str, Any]:
        self._validate_issuer(principal)
        if not isinstance(payload, Mapping):
            raise ControlRejected("INVALID_INPUT", "Mandate must be an object.")
        required = tuple(self.policy["mandate"]["canonical_fields"])
        if set(payload) != set(required):
            raise ControlRejected(
                "INVALID_INPUT",
                "Mandate fields must exactly match the Gate 0 canonical fields.",
            )
        try:
            canonical = json.loads(_canonical(payload))
        except (TypeError, ValueError) as error:
            raise ControlRejected(
                "INVALID_INPUT",
                "Mandate values must be canonical JSON.",
            ) from error
        issuer = canonical["issuer"]
        if not isinstance(issuer, Mapping) or dict(issuer) != asdict(principal):
            raise ControlRejected(
                "MANDATE_ISSUER_MISMATCH",
                "Mandate issuer does not match the authenticated principal.",
            )
        issued_at = _parse_utc(canonical["issued_at"])
        expiry = _parse_utc(canonical["expiry"])
        current = now.astimezone(timezone.utc)
        if issued_at > current or expiry <= current:
            raise ControlRejected(
                "MANDATE_EXPIRED",
                "Mandate issuance or expiry is not current.",
            )
        if expiry - issued_at > timedelta(
            hours=int(self.policy["limits"]["mandate_ttl_hours"])
        ):
            raise ControlRejected(
                "MANDATE_TTL_EXCEEDED",
                "Mandate TTL exceeds the Gate 0 maximum.",
            )
        binding = self.policy["bindings"]["simulation"]
        if (
            canonical["organization"] != binding["organization"]
            or canonical["connection"] != binding["connection"]
            or canonical["account"] != binding["direct_account"]
            or canonical["environment"] != "SIMULATION"
            or canonical["credential_profile"] != "DIRECT_PILOT_WRITE"
            or canonical["policy_version"] != self.policy["policy_id"]
        ):
            raise ControlRejected(
                "MANDATE_SCOPE_MISMATCH",
                "Mandate scope is not the trusted simulation binding.",
            )
        targets = canonical["targets"]
        if (
            not isinstance(targets, list)
            or not targets
            or any(not isinstance(item, str) or not item for item in targets)
            or len(set(targets)) != len(targets)
        ):
            raise ControlRejected(
                "UNKNOWN_TARGET",
                "Mandate targets must be unique non-empty identifiers.",
            )
        allowed = canonical["allowed_action_classes"]
        policy_allowed = set(self.policy["mandate"]["allowed_action_classes"])
        if (
            not isinstance(allowed, list)
            or not allowed
            or not set(allowed).issubset(policy_allowed)
            or len(set(allowed)) != len(allowed)
        ):
            raise ControlRejected(
                "MANDATE_ACTION_WIDENED",
                "Mandate actions exceed the Gate 0 bounded-autonomy set.",
            )
        prohibited = canonical["prohibited_action_classes"]
        required_prohibited = set(self.policy["mandate"]["prohibited_action_classes"])
        if (
            not isinstance(prohibited, list)
            or not required_prohibited.issubset(set(prohibited))
            or set(allowed) & set(prohibited)
        ):
            raise ControlRejected(
                "MANDATE_ACTION_WIDENED",
                "Mandate prohibited actions do not preserve Gate 0 restrictions.",
            )
        self._validate_limits(canonical)
        if set(canonical["stop_conditions"]) != set(
            self.policy["mandate"]["stop_conditions"]
        ):
            raise ControlRejected(
                "MANDATE_STOP_CONDITION_MISMATCH",
                "Mandate stop conditions must exactly preserve Gate 0.",
            )
        if canonical["kpi"] != self.policy["mandate"]["kpi"]:
            raise ControlRejected(
                "MANDATE_KPI_MISMATCH",
                "Mandate KPI must match Gate 0.",
            )
        minimum = canonical["minimum_sample"]
        policy_minimum = self.policy["mandate"]["minimum_sample"]
        if (
            not isinstance(minimum, Mapping)
            or set(minimum) != {"clicks", "conversions"}
            or int(minimum["clicks"]) < int(policy_minimum["clicks"])
            or int(minimum["conversions"]) < int(policy_minimum["conversions"])
        ):
            raise ControlRejected(
                "MANDATE_SAMPLE_WIDENED",
                "Mandate minimum sample is below Gate 0.",
            )
        return canonical

    def _validate_limits(self, canonical: Mapping[str, Any]) -> None:
        limits = self.policy["limits"]
        numeric_limits = (
            (
                "total_monetary_limit",
                int(limits["mandate_total_exposure_rub"]),
            ),
            (
                "daily_monetary_limit",
                int(limits["mandate_daily_exposure_rub"]),
            ),
            ("maximum_step_change", int(limits["maximum_step_percent"])),
            (
                "maximum_daily_change",
                int(limits["maximum_daily_cumulative_change_percent"]),
            ),
            (
                "platform_side_spend_cap",
                int(limits["platform_weekly_spend_rub"]),
            ),
        )
        for field, maximum in numeric_limits:
            value = canonical[field]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ControlRejected(
                    "INVALID_INPUT",
                    field + " must be an integer.",
                )
            if value <= 0 or value > maximum:
                raise ControlRejected(
                    "MANDATE_LIMIT_WIDENED",
                    field + " exceeds Gate 0.",
                )
        cooldown = canonical["cooldown"]
        if (
            not isinstance(cooldown, Mapping)
            or set(cooldown) != {"hours", "observation_window_hours"}
            or any(
                isinstance(cooldown[field], bool)
                or not isinstance(cooldown[field], int)
                for field in ("hours", "observation_window_hours")
            )
            or cooldown["hours"] < int(self.policy["timing"]["cooldown_hours"])
            or cooldown["observation_window_hours"]
            < int(self.policy["timing"]["observation_window_hours"])
        ):
            raise ControlRejected(
                "MANDATE_COOLDOWN_WIDENED",
                "Mandate cooldown or observation window is below Gate 0.",
            )
        quotas = canonical["action_quotas"]
        if (
            not isinstance(quotas, Mapping)
            or set(quotas) != {"actions_per_24h"}
            or isinstance(quotas["actions_per_24h"], bool)
            or not isinstance(quotas["actions_per_24h"], int)
            or quotas["actions_per_24h"] <= 0
            or quotas["actions_per_24h"]
            > int(self.policy["limits"]["mandate_actions_per_24h"])
        ):
            raise ControlRejected(
                "MANDATE_QUOTA_WIDENED",
                "Mandate action quota exceeds Gate 0.",
            )

    def _validate_issuer(self, principal: AuthenticatedPrincipal) -> None:
        expected = self.policy["principals"]["mandate_issuer"]
        if (
            principal.identity != expected["identity"]
            or principal.authentication != expected["authentication"]
        ):
            raise ControlRejected(
                "UNAUTHENTICATED_PRINCIPAL",
                "only the Gate 0 mandate issuer may manage Mandates.",
            )

    def _record_from_row(self, row: sqlite3.Row) -> MandateRecord:
        try:
            canonical = json.loads(row["canonical_json"])
        except (TypeError, json.JSONDecodeError) as error:
            raise ControlRejected(
                "MANDATE_INTEGRITY_FAILURE",
                "Mandate canonical JSON is invalid.",
            ) from error
        if not isinstance(canonical, Mapping):
            raise ControlRejected(
                "MANDATE_INTEGRITY_FAILURE",
                "Mandate canonical value is invalid.",
            )
        canonical_json = _canonical(canonical)
        digest = canonical_hash(canonical)
        mandate_id = "mandate-" + digest.removeprefix("sha256:")
        if (
            digest != row["canonical_hash"]
            or mandate_id != row["mandate_id"]
            or not self.signer.verify(
                canonical_json.encode("utf-8"),
                row["signature"],
            )
        ):
            raise ControlRejected(
                "MANDATE_INTEGRITY_FAILURE",
                "Mandate hash or issuer signature is invalid.",
            )
        return MandateRecord(
            mandate_id=row["mandate_id"],
            canonical=dict(canonical),
            canonical_hash=row["canonical_hash"],
            signature=row["signature"],
            status=row["status"],
            activation_version=int(row["activation_version"]),
            revocation_version=int(row["revocation_version"]),
            activated_at=row["activated_at"],
            revoked_at=row["revoked_at"],
            revocation_reason=row["revocation_reason"],
        )

    def _load_active_in_connection(
        self,
        connection: sqlite3.Connection,
        mandate_id: str,
        now: datetime,
    ) -> MandateRecord:
        row = connection.execute(
            "SELECT * FROM mandates WHERE mandate_id = ?",
            (mandate_id,),
        ).fetchone()
        if row is None:
            raise ControlRejected("MANDATE_NOT_FOUND", "Mandate does not exist.")
        record = self._record_from_row(row)
        if record.status == "REVOKED":
            raise ControlRejected("MANDATE_REVOKED", "Mandate is revoked.")
        if record.status != "ACTIVE":
            raise ControlRejected("MANDATE_INACTIVE", "Mandate is not active.")
        if _parse_utc(record.canonical["expiry"]) <= now.astimezone(timezone.utc):
            raise ControlRejected("MANDATE_EXPIRED", "Mandate has expired.")
        self._require_no_mandate_interrupt(mandate_id)
        return record

    def require_dispatch_allowed(
        self,
        mandate_id: str,
        scope: TrustedScope,
        now: datetime,
    ) -> None:
        self._require_no_mandate_interrupt(mandate_id)
        try:
            kill_active = self.interrupts.any_active(
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
        if kill_active:
            raise ControlRejected(
                "KILL_SWITCH_ACTIVE",
                "durable kill switch blocks the unsent command.",
            )
        mandate = self.load(mandate_id)
        if mandate.status != "ACTIVE":
            raise ControlRejected(
                "MANDATE_REVOKED",
                "Mandate is no longer active.",
            )
        if _parse_utc(mandate.canonical["expiry"]) <= now.astimezone(timezone.utc):
            raise ControlRejected("MANDATE_EXPIRED", "Mandate has expired.")
        with self._connect() as connection:
            if self._kill_switch_active(connection, scope):
                raise ControlRejected(
                    "KILL_SWITCH_ACTIVE",
                    "durable kill switch blocks the unsent command.",
                )

    def _require_no_mandate_interrupt(self, mandate_id: str) -> None:
        try:
            active = self.interrupts.any_active("mandate", (mandate_id,))
        except InterruptStateUnavailable as error:
            raise ControlRejected(
                "KILL_SWITCH_UNAVAILABLE",
                "durable revocation interrupt is unavailable.",
            ) from error
        if active:
            raise ControlRejected("MANDATE_REVOKED", "Mandate is revoked.")

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        mandate_id: str,
        event_type: str,
        principal: AuthenticatedPrincipal,
        now: datetime,
        reason: Optional[str] = None,
    ) -> None:
        row = connection.execute(
            "SELECT COALESCE(MAX(event_version), 0) + 1 AS next_version "
            "FROM mandate_authority_events WHERE mandate_id = ?",
            (mandate_id,),
        ).fetchone()
        connection.execute(
            "INSERT INTO mandate_authority_events "
            "(mandate_id, event_version, event_type, principal, "
            "authentication, reason, occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                mandate_id,
                int(row["next_version"]),
                event_type,
                principal.identity,
                principal.authentication,
                reason,
                _utc_text(now),
            ),
        )

    @staticmethod
    def _validate_prepared_binding(
        mandate: MandateRecord,
        prepared: PreparedChange,
    ) -> None:
        canonical = mandate.canonical
        if (
            prepared.scope.organization != canonical["organization"]
            or prepared.scope.connection != canonical["connection"]
            or prepared.scope.account != canonical["account"]
            or prepared.scope.campaign not in canonical["targets"]
        ):
            raise ControlRejected(
                "MANDATE_TARGET_MISMATCH",
                "proposal target is outside the Mandate.",
            )
        if prepared.action.value not in canonical["allowed_action_classes"]:
            raise ControlRejected(
                "UNSUPPORTED_ACTION",
                "action is outside the Mandate.",
            )
        if prepared.action.value in canonical["prohibited_action_classes"]:
            raise ControlRejected(
                "UNSUPPORTED_ACTION",
                "action is explicitly prohibited by the Mandate.",
            )
        if prepared.policy_version != canonical["policy_version"]:
            raise ControlRejected(
                "POLICY_VERSION_MISMATCH",
                "proposal policy differs from the Mandate.",
            )

    def _check_quota(
        self,
        connection: sqlite3.Connection,
        mandate: MandateRecord,
        prepared: PreparedChange,
        monetary_exposure_rub: int,
        now: datetime,
    ) -> None:
        canonical = mandate.canonical
        all_usage = connection.execute(
            "SELECT COALESCE(SUM(monetary_exposure_rub), 0) AS monetary "
            "FROM mandate_consumptions WHERE mandate_id = ?",
            (mandate.mandate_id,),
        ).fetchone()
        if int(all_usage["monetary"]) + monetary_exposure_rub > int(
            canonical["total_monetary_limit"]
        ):
            raise ControlRejected(
                "MONETARY_CAP_REACHED",
                "Mandate total monetary limit is exhausted.",
            )
        since = _utc_text(now - timedelta(hours=24))
        recent = connection.execute(
            "SELECT COUNT(*) AS action_count FROM mandate_consumptions "
            "WHERE mandate_id = ? AND reserved_at > ?",
            (mandate.mandate_id, since),
        ).fetchone()
        if int(recent["action_count"]) >= int(
            canonical["action_quotas"]["actions_per_24h"]
        ):
            raise ControlRejected(
                "ACTION_QUOTA_REACHED",
                "Mandate action quota is exhausted.",
            )
        latest = connection.execute(
            "SELECT MAX(observation_until) AS observation_until "
            "FROM mandate_consumptions WHERE target = ?",
            (prepared.scope.campaign,),
        ).fetchone()
        if latest["observation_until"] is not None and _parse_utc(
            latest["observation_until"]
        ) > now.astimezone(timezone.utc):
            raise ControlRejected(
                "OBSERVATION_WINDOW_ACTIVE",
                "a second action is blocked until observation closes.",
            )
        day = _utc_text(now)[:10]
        daily = connection.execute(
            "SELECT COALESCE(SUM(monetary_exposure_rub), 0) AS monetary, "
            "COALESCE(SUM(step_change_percent), 0) AS step "
            "FROM mandate_consumptions "
            "WHERE mandate_id = ? AND substr(reserved_at, 1, 10) = ?",
            (mandate.mandate_id, day),
        ).fetchone()
        if int(daily["monetary"]) + monetary_exposure_rub > int(
            canonical["daily_monetary_limit"]
        ):
            raise ControlRejected(
                "DAILY_MONETARY_LIMIT_REACHED",
                "Mandate daily monetary limit is exhausted.",
            )
        step = self._step_percent(prepared)
        if step > int(canonical["maximum_step_change"]):
            raise ControlRejected(
                "STEP_LIMIT_EXCEEDED",
                "action exceeds the Mandate step limit.",
            )
        if int(daily["step"]) + step > int(canonical["maximum_daily_change"]):
            raise ControlRejected(
                "DAILY_CHANGE_LIMIT_EXCEEDED",
                "action exceeds the Mandate daily change limit.",
            )

    @staticmethod
    def _step_percent(prepared: PreparedChange) -> int:
        spec = ACTION_SPECS[prepared.action]
        if spec.relative_percent is None:
            return 0
        value = prepared.expected_diff.get("relative_step_percent")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ControlRejected(
                "INVALID_INPUT",
                "relative step must be an integer.",
            )
        return abs(value)

    @staticmethod
    def _kill_switch_active(
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
