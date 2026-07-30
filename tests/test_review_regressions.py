from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from mox_adv import e2e_runner
from mox_adv.approval_execution import ApprovalExecutionService
from mox_adv.autonomy import (
    BoundedAutonomyService,
    DurableMandateAuthority,
    HMACMandateSigner,
)
from mox_adv.campaign_lifecycle import (
    CampaignApproval,
    CampaignLifecycleService,
    CampaignSagaStore,
    LifecycleRejected,
    validate_campaign_draft,
)
from mox_adv.commands import OptimizationAction
from mox_adv.control_state import (
    AuthenticatedPrincipal,
    ControlRejected,
    DurableControlState,
    ExecutionStatus,
)
from mox_adv.direct_management import (
    DirectManagementConnectorV1,
    DirectStateTransitionRejected,
    FakeDirectManagementAdapter,
)
from mox_adv.e2e_runner import (
    CAMPAIGN_NOW,
    GOAL_NOW,
    IMPACT_FIXTURE,
    NOW,
    OBSERVE_FIXTURE,
    POLICY_PATH,
    _analytics_optimization_workflow,
    _approval_prepared,
    _approval_request,
    _autonomy_prepared,
    _autonomy_request,
    _campaign_payload,
    _campaign_request,
    _campaign_safety,
    _goal_payload,
    _mandate_payload,
    _register_campaign_authority,
    _scope,
    run_readonly_e2e,
)
from mox_adv.fake_write_adapter import FakeWriteAdapter
from mox_adv.goal_lifecycle import (
    AuthorityKind,
    CreationReservation as GoalCreationReservation,
    FakeMetrikaGoalAdapter,
    FakeSitePublishAdapter,
    GoalAuthority,
    GoalLifecycleRejected,
    GoalLifecycleService,
    GoalLifecycleStore,
    goal_creation_binding,
    site_publish_binding,
    site_publish_diff,
)
from mox_adv.impact import ImpactEvaluator, load_impact_fixture
from mox_adv.lifecycle_authority import LifecycleAuthorityService
from mox_adv.model_cost import DurableModelCostLedger
from mox_adv.model_provider import DeterministicFakeModelProvider
from mox_adv.monitoring import MonitoringRead, MonitoringScheduler, MonitoringStore
from mox_adv.observe import run_observe_fixture
from mox_adv.proposal_store import ImmutableProposalStore
from mox_adv.recommend_contracts import ModelResponse
from mox_adv.recommend_projection import (
    build_sanitized_projection,
    campaign_fingerprint,
    projection_from_integrated_snapshot,
)
from mox_adv.recommend_service import RecommendationService
from scripts.validate_gate0 import validate_policy

ROOT = Path(__file__).resolve().parents[1]
LLM_FIXTURE = ROOT / "fixtures" / "llm" / "LLM_EFFECTIVE_BUDGET_PRESSURE.json"


def load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


class FixedAuthenticator:
    def authenticate(self) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            identity="sviridov",
            authentication="authenticated_macos_user",
        )


class WrongAuthenticator:
    def authenticate(self) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            identity="mallory",
            authentication="authenticated_macos_user",
        )


class EngagingAudit:
    def __init__(
        self,
        state: DurableControlState,
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> None:
        self.state = state
        self.principal = principal
        self.now = now

    def authorize(
        self,
        execution_key: str,
        target_key: str,
        occurred_at: datetime,
    ) -> None:
        del execution_key, target_key, occurred_at
        self.state.engage_kill_switch(
            "global",
            "Regression test engages the switch after audit starts.",
            self.principal,
            self.now,
        )


class AdvancingClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **changes: int) -> None:
        self.value += timedelta(**changes)


class AdvancingReadSource:
    def __init__(self, value: MonitoringRead, clock: AdvancingClock) -> None:
        self.value = value
        self.clock = clock

    def read(self) -> MonitoringRead:
        self.clock.advance(minutes=31)
        return self.value


class MeteredInvalidProvider:
    provider_id = "metered"
    model_id = "invalid-schema-v1"
    maximum_input_tokens = 100
    maximum_output_tokens = 0

    def __init__(self) -> None:
        self.invocation_count = 0

    def generate(self, projection) -> ModelResponse:
        del projection
        self.invocation_count += 1
        return ModelResponse(
            payload={"invalid": True},
            provider=self.provider_id,
            model_id=self.model_id,
            input_tokens=100,
            output_tokens=0,
            cost_rub="untrusted",
            duration_ms=1,
        )


class MalformedBoundaryProvider(MeteredInvalidProvider):
    def generate(self, projection) -> object:
        del projection
        self.invocation_count += 1
        return object()


class SpoofedDirectAdapter:
    is_fake = True

    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, request):
        del request
        self.calls += 1
        raise AssertionError("Spoofed adapter reached the transport seam.")

    def inspect(self, service: str, object_id: str):
        del service, object_id
        raise AssertionError("Spoofed adapter reached the transport seam.")


class SpoofedGoalAdapter(FakeMetrikaGoalAdapter):
    pass


def linked_snapshot(root: Path):
    fixture = json.loads(OBSERVE_FIXTURE.read_text(encoding="utf-8"))
    fixture["direct_state"]["current_weekly_budget_micros"] = 2_700_000_000
    for row in fixture["direct_report"]["rows"]:
        row["cost_micros"] = int(row["cost_micros"]) // 2
    path = root / "linked.json"
    path.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return e2e_runner._build_snapshot(path), path


