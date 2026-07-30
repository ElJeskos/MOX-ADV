"""Immutable canonical proposal persistence."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from mox_adv.recommend_contracts import (
    _SAFE_IDENTIFIER,
    _SHA256,
    OptimizationProposalV1,
    ProposalConflictError,
    ProviderMetadata,
    SchemaValidationError,
    _canonical_hash,
    _closed,
    _parse_utc,
)


@dataclass(frozen=True)
class StoredProposal:
    canonical_hash: str
    deduplicated: bool
    proposal_id: str


@dataclass(frozen=True)
class ActiveStoredProposal:
    proposal: OptimizationProposalV1
    provider: ProviderMetadata
    canonical_hash: str


def normalized_reason_key(observed_facts: Any) -> str:
    if not isinstance(observed_facts, (tuple, list)) or any(
        not isinstance(item, str) or not item for item in observed_facts
    ):
        raise SchemaValidationError("Proposal reason facts are invalid.")
    canonical = json.dumps(
        sorted(set(observed_facts)),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


class ImmutableProposalStore:
    """Persist canonical proposal envelopes without overwrite."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / ".active-proposals.sqlite3"
        with self._connect_index() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS active_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL,
                    reason_key TEXT NOT NULL,
                    canonical_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE UNIQUE INDEX IF NOT EXISTS
                    one_active_proposal_per_snapshot_reason
                ON active_proposals(snapshot_id, reason_key) WHERE active = 1;
                """
            )

    def _connect_index(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.index_path), timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def save(
        self,
        proposal: OptimizationProposalV1,
        provider: ProviderMetadata,
        *,
        reason_facts: Any = None,
        at: Optional[datetime] = None,
    ) -> StoredProposal:
        proposal_data = proposal.as_dict()
        canonical_hash = _canonical_hash(proposal_data)
        normalized_reason = normalized_reason_key(
            proposal.observed_facts
            if reason_facts is None
            else reason_facts
        )
        expires_at = _parse_utc(
            proposal.expires_at,
            "Proposal expiry",
        ).isoformat()
        envelope = {
            "schema_version": "stored-proposal-v2",
            "canonical_hash": canonical_hash,
            "reason_key": normalized_reason,
            "proposal": proposal_data,
            "provider": provider.as_dict(),
        }
        canonical_bytes = json.dumps(
            envelope,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        timestamp = (
            _parse_utc(proposal.created_at, "Proposal created_at")
            if at is None
            else self._aware_utc(at)
        )
        connection = self._connect_index()
        created_path = False
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE active_proposals SET active = 0 "
                "WHERE active = 1 AND expires_at <= ?",
                (timestamp.isoformat(),),
            )
            active = connection.execute(
                "SELECT proposal_id, canonical_hash FROM active_proposals "
                "WHERE snapshot_id = ? AND reason_key = ? AND active = 1",
                (proposal.snapshot_id, normalized_reason),
            ).fetchone()
            if active is not None:
                existing_path = self.root / (str(active["proposal_id"]) + ".json")
                existing, _ = self._load_envelope(existing_path)
                existing_proposal = existing["proposal"]
                if (
                    not isinstance(existing_proposal, Mapping)
                    or existing["canonical_hash"] != active["canonical_hash"]
                    or _canonical_hash(existing_proposal)
                    != active["canonical_hash"]
                    or existing_proposal.get("snapshot_id")
                    != proposal.snapshot_id
                    or existing["reason_key"] != normalized_reason
                ):
                    raise ProposalConflictError(
                        "Active proposal index does not match immutable content."
                    )
                connection.commit()
                return StoredProposal(
                    canonical_hash=str(active["canonical_hash"]),
                    deduplicated=True,
                    proposal_id=str(active["proposal_id"]),
                )
            path = self.root / (proposal.proposal_id + ".json")
            try:
                descriptor = os.open(
                    path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o400,
                )
            except FileExistsError:
                existing, existing_bytes = self._load_envelope(path)
                if (
                    existing["canonical_hash"] != canonical_hash
                    or existing_bytes != canonical_bytes
                ):
                    raise ProposalConflictError(
                        "An immutable proposal ID already contains different content."
                    )
                indexed = connection.execute(
                    "INSERT INTO active_proposals "
                    "(proposal_id, snapshot_id, reason_key, canonical_hash, "
                    "expires_at, active) VALUES (?, ?, ?, ?, ?, 1) "
                    "ON CONFLICT(proposal_id) DO UPDATE SET "
                    "active = 1 WHERE snapshot_id = excluded.snapshot_id "
                    "AND reason_key = excluded.reason_key "
                    "AND canonical_hash = excluded.canonical_hash "
                    "AND expires_at = excluded.expires_at",
                    (
                        proposal.proposal_id,
                        proposal.snapshot_id,
                        normalized_reason,
                        canonical_hash,
                        expires_at,
                    ),
                )
                if indexed.rowcount != 1:
                    raise ProposalConflictError(
                        "Immutable proposal index could not be reactivated."
                    )
                connection.commit()
                return StoredProposal(
                    canonical_hash=canonical_hash,
                    deduplicated=True,
                    proposal_id=proposal.proposal_id,
                )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(canonical_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
                created_path = True
                connection.execute(
                    "INSERT INTO active_proposals "
                    "(proposal_id, snapshot_id, reason_key, canonical_hash, "
                    "expires_at, active) VALUES (?, ?, ?, ?, ?, 1)",
                    (
                        proposal.proposal_id,
                        proposal.snapshot_id,
                        normalized_reason,
                        canonical_hash,
                        expires_at,
                    ),
                )
                connection.commit()
            except BaseException:
                if created_path:
                    try:
                        path.unlink()
                    except OSError:
                        pass
                raise
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        return StoredProposal(
            canonical_hash=canonical_hash,
            deduplicated=False,
            proposal_id=proposal.proposal_id,
        )

    def load_active_by_reason(
        self,
        snapshot_id: str,
        reason_key: str,
        projection: Mapping[str, Any],
        at: datetime,
    ) -> Optional[ActiveStoredProposal]:
        timestamp = self._aware_utc(at)
        with self._connect_index() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE active_proposals SET active = 0 "
                "WHERE active = 1 AND expires_at <= ?",
                (timestamp.isoformat(),),
            )
            row = connection.execute(
                "SELECT proposal_id, canonical_hash, expires_at "
                "FROM active_proposals "
                "WHERE snapshot_id = ? AND reason_key = ? AND active = 1",
                (snapshot_id, reason_key),
            ).fetchone()
        if row is None:
            return None
        path = self.root / (str(row["proposal_id"]) + ".json")
        envelope, _ = self._load_envelope(path)
        proposal = OptimizationProposalV1.from_mapping(
            envelope["proposal"],
            projection,
        )
        if (
            envelope["canonical_hash"] != row["canonical_hash"]
            or _canonical_hash(proposal.as_dict()) != row["canonical_hash"]
            or envelope["reason_key"] != reason_key
            or proposal.snapshot_id != snapshot_id
            or _parse_utc(proposal.expires_at, "Proposal expiry").isoformat()
            != row["expires_at"]
        ):
            raise ProposalConflictError("Active proposal integrity check failed.")
        return ActiveStoredProposal(
            proposal=proposal,
            provider=self._provider(envelope["provider"]),
            canonical_hash=str(row["canonical_hash"]),
        )

    def load_active(
        self,
        proposal_id: str,
        projection: Mapping[str, Any],
        at: Optional[datetime] = None,
    ) -> Optional[OptimizationProposalV1]:
        if _SAFE_IDENTIFIER.fullmatch(proposal_id) is None:
            raise SchemaValidationError("Proposal ID is invalid.")
        path = self.root / (proposal_id + ".json")
        if not path.is_file():
            return None
        envelope, _ = self._load_envelope(path)
        proposal = OptimizationProposalV1.from_mapping(
            envelope["proposal"],
            projection,
        )
        if _canonical_hash(proposal.as_dict()) != envelope["canonical_hash"]:
            raise ProposalConflictError("Stored proposal canonical hash is invalid.")
        now = (
            datetime.now(timezone.utc)
            if at is None
            else self._aware_utc(at)
        )
        if _parse_utc(proposal.expires_at, "Proposal expiry") <= now:
            return None
        with self._connect_index() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE active_proposals SET active = 0 "
                "WHERE active = 1 AND expires_at <= ?",
                (now.isoformat(),),
            )
            indexed = connection.execute(
                "SELECT canonical_hash, snapshot_id, expires_at "
                "FROM active_proposals WHERE proposal_id = ? AND active = 1",
                (proposal_id,),
            ).fetchone()
        if indexed is None:
            return None
        if (
            indexed["canonical_hash"] != envelope["canonical_hash"]
            or indexed["snapshot_id"] != proposal.snapshot_id
            or indexed["expires_at"]
            != _parse_utc(proposal.expires_at, "Proposal expiry").isoformat()
        ):
            raise ProposalConflictError("Active proposal index is inconsistent.")
        return proposal

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise SchemaValidationError("Proposal evaluation time must be aware.")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _load_envelope(path: Path) -> tuple[Mapping[str, Any], bytes]:
        try:
            content = path.read_bytes()
            value = json.loads(content.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ProposalConflictError("Stored proposal cannot be read.") from error
        _closed(
            value,
            (
                "schema_version",
                "canonical_hash",
                "reason_key",
                "proposal",
                "provider",
            ),
            "Stored proposal",
        )
        if value["schema_version"] != "stored-proposal-v2":
            raise ProposalConflictError("Stored proposal version is unsupported.")
        if not isinstance(value["canonical_hash"], str) or _SHA256.fullmatch(
            value["canonical_hash"]
        ) is None:
            raise ProposalConflictError("Stored proposal hash is invalid.")
        if not isinstance(value["reason_key"], str) or _SHA256.fullmatch(
            value["reason_key"]
        ) is None:
            raise ProposalConflictError("Stored proposal reason is invalid.")
        canonical_bytes = json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        if content != canonical_bytes:
            raise ProposalConflictError("Stored proposal bytes are not canonical.")
        return value, content

    @staticmethod
    def _provider(value: Mapping[str, Any]) -> ProviderMetadata:
        try:
            metadata = ProviderMetadata(
                provider=str(value["provider"]),
                model_id=str(value["model_id"]),
                input_tokens=int(value["input_tokens"]),
                output_tokens=int(value["output_tokens"]),
                cost_rub=str(value["cost_rub"]),
                duration_ms=int(value["duration_ms"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ProposalConflictError(
                "Stored provider metadata is invalid."
            ) from error
        if (
            not metadata.provider
            or not metadata.model_id
            or min(
                metadata.input_tokens,
                metadata.output_tokens,
                metadata.duration_ms,
            )
            < 0
        ):
            raise ProposalConflictError("Stored provider metadata is invalid.")
        return metadata
