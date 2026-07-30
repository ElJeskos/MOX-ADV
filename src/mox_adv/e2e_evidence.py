"""Read-only E2E safety recording and final evidence artifacts."""

from __future__ import annotations

import hashlib
import json
import socket
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import urlencode, urlparse

from mox_adv.artifacts import RunWorkspace
from mox_adv.audit import SQLiteAuditJournal
from mox_adv.canonical import canonical_json
from mox_adv.egress import (
    CredentialProfile,
    EgressAuthority,
    HttpEgressGuard,
    MatrixAccessClass,
)
from mox_adv.trust_boundary import (
    CapabilityEvidence,
    SimulationAuditAnchorSigner,
    required_capability_contract,
    write_capability_evidence_summary,
)

CAPABILITY_ACCEPTANCE_CASES = required_capability_contract()
REQUIRED_CAPABILITIES = tuple(CAPABILITY_ACCEPTANCE_CASES)
LOCAL_E2E_EXERCISED_CAPABILITIES = frozenset(REQUIRED_CAPABILITIES) - {
    "CLOSED_LOOP_CONTROL"
}
CAPABILITY_EVIDENCE_PATHS = {
    "CAMPAIGN_LIFECYCLE": (
        "lifecycle-evidence.json",
        "change_diff.json",
        "events.jsonl",
    ),
    "GOAL_LIFECYCLE": (
        "lifecycle-evidence.json",
        "events.jsonl",
    ),
    "SOURCE_INTEGRATION": (
        "observe-evidence.json",
        "events.jsonl",
    ),
    "INTEGRATED_ANALYTICS": (
        "observe-evidence.json",
        "result.json",
    ),
    "LLM_ANALYSIS": (
        "proposal.json",
        "events.jsonl",
    ),
    "APPROVAL_REQUIRED": (
        "approval.json",
        "change_diff.json",
        "events.jsonl",
    ),
    "BOUNDED_AUTONOMY": (
        "change_diff.json",
        "events.jsonl",
    ),
    "MONITORING_AND_ALERTING": (
        "monitoring-evidence.json",
        "events.jsonl",
    ),
    "IMPACT_EVALUATION": (
        "impact_report.json",
        "result.json",
    ),
    "OPERATIONAL_MODES": (
        "observe-evidence.json",
        "proposal.json",
        "approval.json",
        "change_diff.json",
    ),
    "TOOL_CONTRACT": (
        "change_diff.json",
        "lifecycle-evidence.json",
        "external-egress.jsonl",
    ),
    "ORIGINAL_INTEGRATION_COVERAGE": (
        "lifecycle-evidence.json",
        "external-egress.jsonl",
    ),
    "SAFETY_CORE": (
        "events.jsonl",
        "external-egress.jsonl",
        "signed-audit-anchor.json",
        "artifact-manifest.json",
    ),
    "CLOSED_LOOP_CONTROL": (),
}
REQUIRED_SUPPLEMENTAL_ARTIFACTS = frozenset(
    {
        "proposal.json",
        "approval.json",
        "change_diff.json",
        "impact_report.json",
        "observe-evidence.json",
        "monitoring-evidence.json",
        "lifecycle-evidence.json",
    }
)
REQUIRED_RUN_SUMMARY_FIELDS = frozenset(
    {
        "source",
        "snapshot_id",
        "period_start",
        "period_end",
        "provenance",
        "metrics",
        "provider",
        "model_id",
        "input_tokens",
        "output_tokens",
        "cost_rub",
        "duration_ms",
        "stage_durations_ms",
        "proposal_id",
        "policy_decision",
        "execution",
    }
)


class ExternalEgressBlocked(PermissionError):
    """The E2E process attempted egress outside its read-only authority."""


@dataclass(frozen=True)
class ExternalReadRecord:
    credential_profile: str
    http_method: str
    url: str
    version: str
    service: str
    operation: str

    def as_dict(self) -> Mapping[str, str]:
        return {
            "credential_profile": self.credential_profile,
            "http_method": self.http_method,
            "url": self.url,
            "version": self.version,
            "service": self.service,
            "operation": self.operation,
        }