def immutable_execution_context(root: Path):
    policy = load_policy()
    snapshot, _ = linked_snapshot(root)
    evaluated_at = datetime.fromisoformat(snapshot.generated_at)
    projection = projection_from_integrated_snapshot(
        snapshot,
        policy,
        evaluated_at,
    )
    proposal_store = ImmutableProposalStore(root / "proposals")
    recommendation = RecommendationService(
        DeterministicFakeModelProvider(),
        proposal_store,
        policy,
    ).recommend(
        projection=projection,
        run_id="immutable-run",
        snapshot_id=snapshot.snapshot_id,
        expected_fingerprint=campaign_fingerprint(snapshot),
        created_at=evaluated_at.isoformat(),
        expires_at=(evaluated_at + timedelta(minutes=30)).isoformat(),
    )
    if recommendation.proposal is None:
        raise AssertionError("Immutable proposal setup failed.")
    state = DurableControlState(root / "control.sqlite3")
    prepared = state.register_optimization_proposal(
        proposal_store=proposal_store,
        proposal_id=recommendation.proposal.proposal_id,
        snapshot=snapshot,
        policy=policy,
        writer=str(policy["bindings"]["simulation"]["single_writer"]),
        at=evaluated_at,
    )
    return policy, snapshot, evaluated_at, state, prepared


def lifecycle_authority(policy: dict) -> LifecycleAuthorityService:
    return LifecycleAuthorityService(
        policy,
        FixedAuthenticator(),
        HMACMandateSigner(b"review-regression-lifecycle-authority"),
    )


def goal_components(
    root: Path,
    *,
    control_state: DurableControlState | None = None,
):
    policy = load_policy()
    authority_service = lifecycle_authority(policy)
    store = GoalLifecycleStore(root / "goals.sqlite3", authority_service)
    simulation = policy["bindings"]["simulation"]
    goal_adapter = FakeMetrikaGoalAdapter(
        (simulation["test_counter"], simulation["pilot_counter"])
    )
    site_adapter = FakeSitePublishAdapter(
        {
            simulation["test_site_zone"]: "test-page-v1",
            simulation["pilot_site_zone"]: "pilot-page-v1",
        }
    )
    shared_control_state = (
        DurableControlState(root / "control.sqlite3")
        if control_state is None
        else control_state
    )
    service = GoalLifecycleService(
        policy,
        store,
        goal_adapter,
        site_adapter,
        FixedAuthenticator(),
        shared_control_state,
    )
    return policy, store, goal_adapter, site_adapter, service


def register_goal_creation(
    policy: dict,
    store: GoalLifecycleStore,
    *,
    run_id: str,
) -> tuple[str, str, str]:
    simulation = policy["bindings"]["simulation"]
    proposal_id = "proposal-" + run_id
    reservation_id = "reservation-" + run_id
    authority_id = "authority-" + run_id
    candidate_id = "candidate-" + run_id
    reservation = GoalCreationReservation(
        reservation_id=reservation_id,
        scope_binding="test_counter",
        object_type="METRIKA_GOAL",
        proposal_id=proposal_id,
        credential_profile="METRIKA_TEST_WRITE",
        expires_at=GOAL_NOW + timedelta(minutes=30),
    )
    authority = GoalAuthority(
        authority_id=authority_id,
        kind=AuthorityKind.MANDATE,
        principal="sviridov",
        authentication="authenticated_macos_user",
        proposal_id=proposal_id,
        counter_id=str(simulation["test_counter"]),
        site_zone=str(simulation["test_site_zone"]),
        allowed_actions=("GOAL_AUTHORING",),
        expires_at=GOAL_NOW + timedelta(hours=1),
        policy_id=str(policy["policy_id"]),
        binding_hash=goal_creation_binding(
            policy_id=str(policy["policy_id"]),
            run_id=run_id,
            candidate_id=candidate_id,
            proposal_id=proposal_id,
            reservation_id=reservation_id,
            counter_id=str(simulation["test_counter"]),
            site_zone=str(simulation["test_site_zone"]),
            credential_profile="METRIKA_TEST_WRITE",
            payload=_goal_payload(),
        ),
    )
    store.register_reservation(reservation)
    store.register_authority(authority, GOAL_NOW)
    return proposal_id, reservation_id, authority_id


def create_goal_candidate(
    policy: dict,
    store: GoalLifecycleStore,
    service: GoalLifecycleService,
    *,
    run_id: str,
):
    proposal_id, reservation_id, authority_id = register_goal_creation(
        policy,
        store,
        run_id=run_id,
    )
    candidate = service.create_candidate(
        run_id=run_id,
        proposal_id=proposal_id,
        reservation_id=reservation_id,
        authority_id=authority_id,
        counter_id=str(policy["bindings"]["simulation"]["test_counter"]),
        credential_profile="METRIKA_TEST_WRITE",
        payload=_goal_payload(),
        now=GOAL_NOW,
    )
    return candidate


def publish_goal_candidate(
    policy: dict,
    store: GoalLifecycleStore,
    service: GoalLifecycleService,
    candidate,
    *,
    kind: AuthorityKind,
):
    zone = str(policy["bindings"]["simulation"]["test_site_zone"])
    exact_diff = site_publish_diff(candidate, zone, "test-page-v1")
    authority = GoalAuthority(
        authority_id="site-authority-" + candidate.run_id,
        kind=kind,
        principal="sviridov",
        authentication="authenticated_macos_user",
        proposal_id=candidate.proposal_id,
        counter_id=candidate.counter_id,
        site_zone=zone,
        allowed_actions=("SITE_PUBLISH",),
        expires_at=GOAL_NOW + timedelta(hours=1),
        policy_id=str(policy["policy_id"]),
        binding_hash=site_publish_binding(
            policy_id=str(policy["policy_id"]),
            candidate=candidate,
            exact_diff=exact_diff,
        ),
    )
    store.register_authority(authority, GOAL_NOW)
    return service.publish_candidate_event(
        candidate.candidate_id,
        authority_id=authority.authority_id,
        site_zone=zone,
        expected_version="test-page-v1",
        now=GOAL_NOW,
    )


