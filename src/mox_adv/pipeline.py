"""Safe local fixture pipeline that exercises every internal API boundary."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, List, Mapping, Optional

from mox_adv.analytics import AnalyticsEngineV1
from mox_adv.artifacts import RunWorkspace
from mox_adv.audit import SQLiteAuditJournal
from mox_adv.connectors import FixtureConnectorV1
from mox_adv.contracts import (
    ARTIFACT_SCHEMA_VERSION,
    INTERNAL_API_VERSION,
    AuditVerification,
    ExecutionStatus,
    RunContext,
    RunError,
    RunOutcome,
    RunResult,
    RunStatus,
)
from mox_adv.decision import DecisionEngineV1
from mox_adv.errors import RunAlreadyExistsError, RunRejectedError
from mox_adv.execution import SimulationExecutorV1
from mox_adv.host_launcher import (
    CredentialProfileRejected,
    resolve_keychain_binding,
)
from mox_adv.internal_api.v1 import (
    AnalyticsAPI,
    ConnectorsAPI,
    DecisionAPI,
    ExecutionAPI,
    NormalizationAPI,
    PolicyAPI,
)
from mox_adv.normalization import NormalizerV1
from mox_adv.policy import SimulationPolicyV1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json_object(path: Path, code: str, stage: str) -> Mapping[str, Any]:
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


def _load_policy(path: Path) -> Mapping[str, Any]:
    policy = _load_json_object(path, "POLICY_REJECTED", "policy")
    try:
        policy_version = policy["policy_id"]
        schema_version = policy["schema_version"]
        simulation_status = policy["record"]["simulation_status"]
        production_write_authorized = policy["record"]["production_write_authorized"]
        write_egress = policy["environment"]["simulation_write_egress"]
    except (KeyError, TypeError) as error:
        raise RunRejectedError(
            "POLICY_REJECTED",
            "policy",
            "The Gate 0 policy is incomplete for simulation.",
        ) from error
    if (
        not isinstance(policy_version, str)
        or not isinstance(schema_version, str)
        or simulation_status != "READY"
        or production_write_authorized is not False
        or write_egress is not False
    ):
        raise RunRejectedError(
            "POLICY_REJECTED",
            "policy",
            "The Gate 0 policy does not authorize safe simulation.",
        )
    return policy


def _report(result: RunResult) -> str:
    if result.status == "SUCCEEDED":
        outcome = "Локальный simulation-run завершён успешно."
    elif result.status == "REJECTED":
        outcome = (
            "Локальный simulation-run безопасно отклонён до изменения внешних систем."
        )
    else:
        outcome = "Локальный simulation-run завершён контролируемой ошибкой."
    return (
        "# Отчёт MOX-ADV\n\n"
        f"{outcome}\n"
        f"Идентификатор запуска: `{result.run_id}`.\n"
        f"Версия схемы: `{result.schema_version}`.\n"
        f"Версия policy: `{result.policy_version}`.\n"
        f"Статус выполнения: `{result.execution_status}`.\n"
        "Внешние изменяющие запросы не отправлялись.\n"
        f"Финальный номер audit-события: `{result.audit.final_sequence}`.\n"
        f"Финальный SHA-256 hash: `{result.audit.final_hash}`.\n"
    )


def _finalize(
    workspace: RunWorkspace,
    journal: SQLiteAuditJournal,
    context: RunContext,
    started_monotonic: float,
    status: RunStatus,
    execution_status: ExecutionStatus,
    stages: List[str],
    snapshot_id: Optional[str],
    technical_command: Optional[str],
    external_write_sent: bool,
    error: Optional[RunError],
) -> RunResult:
    final_event = journal.append(
        "run.completed",
        {
            "status": status,
            "execution_status": execution_status,
            "external_write_sent": external_write_sent,
            "error_code": None if error is None else error.code,
        },
    )
    verification = journal.seal()
    if (
        verification.final_sequence != final_event.sequence
        or verification.final_hash != final_event.event_hash
    ):
        raise RuntimeError("The sealed audit anchor does not match completion.")
    result = RunResult(
        schema_version=context.schema_version,
        policy_version=context.policy_version,
        internal_api_version=INTERNAL_API_VERSION,
        run_id=context.run_id,
        source=context.source,
        evidence_type=context.evidence_type,
        mode=context.mode,
        status=status,
        execution_status=execution_status,
        external_write_sent=external_write_sent,
        snapshot_id=snapshot_id,
        started_at=context.started_at,
        finished_at=_utc_now(),
        duration_ms=max(0, int((time.monotonic() - started_monotonic) * 1000)),
        stages=tuple(stages),
        technical_command=technical_command,
        error=error,
        audit=AuditVerification(
            final_sequence=verification.final_sequence,
            final_hash=verification.final_hash,
        ),
    )
    workspace.write_result(result)
    workspace.write_text("report.md", _report(result))
    journal.export_jsonl(workspace.path / "events.jsonl")
    return result


def _safe_rejected_run_id(rejected_run_id: str) -> str:
    digest = hashlib.sha256(rejected_run_id.encode("utf-8")).hexdigest()[:16]
    return "rejected-" + digest


def _consume_ephemeral_credential(stream: BinaryIO) -> None:
    secret = bytearray(stream.readline(16_385))
    try:
        if not secret or len(secret) > 16_384:
            raise RunRejectedError(
                "CREDENTIAL_CHANNEL_REJECTED",
                "credential_ingress",
                "The ephemeral credential channel is empty or too large.",
            )
        if stream.read(1):
            raise RunRejectedError(
                "CREDENTIAL_CHANNEL_REJECTED",
                "credential_ingress",
                "The ephemeral credential channel contains unexpected extra data.",
            )
    finally:
        for index in range(len(secret)):
            secret[index] = 0


def _complete_failure(
    workspace: RunWorkspace,
    journal: Optional[SQLiteAuditJournal],
    context: RunContext,
    started_monotonic: float,
    stages: List[str],
    error: RunError,
    status: RunStatus,
    execution_status: ExecutionStatus,
    event_type: str,
    exit_code: int,
) -> RunOutcome:
    owns_journal = journal is None
    if journal is None:
        journal = SQLiteAuditJournal(
            path=workspace.path / ".audit.sqlite3",
            run_id=context.run_id,
            schema_version=context.schema_version,
            policy_version=context.policy_version,
        )
        journal.append(
            "run.started",
            {
                "mode": context.mode,
                "source": context.source,
                "external_write_egress": False,
            },
        )
        stages.append("audit")
    try:
        journal.append(
            event_type,
            {"error_code": error.code, "stage": error.stage},
        )
        result = _finalize(
            workspace=workspace,
            journal=journal,
            context=context,
            started_monotonic=started_monotonic,
            status=status,
            execution_status=execution_status,
            stages=stages,
            snapshot_id=None,
            technical_command=None,
            external_write_sent=False,
            error=error,
        )
        return RunOutcome(
            exit_code=exit_code,
            run_id=context.run_id,
            status=result.status,
            run_directory=str(workspace.path),
            error_code=error.code,
        )
    finally:
        if owns_journal:
            journal.close()


def run_fixture(
    run_id: str,
    runs_root: Path,
    fixture_path: Path,
    policy_path: Path,
    credential_stream: Optional[BinaryIO] = None,
    credential_profile: Optional[str] = None,
) -> RunOutcome:
    """Execute one immutable simulation run and return a safe process outcome."""

    started_monotonic = time.monotonic()
    initial_rejection: Optional[RunRejectedError] = None
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
        initial_rejection = RunRejectedError(
            "INVALID_RUN_ID",
            "workspace",
            "The requested run identifier is invalid.",
        )
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

    policy_version = "unavailable"
    context = RunContext(
        run_id=run_id,
        schema_version=ARTIFACT_SCHEMA_VERSION,
        policy_version=policy_version,
        mode="SIMULATION",
        evidence_type="SIMULATED",
        source="LOCAL_FIXTURE",
        started_at=_utc_now(),
    )
    journal: Optional[SQLiteAuditJournal] = None
    stages: List[str] = []
    try:
        policy = _load_policy(policy_path)
        policy_version = str(policy["policy_id"])
        context = RunContext(
            run_id=run_id,
            schema_version=ARTIFACT_SCHEMA_VERSION,
            policy_version=policy_version,
            mode="SIMULATION",
            evidence_type="SIMULATED",
            source="LOCAL_FIXTURE",
            started_at=context.started_at,
        )
        journal = SQLiteAuditJournal(
            path=workspace.path / ".audit.sqlite3",
            run_id=run_id,
            schema_version=context.schema_version,
            policy_version=context.policy_version,
        )
        journal.append(
            "run.started",
            {
                "mode": context.mode,
                "source": context.source,
                "external_write_egress": False,
            },
        )
        stages.append("audit")
        if initial_rejection is not None:
            raise initial_rejection
        if credential_stream is not None:
            if credential_profile is None:
                raise RunRejectedError(
                    "CREDENTIAL_PROFILE_REJECTED",
                    "credential_ingress",
                    "The ephemeral credential channel has no trusted profile.",
                )
            try:
                resolve_keychain_binding(policy, credential_profile)
            except CredentialProfileRejected as profile_error:
                raise RunRejectedError(
                    "CREDENTIAL_PROFILE_REJECTED",
                    "credential_ingress",
                    "The credential profile is not authorized for this run.",
                ) from profile_error
            _consume_ephemeral_credential(credential_stream)
            stages.append("credential_ingress")
            journal.append(
                "credential_ingress.completed",
                {
                    "channel": "EPHEMERAL_STDIN",
                    "credential_profile": credential_profile,
                },
            )
        elif credential_profile is not None:
            raise RunRejectedError(
                "CREDENTIAL_PROFILE_REJECTED",
                "credential_ingress",
                "A credential profile requires the ephemeral credential channel.",
            )
        connectors: ConnectorsAPI = FixtureConnectorV1()
        normalization: NormalizationAPI = NormalizerV1()
        analytics: AnalyticsAPI = AnalyticsEngineV1()
        decision_api: DecisionAPI = DecisionEngineV1()
        policy_api: PolicyAPI = SimulationPolicyV1()
        execution_api: ExecutionAPI = SimulationExecutorV1()

        raw_fixture = _load_json_object(
            fixture_path,
            "FIXTURE_INPUT_REJECTED",
            "connectors",
        )
        connected = connectors.read_fixture(context, raw_fixture)
        stages.append("connectors")
        journal.append(
            "connectors.completed",
            {
                "fixture_id": connected.fixture_id,
                "record_count": len(connected.records),
            },
        )

        snapshot = normalization.normalize(context, connected)
        stages.append("normalization")
        journal.append(
            "normalization.completed",
            {"snapshot_id": snapshot.snapshot_id},
        )

        summary = analytics.calculate(context, snapshot)
        stages.append("analytics")
        journal.append(
            "analytics.completed",
            {
                "snapshot_id": summary.snapshot_id,
                "impressions": summary.impressions,
                "clicks": summary.clicks,
                "conversions": summary.conversions,
                "cost_rub": str(summary.cost_rub),
                "ctr": str(summary.ctr),
            },
        )

        decision = decision_api.decide(context, summary)
        stages.append("decision")
        journal.append(
            "decision.completed",
            {"action": decision.action, "reason_code": decision.reason_code},
        )

        policy_decision = policy_api.evaluate(context, decision)
        stages.append("policy")
        journal.append(
            "policy.completed",
            {
                "allowed": policy_decision.allowed,
                "reason_code": policy_decision.reason_code,
                "external_write_egress": policy_decision.external_write_egress,
            },
        )

        execution = execution_api.execute(
            context,
            decision,
            policy_decision,
        )
        stages.append("execution")
        journal.append(
            "execution.completed",
            {
                "execution_status": execution.execution_status,
                "external_write_sent": execution.external_write_sent,
                "technical_command": execution.technical_command,
            },
        )
        result = _finalize(
            workspace=workspace,
            journal=journal,
            context=context,
            started_monotonic=started_monotonic,
            status="SUCCEEDED",
            execution_status=execution.execution_status,
            stages=stages,
            snapshot_id=snapshot.snapshot_id,
            technical_command=execution.technical_command,
            external_write_sent=execution.external_write_sent,
            error=None,
        )
        return RunOutcome(
            exit_code=0,
            run_id=run_id,
            status=result.status,
            run_directory=str(workspace.path),
        )
    except RunRejectedError as rejected:
        error = RunError(
            code=rejected.code,
            message=rejected.safe_message,
            stage=rejected.stage,
        )
        return _complete_failure(
            workspace=workspace,
            journal=journal,
            context=context,
            started_monotonic=started_monotonic,
            stages=stages,
            error=error,
            status="REJECTED",
            execution_status="BLOCKED",
            event_type="run.rejected",
            exit_code=2,
        )
    except Exception:
        error = RunError(
            code="INTERNAL_FAILURE",
            message="The local run failed without exposing internal details.",
            stage="runtime",
        )
        return _complete_failure(
            workspace=workspace,
            journal=journal,
            context=context,
            started_monotonic=started_monotonic,
            stages=stages,
            error=error,
            status="FAILED",
            execution_status="FAILED",
            event_type="run.failed",
            exit_code=1,
        )
    finally:
        if journal is not None:
            journal.close()