class ReadOnlyEgressRecorder:
    """Authorize and record only an exact external Direct Reports read."""

    def __init__(self, policy: Mapping[str, Any]) -> None:
        self._guard = HttpEgressGuard(policy)
        self._matrix = tuple(policy["api_matrix"])
        self._records: list[ExternalReadRecord] = []
        self._blocked_non_read_attempts = 0
        self._local_socket_attempts = 0
        self._browser_interceptions: list[Mapping[str, str]] = []
        self._browser_websocket_attempts: list[str] = []

    @property
    def records(self) -> tuple[ExternalReadRecord, ...]:
        return tuple(self._records)

    @property
    def blocked_non_read_attempts(self) -> int:
        return self._blocked_non_read_attempts

    @property
    def local_socket_attempts(self) -> int:
        return self._local_socket_attempts

    @property
    def browser_interceptions(self) -> tuple[Mapping[str, str], ...]:
        return tuple(self._browser_interceptions)

    @property
    def browser_websocket_attempts(self) -> tuple[str, ...]:
        return tuple(self._browser_websocket_attempts)

    def authorize_external(
        self,
        http_method: str,
        url: str,
        *,
        version: str,
        service: str,
        operation: str,
        authority: EgressAuthority,
    ) -> None:
        matching = [
            item
            for item in self._matrix
            if item["version"] == version
            and item["service"] == service
            and item["method"] == operation
            and item["http_verb"] == http_method.upper()
        ]
        is_explicit_read = (
            authority.credential_profile == CredentialProfile.DIRECT_PROD_READ
            and len(matching) == 1
            and matching[0]["access_class"] == MatrixAccessClass.READ_ONLY
        )
        if not is_explicit_read:
            self._blocked_non_read_attempts += 1
            raise ExternalEgressBlocked(
                "EXTERNAL_NON_READ_EGRESS_BLOCKED_BEFORE_TRANSPORT"
            )
        self._guard.authorize(
            http_method,
            url,
            version=version,
            service=service,
            operation=operation,
            authority=authority,
        )
        self._records.append(
            ExternalReadRecord(
                credential_profile=authority.credential_profile.value,
                http_method=http_method.upper(),
                url=url,
                version=version,
                service=service,
                operation=operation,
            )
        )

    def assert_read_only(self) -> None:
        if self._blocked_non_read_attempts:
            raise ExternalEgressBlocked(
                "A non-read external attempt occurred during this E2E run."
            )

    @contextmanager
    def enforce_python_sockets(self):
        """Deny every non-loopback Python socket before transport."""

        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        original_sendto = socket.socket.sendto
        original_sendmsg = getattr(socket.socket, "sendmsg", None)

        def require_loopback(address: Any) -> None:
            if not isinstance(address, tuple) or not address:
                return
            host = str(address[0])
            if host not in {"127.0.0.1", "::1", "localhost"}:
                self._blocked_non_read_attempts += 1
                raise ExternalEgressBlocked(
                    "EXTERNAL_SOCKET_EGRESS_BLOCKED_BEFORE_TRANSPORT"
                )
            self._local_socket_attempts += 1

        def guarded_connect(instance: socket.socket, address: Any) -> Any:
            require_loopback(address)
            return original_connect(instance, address)

        def guarded_connect_ex(instance: socket.socket, address: Any) -> int:
            require_loopback(address)
            return original_connect_ex(instance, address)

        def guarded_sendto(
            instance: socket.socket,
            data: bytes,
            *args: Any,
        ) -> int:
            if args:
                require_loopback(args[-1])
            return original_sendto(instance, data, *args)

        def guarded_sendmsg(
            instance: socket.socket,
            buffers: Any,
            ancdata: Any = (),
            flags: int = 0,
            address: Any = None,
        ) -> int:
            if address is not None:
                require_loopback(address)
            if original_sendmsg is None:
                raise AttributeError("socket.sendmsg is unavailable")
            if address is None:
                return original_sendmsg(instance, buffers, ancdata, flags)
            return original_sendmsg(instance, buffers, ancdata, flags, address)

        patches = [
            mock.patch.object(socket.socket, "connect", guarded_connect),
            mock.patch.object(socket.socket, "connect_ex", guarded_connect_ex),
            mock.patch.object(socket.socket, "sendto", guarded_sendto),
        ]
        if original_sendmsg is not None:
            patches.append(mock.patch.object(socket.socket, "sendmsg", guarded_sendmsg))
        with ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            yield

    def record_browser_request(
        self,
        http_method: str,
        url: str,
        *,
        expected_counter_id: str,
        expected_event: str,
    ) -> str:
        """Route every browser request through one local-only decision."""

        parsed = urlparse(url)
        if parsed.hostname == "127.0.0.1" and parsed.scheme == "http":
            return "LOCAL"
        expected_path = "/watch/" + expected_counter_id
        if (
            http_method == "POST"
            and parsed.scheme == "https"
            and parsed.hostname == "mc.yandex.ru"
            and parsed.port in {None, 443}
            and parsed.path == expected_path
            and parsed.query == urlencode({"event": expected_event})
            and not parsed.fragment
        ):
            record = {
                "http_method": http_method,
                "url": url,
                "counter_id": expected_counter_id,
                "event": expected_event,
            }
            self._browser_interceptions.append(record)
            return "INTERCEPTED_EVENT"
        self._blocked_non_read_attempts += 1
        raise ExternalEgressBlocked(
            "UNEXPECTED_BROWSER_EGRESS_BLOCKED_BEFORE_TRANSPORT"
        )

    def block_browser_websocket(self, url: str) -> None:
        """Record a browser WebSocket that must not connect to a server."""

        self._browser_websocket_attempts.append(url)
        self._blocked_non_read_attempts += 1

    def browser_event(
        self,
        counter_id: str,
        event: str,
    ) -> Mapping[str, str] | None:
        matches = [
            item
            for item in self._browser_interceptions
            if item["counter_id"] == counter_id and item["event"] == event
        ]
        if len(matches) != 1:
            return None
        return matches[0]


