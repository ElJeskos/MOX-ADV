"""Deterministic read-only monitoring for the Gate 0 prototype."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, Tuple

from mox_adv.contracts import IntegratedPerformanceSnapshot
from mox_adv.normalization import IntegratedSnapshotNormalizerV1


class MonitoringRejected(ValueError):
    """A monitoring input or durable state is unsafe to use."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise MonitoringRejected("Monitoring timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class MonitoringRead:
    snapshot: IntegratedPerformanceSnapshot
    previous_snapshot: Optional[IntegratedPerformanceSnapshot] = None
    tracking_failure: bool = False
    known_site_failure: bool = False
    last_applied_write_at: Optional[datetime] = None


class ReadOnlyMonitoringSource(Protocol):
    """A monitoring source whose public boundary exposes reads only."""

    def read(self) -> MonitoringRead: ...


@dataclass(frozen=True)
class MonitoringOutcome:
    status: str
    snapshot_id: Optional[str]
    anomalies: Tuple[Anomaly, ...] = ()
    alerts: Tuple[MonitoringAlert, ...] = ()
    proposals: Tuple[ActiveProposal, ...] = ()
    snapshot_version: Optional[int] = None
    write_blocked: bool = False
    block_reason: Optional[str] = None


@dataclass(frozen=True)
class Anomaly:
    reason_code: str
    observed_value: str
    threshold: str
    financial: bool


@dataclass(frozen=True)
class ActiveProposal:
    proposal_id: str
    snapshot_id: str
    reason_code: str
    created_at: str
    deduplicated: bool


@dataclass(frozen=True)
class MonitoringAlert:
    alert_id: str
    snapshot_id: str
    reason_code: str
    observed_value: str
    threshold: str
    created_at: str


@dataclass(frozen=True)
class SnapshotVersion:
    snapshot_id: str
    version: int
    deduplicated: bool


@dataclass(frozen=True)
class PollClaim:
    token: str
    generation: int


@dataclass(frozen=True)
class WriteWindowDecision:
    allowed: bool
    reason_code: Optional[str]
    blocked_until: Optional[str]


def _decimal(value: object) -> Optional[Decimal]:
    if isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


