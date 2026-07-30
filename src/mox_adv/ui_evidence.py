"""Dashboard-facing normative evidence summaries and immutable run bundles."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any, cast

from mox_adv.artifacts import RunWorkspace
from mox_adv.audit import AuditAnchorSigner, SignedAuditAnchor, SQLiteAuditJournal
from mox_adv.canonical import canonical_json
from mox_adv.trust_boundary import (
    CapabilityEvidence,
    SimulationAuditAnchorSigner,
    required_capability_contract,
)

_SCHEMA_VERSION = "dashboard-evidence-v1"
_SUMMARY_SCHEMA_VERSION = "dashboard-evidence-summary-v1"
_RESULT_SCHEMA_VERSION = "dashboard-result-v1"
_MANIFEST_SCHEMA_VERSION = "dashboard-artifact-manifest-v1"
_EVIDENCE_TYPES = frozenset(
    {"SIMULATED", "REAL_READ_ONLY", "TEST_COUNTER", "CONTROLLED_PILOT"}
)
_CAPABILITY_STATUSES = frozenset({"PROVEN", "NOT_PROVEN", "INCONCLUSIVE", "NOT_TESTED"})
_GATE_ORDER = ("GATE_0", "GATE_1", "GATE_2", "GATE_3", "GATE_4")
_GATE_STATUSES = frozenset({"READY", "NOT_READY", "BLOCKED"})
_EXECUTION_STATUSES = frozenset(
    {
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
    }
)
_OPTIONAL_ARTIFACTS = {
    "proposal": ("proposal_path", "proposal.json"),
    "approval": ("approval_path", "approval.json"),
    "change_diff": ("change_diff_path", "change_diff.json"),
    "impact": ("impact_report_path", "impact_report.json"),
}
_REQUIRED_INPUT_FIELDS = (
    "run_id",
    "policy_version",
    "mode",
    "status",
    "execution_status",
    "source",
    "snapshot_id",
    "period_start",
    "period_end",
    "provenance",
    "original_metrics",
    "metrics",
    "provider",
    "model_id",
    "input_tokens",
    "output_tokens",
    "cost_rub",
    "duration_ms",
    "stage_durations_ms",
)
_SENSITIVE_KEY_MARKERS = (
    "access_token",
    "refresh_token",
    "oauth_token",
    "authorization",
    "client_secret",
    "api_key",
    "password",
)
_SENSITIVE_EXACT_KEYS = frozenset({"secret", "token"})
DASHBOARD_GENERATED_EVIDENCE_ARTIFACTS = (
    ".dashboard-audit.sqlite3",
    "artifact-manifest.json",
    "events.jsonl",
    "report.md",
    "result.json",
    "signed-audit-anchor.json",
)
_GENERATED_EVIDENCE_PATHS = frozenset(
    DASHBOARD_GENERATED_EVIDENCE_ARTIFACTS
).difference({".dashboard-audit.sqlite3"})
_CLOSED_LOOP_BINDING_FIELDS = (
    "analytics_campaign_id",
    "proposal_campaign_id",
    "execution_campaign_id",
    "impact_campaign_id",
)


def _json_copy(value: Any) -> Any:
    try:
        return json.loads(canonical_json(value))
    except (TypeError, ValueError) as error:
        raise ValueError("Dashboard evidence must be JSON-serializable.") from error


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(name + " must be a JSON object.")
    return value


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + " must be a non-empty string.")
    return value


def _require_non_negative_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(name + " must be a non-negative integer.")
    return cast(int, value)


def _decimal(value: Any, name: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise TypeError(name + " must be a finite decimal.")
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(name + " must be a finite decimal.") from error
    if not converted.is_finite() or converted < 0 or (positive and converted <= 0):
        raise ValueError(name + " must be a finite decimal.")
    return converted


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _percentage(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _assert_no_sensitive_material(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise TypeError("Dashboard evidence object keys must be strings.")
            lowered = key.casefold()
            if lowered in _SENSITIVE_EXACT_KEYS or any(
                marker in lowered for marker in _SENSITIVE_KEY_MARKERS
            ):
                raise ValueError(
                    "Dashboard evidence contains a sensitive field at "
                    + path
                    + "."
                    + key
                    + "."
                )
            _assert_no_sensitive_material(nested, path + "." + key)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            _assert_no_sensitive_material(nested, path + "[" + str(index) + "]")
        return
    if isinstance(value, str):
        lowered = value.casefold()
        if "authorization: bearer " in lowered or lowered.startswith("bearer "):
            raise ValueError(
                "Dashboard evidence contains sensitive bearer material at " + path + "."
            )


def _relative_artifact_path(value: Any, name: str) -> str:
    path = _require_string(value, name)
    pure_path = PurePosixPath(path)
    if (
        pure_path.is_absolute()
        or ".." in pure_path.parts
        or path != pure_path.as_posix()
    ):
        raise ValueError(name + " must be a safe relative POSIX path.")
    return path


def _artifact_references(run: Mapping[str, Any]) -> Mapping[str, str]:
    raw = run.get("artifact_references", {})
    references = _require_mapping(raw, "artifact_references")
    unknown = set(references).difference(_OPTIONAL_ARTIFACTS)
    if unknown:
        raise ValueError(
            "Unknown Dashboard artifact references: " + ", ".join(sorted(unknown))
        )
    result: dict[str, str] = {}
    for reference, value in references.items():
        field, expected_name = _OPTIONAL_ARTIFACTS[reference]
        relative = _relative_artifact_path(value, "artifact_references." + reference)
        if relative != expected_name:
            raise ValueError(
                "Dashboard " + reference + " evidence must use " + expected_name + "."
            )
        result[field] = relative
    return result


def _cost_policy(run: Mapping[str, Any]) -> Mapping[str, Any]:
    used = _decimal(run["cost_rub"], "cost_rub")
    limit = _decimal(
        run.get("cost_limit_rub", "2000.00"), "cost_limit_rub", positive=True
    )
    utilization = used * Decimal(100) / limit
    if utilization >= Decimal(100):
        state = "BLOCKED"
    elif utilization >= Decimal(80):
        state = "WARNING"
    else:
        state = "OK"
    tariff_version = _require_string(
        run.get("tariff_version", "NOT_RECORDED"),
        "tariff_version",
    )
    exchange_rate_version = _require_string(
        run.get("exchange_rate_version", "NOT_RECORDED"),
        "exchange_rate_version",
    )
    return {
        "used_rub": _money(used),
        "limit_rub": _money(limit),
        "utilization_percent": _percentage(utilization),
        "state": state,
        "new_model_calls_allowed": state != "BLOCKED",
        "tariff_version": tariff_version,
        "exchange_rate_version": exchange_rate_version,
    }


def _closed_loop_target_binding(run: Mapping[str, Any]) -> Mapping[str, str]:
    binding = _require_mapping(run.get("target_binding", {}), "target_binding")
    missing = [field for field in _CLOSED_LOOP_BINDING_FIELDS if field not in binding]
    if missing:
        raise ValueError(
            "CLOSED_LOOP_CONTROL target binding is missing fields: "
            + ", ".join(missing)
        )
    values = {
        field: _require_string(binding.get(field), "target_binding." + field)
        for field in _CLOSED_LOOP_BINDING_FIELDS
    }
    if len(set(values.values())) != 1:
        raise ValueError(
            "CLOSED_LOOP_CONTROL target binding must identify one campaign."
        )
    return values


def _capability_summary(run: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    contract = required_capability_contract()
    raw = _require_mapping(run.get("capability_evidence", {}), "capability_evidence")
    unknown = set(raw).difference(contract)
    if unknown:
        raise ValueError("Unknown capabilities: " + ", ".join(sorted(unknown)))
    default_type = _require_string(run["evidence_type"], "evidence_type")
    result = []
    for capability, acceptance_cases in contract.items():
        supplied = raw.get(capability)
        if supplied is None:
            item = CapabilityEvidence(
                capability=capability,
                status="NOT_TESTED",
                evidence_type=default_type,
                acceptance_cases=acceptance_cases,
                evidence_paths=(),
                limitations=("Эта способность не проверялась в данном Dashboard run.",),
            )
            result.append(item.as_dict())
            continue
        evidence = _require_mapping(
            supplied,
            "capability_evidence." + capability,
        )
        status = _require_string(evidence.get("status"), capability + ".status")
        evidence_type = _require_string(
            evidence.get("evidence_type", default_type),
            capability + ".evidence_type",
        )
        if status not in _CAPABILITY_STATUSES:
            raise ValueError(capability + " capability status is invalid.")
        if evidence_type not in _EVIDENCE_TYPES:
            raise ValueError(capability + " evidence type is invalid.")
        if status == "PROVEN" and evidence_type == "SIMULATED":
            raise ValueError(
                "SIMULATED capability evidence cannot claim PROVEN status."
            )
        if (
            capability == "CLOSED_LOOP_CONTROL"
            and status == "PROVEN"
            and evidence_type != "CONTROLLED_PILOT"
        ):
            raise ValueError("CLOSED_LOOP_CONTROL requires CONTROLLED_PILOT evidence.")
        if capability == "CLOSED_LOOP_CONTROL" and status == "PROVEN":
            _closed_loop_target_binding(run)
        raw_paths = evidence.get("evidence_paths", ())
        raw_limitations = evidence.get("limitations", ())
        if not isinstance(raw_paths, Sequence) or isinstance(raw_paths, str):
            raise TypeError(capability + " evidence paths are invalid.")
        if not isinstance(raw_limitations, Sequence) or isinstance(
            raw_limitations, str
        ):
            raise TypeError(capability + " limitations are invalid.")
        paths = tuple(
            _relative_artifact_path(path, capability + ".evidence_paths")
            for path in raw_paths
        )
        limitations = tuple(
            _require_string(item, capability + ".limitations")
            for item in raw_limitations
        )
        if status == "NOT_TESTED" and paths:
            raise ValueError("NOT_TESTED capability evidence cannot cite paths.")
        item = CapabilityEvidence(
            capability=capability,
            status=status,
            evidence_type=evidence_type,
            acceptance_cases=acceptance_cases,
            evidence_paths=paths,
            limitations=limitations,
        )
        result.append(item.as_dict())
    return tuple(result)


def _gate_summary(run: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = _require_mapping(run.get("gates", {}), "gates")
    unknown = set(raw).difference(_GATE_ORDER)
    if unknown:
        raise ValueError("Unknown gates: " + ", ".join(sorted(unknown)))
    result = []
    previous_ready = True
    for gate in _GATE_ORDER:
        supplied = _require_mapping(raw.get(gate, {}), "gates." + gate)
        status = _require_string(supplied.get("status", "NOT_READY"), gate + ".status")
        if status not in _GATE_STATUSES:
            raise ValueError(gate + " status is invalid.")
        raw_paths = supplied.get("evidence_paths", ())
        raw_limitations = supplied.get("limitations", ())
        if not isinstance(raw_paths, Sequence) or isinstance(raw_paths, str):
            raise TypeError(gate + " evidence paths are invalid.")
        if not isinstance(raw_limitations, Sequence) or isinstance(
            raw_limitations, str
        ):
            raise TypeError(gate + " limitations are invalid.")
        paths = tuple(
            _relative_artifact_path(path, gate + ".evidence_paths")
            for path in raw_paths
        )
        limitations = tuple(
            _require_string(item, gate + ".limitations") for item in raw_limitations
        )
        if status == "READY" and not paths:
            raise ValueError(gate + " READY status requires evidence paths.")
        if status == "READY" and not previous_ready:
            raise ValueError(gate + " cannot be READY before earlier gates.")
        if (
            gate == "GATE_4"
            and status == "READY"
            and run["evidence_type"] != "CONTROLLED_PILOT"
        ):
            raise ValueError("GATE_4 READY requires CONTROLLED_PILOT evidence.")
        if status != "READY" and not limitations:
            limitations = ("Подтверждающие материалы для этого gate ещё не приложены.",)
        result.append(
            {
                "gate": gate,
                "status": status,
                "evidence_paths": list(paths),
                "limitations": list(limitations),
            }
        )
        previous_ready = previous_ready and status == "READY"
    return tuple(result)


def build_dashboard_evidence_summary(
    run: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Build an honest JSON-ready capability, gate, and cost summary."""

    run = _require_mapping(run, "run")
    missing = [name for name in _REQUIRED_INPUT_FIELDS if name not in run]
    if missing:
        raise ValueError("Dashboard evidence is missing fields: " + ", ".join(missing))
    _assert_no_sensitive_material(run)
    for name in (
        "run_id",
        "policy_version",
        "mode",
        "status",
        "source",
        "snapshot_id",
        "period_start",
        "period_end",
        "provider",
        "model_id",
    ):
        _require_string(run[name], name)
    evidence_type = _require_string(
        run.get("evidence_type", "SIMULATED"),
        "evidence_type",
    )
    if evidence_type not in _EVIDENCE_TYPES:
        raise ValueError("Dashboard evidence_type is invalid.")
    normalized_run = dict(run)
    normalized_run["evidence_type"] = evidence_type
    execution_status = _require_string(run["execution_status"], "execution_status")
    if execution_status not in _EXECUTION_STATUSES:
        raise ValueError("Dashboard execution_status is invalid.")
    _require_mapping(run["provenance"], "provenance")
    _require_mapping(run["original_metrics"], "original_metrics")
    _require_mapping(run["metrics"], "metrics")
    _require_non_negative_integer(run["input_tokens"], "input_tokens")
    _require_non_negative_integer(run["output_tokens"], "output_tokens")
    _require_non_negative_integer(run["duration_ms"], "duration_ms")
    durations = _require_mapping(run["stage_durations_ms"], "stage_durations_ms")
    for stage, duration in durations.items():
        _require_string(stage, "stage_durations_ms key")
        _require_non_negative_integer(duration, "stage_durations_ms." + stage)
    references = _artifact_references(normalized_run)
    capabilities = _capability_summary(normalized_run)
    gates = _gate_summary(normalized_run)
    cost_policy = _cost_policy(normalized_run)
    overall_status = (
        "PROVEN"
        if all(item["status"] == "PROVEN" for item in capabilities)
        and all(item["status"] == "READY" for item in gates)
        else "NOT_PROVEN"
    )
    limitations = run.get("limitations", ())
    if not isinstance(limitations, Sequence) or isinstance(limitations, str):
        raise TypeError("Dashboard limitations are invalid.")
    summary = {
        "schema_version": _SUMMARY_SCHEMA_VERSION,
        "run_id": run["run_id"],
        "policy_version": run["policy_version"],
        "mode": run["mode"],
        "evidence_type": evidence_type,
        "overall_status": overall_status,
        "capabilities": list(capabilities),
        "gates": list(gates),
        "cost_policy": dict(cost_policy),
        "artifact_references": dict(references),
        "limitations": [_require_string(item, "limitations") for item in limitations],
    }
    if "target_binding" in normalized_run:
        summary["target_binding"] = dict(_closed_loop_target_binding(normalized_run))
    return cast(Mapping[str, Any], _json_copy(summary))