def final_capability_evidence() -> tuple[CapabilityEvidence, ...]:
    """Build the exact 14-capability report without production overclaiming."""

    evidence = []
    for capability in REQUIRED_CAPABILITIES:
        if capability not in LOCAL_E2E_EXERCISED_CAPABILITIES:
            status = "NOT_TESTED"
            evidence_type = "SIMULATED"
            paths: tuple[str, ...] = ()
            limitation = (
                "Полный цикл на одной allowlisted pilot campaign не выполнялся, "
                "поскольку внешние write-действия запрещены для этого E2E run."
            )
        else:
            status = "NOT_PROVEN"
            evidence_type = "SIMULATED"
            paths = CAPABILITY_EVIDENCE_PATHS[capability]
            limitation = (
                "Локальный E2E выполнен с sealed fakes и local interception; "
                "обязательные REAL_READ_ONLY, TEST_COUNTER или CONTROLLED_PILOT "
                "evidence этим run не заменяются."
            )
        evidence.append(
            CapabilityEvidence(
                capability=capability,
                status=status,
                evidence_type=evidence_type,
                acceptance_cases=CAPABILITY_ACCEPTANCE_CASES[capability],
                evidence_paths=paths,
                limitations=(limitation,),
            )
        )
    return tuple(evidence)


def _overall_capability_status(
    capabilities: Sequence[CapabilityEvidence],
) -> str:
    statuses = {item.status for item in capabilities}
    if "NOT_PROVEN" in statuses:
        return "NOT_PROVEN"
    if "INCONCLUSIVE" in statuses:
        return "INCONCLUSIVE"
    if "NOT_TESTED" in statuses:
        return "NOT_TESTED"
    return "PROVEN"


def _report(
    *,
    run_id: str,
    overall_status: str,
    checks: Sequence[Mapping[str, Any]],
    capabilities: Sequence[CapabilityEvidence],
    run_summary: Mapping[str, Any],
    egress: ReadOnlyEgressRecorder,
) -> str:
    lines = [
        "# Итоговый read-only E2E отчёт MOX-ADV",
        "",
        "Оба локальных модуля завершили E2E-проверку с sealed fakes и Playwright local interception.",
        "Реальные внешние write-запросы и отправка событий не выполнялись.",
        f"Идентификатор запуска: `{run_id}`.",
        f"Общий capability status: `{overall_status}`.",
        f"Источник данных: `{run_summary['source']}`.",
        f"Snapshot: `{run_summary['snapshot_id']}`.",
        (
            "Период данных: `"
            + str(run_summary["period_start"])
            + "` — `"
            + str(run_summary["period_end"])
            + "`."
        ),
        f"Внешних read-запросов: `{len(egress.records)}`.",
        f"Локально перехваченных browser events: `{len(egress.browser_interceptions)}`.",
        (
            "Заблокированных browser WebSocket-подключений: `"
            + str(len(egress.browser_websocket_attempts))
            + "`."
        ),
        "",
        "## Проверки",
        "",
    ]
    for check in checks:
        lines.append("- " + str(check["name"]) + ": `" + str(check["status"]) + "`.")
    lines.extend(["", "## Способности", ""])
    for item in capabilities:
        paths = ", ".join(item.evidence_paths) if item.evidence_paths else "нет"
        lines.append(
            "- "
            + item.capability
            + ": status="
            + item.status
            + "; evidence_type="
            + item.evidence_type
            + "; evidence_paths="
            + paths
            + "."
        )
        lines.append("  Ограничение: " + " ".join(item.limitations))
    return "\n".join(lines) + "\n"