class Gate0AnomalyPolicy:
    """Evaluate the approved Gate 0 thresholds without rounded comparisons."""

    def __init__(self, policy: Mapping[str, Any]) -> None:
        self.policy = policy
        self.thresholds = policy["monitoring"]["anomaly_thresholds"]
        self.timing = policy["timing"]

    def evaluate(
        self,
        monitoring_read: MonitoringRead,
        now: datetime,
    ) -> Tuple[Anomaly, ...]:
        snapshot = monitoring_read.snapshot
        metrics = snapshot.metrics
        deviations = snapshot.baseline_deviation
        found: list[Anomaly] = []
        self._safety_anomalies(found, monitoring_read, now)
        self._at_or_above(
            found,
            "BUDGET_PRESSURE",
            metrics.get("budget_utilization_percent"),
            self.thresholds["budget_pressure_usage_percent"],
        )
        pacing = _decimal(metrics.get("pacing_percent"))
        pacing_limit = Decimal(100) + Decimal(self.thresholds["pacing_ahead_percent"])
        if pacing is not None and pacing >= pacing_limit:
            found.append(Anomaly("PACING_AHEAD", str(pacing), str(pacing_limit), True))
        high_cpa = _decimal(metrics.get("cpa_rub"))
        high_cpa_limit = Decimal(self.thresholds["high_cpa_rub"])
        if high_cpa is not None and high_cpa > high_cpa_limit:
            found.append(Anomaly("HIGH_CPA", str(high_cpa), str(high_cpa_limit), True))
        self._absolute_at_or_above(
            found,
            "CPC_DEVIATION_FROM_BASELINE",
            deviations.get("cpc_rub"),
            self.thresholds["cpc_deviation_from_baseline_percent"],
        )
        self._absolute_at_or_above(
            found,
            "CTR_DEVIATION_FROM_BASELINE",
            deviations.get("ctr_percent"),
            self.thresholds["ctr_deviation_from_baseline_percent"],
        )
        self._absolute_at_or_above(
            found,
            "CONVERSION_RATE_DEVIATION_FROM_BASELINE",
            deviations.get("conversion_rate_percent"),
            self.thresholds["conversion_rate_deviation_from_baseline_percent"],
        )
        impressions = _decimal(metrics.get("impressions"))
        ctr = _decimal(metrics.get("ctr_percent"))
        minimum_impressions = Decimal(self.thresholds["low_ctr_minimum_impressions"])
        low_ctr = Decimal(self.thresholds["low_ctr_percent"])
        if (
            impressions is not None
            and ctr is not None
            and impressions >= minimum_impressions
            and ctr < low_ctr
        ):
            found.append(Anomaly("LOW_CTR", str(ctr), str(low_ctr), True))

        cutoff = self._late_conversion_cutoff(snapshot)
        if _utc(now) >= cutoff:
            goal_visits = _decimal(metrics.get("goal_visits"))
            cost_micros = _decimal(metrics.get("cost_micros"))
            no_conversion_goal_visits = Decimal(
                self.thresholds["no_conversion_goal_visits"]
            )
            no_conversion_spend_micros = Decimal(
                self.thresholds["no_conversion_spend_rub"]
            ) * Decimal(1_000_000)
            if (
                goal_visits == no_conversion_goal_visits
                and cost_micros is not None
                and cost_micros >= no_conversion_spend_micros
            ):
                found.append(
                    Anomaly(
                        "NO_CONVERSION_SPEND",
                        str(cost_micros),
                        str(no_conversion_spend_micros),
                        True,
                    )
                )
            self._spend_growth_without_conversion(
                found,
                snapshot,
                monitoring_read.previous_snapshot,
            )

        self._goal_cessation(found, snapshot, now)
        self._source_mismatch(found, snapshot)
        return tuple(found)

    def _safety_anomalies(
        self,
        found: list[Anomaly],
        monitoring_read: MonitoringRead,
        now: datetime,
    ) -> None:
        snapshot = monitoring_read.snapshot
        at = _utc(now)
        direct_retrievals = (
            self._parse_utc(snapshot.provenance.direct_report.retrieved_at),
            self._parse_utc(snapshot.provenance.direct_state.retrieved_at),
        )
        metrika_retrieval = self._parse_utc(
            snapshot.provenance.metrika_report.retrieved_at
        )
        direct_age = max(at - item for item in direct_retrievals)
        metrika_age = at - metrika_retrieval
        direct_limit = timedelta(minutes=int(self.timing["direct_freshness_minutes"]))
        metrika_limit = timedelta(hours=int(self.timing["metrika_freshness_hours"]))
        if direct_age > direct_limit:
            found.append(
                Anomaly(
                    "DIRECT_DATA_STALE",
                    str(direct_age.total_seconds()),
                    str(direct_limit.total_seconds()),
                    False,
                )
            )
        if metrika_age > metrika_limit:
            found.append(
                Anomaly(
                    "METRIKA_DATA_STALE",
                    str(metrika_age.total_seconds()),
                    str(metrika_limit.total_seconds()),
                    False,
                )
            )
        watermarks = (
            self._parse_utc(snapshot.provenance.direct_report.watermark),
            self._parse_utc(snapshot.provenance.direct_state.watermark),
            self._parse_utc(snapshot.provenance.metrika_report.watermark),
        )
        skew = max(watermarks) - min(watermarks)
        skew_limit = timedelta(hours=int(self.timing["maximum_watermark_skew_hours"]))
        if skew > skew_limit:
            found.append(
                Anomaly(
                    "WATERMARK_SKEW_EXCEEDED",
                    str(skew.total_seconds()),
                    str(skew_limit.total_seconds()),
                    False,
                )
            )
        if monitoring_read.tracking_failure:
            found.append(Anomaly("TRACKING_FAILURE", "true", "false", False))
        if monitoring_read.known_site_failure:
            found.append(Anomaly("KNOWN_SITE_FAILURE", "true", "false", False))
        if (
            snapshot.last_change.author
            != self.policy["principals"]["owner"]["identity"]
        ):
            found.append(
                Anomaly(
                    "UNKNOWN_EXTERNAL_CHANGE",
                    snapshot.last_change.author,
                    str(self.policy["principals"]["owner"]["identity"]),
                    False,
                )
            )
        if snapshot.comparability_status == "PARTIAL":
            found.append(Anomaly("SNAPSHOT_PARTIAL", "PARTIAL", "COMPARABLE", False))
        elif snapshot.comparability_status == "INCOMPATIBLE":
            found.append(
                Anomaly(
                    "SNAPSHOT_INCOMPATIBLE",
                    "INCOMPATIBLE",
                    "COMPARABLE",
                    False,
                )
            )
        if snapshot.confidence_status == "STALE_DATA":
            found.append(Anomaly("SNAPSHOT_STALE", "STALE_DATA", "READY", False))

    @staticmethod
    def _parse_utc(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise MonitoringRejected("Snapshot timestamp is invalid.") from error
        return _utc(parsed)

    @staticmethod
    def _at_or_above(
        found: list[Anomaly],
        reason_code: str,
        observed: object,
        threshold: object,
    ) -> None:
        value = _decimal(observed)
        limit = Decimal(str(threshold))
        if value is not None and value >= limit:
            found.append(Anomaly(reason_code, str(value), str(limit), True))

    @staticmethod
    def _absolute_at_or_above(
        found: list[Anomaly],
        reason_code: str,
        observed: object,
        threshold: object,
    ) -> None:
        value = _decimal(observed)
        limit = Decimal(str(threshold))
        if value is not None and abs(value) >= limit:
            found.append(Anomaly(reason_code, str(value), str(limit), True))

    def _late_conversion_cutoff(
        self,
        snapshot: IntegratedPerformanceSnapshot,
    ) -> datetime:
        try:
            period_end = date.fromisoformat(snapshot.period_end)
        except ValueError as error:
            raise MonitoringRejected("Snapshot period_end is invalid.") from error
        closed_at = datetime.combine(
            period_end + timedelta(days=1),
            time.min,
            tzinfo=timezone.utc,
        )
        return closed_at + timedelta(
            hours=int(self.timing["late_conversion_cutoff_hours"])
        )

    def _spend_growth_without_conversion(
        self,
        found: list[Anomaly],
        snapshot: IntegratedPerformanceSnapshot,
        previous: Optional[IntegratedPerformanceSnapshot],
    ) -> None:
        if previous is None:
            return
        current_spend = _decimal(snapshot.metrics.get("cost_micros"))
        previous_spend = _decimal(previous.metrics.get("cost_micros"))
        current_conversions = _decimal(snapshot.metrics.get("goal_visits"))
        previous_conversions = _decimal(previous.metrics.get("goal_visits"))
        if None in (
            current_spend,
            previous_spend,
            current_conversions,
            previous_conversions,
        ):
            return
        assert current_spend is not None
        assert previous_spend is not None
        assert current_conversions is not None
        assert previous_conversions is not None
        growth = current_spend - previous_spend
        threshold = Decimal(
            self.thresholds["spend_growth_without_conversion_rub"]
        ) * Decimal(1_000_000)
        if growth >= threshold and current_conversions <= previous_conversions:
            found.append(
                Anomaly(
                    "SPEND_GROWTH_WITHOUT_CONVERSION",
                    str(growth),
                    str(threshold),
                    True,
                )
            )

    def _goal_cessation(
        self,
        found: list[Anomaly],
        snapshot: IntegratedPerformanceSnapshot,
        now: datetime,
    ) -> None:
        if not snapshot.records:
            return
        latest_date = max(
            date.fromisoformat(record.date) for record in snapshot.records
        )
        latest = [
            record
            for record in snapshot.records
            if record.date == latest_date.isoformat()
        ]
        visits = sum(record.visits for record in latest)
        goal_visits = sum(record.goal_visits for record in latest)
        ceased_at = datetime.combine(
            latest_date + timedelta(days=1),
            time.min,
            tzinfo=timezone.utc,
        )
        required_age = timedelta(hours=int(self.thresholds["goal_cessation_hours"]))
        if (
            _utc(now) - ceased_at >= required_age
            and visits >= int(self.thresholds["goal_cessation_minimum_visits"])
            and goal_visits == 0
        ):
            found.append(
                Anomaly(
                    "GOAL_CESSATION",
                    str(visits),
                    str(self.thresholds["goal_cessation_minimum_visits"]),
                    True,
                )
            )

    def _source_mismatch(
        self,
        found: list[Anomaly],
        snapshot: IntegratedPerformanceSnapshot,
    ) -> None:
        clicks = _decimal(snapshot.metrics.get("clicks"))
        visits = _decimal(snapshot.metrics.get("visits"))
        if clicks is None or visits is None or clicks == 0:
            return
        mismatch = abs(clicks - visits) / clicks * Decimal(100)
        threshold = Decimal(self.thresholds["source_mismatch_percent"])
        if mismatch >= threshold:
            found.append(
                Anomaly(
                    "SOURCE_MISMATCH",
                    str(mismatch),
                    str(threshold),
                    False,
                )
            )


class MonitoringStore:
    """Durable scheduler state stored locally without an external write path."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS scheduler_state ("
                "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
                "last_completed_at TEXT, "
                "claim_token TEXT, "
                "claim_started_at TEXT, "
                "claim_generation INTEGER NOT NULL DEFAULT 0, "
                "lease_expires_at TEXT)"
            )
            columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(scheduler_state)"
                ).fetchall()
            }
            if "claim_generation" not in columns:
                connection.execute(
                    "ALTER TABLE scheduler_state "
                    "ADD COLUMN claim_generation INTEGER NOT NULL DEFAULT 0"
                )
            if "lease_expires_at" not in columns:
                connection.execute(
                    "ALTER TABLE scheduler_state ADD COLUMN lease_expires_at TEXT"
                )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS snapshot_versions ("
                "snapshot_id TEXT PRIMARY KEY, "
                "series_key TEXT NOT NULL, "
                "version INTEGER NOT NULL, "
                "canonical_bytes BLOB NOT NULL, "
                "UNIQUE(series_key, version))"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS active_proposals ("
                "proposal_id TEXT PRIMARY KEY, "
                "snapshot_id TEXT NOT NULL, "
                "reason_code TEXT NOT NULL, "
                "created_at TEXT NOT NULL, "
                "active INTEGER NOT NULL CHECK (active IN (0, 1)))"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "one_active_proposal_per_snapshot_reason "
                "ON active_proposals(snapshot_id, reason_code) WHERE active = 1"
            )

    def claim_poll(
        self,
        now: datetime,
        interval: timedelta,
        lease_timeout: timedelta,
    ) -> Optional[PollClaim]:
        timestamp = _utc(now)
        claim_token = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT last_completed_at, claim_token, claim_generation, "
                "lease_expires_at "
                "FROM scheduler_state WHERE singleton = 1"
            ).fetchone()
            if row is not None:
                if row[1] is not None and row[3] is not None:
                    lease_expires_at = datetime.fromisoformat(str(row[3]))
                    if timestamp < _utc(lease_expires_at):
                        return None
                if row[0] is not None:
                    last_completed_at = datetime.fromisoformat(str(row[0]))
                    if timestamp - _utc(last_completed_at) < interval:
                        return None
                generation = int(row[2]) + 1
                connection.execute(
                    "UPDATE scheduler_state SET claim_token = ?, "
                    "claim_started_at = ?, claim_generation = ?, "
                    "lease_expires_at = ? WHERE singleton = 1",
                    (
                        claim_token,
                        timestamp.isoformat(),
                        generation,
                        (timestamp + lease_timeout).isoformat(),
                    ),
                )
            else:
                generation = 1
                connection.execute(
                    "INSERT INTO scheduler_state("
                    "singleton, last_completed_at, claim_token, claim_started_at, "
                    "claim_generation, lease_expires_at"
                    ") VALUES (1, NULL, ?, ?, ?, ?)",
                    (
                        claim_token,
                        timestamp.isoformat(),
                        generation,
                        (timestamp + lease_timeout).isoformat(),
                    ),
                )
        return PollClaim(claim_token, generation)

    def heartbeat_poll(
        self,
        claim: PollClaim,
        now: datetime,
        lease_timeout: timedelta,
    ) -> None:
        timestamp = _utc(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE scheduler_state SET lease_expires_at = ? "
                "WHERE singleton = 1 AND claim_token = ? "
                "AND claim_generation = ? AND lease_expires_at > ?",
                (
                    (timestamp + lease_timeout).isoformat(),
                    claim.token,
                    claim.generation,
                    timestamp.isoformat(),
                ),
            )
            if changed.rowcount != 1:
                raise MonitoringRejected("Scheduler poll claim was lost.")

    def release_poll(self, claim: PollClaim) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE scheduler_state SET claim_token = NULL, "
                "claim_started_at = NULL, lease_expires_at = NULL "
                "WHERE singleton = 1 AND claim_token = ? "
                "AND claim_generation = ?",
                (claim.token, claim.generation),
            )

    def persist_poll(
        self,
        claim: PollClaim,
        snapshot: IntegratedPerformanceSnapshot,
        proposal_reason_codes: Tuple[str, ...],
        completed_at: datetime,
    ) -> Tuple[SnapshotVersion, Tuple[ActiveProposal, ...]]:
        timestamp = _utc(completed_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_claim(connection, claim, timestamp)
            snapshot_version = self._save_snapshot(connection, snapshot)
            proposals = tuple(
                self._active_proposal(
                    connection,
                    snapshot.snapshot_id,
                    reason_code,
                    timestamp,
                )
                for reason_code in proposal_reason_codes
            )
            changed = connection.execute(
                "UPDATE scheduler_state SET last_completed_at = ?, "
                "claim_token = NULL, claim_started_at = NULL, "
                "lease_expires_at = NULL "
                "WHERE singleton = 1 AND claim_token = ? "
                "AND claim_generation = ?",
                (timestamp.isoformat(), claim.token, claim.generation),
            )
            if changed.rowcount != 1:
                raise MonitoringRejected("Scheduler poll claim was lost.")
        return snapshot_version, proposals

    @staticmethod
    def _save_snapshot(
        connection: sqlite3.Connection,
        snapshot: IntegratedPerformanceSnapshot,
    ) -> SnapshotVersion:
        canonical_bytes = json.dumps(
            snapshot.as_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        series_identity = {
            "scope": {
                "organization": snapshot.scope.organization,
                "connection": snapshot.scope.connection,
                "account": snapshot.scope.account,
                "campaign": snapshot.scope.campaign,
                "counter": snapshot.scope.counter,
                "goal": snapshot.scope.goal,
            },
            "period_start": snapshot.period_start,
            "period_end": snapshot.period_end,
            "timezone": snapshot.timezone,
            "attribution": {
                "direct": snapshot.attribution.direct,
                "metrika": snapshot.attribution.metrika,
            },
            "policy_version": snapshot.policy_version,
        }
        series_key = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    series_identity,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
        )
        existing = connection.execute(
            "SELECT version, canonical_bytes FROM snapshot_versions "
            "WHERE snapshot_id = ?",
            (snapshot.snapshot_id,),
        ).fetchone()
        if existing is not None:
            if bytes(existing[1]) != canonical_bytes:
                raise MonitoringRejected(
                    "An immutable snapshot ID contains different bytes."
                )
            return SnapshotVersion(
                snapshot.snapshot_id,
                int(existing[0]),
                True,
            )
        row = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM snapshot_versions "
            "WHERE series_key = ?",
            (series_key,),
        ).fetchone()
        version = int(row[0]) + 1
        connection.execute(
            "INSERT INTO snapshot_versions("
            "snapshot_id, series_key, version, canonical_bytes"
            ") VALUES (?, ?, ?, ?)",
            (snapshot.snapshot_id, series_key, version, canonical_bytes),
        )
        return SnapshotVersion(snapshot.snapshot_id, version, False)

    def load_snapshot_bytes(self, snapshot_id: str) -> bytes:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT canonical_bytes FROM snapshot_versions WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            raise MonitoringRejected("Snapshot is not stored.")
        return bytes(row[0])

    @staticmethod
    def _active_proposal(
        connection: sqlite3.Connection,
        snapshot_id: str,
        reason_code: str,
        created_at: datetime,
    ) -> ActiveProposal:
        timestamp = _utc(created_at).isoformat()
        proposal_id = (
            "monitoring-proposal-"
            + hashlib.sha256(
                (snapshot_id + "\x00" + reason_code).encode("utf-8")
            ).hexdigest()[:24]
        )
        existing = connection.execute(
            "SELECT proposal_id, created_at FROM active_proposals "
            "WHERE snapshot_id = ? AND reason_code = ? AND active = 1",
            (snapshot_id, reason_code),
        ).fetchone()
        if existing is not None:
            return ActiveProposal(
                proposal_id=str(existing[0]),
                snapshot_id=snapshot_id,
                reason_code=reason_code,
                created_at=str(existing[1]),
                deduplicated=True,
            )
        connection.execute(
            "INSERT INTO active_proposals("
            "proposal_id, snapshot_id, reason_code, created_at, active"
            ") VALUES (?, ?, ?, ?, 1)",
            (proposal_id, snapshot_id, reason_code, timestamp),
        )
        return ActiveProposal(
            proposal_id=proposal_id,
            snapshot_id=snapshot_id,
            reason_code=reason_code,
            created_at=timestamp,
            deduplicated=False,
        )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path), isolation_level=None)

    @staticmethod
    def _require_claim(
        connection: sqlite3.Connection,
        claim: PollClaim,
        now: datetime,
    ) -> None:
        row = connection.execute(
            "SELECT 1 FROM scheduler_state WHERE singleton = 1 "
            "AND claim_token = ? AND claim_generation = ? "
            "AND lease_expires_at > ?",
            (claim.token, claim.generation, _utc(now).isoformat()),
        ).fetchone()
        if row is None:
            raise MonitoringRejected("Scheduler poll claim was lost.")


class DurableWriteWindowGate:
    """Serialize write attempts and enforce the durable Gate 0 quiet window."""

    def __init__(self, path: Path, policy: Mapping[str, Any]) -> None:
        self.path = path
        self.window = timedelta(
            hours=max(
                int(policy["timing"]["cooldown_hours"]),
                int(policy["timing"]["observation_window_hours"]),
            )
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def reserve(self, execution_key: str, now: datetime) -> WriteWindowDecision:
        if not execution_key:
            raise MonitoringRejected("Write-window execution key is required.")
        timestamp = _utc(now)
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT execution_key, status, active_until "
                "FROM write_window_gate WHERE singleton = 1"
            ).fetchone()
            if row is not None:
                if str(row[1]) == "IN_PROGRESS":
                    return WriteWindowDecision(
                        False,
                        "WRITE_WINDOW_IN_PROGRESS",
                        None,
                    )
                active_until = datetime.fromisoformat(str(row[2]))
                if timestamp < _utc(active_until):
                    return WriteWindowDecision(
                        False,
                        "COOLDOWN_AND_OBSERVATION_ACTIVE",
                        _utc(active_until).isoformat(),
                    )
            connection.execute(
                "INSERT INTO write_window_gate("
                "singleton, execution_key, status, reserved_at, active_until"
                ") VALUES (1, ?, 'IN_PROGRESS', ?, NULL) "
                "ON CONFLICT(singleton) DO UPDATE SET "
                "execution_key = excluded.execution_key, "
                "status = excluded.status, reserved_at = excluded.reserved_at, "
                "active_until = NULL",
                (execution_key, timestamp.isoformat()),
            )
        return WriteWindowDecision(True, None, None)

    def activate(self, execution_key: str, applied_at: datetime) -> None:
        timestamp = _utc(applied_at)
        with self._connect() as connection:
            self._ensure_schema(connection)
            changed = connection.execute(
                "UPDATE write_window_gate SET status = 'ACTIVE', "
                "active_until = ? WHERE singleton = 1 "
                "AND execution_key = ? AND status = 'IN_PROGRESS'",
                ((timestamp + self.window).isoformat(), execution_key),
            )
            if changed.rowcount != 1:
                raise MonitoringRejected(
                    "Write-window reservation cannot be activated."
                )

    def release(self, execution_key: str) -> None:
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute(
                "DELETE FROM write_window_gate WHERE singleton = 1 "
                "AND execution_key = ? AND status = 'IN_PROGRESS'",
                (execution_key,),
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path), isolation_level=None)

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS write_window_gate ("
            "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
            "execution_key TEXT NOT NULL, "
            "status TEXT NOT NULL "
            "CHECK (status IN ('IN_PROGRESS', 'ACTIVE')), "
            "reserved_at TEXT NOT NULL, "
            "active_until TEXT)"
        )


class MonitoringScheduler:
    """Run one due read-only poll through a clock-controlled public seam."""

    def __init__(
        self,
        policy: Mapping[str, Any],
        source: ReadOnlyMonitoringSource,
        store: MonitoringStore,
        clock: Callable[[], datetime],
        lease_timeout: timedelta = timedelta(minutes=5),
    ) -> None:
        self.policy = policy
        self.source = source
        self.store = store
        self.clock = clock
        self.lease_timeout = lease_timeout
        self.anomaly_policy = Gate0AnomalyPolicy(policy)

    def poll(self) -> MonitoringOutcome:
        now = _utc(self.clock())
        interval = timedelta(minutes=int(self.policy["monitoring"]["poll_minutes"]))
        claim = self.store.claim_poll(now, interval, self.lease_timeout)
        if claim is None:
            return MonitoringOutcome(status="NOT_DUE", snapshot_id=None)
        try:
            monitoring_read = self.source.read()
            self.store.heartbeat_poll(claim, _utc(self.clock()), self.lease_timeout)
            snapshot = monitoring_read.snapshot
            if snapshot.policy_version != self.policy["policy_id"]:
                raise MonitoringRejected(
                    "Snapshot policy version does not match Gate 0."
                )
            if not IntegratedSnapshotNormalizerV1.verify_fingerprint(
                snapshot.as_dict()
            ):
                raise MonitoringRejected("Snapshot fingerprint is invalid.")
            self.store.heartbeat_poll(claim, _utc(self.clock()), self.lease_timeout)
            anomalies = self.anomaly_policy.evaluate(monitoring_read, now)
            write_blocked, block_reason = self._write_window(
                monitoring_read.last_applied_write_at,
                now,
            )
            safe_for_financial_proposal = (
                snapshot.comparability_status == "COMPARABLE"
                and snapshot.confidence_status == "READY"
                and snapshot.financial_recommendations_allowed
                and not any(not anomaly.financial for anomaly in anomalies)
                and not write_blocked
            )
            proposal_reason_codes = (
                tuple(anomaly.reason_code for anomaly in anomalies if anomaly.financial)
                if safe_for_financial_proposal
                else ()
            )
            self.store.heartbeat_poll(claim, _utc(self.clock()), self.lease_timeout)
            alerts = tuple(
                MonitoringAlert(
                    alert_id="monitoring-alert-"
                    + hashlib.sha256(
                        (snapshot.snapshot_id + "\x00" + anomaly.reason_code).encode(
                            "utf-8"
                        )
                    ).hexdigest()[:24],
                    snapshot_id=snapshot.snapshot_id,
                    reason_code=anomaly.reason_code,
                    observed_value=anomaly.observed_value,
                    threshold=anomaly.threshold,
                    created_at=now.isoformat(),
                )
                for anomaly in anomalies
            )
            snapshot_version, proposals = self.store.persist_poll(
                claim,
                snapshot,
                proposal_reason_codes,
                _utc(self.clock()),
            )
            outcome = MonitoringOutcome(
                status="POLLED",
                snapshot_id=snapshot.snapshot_id,
                anomalies=anomalies,
                alerts=alerts,
                proposals=proposals,
                snapshot_version=snapshot_version.version,
                write_blocked=write_blocked,
                block_reason=block_reason,
            )
            return outcome
        except BaseException:
            self.store.release_poll(claim)
            raise

    def _write_window(
        self,
        last_applied_write_at: Optional[datetime],
        now: datetime,
    ) -> Tuple[bool, Optional[str]]:
        if last_applied_write_at is None:
            return False, None
        elapsed = _utc(now) - _utc(last_applied_write_at)
        cooldown = timedelta(hours=int(self.policy["timing"]["cooldown_hours"]))
        observation = timedelta(
            hours=int(self.policy["timing"]["observation_window_hours"])
        )
        cooldown_active = elapsed < cooldown
        observation_active = elapsed < observation
        if cooldown_active and observation_active:
            return True, "COOLDOWN_AND_OBSERVATION_ACTIVE"
        if cooldown_active:
            return True, "COOLDOWN_ACTIVE"
        if observation_active:
            return True, "OBSERVATION_WINDOW_ACTIVE"
        return False, None
