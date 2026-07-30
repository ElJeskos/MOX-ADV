"""Paired Monitoring Cycle adapters over the public Direct module contract."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from mox_adv.approval_execution import ExecutionFacts
from mox_adv.contracts import (
    DirectCampaignStateBlock,
    DirectCampaignStateReadQuery,
    DirectReportBlock,
    DirectReportRow,
    DirectReportsReadQuery,
)
from mox_adv.control_state import DurableControlState, PreparedChange
from mox_adv.direct_action_runtime import (
    DirectActionRuntimeV1,
    PairedDirectActionContextV1,
)
from mox_adv.direct_provider import DirectStateValuesV1
from mox_adv.environment import ExecutionEnvironment
from mox_adv.fake_write_adapter import FakeWriteAdapter
from mox_adv.impact import ImpactEvaluationRequest, ImpactObservation, ImpactReport
from mox_adv.mandate_store import DurableMandateAuthority
from mox_adv.module_api.v1 import (
    DirectoryDecisionRecordStoreV1,
    InProcessModuleAdapterV1,
    ModuleRequestV1,
    ModuleResultV1,
)
from mox_adv.modules.direct import DirectModuleV1
from mox_adv.monitoring import MonitoringStore
from mox_adv.proposal_store import ImmutableProposalStore
from mox_adv.recommend_projection import SanitizedProjection


@dataclass(frozen=True)
class PairedDirectExecutionOutcomeV1:
    """Return the module result together with the sealed TEST readback."""

    result: ModuleResultV1
    decision_record: Mapping[str, Any]
    observed_value: Any
    write_calls: int


@dataclass(frozen=True)
class PairedDirectImpactOutcomeV1:
    """Return the unchanged impact report with its public module evidence."""

    report: ImpactReport
    result: ModuleResultV1
    decision_record: Mapping[str, Any]


class PairedSnapshotDirectProviderV1:
    """Expose one trusted paired snapshot as the Direct reread boundary."""

    def __init__(
        self,
        *,
        snapshot: Mapping[str, Any],
        now: datetime,
        direct_age_minutes: int,
        metrika_age_minutes: int,
        watermark_skew_minutes: int,
        trusted_change_author: str,
    ) -> None:
        self._snapshot = snapshot
        self._connection_id = str(snapshot["scope"]["connection"])
        self._account_id = str(snapshot["scope"]["account"])
        self._campaign_id = str(snapshot["scope"]["campaign"])
        self._trusted_change_author = trusted_change_author
        self._direct_retrieved = now - timedelta(minutes=direct_age_minutes)
        metrika_retrieved = now - timedelta(minutes=metrika_age_minutes)
        watermark_base = min(self._direct_retrieved, metrika_retrieved) - timedelta(
            minutes=watermark_skew_minutes
        )
        self.external_observed_at = metrika_retrieved
        self.external_watermark = watermark_base
        self.direct_watermark = watermark_base + timedelta(
            minutes=watermark_skew_minutes
        )
        self.report_reads = 0
        self.state_reads = 0

    def read_direct_report(
        self,
        connection_id: str,
        query: DirectReportsReadQuery,
    ) -> DirectReportBlock:
        self._authorize(
            connection_id,
            query.account,
            query.campaign,
        )
        if (
            query.period_start != self._snapshot["period_start"]
            or query.period_end != self._snapshot["period_end"]
            or query.attribution != "AUTO"
        ):
            raise ValueError("The paired Direct report query is outside the snapshot.")
        self.report_reads += 1
        rows = tuple(
            DirectReportRow(
                campaign=str(item["campaign"]),
                date=str(item["date"]),
                impressions=int(item["impressions"]),
                clicks=int(item["clicks"]),
                cost_micros=int(item["cost_micros"]),
            )
            for item in self._snapshot["records"]
        )
        return DirectReportBlock(
            source="LOCAL_FIXTURE",
            retrieved_at=self._direct_retrieved.isoformat(),
            watermark=self.direct_watermark.isoformat(),
            period_start=str(self._snapshot["period_start"]),
            period_end=str(self._snapshot["period_end"]),
            timezone=str(self._snapshot["timezone"]),
            attribution="AUTO",
            currency="RUB",
            rows=rows,
        )

    def read_direct_state(
        self,
        connection_id: str,
        query: DirectCampaignStateReadQuery,
    ) -> DirectCampaignStateBlock:
        self._authorize(
            connection_id,
            query.account,
            query.campaign,
        )
        self.state_reads += 1
        campaign = self._snapshot["campaign"]
        return DirectCampaignStateBlock(
            source="LOCAL_FIXTURE",
            retrieved_at=self._direct_retrieved.isoformat(),
            watermark=self.direct_watermark.isoformat(),
            campaign=self._campaign_id,
            campaign_state=str(campaign["state"]),
            group_state=str(campaign["group_state"]),
            ad_state=str(campaign["ad_state"]),
            strategy=str(campaign["strategy"]),
            current_weekly_budget_micros=int(campaign["current_weekly_budget_micros"]),
            budget_period_start=str(campaign["budget_period_start"]),
            budget_period_end=str(campaign["budget_period_end"]),
            current_search_bid_micros=int(campaign["current_search_bid_micros"]),
            ad_variant=str(campaign["current_ad_variant"]),
            object_config_version=str(campaign["object_config_version"]),
            last_change_author=self._trusted_change_author,
            last_change_occurred_at=(
                self._direct_retrieved - timedelta(days=7)
            ).isoformat(),
        )

    def authorizes_change_author(
        self,
        connection_id: str,
        author: str,
    ) -> bool:
        if connection_id != self._connection_id:
            raise PermissionError("The paired Direct connection is not authorized.")
        return author == self._trusted_change_author

    def expected_state(self) -> DirectStateValuesV1:
        campaign = self._snapshot["campaign"]
        return DirectStateValuesV1(
            campaign_state=str(campaign["state"]),
            group_state=str(campaign["group_state"]),
            ad_state=str(campaign["ad_state"]),
            strategy=str(campaign["strategy"]),
            current_weekly_budget_micros=int(campaign["current_weekly_budget_micros"]),
            budget_period_start=_utc(str(campaign["budget_period_start"])),
            budget_period_end=_utc(str(campaign["budget_period_end"])),
            current_search_bid_micros=int(campaign["current_search_bid_micros"]),
            ad_variant=str(campaign["current_ad_variant"]),
            object_config_version=str(campaign["object_config_version"]),
            last_change_author=self._trusted_change_author,
            last_change_occurred_at=self._direct_retrieved - timedelta(days=7),
        )

    def _authorize(
        self,
        connection_id: str,
        account_id: str,
        campaign_id: str,
    ) -> None:
        if (
            connection_id != self._connection_id
            or account_id != self._account_id
            or campaign_id != self._campaign_id
        ):
            raise PermissionError("The paired Direct scope is not authorized.")


def execute_paired_direct_test_action(
    *,
    run_directory: Path,
    policy: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    projection: SanitizedProjection,
    prepared: PreparedChange,
    state: DurableControlState,
    proposal_store: ImmutableProposalStore,
    now: datetime,
    execution_facts: ExecutionFacts | None = None,
    test_adapter: FakeWriteAdapter | None = None,
    persist_artifacts: bool = True,
    mandate_authority: DurableMandateAuthority | None = None,
    mandate_id: str | None = None,
) -> PairedDirectExecutionOutcomeV1:
    """Execute one existing paired proposal through DirectModuleV1 in TEST."""

    if prepared.snapshot_id != snapshot["snapshot_id"]:
        raise ValueError("The prepared change is not bound to the paired snapshot.")
    freshness = projection["freshness"]
    provider = PairedSnapshotDirectProviderV1(
        snapshot=snapshot,
        now=now,
        direct_age_minutes=int(freshness["direct_minutes"]),
        metrika_age_minutes=int(freshness["metrika_minutes"]),
        watermark_skew_minutes=int(freshness["watermark_skew_minutes"]),
        trusted_change_author=prepared.scope.writer,
    )
    adapter = test_adapter or FakeWriteAdapter(
        initial_state={prepared.target_key(): prepared.current_value}
    )
    decision_records = DirectoryDecisionRecordStoreV1(
        run_directory / "decision-records"
    )
    runtime = DirectActionRuntimeV1(
        policy=policy,
        state=state,
        proposal_store=proposal_store,
        trigger_store=MonitoringStore(run_directory / "monitoring.sqlite3"),
        test_adapter=adapter,
        environment=ExecutionEnvironment.TEST,
        paired_context=PairedDirectActionContextV1(
            projection=projection,
            snapshot_id=str(snapshot["snapshot_id"]),
            expected_fingerprint=prepared.expected_fingerprint,
            expected_state=provider.expected_state(),
            execution_facts=execution_facts,
        ),
        mandate_authority=mandate_authority,
    )
    module = DirectModuleV1(
        clock=lambda: now,
        decision_records=decision_records,
        provider_reader=provider,
        action_runtime=runtime,
        environment=ExecutionEnvironment.TEST,
    )
    request = _paired_execution_request(
        snapshot=snapshot,
        prepared=prepared,
        provider=provider,
        mandate_id=mandate_id,
    )
    result = InProcessModuleAdapterV1(
        module,
        environment=ExecutionEnvironment.TEST,
        decision_records=decision_records,
    ).invoke(request)
    if result.decision_record_ref is None:
        raise RuntimeError("Direct execution did not persist a Decision Record.")
    record = decision_records.read(result.decision_record_ref)
    if persist_artifacts:
        _write_immutable_json(
            run_directory / "direct-module-result.json",
            result.as_dict(),
        )
        _write_immutable_json(
            run_directory / "direct-decision-record.json",
            record,
        )
    execution = result.execution_result
    observed_value: Any = None
    if execution is not None and execution.provider_reference is not None:
        observed_value = execution.provider_reference
        if isinstance(prepared.current_value, int):
            observed_value = int(observed_value)
    return PairedDirectExecutionOutcomeV1(
        result=result,
        decision_record=record,
        observed_value=observed_value,
        write_calls=adapter.write_calls,
    )


def evaluate_paired_direct_impact(
    *,
    run_directory: Path,
    policy: Mapping[str, Any],
    request: ImpactEvaluationRequest,
) -> PairedDirectImpactOutcomeV1:
    """Evaluate existing linked impact evidence through DirectModuleV1."""

    decision_records = DirectoryDecisionRecordStoreV1(
        run_directory / "decision-records"
    )
    module = DirectModuleV1(
        decision_records=decision_records,
        impact_policy=policy,
        environment=ExecutionEnvironment.TEST,
    )
    module_request = ModuleRequestV1.from_dict(
        {
            "schema_version": "module-request-v1",
            "connection_ref": {"connection_id": "paired-monitoring-cycle"},
            "environment": "TEST",
            "scope": {
                "organization_id": "paired-monitoring-cycle",
                "account_id": "paired-direct-account",
                "campaign_id": request.baseline.campaign,
            },
            "period": {
                "start_date": request.baseline.period_start,
                "end_date": request.post_change.period_end,
                "timezone": "UTC",
            },
            "objective": {
                "code": "EVALUATE_PAIRED_IMPACT",
                "description": (
                    "Evaluate the existing linked post-change observations."
                ),
            },
            "operation": {
                "kind": "ANALYZE",
                "operation_type": "EVALUATE_IMPACT",
            },
            "impact_evaluation_command": {
                "schema_version": "direct-impact-evaluation-command-v1",
                "command": "EVALUATE_IMPACT",
                "fixture_name": request.fixture_name,
                "run_id": request.run_id,
                "change_id": request.change_id,
                "policy_version": request.policy_version,
                "change_applied_at": request.change_applied_at,
                "evaluated_at": request.evaluated_at,
                "baseline": _impact_observation(request.baseline),
                "post_change": _impact_observation(request.post_change),
                "seasonality": request.seasonality,
                "known_interventions": list(request.known_interventions),
                "confounders": list(request.confounders),
                "evidence": list(request.evidence),
            },
            "idempotency_key": "paired-impact-" + request.change_id,
        }
    )
    result = InProcessModuleAdapterV1(
        module,
        environment=ExecutionEnvironment.TEST,
        decision_records=decision_records,
    ).invoke(module_request)
    if result.status != "SUCCEEDED" or result.impact_outcome is None:
        reason = result.errors[0].code if result.errors else result.status
        raise ValueError("Paired Direct impact evaluation failed: " + reason)
    if result.decision_record_ref is None:
        raise RuntimeError("Direct impact did not persist a Decision Record.")
    record = decision_records.read(result.decision_record_ref)
    outcome = result.impact_outcome.as_dict()
    report = ImpactReport(
        schema_version=str(outcome["schema_version"]),
        policy_version=str(outcome["policy_version"]),
        run_id=str(outcome["run_id"]),
        change_id=str(outcome["change_id"]),
        fixture_name=str(outcome["fixture_name"]),
        status=str(outcome["status"]),
        effect_classification=str(outcome["effect_classification"]),
        baseline=dict(outcome["baseline"]),
        post_change=dict(outcome["post_change"]),
        watermarks=dict(outcome["watermarks"]),
        delayed_conversion_cutoff_hours=int(outcome["delayed_conversion_cutoff_hours"]),
        observation_window_hours=int(outcome["observation_window_hours"]),
        seasonality=str(outcome["seasonality"]),
        known_interventions=tuple(outcome["known_interventions"]),
        confounders=tuple(outcome["confounders"]),
        metric_changes=dict(outcome["metric_changes"]),
        confidence=str(outcome["confidence"]),
        evidence=tuple(outcome["evidence"]),
        next_decision=str(outcome["next_decision"]),
    )
    _write_immutable_json(run_directory / "impact-module-result.json", result.as_dict())
    _write_immutable_json(run_directory / "impact-decision-record.json", record)
    return PairedDirectImpactOutcomeV1(
        report=report,
        result=result,
        decision_record=record,
    )


def _paired_execution_request(
    *,
    snapshot: Mapping[str, Any],
    prepared: PreparedChange,
    provider: PairedSnapshotDirectProviderV1,
    mandate_id: str | None,
) -> ModuleRequestV1:
    metrics = snapshot["metrics"]
    campaign = snapshot["campaign"]
    evidence_metrics = (
        ("impressions", int(metrics["impressions"]), "COUNT"),
        ("clicks", int(metrics["clicks"]), "COUNT"),
        ("cost_micros", int(metrics["cost_micros"]), "MICROS_RUB"),
        ("conversions", int(metrics["goal_visits"]), "COUNT"),
        ("campaign_state", str(campaign["state"]), "CODE"),
        ("group_state", str(campaign["group_state"]), "CODE"),
        ("ad_state", str(campaign["ad_state"]), "CODE"),
        ("strategy", str(campaign["strategy"]), "CODE"),
        (
            "current_weekly_budget_micros",
            int(campaign["current_weekly_budget_micros"]),
            "MICROS_RUB",
        ),
        (
            "current_search_bid_micros",
            int(campaign["current_search_bid_micros"]),
            "MICROS_RUB",
        ),
        ("ad_variant", str(campaign["current_ad_variant"]), "CODE"),
        (
            "object_config_version",
            str(campaign["object_config_version"]),
            "CODE",
        ),
        ("budget_period_start", str(campaign["budget_period_start"]), "ISO_8601"),
        ("budget_period_end", str(campaign["budget_period_end"]), "ISO_8601"),
    )
    scope = snapshot["scope"]
    command = {
        "schema_version": "direct-action-command-v1",
        "command": "EXECUTE_PROPOSAL",
        "proposal_id": prepared.proposal_id,
    }
    if mandate_id is not None:
        command["mandate_id"] = mandate_id
    return ModuleRequestV1.from_dict(
        {
            "schema_version": "module-request-v1",
            "connection_ref": {"connection_id": str(scope["connection"])},
            "environment": "TEST",
            "scope": {
                "organization_id": str(scope["organization"]),
                "account_id": str(scope["account"]),
                "campaign_id": str(scope["campaign"]),
            },
            "period": {
                "start_date": str(snapshot["period_start"]),
                "end_date": str(snapshot["period_end"]),
                "timezone": str(snapshot["timezone"]),
            },
            "objective": {
                "code": "PAIRED_MONITORING_CYCLE",
                "description": (
                    "Apply the exact authorized proposal from the paired snapshot."
                ),
            },
            "external_evidence": {
                "schema_version": "normalized-metrics-evidence-v1",
                "evidence_id": str(snapshot["snapshot_id"]),
                "source": "PAIRED_MODULE_RESULT",
                "observed_at": provider.external_observed_at.isoformat(),
                "watermark": provider.external_watermark.isoformat(),
                "metrics": [
                    {"name": name, "value": value, "unit": unit}
                    for name, value, unit in evidence_metrics
                ],
            },
            "operation": {
                "kind": "EXECUTE",
                "operation_type": "APPLY_OPTIMIZATION",
            },
            "direct_action_command": command,
            "idempotency_key": prepared.execution_key(),
        }
    )


def _impact_observation(value: ImpactObservation) -> Mapping[str, Any]:
    return {
        "snapshot_id": value.snapshot_id,
        "campaign": value.campaign,
        "period_start": value.period_start,
        "period_end": value.period_end,
        "watermarks": dict(value.watermarks),
        "metrics": dict(value.metrics),
        "comparability_status": value.comparability_status,
        "confidence_status": value.confidence_status,
    }


def _write_immutable_json(path: Path, value: Mapping[str, Any]) -> None:
    content = (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o400,
        )
    except FileExistsError:
        if path.read_bytes() != content:
            raise RuntimeError(path.name + " contains different immutable content.")
        return
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("Paired snapshot timestamps must use UTC.")
    return parsed.astimezone(timezone.utc)


__all__ = [
    "PairedDirectExecutionOutcomeV1",
    "PairedDirectImpactOutcomeV1",
    "PairedSnapshotDirectProviderV1",
    "evaluate_paired_direct_impact",
    "execute_paired_direct_test_action",
]