def _validate_run_summary(
    run_summary: Mapping[str, Any],
    supplemental_artifacts: Mapping[str, Mapping[str, Any]],
) -> None:
    if set(run_summary) != REQUIRED_RUN_SUMMARY_FIELDS:
        raise ValueError("The final E2E run summary is incomplete.")
    if set(supplemental_artifacts) != REQUIRED_SUPPLEMENTAL_ARTIFACTS:
        raise ValueError("The final E2E supplemental artifact set is incomplete.")
    string_fields = (
        "source",
        "snapshot_id",
        "period_start",
        "period_end",
        "provider",
        "model_id",
        "cost_rub",
        "proposal_id",
    )
    if any(
        not isinstance(run_summary[field], str) or not run_summary[field]
        for field in string_fields
    ):
        raise ValueError("The final E2E run identity fields are invalid.")
    for field in (
        "provenance",
        "metrics",
        "stage_durations_ms",
        "policy_decision",
        "execution",
    ):
        if not isinstance(run_summary[field], Mapping) or not run_summary[field]:
            raise ValueError("The final E2E run detail fields are invalid.")
    for field in ("input_tokens", "output_tokens", "duration_ms"):
        value = run_summary[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("The final E2E numeric metadata is invalid.")
    execution = run_summary["execution"]
    required_execution = {
        "technical_command",
        "before",
        "after",
        "readback",
        "final_object_state",
    }
    if set(execution) != required_execution:
        raise ValueError("The final E2E execution evidence is incomplete.")
    if any(not execution[field] for field in required_execution):
        raise ValueError("The final E2E execution evidence is empty.")
    proposal = supplemental_artifacts["proposal.json"]
    approval = supplemental_artifacts["approval.json"]
    change_diff = supplemental_artifacts["change_diff.json"]
    impact = supplemental_artifacts["impact_report.json"]
    if (
        proposal.get("proposal_id") != run_summary["proposal_id"]
        or not approval.get("approval_id")
        or approval.get("proposal_id") != run_summary["proposal_id"]
        or not approval.get("used_at")
        or not change_diff.get("approval_required")
        or change_diff["approval_required"].get("proposal_id")
        != run_summary["proposal_id"]
        or impact.get("status") != "OBSERVED_POST_CHANGE"
    ):
        raise ValueError("The final E2E stage artifacts are inconsistent.")


def _artifact_digest(path: Path) -> Mapping[str, Any]:
    content = path.read_bytes()
    return {
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _write_artifact_manifest(
    workspace: RunWorkspace,
    *,
    run_id: str,
    policy_version: str,
) -> None:
    signer = SimulationAuditAnchorSigner()
    artifacts = {
        path.relative_to(workspace.path).as_posix(): _artifact_digest(path)
        for path in sorted(workspace.path.rglob("*"))
        if path.is_file() and path.name != "artifact-manifest.json"
    }
    payload = {
        "schema_version": "readonly-e2e-artifact-manifest-v1",
        "run_id": run_id,
        "policy_version": policy_version,
        "artifacts": artifacts,
        "key_id": signer.key_id,
    }
    signature = signer.sign(canonical_json(payload).encode("utf-8"))
    workspace.write_json(
        "artifact-manifest.json",
        {
            **payload,
            "signature": signature,
        },
    )


def verify_e2e_artifact_manifest(run_directory: Path) -> None:
    """Verify signature, exact file set, sizes, and SHA-256 artifact digests."""

    manifest_path = run_directory / "artifact-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("The E2E artifact manifest is unavailable.") from error
    if not isinstance(manifest, Mapping):
        raise TypeError("The E2E artifact manifest is invalid.")
    signature = manifest.get("signature")
    payload = {key: value for key, value in manifest.items() if key != "signature"}
    signer = SimulationAuditAnchorSigner()
    if (
        payload.get("schema_version") != "readonly-e2e-artifact-manifest-v1"
        or payload.get("key_id") != signer.key_id
        or not isinstance(signature, str)
        or not signer.verify(canonical_json(payload).encode("utf-8"), signature)
    ):
        raise ValueError("The E2E artifact manifest signature is invalid.")
    expected = payload.get("artifacts")
    if not isinstance(expected, Mapping):
        raise TypeError("The E2E artifact manifest has no artifact map.")
    actual_paths = {
        path.relative_to(run_directory).as_posix()
        for path in run_directory.rglob("*")
        if path.is_file() and path.name != "artifact-manifest.json"
    }
    if set(expected) != actual_paths:
        raise ValueError("The E2E artifact manifest file set changed.")
    for relative_path, recorded in expected.items():
        if (
            not isinstance(relative_path, str)
            or not isinstance(recorded, Mapping)
            or dict(recorded) != _artifact_digest(run_directory / relative_path)
        ):
            raise ValueError("The E2E artifact manifest digest changed.")


def write_final_e2e_artifacts(
    runs_root: Path,
    *,
    run_id: str,
    policy_version: str,
    checks: Sequence[Mapping[str, Any]],
    egress: ReadOnlyEgressRecorder,
    supplemental_artifacts: Mapping[str, Mapping[str, Any]],
    run_summary: Mapping[str, Any],
    additional_text_artifacts: Callable[[Path], Mapping[str, str]] | None = None,
) -> Path:
    """Write one immutable E2E evidence bundle and deterministic fingerprint."""

    if not checks or any(item.get("status") != "PASSED" for item in checks):
        raise ValueError("Every local E2E check must pass before finalization.")
    _validate_run_summary(run_summary, supplemental_artifacts)
    egress.assert_read_only()
    workspace = RunWorkspace.create(runs_root, run_id)
    capabilities = final_capability_evidence()
    journal = SQLiteAuditJournal(
        workspace.path / ".audit.sqlite3",
        run_id,
        "readonly-e2e-artifacts-v1",
        policy_version,
    )
    journal.append(
        "e2e.started",
        {
            "external_write_allowed": False,
            "event_send_allowed": False,
            "real_read_profile_required": "DIRECT_PROD_READ",
        },
    )
    for check in checks:
        journal.append("e2e.check.passed", dict(check))
    journal.append(
        "llm.proposal.recorded",
        {
            "proposal_id": run_summary["proposal_id"],
            "proposal": dict(supplemental_artifacts["proposal.json"]),
        },
    )
    journal.append(
        "policy.decision.recorded",
        dict(run_summary["policy_decision"]),
    )
    journal.append(
        "executor.result.recorded",
        dict(run_summary["execution"]),
    )
    journal.append(
        "external_egress.verified",
        {
            "external_read_count": len(egress.records),
            "external_non_read_attempt_count": egress.blocked_non_read_attempts,
            "local_socket_attempt_count": egress.local_socket_attempts,
            "browser_interception_count": len(egress.browser_interceptions),
            "browser_websocket_block_count": len(egress.browser_websocket_attempts),
        },
    )
    final_event = journal.append(
        "e2e.completed",
        {
            "local_status": "SUCCEEDED",
            "external_write_sent": False,
            "capability_status": _overall_capability_status(capabilities),
        },
    )
    signer = SimulationAuditAnchorSigner()
    anchor = journal.create_signed_anchor(signer, datetime.now(timezone.utc))
    verification = journal.seal()
    if (
        verification.final_sequence != final_event.sequence
        or verification.final_hash != final_event.event_hash
    ):
        raise RuntimeError("The E2E audit tail does not match completion.")
    journal.export_jsonl(workspace.path / "events.jsonl")
    journal.close()

    for name, value in supplemental_artifacts.items():
        workspace.write_json(name, value)
    egress_text = "".join(
        canonical_json(record.as_dict()) + "\n" for record in egress.records
    )
    workspace.write_text("external-egress.jsonl", egress_text)
    workspace.write_json("signed-audit-anchor.json", anchor.as_dict())
    write_capability_evidence_summary(
        workspace.path / "capability-evidence.json",
        run_id=run_id,
        policy_version=policy_version,
        capabilities=capabilities,
    )

    semantic = {
        "schema_version": "readonly-e2e-stability-v1",
        "policy_version": policy_version,
        "checks": sorted(
            (dict(item) for item in checks),
            key=lambda item: str(item["name"]),
        ),
        "capabilities": [item.as_dict() for item in capabilities],
        "external_egress": [item.as_dict() for item in egress.records],
        "browser_interceptions": [dict(item) for item in egress.browser_interceptions],
        "browser_websocket_attempts": list(egress.browser_websocket_attempts),
        "external_write_sent": False,
        "run_summary": {
            key: value
            for key, value in run_summary.items()
            if key not in {"duration_ms", "stage_durations_ms"}
        },
        "supplemental_artifacts": {
            name: dict(supplemental_artifacts[name])
            for name in sorted(supplemental_artifacts)
        },
    }
    stability_fingerprint = (
        "sha256:" + hashlib.sha256(canonical_json(semantic).encode("utf-8")).hexdigest()
    )
    overall_status = _overall_capability_status(capabilities)
    result = {
        "schema_version": "readonly-e2e-result-v1",
        "policy_version": policy_version,
        "run_id": run_id,
        "status": "SUCCEEDED",
        "execution_status": "APPLIED",
        "evidence_type": "SIMULATED",
        "external_write_sent": False,
        "external_event_sent": False,
        "external_read_count": len(egress.records),
        "external_non_read_attempt_count": egress.blocked_non_read_attempts,
        "local_socket_attempt_count": egress.local_socket_attempts,
        "browser_interception_count": len(egress.browser_interceptions),
        "browser_websocket_block_count": len(egress.browser_websocket_attempts),
        "source": run_summary["source"],
        "snapshot_id": run_summary["snapshot_id"],
        "period_start": run_summary["period_start"],
        "period_end": run_summary["period_end"],
        "provenance": run_summary["provenance"],
        "original_metrics": run_summary["metrics"],
        "metrics": run_summary["metrics"],
        "provider": run_summary["provider"],
        "model_id": run_summary["model_id"],
        "input_tokens": run_summary["input_tokens"],
        "output_tokens": run_summary["output_tokens"],
        "cost_rub": run_summary["cost_rub"],
        "duration_ms": run_summary["duration_ms"],
        "stage_durations_ms": run_summary["stage_durations_ms"],
        "proposal_id": run_summary["proposal_id"],
        "proposal_path": "proposal.json",
        "validation_results": list(checks),
        "blocking_code": None,
        "policy_decision": run_summary["policy_decision"],
        "technical_command": run_summary["execution"]["technical_command"],
        "before": run_summary["execution"]["before"],
        "after": run_summary["execution"]["after"],
        "readback": run_summary["execution"]["readback"],
        "final_object_state": run_summary["execution"]["final_object_state"],
        "approval_path": "approval.json",
        "change_diff_path": "change_diff.json",
        "impact_report_path": "impact_report.json",
        "capability_status": overall_status,
        "capability_count": len(capabilities),
        "capability_evidence_path": "capability-evidence.json",
        "stability_fingerprint": stability_fingerprint,
        "checks": list(checks),
        "audit": {
            "algorithm": "SHA-256",
            "final_sequence": verification.final_sequence,
            "final_hash": verification.final_hash,
            "signed_anchor_path": "signed-audit-anchor.json",
            "artifact_manifest_path": "artifact-manifest.json",
        },
    }
    workspace.write_json("result.json", result)
    workspace.write_text(
        "report.md",
        _report(
            run_id=run_id,
            overall_status=overall_status,
            checks=checks,
            capabilities=capabilities,
            run_summary=run_summary,
            egress=egress,
        ),
    )
    workspace.write_json(
        "stability-fingerprint.json",
        {
            "schema_version": "readonly-e2e-stability-v1",
            "fingerprint": stability_fingerprint,
        },
    )
    if additional_text_artifacts is not None:
        for name, text in additional_text_artifacts(workspace.path).items():
            if Path(name).name != name or not name:
                raise ValueError("An additional E2E artifact name is invalid.")
            workspace.write_text(name, text)
    _write_artifact_manifest(
        workspace,
        run_id=run_id,
        policy_version=policy_version,
    )
    verify_e2e_artifact_manifest(workspace.path)
    return workspace.path
