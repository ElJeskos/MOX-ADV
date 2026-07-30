"""Safe JSON workflow façade for Dashboard lifecycle operations."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from mox_adv.campaign_lifecycle import (
    CampaignApproval,
    CampaignCreationRequest,
    CampaignDraftSafetyBindings,
    CampaignLifecycleService,
    CampaignSagaStore,
    CreationReservationStatus,
    validate_campaign_draft,
)
from mox_adv.campaign_lifecycle import (
    CreationReservation as CampaignCreationReservation,
)
from mox_adv.control_state import AuthenticatedPrincipal
from mox_adv.direct_management import (
    DirectManagementConnectorV1,
    FakeDirectManagementAdapter,
)
from mox_adv.goal_adapters import (
    FakeMetrikaGoalAdapter,
    FakeSitePublishAdapter,
)
from mox_adv.goal_contracts import (
    AuthorityKind,
    GoalAuthority,
    GoalCandidateRecord,
    GoalCandidateStatus,
    GoalTechnicalStatus,
    goal_creation_binding,
    site_publish_binding,
    site_publish_diff,
    validate_candidate,
)
from mox_adv.goal_contracts import (
    CreationReservation as GoalCreationReservation,
)
from mox_adv.goal_evidence import GoalEventEvidence
from mox_adv.goal_service import GoalLifecycleService
from mox_adv.goal_store import GoalLifecycleStore
from mox_adv.impact import (
    ImpactArtifactStore,
    ImpactEvaluationRequest,
    ImpactEvaluator,
    ImpactObservation,
    ImpactRejected,
)

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ControlledPilotExecutor = Callable[
    [Mapping[str, Any]],
    Mapping[str, Any],
]
ProductionAuthorityVerifier = Callable[
    [str, Mapping[str, Any], Mapping[str, Any], datetime],
    Mapping[str, Any],
]


class DashboardWorkflowRejected(RuntimeError):
    """A Dashboard workflow failed before any external write."""


class _SimulatedPrincipalAuthenticator:
    def __init__(self, policy: Mapping[str, Any]) -> None:
        principal = policy["principals"]["product_signoff"]
        self.identity = str(principal["identity"])
        self.authentication = str(principal["authentication"])

    def authenticate(self) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            identity=self.identity,
            authentication=self.authentication,
        )


class DashboardWorkflowFacade:
    """Expose lifecycle workflows as JSON-safe, fail-closed operator contracts."""

    def __init__(
        self,
        *,
        runs_root: Path,
        policy_path: Path,
        campaign_safety: CampaignDraftSafetyBindings,
        production_campaign_executor: ControlledPilotExecutor | None = None,
        production_goal_executor: ControlledPilotExecutor | None = None,
        production_authority_verifier: ProductionAuthorityVerifier | None = None,
    ) -> None:
        self.runs_root = Path(runs_root)
        self.policy_path = Path(policy_path)
        self.campaign_safety = campaign_safety
        self.production_campaign_executor = production_campaign_executor
        self.production_goal_executor = production_goal_executor
        self.production_authority_verifier = production_authority_verifier
        try:
            self.policy: Mapping[str, Any] = json.loads(
                self.policy_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise DashboardWorkflowRejected("GATE0_POLICY_UNAVAILABLE") from error
        self._goal_sessions: dict[str, dict[str, Any]] = {}

    def preview_campaign(
        self,
        *,
        run_id: str,
        proposal_id: str,
        draft_payload: Mapping[str, Any],
        execution_mode: str = "SIMULATION",
    ) -> dict[str, Any]:
        """Validate and disclose one campaign creation plan."""

        self._require_identifier(run_id, "RUN_ID_INVALID")
        self._require_identifier(proposal_id, "PROPOSAL_ID_INVALID")
        if execution_mode not in {"SIMULATION", "PRODUCTION"}:
            raise DashboardWorkflowRejected("EXECUTION_MODE_INVALID")
        draft = validate_campaign_draft(
            draft_payload,
            self.policy,
            self.campaign_safety,
        )
        bindings = self.policy["bindings"]
        if execution_mode == "SIMULATION":
            selected = bindings["simulation"]
            account = str(selected["direct_account"])
            reservation_id = str(selected["campaign_creation_reservation"])
            status = "READY_FOR_SIMULATION"
            evidence_type = "SIMULATED"
        else:
            selected = bindings["pilot"]
            if not selected.get("direct_account") or not selected.get(
                "campaign_creation_reservation"
            ):
                raise DashboardWorkflowRejected(
                    "PRODUCTION_PREREQUISITES_NOT_CONFIGURED"
                )
            account = str(selected["direct_account"])
            reservation_id = str(selected["campaign_creation_reservation"])
            status = "READY_FOR_CONTROLLED_PILOT"
            evidence_type = "CONTROLLED_PILOT"
        request = self._campaign_request(
            run_id,
            proposal_id,
            draft,
            account=account,
            reservation_id=reservation_id,
        )
        return {
            "schema_version": "dashboard-campaign-workflow-v1",
            "workflow": "CAMPAIGN_LIFECYCLE",
            "status": status,
            "execution_mode": execution_mode,
            "run_id": run_id,
            "proposal_id": proposal_id,
            "target": {
                "account": account,
                "credential_profile": "DIRECT_PILOT_WRITE",
                "external_write_allowed": execution_mode == "PRODUCTION",
            },
            "exact_diff": {
                "operation": "CREATE_UNIFIED_SEARCH_CAMPAIGN",
                "before": None,
                "after": draft.as_dict(),
            },
            "risks": [
                "CREATE_OBJECTS",
                "SUBMIT_MODERATION",
                "LAUNCH_CAMPAIGN",
            ],
            "authority_requirement": {
                "kind": "APPROVAL",
                "proposal_id": proposal_id,
                "account": account,
                "credential_profile": "DIRECT_PILOT_WRITE",
                "reservation_id": reservation_id,
                "exact_binding": request.approval_binding(
                    str(self.policy["policy_id"])
                ),
                "armed": execution_mode == "PRODUCTION",
                "evidence_type": evidence_type,
            },
            "evidence_paths": [],
        }

    def run_campaign(
        self,
        *,
        run_id: str,
        proposal_id: str,
        draft_payload: Mapping[str, Any],
        execution_mode: str,
        requested_at: str,
        authority: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run fake simulation or an authority-verified controlled-pilot executor."""

        if execution_mode == "PRODUCTION" and authority is None:
            raise DashboardWorkflowRejected("PRODUCTION_AUTHORITY_REQUIRED")
        preview = self.preview_campaign(
            run_id=run_id,
            proposal_id=proposal_id,
            draft_payload=draft_payload,
            execution_mode=execution_mode,
        )
        if execution_mode == "PRODUCTION":
            if authority is None:
                raise DashboardWorkflowRejected("PRODUCTION_AUTHORITY_REQUIRED")
            if self.production_authority_verifier is None:
                raise DashboardWorkflowRejected(
                    "PRODUCTION_AUTHORITY_VERIFIER_NOT_CONFIGURED"
                )
            if self.production_campaign_executor is None:
                raise DashboardWorkflowRejected("PRODUCTION_EXECUTOR_NOT_CONFIGURED")
            return self._run_production_campaign(
                preview=preview,
                draft_payload=draft_payload,
                authority=authority,
                requested_at=requested_at,
            )
        if execution_mode != "SIMULATION":
            raise DashboardWorkflowRejected("EXECUTION_MODE_INVALID")
        now = self._parse_utc(requested_at)
        run_directory = self._run_directory(run_id)
        artifact_path = run_directory / "campaign_workflow.json"
        existing = self._load_matching_artifact(
            artifact_path,
            proposal_id=proposal_id,
            exact_diff=preview["exact_diff"],
        )
        if existing is not None:
            return existing

        draft = validate_campaign_draft(
            draft_payload,
            self.policy,
            self.campaign_safety,
        )
        request = self._campaign_request(run_id, proposal_id, draft)
        state_path = run_directory / "campaign_state.sqlite3"
        store = CampaignSagaStore(state_path)
        simulation = self.policy["bindings"]["simulation"]
        store.register_creation_reservation(
            CampaignCreationReservation(
                reservation_id=request.reservation_id,
                status=CreationReservationStatus.AVAILABLE,
                scope_binding=str(simulation["direct_account"]),
                object_type="UNIFIED_CAMPAIGN",
                proposal_id=proposal_id,
                credential_profile=request.credential_profile,
                expires_at=now + timedelta(minutes=30),
            ),
            now,
        )
        principal = self.policy["principals"]["approver"]
        store.register_campaign_approval(
            CampaignApproval(
                approval_id=request.approval_id,
                proposal_id=proposal_id,
                binding_hash=request.approval_binding(str(self.policy["policy_id"])),
                approver=str(principal["identity"]),
                authentication=str(principal["authentication"]),
                expires_at=now + timedelta(minutes=15),
            )
        )
        adapter = FakeDirectManagementAdapter()
        service = CampaignLifecycleService(
            self.policy,
            store,
            DirectManagementConnectorV1(self.policy, adapter, store),
            self.campaign_safety,
        )
        saga = service.execute(request, now)
        result = {
            **preview,
            "status": saga.status.value,
            "requested_at": now.isoformat(),
            "completed_steps": [item.value for item in saga.completed_steps],
            "created_objects": [
                {
                    "service": item.service.value,
                    "object_id": item.object_id,
                    "actual_type": item.actual_type,
                }
                for item in saga.created_objects
            ],
            "detail": saga.detail,
            "authority_evidence": {
                "approval_id": request.approval_id,
                "evidence_type": "SIMULATED",
                "not_valid_for_production": True,
            },
            "fake_adapter_call_count": len(adapter.calls),
            "external_write_sent": False,
            "evidence_paths": [str(artifact_path), str(state_path)],
        }
        self._write_immutable_json(artifact_path, result)
        return result

    def _run_production_campaign(
        self,
        *,
        preview: Mapping[str, Any],
        draft_payload: Mapping[str, Any],
        authority: Mapping[str, Any],
        requested_at: str,
    ) -> dict[str, Any]:
        now = self._parse_utc(requested_at)
        run_id = str(preview["run_id"])
        proposal_id = str(preview["proposal_id"])
        requirement = preview["authority_requirement"]
        authority_evidence = self._verify_production_authority(
            workflow="CAMPAIGN_LIFECYCLE",
            authority=authority,
            requirement=requirement,
            requested_at=now,
        )
        run_directory = self._run_directory(run_id)
        artifact_path = run_directory / "campaign_workflow.json"
        existing = self._load_matching_artifact(
            artifact_path,
            proposal_id=proposal_id,
            exact_diff=preview["exact_diff"],
        )
        if existing is not None:
            return existing
        draft = validate_campaign_draft(
            draft_payload,
            self.policy,
            self.campaign_safety,
        )
        target = preview["target"]
        request = self._campaign_request(
            run_id,
            proposal_id,
            draft,
            account=str(target["account"]),
            reservation_id=str(requirement["reservation_id"]),
        )
        intent_path = run_directory / "campaign_intent.json"
        plan = {
            "schema_version": "dashboard-controlled-pilot-plan-v1",
            "workflow": "CAMPAIGN_LIFECYCLE",
            "requested_at": now.isoformat(),
            "canonical_plan": request.canonical_plan(str(self.policy["policy_id"])),
            "exact_diff": preview["exact_diff"],
            "risks": preview["risks"],
            "authority_evidence": authority_evidence,
        }
        self._write_or_match_immutable(intent_path, plan)
        executor = self.production_campaign_executor
        if executor is None:
            raise DashboardWorkflowRejected("PRODUCTION_EXECUTOR_NOT_CONFIGURED")
        execution = self._validate_controlled_result(executor(plan))
        result = {
            **preview,
            "status": execution["status"],
            "execution_status": execution["execution_status"],
            "requested_at": now.isoformat(),
            "controlled_pilot_result": execution,
            "external_write_sent": execution["external_write_sent"],
            "evidence_paths": [
                str(artifact_path),
                str(intent_path),
                *authority_evidence["evidence_paths"],
                *execution["evidence_paths"],
            ],
        }
        self._write_immutable_json(artifact_path, result)
        return result

    def preview_goal(
        self,
        *,
        run_id: str,
        proposal_id: str,
        candidate_payload: Mapping[str, Any],
        expected_site_version: str,
        execution_mode: str = "SIMULATION",
    ) -> dict[str, Any]:
        """Validate a candidate and disclose both separately bound write plans."""

        self._require_identifier(run_id, "RUN_ID_INVALID")
        self._require_identifier(proposal_id, "PROPOSAL_ID_INVALID")
        self._require_identifier(
            expected_site_version,
            "SITE_VERSION_INVALID",
        )
        if execution_mode not in {"SIMULATION", "PRODUCTION"}:
            raise DashboardWorkflowRejected("EXECUTION_MODE_INVALID")
        candidate_payload = validate_candidate(candidate_payload, self.policy)
        bindings = self.policy["bindings"]
        if execution_mode == "SIMULATION":
            selected = bindings["simulation"]
            counter_id = str(selected["test_counter"])
            site_zone = str(selected["test_site_zone"])
            reservation_id = str(selected["test_candidate_goal_reservation"])
            credential_profile = "METRIKA_TEST_WRITE"
            status = "READY_FOR_SIMULATION"
            evidence_type = "SIMULATED"
        else:
            selected = bindings["pilot"]
            if (
                not selected.get("pilot_counter")
                or not selected.get("pilot_site_zone")
                or not selected.get("pilot_candidate_goal_reservation")
            ):
                raise DashboardWorkflowRejected(
                    "PRODUCTION_GOAL_PREREQUISITES_NOT_CONFIGURED"
                )
            counter_id = str(selected["pilot_counter"])
            site_zone = str(selected["pilot_site_zone"])
            reservation_id = str(selected["pilot_candidate_goal_reservation"])
            credential_profile = "METRIKA_PILOT_WRITE"
            status = "READY_FOR_CONTROLLED_PILOT"
            evidence_type = "CONTROLLED_PILOT"
        candidate_id = "candidate-" + run_id
        creation_binding = goal_creation_binding(
            policy_id=str(self.policy["policy_id"]),
            run_id=run_id,
            candidate_id=candidate_id,
            proposal_id=proposal_id,
            reservation_id=reservation_id,
            counter_id=counter_id,
            site_zone=site_zone,
            credential_profile=credential_profile,
            payload=candidate_payload,
        )
        candidate = GoalCandidateRecord(
            candidate_id=candidate_id,
            run_id=run_id,
            proposal_id=proposal_id,
            counter_id=counter_id,
            goal_id="PENDING_SIMULATION",
            name=str(candidate_payload["name"]),
            event=str(candidate_payload["event"]),
            site_location=str(candidate_payload["site_location"]),
            goal_type=str(candidate_payload["type"]),
            business_meaning=str(candidate_payload["business_meaning"]),
            priority=int(candidate_payload["priority"]),
            status=GoalCandidateStatus.CANDIDATE,
            technical_status=GoalTechnicalStatus.PENDING,
            created_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
        )
        publish_diff = site_publish_diff(
            candidate,
            site_zone,
            expected_site_version,
        )
        publication_binding = site_publish_binding(
            policy_id=str(self.policy["policy_id"]),
            candidate=candidate,
            exact_diff=publish_diff,
        )
        return {
            "schema_version": "dashboard-goal-workflow-v1",
            "workflow": "GOAL_LIFECYCLE",
            "status": status,
            "execution_mode": execution_mode,
            "run_id": run_id,
            "proposal_id": proposal_id,
            "candidate_id": candidate_id,
            "target": {
                "counter_id": counter_id,
                "site_zone": site_zone,
                "credential_profile": credential_profile,
                "external_write_allowed": execution_mode == "PRODUCTION",
            },
            "exact_diff": {
                "operation": "CREATE_GOAL_AND_INSTALL_REACH_GOAL",
                "before": {"metrika_goal": None, "site_event": None},
                "after": {
                    "metrika_goal": candidate_payload,
                    "site_event": {
                        "event": candidate.event,
                        "selector": candidate.site_location,
                        "page_version": expected_site_version + "+" + run_id,
                    },
                },
            },
            "risks": [
                "CREATE_METRIKA_GOAL",
                "PUBLISH_SITE_EVENT",
                "SEMANTIC_MISCLASSIFICATION",
            ],
            "authority_requirement": {
                "goal_creation": {
                    "kind": "APPROVAL_OR_MANDATE",
                    "action": "GOAL_AUTHORING",
                    "proposal_id": proposal_id,
                    "counter_id": counter_id,
                    "site_zone": site_zone,
                    "reservation_id": reservation_id,
                    "credential_profile": credential_profile,
                    "exact_binding": creation_binding,
                    "armed": execution_mode == "PRODUCTION",
                    "evidence_type": evidence_type,
                },
                "site_publish": {
                    "kind": "APPROVAL",
                    "action": "SITE_PUBLISH",
                    "proposal_id": proposal_id,
                    "counter_id": counter_id,
                    "site_zone": site_zone,
                    "expected_page_version": expected_site_version,
                    "exact_binding": publication_binding,
                    "armed": execution_mode == "PRODUCTION",
                    "evidence_type": evidence_type,
                },
            },
            "evidence_paths": [],
        }

    def run_goal(
        self,
        *,
        run_id: str,
        proposal_id: str,
        candidate_payload: Mapping[str, Any],
        expected_site_version: str,
        execution_mode: str,
        requested_at: str,
        semantic_decision: str,
        reviewer: str,
        authority: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run fake simulation or an authority-verified controlled-pilot executor."""

        if semantic_decision not in {"APPROVE", "REJECT"}:
            raise DashboardWorkflowRejected("SEMANTIC_DECISION_INVALID")
        if execution_mode == "PRODUCTION" and authority is None:
            raise DashboardWorkflowRejected("PRODUCTION_GOAL_AUTHORITY_REQUIRED")
        preview = self.preview_goal(
            run_id=run_id,
            proposal_id=proposal_id,
            candidate_payload=candidate_payload,
            expected_site_version=expected_site_version,
            execution_mode=execution_mode,
        )
        if execution_mode == "PRODUCTION":
            if authority is None:
                raise DashboardWorkflowRejected("PRODUCTION_GOAL_AUTHORITY_REQUIRED")
            if self.production_authority_verifier is None:
                raise DashboardWorkflowRejected(
                    "PRODUCTION_AUTHORITY_VERIFIER_NOT_CONFIGURED"
                )
            if self.production_goal_executor is None:
                raise DashboardWorkflowRejected(
                    "PRODUCTION_GOAL_EXECUTOR_NOT_CONFIGURED"
                )
            return self._run_production_goal(
                preview=preview,
                candidate_payload=candidate_payload,
                authority=authority,
                requested_at=requested_at,
                semantic_decision=semantic_decision,
                reviewer=reviewer,
            )
        if execution_mode != "SIMULATION":
            raise DashboardWorkflowRejected("EXECUTION_MODE_INVALID")
        self.run_goal_technical(
            run_id=run_id,
            proposal_id=proposal_id,
            candidate_payload=candidate_payload,
            expected_site_version=expected_site_version,
            requested_at=requested_at,
        )
        return self.decide_goal_simulation(
            run_id=run_id,
            semantic_decision=semantic_decision,
            reviewer=reviewer,
            requested_at=requested_at,
        )

    def run_goal_technical(
        self,
        *,
        run_id: str,
        proposal_id: str,
        candidate_payload: Mapping[str, Any],
        expected_site_version: str,
        requested_at: str,
    ) -> dict[str, Any]:
        """Create and technically verify a simulated candidate without semantics."""

        existing_session = self._goal_sessions.get(run_id)
        if existing_session is not None:
            return dict(existing_session["result"])
        preview = self.preview_goal(
            run_id=run_id,
            proposal_id=proposal_id,
            candidate_payload=candidate_payload,
            expected_site_version=expected_site_version,
            execution_mode="SIMULATION",
        )
        now = self._parse_utc(requested_at)
        run_directory = self._run_directory(run_id)
        artifact_path = run_directory / "goal_technical.json"
        if (run_directory / "goal_workflow.json").exists():
            raise DashboardWorkflowRejected("SEMANTIC_DECISION_ALREADY_RECORDED")

        simulation = self.policy["bindings"]["simulation"]
        counter_id = str(simulation["test_counter"])
        site_zone = str(simulation["test_site_zone"])
        reservation_id = str(simulation["test_candidate_goal_reservation"])
        state_path = run_directory / "goal_state.sqlite3"
        store = GoalLifecycleStore(state_path)
        goal_adapter = FakeMetrikaGoalAdapter(
            (counter_id, str(simulation["pilot_counter"]))
        )
        site_adapter = FakeSitePublishAdapter(
            {
                site_zone: expected_site_version,
                str(simulation["pilot_site_zone"]): "pilot-page-v1",
            }
        )
        service = GoalLifecycleService(
            self.policy,
            store,
            goal_adapter,
            site_adapter,
            _SimulatedPrincipalAuthenticator(self.policy),
        )
        store.register_reservation(
            GoalCreationReservation(
                reservation_id=reservation_id,
                scope_binding="test_counter",
                object_type="METRIKA_GOAL",
                proposal_id=proposal_id,
                credential_profile="METRIKA_TEST_WRITE",
                expires_at=now + timedelta(minutes=15),
            )
        )
        mandate_principal = self.policy["principals"]["mandate_issuer"]
        creation_authority = GoalAuthority(
            authority_id="dashboard-goal-authority-" + run_id,
            kind=AuthorityKind.MANDATE,
            principal=str(mandate_principal["identity"]),
            authentication=str(mandate_principal["authentication"]),
            proposal_id=proposal_id,
            counter_id=counter_id,
            site_zone=site_zone,
            allowed_actions=("GOAL_AUTHORING",),
            expires_at=now + timedelta(hours=1),
            policy_id=str(self.policy["policy_id"]),
            binding_hash=str(
                preview["authority_requirement"]["goal_creation"]["exact_binding"]
            ),
        )
        store.register_authority(creation_authority)
        candidate = service.create_candidate(
            run_id=run_id,
            proposal_id=proposal_id,
            reservation_id=reservation_id,
            authority_id=creation_authority.authority_id,
            counter_id=counter_id,
            credential_profile="METRIKA_TEST_WRITE",
            payload=candidate_payload,
            now=now,
        )
        exact_site_diff = site_publish_diff(
            candidate,
            site_zone,
            expected_site_version,
        )
        approver = self.policy["principals"]["approver"]
        publication_authority = GoalAuthority(
            authority_id="dashboard-site-approval-" + run_id,
            kind=AuthorityKind.APPROVAL,
            principal=str(approver["identity"]),
            authentication=str(approver["authentication"]),
            proposal_id=proposal_id,
            counter_id=counter_id,
            site_zone=site_zone,
            allowed_actions=("SITE_PUBLISH",),
            expires_at=now + timedelta(minutes=15),
            policy_id=str(self.policy["policy_id"]),
            binding_hash=site_publish_binding(
                policy_id=str(self.policy["policy_id"]),
                candidate=candidate,
                exact_diff=exact_site_diff,
            ),
        )
        store.register_authority(publication_authority)
        publication = service.publish_candidate_event(
            candidate.candidate_id,
            authority_id=publication_authority.authority_id,
            site_zone=site_zone,
            expected_version=expected_site_version,
            now=now,
        )
        goal_adapter.set_visit_observations(
            candidate.counter_id,
            candidate.goal_id,
            ("PENDING", "DELIVERED"),
        )
        event_evidence = GoalEventEvidence(
            event=candidate.event,
            selector=candidate.site_location,
            trigger_selector="#dashboard-test-trigger",
            counter_id=candidate.counter_id,
            http_method="POST",
            request_url=(
                "https://mc.yandex.ru/watch/"
                + candidate.counter_id
                + "?"
                + urlencode({"event": candidate.event})
            ),
            emitted_count=1,
            intercepted_locally=True,
            real_network_requests=0,
        )
        technical = service.verify_candidate_delivery(
            candidate.candidate_id,
            event_evidence,
            now,
        )
        result = {
            **preview,
            "status": "AWAITING_SEMANTIC_DECISION",
            "requested_at": now.isoformat(),
            "semantic_decision": None,
            "semantic_reviewer": None,
            "technical_status": technical.status.value,
            "technical_evidence": self._jsonable(asdict(technical)),
            "publication": self._jsonable(asdict(publication)),
            "cleanup": {
                "performed": False,
                "fake_goal_deleted": 0,
                "fake_site_rollback": 0,
            },
            "fake_adapter_calls": {
                "goal_add": goal_adapter.add_calls,
                "site_publish": site_adapter.publish_calls,
            },
            "external_write_sent": False,
            "evidence_paths": [str(artifact_path), str(state_path)],
        }
        self._write_immutable_json(artifact_path, result)
        self._goal_sessions[run_id] = {
            "result": result,
            "service": service,
            "candidate_id": candidate.candidate_id,
            "goal_adapter": goal_adapter,
            "site_adapter": site_adapter,
            "state_path": state_path,
        }
        return result

    def decide_goal_simulation(
        self,
        *,
        run_id: str,
        semantic_decision: str,
        reviewer: str,
        requested_at: str,
    ) -> dict[str, Any]:
        """Record the separate human semantic decision and optional cleanup."""

        if semantic_decision not in {"APPROVE", "REJECT"}:
            raise DashboardWorkflowRejected("SEMANTIC_DECISION_INVALID")
        self._require_identifier(run_id, "RUN_ID_INVALID")
        run_directory = self._run_directory(run_id)
        artifact_path = run_directory / "goal_workflow.json"
        if artifact_path.is_file():
            existing = json.loads(artifact_path.read_text(encoding="utf-8"))
            if existing.get("semantic_decision") != semantic_decision:
                raise DashboardWorkflowRejected("IMMUTABLE_ARTIFACT_CONFLICT")
            return existing
        session = self._goal_sessions.get(run_id)
        if session is None:
            session = self._restore_goal_session(run_id)
        now = self._parse_utc(requested_at)
        service = session["service"]
        candidate_id = str(session["candidate_id"])
        decided = service.decide_business_semantics(
            candidate_id,
            approved=semantic_decision == "APPROVE",
            reviewer=reviewer,
            now=now,
        )
        cleanup_performed = semantic_decision == "REJECT"
        if cleanup_performed:
            service.cleanup_rejected_candidate(candidate_id, run_id)
        goal_adapter = session["goal_adapter"]
        site_adapter = session["site_adapter"]
        result = {
            **session["result"],
            "status": decided.status.value,
            "semantic_decision": semantic_decision,
            "semantic_reviewer": decided.semantic_reviewer,
            "semantic_authentication": {
                "evidence_type": "SIMULATED",
                "not_valid_for_production": True,
            },
            "cleanup": {
                "performed": cleanup_performed,
                "fake_goal_deleted": goal_adapter.delete_calls,
                "fake_site_rollback": site_adapter.rollback_calls,
            },
            "fake_adapter_calls": {
                "goal_add": int(session["result"]["fake_adapter_calls"]["goal_add"]),
                "site_publish": int(
                    session["result"]["fake_adapter_calls"]["site_publish"]
                ),
            },
            "evidence_paths": [
                str(artifact_path),
                str(session["state_path"]),
                str(run_directory / "goal_technical.json"),
            ],
        }
        self._write_immutable_json(artifact_path, result)
        del self._goal_sessions[run_id]
        return result

    def _restore_goal_session(self, run_id: str) -> dict[str, Any]:
        """Rebuild fake adapters around the durable Goal saga state."""

        run_directory = self._run_directory(run_id)
        technical_path = run_directory / "goal_technical.json"
        state_path = run_directory / "goal_state.sqlite3"
        if not technical_path.is_file() or not state_path.is_file():
            raise DashboardWorkflowRejected("TECHNICAL_VERIFICATION_SESSION_NOT_FOUND")
        result = json.loads(technical_path.read_text(encoding="utf-8"))
        candidate_id = str(result.get("candidate_id", ""))
        store = GoalLifecycleStore(state_path)
        candidate = store.load_candidate(candidate_id)
        publication = store.load_publication(candidate_id)
        simulation = self.policy["bindings"]["simulation"]
        goal_adapter = FakeMetrikaGoalAdapter(
            (
                str(simulation["test_counter"]),
                str(simulation["pilot_counter"]),
            )
        )
        goal_adapter.seed_existing_goal(
            candidate.counter_id,
            {
                "goal_id": candidate.goal_id,
                "name": candidate.name,
                "event": candidate.event,
                "site_location": candidate.site_location,
                "type": candidate.goal_type,
                "business_meaning": candidate.business_meaning,
                "priority": candidate.priority,
            },
        )
        site_adapter = FakeSitePublishAdapter(
            {
                publication.site_zone: publication.published_version,
                str(simulation["pilot_site_zone"]): "pilot-page-v1",
            }
        )
        site_adapter.seed_publication(publication)
        service = GoalLifecycleService(
            self.policy,
            store,
            goal_adapter,
            site_adapter,
            _SimulatedPrincipalAuthenticator(self.policy),
        )
        session = {
            "result": result,
            "service": service,
            "candidate_id": candidate_id,
            "goal_adapter": goal_adapter,
            "site_adapter": site_adapter,
            "state_path": state_path,
        }
        self._goal_sessions[run_id] = session
        return session

    def _run_production_goal(
        self,
        *,
        preview: Mapping[str, Any],
        candidate_payload: Mapping[str, Any],
        authority: Mapping[str, Any],
        requested_at: str,
        semantic_decision: str,
        reviewer: str,
    ) -> dict[str, Any]:
        now = self._parse_utc(requested_at)
        run_id = str(preview["run_id"])
        proposal_id = str(preview["proposal_id"])
        authority_evidence = self._verify_production_authority(
            workflow="GOAL_LIFECYCLE",
            authority=authority,
            requirement=preview["authority_requirement"],
            requested_at=now,
        )
        run_directory = self._run_directory(run_id)
        artifact_path = run_directory / "goal_workflow.json"
        existing = self._load_matching_artifact(
            artifact_path,
            proposal_id=proposal_id,
            exact_diff=preview["exact_diff"],
        )
        if existing is not None:
            if existing.get("semantic_decision") != semantic_decision:
                raise DashboardWorkflowRejected("IMMUTABLE_ARTIFACT_CONFLICT")
            return existing
        intent_path = run_directory / "goal_intent.json"
        plan = {
            "schema_version": "dashboard-controlled-pilot-plan-v1",
            "workflow": "GOAL_LIFECYCLE",
            "requested_at": now.isoformat(),
            "proposal_id": proposal_id,
            "candidate_id": preview["candidate_id"],
            "candidate": dict(candidate_payload),
            "target": dict(preview["target"]),
            "exact_diff": preview["exact_diff"],
            "risks": preview["risks"],
            "authority_evidence": authority_evidence,
            "semantic_review": {
                "decision": semantic_decision,
                "reviewer": reviewer,
                "executor_must_authenticate": True,
            },
        }
        self._write_or_match_immutable(intent_path, plan)
        executor = self.production_goal_executor
        if executor is None:
            raise DashboardWorkflowRejected("PRODUCTION_GOAL_EXECUTOR_NOT_CONFIGURED")
        execution = self._validate_controlled_result(executor(plan))
        result = {
            **preview,
            "status": execution["status"],
            "execution_status": execution["execution_status"],
            "requested_at": now.isoformat(),
            "semantic_decision": semantic_decision,
            "semantic_reviewer": reviewer,
            "controlled_pilot_result": execution,
            "external_write_sent": execution["external_write_sent"],
            "evidence_paths": [
                str(artifact_path),
                str(intent_path),
                *authority_evidence["evidence_paths"],
                *execution["evidence_paths"],
            ],
        }
        self._write_immutable_json(artifact_path, result)
        return result

    def evaluate_impact(
        self,
        request_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Evaluate linked post-change evidence and expose safe follow-up plans."""

        request = self._impact_request(request_payload)
        self._require_identifier(request.run_id, "RUN_ID_INVALID")
        try:
            report = ImpactEvaluator(self.policy).evaluate(request)
        except ImpactRejected as error:
            raise DashboardWorkflowRejected(str(error)) from error
        run_directory = self._run_directory(request.run_id)
        canonical_path = run_directory / "impact_report.json"
        stored = ImpactArtifactStore(run_directory).write(report)
        options = self._impact_decision_options(request.change_id)
        selected = next(
            item for item in options if item["decision"] == report.next_decision
        )
        workflow_path = run_directory / "impact_workflow.json"
        result = {
            "schema_version": "dashboard-impact-workflow-v1",
            "workflow": "IMPACT_EVALUATION",
            "status": report.status,
            "run_id": request.run_id,
            "change_id": request.change_id,
            "recommended_next_decision": report.next_decision,
            "decision_options": options,
            "exact_diff": {
                "operation": "EVALUATE_POST_CHANGE",
                "before": dict(request_payload["baseline"]),
                "after": dict(request_payload["post_change"]),
            },
            "risks": [
                "OBSERVED_ASSOCIATION_NOT_CAUSAL",
                "DELAYED_CONVERSION_RISK",
            ],
            "authority_requirement": selected["authority_requirement"],
            "impact_report": report.as_dict(),
            "canonical_report_hash": stored.canonical_hash,
            "evidence_paths": [str(workflow_path), str(canonical_path)],
        }
        if workflow_path.exists():
            try:
                existing = json.loads(workflow_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise DashboardWorkflowRejected(
                    "EVIDENCE_ARTIFACT_UNREADABLE"
                ) from error
            if existing != result:
                raise DashboardWorkflowRejected("IMMUTABLE_ARTIFACT_CONFLICT")
            return existing
        self._write_immutable_json(workflow_path, result)
        return result

    def _campaign_request(
        self,
        run_id: str,
        proposal_id: str,
        draft: Any,
        *,
        account: str | None = None,
        reservation_id: str | None = None,
    ) -> CampaignCreationRequest:
        simulation = self.policy["bindings"]["simulation"]
        return CampaignCreationRequest(
            run_id=run_id,
            execution_key="dashboard-campaign:" + run_id,
            proposal_id=proposal_id,
            approval_id="dashboard-approval-" + run_id,
            account=(str(simulation["direct_account"]) if account is None else account),
            credential_profile="DIRECT_PILOT_WRITE",
            reservation_id=(
                str(simulation["campaign_creation_reservation"])
                if reservation_id is None
                else reservation_id
            ),
            draft=draft,
        )

    def _impact_request(
        self,
        payload: Mapping[str, Any],
    ) -> ImpactEvaluationRequest:
        fields = {
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
        }
        if not isinstance(payload, Mapping) or set(payload) != fields:
            raise DashboardWorkflowRejected("IMPACT_REQUEST_INVALID")
        text_fields = (
            "fixture_name",
            "run_id",
            "change_id",
            "policy_version",
            "change_applied_at",
            "evaluated_at",
            "seasonality",
        )
        if any(
            not isinstance(payload[name], str) or not payload[name]
            for name in text_fields
        ):
            raise DashboardWorkflowRejected("IMPACT_REQUEST_INVALID")
        tuple_fields = {}
        for name in ("known_interventions", "confounders", "evidence"):
            value = payload[name]
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not item for item in value
            ):
                raise DashboardWorkflowRejected("IMPACT_REQUEST_INVALID")
            tuple_fields[name] = tuple(value)
        try:
            baseline = ImpactObservation.from_mapping(
                payload["baseline"],
                "Baseline",
            )
            post_change = ImpactObservation.from_mapping(
                payload["post_change"],
                "Post-change",
            )
        except ImpactRejected as error:
            raise DashboardWorkflowRejected(str(error)) from error
        return ImpactEvaluationRequest(
            fixture_name=str(payload["fixture_name"]),
            run_id=str(payload["run_id"]),
            change_id=str(payload["change_id"]),
            policy_version=str(payload["policy_version"]),
            change_applied_at=str(payload["change_applied_at"]),
            evaluated_at=str(payload["evaluated_at"]),
            baseline=baseline,
            post_change=post_change,
            seasonality=str(payload["seasonality"]),
            known_interventions=tuple_fields["known_interventions"],
            confounders=tuple_fields["confounders"],
            evidence=tuple_fields["evidence"],
        )

    @staticmethod
    def _impact_decision_options(change_id: str) -> list[dict[str, Any]]:
        return [
            {
                "decision": "KEEP_CHANGE",
                "exact_diff": {
                    "operation": "KEEP_CHANGE",
                    "change_id": change_id,
                    "mutation": None,
                },
                "risks": ["LATE_REGRESSION"],
                "authority_requirement": {"kind": "NONE"},
            },
            {
                "decision": "ROLLBACK_CHANGE",
                "exact_diff": {
                    "operation": "ROLLBACK_CHANGE",
                    "change_id": change_id,
                    "mutation": "RESTORE_PRE_CHANGE_VALUE",
                },
                "risks": ["ROLLBACK_MAY_REDUCE_PERFORMANCE"],
                "authority_requirement": {
                    "kind": "APPROVAL",
                    "binding": "EXACT_ROLLBACK_DIFF_REQUIRED",
                },
            },
            {
                "decision": "ADJUST_CHANGE",
                "exact_diff": {
                    "operation": "ADJUST_CHANGE",
                    "change_id": change_id,
                    "mutation": "NEW_BOUNDED_ADJUSTMENT",
                },
                "risks": ["NEW_OBSERVATION_WINDOW_REQUIRED"],
                "authority_requirement": {
                    "kind": "NEW_PROPOSAL_AND_APPROVAL",
                },
            },
            {
                "decision": "ESCALATE_TO_HUMAN",
                "exact_diff": {
                    "operation": "ESCALATE_TO_HUMAN",
                    "change_id": change_id,
                    "mutation": None,
                },
                "risks": ["DECISION_DELAY"],
                "authority_requirement": {"kind": "HUMAN_REVIEW"},
            },
        ]

    def _verify_production_authority(
        self,
        *,
        workflow: str,
        authority: Mapping[str, Any],
        requirement: Mapping[str, Any],
        requested_at: datetime,
    ) -> dict[str, Any]:
        verifier = self.production_authority_verifier
        if verifier is None:
            raise DashboardWorkflowRejected(
                "PRODUCTION_AUTHORITY_VERIFIER_NOT_CONFIGURED"
            )
        try:
            verified = verifier(
                workflow,
                authority,
                requirement,
                requested_at,
            )
        except DashboardWorkflowRejected:
            raise
        except BaseException as error:
            raise DashboardWorkflowRejected(
                "PRODUCTION_AUTHORITY_VERIFICATION_FAILED"
            ) from error
        required = {
            "status",
            "authority_ids",
            "binding_hashes",
            "evidence_paths",
        }
        if workflow == "CAMPAIGN_LIFECYCLE":
            expected_bindings = {str(requirement["exact_binding"])}
        elif workflow == "GOAL_LIFECYCLE":
            expected_bindings = {
                str(requirement["goal_creation"]["exact_binding"]),
                str(requirement["site_publish"]["exact_binding"]),
            }
        else:
            raise DashboardWorkflowRejected("WORKFLOW_INVALID")
        if (
            not isinstance(verified, Mapping)
            or set(verified) != required
            or verified.get("status") != "VERIFIED"
            or not isinstance(verified.get("authority_ids"), list)
            or not isinstance(verified.get("binding_hashes"), list)
            or not isinstance(verified.get("evidence_paths"), list)
        ):
            raise DashboardWorkflowRejected("PRODUCTION_AUTHORITY_VERIFICATION_INVALID")
        authority_ids = verified["authority_ids"]
        binding_hashes = verified["binding_hashes"]
        evidence_paths = verified["evidence_paths"]
        if (
            not authority_ids
            or any(
                not isinstance(value, str) or not value
                for value in (*authority_ids, *binding_hashes, *evidence_paths)
            )
            or len(set(authority_ids)) != len(authority_ids)
            or set(binding_hashes) != expected_bindings
        ):
            raise DashboardWorkflowRejected("PRODUCTION_AUTHORITY_VERIFICATION_INVALID")
        return {
            "status": "VERIFIED",
            "authority_ids": list(authority_ids),
            "binding_hashes": list(binding_hashes),
            "evidence_paths": list(evidence_paths),
        }

    @staticmethod
    def _validate_controlled_result(
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        required = {
            "status",
            "execution_status",
            "external_write_sent",
            "evidence_paths",
        }
        statuses = {
            "APPLIED",
            "NO_CHANGE",
            "BLOCKED",
            "ALREADY_PROCESSED",
            "UNKNOWN_RESULT",
            "FAILED",
            "PARTIALLY_APPLIED",
            "COMPENSATION_REQUIRED",
        }
        if (
            not isinstance(result, Mapping)
            or set(result) != required
            or result.get("status") not in statuses
            or result.get("execution_status") not in statuses
            or not isinstance(result.get("external_write_sent"), bool)
            or not isinstance(result.get("evidence_paths"), list)
            or any(
                not isinstance(path, str) or not path
                for path in result.get("evidence_paths", [])
            )
        ):
            raise DashboardWorkflowRejected("CONTROLLED_PILOT_RESULT_INVALID")
        if (
            result["execution_status"] in {"APPLIED", "NO_CHANGE"}
            and not result["external_write_sent"]
        ):
            raise DashboardWorkflowRejected("CONTROLLED_PILOT_RESULT_INVALID")
        return {
            "status": str(result["status"]),
            "execution_status": str(result["execution_status"]),
            "external_write_sent": bool(result["external_write_sent"]),
            "evidence_paths": list(result["evidence_paths"]),
        }

    @classmethod
    def _write_or_match_immutable(
        cls,
        path: Path,
        payload: Mapping[str, Any],
    ) -> None:
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise DashboardWorkflowRejected(
                    "EVIDENCE_ARTIFACT_UNREADABLE"
                ) from error
            if existing != dict(payload):
                raise DashboardWorkflowRejected("IMMUTABLE_ARTIFACT_CONFLICT")
            return
        cls._write_immutable_json(path, payload)

    def _run_directory(self, run_id: str) -> Path:
        self._require_identifier(run_id, "RUN_ID_INVALID")
        path = self.runs_root / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _parse_utc(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as error:
            raise DashboardWorkflowRejected("REQUESTED_AT_INVALID") from error
        if parsed.tzinfo is None:
            raise DashboardWorkflowRejected("REQUESTED_AT_INVALID")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _load_matching_artifact(
        path: Path,
        *,
        proposal_id: str,
        exact_diff: Mapping[str, Any],
    ) -> Any:
        if not path.exists():
            return None
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise DashboardWorkflowRejected("EVIDENCE_ARTIFACT_UNREADABLE") from error
        if (
            existing.get("proposal_id") != proposal_id
            or existing.get("exact_diff") != exact_diff
        ):
            raise DashboardWorkflowRejected("IMMUTABLE_ARTIFACT_CONFLICT")
        return existing

    @staticmethod
    def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> None:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        try:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o400,
            )
        except FileExistsError as error:
            raise DashboardWorkflowRejected("IMMUTABLE_ARTIFACT_CONFLICT") from error
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            try:
                path.unlink()
            except OSError:
                pass
            raise

    @classmethod
    def _jsonable(cls, value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        if isinstance(value, Mapping):
            return {str(key): cls._jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._jsonable(item) for item in value]
        return value

    @staticmethod
    def _require_identifier(value: str, reason: str) -> None:
        if not isinstance(value, str) or _SAFE_RUN_ID.fullmatch(value) is None:
            raise DashboardWorkflowRejected(reason)
