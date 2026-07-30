"""Trust-boundary verification primitives for local prototype evidence."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from mox_adv.audit import (
    AuditAnchorSigner,
    AuditWriteBlocked,
    SignedAuditAnchor,
    SQLiteAuditJournal,
)
from mox_adv.canonical import canonical_json
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
_CAPABILITY_STATUSES = frozenset({"PROVEN", "NOT_PROVEN", "INCONCLUSIVE", "NOT_TESTED"})
_EVIDENCE_TYPES = frozenset(
    {"TEST_COUNTER", "REAL_READ_ONLY", "SIMULATED", "CONTROLLED_PILOT"}
)
_REQUIRED_CAPABILITIES = (
    "CAMPAIGN_LIFECYCLE",
    "GOAL_LIFECYCLE",
    "SOURCE_INTEGRATION",
    "INTEGRATED_ANALYTICS",
    "LLM_ANALYSIS",
    "APPROVAL_REQUIRED",
    "BOUNDED_AUTONOMY",
    "MONITORING_AND_ALERTING",
    "IMPACT_EVALUATION",
    "OPERATIONAL_MODES",
    "TOOL_CONTRACT",
    "ORIGINAL_INTEGRATION_COVERAGE",
    "SAFETY_CORE",
    "CLOSED_LOOP_CONTROL",
)
_CAPABILITY_ACCEPTANCE_CASES = {
    "CAMPAIGN_LIFECYCLE": ("02", "11", "27"),
    "GOAL_LIFECYCLE": ("03", "12", "12.1", "12.2", "27"),
    "SOURCE_INTEGRATION": ("08", "09", "27"),
    "INTEGRATED_ANALYTICS": ("08", "09", "27"),
    "LLM_ANALYSIS": ("07", "10", "22", "22.1", "25", "27"),
    "APPROVAL_REQUIRED": ("15", "27"),
    "BOUNDED_AUTONOMY": ("15.1", "15.2", "27"),
    "MONITORING_AND_ALERTING": ("20", "27"),
    "IMPACT_EVALUATION": ("21", "21.2", "27"),
    "OPERATIONAL_MODES": ("13", "14", "15", "15.1", "27"),
    "TOOL_CONTRACT": ("01", "02", "16", "16.2", "27"),
    "ORIGINAL_INTEGRATION_COVERAGE": ("02", "03", "27"),
    "SAFETY_CORE": (
        "00",
        "05",
        "06",
        "16",
        "16.1",
        "16.2",
        "17",
        "17.1",
        "17.2",
        "18",
        "19",
        "19.1",
        "19.2",
        "22",
        "22.1",
        "23",
        "23.1",
        "24",
        "25",
        "26",
        "27",
    ),
    "CLOSED_LOOP_CONTROL": ("21.1", "27"),
}
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


def required_capability_contract() -> Mapping[str, tuple[str, ...]]:
    """Return the normative capability order and acceptance-case bindings."""

    return {
        capability: _CAPABILITY_ACCEPTANCE_CASES[capability]
        for capability in _REQUIRED_CAPABILITIES
    }


def _flatten_strings(value: Any) -> tuple[str, ...]:
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
    untrusted_text_excluded: bool
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
    policy_before = hashlib.sha256(canonical_json(policy).encode("utf-8")).hexdigest()
    source = dict(trusted_snapshot)
    source.update(untrusted_payload)
    projection = build_sanitized_projection(source, policy)
    policy_after = hashlib.sha256(canonical_json(policy).encode("utf-8")).hexdigest()
    serialized_projection = canonical_json(dict(projection))
    return InjectionVerification(
        fixture_id=fixture_id,
        surface=surface,
        injection_text=canonical_json(untrusted_payload),
        projection=projection,
        untrusted_text_excluded=all(
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
        expected_pre_write_hash: str | None,
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


class PreWriteAudit(Protocol):
    def authorize(
        self,
        execution_key: str,
        target_key: str,
        occurred_at: datetime,
    ) -> None: ...


class WriteWindow(Protocol):
    def reserve(self, execution_key: str) -> None: ...

    def release(self, execution_key: str) -> None: ...


class GuardedDispatchBoundary:
    """Order durable pre-write evidence before write-window reservation."""

    def __init__(
        self,
        pre_write_audit: PreWriteAudit,
        write_window: WriteWindow,
        clock: Callable[[], datetime],
    ) -> None:
        self.pre_write_audit = pre_write_audit
        self.write_window = write_window
        self.clock = clock

    def authorize(
        self,
        execution_key: str,
        target_key: str,
        final_check: Callable[[], None] | None = None,
    ) -> None:
        self.pre_write_audit.authorize(
            execution_key,
            target_key,
            self.clock(),
        )
        self.write_window.reserve(execution_key)
        try:
            if final_check is not None:
                final_check()
        except BaseException:
            self.write_window.release(execution_key)
            raise


class SimulationAuditAnchorSigner:
    """Reproducible non-secret signer used only by fake-adapter simulation."""

    key_id = "simulation-audit-anchor-v1"
    _key = b"MOX-ADV-NON-SECRET-SIMULATION-ANCHOR-V1"

    def sign(self, payload: bytes) -> str:
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def verify(self, payload: bytes, signature: str) -> bool:
        return hmac.compare_digest(self.sign(payload), signature)


class MacOSKeychainAuditAnchorSigner:
    """Load trusted audit signing material from macOS Keychain per operation."""

    def __init__(
        self,
        *,
        service: str = "MOX_ADV_AUDIT_ANCHOR_SIGNING_KEY",
        account: str = "sviridov",
    ) -> None:
        self.service = service
        self.account = account
        self.key_id = "macos-keychain:" + service + ":" + account

    def _key(self) -> bytes:
        try:
            completed = subprocess.run(
                [
                    "/usr/bin/security",
                    "find-generic-password",
                    "-w",
                    "-s",
                    self.service,
                    "-a",
                    self.account,
                ],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise AuditWriteBlocked("AUDIT_SIGNING_UNAVAILABLE") from error
        key = completed.stdout.rstrip(b"\r\n")
        if completed.returncode != 0 or not key:
            raise AuditWriteBlocked("AUDIT_SIGNING_UNAVAILABLE")
        return key

    def sign(self, payload: bytes) -> str:
        return hmac.new(self._key(), payload, hashlib.sha256).hexdigest()

    def verify(self, payload: bytes, signature: str) -> bool:
        expected = hmac.new(self._key(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)


class DurablePreWriteAudit:
    """Persist and verify one signed intent immediately before dispatch."""

    def __init__(
        self,
        control_state_path: Path,
        policy_version: str,
        signer: AuditAnchorSigner,
    ) -> None:
        self.root = control_state_path.parent / (
            "." + control_state_path.name + ".pre-write-audit"
        )
        self.policy_version = policy_version
        self.signer = signer

    def authorize(
        self,
        execution_key: str,
        target_key: str,
        occurred_at: datetime,
    ) -> None:
        digest = hashlib.sha256(execution_key.encode("utf-8")).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        journal_path = self.root / (digest + ".sqlite3")
        anchor_path = self.root / (digest + ".anchor.json")
        if journal_path.exists() or anchor_path.exists():
            raise AuditWriteBlocked("PRE_WRITE_AUDIT_ALREADY_EXISTS")
        journal: SQLiteAuditJournal | None = None
        try:
            journal = SQLiteAuditJournal(
                journal_path,
                execution_key,
                "pre-write-audit-v1",
                self.policy_version,
            )
            event = journal.append(
                "write.intent.recorded",
                {
                    "execution_key": execution_key,
                    "target_key": target_key,
                },
            )
            anchor = journal.create_signed_anchor(self.signer, occurred_at)
            journal.verify_pre_write_anchor(
                anchor,
                self.signer,
                event.event_hash,
                now=occurred_at,
                maximum_age=timedelta(microseconds=1),
            )
            _atomic_json(anchor_path, anchor.as_dict())
        except AuditWriteBlocked:
            raise
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
            raise AuditWriteBlocked("AUDIT_EVIDENCE_UNAVAILABLE") from error
        finally:
            if journal is not None:
                journal.close()

    def verify_persisted(
        self,
        execution_key: str,
        *,
        now: datetime,
        maximum_age: timedelta,
    ) -> SignedAuditAnchor:
        digest = hashlib.sha256(execution_key.encode("utf-8")).hexdigest()
        journal_path = self.root / (digest + ".sqlite3")
        anchor_path = self.root / (digest + ".anchor.json")
        try:
            value = json.loads(anchor_path.read_text(encoding="utf-8"))
            if not isinstance(value, Mapping):
                raise AuditWriteBlocked("AUDIT_ANCHOR_INVALID")
            anchor = SignedAuditAnchor.from_mapping(value)
            if (
                anchor.run_id != execution_key
                or anchor.policy_version != self.policy_version
            ):
                raise AuditWriteBlocked("AUDIT_ANCHOR_INVALID")
            journal = SQLiteAuditJournal.open(journal_path)
            try:
                journal.verify_signed_anchor(
                    anchor,
                    self.signer,
                    now=now,
                    maximum_age=maximum_age,
                )
            finally:
                journal.close()
            return anchor
        except AuditWriteBlocked:
            raise
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
            raise AuditWriteBlocked("AUDIT_ANCHOR_INVALID") from error


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
    ) -> tuple[str, ...]:
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
    acceptance_cases: tuple[str, ...]
    evidence_paths: tuple[str, ...]
    limitations: tuple[str, ...]

    def as_dict(self) -> Mapping[str, Any]:
        if self.capability not in _REQUIRED_CAPABILITIES:
            raise ValueError("Capability evidence capability is invalid.")
        if self.status not in _CAPABILITY_STATUSES:
            raise ValueError("Capability evidence status is invalid.")
        if self.evidence_type not in _EVIDENCE_TYPES:
            raise ValueError("Capability evidence type is invalid.")
        if (
            not self.capability
            or not self.evidence_type
            or not self.acceptance_cases
            or (self.status != "NOT_TESTED" and not self.evidence_paths)
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


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
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
    _atomic_json(path, value)


def emit_run_capability_evidence(
    run_directory: Path,
    *,
    run_id: str,
    policy_version: str,
    mode: str,
    status: str,
) -> str:
    """Emit the capability contract from an actual bootstrap or OBSERVE run."""

    capabilities = build_run_capability_evidence(mode=mode, status=status)
    name = "capability-evidence.json"
    write_capability_evidence_summary(
        run_directory / name,
        run_id=run_id,
        policy_version=policy_version,
        capabilities=capabilities,
    )
    return name


def build_run_capability_evidence(
    *,
    mode: str,
    status: str,
) -> tuple[CapabilityEvidence, ...]:
    """Describe every normative capability without overclaiming local evidence."""

    exercised = (
        {"SOURCE_INTEGRATION", "INTEGRATED_ANALYTICS", "OPERATIONAL_MODES"}
        if mode == "OBSERVE"
        else {"SAFETY_CORE", "TOOL_CONTRACT"}
    )
    evidence_paths = ("result.json", "report.md", "events.jsonl")
    capabilities = []
    for name in _REQUIRED_CAPABILITIES:
        was_exercised = name in exercised
        limitations = (
            (
                "Локальные evidence типа SIMULATED не заменяют обязательные "
                "REAL_READ_ONLY или CONTROLLED_PILOT."
            )
            if was_exercised
            else "Эта способность не проверялась в данном запуске."
        )
        if status != "SUCCEEDED" and was_exercised:
            limitations = "Локальная проверка способности завершилась неуспешно."
        capabilities.append(
            CapabilityEvidence(
                capability=name,
                status="NOT_PROVEN" if was_exercised else "NOT_TESTED",
                evidence_type="SIMULATED",
                acceptance_cases=_CAPABILITY_ACCEPTANCE_CASES[name],
                evidence_paths=evidence_paths if was_exercised else (),
                limitations=(limitations,),
            )
        )
    return tuple(capabilities)


def capability_report_section(*, mode: str, status: str) -> str:
    """Render every normative capability directly into the human report."""

    lines = ["", "## Способности", ""]
    for item in build_run_capability_evidence(mode=mode, status=status):
        paths = ", ".join(item.evidence_paths) if item.evidence_paths else "нет"
        limitations = " ".join(item.limitations)
        lines.append(
            "- "
            + item.capability
            + ": status="
            + item.status
            + "; evidence_type="
            + item.evidence_type
            + "; evidence_paths="
            + paths
            + "; limitations="
            + limitations
        )
    return "\n".join(lines) + "\n"
