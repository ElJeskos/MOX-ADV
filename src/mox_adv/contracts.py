"""Typed contracts shared by the versioned internal API."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Dict, Literal, Mapping, Optional, Sequence, Tuple


ARTIFACT_SCHEMA_VERSION = "run-artifacts-v1"
INTERNAL_API_VERSION = "internal-api-v1"
FIXTURE_SCHEMA_VERSION = "safe-bootstrap-fixture-v1"

RunMode = Literal["SIMULATION"]
EvidenceType = Literal["SIMULATED"]
RunStatus = Literal["SUCCEEDED", "REJECTED", "FAILED"]
ExecutionStatus = Literal[
    "NOT_STARTED",
    "IN_FLIGHT",
    "APPLIED",
    "NO_CHANGE",
    "BLOCKED",
    "ALREADY_PROCESSED",
    "UNKNOWN_RESULT",
    "FAILED",
    "PARTIALLY_APPLIED",
    "COMPENSATION_REQUIRED",
]
SafeAction = Literal["KEEP", "REQUEST_HUMAN_HELP"]


@dataclass(frozen=True)
class RunContext:
    run_id: str
    schema_version: str
    policy_version: str
    mode: RunMode
    evidence_type: EvidenceType
    source: str
    started_at: str


@dataclass(frozen=True)
class RunError:
    code: str
    message: str
    stage: str
    retryable: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FixtureRecord:
    impressions: int
    clicks: int
    conversions: int
    cost_rub: Decimal


@dataclass(frozen=True)
class ConnectedFixture:
    fixture_id: str
    records: Tuple[FixtureRecord, ...]


@dataclass(frozen=True)
class NormalizedSnapshot:
    snapshot_id: str
    fixture_id: str
    records: Tuple[FixtureRecord, ...]


@dataclass(frozen=True)
class AnalyticsSummary:
    snapshot_id: str
    impressions: int
    clicks: int
    conversions: int
    cost_rub: Decimal
    ctr: Decimal


@dataclass(frozen=True)
class Decision:
    action: SafeAction
    reason_code: str


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason_code: str
    external_write_egress: bool


@dataclass(frozen=True)
class ExecutionResult:
    execution_status: ExecutionStatus
    external_write_sent: bool
    technical_command: str


@dataclass(frozen=True)
class PersistedEvent:
    sequence: int
    run_id: str
    schema_version: str
    policy_version: str
    occurred_at: str
    event_type: str
    payload: Mapping[str, Any]
    previous_hash: str
    event_hash: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "sequence": self.sequence,
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "occurred_at": self.occurred_at,
            "event_type": self.event_type,
            "payload": dict(self.payload),
            "previous_hash": self.previous_hash,
            "event_hash": self.event_hash,
        }


@dataclass(frozen=True)
class AuditVerification:
    final_sequence: int
    final_hash: str


@dataclass(frozen=True)
class RunResult:
    schema_version: str
    policy_version: str
    internal_api_version: str
    run_id: str
    source: str
    evidence_type: EvidenceType
    mode: RunMode
    status: RunStatus
    execution_status: ExecutionStatus
    external_write_sent: bool
    snapshot_id: Optional[str]
    started_at: str
    finished_at: str
    duration_ms: int
    stages: Sequence[str]
    technical_command: Optional[str]
    error: Optional[RunError]
    audit: AuditVerification

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "internal_api_version": self.internal_api_version,
            "run_id": self.run_id,
            "source": self.source,
            "evidence_type": self.evidence_type,
            "mode": self.mode,
            "status": self.status,
            "execution_status": self.execution_status,
            "external_write_sent": self.external_write_sent,
            "snapshot_id": self.snapshot_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "stages": list(self.stages),
            "technical_command": self.technical_command,
            "provider": None,
            "model_id": None,
            "tokens": 0,
            "cost_rub": "0",
            "stage_durations_ms": {},
            "error": None if self.error is None else self.error.as_dict(),
            "audit": {
                "algorithm": "SHA-256",
                "final_sequence": self.audit.final_sequence,
                "final_hash": self.audit.final_hash,
            },
        }


@dataclass(frozen=True)
class RunOutcome:
    exit_code: int
    run_id: str
    status: RunStatus
    run_directory: Optional[str]
    error_code: Optional[str] = None
