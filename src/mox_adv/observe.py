"""Read-only OBSERVE pipeline for linked Direct and Metrika fixtures."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from mox_adv.analytics import IntegratedAnalyticsEngineV1
from mox_adv.artifacts import RunWorkspace
from mox_adv.audit import SQLiteAuditJournal
from mox_adv.connectors import (
    FixtureAnalyticsConnectorV1,
    FixtureAnalyticsReadConnectorsV1,
)
from mox_adv.contracts import (
    ARTIFACT_SCHEMA_VERSION,
    INTERNAL_API_VERSION,
    AnalyticsPeriod,
    AnalyticsScope,
    AuditVerification,
    BaselineAggregate,
    ConnectedAnalytics,
    DirectCampaignStateBlock,
    DirectCampaignStateReadQuery,
    DirectReportBlock,
    DirectReportsReadQuery,
    IntegratedPerformanceSnapshot,
    MetrikaReportBlock,
    MetrikaReportReadQuery,
    RunOutcome,
    TrustedAnalyticsScope,
)
from mox_adv.errors import RunAlreadyExistsError, RunRejectedError
from mox_adv.internal_api.v1 import (
    DirectCampaignStateReadAPI,
    DirectReportsReadAPI,
    MetrikaReportReadAPI,
)
from mox_adv.normalization import IntegratedSnapshotNormalizerV1
from mox_adv.trust_boundary import (
    capability_report_section,
    emit_run_capability_evidence,
)

LOCAL_FIXTURE_CAMPAIGNS = {
    "linked-observe": "sim-campaign",
    "ui-linked-budget-pressure": "sim-campaign",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json_object(
    path: Path,
    code: str,
    stage: str,
) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RunRejectedError(
            code,
            stage,
            "The required local JSON input could not be loaded.",
        ) from error
    if not isinstance(value, dict):
        raise RunRejectedError(
            code,
            stage,
            "The required local JSON input must be an object.",
        )
    return value


def load_linked_fixture(path: Path) -> dict[str, Any]:
    return _load_json_object(
        path,
        "ANALYTICS_FIXTURE_REJECTED",
        "connectors",
    )


def load_observe_policy(path: Path) -> dict[str, Any]:
    policy = _load_json_object(path, "POLICY_REJECTED", "policy")
    try:
        valid = (
            policy["record"]["policy_decisions_status"] == "APPROVED"
            and policy["record"]["simulation_status"] == "READY"
            and policy["record"]["production_write_authorized"] is False
            and policy["environment"]["simulation_write_egress"] is False
            and policy["schema_version"] == "gate0-policy-v1"
            and isinstance(policy["policy_id"], str)
        )
    except (KeyError, TypeError) as error:
        raise RunRejectedError(
            "POLICY_REJECTED",
            "policy",
            "The Gate 0 policy is incomplete for OBSERVE.",
        ) from error
    if not valid:
        raise RunRejectedError(
            "POLICY_REJECTED",
            "policy",
            "The Gate 0 policy does not authorize safe OBSERVE.",
        )
    return policy


def trusted_fixture_scope(
    policy: Mapping[str, Any],
    fixture_id: str,
) -> TrustedAnalyticsScope:
    try:
        campaign = LOCAL_FIXTURE_CAMPAIGNS[fixture_id]
        bindings = policy["bindings"]["simulation"]
        return TrustedAnalyticsScope(
            organization=str(bindings["organization"]),
            connection=str(bindings["connection"]),
            account=str(bindings["direct_account"]),
            campaign=campaign,
            counter=str(bindings["pilot_counter"]),
            goal=str(bindings["primary_goal"]),
            baseline_campaign=str(bindings["readonly_baseline_campaign"]),
        )
    except (KeyError, TypeError) as error:
        raise RunRejectedError(
            "TRUSTED_SCOPE_REJECTED",
            "normalization",
            "The local fixture has no approved trusted scope.",
        ) from error


def read_observe_snapshot(
    *,
    policy: Mapping[str, Any],
    observation_id: str,
    generated_at: str,
    period_start: str,
    period_end: str,
    trusted_scope: TrustedAnalyticsScope,
    direct_reports: DirectReportsReadAPI,
    direct_state: DirectCampaignStateReadAPI,
    metrika_report: MetrikaReportReadAPI,
    baseline: Optional[BaselineAggregate] = None,
) -> IntegratedPerformanceSnapshot:
    """Collect three typed read blocks and build one linked snapshot."""

    direct_block = direct_reports.read_report(
        DirectReportsReadQuery(
            account=trusted_scope.account,
            campaign=trusted_scope.campaign,
            period_start=period_start,
            period_end=period_end,
            attribution=str(policy["attribution"]["direct"]),
        )
    )
    state_block = direct_state.read_campaign_state(
        DirectCampaignStateReadQuery(
            account=trusted_scope.account,
            campaign=trusted_scope.campaign,
        )
    )
    metrika_block = metrika_report.read_metrika_report(
        MetrikaReportReadQuery(
            counter=trusted_scope.counter,
            campaign=trusted_scope.campaign,
            goal=trusted_scope.goal,
            period_start=period_start,
            period_end=period_end,
            attribution=str(policy["attribution"]["metrika"]),
        )
    )
    return build_observe_snapshot_from_blocks(
        policy=policy,
        observation_id=observation_id,
        generated_at=generated_at,
        period_start=period_start,
        period_end=period_end,
        trusted_scope=trusted_scope,
        direct_block=direct_block,
        state_block=state_block,
        metrika_block=metrika_block,
        baseline=baseline,
    )


def build_observe_snapshot_from_blocks(
    *,
    policy: Mapping[str, Any],
    observation_id: str,
    generated_at: str,
    period_start: str,
    period_end: str,
    trusted_scope: TrustedAnalyticsScope,
    direct_block: DirectReportBlock,
    state_block: DirectCampaignStateBlock,
    metrika_block: MetrikaReportBlock,
    baseline: Optional[BaselineAggregate] = None,
) -> IntegratedPerformanceSnapshot:
    """Normalize already collected typed blocks at their completion time."""

    connected = ConnectedAnalytics(
        observation_id=observation_id,
        generated_at=generated_at,
        scope=AnalyticsScope(
            organization=trusted_scope.organization,
            connection=trusted_scope.connection,
            account=trusted_scope.account,
            campaign=trusted_scope.campaign,
            counter=trusted_scope.counter,
            goal=trusted_scope.goal,
        ),
        requested_period=AnalyticsPeriod(
            period_start=period_start,
            period_end=period_end,
        ),
        direct_report=direct_block,
        direct_state=state_block,
        metrika_report=metrika_block,
        baseline=baseline,
    )
    draft = IntegratedSnapshotNormalizerV1().normalize(
        connected,
        policy,
        trusted_scope,
    )
    snapshot = IntegratedAnalyticsEngineV1().calculate(draft)
    if not IntegratedSnapshotNormalizerV1.verify_fingerprint(snapshot.as_dict()):
        raise RunRejectedError(
            "SNAPSHOT_FINGERPRINT_MISMATCH",
            "analytics",
            "The integrated snapshot fingerprint does not match its fields.",
        )
    return snapshot


def _safe_rejected_run_id(rejected_run_id: str) -> str:
    digest = hashlib.sha256(rejected_run_id.encode("utf-8")).hexdigest()[:16]
    return "rejected-" + digest


def _report(
    run_id: str,
    status: str,
    snapshot: Optional[IntegratedPerformanceSnapshot],
    error_code: Optional[str],
) -> str:
    lines = ["# Отчёт MOX-ADV OBSERVE", ""]
    if status == "SUCCEEDED" and snapshot is not None:
        lines.extend(
            [
                "Наблюдение по связанным данным завершено успешно.",
                f"Идентификатор запуска: `{run_id}`.",
                f"Идентификатор snapshot: `{snapshot.snapshot_id}`.",
                (f"Сопоставимость данных: `{snapshot.comparability_status}`."),
                f"Доверительный статус: `{snapshot.confidence_status}`.",
                f"CTR: `{snapshot.display_metrics['ctr_percent']}%`.",
                f"CPC: `{snapshot.display_metrics['cpc_rub']} ₽`.",
                (
                    "Конверсия: "
                    f"`{snapshot.display_metrics['conversion_rate_percent']}%`."
                ),
                f"CPA: `{snapshot.display_metrics['cpa_rub']} ₽`.",
                (
                    "Использование недельного бюджета: "
                    f"`{snapshot.display_metrics['budget_utilization_percent']}%`."
                ),
                f"Pacing: `{snapshot.display_metrics['pacing_percent']}%`.",
                "Write-proposal не создавался, executor не вызывался.",
                "Внешние изменяющие запросы не отправлялись.",
                "Сводка capabilities: `capability-evidence.json`.",
            ]
        )
    else:
        lines.extend(
            [
                "Наблюдение безопасно остановлено до анализа.",
                f"Идентификатор запуска: `{run_id}`.",
                f"Код ошибки: `{error_code or 'INTERNAL_FAILURE'}`.",
                "Write-proposal не создавался, executor не вызывался.",
                "Внешние изменяющие запросы не отправлялись.",
                "Сводка capabilities: `capability-evidence.json`.",
            ]
        )
    return (
        "\n".join(lines)
        + "\n"
        + capability_report_section(
            mode="OBSERVE",
            status=status,
        )
    )


def _result(
    *,
    run_id: str,
    policy_version: str,
    status: str,
    started_at: str,
    started_monotonic: float,
    audit: AuditVerification,
    snapshot: Optional[IntegratedPerformanceSnapshot],
    error_code: Optional[str],
    error_stage: Optional[str],
    error_message: Optional[str],
) -> Mapping[str, Any]:
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "policy_version": policy_version,
        "internal_api_version": INTERNAL_API_VERSION,
        "run_id": run_id,
        "source": "LOCAL_FIXTURE",
        "evidence_type": "SIMULATED",
        "mode": "OBSERVE",
        "status": status,
        "execution_status": "NOT_STARTED",
        "external_write_sent": False,
        "snapshot_id": None if snapshot is None else snapshot.snapshot_id,
        "snapshot": None if snapshot is None else snapshot.as_dict(),
        "capability_evidence_path": "capability-evidence.json",
        "started_at": started_at,
        "finished_at": _utc_now(),
        "duration_ms": max(
            0,
            int((time.monotonic() - started_monotonic) * 1000),
        ),
        "stages": (
            ["audit", "policy", "connectors", "normalization", "analytics"]
            if snapshot is not None
            else ["audit"]
        ),
        "error": (
            None
            if error_code is None
            else {
                "code": error_code,
                "stage": error_stage,
                "message": error_message,
                "retryable": False,
            }
        ),
        "audit": {
            "algorithm": "SHA-256",
            "final_sequence": audit.final_sequence,
            "final_hash": audit.final_hash,
        },
    }


def run_observe_fixture(
    run_id: str,
    runs_root: Path,
    fixture_path: Path,
    policy_path: Path,
) -> RunOutcome:
    """Create one immutable OBSERVE run with no executor or write egress."""

    started_monotonic = time.monotonic()
    started_at = _utc_now()
    try:
        workspace = RunWorkspace.create(runs_root, run_id)
    except RunAlreadyExistsError:
        return RunOutcome(
            exit_code=2,
            run_id=run_id,
            status="REJECTED",
            run_directory=str(runs_root / run_id),
            error_code="RUN_ALREADY_EXISTS",
        )
    except ValueError:
        run_id = _safe_rejected_run_id(run_id)
        try:
            workspace = RunWorkspace.create(runs_root, run_id)
        except RunAlreadyExistsError:
            return RunOutcome(
                exit_code=2,
                run_id=run_id,
                status="REJECTED",
                run_directory=str(runs_root / run_id),
                error_code="RUN_ALREADY_EXISTS",
            )
        return _complete_rejection(
            workspace=workspace,
            run_id=run_id,
            policy_version="unavailable",
            started_at=started_at,
            started_monotonic=started_monotonic,
            error=RunRejectedError(
                "INVALID_RUN_ID",
                "workspace",
                "The requested run identifier is invalid.",
            ),
        )

    try:
        policy = load_observe_policy(policy_path)
    except RunRejectedError as error:
        return _complete_rejection(
            workspace=workspace,
            run_id=run_id,
            policy_version="unavailable",
            started_at=started_at,
            started_monotonic=started_monotonic,
            error=error,
        )
    policy_version = str(policy["policy_id"])
    journal = SQLiteAuditJournal(
        path=workspace.path / ".audit.sqlite3",
        run_id=run_id,
        schema_version=ARTIFACT_SCHEMA_VERSION,
        policy_version=policy_version,
    )
    try:
        journal.append(
            "run.started",
            {
                "mode": "OBSERVE",
                "source": "LOCAL_FIXTURE",
                "external_write_egress": False,
            },
        )
        journal.append("policy.validated", {"policy_version": policy_version})
        raw_fixture = load_linked_fixture(fixture_path)
        connected = FixtureAnalyticsConnectorV1().read_linked(raw_fixture)
        journal.append(
            "analytics.connected",
            {
                "observation_id": connected.observation_id,
                "connector_contract": "read-only-v1",
            },
        )
        trusted_scope = trusted_fixture_scope(
            policy,
            connected.observation_id,
        )
        fixture_reads = FixtureAnalyticsReadConnectorsV1(connected)
        snapshot = read_observe_snapshot(
            policy=policy,
            observation_id=connected.observation_id,
            generated_at=connected.generated_at,
            period_start=connected.direct_report.period_start,
            period_end=connected.direct_report.period_end,
            trusted_scope=trusted_scope,
            direct_reports=fixture_reads,
            direct_state=fixture_reads,
            metrika_report=fixture_reads,
            baseline=connected.baseline,
        )
        journal.append(
            "analytics.snapshot_ready",
            {
                "snapshot_id": snapshot.snapshot_id,
                "comparability_status": snapshot.comparability_status,
                "confidence_status": snapshot.confidence_status,
                "financial_recommendations_allowed": (
                    snapshot.financial_recommendations_allowed
                ),
            },
        )
        final_event = journal.append(
            "run.completed",
            {
                "status": "SUCCEEDED",
                "execution_status": "NOT_STARTED",
                "external_write_sent": False,
            },
        )
        verification = journal.seal()
        if verification.final_hash != final_event.event_hash:
            raise RuntimeError("The audit completion anchor is inconsistent.")
        result = _result(
            run_id=run_id,
            policy_version=policy_version,
            status="SUCCEEDED",
            started_at=started_at,
            started_monotonic=started_monotonic,
            audit=verification,
            snapshot=snapshot,
            error_code=None,
            error_stage=None,
            error_message=None,
        )
        workspace.write_json("result.json", result)
        workspace.write_text(
            "report.md",
            _report(run_id, "SUCCEEDED", snapshot, None),
        )
        journal.export_jsonl(workspace.path / "events.jsonl")
        emit_run_capability_evidence(
            workspace.path,
            run_id=run_id,
            policy_version=policy_version,
            mode="OBSERVE",
            status="SUCCEEDED",
        )
        return RunOutcome(
            exit_code=0,
            run_id=run_id,
            status="SUCCEEDED",
            run_directory=str(workspace.path),
        )
    except RunRejectedError as error:
        return _complete_rejection(
            workspace=workspace,
            run_id=run_id,
            policy_version=policy_version,
            started_at=started_at,
            started_monotonic=started_monotonic,
            error=error,
            journal=journal,
        )
    finally:
        journal.close()


def _complete_rejection(
    *,
    workspace: RunWorkspace,
    run_id: str,
    policy_version: str,
    started_at: str,
    started_monotonic: float,
    error: RunRejectedError,
    journal: Optional[SQLiteAuditJournal] = None,
) -> RunOutcome:
    owns_journal = journal is None
    if journal is None:
        journal = SQLiteAuditJournal(
            path=workspace.path / ".audit.sqlite3",
            run_id=run_id,
            schema_version=ARTIFACT_SCHEMA_VERSION,
            policy_version=policy_version,
        )
        journal.append(
            "run.started",
            {
                "mode": "OBSERVE",
                "source": "LOCAL_FIXTURE",
                "external_write_egress": False,
            },
        )
    try:
        journal.append(
            "run.rejected",
            {"error_code": error.code, "stage": error.stage},
        )
        final_event = journal.append(
            "run.completed",
            {
                "status": "REJECTED",
                "execution_status": "NOT_STARTED",
                "external_write_sent": False,
            },
        )
        verification = journal.seal()
        if verification.final_hash != final_event.event_hash:
            raise RuntimeError("The audit completion anchor is inconsistent.")
        workspace.write_json(
            "result.json",
            _result(
                run_id=run_id,
                policy_version=policy_version,
                status="REJECTED",
                started_at=started_at,
                started_monotonic=started_monotonic,
                audit=verification,
                snapshot=None,
                error_code=error.code,
                error_stage=error.stage,
                error_message=error.safe_message,
            ),
        )
        workspace.write_text(
            "report.md",
            _report(run_id, "REJECTED", None, error.code),
        )
        journal.export_jsonl(workspace.path / "events.jsonl")
        emit_run_capability_evidence(
            workspace.path,
            run_id=run_id,
            policy_version=policy_version,
            mode="OBSERVE",
            status="REJECTED",
        )
        return RunOutcome(
            exit_code=2,
            run_id=run_id,
            status="REJECTED",
            run_directory=str(workspace.path),
            error_code=error.code,
        )
    finally:
        if owns_journal:
            journal.close()