def _result_document(
    run: Mapping[str, Any],
    summary: Mapping[str, Any],
    *,
    final_sequence: int,
    final_hash: str,
) -> Mapping[str, Any]:
    result = {
        "schema_version": _RESULT_SCHEMA_VERSION,
        "policy_version": run["policy_version"],
        "run_id": run["run_id"],
        "mode": run["mode"],
        "status": run["status"],
        "execution_status": run["execution_status"],
        "evidence_type": summary["evidence_type"],
        "source": run["source"],
        "snapshot_id": run["snapshot_id"],
        "period_start": run["period_start"],
        "period_end": run["period_end"],
        "provenance": _json_copy(run["provenance"]),
        "original_metrics": _json_copy(run["original_metrics"]),
        "metrics": _json_copy(run["metrics"]),
        "validation_results": _json_copy(run.get("validation_results", [])),
        "blocking_code": run.get("blocking_code"),
        "policy_decision": _json_copy(run.get("policy_decision", {})),
        "technical_command": _json_copy(run.get("technical_command", {})),
        "before": _json_copy(run.get("before", {})),
        "after": _json_copy(run.get("after", {})),
        "readback": _json_copy(run.get("readback", {})),
        "final_object_state": _json_copy(run.get("final_object_state")),
        "provider": run["provider"],
        "model_id": run["model_id"],
        "input_tokens": run["input_tokens"],
        "output_tokens": run["output_tokens"],
        "cost_rub": summary["cost_policy"]["used_rub"],
        "cost_policy": _json_copy(summary["cost_policy"]),
        "duration_ms": run["duration_ms"],
        "stage_durations_ms": _json_copy(run["stage_durations_ms"]),
        "evidence_summary": _json_copy(summary),
        "audit": {
            "algorithm": "SHA-256",
            "final_sequence": final_sequence,
            "final_hash": final_hash,
            "signed_anchor_path": "signed-audit-anchor.json",
            "artifact_manifest_path": "artifact-manifest.json",
        },
    }
    result.update(summary["artifact_references"])
    return result


