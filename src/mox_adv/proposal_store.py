"""Immutable canonical proposal persistence."""

from __future__ import annotations

import json
import os
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


class ImmutableProposalStore:
    """Persist canonical proposal envelopes without overwrite."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        proposal: OptimizationProposalV1,
        provider: ProviderMetadata,
    ) -> StoredProposal:
        proposal_data = proposal.as_dict()
        canonical_hash = _canonical_hash(proposal_data)
        envelope = {
            "schema_version": "stored-proposal-v1",
            "canonical_hash": canonical_hash,
            "proposal": proposal_data,
            "provider": provider.as_dict(),
        }
        canonical_bytes = json.dumps(
            envelope,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
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
            return StoredProposal(canonical_hash=canonical_hash, deduplicated=True)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(canonical_bytes)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            try:
                path.unlink()
            except OSError:
                pass
            raise
        return StoredProposal(canonical_hash=canonical_hash, deduplicated=False)

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
        now = datetime.now(timezone.utc) if at is None else at.astimezone(timezone.utc)
        if _parse_utc(proposal.expires_at, "Proposal expiry") <= now:
            return None
        return proposal

    @staticmethod
    def _load_envelope(path: Path) -> tuple[Mapping[str, Any], bytes]:
        try:
            content = path.read_bytes()
            value = json.loads(content.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ProposalConflictError("Stored proposal cannot be read.") from error
        _closed(
            value,
            ("schema_version", "canonical_hash", "proposal", "provider"),
            "Stored proposal",
        )
        if value["schema_version"] != "stored-proposal-v1":
            raise ProposalConflictError("Stored proposal version is unsupported.")
        if (
            not isinstance(value["canonical_hash"], str)
            or _SHA256.fullmatch(value["canonical_hash"]) is None
        ):
            raise ProposalConflictError("Stored proposal hash is invalid.")
        canonical_bytes = json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        if content != canonical_bytes:
            raise ProposalConflictError("Stored proposal bytes are not canonical.")
        return value, content
