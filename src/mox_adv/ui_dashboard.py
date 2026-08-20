"""Integrated localhost application facade for the MOX-ADV Dashboard."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any

from mox_adv.campaign_lifecycle import (
    SAGA_STEPS,
    CampaignDraftSafetyBindings,
)
from mox_adv.canonical import canonical_json
from mox_adv.control_state import (
    DurableControlState,
    MacOSLocalPrincipalAuthenticator,
)
from mox_adv.mandate_signing import HMACMandateSigner
from mox_adv.mandate_store import DurableMandateAuthority
from mox_adv.trust_boundary import required_capability_contract
from mox_adv.ui_campaign import (
    DashboardCampaignLaunchHistory,
    DashboardCampaignRejected,
    DashboardCampaignStore,
)
from mox_adv.ui_control_plane import DashboardControlPlane
from mox_adv.ui_evidence import (
    DASHBOARD_GENERATED_EVIDENCE_ARTIFACTS,
    verify_dashboard_evidence_bundle,
    write_dashboard_evidence_bundle,
)
from mox_adv.ui_goal import DashboardGoalLifecycleHistory
from mox_adv.ui_workflows import DashboardWorkflowFacade

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "gate0-policy.json"
IMPACT_FIXTURES = ROOT / "fixtures" / "impact"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DOWNLOADABLE_ARTIFACTS = frozenset(
    {
        "acceptance-report.html",
    }
)


class DashboardApplication:
    """Compose the safe control plane, workflows, and evidence for localhost UI."""

    def __init__(
        self,
        runs_root: Path,
        run_service: Any | None = None,
        authenticator: Any | None = None,
    ) -> None:
        self.runs_root = Path(runs_root)
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.run_service = run_service
        self.policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        self.authenticator = authenticator or MacOSLocalPrincipalAuthenticator(
            expected_identity=str(self.policy["principals"]["owner"]["identity"])
        )
        campaign_safety = CampaignDraftSafetyBindings(
            allowed_landing_hosts=("allowlisted.example",),
            prohibited_phrases=("guaranteed results",),
            prepared_media_references=(
                "prepared-media-1",
                "prepared-media-2",
            ),
        )
        self.campaign_store = DashboardCampaignStore(
            self.runs_root / "ui-campaign.sqlite3",
            policy=self.policy,
            campaign_safety=campaign_safety,
        )
        self.campaign_launch_history = DashboardCampaignLaunchHistory(self.runs_root)
        self.goal_lifecycle_history = DashboardGoalLifecycleHistory(self.runs_root)
        control_path = self.runs_root / "ui-control-plane.sqlite3"
        self.control_state = DurableControlState(control_path)
        self.mandate_authority = DurableMandateAuthority(
            control_path,
            self.policy,
            HMACMandateSigner(b"mox-adv-dashboard-simulation-control-key"),
        )
        self.control = DashboardControlPlane(
            self.control_state,
            self.mandate_authority,
            self.policy,
        )
        if self.run_service is not None:
            self.run_service.configure_bounded_autonomy(
                self.control_state,
                self.mandate_authority,
            )
            self.run_service.configure_operating_mode_provider(
                lambda: "BOUNDED_AUTONOMY"
            )
            self.run_service.configure_campaign_context_provider(
                self.campaign_store.analysis_context
            )
        self.workflows = DashboardWorkflowFacade(
            runs_root=self.runs_root,
            policy_path=POLICY_PATH,
            campaign_safety=campaign_safety,
        )
        self._reconcile_completed_goal_evidence()

    def control_overview(self) -> dict[str, Any]:
        return self.control.overview(
            now=datetime.now(timezone.utc),
            environment="SIMULATION",
        )

    def select_operating_mode(self, mode: str) -> dict[str, Any]:
        return self.control.select_mode(
            mode,
            self.authenticator.authenticate(),
            datetime.now(timezone.utc),
        )

    def engage_kill_switch(self, scope: str) -> dict[str, Any]:
        return self.control.engage_kill_switch(
            self._scope_value(scope),
            "Dashboard incident principal engaged the kill switch.",
            self.authenticator.authenticate(),
            datetime.now(timezone.utc),
        )

    def release_kill_switch(
        self,
        scope: str,
        confirmation: str,
    ) -> dict[str, Any]:
        if confirmation != "RELEASE":
            raise ValueError("ELEVATED_RELEASE_CONFIRMATION_REQUIRED")
        return self.control.release_kill_switch(
            self._scope_value(scope),
            "Dashboard incident principal released the kill switch.",
            self.authenticator.elevated_reauthenticate(),
            datetime.now(timezone.utc),
        )

    def issue_test_mandate(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        simulation = self.policy["bindings"]["simulation"]
        mandate = self.policy["mandate"]
        payload = {
            "organization": simulation["organization"],
            "connection": simulation["connection"],
            "account": simulation["direct_account"],
            "environment": "SIMULATION",
            "credential_profile": "DIRECT_PILOT_WRITE",
            "targets": ["sim-campaign"],
            "allowed_action_classes": list(mandate["allowed_action_classes"]),
            "prohibited_action_classes": list(mandate["prohibited_action_classes"]),
            "total_monetary_limit": 500,
            "daily_monetary_limit": 500,
            "maximum_step_change": 10,
            "maximum_daily_change": 10,
            "kpi": dict(mandate["kpi"]),
            "minimum_sample": dict(mandate["minimum_sample"]),
            "cooldown": {
                "hours": 72,
                "observation_window_hours": 72,
            },
            "stop_conditions": list(mandate["stop_conditions"]),
            "action_quotas": {"actions_per_24h": 1},
            "platform_side_spend_cap": 3000,
            "issuer": dict(self.policy["principals"]["mandate_issuer"]),
            "policy_version": self.policy["policy_id"],
            "issued_at": now.isoformat(),
            "expiry": (now + timedelta(hours=24)).isoformat(),
        }
        issued = self.control.issue_mandate(
            payload,
            self.authenticator.authenticate(),
            now,
        )
        return self.control.activate_mandate(
            str(issued["mandate_id"]),
            self.authenticator.authenticate(),
            now,
        )

    def configure_test_automation(
        self,
        value: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Enable one autonomous policy without exposing authority modes."""

        if self.run_service is None:
            raise ValueError("UI_RUN_SERVICE_UNAVAILABLE")
        normalized = dict(value)
        normalized["mode"] = "test"
        normalized["operating_mode"] = "BOUNDED_AUTONOMY"
        if bool(normalized.get("enabled")):
            active = next(
                (
                    item
                    for item in self.control.list_mandates(
                        now=datetime.now(timezone.utc)
                    )
                    if item["status"] == "ACTIVE"
                ),
                None,
            )
            if active is None:
                self.issue_test_mandate()
        return self.run_service.configure_automation(normalized)

    def revoke_latest_mandate(self) -> dict[str, Any]:
        mandates = self.control.list_mandates(now=datetime.now(timezone.utc))
        active = next(
            (item for item in mandates if item["status"] in {"ACTIVE", "ISSUED"}),
            None,
        )
        if active is None:
            raise ValueError("ACTIVE_MANDATE_NOT_FOUND")
        return self.control.revoke_mandate(
            str(active["mandate_id"]),
            "Dashboard operator revoked the simulation Mandate.",
            self.authenticator.authenticate(),
            datetime.now(timezone.utc),
        )

    def grant_pending_proposal(self, run_id: str) -> dict[str, Any]:
        if self.run_service is None:
            raise ValueError("UI_RUN_SERVICE_UNAVAILABLE")
        prepared = self.run_service.prepare_pending_approval(run_id)
        return self.control.grant_approval(
            proposal_id=prepared.proposal_id,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            reason="Dashboard operator approved the exact immutable proposal.",
            principal=self.authenticator.authenticate(),
            now=datetime.now(timezone.utc),
        )

    def revise_pending_proposal(
        self,
        run_id: str,
        relative_step_percent: int,
    ) -> dict[str, Any]:
        if self.run_service is None:
            raise ValueError("UI_RUN_SERVICE_UNAVAILABLE")
        return self.run_service.revise_pending_run(
            run_id,
            relative_step_percent=relative_step_percent,
        )

    def revoke_approval(self, approval_id: str) -> dict[str, Any]:
        if not approval_id:
            raise ValueError("APPROVAL_ID_REQUIRED")
        return self.control.revoke_approval(
            approval_id,
            self.authenticator.authenticate(),
            datetime.now(timezone.utc),
        )

    def apply_approved_proposal(self, run_id: str) -> dict[str, Any]:
        if self.run_service is None:
            raise ValueError("UI_RUN_SERVICE_UNAVAILABLE")
        return self.run_service.approve_pending_run(run_id)

    def campaign_catalog(self) -> dict[str, Any]:
        return self.campaign_store.catalog()

    def campaign_overview(
        self,
        draft_id: str | None = None,
    ) -> dict[str, Any]:
        return self.campaign_store.load(draft_id)

    def select_campaign(self, draft_id: str) -> dict[str, Any]:
        result = self.campaign_store.select(draft_id)
        self._sync_campaign_target(result)
        return self.campaign_store.catalog()

    def create_campaign_draft(self, expected_revision: int) -> dict[str, Any]:
        result = self.campaign_store.create_new(
            expected_revision=expected_revision,
        )
        self._sync_campaign_target(result)
        return result

    def save_campaign_draft(
        self,
        value: Mapping[str, Any],
        expected_revision: int,
        draft_id: str | None = None,
    ) -> dict[str, Any]:
        result = self.campaign_store.save(
            value,
            expected_revision=expected_revision,
            draft_id=draft_id,
        )
        self._sync_campaign_target(result)
        return result

    def delete_campaign_draft(
        self,
        draft_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        result = self.campaign_store.delete(
            draft_id,
            expected_revision=expected_revision,
        )
        selected = result["selected"]
        if isinstance(selected, Mapping):
            self._sync_campaign_target(selected)
        return result

    def _sync_campaign_target(self, campaign: Mapping[str, Any]) -> None:
        if self.run_service is None:
            return
        settings = self.run_service.automation()
        settings["recommendation_rules"]["target_cpa_rub"] = int(
            campaign["business_goal"]["target_cpa_rub"]
        )
        self.run_service.configure_automation(settings)

    def campaign_launch_overview(self, draft_id: str) -> dict[str, Any]:
        draft = self.campaign_store.campaign_draft_payload(draft_id)
        launch = self.campaign_launch_history.latest(draft_id)
        if launch is None:
            return {
                "draft_id": draft_id,
                "launch_status": "NOT_LAUNCHED",
                "workflow_status": "NOT_STARTED",
                "current": True,
                "run_id": None,
                "requested_at": None,
                "completed_steps": [],
                "total_steps": len(SAGA_STEPS),
                "external_write_sent": False,
                "message": None,
            }
        launched_draft = launch["exact_diff"]["after"]
        current = canonical_json(launched_draft) == canonical_json(draft)
        completed_steps = list(launch["completed_steps"])
        workflow_status = str(launch["status"])
        verified = (
            workflow_status == "APPLIED"
            and str(launch["execution_mode"]) == "SIMULATION"
            and completed_steps == [step.value for step in SAGA_STEPS]
            and not bool(launch["external_write_sent"])
        )
        return {
            "draft_id": draft_id,
            "launch_status": (
                "FAILED" if not verified else "LAUNCHED" if current else "OUTDATED"
            ),
            "workflow_status": workflow_status,
            "current": current,
            "run_id": str(launch["run_id"]),
            "requested_at": str(launch["requested_at"]),
            "completed_steps": completed_steps,
            "total_steps": len(SAGA_STEPS),
            "external_write_sent": bool(launch["external_write_sent"]),
            "message": (
                None
                if verified
                else str(
                    launch.get("detail")
                    or "Campaign Lifecycle не подтвердил полный тестовый запуск."
                )
            ),
        }

    def run_campaign_simulation(
        self,
        draft_id: str,
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        if not isinstance(draft_id, str) or not draft_id.strip():
            raise DashboardCampaignRejected(
                "CAMPAIGN_DRAFT_ID_REQUIRED",
                "Выберите тестовую кампанию перед запуском.",
            )
        run_id = self._new_run_id("campaign")
        result = self.workflows.run_campaign(
            run_id=run_id,
            proposal_id="proposal-" + run_id,
            draft_payload=self.campaign_store.campaign_draft_payload(
                draft_id,
                expected_revision=expected_revision,
            ),
            execution_mode="SIMULATION",
            requested_at=datetime.now(timezone.utc).isoformat(),
        )
        self.campaign_launch_history.record(result)
        self._write_workflow_evidence(result, "CAMPAIGN_LIFECYCLE")
        return result

    def run_goal_simulation(self, semantic_decision: str) -> dict[str, Any]:
        run_id = self._new_run_id("goal")
        result = self.workflows.run_goal(
            run_id=run_id,
            proposal_id="proposal-" + run_id,
            candidate_payload=self.campaign_store.goal_candidate_payload(),
            expected_site_version="test-page-v1",
            execution_mode="SIMULATION",
            requested_at=datetime.now(timezone.utc).isoformat(),
            semantic_decision=semantic_decision,
            reviewer=str(self.policy["principals"]["product_signoff"]["identity"]),
        )
        self._write_workflow_evidence(result, "GOAL_LIFECYCLE")
        return result

    def goal_lifecycle_overview(self, draft_id: str) -> dict[str, Any]:
        draft_id = self._require_goal_draft_id(draft_id)
        draft = self.campaign_store.load(draft_id)
        candidate = self.campaign_store.goal_candidate_payload(draft_id)
        source_draft = self._goal_source_draft(draft, candidate)
        latest = self.goal_lifecycle_history.latest(draft_id)
        result: dict[str, Any] = {
            "workflow": "GOAL_LIFECYCLE",
            "draft_id": draft_id,
            "revision": int(draft["revision"]),
            "candidate": candidate,
            "lifecycle_status": "NOT_STARTED",
            "technical_status": "NOT_STARTED",
            "semantic_decision": None,
            "run_id": None,
            "requested_at": None,
            "technical_evidence": None,
            "cleanup": None,
            "evidence_type": None,
            "execution_mode": None,
            "can_reject": False,
            "external_write_sent": False,
        }
        if latest is None:
            return result
        current = latest["source_draft"] == source_draft
        pending = self.goal_lifecycle_history.pending()
        status = str(latest.get("status", "FAILED"))
        if not current:
            lifecycle_status = "OUTDATED"
        elif status in {
            "AWAITING_SEMANTIC_DECISION",
            "APPROVED",
            "REJECTED",
        }:
            lifecycle_status = status
        else:
            lifecycle_status = "FAILED"
        return {
            **result,
            "lifecycle_status": lifecycle_status,
            "technical_status": str(latest.get("technical_status", "NOT_STARTED")),
            "semantic_decision": latest.get("semantic_decision"),
            "run_id": latest.get("run_id"),
            "requested_at": latest.get("requested_at"),
            "technical_evidence": latest.get("technical_evidence"),
            "cleanup": latest.get("cleanup"),
            "evidence_type": latest.get("evidence_type"),
            "execution_mode": latest.get("execution_mode"),
            "can_reject": bool(
                status == "AWAITING_SEMANTIC_DECISION"
                and pending is not None
                and pending["run_id"] == latest.get("run_id")
                and pending["draft_id"] == draft_id
            ),
            "external_write_sent": bool(latest.get("external_write_sent", False)),
        }

    def run_goal_technical_simulation(
        self,
        draft_id: str,
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        draft_id = self._require_goal_draft_id(draft_id)
        draft = self.campaign_store.load(draft_id)
        candidate = self.campaign_store.goal_candidate_payload(
            draft_id,
            expected_revision=expected_revision,
        )
        run_id = self._new_run_id("goal")
        self.goal_lifecycle_history.reserve(run_id, draft_id)
        try:
            result = self.workflows.run_goal_technical(
                run_id=run_id,
                proposal_id="proposal-" + run_id,
                candidate_payload=candidate,
                expected_site_version="test-page-v1",
                requested_at=datetime.now(timezone.utc).isoformat(),
                source_draft=self._goal_source_draft(draft, candidate),
            )
        except Exception:
            self.goal_lifecycle_history.release(run_id)
            raise
        self.goal_lifecycle_history.record(result)
        return result

    def _reconcile_completed_goal_evidence(self) -> None:
        for path in sorted(self.runs_root.iterdir()):
            workflow_path = path / "goal_workflow.json"
            if not path.is_dir() or not workflow_path.is_file():
                continue
            try:
                result = json.loads(workflow_path.read_text(encoding="utf-8"))
                if (
                    not isinstance(result, Mapping)
                    or result.get("workflow") != "GOAL_LIFECYCLE"
                    or result.get("run_id") != path.name
                ):
                    raise ValueError("GOAL_WORKFLOW_ARTIFACT_INVALID")
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                self._quarantine_corrupt_goal_run(path)
                continue
            evidence_complete = all(
                (path / name).is_file()
                for name in DASHBOARD_GENERATED_EVIDENCE_ARTIFACTS
            )
            if evidence_complete:
                try:
                    verify_dashboard_evidence_bundle(path)
                except (OSError, TypeError, ValueError):
                    evidence_complete = False
            if evidence_complete:
                continue
            self._quarantine_incomplete_evidence(path)
            self._write_workflow_evidence(result, "GOAL_LIFECYCLE")

    def _quarantine_corrupt_goal_run(self, run_directory: Path) -> None:
        quarantine_root = self.runs_root / ".incomplete-dashboard-evidence"
        quarantine_root.mkdir(exist_ok=True)
        suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = quarantine_root / f"{run_directory.name}-{suffix}"
        run_directory.replace(destination)

    def _quarantine_incomplete_evidence(self, run_directory: Path) -> None:
        candidates = {
            run_directory / name for name in DASHBOARD_GENERATED_EVIDENCE_ARTIFACTS
        }
        candidates.update(run_directory.glob(".dashboard-audit.sqlite3-*"))
        for name in DASHBOARD_GENERATED_EVIDENCE_ARTIFACTS:
            candidates.update(run_directory.glob(f".{name}.*"))
        existing = sorted(path for path in candidates if path.is_file())
        if not existing:
            return
        quarantine_root = self.runs_root / ".incomplete-dashboard-evidence"
        quarantine_root.mkdir(exist_ok=True)
        suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = quarantine_root / f"{run_directory.name}-{suffix}"
        destination.mkdir()
        for path in existing:
            path.replace(destination / path.name)

    def decide_pending_goal_simulation(
        self,
        semantic_decision: str,
        *,
        draft_id: str,
        expected_revision: int,
        run_id: str,
    ) -> dict[str, Any]:
        draft_id = self._require_goal_draft_id(draft_id)
        pending = self.goal_lifecycle_history.pending()
        if pending is None:
            raise ValueError("GOAL_TECHNICAL_VERIFICATION_REQUIRED")
        if run_id != pending["run_id"] or draft_id != pending["draft_id"]:
            raise ValueError("GOAL_TECHNICAL_RUN_MISMATCH")
        draft = self.campaign_store.load(draft_id)
        candidate = self.campaign_store.goal_candidate_payload(
            draft_id,
            expected_revision=expected_revision,
        )
        latest = self.goal_lifecycle_history.latest(draft_id)
        if latest is None or latest.get("run_id") != run_id:
            raise ValueError("GOAL_TECHNICAL_VERIFICATION_OUTDATED")
        source_is_current = latest.get("source_draft") == self._goal_source_draft(
            draft, candidate
        )
        if semantic_decision == "APPROVE" and not source_is_current:
            raise ValueError("GOAL_TECHNICAL_VERIFICATION_OUTDATED")
        result = self.workflows.decide_goal_simulation(
            run_id=run_id,
            semantic_decision=semantic_decision,
            reviewer=str(self.policy["principals"]["product_signoff"]["identity"]),
            requested_at=datetime.now(timezone.utc).isoformat(),
        )
        self.goal_lifecycle_history.record(result)
        self._write_workflow_evidence(result, "GOAL_LIFECYCLE")
        return result

    @staticmethod
    def _require_goal_draft_id(draft_id: str) -> str:
        if not isinstance(draft_id, str) or not draft_id.strip():
            raise DashboardCampaignRejected(
                "CAMPAIGN_DRAFT_ID_REQUIRED",
                "Выберите тестовую кампанию перед проверкой цели.",
            )
        return draft_id.strip()

    @staticmethod
    def _goal_source_draft(
        draft: Mapping[str, Any],
        candidate: Mapping[str, Any],
    ) -> dict[str, Any]:
        encoded = canonical_json(candidate).encode("utf-8")
        return {
            "draft_id": str(draft["draft_id"]),
            "revision": int(draft["revision"]),
            "candidate_hash": "sha256:" + hashlib.sha256(encoded).hexdigest(),
        }

    def run_impact_fixture(
        self,
        fixture_name: str,
        source_run_id: str | None = None,
    ) -> dict[str, Any]:
        if _SAFE_NAME.fullmatch(fixture_name) is None:
            raise ValueError("IMPACT_FIXTURE_INVALID")
        path = IMPACT_FIXTURES / (fixture_name + ".json")
        if not path.is_file() or path.parent != IMPACT_FIXTURES:
            raise ValueError("IMPACT_FIXTURE_NOT_FOUND")
        if source_run_id is not None:
            if self.run_service is None:
                raise ValueError("UI_RUN_SERVICE_UNAVAILABLE")
            source_report = self.run_service.load_report(source_run_id)
            if source_report["execution"]["status"] not in {
                "APPLIED",
                "NO_CHANGE",
            }:
                raise ValueError("IMPACT_SOURCE_DECISION_NOT_ACCEPTED")
        payload = json.loads(path.read_text(encoding="utf-8"))
        run_id = self._new_run_id("impact")
        payload["run_id"] = run_id
        payload["change_id"] = "change-" + run_id
        result = self.workflows.evaluate_impact(payload)
        self._write_workflow_evidence(result, "IMPACT_EVALUATION")
        if source_run_id is None:
            return result
        self.run_service.record_decision_outcome(
            source_run_id=source_run_id,
            outcome_run_id=run_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            payload=result,
        )
        return {
            **result,
            "source_run_id": source_run_id,
        }

    def evidence_overview(self) -> dict[str, Any]:
        latest = self._latest_full_evidence()
        if latest is not None:
            return latest
        capabilities = [
            {
                "capability": name,
                "status": "NOT_TESTED",
                "evidence_type": "SIMULATED",
                "evidence_paths": [],
                "limitations": [
                    "Полный тестовый контур ещё не запускался из Dashboard."
                ],
            }
            for name in required_capability_contract()
        ]
        gates = self.control.gate_state()
        return {
            "run_id": None,
            "overall_status": "NOT_PROVEN",
            "evidence_type": "SIMULATED",
            "capabilities": capabilities,
            "gates": self._dashboard_gates(
                gates,
                simulation_evidence_available=False,
            ),
            "artifacts": {},
        }

    def run_full_evidence(self) -> dict[str, Any]:
        from mox_adv.e2e_runner import run_readonly_e2e

        run_id = self._new_run_id("full-evidence")

        def acceptance_artifact(run_directory: Path) -> Mapping[str, str]:
            return {
                "acceptance-report.html": self._acceptance_report_html(
                    self._full_evidence_summary(run_id, run_directory)
                )
            }

        run_directory = run_readonly_e2e(
            self.runs_root,
            run_id,
            additional_text_artifacts=acceptance_artifact,
        )
        summary = self._full_evidence_summary(run_id, run_directory)
        summary["artifacts"] = self._artifact_links(run_id, run_directory)
        return summary

    def _full_evidence_summary(
        self,
        run_id: str,
        run_directory: Path,
    ) -> dict[str, Any]:
        result = json.loads((run_directory / "result.json").read_text(encoding="utf-8"))
        capability = json.loads(
            (run_directory / "capability-evidence.json").read_text(encoding="utf-8")
        )
        return {
            "run_id": run_id,
            "overall_status": result["capability_status"],
            "evidence_type": result["evidence_type"],
            "capabilities": capability["capabilities"],
            "gates": self._dashboard_gates(self.control.gate_state()),
        }

    @staticmethod
    def _acceptance_report_html(summary: Mapping[str, Any]) -> str:
        capability_rows = "".join(
            "<tr>"
            f"<td>{escape(str(item['capability']))}</td>"
            f"<td>{escape(str(item['status']))}</td>"
            f"<td>{escape(str(item['evidence_type']))}</td>"
            f"<td>{escape(', '.join(item.get('evidence_paths', [])) or '—')}</td>"
            f"<td>{escape(' '.join(item.get('limitations', [])) or '—')}</td>"
            "</tr>"
            for item in summary["capabilities"]
        )
        gate_rows = "".join(
            f"<li>{escape(str(item['gate']))}: {escape(str(item['status']))}</li>"
            for item in summary["gates"]
        )
        return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MOX-ADV — acceptance report</title>
  <style>
    body {{ font: 15px/1.5 system-ui; max-width: 1180px; margin: 40px auto; padding: 0 24px; color: #18221d; }}
    h1 {{ font-size: 32px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 10px; border: 1px solid #cad4ce; text-align: left; vertical-align: top; }}
    th {{ background: #eef3f0; }}
    code {{ overflow-wrap: anywhere; }}
  </style>
</head>
<body>
  <h1>MOX-ADV · acceptance evidence</h1>
  <p>Run: <code>{escape(str(summary["run_id"]))}</code></p>
  <p>Статус: <strong>{escape(str(summary["overall_status"]))}</strong> · evidence type: {escape(str(summary["evidence_type"]))}</p>
  <h2>Gate</h2>
  <ul>{gate_rows}</ul>
  <h2>Capabilities</h2>
  <table>
    <thead><tr><th>Capability</th><th>Status</th><th>Evidence type</th><th>Evidence paths</th><th>Limitations</th></tr></thead>
    <tbody>{capability_rows}</tbody>
  </table>
</body>
</html>
"""

    def artifact_path(self, run_id: str, name: str) -> Path:
        if _SAFE_NAME.fullmatch(run_id) is None or name not in _DOWNLOADABLE_ARTIFACTS:
            raise ValueError("ARTIFACT_NOT_ALLOWED")
        path = self.runs_root / run_id / name
        if not path.is_file() or path.parent != self.runs_root / run_id:
            raise FileNotFoundError(name)
        return path

    def _write_workflow_evidence(
        self,
        result: Mapping[str, Any],
        capability: str,
    ) -> None:
        run_id = str(result["run_id"])
        run_directory = self.runs_root / run_id
        change_diff = {
            "workflow": result["workflow"],
            "exact_diff": result["exact_diff"],
            "risks": list(result["risks"]),
            "authority_requirement": result["authority_requirement"],
        }
        change_diff_path = run_directory / "change_diff.json"
        if not change_diff_path.exists():
            change_diff_path.write_text(
                json.dumps(
                    change_diff,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        execution_status = (
            "NO_CHANGE" if capability == "IMPACT_EVALUATION" else "APPLIED"
        )
        record: dict[str, Any] = {
            "run_id": run_id,
            "policy_version": self.policy["policy_id"],
            "mode": result["workflow"],
            "evidence_type": "SIMULATED",
            "status": "SUCCEEDED",
            "execution_status": execution_status,
            "source": "LOCAL_FIXTURE",
            "snapshot_id": self._fingerprint(result),
            "period_start": "2026-07-01T00:00:00+00:00",
            "period_end": "2026-07-07T00:00:00+00:00",
            "provenance": {
                "workflow_artifact": str(result["evidence_paths"][0]),
                "external_write_sent": bool(result.get("external_write_sent", False)),
            },
            "original_metrics": {},
            "metrics": {},
            "validation_results": [
                {"code": "READY", "status": "PASSED"},
            ],
            "blocking_code": None,
            "policy_decision": {
                "status": "ALLOWED_SIMULATION",
                "reason_code": "SEALED_FAKE_ONLY",
            },
            "technical_command": {
                "workflow": result["workflow"],
                "operation": result["exact_diff"]["operation"],
            },
            "before": result["exact_diff"].get("before"),
            "after": result["exact_diff"].get("after"),
            "readback": {
                "status": result["status"],
                "external_write_sent": bool(result.get("external_write_sent", False)),
            },
            "final_object_state": result["status"],
            "provider": "DETERMINISTIC_LOCAL_WORKFLOW",
            "model_id": "NO_MODEL_CALL",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_rub": "0.00",
            "cost_limit_rub": "2000.00",
            "duration_ms": 0,
            "stage_durations_ms": {"workflow": 0},
            "capability_evidence": {
                capability: {
                    "status": "NOT_PROVEN",
                    "evidence_type": "SIMULATED",
                    "evidence_paths": [
                        "change_diff.json",
                        "result.json",
                        "events.jsonl",
                    ],
                    "limitations": [
                        "Simulation evidence does not replace controlled-pilot evidence."
                    ],
                }
            },
            "gates": {
                "GATE_0": {
                    "status": "READY",
                    "evidence_paths": ["result.json"],
                    "limitations": [],
                },
                "GATE_1": {
                    "status": "NOT_READY",
                    "evidence_paths": [],
                    "limitations": [
                        "Controlled-pilot authority and bindings are not configured."
                    ],
                },
            },
            "limitations": [
                "Dashboard workflow used local fake adapters and sent no external write."
            ],
            "artifact_references": {
                "change_diff": "change_diff.json",
            },
        }
        if capability == "IMPACT_EVALUATION":
            record["artifact_references"]["impact"] = "impact_report.json"
            record["capability_evidence"][capability]["evidence_paths"] = [
                "impact_report.json",
                "result.json",
                "events.jsonl",
            ]
        write_dashboard_evidence_bundle(run_directory, record)

    def _latest_full_evidence(self) -> dict[str, Any] | None:
        candidates = sorted(
            (
                path
                for path in self.runs_root.iterdir()
                if path.is_dir()
                and (path / "capability-evidence.json").is_file()
                and (path / "result.json").is_file()
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in candidates:
            try:
                result = json.loads((path / "result.json").read_text(encoding="utf-8"))
                capability = json.loads(
                    (path / "capability-evidence.json").read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                continue
            if (
                not isinstance(result, Mapping)
                or not isinstance(capability, Mapping)
                or not isinstance(result.get("capability_status"), str)
                or not isinstance(result.get("evidence_type"), str)
                or not isinstance(capability.get("capabilities"), list)
            ):
                continue
            return {
                "run_id": path.name,
                "overall_status": result["capability_status"],
                "evidence_type": result["evidence_type"],
                "capabilities": capability["capabilities"],
                "gates": self._dashboard_gates(self.control.gate_state()),
                "artifacts": self._artifact_links(path.name, path),
            }
        return None

    @staticmethod
    def _dashboard_gates(
        gates: Mapping[str, Any],
        *,
        simulation_evidence_available: bool = True,
    ) -> list[dict[str, Any]]:
        gate0_ready = gates["policy"]["status"] == "READY"
        simulation_ready = gates["simulation"]["status"] == "READY"
        pilot_ready = gates["controlled_pilot"]["status"] == "READY"
        return [
            {
                "gate": "GATE_0",
                "status": "READY" if gate0_ready else "BLOCKED",
            },
            {
                "gate": "GATE_1",
                "status": (
                    "READY"
                    if simulation_ready and simulation_evidence_available
                    else "NOT_READY"
                ),
            },
            {"gate": "GATE_2", "status": "NOT_READY"},
            {"gate": "GATE_3", "status": "NOT_READY"},
            {
                "gate": "GATE_4",
                "status": "READY" if pilot_ready else "NO_GO",
            },
        ]

    @staticmethod
    def _artifact_links(run_id: str, directory: Path) -> dict[str, str]:
        return {
            path.name: f"/api/evidence-runs/{run_id}/{path.name}"
            for path in directory.iterdir()
            if path.is_file() and path.name in _DOWNLOADABLE_ARTIFACTS
        }

    def _scope_value(self, scope: str) -> str:
        simulation = self.policy["bindings"]["simulation"]
        values = {
            "global": "global",
            "organization": "organization:" + str(simulation["organization"]),
            "connection": "connection:" + str(simulation["connection"]),
            "campaign": "campaign:sim-campaign",
        }
        try:
            return values[scope]
        except KeyError as error:
            raise ValueError("KILL_SWITCH_SCOPE_INVALID") from error

    @staticmethod
    def _new_run_id(prefix: str) -> str:
        return (
            "ui-"
            + prefix
            + "-"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        )

    @staticmethod
    def _fingerprint(value: Mapping[str, Any]) -> str:
        return (
            "sha256:"
            + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
        )