def _report_markdown(
    run: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> str:
    cost = summary["cost_policy"]
    lines = [
        "# Отчёт Dashboard MOX-ADV",
        "",
        f"Идентификатор запуска: `{run['run_id']}`.",
        f"Режим: `{run['mode']}`.",
        f"Тип доказательства: `{summary['evidence_type']}`.",
        f"Статус запуска: `{run['status']}`.",
        f"Статус исполнения: `{run['execution_status']}`.",
        f"Общий статус: `{summary['overall_status']}`.",
        f"Источник данных: `{run['source']}`.",
        f"Snapshot: `{run['snapshot_id']}`.",
        f"Период данных: `{run['period_start']}` — `{run['period_end']}`.",
        "",
        "## Использование модели",
        "",
        f"Provider: `{run['provider']}`.",
        f"Model ID: `{run['model_id']}`.",
        f"Входных токенов: `{run['input_tokens']}`.",
        f"Выходных токенов: `{run['output_tokens']}`.",
        f"Стоимость: `{cost['used_rub']} ₽` из `{cost['limit_rub']} ₽`.",
        f"Состояние лимита стоимости: `{cost['state']}`.",
        f"Общая длительность: `{run['duration_ms']} мс`.",
        "",
        "## Способности",
        "",
    ]
    for capability in summary["capabilities"]:
        paths = ", ".join(capability["evidence_paths"]) or "нет"
        lines.append(
            "- `"
            + capability["capability"]
            + "`: статус `"
            + capability["status"]
            + "`, тип `"
            + capability["evidence_type"]
            + "`, evidence paths: "
            + paths
            + "."
        )
        for limitation in capability["limitations"]:
            lines.append("  Ограничение: " + limitation)
    lines.extend(["", "## Готовность Gate 0–4", ""])
    for gate in summary["gates"]:
        paths = ", ".join(gate["evidence_paths"]) or "нет"
        lines.append(
            "- `"
            + gate["gate"]
            + "`: статус `"
            + gate["status"]
            + "`, evidence paths: "
            + paths
            + "."
        )
        for limitation in gate["limitations"]:
            lines.append("  Ограничение: " + limitation)
    lines.extend(["", "## Общие ограничения", ""])
    if summary["limitations"]:
        for limitation in summary["limitations"]:
            lines.append("- " + limitation)
    else:
        lines.append("- Дополнительные ограничения не заявлены.")
    if summary["artifact_references"]:
        lines.extend(["", "## Дополнительные артефакты", ""])
        for field, path in sorted(summary["artifact_references"].items()):
            lines.append("- `" + field + "`: `" + path + "`.")
    return "\n".join(lines) + "\n"


def _artifact_digest(path: Path) -> Mapping[str, Any]:
    content = path.read_bytes()
    return {
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _write_manifest(
    workspace: RunWorkspace,
    *,
    run_id: str,
    policy_version: str,
    signer: AuditAnchorSigner,
) -> None:
    artifacts = {
        path.relative_to(workspace.path).as_posix(): _artifact_digest(path)
        for path in sorted(workspace.path.rglob("*"))
        if path.is_file() and path.name != "artifact-manifest.json"
    }
    payload = {
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "policy_version": policy_version,
        "algorithm": "SHA-256",
        "artifacts": artifacts,
        "key_id": signer.key_id,
    }
    workspace.write_json(
        "artifact-manifest.json",
        {
            **payload,
            "signature": signer.sign(canonical_json(payload).encode("utf-8")),
        },
    )


def _select_signer(
    evidence_type: str,
    signer: AuditAnchorSigner | None,
) -> AuditAnchorSigner:
    if signer is None:
        if evidence_type == "CONTROLLED_PILOT":
            raise ValueError(
                "CONTROLLED_PILOT evidence requires a non-simulation audit signer."
            )
        return SimulationAuditAnchorSigner()
    if evidence_type == "CONTROLLED_PILOT" and isinstance(
        signer, SimulationAuditAnchorSigner
    ):
        raise ValueError(
            "CONTROLLED_PILOT evidence requires a non-simulation audit signer."
        )
    return signer


def _validate_referenced_files(
    run_directory: Path,
    summary: Mapping[str, Any],
) -> None:
    for relative in summary["artifact_references"].values():
        path = run_directory / relative
        if not path.is_file():
            raise ValueError(
                "Referenced Dashboard evidence artifact is missing: " + relative
            )
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(
                "Referenced Dashboard evidence artifact is not valid JSON: " + relative
            ) from error
        _assert_no_sensitive_material(value, "$artifact." + relative)
    available = _GENERATED_EVIDENCE_PATHS.union(summary["artifact_references"].values())
    cited = set()
    for capability in summary["capabilities"]:
        cited.update(capability["evidence_paths"])
    for gate in summary["gates"]:
        cited.update(gate["evidence_paths"])
    missing = cited.difference(available)
    if missing:
        raise ValueError(
            "Dashboard evidence cites unavailable artifacts: "
            + ", ".join(sorted(missing))
        )


def write_dashboard_evidence_bundle(
    run_directory: Path,
    run: Mapping[str, Any],
    *,
    signer: AuditAnchorSigner | None = None,
    anchored_at: datetime | None = None,
) -> Mapping[str, Any]:
    """Write normative immutable Dashboard evidence into one run directory."""

    summary = build_dashboard_evidence_summary(run)
    selected_signer = _select_signer(str(summary["evidence_type"]), signer)
    anchored_at = anchored_at or datetime.now(timezone.utc)
    if anchored_at.tzinfo is None or anchored_at.utcoffset() is None:
        raise ValueError("Dashboard audit anchor time must be timezone-aware.")
    run_directory.mkdir(parents=True, exist_ok=True)
    _validate_referenced_files(run_directory, summary)
    existing = [
        name
        for name in DASHBOARD_GENERATED_EVIDENCE_ARTIFACTS
        if (run_directory / name).exists()
    ]
    if existing:
        raise FileExistsError(
            "Dashboard evidence artifacts are immutable: " + ", ".join(sorted(existing))
        )
    workspace = RunWorkspace(run_directory)
    journal = SQLiteAuditJournal(
        run_directory / ".dashboard-audit.sqlite3",
        str(run["run_id"]),
        _SCHEMA_VERSION,
        str(run["policy_version"]),
    )
    try:
        journal.append(
            "dashboard.run.recorded",
            {
                "mode": run["mode"],
                "status": run["status"],
                "execution_status": run["execution_status"],
                "evidence_type": summary["evidence_type"],
                "snapshot_id": run["snapshot_id"],
            },
        )
        journal.append(
            "dashboard.model_cost.evaluated",
            dict(summary["cost_policy"]),
        )
        journal.append(
            "dashboard.policy_decision.recorded",
            _json_copy(run.get("policy_decision", {})),
        )
        journal.append(
            "dashboard.executor_result.recorded",
            {
                "technical_command": _json_copy(run.get("technical_command", {})),
                "before": _json_copy(run.get("before", {})),
                "after": _json_copy(run.get("after", {})),
                "readback": _json_copy(run.get("readback", {})),
                "final_object_state": _json_copy(run.get("final_object_state")),
            },
        )
        journal.append(
            "dashboard.capabilities.evaluated",
            {
                "overall_status": summary["overall_status"],
                "capabilities": _json_copy(summary["capabilities"]),
            },
        )
        journal.append(
            "dashboard.gates.evaluated",
            {"gates": _json_copy(summary["gates"])},
        )
        if summary["artifact_references"]:
            journal.append(
                "dashboard.artifacts.linked",
                dict(summary["artifact_references"]),
            )
        final_event = journal.append(
            "dashboard.evidence.completed",
            {
                "status": run["status"],
                "overall_status": summary["overall_status"],
                "artifact_references": dict(summary["artifact_references"]),
            },
        )
        anchor = journal.create_signed_anchor(selected_signer, anchored_at)
        verification = journal.seal()
        if (
            verification.final_sequence != final_event.sequence
            or verification.final_hash != final_event.event_hash
        ):
            raise RuntimeError("Dashboard audit tail does not match completion.")
        journal.export_jsonl(run_directory / "events.jsonl")
    finally:
        journal.close()
    workspace.write_json("signed-audit-anchor.json", anchor.as_dict())
    result = _result_document(
        run,
        summary,
        final_sequence=verification.final_sequence,
        final_hash=verification.final_hash,
    )
    workspace.write_json("result.json", result)
    workspace.write_text("report.md", _report_markdown(run, summary))
    _write_manifest(
        workspace,
        run_id=str(run["run_id"]),
        policy_version=str(run["policy_version"]),
        signer=selected_signer,
    )
    return summary


def _verify_manifest(
    run_directory: Path,
    signer: AuditAnchorSigner,
) -> None:
    try:
        manifest = json.loads(
            (run_directory / "artifact-manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Dashboard artifact manifest is unavailable.") from error
    if not isinstance(manifest, Mapping):
        raise TypeError("Dashboard artifact manifest is invalid.")
    signature = manifest.get("signature")
    payload = {key: value for key, value in manifest.items() if key != "signature"}
    if (
        payload.get("schema_version") != _MANIFEST_SCHEMA_VERSION
        or payload.get("key_id") != signer.key_id
        or not isinstance(signature, str)
        or not signer.verify(canonical_json(payload).encode("utf-8"), signature)
    ):
        raise ValueError("Dashboard artifact manifest signature is invalid.")
    expected = payload.get("artifacts")
    if not isinstance(expected, Mapping):
        raise TypeError("Dashboard artifact manifest has no artifact map.")
    actual_paths = {
        path.relative_to(run_directory).as_posix()
        for path in run_directory.rglob("*")
        if path.is_file() and path.name != "artifact-manifest.json"
    }
    if set(expected) != actual_paths:
        raise ValueError("Dashboard artifact manifest file set changed.")
    for relative, digest in expected.items():
        if (
            not isinstance(relative, str)
            or not isinstance(digest, Mapping)
            or dict(digest) != _artifact_digest(run_directory / relative)
        ):
            raise ValueError("Dashboard artifact manifest digest changed.")


def _verify_exported_hash_chain(run_directory: Path) -> tuple[int, str]:
    try:
        lines = (
            (run_directory / "events.jsonl").read_text(encoding="utf-8").splitlines()
        )
        events = [json.loads(line) for line in lines]
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Dashboard events hash chain is unavailable.") from error
    if not events:
        raise ValueError("Dashboard events hash chain is empty.")
    previous_hash = "0" * 64
    for expected_sequence, event in enumerate(events, start=1):
        if not isinstance(event, Mapping):
            raise TypeError("Dashboard events hash chain is invalid.")
        canonical = {
            "sequence": event.get("sequence"),
            "run_id": event.get("run_id"),
            "schema_version": event.get("schema_version"),
            "policy_version": event.get("policy_version"),
            "occurred_at": event.get("occurred_at"),
            "event_type": event.get("event_type"),
            "payload": event.get("payload"),
            "previous_hash": event.get("previous_hash"),
        }
        expected_hash = hashlib.sha256(
            canonical_json(canonical).encode("utf-8")
        ).hexdigest()
        if (
            event.get("sequence") != expected_sequence
            or event.get("previous_hash") != previous_hash
            or event.get("event_hash") != expected_hash
        ):
            raise ValueError("Dashboard events hash chain is invalid.")
        previous_hash = expected_hash
    return len(events), previous_hash


def verify_dashboard_evidence_bundle(
    run_directory: Path,
    *,
    signer: AuditAnchorSigner | None = None,
    now: datetime | None = None,
    maximum_anchor_age: timedelta = timedelta(days=30),
) -> Mapping[str, Any]:
    """Verify the manifest, exported chain, SQLite journal, and signed anchor."""

    try:
        anchor_value = json.loads(
            (run_directory / "signed-audit-anchor.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Dashboard signed audit anchor is unavailable.") from error
    if not isinstance(anchor_value, Mapping):
        raise TypeError("Dashboard signed audit anchor is invalid.")
    anchor = SignedAuditAnchor.from_mapping(anchor_value)
    selected_signer = signer
    if selected_signer is None and anchor.key_id == SimulationAuditAnchorSigner.key_id:
        selected_signer = SimulationAuditAnchorSigner()
    if selected_signer is None or selected_signer.key_id != anchor.key_id:
        raise ValueError("Dashboard audit signer is required for this evidence.")
    _verify_manifest(run_directory, selected_signer)
    exported_sequence, exported_hash = _verify_exported_hash_chain(run_directory)
    journal = SQLiteAuditJournal.open(run_directory / ".dashboard-audit.sqlite3")
    try:
        verification = journal.verify_signed_anchor(
            anchor,
            selected_signer,
            now=now or datetime.now(timezone.utc),
            maximum_age=maximum_anchor_age,
        )
    finally:
        journal.close()
    if (
        verification.final_sequence != exported_sequence
        or verification.final_hash != exported_hash
    ):
        raise ValueError("Dashboard exported hash chain differs from audit journal.")
    try:
        result = json.loads((run_directory / "result.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Dashboard result.json is unavailable.") from error
    if not isinstance(result, Mapping):
        raise TypeError("Dashboard result.json is invalid.")
    audit = result.get("audit")
    if (
        not isinstance(audit, Mapping)
        or audit.get("final_sequence") != verification.final_sequence
        or audit.get("final_hash") != verification.final_hash
    ):
        raise ValueError("Dashboard result does not match the audit anchor.")
    return cast(Mapping[str, Any], _json_copy(result))
