"""Transactional SQLite audit journal with a sealed SHA-256 hash chain."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from mox_adv.canonical import canonical_json
from mox_adv.contracts import AuditVerification, PersistedEvent

GENESIS_HASH = "0" * 64


class AuditIntegrityError(RuntimeError):
    """The journal no longer matches its committed hash chain."""


class AuditSealedError(RuntimeError):
    """A sealed journal is immutable."""


class AuditAnchorVerificationError(RuntimeError):
    """A signed audit anchor is invalid, stale, or belongs to another journal."""


class AuditWriteBlocked(RuntimeError):
    """A write lacks a current, signed pre-write audit event."""


class AuditAnchorSigner(Protocol):
    """Sign and verify a canonical anchor without exposing signing material."""

    key_id: str

    def sign(self, payload: bytes) -> str: ...

    def verify(self, payload: bytes, signature: str) -> bool: ...


@dataclass(frozen=True)
class SignedAuditAnchor:
    schema_version: str
    run_id: str
    policy_version: str
    final_sequence: int
    final_hash: str
    anchored_at: str
    key_id: str
    signature: str

    def signing_payload(self) -> bytes:
        return canonical_json(
            {
                "anchored_at": self.anchored_at,
                "final_hash": self.final_hash,
                "final_sequence": self.final_sequence,
                "key_id": self.key_id,
                "policy_version": self.policy_version,
                "run_id": self.run_id,
                "schema_version": self.schema_version,
            }
        ).encode("utf-8")

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "policy_version": self.policy_version,
            "final_sequence": self.final_sequence,
            "final_hash": self.final_hash,
            "anchored_at": self.anchored_at,
            "key_id": self.key_id,
            "signature": self.signature,
        }

    def with_signature(self, signature: str) -> "SignedAuditAnchor":
        return replace(self, signature=signature)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SignedAuditAnchor":
        fields = {
            "schema_version",
            "run_id",
            "policy_version",
            "final_sequence",
            "final_hash",
            "anchored_at",
            "key_id",
            "signature",
        }
        if set(value) != fields:
            raise AuditAnchorVerificationError(
                "The signed audit anchor schema is invalid."
            )
        if (
            not isinstance(value["final_sequence"], int)
            or isinstance(value["final_sequence"], bool)
            or any(
                not isinstance(value[name], str) or not value[name]
                for name in fields - {"final_sequence"}
            )
        ):
            raise AuditAnchorVerificationError(
                "The signed audit anchor fields are invalid."
            )
        return cls(
            schema_version=value["schema_version"],
            run_id=value["run_id"],
            policy_version=value["policy_version"],
            final_sequence=value["final_sequence"],
            final_hash=value["final_hash"],
            anchored_at=value["anchored_at"],
            key_id=value["key_id"],
            signature=value["signature"],
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_hash(
    sequence: int,
    run_id: str,
    schema_version: str,
    policy_version: str,
    occurred_at: str,
    event_type: str,
    payload: Mapping[str, Any],
    previous_hash: str,
) -> str:
    canonical = {
        "sequence": sequence,
        "run_id": run_id,
        "schema_version": schema_version,
        "policy_version": policy_version,
        "occurred_at": occurred_at,
        "event_type": event_type,
        "payload": dict(payload),
        "previous_hash": previous_hash,
    }
    return hashlib.sha256(canonical_json(canonical).encode("utf-8")).hexdigest()


class SQLiteAuditJournal:
    """One journal per immutable run directory."""

    def __init__(
        self,
        path: Path,
        run_id: str,
        schema_version: str,
        policy_version: str,
    ) -> None:
        self.path = path
        self.run_id = run_id
        self.schema_version = schema_version
        self.policy_version = policy_version
        self._connection = sqlite3.connect(str(path), timeout=5, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS run_state (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                run_id TEXT NOT NULL UNIQUE,
                schema_version TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'SEALED')),
                final_sequence INTEGER NOT NULL,
                final_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY CHECK (sequence > 0),
                run_id TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL UNIQUE
            );
            """
        )
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            existing = self._connection.execute(
                "SELECT run_id FROM run_state WHERE singleton = 1"
            ).fetchone()
            if existing is not None:
                raise AuditIntegrityError("The audit journal already has an owner.")
            self._connection.execute(
                """
                INSERT INTO run_state (
                    singleton, run_id, schema_version, policy_version,
                    status, final_sequence, final_hash
                ) VALUES (1, ?, ?, ?, 'ACTIVE', 0, ?)
                """,
                (run_id, schema_version, policy_version, GENESIS_HASH),
            )
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            self._connection.close()
            raise

    @classmethod
    def open(cls, path: Path) -> "SQLiteAuditJournal":
        instance = cls.__new__(cls)
        instance.path = path
        instance._connection = sqlite3.connect(
            str(path),
            timeout=5,
            isolation_level=None,
        )
        instance._connection.row_factory = sqlite3.Row
        state = instance._connection.execute(
            """
            SELECT run_id, schema_version, policy_version
            FROM run_state
            WHERE singleton = 1
            """
        ).fetchone()
        if state is None:
            instance._connection.close()
            raise AuditIntegrityError("The audit journal has no run state.")
        instance.run_id = state["run_id"]
        instance.schema_version = state["schema_version"]
        instance.policy_version = state["policy_version"]
        return instance

    def append(
        self,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> PersistedEvent:
        if not event_type or len(event_type) > 128:
            raise ValueError("The audit event type is invalid.")
        payload_json = canonical_json(dict(payload))
        occurred_at = _utc_now()
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            state = self._connection.execute(
                """
                SELECT status, final_sequence, final_hash
                FROM run_state
                WHERE singleton = 1
                """
            ).fetchone()
            if state is None:
                raise AuditIntegrityError("The audit journal has no run state.")
            if state["status"] != "ACTIVE":
                raise AuditSealedError("The audit journal is sealed.")
            previous = self._connection.execute(
                """
                SELECT sequence, event_hash
                FROM events
                ORDER BY sequence DESC
                LIMIT 1
                """
            ).fetchone()
            committed_sequence = 0 if previous is None else int(previous["sequence"])
            committed_hash = (
                GENESIS_HASH if previous is None else previous["event_hash"]
            )
            if (
                state["final_sequence"] != committed_sequence
                or state["final_hash"] != committed_hash
            ):
                raise AuditIntegrityError(
                    "The current audit tail does not match its durable anchor."
                )
            self._verify_rows()
            sequence = 1 if previous is None else int(previous["sequence"]) + 1
            previous_hash = GENESIS_HASH if previous is None else previous["event_hash"]
            event_hash = _event_hash(
                sequence=sequence,
                run_id=self.run_id,
                schema_version=self.schema_version,
                policy_version=self.policy_version,
                occurred_at=occurred_at,
                event_type=event_type,
                payload=json.loads(payload_json),
                previous_hash=previous_hash,
            )
            self._connection.execute(
                """
                INSERT INTO events (
                    sequence, run_id, schema_version, policy_version,
                    occurred_at, event_type, payload_json,
                    previous_hash, event_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    self.run_id,
                    self.schema_version,
                    self.policy_version,
                    occurred_at,
                    event_type,
                    payload_json,
                    previous_hash,
                    event_hash,
                ),
            )
            self._connection.execute(
                """
                UPDATE run_state
                SET final_sequence = ?, final_hash = ?
                WHERE singleton = 1 AND status = 'ACTIVE'
                """,
                (sequence, event_hash),
            )
            self._connection.execute("COMMIT")
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise
        return PersistedEvent(
            sequence=sequence,
            run_id=self.run_id,
            schema_version=self.schema_version,
            policy_version=self.policy_version,
            occurred_at=occurred_at,
            event_type=event_type,
            payload=json.loads(payload_json),
            previous_hash=previous_hash,
            event_hash=event_hash,
        )

    def seal(self) -> AuditVerification:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            verification = self.verify()
            state = self._connection.execute(
                "SELECT status FROM run_state WHERE singleton = 1"
            ).fetchone()
            if state is None:
                raise AuditIntegrityError("The audit journal has no run state.")
            if state["status"] != "ACTIVE":
                raise AuditSealedError("The audit journal is sealed.")
            final = self._connection.execute(
                """
                SELECT sequence, event_hash
                FROM events
                ORDER BY sequence DESC
                LIMIT 1
                """
            ).fetchone()
            if final is None:
                raise AuditIntegrityError("An empty audit journal cannot be sealed.")
            if (
                verification.final_sequence != final["sequence"]
                or verification.final_hash != final["event_hash"]
            ):
                raise AuditIntegrityError(
                    "The verified audit chain does not match its current tail."
                )
            self._connection.execute(
                """
                UPDATE run_state
                SET status = 'SEALED', final_sequence = ?, final_hash = ?
                WHERE singleton = 1 AND status = 'ACTIVE'
                """,
                (final["sequence"], final["event_hash"]),
            )
            self._connection.execute("COMMIT")
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise
        return AuditVerification(
            final_sequence=int(final["sequence"]),
            final_hash=final["event_hash"],
        )

    def _verify_rows(self) -> AuditVerification:
        rows = self._connection.execute(
            """
            SELECT sequence, run_id, schema_version, policy_version,
                   occurred_at, event_type, payload_json,
                   previous_hash, event_hash
            FROM events
            ORDER BY sequence
            """
        ).fetchall()
        previous_hash = GENESIS_HASH
        expected_sequence = 1
        for row in rows:
            if row["sequence"] != expected_sequence:
                raise AuditIntegrityError("The audit event sequence is not contiguous.")
            if row["previous_hash"] != previous_hash:
                raise AuditIntegrityError("The audit previous hash does not match.")
            if (
                row["run_id"] != self.run_id
                or row["schema_version"] != self.schema_version
                or row["policy_version"] != self.policy_version
            ):
                raise AuditIntegrityError("The audit event owner metadata changed.")
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError as error:
                raise AuditIntegrityError(
                    "The audit event payload is invalid."
                ) from error
            expected_hash = _event_hash(
                sequence=row["sequence"],
                run_id=row["run_id"],
                schema_version=row["schema_version"],
                policy_version=row["policy_version"],
                occurred_at=row["occurred_at"],
                event_type=row["event_type"],
                payload=payload,
                previous_hash=row["previous_hash"],
            )
            if row["event_hash"] != expected_hash:
                raise AuditIntegrityError("The audit event hash does not match.")
            previous_hash = row["event_hash"]
            expected_sequence += 1
        final_sequence = len(rows)
        final_hash = GENESIS_HASH if not rows else previous_hash
        return AuditVerification(
            final_sequence=final_sequence,
            final_hash=final_hash,
        )

    def verify(self) -> AuditVerification:
        state = self._connection.execute(
            """
            SELECT run_id, schema_version, policy_version, status,
                   final_sequence, final_hash
            FROM run_state
            WHERE singleton = 1
            """
        ).fetchone()
        if state is None:
            raise AuditIntegrityError("The audit journal has no run state.")
        if (
            state["run_id"] != self.run_id
            or state["schema_version"] != self.schema_version
            or state["policy_version"] != self.policy_version
        ):
            raise AuditIntegrityError("The audit journal owner metadata changed.")
        verification = self._verify_rows()
        if (
            state["final_sequence"] != verification.final_sequence
            or state["final_hash"] != verification.final_hash
        ):
            state_label = "sealed" if state["status"] == "SEALED" else "active"
            raise AuditIntegrityError(
                "The " + state_label + " audit anchor does not match."
            )
        return verification

    def create_signed_anchor(
        self,
        signer: AuditAnchorSigner,
        anchored_at: datetime,
    ) -> SignedAuditAnchor:
        if anchored_at.tzinfo is None or anchored_at.utcoffset() is None:
            raise ValueError("Audit anchor time must be timezone-aware.")
        verification = self.verify()
        unsigned = SignedAuditAnchor(
            schema_version=self.schema_version,
            run_id=self.run_id,
            policy_version=self.policy_version,
            final_sequence=verification.final_sequence,
            final_hash=verification.final_hash,
            anchored_at=anchored_at.astimezone(timezone.utc).isoformat(),
            key_id=signer.key_id,
            signature="",
        )
        return unsigned.with_signature(signer.sign(unsigned.signing_payload()))

    def verify_signed_anchor(
        self,
        anchor: SignedAuditAnchor,
        signer: AuditAnchorSigner,
        *,
        now: datetime,
        maximum_age: timedelta,
    ) -> AuditVerification:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Audit verification time must be timezone-aware.")
        if maximum_age <= timedelta(0):
            raise ValueError("Audit anchor maximum age must be positive.")
        verification = self.verify()
        if (
            anchor.schema_version != self.schema_version
            or anchor.run_id != self.run_id
            or anchor.policy_version != self.policy_version
            or anchor.final_sequence != verification.final_sequence
            or anchor.final_hash != verification.final_hash
            or anchor.key_id != signer.key_id
        ):
            raise AuditAnchorVerificationError(
                "The signed audit anchor does not match the current journal."
            )
        try:
            anchored_at = datetime.fromisoformat(anchor.anchored_at)
        except ValueError as error:
            raise AuditAnchorVerificationError(
                "The signed audit anchor time is invalid."
            ) from error
        if anchored_at.tzinfo is None or anchored_at.utcoffset() is None:
            raise AuditAnchorVerificationError(
                "The signed audit anchor time is not timezone-aware."
            )
        age = now.astimezone(timezone.utc) - anchored_at.astimezone(timezone.utc)
        if age < timedelta(0) or age > maximum_age:
            raise AuditAnchorVerificationError(
                "The signed audit anchor is outside its approved period."
            )
        if not signer.verify(anchor.signing_payload(), anchor.signature):
            raise AuditAnchorVerificationError(
                "The signed audit anchor signature is invalid."
            )
        return verification

    def verify_pre_write_anchor(
        self,
        anchor: SignedAuditAnchor,
        signer: AuditAnchorSigner,
        expected_pre_write_hash: Any,
        *,
        now: datetime,
        maximum_age: timedelta,
    ) -> None:
        if not isinstance(expected_pre_write_hash, str):
            raise AuditWriteBlocked("PRE_WRITE_AUDIT_MISSING")
        try:
            verification = self.verify_signed_anchor(
                anchor,
                signer,
                now=now,
                maximum_age=maximum_age,
            )
        except (AuditIntegrityError, AuditAnchorVerificationError) as error:
            raise AuditWriteBlocked("AUDIT_ANCHOR_INVALID") from error
        latest = self._connection.execute(
            """
            SELECT event_type, event_hash
            FROM events
            ORDER BY sequence DESC
            LIMIT 1
            """
        ).fetchone()
        if (
            latest is None
            or latest["event_type"] != "write.intent.recorded"
            or latest["event_hash"] != expected_pre_write_hash
            or verification.final_hash != expected_pre_write_hash
        ):
            raise AuditWriteBlocked("PRE_WRITE_AUDIT_MISSING")

    def export_jsonl(self, path: Path) -> None:
        verification = self.verify()
        state = self._connection.execute(
            "SELECT status FROM run_state WHERE singleton = 1"
        ).fetchone()
        if state is None or state["status"] != "SEALED":
            raise AuditIntegrityError("Only a sealed audit journal can be exported.")
        rows = self._connection.execute(
            """
            SELECT sequence, run_id, schema_version, policy_version,
                   occurred_at, event_type, payload_json,
                   previous_hash, event_hash
            FROM events
            ORDER BY sequence
            """
        ).fetchall()
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="." + path.name + ".",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                for row in rows:
                    event = PersistedEvent(
                        sequence=row["sequence"],
                        run_id=row["run_id"],
                        schema_version=row["schema_version"],
                        policy_version=row["policy_version"],
                        occurred_at=row["occurred_at"],
                        event_type=row["event_type"],
                        payload=json.loads(row["payload_json"]),
                        previous_hash=row["previous_hash"],
                        event_hash=row["event_hash"],
                    )
                    stream.write(canonical_json(event.as_dict()) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        if verification.final_sequence != len(rows):
            raise AuditIntegrityError("The audit export is incomplete.")

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "SQLiteAuditJournal":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