class ReviewRegressionTests(unittest.TestCase):
    def test_closed_loop_envelope_links_one_campaign_without_overclaiming(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts, summary = _analytics_optimization_workflow(
                Path(temporary),
                load_policy(),
            )
        envelope = artifacts["closed-loop-envelope.json"]
        proposal = artifacts["proposal.json"]
        change = artifacts["change_diff.json"]["approval_required"]
        impact = artifacts["impact_report.json"]
        observe = artifacts["observe-evidence.json"]
        self.assertEqual(summary["snapshot_id"], proposal["snapshot_id"])
        self.assertEqual(observe["snapshot_id"], impact["baseline"]["snapshot_id"])
        self.assertEqual(
            {
                observe["campaign"],
                change["campaign"],
                impact["baseline"]["campaign"],
                impact["post_change"]["campaign"],
                envelope["campaign"],
            },
            {envelope["impact_campaign"]},
        )
        self.assertEqual(change["execution_key"], impact["change_id"])
        self.assertEqual(
            impact["post_change"]["snapshot_id"],
            envelope["post_snapshot_id"],
        )
        self.assertNotEqual(
            impact["baseline"]["snapshot_id"],
            impact["post_change"]["snapshot_id"],
        )
        self.assertEqual("linked-observe", envelope["post_observation_id"])
        self.assertEqual("LOCAL_FIXTURE", envelope["post_snapshot_source"])
        self.assertEqual("SIMULATED", envelope["evidence_type"])
        self.assertEqual("NOT_PROVEN", envelope["capability_status"])

    def test_executor_derives_plan_and_facts_from_immutable_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            policy, _, evaluated_at, state, prepared = immutable_execution_context(
                Path(temporary)
            )
            with self.assertRaisesRegex(
                ControlRejected,
                "IMMUTABLE_PROPOSAL_CONFLICT",
            ):
                state.register_prepared_change(
                    replace(prepared, target_value=prepared.target_value + 1)
                )
            state.grant_approval(
                prepared.proposal_id,
                evaluated_at + timedelta(minutes=15),
                "Approve the exact immutable plan.",
                FixedAuthenticator().authenticate(),
                evaluated_at,
            )
            adapter = FakeWriteAdapter(
                initial_state={
                    prepared.target_key(): prepared.current_value,
                },
                current_fingerprints={
                    prepared.target_key(): "sha256:" + "9" * 64,
                },
            )
            caller_request = _approval_request(prepared)
            outcome = ApprovalExecutionService(
                policy,
                state,
                adapter,
                clock=lambda: evaluated_at,
            ).execute(caller_request)
            adapter.set_current_fingerprint(
                prepared.target_key(),
                prepared.expected_fingerprint,
            )
            hostile_caller_request = replace(
                caller_request,
                facts=replace(
                    caller_request.facts,
                    automation_enabled=False,
                    comparability_status="INCOMPATIBLE",
                    direct_age_minutes=10_000,
                    clicks=0,
                    conversions=0,
                    monetary_exposure_rub=10_000,
                    current_fingerprint="sha256:" + "8" * 64,
                ),
            )
            applied = ApprovalExecutionService(
                policy,
                state,
                adapter,
                clock=lambda: evaluated_at,
            ).execute(hostile_caller_request)
        self.assertEqual(ExecutionStatus.BLOCKED, outcome.status)
        self.assertEqual("FINGERPRINT_MISMATCH", outcome.reason_code)
        self.assertEqual(ExecutionStatus.APPLIED, applied.status)
        self.assertEqual(1, adapter.write_calls)

    def test_kill_switch_rechecked_after_audit_without_consuming_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            policy = load_policy()
            state = DurableControlState(Path(temporary) / "control.sqlite3")
            principal = FixedAuthenticator().authenticate()
            prepared = _approval_prepared("proposal-final-kill-check")
            state.register_prepared_change(prepared)
            approval = state.grant_approval(
                prepared.proposal_id,
                NOW + timedelta(minutes=15),
                "Approve only while the kill switch stays inactive.",
                principal,
                NOW,
            )
            adapter = FakeWriteAdapter(
                initial_state={
                    prepared.target_key(): prepared.current_value,
                }
            )
            outcome = ApprovalExecutionService(
                policy,
                state,
                adapter,
                clock=lambda: NOW,
                pre_write_audit=EngagingAudit(state, principal, NOW),
            ).execute(_approval_request(prepared))
            self.assertFalse(state.load_approval(approval.approval_id).used)
            state.release_kill_switch(
                "global",
                "Continue local regression validation.",
                principal,
                NOW,
            )
            next_prepared = _approval_prepared("proposal-after-final-kill-check")
            state.register_prepared_change(next_prepared)
            state.grant_approval(
                next_prepared.proposal_id,
                NOW + timedelta(minutes=15),
                "Approve after the durable switch is released.",
                principal,
                NOW,
            )
            next_adapter = FakeWriteAdapter(
                initial_state={
                    next_prepared.target_key(): next_prepared.current_value,
                }
            )
            next_outcome = ApprovalExecutionService(
                policy,
                state,
                next_adapter,
                clock=lambda: NOW,
            ).execute(_approval_request(next_prepared))
        self.assertEqual(ExecutionStatus.BLOCKED, outcome.status)
        self.assertEqual("KILL_SWITCH_ACTIVE", outcome.reason_code)
        self.assertEqual(0, adapter.write_calls)
        self.assertEqual(ExecutionStatus.APPLIED, next_outcome.status)
        self.assertEqual(1, next_adapter.write_calls)

    def test_lifecycle_authorities_require_authenticated_signed_issuance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = load_policy()
            draft = validate_campaign_draft(
                _campaign_payload(),
                policy,
                _campaign_safety(),
            )
            request = _campaign_request(draft)
            raw_approval = CampaignApproval(
                approval_id=request.approval_id,
                proposal_id=request.proposal_id,
                binding_hash=request.approval_binding(str(policy["policy_id"])),
                approver="sviridov",
                authentication="authenticated_macos_user",
                expires_at=NOW + timedelta(minutes=15),
            )
            with self.assertRaisesRegex(
                LifecycleRejected,
                "AUTHORITY_SERVICE_REQUIRED",
            ):
                CampaignSagaStore(
                    root / "unsigned-campaign.sqlite3"
                ).register_campaign_approval(raw_approval, NOW)
            with self.assertRaisesRegex(
                LifecycleRejected,
                "AUTHORITY_SERVICE_REQUIRED",
            ):
                CampaignSagaStore(
                    root / "spoofed-campaign-service.sqlite3",
                    object(),
                )
            wrong_service = LifecycleAuthorityService(
                policy,
                WrongAuthenticator(),
                HMACMandateSigner(b"wrong-principal-authority"),
            )
            goal_store = GoalLifecycleStore(
                root / "wrong-goal.sqlite3",
                wrong_service,
            )
            raw_goal_authority = GoalAuthority(
                authority_id="wrong-goal-authority",
                kind=AuthorityKind.MANDATE,
                principal="sviridov",
                authentication="authenticated_macos_user",
                proposal_id="proposal",
                counter_id="sim-test-counter",
                site_zone="sim-test-site-zone",
                allowed_actions=("GOAL_AUTHORING",),
                expires_at=NOW + timedelta(hours=1),
                policy_id=str(policy["policy_id"]),
                binding_hash="sha256:" + "1" * 64,
            )
            with self.assertRaisesRegex(
                GoalLifecycleRejected,
                "UNAUTHENTICATED_PRINCIPAL",
            ):
                goal_store.register_authority(raw_goal_authority, NOW)
            with self.assertRaisesRegex(
                GoalLifecycleRejected,
                "AUTHORITY_SERVICE_REQUIRED",
            ):
                GoalLifecycleStore(
                    root / "spoofed-goal-service.sqlite3",
                    object(),
                )
            with self.assertRaisesRegex(
                ControlRejected,
                "AUTHORITY_NOT_AUTHENTICATED",
            ):
                DurableControlState(
                    root / "control.sqlite3"
                ).register_campaign_approval_authority(
                    authority_service=object(),
                    verified=object(),
                )

    def test_self_declared_fake_adapters_cannot_reach_write_seams(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            policy = load_policy()
            with self.assertRaisesRegex(
                DirectStateTransitionRejected,
                "DURABLE_DISPATCH_GUARD_REQUIRED",
            ):
                DirectManagementConnectorV1(
                    policy,
                    FakeDirectManagementAdapter(),
                    CampaignSagaStore(
                        Path(temporary) / "unguarded-registry.sqlite3"
                    ),
                )
            with self.assertRaisesRegex(
                GoalLifecycleRejected,
                "DURABLE_DISPATCH_GUARD_REQUIRED",
            ):
                GoalLifecycleService(
                    policy,
                    GoalLifecycleStore(
                        Path(temporary) / "unguarded-goals.sqlite3"
                    ),
                    FakeMetrikaGoalAdapter(("sim-test-counter",)),
                    FakeSitePublishAdapter(
                        {"sim-test-site-zone": "test-page-v1"}
                    ),
                )
            spoofed = SpoofedDirectAdapter()
            connector = DirectManagementConnectorV1(
                policy,
                spoofed,
                CampaignSagaStore(Path(temporary) / "registry.sqlite3"),
                control_state=DurableControlState(
                    Path(temporary) / "control.sqlite3"
                ),
            )
            with self.assertRaisesRegex(
                DirectStateTransitionRejected,
                "PRODUCTION_CONNECTOR_DISABLED",
            ):
                connector.campaigns_add(
                    "spoof-run",
                    "spoof-operation",
                    {"type": "UNIFIED_CAMPAIGN"},
                )
            with self.assertRaisesRegex(
                GoalLifecycleRejected,
                "FAKE_ADAPTER_REQUIRED",
            ):
                GoalLifecycleService(
                    policy,
                    GoalLifecycleStore(Path(temporary) / "goals.sqlite3"),
                    SpoofedGoalAdapter(("sim-test-counter",)),
                    FakeSitePublishAdapter(
                        {"sim-test-site-zone": "test-page-v1"}
                    ),
                    control_state=DurableControlState(
                        Path(temporary) / "control.sqlite3"
                    ),
                )
        self.assertEqual(0, spoofed.calls)

    def test_every_non_add_direct_operation_requires_current_run_ownership(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            policy = load_policy()
            adapter = FakeDirectManagementAdapter()
            connector = DirectManagementConnectorV1(
                policy,
                adapter,
                CampaignSagaStore(Path(temporary) / "registry.sqlite3"),
                control_state=DurableControlState(
                    Path(temporary) / "control.sqlite3"
                ),
            )
            run_id = "ownership-run"
            methods = (
                (str(item["service"]), str(item["method"]))
                for item in policy["api_matrix"]
                if item["system"] == "DIRECT"
                and item["service"]
                in {"Campaigns", "AdGroups", "Ads", "Keywords", "KeywordBids"}
                and item["method"] != "add"
            )
            for service, method in methods:
                with self.subTest(service=service, method=method):
                    ids = ("foreign-object",)
                    payload = (
                        {"ids": list(ids)}
                        if method in {"get", "moderate"}
                        else {"id": ids[0], "changes": {}}
                    )
                    operation_key = connector._operation_key(
                        run_id,
                        service,
                        method,
                        ids,
                    )
                    with self.assertRaisesRegex(
                        DirectStateTransitionRejected,
                        "RUN_OWNERSHIP_REQUIRED",
                    ):
                        connector._invoke(
                            run_id,
                            operation_key,
                            service,
                            method,
                            payload,
                        )
        self.assertEqual([], adapter.calls)

    def test_mandate_minimum_sample_is_canonical_policy_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            policy = load_policy()
            state = DurableControlState(Path(temporary) / "control.sqlite3")
            prepared = _autonomy_prepared("proposal-strict-minimum")
            state.register_prepared_change(prepared)
            principal = FixedAuthenticator().authenticate()
            authority = DurableMandateAuthority(
                state.path,
                policy,
                HMACMandateSigner(b"strict-minimum-mandate"),
            )
            payload = dict(_mandate_payload(policy, NOW))
            payload["minimum_sample"] = {
                "clicks": 100,
                "conversions": 10,
            }
            issued = authority.issue(payload, principal, NOW)
            mandate = authority.activate(issued.mandate_id, principal, NOW)
            adapter = FakeWriteAdapter(
                initial_state={
                    prepared.target_key(): prepared.current_value,
                }
            )
            outcome = BoundedAutonomyService(
                policy,
                state,
                authority,
                adapter,
                clock=lambda: NOW,
            ).execute(_autonomy_request(prepared, mandate))
        self.assertEqual(ExecutionStatus.BLOCKED, outcome.status)
        self.assertEqual("ACTION_POLICY_REJECTED", outcome.reason_code)
        self.assertEqual(0, adapter.write_calls)

    def test_no_conversion_suspend_accepts_not_applicable_cpa(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            policy = load_policy()
            state = DurableControlState(Path(temporary) / "control.sqlite3")
            prepared = replace(
                _approval_prepared("proposal-no-conversion"),
                action=OptimizationAction.SUSPEND_CAMPAIGN,
                current_value="ON",
                target_value="SUSPENDED",
                expected_diff={
                    "operation": "SUSPEND_CAMPAIGN",
                    "target_state": "SUSPENDED",
                },
            )
            state.register_prepared_change(prepared)
            state.grant_approval(
                prepared.proposal_id,
                NOW + timedelta(minutes=15),
                "Suspend after the exact no-conversion threshold.",
                FixedAuthenticator().authenticate(),
                NOW,
            )
            request = _approval_request(prepared)
            request = replace(
                request,
                facts=replace(
                    request.facts,
                    clicks=100,
                    conversions=0,
                    spend_rub=2000,
                    cpa_rub="NOT_APPLICABLE",
                    campaign_state="ON",
                    monetary_exposure_rub=0,
                ),
            )
            adapter = FakeWriteAdapter(
                initial_state={
                    prepared.target_key(): prepared.current_value,
                }
            )
            outcome = ApprovalExecutionService(
                policy,
                state,
                adapter,
                clock=lambda: NOW,
            ).execute(request)
        self.assertEqual(ExecutionStatus.APPLIED, outcome.status)
        self.assertEqual("SUSPENDED", outcome.observed_value)
        self.assertEqual(1, adapter.write_calls)

    def test_model_cost_ledger_counts_invalid_calls_warns_and_blocks_at_cap(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = copy.deepcopy(load_policy())
            policy["llm_cost"]["exchange_rate_rub_per_usd"] = "100"
            policy["llm_cost"]["tariffs"] = [
                {
                    "provider": "metered",
                    "model_id": "invalid-schema-v1",
                    "input_usd_per_million": "100000",
                    "output_usd_per_million": "0",
                }
            ]
            provider = MeteredInvalidProvider()
            ledger = DurableModelCostLedger(root / "cost.sqlite3", policy)
            projection = build_sanitized_projection(
                json.loads(LLM_FIXTURE.read_text(encoding="utf-8")),
                policy,
            )
            service = RecommendationService(
                provider,
                ImmutableProposalStore(root / "proposals"),
                policy,
                cost_ledger=ledger,
            )
            invalid = service.recommend(
                projection=projection,
                run_id="metered-invalid",
                snapshot_id="sha256:" + "a" * 64,
                expected_fingerprint="sha256:" + "b" * 64,
                created_at="2026-07-29T09:00:00+00:00",
                expires_at="2026-07-29T09:30:00+00:00",
            )
            ledger.record_synthetic_cost("synthetic-to-80", "600")
            at_warning = ledger.usage()
            ledger.record_synthetic_cost("synthetic-to-100", "400")
            exhausted = ledger.usage()
            blocked = service.recommend(
                projection=projection,
                run_id="metered-blocked",
                snapshot_id="sha256:" + "c" * 64,
                expected_fingerprint="sha256:" + "d" * 64,
                created_at="2026-07-29T09:01:00+00:00",
                expires_at="2026-07-29T09:31:00+00:00",
            )
            malformed_provider = MalformedBoundaryProvider()
            malformed_ledger = DurableModelCostLedger(
                root / "malformed-cost.sqlite3",
                policy,
            )
            malformed = RecommendationService(
                malformed_provider,
                ImmutableProposalStore(root / "malformed-proposals"),
                policy,
                cost_ledger=malformed_ledger,
            ).recommend(
                projection=projection,
                run_id="metered-malformed",
                snapshot_id="sha256:" + "e" * 64,
                expected_fingerprint="sha256:" + "f" * 64,
                created_at="2026-07-29T09:02:00+00:00",
                expires_at="2026-07-29T09:32:00+00:00",
            )
            malformed_usage = malformed_ledger.usage()
        self.assertEqual("INVALID_INPUT", invalid.reason_code)
        self.assertEqual("1000", invalid.provider.cost_rub)
        self.assertEqual(1, provider.invocation_count)
        self.assertTrue(at_warning.warning)
        self.assertEqual("1600", at_warning.charged_cost_rub)
        self.assertTrue(exhausted.exhausted)
        self.assertEqual("2000", exhausted.charged_cost_rub)
        self.assertEqual("MODEL_COST_LIMIT_EXHAUSTED", blocked.reason_code)
        self.assertEqual(1, provider.invocation_count)
        self.assertEqual(
            "MODEL_USAGE_METADATA_INVALID",
            malformed.reason_code,
        )
        self.assertEqual("1000", malformed_usage.charged_cost_rub)
        self.assertEqual("0", malformed_usage.reserved_cost_rub)
        self.assertEqual(1, malformed_provider.invocation_count)
        self.assertEqual([], validate_policy(load_policy(), profile="simulation"))

    def test_site_publication_accepts_mandate_and_records_verified_principal(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            policy, store, _, _, service = goal_components(Path(temporary))
            candidate = create_goal_candidate(
                policy,
                store,
                service,
                run_id="site-mandate",
            )
            publication = publish_goal_candidate(
                policy,
                store,
                service,
                candidate,
                kind=AuthorityKind.MANDATE,
            )
        self.assertEqual("sviridov", publication.author)
        self.assertEqual("sim-test-site-zone", publication.site_zone)

    def test_goal_cleanup_resumes_after_external_rollback_before_progress_write(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            policy, store, goal_adapter, site_adapter, service = goal_components(
                Path(temporary)
            )
            candidate = create_goal_candidate(
                policy,
                store,
                service,
                run_id="cleanup-restart",
            )
            publish_goal_candidate(
                policy,
                store,
                service,
                candidate,
                kind=AuthorityKind.APPROVAL,
            )
            service.decide_business_semantics(
                candidate.candidate_id,
                approved=False,
                reviewer="sviridov",
                now=GOAL_NOW,
            )
            with (
                mock.patch.object(
                    store,
                    "mark_cleanup_publication_rolled_back",
                    side_effect=sqlite3.OperationalError(
                        "Injected progress persistence failure."
                    ),
                ),
                self.assertRaises(sqlite3.OperationalError),
            ):
                service.cleanup_rejected_candidate(
                    candidate.candidate_id,
                    candidate.run_id,
                )
            service.cleanup_rejected_candidate(
                candidate.candidate_id,
                candidate.run_id,
            )
            service.cleanup_rejected_candidate(
                candidate.candidate_id,
                candidate.run_id,
            )
        self.assertEqual(1, site_adapter.rollback_calls)
        self.assertEqual(1, goal_adapter.delete_calls)

    def test_campaign_preflight_rejection_keeps_authority_reserved_and_no_marker(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = load_policy()
            authority_service = lifecycle_authority(policy)
            draft = validate_campaign_draft(
                _campaign_payload(),
                policy,
                _campaign_safety(),
            )
            request = _campaign_request(draft)
            store = CampaignSagaStore(root / "campaign.sqlite3", authority_service)
            _register_campaign_authority(store, request, policy)
            state = DurableControlState(root / "control.sqlite3")
            principal = FixedAuthenticator().authenticate()
            state.engage_kill_switch(
                "global",
                "Block the campaign before its first fake dispatch.",
                principal,
                CAMPAIGN_NOW,
            )
            adapter = FakeDirectManagementAdapter()
            service = CampaignLifecycleService(
                policy,
                store,
                DirectManagementConnectorV1(
                    policy,
                    adapter,
                    store,
                    control_state=state,
                    trusted_scope=_scope("campaign-lifecycle"),
                ),
                _campaign_safety(),
            )
            with self.assertRaisesRegex(ControlRejected, "KILL_SWITCH_ACTIVE"):
                service.execute(request, CAMPAIGN_NOW)
            with sqlite3.connect(str(store.path)) as connection:
                reservation_status = connection.execute(
                    "SELECT status FROM creation_reservations "
                    "WHERE reservation_id = ?",
                    (request.reservation_id,),
                ).fetchone()[0]
            approval_status = store.campaign_approval_status(request.approval_id)
            pending_step = store.pending_dispatched_step(request.execution_key)
        self.assertEqual("RESERVED", approval_status)
        self.assertEqual("RESERVED", reservation_status)
        self.assertIsNone(pending_step)
        self.assertEqual([], adapter.calls)

    def test_campaign_final_guard_rejection_cancels_unsent_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = load_policy()
            draft = validate_campaign_draft(
                _campaign_payload(),
                policy,
                _campaign_safety(),
            )
            request = _campaign_request(draft)
            store = CampaignSagaStore(
                root / "campaign.sqlite3",
                lifecycle_authority(policy),
            )
            _register_campaign_authority(store, request, policy)
            state = DurableControlState(root / "control.sqlite3")
            adapter = FakeDirectManagementAdapter()
            service = CampaignLifecycleService(
                policy,
                store,
                DirectManagementConnectorV1(
                    policy,
                    adapter,
                    store,
                    control_state=state,
                    trusted_scope=_scope("campaign-lifecycle"),
                ),
                _campaign_safety(),
            )
            dispatch_checks = 0

            def reject_second_dispatch(scope) -> None:
                nonlocal dispatch_checks
                del scope
                dispatch_checks += 1
                if dispatch_checks == 2:
                    raise ControlRejected(
                        "KILL_SWITCH_ACTIVE",
                        "The final pre-transport guard rejected the dispatch.",
                    )

            with (
                mock.patch.object(
                    state,
                    "require_dispatch_allowed",
                    side_effect=reject_second_dispatch,
                ),
                self.assertRaisesRegex(ControlRejected, "KILL_SWITCH_ACTIVE"),
            ):
                service.execute(request, CAMPAIGN_NOW)
            approval_status = store.campaign_approval_status(request.approval_id)
            pending_step = store.pending_dispatched_step(request.execution_key)
        self.assertEqual(2, dispatch_checks)
        self.assertEqual("RESERVED", approval_status)
        self.assertIsNone(pending_step)
        self.assertEqual([], adapter.calls)

    def test_campaign_post_write_authority_failure_blocks_blind_retry(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = load_policy()
            draft = validate_campaign_draft(
                _campaign_payload(),
                policy,
                _campaign_safety(),
            )
            request = _campaign_request(draft)
            store = CampaignSagaStore(
                root / "campaign.sqlite3",
                lifecycle_authority(policy),
            )
            _register_campaign_authority(store, request, policy)
            adapter = FakeDirectManagementAdapter()
            service = CampaignLifecycleService(
                policy,
                store,
                DirectManagementConnectorV1(
                    policy,
                    adapter,
                    store,
                    control_state=DurableControlState(
                        root / "control.sqlite3"
                    ),
                    trusted_scope=_scope("campaign-lifecycle"),
                ),
                _campaign_safety(),
            )
            with mock.patch.object(
                store,
                "consume_first_write_authority",
                side_effect=sqlite3.OperationalError(
                    "Injected authority persistence failure."
                ),
            ):
                first = service.execute(request, CAMPAIGN_NOW)
            repeated = service.execute(request, CAMPAIGN_NOW)
            approval_status = store.campaign_approval_status(
                request.approval_id
            )
            pending_step = store.pending_dispatched_step(
                request.execution_key
            )
        self.assertEqual("UNKNOWN_RESULT", first.status)
        self.assertEqual("UNKNOWN_RESULT", repeated.status)
        self.assertEqual("RESERVED", approval_status)
        self.assertEqual("CAMPAIGN_ADD", pending_step)
        self.assertEqual(1, len(adapter.calls))

    def test_global_kill_switch_blocks_goal_fake_and_releases_reservations(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = DurableControlState(root / "control.sqlite3")
            principal = FixedAuthenticator().authenticate()
            state.engage_kill_switch(
                "global",
                "Block the next goal fake dispatch.",
                principal,
                NOW,
            )
            policy, store, adapter, _, service = goal_components(
                root,
                control_state=state,
            )
            proposal_id, reservation_id, authority_id = register_goal_creation(
                policy,
                store,
                run_id="goal-kill",
            )
            with self.assertRaisesRegex(
                GoalLifecycleRejected,
                "KILL_SWITCH_ACTIVE",
            ):
                service.create_candidate(
                    run_id="goal-kill",
                    proposal_id=proposal_id,
                    reservation_id=reservation_id,
                    authority_id=authority_id,
                    counter_id="sim-test-counter",
                    credential_profile="METRIKA_TEST_WRITE",
                    payload=_goal_payload(),
                    now=GOAL_NOW,
                )
            reservation_status = store.reservation_status(reservation_id)
            authority_status = store.authority_status(authority_id)
        self.assertEqual(0, adapter.add_calls)
        self.assertEqual("AVAILABLE", reservation_status)
        self.assertEqual("ACTIVE", authority_status)

    def test_kill_switch_preserves_direct_readback_but_blocks_write(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = load_policy()
            store = CampaignSagaStore(root / "registry.sqlite3")
            state = DurableControlState(root / "control.sqlite3")
            adapter = FakeDirectManagementAdapter()
            connector = DirectManagementConnectorV1(
                policy,
                adapter,
                store,
                control_state=state,
            )
            run_id = "kill-switch-readback"
            created = connector.campaigns_add(
                run_id,
                "seed-campaign",
                {
                    "type": "UNIFIED_CAMPAIGN",
                    "state": "SUSPENDED",
                },
            )
            store.register_created_objects(
                run_id,
                "seed-campaign",
                created,
            )
            state.engage_kill_switch(
                "global",
                "Keep reconciliation reads available while blocking writes.",
                FixedAuthenticator().authenticate(),
                NOW,
            )
            readback = connector.campaigns_get(
                run_id,
                (created[0].object_id,),
            )
            with self.assertRaisesRegex(
                ControlRejected,
                "KILL_SWITCH_ACTIVE",
            ):
                connector.campaigns_update(
                    run_id,
                    created[0].object_id,
                    {"WeeklySpendLimit": 1_000_000_000},
                )
        self.assertEqual(created[0].object_id, readback[0]["id"])
        self.assertEqual(1, adapter.operation_count("Campaigns", "add"))
        self.assertEqual(1, adapter.operation_count("Campaigns", "get"))
        self.assertEqual(0, adapter.operation_count("Campaigns", "update"))

    def test_malformed_observe_input_returns_human_help_contract_and_artifacts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = json.loads(OBSERVE_FIXTURE.read_text(encoding="utf-8"))
            fixture["direct_report"] = []
            fixture_path = root / "malformed.json"
            fixture_path.write_text(
                json.dumps(fixture),
                encoding="utf-8",
            )
            outcome = run_observe_fixture(
                run_id="malformed-observe",
                runs_root=root / "runs",
                fixture_path=fixture_path,
                policy_path=POLICY_PATH,
            )
            run = Path(outcome.run_directory)
            result = json.loads(
                (run / "result.json").read_text(encoding="utf-8")
            )
            report_exists = (run / "report.md").is_file()
            events_exist = (run / "events.jsonl").is_file()
        self.assertEqual("REJECTED", outcome.status)
        self.assertEqual("NEEDS_HUMAN", result["decision_status"])
        self.assertEqual("REQUEST_HUMAN_HELP", result["decision_action"])
        self.assertEqual("INVALID_INPUT", result["reason_code"])
        self.assertTrue(report_exists)
        self.assertTrue(events_exist)

    def test_failed_e2e_and_invalid_run_id_retain_safe_mandatory_artifacts(
        self,
    ) -> None:
        def fail_after_partial_finalization(*args, **kwargs):
            del args
            workspace = kwargs["workspace"]
            workspace.write_json("result.json", {"status": "SUCCEEDED"})
            workspace.write_text("report.md", "Успешный результат.")
            workspace.write_text(
                "events.jsonl",
                '{"event_type":"e2e.completed"}\n',
            )
            raise RuntimeError("Injected partial finalization failure.")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "runs"
            with (
                mock.patch.object(
                    e2e_runner,
                    "_analytics_optimization_workflow",
                    side_effect=RuntimeError("Injected workflow failure."),
                ),
                self.assertRaises(RuntimeError),
            ):
                run_readonly_e2e(root, "failed-run")
            failed = root / "failed-run"
            with (
                mock.patch.object(
                    e2e_runner,
                    "_analytics_optimization_workflow",
                    return_value=(
                        {},
                        {"execution": {"final_object_state": {}}},
                    ),
                ),
                mock.patch.object(
                    e2e_runner,
                    "_campaign_goal_workflow",
                    return_value={
                        "campaign_status": "APPLIED",
                        "campaign_rollback_status": "PARTIALLY_APPLIED",
                        "goal_technical_status": "VERIFIED",
                        "goal_semantic_status": "REJECTED",
                    },
                ),
                mock.patch.object(
                    e2e_runner,
                    "write_final_e2e_artifacts",
                    side_effect=fail_after_partial_finalization,
                ),
                self.assertRaises(RuntimeError),
            ):
                run_readonly_e2e(root, "partial-run")
            partial = root / "partial-run"
            rejected = run_readonly_e2e(root, "../../escaped")
            failed_result = json.loads(
                (failed / "result.json").read_text(encoding="utf-8")
            )
            partial_result = json.loads(
                (partial / "result.json").read_text(encoding="utf-8")
            )
            partial_events = (partial / "events.jsonl").read_text(
                encoding="utf-8"
            )
            partial_report = (partial / "report.md").read_text(
                encoding="utf-8"
            )
            rejected_result = json.loads(
                (rejected / "result.json").read_text(encoding="utf-8")
            )
            mandatory_artifacts_exist = all(
                (run / name).is_file()
                for run in (failed, partial, rejected)
                for name in ("result.json", "report.md", "events.jsonl")
            )
            rejected_is_contained = rejected.parent == root
        self.assertTrue(mandatory_artifacts_exist)
        self.assertEqual("FAILED", failed_result["status"])
        self.assertEqual("FAILED", partial_result["status"])
        self.assertIn("e2e.failed", partial_events)
        self.assertIn("Неуспешный", partial_report)
        self.assertEqual("INVALID_RUN_ID", rejected_result["blocking_code"])
        self.assertTrue(rejected_is_contained)

    def test_pacing_is_not_applicable_when_report_and_budget_periods_differ(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = json.loads(OBSERVE_FIXTURE.read_text(encoding="utf-8"))
            fixture["generated_at"] = "2026-07-24T12:00:00+00:00"
            fixture["direct_report"]["source"] = "DIRECT_REPORTS"
            fixture["direct_state"]["source"] = "DIRECT_CAMPAIGN_STATE"
            fixture["metrika_report"]["source"] = "METRIKA_REPORT"
            fixture["direct_report"]["period_end"] = "2026-07-23"
            fixture["metrika_report"]["period_end"] = "2026-07-23"
            fixture["direct_report"]["rows"] = fixture["direct_report"]["rows"][:3]
            fixture["metrika_report"]["rows"] = fixture["metrika_report"]["rows"][:3]
            for block in ("direct_report", "direct_state", "metrika_report"):
                fixture[block]["retrieved_at"] = "2026-07-24T12:00:00+00:00"
                fixture[block]["watermark"] = "2026-07-24T11:59:00+00:00"
            path = root / "partial-period.json"
            path.write_text(json.dumps(fixture), encoding="utf-8")
            snapshot = e2e_runner._build_snapshot(path)
        self.assertEqual("PARTIAL", snapshot.comparability_status)
        self.assertIn(
            "PACING_BUDGET_PERIOD_MISMATCH",
            snapshot.data_quality_gaps,
        )
        self.assertEqual("NOT_APPLICABLE", snapshot.metrics["pacing_percent"])
        self.assertNotEqual("NOT_APPLICABLE", snapshot.metrics["cpa_rub"])

    def test_active_proposal_is_unique_by_snapshot_and_normalized_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            policy = load_policy()
            provider = DeterministicFakeModelProvider()
            store = ImmutableProposalStore(Path(temporary) / "proposals")
            service = RecommendationService(provider, store, policy)
            projection = build_sanitized_projection(
                json.loads(LLM_FIXTURE.read_text(encoding="utf-8")),
                policy,
            )
            first = service.recommend(
                projection=projection,
                run_id="first-run",
                snapshot_id="sha256:" + "a" * 64,
                expected_fingerprint="sha256:" + "b" * 64,
                created_at="2026-07-29T09:00:00+00:00",
                expires_at="2026-07-29T09:30:00+00:00",
            )
            second = service.recommend(
                projection=projection,
                run_id="second-run",
                snapshot_id="sha256:" + "a" * 64,
                expected_fingerprint="sha256:" + "b" * 64,
                created_at="2026-07-29T09:05:00+00:00",
                expires_at="2026-07-29T09:35:00+00:00",
            )
        self.assertIsNotNone(first.proposal)
        self.assertIsNotNone(second.proposal)
        self.assertEqual(first.proposal.proposal_id, second.proposal.proposal_id)
        self.assertTrue(second.deduplicated)
        self.assertEqual(1, provider.invocation_count)

    def test_zero_conversion_impact_still_produces_observed_report(self) -> None:
        policy = load_policy()
        request = load_impact_fixture(IMPACT_FIXTURE, policy)
        baseline = replace(
            request.baseline,
            metrics={**request.baseline.metrics, "goal_visits": 0},
        )
        post_change = replace(
            request.post_change,
            metrics={**request.post_change.metrics, "goal_visits": 0},
        )
        report = ImpactEvaluator(policy).evaluate(
            replace(
                request,
                fixture_name="IMPACT_ZERO_CONVERSION",
                baseline=baseline,
                post_change=post_change,
            )
        )
        self.assertEqual("OBSERVED_POST_CHANGE", report.status)
        self.assertEqual("NOT_APPLICABLE", report.baseline["cpa_rub"])
        self.assertEqual("NOT_APPLICABLE", report.post_change["cpa_rub"])
        self.assertEqual("ESCALATE_TO_HUMAN", report.next_decision)

    def test_monitoring_evaluates_freshness_with_post_read_clock(self) -> None:
        snapshot = e2e_runner._build_snapshot(OBSERVE_FIXTURE)
        clock = AdvancingClock(datetime.fromisoformat(snapshot.generated_at))
        source = AdvancingReadSource(MonitoringRead(snapshot=snapshot), clock)
        with tempfile.TemporaryDirectory() as temporary:
            outcome = MonitoringScheduler(
                policy=load_policy(),
                source=source,
                store=MonitoringStore(Path(temporary) / "monitoring.sqlite3"),
                clock=clock,
                lease_timeout=timedelta(hours=1),
            ).poll()
        reasons = {item.reason_code for item in outcome.anomalies}
        self.assertIn("DIRECT_DATA_STALE", reasons)
        self.assertEqual((), outcome.proposals)


if __name__ == "__main__":
    unittest.main()
