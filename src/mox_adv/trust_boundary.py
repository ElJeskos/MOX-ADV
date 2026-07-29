"""Trust-boundary verification primitives for local prototype evidence."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

from mox_adv.audit import AuditAnchorSigner, SignedAuditAnchor, SQLiteAuditJournal
from mox_adv.recommend_projection import build_sanitized_projection

_CONTROL_FIELDS = frozenset(
    {
        "target",
        "method",
        "tool",
        "credential_profile",
        "authority",
        "scope",
        "approval",
        "mandate",
    }
)
_CAPABILITY_STATUSES = frozenset({"PROVEN", "PARTIAL", "NOT_PROVEN", "INCONCLUSIVE"})
_SECRET_SCAN_CHANNELS = frozenset(
    {
        "source",
        "prompt",
        "environment_variables",
        "argv",
        "logs",
        "stdout",
        "exceptions",
        "docker_metadata",
    }
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _flatten_strings(value: Any) -> Tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        flattened: list[str] = []
        for nested in value.values():
            flattened.extend(_flatten_strings(nested))
        return tuple(flattened)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        flattened = []
        for nested in value:
            flattened.extend(_flatten_strings(nested))
        return tuple(flattened)
    return ()


@dataclass(frozen=True)
class InjectionVerification:
    fixture_id: str
    surface: str
    injection_text: str
    projection: Mapping[str, Any]
    instruction_remained_data: bool
    authority_unchanged: bool
    policy_unchanged: bool


def verify_injection_fixture(
    fixture: Mapping[str, Any],
    trusted_snapshot: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> InjectionVerification:
    """Prove that one named untrusted surface cannot enter trusted controls."""

    fixture_id = fixture.get("fixture_id")
    surface = fixture.get("surface")
    untrusted_payload = fixture.get("untrusted_payload")
    if (
        not isinstance(fixture_id, str)
        or not fixture_id
        or not isinstance(surface, str)
        or not surface
        or not isinstance(untrusted_payload, Mapping)
    ):
        raise ValueError("Injection fixture must name one surface and payload.")
    strings = _flatten_strings(untrusted_payload)
    if not strings:
        raise ValueError("Injection fixture must contain untrusted text.")
    policy_before = hashlib.sha256(_canonical_json(policy).encode("utf-8")).hexdigest()
    source = dict(trusted_snapshot)
    source.update(untrusted_payload)
    projection = dict(build_sanitized_projection(source, policy))
    policy_after = hashlib.sha256(_canonical_json(policy).encode("utf-8")).hexdigest()
    serialized_projection = _canonical_json(projection)
    return InjectionVerification(
        fixture_id=fixture_id,
        surface=surface,
        injection_text=_canonical_json(untrusted_payload),
        projection=projection,
        instruction_remained_data=all(
            text not in serialized_projection for text in strings
        ),
        authority_unchanged=_CONTROL_FIELDS.isdisjoint(projection),
        policy_unchanged=policy_before == policy_after,
    )


class AuditGuardedFakeWriteAdapter:
    """Allow a fake write only after a current signed pre-write audit event."""

    is_fake = True

    def __init__(
        self,
        delegate: Any,
        journal: SQLiteAuditJournal,
        signer: AuditAnchorSigner,
        anchor: SignedAuditAnchor,
        expected_pre_write_hash: Optional[str],
        *,
        maximum_anchor_age: timedelta,
        clock: Callable[[], datetime],
    ) -> None:
        self.delegate = delegate
        self.journal = journal
        self.signer = signer
        self.anchor = anchor
        self.expected_pre_write_hash = expected_pre_write_hash
        self.maximum_anchor_age = maximum_anchor_age
        self.clock = clock

    def apply(self, target_key: str, command: object) -> None:
        self.journal.verify_pre_write_anchor(
            self.anchor,
            self.signer,
            self.expected_pre_write_hash,
            now=self.clock(),
            maximum_age=self.maximum_anchor_age,
        )
        self.delegate.apply(target_key, command)


class SecretCanaryScanner:
    """Scan every prohibited runtime surface without persisting the canary."""

    def __init__(self, canary: str) -> None:
        if not canary:
            raise ValueError("Secret canary must not be empty.")
        self._canary = canary.encode("utf-8")

    def scan(
        self,
        *,
        channels: Mapping[str, str],
        artifact_paths: Sequence[Path],
    ) -> Tuple[str, ...]:
        missing_channels = _SECRET_SCAN_CHANNELS.difference(channels)
        if missing_channels:
            raise ValueError(
                "Secret scan is missing prohibited channels: "
                + ", ".join(sorted(missing_channels))
            )
        violations = []
        for channel, value in channels.items():
            if self._canary in value.encode("utf-8", errors="replace"):
                violations.append("channel:" + channel)
        for path in artifact_paths:
            if path.is_file() and self._canary in path.read_bytes():
                violations.append("artifact:" + path.name)
        return tuple(sorted(violations))


@dataclass(frozen=True)
class CapabilityEvidence:
    capability: str
    status: str
    evidence_type: str
    acceptance_cases: Tuple[str, ...]
    evidence_paths: Tuple[str, ...]
    limitations: Tuple[str, ...]

    def as_dict(self) -> Mapping[str, Any]:
        if self.status not in _CAPABILITY_STATUSES:
            raise ValueError("Capability evidence status is invalid.")
        if (
            not self.capability
            or not self.evidence_type
            or not self.acceptance_cases
            or not self.evidence_paths
        ):
            raise ValueError("Capability evidence is incomplete.")
        return {
            "capability": self.capability,
            "status": self.status,
            "evidence_type": self.evidence_type,
            "acceptance_cases": list(self.acceptance_cases),
            "evidence_paths": list(self.evidence_paths),
            "limitations": list(self.limitations),
        }


def write_capability_evidence_summary(
    path: Path,
    *,
    run_id: str,
    policy_version: str,
    capabilities: Sequence[CapabilityEvidence],
) -> None:
    """Atomically write an honest, acceptance-case-aligned evidence summary."""

    if not run_id or not policy_version or not capabilities:
        raise ValueError("Capability evidence summary is incomplete.")
    value = {
        "schema_version": "capability-evidence-v1",
        "run_id": run_id,
        "policy_version": policy_version,
        "capabilities": [item.as_dict() for item in capabilities],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="." + path.name + ".",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(
                json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
