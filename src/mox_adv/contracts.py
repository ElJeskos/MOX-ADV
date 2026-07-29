"""Typed contracts shared by the versioned internal API."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Dict, Literal, Mapping, Optional, Protocol, Sequence, Tuple

ARTIFACT_SCHEMA_VERSION = "run-artifacts-v1"
INTERNAL_API_VERSION = "internal-api-v1"
FIXTURE_SCHEMA_VERSION = "safe-bootstrap-fixture-v1"
ANALYTICS_FIXTURE_SCHEMA_VERSION = "integrated-analytics-fixture-v1"
INTEGRATED_SNAPSHOT_SCHEMA_VERSION = "integrated-performance-snapshot-v1"

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
ComparabilityStatus = Literal["COMPARABLE", "PARTIAL", "INCOMPATIBLE"]
ConfidenceStatus = Literal["READY", "INSUFFICIENT_DATA", "STALE_DATA"]


@dataclass(frozen=True)
class VersionedReadRequest:
    system: str
    host: str
    path: str
    version: str
    service: str
    method: str
    http_verb: str
    payload: Mapping[str, Any]


class ReadOnlyTransport(Protocol):
    """A transport with no write-capable operation in its interface."""

    def read(self, request: VersionedReadRequest) -> Any: ...


@dataclass(frozen=True)
class DirectReportsReadQuery:
    account: str
    campaign: str
    period_start: str
    period_end: str
    attribution: str


@dataclass(frozen=True)
class DirectCampaignStateReadQuery:
    account: str
    campaign: str


@dataclass(frozen=True)
class MetrikaReportReadQuery:
    counter: str
    campaign: str
    goal: str
    period_start: str
    period_end: str
    attribution: str


@dataclass(frozen=True)
class DirectReportRow:
    campaign: str
    date: str
    impressions: int
    clicks: int
    cost_micros: int


@dataclass(frozen=True)
class DirectReportBlock:
    source: str
    retrieved_at: str
    watermark: str
    period_start: str
    period_end: str
    timezone: str
    attribution: str
    currency: str
    rows: Tuple[DirectReportRow, ...]


@dataclass(frozen=True)
class DirectCampaignStateBlock:
    source: str
    retrieved_at: str
    watermark: str
    campaign: str
    campaign_state: str
    group_state: str
    ad_state: str
    strategy: str
    current_weekly_budget_micros: int
    budget_period_start: str
    budget_period_end: str
    current_search_bid_micros: int
    ad_variant: str
    object_config_version: str
    last_change_author: str
    last_change_occurred_at: str


@dataclass(frozen=True)
class MetrikaReportRow:
    campaign: str
    goal: str
    date: str
    visits: int
    goal_visits: int


@dataclass(frozen=True)
class MetrikaReportBlock:
    source: str
    retrieved_at: str
    watermark: str
    period_start: str
    period_end: str
    timezone: str
    attribution: str
    rows: Tuple[MetrikaReportRow, ...]


@dataclass(frozen=True)
class BaselineAggregate:
    source_campaign: str
    impressions: int
    clicks: int
    cost_micros: int
    visits: int
    goal_visits: int


@dataclass(frozen=True)
class AnalyticsScope:
    organization: str
    connection: str
    account: str
    campaign: str
    counter: str
    goal: str


@dataclass(frozen=True)
class AnalyticsPeriod:
    period_start: str
    period_end: str


@dataclass(frozen=True)
class ConnectedAnalytics:
    observation_id: str
    generated_at: str
    scope: AnalyticsScope
    requested_period: AnalyticsPeriod
    direct_report: DirectReportBlock
    direct_state: DirectCampaignStateBlock
    metrika_report: MetrikaReportBlock
    baseline: Optional[BaselineAggregate]


@dataclass(frozen=True)
class TrustedAnalyticsScope:
    organization: str
    connection: str
    account: str
    campaign: str
    counter: str
    goal: str
    baseline_campaign: Optional[str] = None


@dataclass(frozen=True)
class SnapshotAttribution:
    direct: str
    metrika: str


@dataclass(frozen=True)
class ProvenanceEntry:
    source: str
    retrieved_at: str
    watermark: str


@dataclass(frozen=True)
class SnapshotProvenance:
    direct_report: ProvenanceEntry
    direct_state: ProvenanceEntry
    metrika_report: ProvenanceEntry


@dataclass(frozen=True)
class IntegratedGrainRecord:
    campaign: str
    goal: str
    date: str
    impressions: int
    clicks: int
    cost_micros: int
    visits: int
    goal_visits: int
    leads: Optional[int]


@dataclass(frozen=True)
class CampaignObservation:
    state: str
    group_state: str
    ad_state: str
    strategy: str
    current_weekly_budget_micros: int
    budget_period_start: str
    budget_period_end: str
    current_search_bid_micros: int
    current_ad_variant: str
    object_config_version: str


@dataclass(frozen=True)
class LastChangeObservation:
    author: str
    occurred_at: str


@dataclass(frozen=True)
class BusinessGoal:
    event: str
    meaning: str


@dataclass(frozen=True)
class TargetKPI:
    name: str
    target_maximum: int


@dataclass(frozen=True)
class IntegratedSnapshotDraft:
    schema_version: str
    policy_version: str
    observation_id: str
    generated_at: str
    scope: AnalyticsScope
    period_start: str
    period_end: str
    timezone: str
    attribution: SnapshotAttribution
    provenance: SnapshotProvenance
    grain_records: Tuple[IntegratedGrainRecord, ...]
    campaign: CampaignObservation
    last_change: LastChangeObservation
    business_goal: BusinessGoal
    target_kpi: TargetKPI
    baseline: Optional[BaselineAggregate]
    comparability_status: ComparabilityStatus
    confidence_status: ConfidenceStatus
    data_quality_gaps: Tuple[str, ...]
    financial_recommendations_allowed: bool


@dataclass(frozen=True)
class IntegratedPerformanceSnapshot:
    snapshot_id: str
    schema_version: str
    policy_version: str
    observation_id: str
    generated_at: str
    scope: AnalyticsScope
    period_start: str
    period_end: str
    timezone: str
    attribution: SnapshotAttribution
    grain: str
    provenance: SnapshotProvenance
    records: Tuple[IntegratedGrainRecord, ...]
    currency: str
    metrics: Mapping[str, Any]
    display_metrics: Mapping[str, str]
    baseline_deviation: Mapping[str, Any]
    campaign: CampaignObservation
    last_change: LastChangeObservation
    business_goal: BusinessGoal
    target_kpi: TargetKPI
    data_quality_gaps: Tuple[str, ...]
    comparability_status: ComparabilityStatus
    confidence_status: ConfidenceStatus
    financial_recommendations_allowed: bool

    def as_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["data_quality_gaps"] = list(self.data_quality_gaps)
        return value


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
    capability_evidence_path: str
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
            "capability_evidence_path": self.capability_evidence_path,
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
