"""Observed post-change impact evaluation without causal overclaiming."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_DECISIONS = (
    "KEEP_CHANGE",
    "ROLLBACK_CHANGE",
    "ADJUST_CHANGE",
    "ESCALATE_TO_HUMAN",
)


class ImpactRejected(ValueError):
    """Impact evidence cannot safely support an observed decision."""


def _closed(
    value: Mapping[str, Any],
    fields: tuple[str, ...],
    label: str,
) -> None:
    if not isinstance(value, Mapping) or set(value) != set(fields):
        raise ImpactRejected(label + " must use the closed impact contract.")


def _utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ImpactRejected(label + " must be an ISO timestamp.") from error
    if parsed.tzinfo is None:
        raise ImpactRejected(label + " must be timezone-aware.")
    return parsed.astimezone(timezone.utc)


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool):
        raise ImpactRejected(label + " must be numeric.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ImpactRejected(label + " must be numeric.") from error
    if not parsed.is_finite() or parsed < 0:
        raise ImpactRejected(label + " must be finite and non-negative.")
    return parsed


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal(1)))
    return format(normalized, "f")


@dataclass(frozen=True)
class ImpactObservation:
    snapshot_id: str
    campaign: str
    period_start: str
    period_end: str
    watermarks: Mapping[str, str]
    metrics: Mapping[str, int]
    comparability_status: str
    confidence_status: str

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        label: str,
    ) -> ImpactObservation:
        _closed(
            value,
            (
                "snapshot_id",
                "campaign",
                "period_start",
                "period_end",
                "watermarks",
                "metrics",
                "comparability_status",
                "confidence_status",
            ),
            label,
        )
        snapshot_id = value["snapshot_id"]
        if not isinstance(snapshot_id, str) or _SHA256.fullmatch(snapshot_id) is None:
            raise ImpactRejected(label + " snapshot_id is invalid.")
        campaign = value["campaign"]
        if not isinstance(campaign, str) or not campaign:
            raise ImpactRejected(label + " campaign is invalid.")
        try:
            period_start = date.fromisoformat(str(value["period_start"]))
            period_end = date.fromisoformat(str(value["period_end"]))
        except ValueError as error:
            raise ImpactRejected(label + " period is invalid.") from error
        if period_end < period_start:
            raise ImpactRejected(label + " period is invalid.")
        watermarks = value["watermarks"]
        _closed(
            watermarks,
            ("direct_report", "direct_state", "metrika_report"),
            label + " watermarks",
        )
        checked_watermarks = {}
        for name, watermark in watermarks.items():
            if not isinstance(watermark, str):
                raise ImpactRejected(label + " watermark is invalid.")
            _utc(watermark, label + " watermark")
            checked_watermarks[name] = watermark
        metrics = value["metrics"]
        _closed(
            metrics,
            ("impressions", "clicks", "cost_micros", "visits", "goal_visits"),
            label + " metrics",
        )
        checked_metrics: dict[str, int] = {}
        for name, metric in metrics.items():
            if isinstance(metric, bool) or not isinstance(metric, int) or metric < 0:
                raise ImpactRejected(label + " metric is invalid.")
            checked_metrics[name] = metric
        if (
            checked_metrics["clicks"] > checked_metrics["impressions"]
            or checked_metrics["goal_visits"] > checked_metrics["visits"]
        ):
            raise ImpactRejected(label + " metric relationships are invalid.")
        comparability = value["comparability_status"]
        confidence = value["confidence_status"]
        if comparability not in {"COMPARABLE", "PARTIAL", "INCOMPATIBLE"}:
            raise ImpactRejected(label + " comparability is invalid.")
        if confidence not in {"READY", "INSUFFICIENT_DATA", "STALE_DATA"}:
            raise ImpactRejected(label + " confidence is invalid.")
        return cls(
            snapshot_id=snapshot_id,
            campaign=campaign,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            watermarks=checked_watermarks,
            metrics=checked_metrics,
            comparability_status=str(comparability),
            confidence_status=str(confidence),
        )

    def cpa_rub(self) -> Decimal:
        conversions = self.metrics["goal_visits"]
        if conversions == 0:
            raise ImpactRejected("Impact CPA is NOT_APPLICABLE.")
        return (
            Decimal(self.metrics["cost_micros"])
            / Decimal(conversions)
            / Decimal(1_000_000)
        )


@dataclass(frozen=True)
class ImpactEvaluationRequest:
    fixture_name: str
    run_id: str
    change_id: str
    policy_version: str
    change_applied_at: str
    evaluated_at: str
    baseline: ImpactObservation
    post_change: ImpactObservation
    seasonality: str
    known_interventions: tuple[str, ...]
    confounders: tuple[str, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class ImpactReport:
    schema_version: str
    policy_version: str
    run_id: str
    change_id: str
    fixture_name: str
    status: str
    effect_classification: str
    baseline: Mapping[str, Any]
    post_change: Mapping[str, Any]
    watermarks: Mapping[str, Any]
    delayed_conversion_cutoff_hours: int
    observation_window_hours: int
    seasonality: str
    known_interventions: tuple[str, ...]
    confounders: tuple[str, ...]
    metric_changes: Mapping[str, Any]
    confidence: str
    evidence: tuple[str, ...]
    next_decision: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "run_id": self.run_id,
            "change_id": self.change_id,
            "fixture_name": self.fixture_name,
            "status": self.status,
            "effect_classification": self.effect_classification,
            "baseline": dict(self.baseline),
            "post_change": dict(self.post_change),
            "watermarks": dict(self.watermarks),
            "delayed_conversion_cutoff_hours": (self.delayed_conversion_cutoff_hours),
            "observation_window_hours": self.observation_window_hours,
            "seasonality": self.seasonality,
            "known_interventions": list(self.known_interventions),
            "confounders": list(self.confounders),
            "metric_changes": dict(self.metric_changes),
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "next_decision": self.next_decision,
        }


@dataclass(frozen=True)
class StoredImpactReport:
    canonical_hash: str
    deduplicated: bool


def load_impact_fixture(
    path: Path,
    policy: Mapping[str, Any],
) -> ImpactEvaluationRequest:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ImpactRejected("Impact fixture cannot be loaded.") from error
    _closed(
        value,
        (
            "fixture_name",
            "run_id",
            "change_id",
            "policy_version",
            "change_applied_at",
            "evaluated_at",
            "baseline",
            "post_change",
            "seasonality",
            "known_interventions",
            "confounders",
            "evidence",
        ),
        "Impact fixture",
    )
    fixture_contracts = policy["impact"].get("decision_fixtures")
    if fixture_contracts is None:
        allowed_names = {str(policy["impact"]["fixture"]["name"])}
    elif isinstance(fixture_contracts, list):
        allowed_names = {
            str(item["name"])
            for item in fixture_contracts
            if isinstance(item, Mapping) and "name" in item
        }
    else:
        raise ImpactRejected("Impact decision fixture contract is invalid.")
    if value["fixture_name"] not in allowed_names:
        raise ImpactRejected("Impact fixture name does not match Gate 0.")
    if value["policy_version"] != policy["policy_id"]:
        raise ImpactRejected("Impact fixture policy version does not match Gate 0.")
    tuple_fields = {}
    for name in ("known_interventions", "confounders", "evidence"):
        items = value[name]
        if not isinstance(items, list) or any(
            not isinstance(item, str) or not item for item in items
        ):
            raise ImpactRejected("Impact " + name + " is invalid.")
        tuple_fields[name] = tuple(items)
    for name in (
        "fixture_name",
        "run_id",
        "change_id",
        "policy_version",
        "change_applied_at",
        "evaluated_at",
        "seasonality",
    ):
        if not isinstance(value[name], str) or not value[name]:
            raise ImpactRejected("Impact " + name + " is invalid.")
    _utc(value["change_applied_at"], "Change time")
    _utc(value["evaluated_at"], "Evaluation time")
    return ImpactEvaluationRequest(
        fixture_name=value["fixture_name"],
        run_id=value["run_id"],
        change_id=value["change_id"],
        policy_version=value["policy_version"],
        change_applied_at=value["change_applied_at"],
        evaluated_at=value["evaluated_at"],
        baseline=ImpactObservation.from_mapping(value["baseline"], "Baseline"),
        post_change=ImpactObservation.from_mapping(
            value["post_change"],
            "Post-change",
        ),
        seasonality=value["seasonality"],
        known_interventions=tuple_fields["known_interventions"],
        confounders=tuple_fields["confounders"],
        evidence=tuple_fields["evidence"],
    )


class ImpactEvaluator:
    """Evaluate one linked post-change observation using Gate 0 values."""

    def __init__(self, policy: Mapping[str, Any]) -> None:
        self.policy = policy
        if tuple(policy["impact"]["decision_values"]) != _DECISIONS:
            raise ImpactRejected("Gate 0 impact decision enum is invalid.")

    def evaluate(self, request: ImpactEvaluationRequest) -> ImpactReport:
        if request.policy_version != self.policy["policy_id"]:
            raise ImpactRejected("Impact policy version does not match Gate 0.")
        if request.baseline.campaign != request.post_change.campaign:
            raise ImpactRejected("Impact observations must use the same campaign.")
        evaluated_at = _utc(request.evaluated_at, "Evaluation time")
        changed_at = _utc(request.change_applied_at, "Change time")
        baseline_closed_at = datetime.combine(
            date.fromisoformat(request.baseline.period_end) + timedelta(days=1),
            time.min,
            tzinfo=timezone.utc,
        )
        post_started_at = datetime.combine(
            date.fromisoformat(request.post_change.period_start),
            time.min,
            tzinfo=timezone.utc,
        )
        if (
            baseline_closed_at > changed_at
            or post_started_at < changed_at
            or post_started_at < baseline_closed_at
        ):
            raise ImpactRejected("TEMPORAL_LINKAGE_INVALID")
        observation_hours = int(self.policy["timing"]["observation_window_hours"])
        if evaluated_at - changed_at < timedelta(hours=observation_hours):
            raise ImpactRejected("OBSERVATION_WINDOW_ACTIVE")
        delayed_hours = int(self.policy["timing"]["late_conversion_cutoff_hours"])
        post_closed_at = datetime.combine(
            date.fromisoformat(request.post_change.period_end) + timedelta(days=1),
            time.min,
            tzinfo=timezone.utc,
        )
        if evaluated_at < post_closed_at + timedelta(hours=delayed_hours):
            raise ImpactRejected("DELAYED_CONVERSION_WINDOW_ACTIVE")
        for watermark in request.post_change.watermarks.values():
            if _utc(watermark, "Post-change watermark") > evaluated_at:
                raise ImpactRejected("Post-change watermark is in the future.")

        baseline_cpa = request.baseline.cpa_rub()
        post_cpa = request.post_change.cpa_rub()
        improvement = baseline_cpa - post_cpa
        improvement_percent = (
            improvement / baseline_cpa * Decimal(100)
            if baseline_cpa != 0
            else Decimal(0)
        )
        confidence = self._confidence(request)
        target = _decimal(
            self.policy["mandate"]["kpi"]["target_maximum"],
            "Target CPA",
        )
        if confidence != "READY":
            next_decision = "ESCALATE_TO_HUMAN"
        elif post_cpa < baseline_cpa and post_cpa <= target:
            next_decision = "KEEP_CHANGE"
        elif post_cpa > baseline_cpa and post_cpa > target:
            next_decision = "ROLLBACK_CHANGE"
        else:
            next_decision = "ADJUST_CHANGE"
        expected_fixture_decision = self._fixture_decision(request.fixture_name)
        if (
            expected_fixture_decision is not None
            and next_decision != expected_fixture_decision
        ):
            raise ImpactRejected("Impact fixture decision does not match Gate 0.")
        return ImpactReport(
            schema_version="impact-report-v1",
            policy_version=request.policy_version,
            run_id=request.run_id,
            change_id=request.change_id,
            fixture_name=request.fixture_name,
            status="OBSERVED_POST_CHANGE",
            effect_classification="OBSERVED_ASSOCIATION",
            baseline={
                "snapshot_id": request.baseline.snapshot_id,
                "period_start": request.baseline.period_start,
                "period_end": request.baseline.period_end,
                "cpa_rub": _decimal_text(baseline_cpa),
            },
            post_change={
                "snapshot_id": request.post_change.snapshot_id,
                "period_start": request.post_change.period_start,
                "period_end": request.post_change.period_end,
                "cpa_rub": _decimal_text(post_cpa),
            },
            watermarks={
                "baseline": dict(request.baseline.watermarks),
                "post_change": dict(request.post_change.watermarks),
            },
            delayed_conversion_cutoff_hours=delayed_hours,
            observation_window_hours=observation_hours,
            seasonality=request.seasonality,
            known_interventions=request.known_interventions,
            confounders=request.confounders,
            metric_changes={
                "cpa_rub": {
                    "baseline": _decimal_text(baseline_cpa),
                    "post_change": _decimal_text(post_cpa),
                    "improvement": _decimal_text(improvement),
                    "improvement_percent": _decimal_text(improvement_percent),
                }
            },
            confidence=confidence,
            evidence=request.evidence,
            next_decision=next_decision,
        )

    def _fixture_decision(self, fixture_name: str) -> str | None:
        contracts = self.policy["impact"].get("decision_fixtures")
        if isinstance(contracts, list):
            for item in contracts:
                if isinstance(item, Mapping) and item.get("name") == fixture_name:
                    value = item.get("expected_next_decision")
                    return str(value) if value is not None else None
            return None
        fixture = self.policy["impact"]["fixture"]
        if fixture.get("name") == fixture_name:
            return str(fixture["expected_next_decision"])
        return None

    def _confidence(self, request: ImpactEvaluationRequest) -> str:
        if not request.evidence:
            return "INSUFFICIENT_EVIDENCE"
        if request.confounders or request.known_interventions:
            return "CONFOUNDED"
        observations = (request.baseline, request.post_change)
        if any(
            observation.comparability_status != "COMPARABLE"
            or observation.confidence_status != "READY"
            for observation in observations
        ):
            return "INSUFFICIENT_DATA"
        minimum = self.policy["mandate"]["minimum_sample"]
        if any(
            observation.metrics["clicks"] < int(minimum["clicks"])
            or observation.metrics["goal_visits"] < int(minimum["conversions"])
            for observation in observations
        ):
            return "INSUFFICIENT_DATA"
        return "READY"


class ImpactArtifactStore:
    """Write one immutable canonical impact_report.json."""

    def __init__(self, run_directory: Path) -> None:
        self.run_directory = run_directory

    def write(self, report: ImpactReport) -> StoredImpactReport:
        self.run_directory.mkdir(parents=True, exist_ok=True)
        canonical_bytes = json.dumps(
            report.as_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        canonical_hash = "sha256:" + hashlib.sha256(canonical_bytes).hexdigest()
        path = self.run_directory / "impact_report.json"
        try:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o400,
            )
        except FileExistsError:
            try:
                existing = path.read_bytes()
            except OSError as error:
                raise ImpactRejected("Impact report cannot be read.") from error
            if existing != canonical_bytes:
                raise ImpactRejected(
                    "Immutable impact_report.json contains different content."
                ) from None
            return StoredImpactReport(canonical_hash, True)
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
        return StoredImpactReport(canonical_hash, False)
