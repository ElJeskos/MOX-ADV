"""Executable local E2E workflow with all write-class paths sealed locally."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from mox_adv.approval_execution import (
    ApprovalExecutionService,
    ExecutionFacts,
    ExecutionRequest,
)
from mox_adv.autonomy import (
    BoundedAutonomyRequest,
    BoundedAutonomyService,
    DurableMandateAuthority,
    HMACMandateSigner,
    MandateRecord,
)
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
from mox_adv.commands import OptimizationAction, calculate_relative_target
from mox_adv.connectors import (
    FixtureAnalyticsConnectorV1,
    FixtureAnalyticsReadConnectorsV1,
)
from mox_adv.control_state import (
    AuthenticatedPrincipal,
    DurableControlState,
    PreparedChange,
    TrustedScope,
)
from mox_adv.direct_management import (
    DirectManagementConnectorV1,
    FakeDirectManagementAdapter,
)
from mox_adv.e2e_browser import exercise_goal_event
from mox_adv.e2e_evidence import (
    ReadOnlyEgressRecorder,
    write_failed_e2e_artifacts,
    write_final_e2e_artifacts,
)
from mox_adv.artifacts import RUN_ID_PATTERN, RunWorkspace
from mox_adv.fake_write_adapter import FakeWriteAdapter
from mox_adv.goal_lifecycle import (
    AuthorityKind,
    FakeMetrikaGoalAdapter,
    FakeSitePublishAdapter,
    GoalAuthority,
    GoalLifecycleService,
    GoalLifecycleStore,
    goal_creation_binding,
    site_publish_binding,
    site_publish_diff,
)
from mox_adv.goal_lifecycle import (
    CreationReservation as GoalCreationReservation,
)
from mox_adv.impact import (
    ImpactEvaluationRequest,
    ImpactEvaluator,
    ImpactObservation,
)
from mox_adv.lifecycle_authority import LifecycleAuthorityService
from mox_adv.model_provider import DeterministicFakeModelProvider
from mox_adv.monitoring import MonitoringRead, MonitoringScheduler, MonitoringStore
from mox_adv.observe import (
    load_linked_fixture,
    load_observe_policy,
    read_observe_snapshot,
    run_observe_fixture,
    trusted_fixture_scope,
)
from mox_adv.proposal_store import ImmutableProposalStore
from mox_adv.recommend_contracts import CampaignDraftV1
from mox_adv.recommend_projection import (
    campaign_fingerprint,
    projection_from_integrated_snapshot,
)
from mox_adv.recommend_service import RecommendationService

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "gate0-policy.json"
OBSERVE_FIXTURE = ROOT / "fixtures" / "linked-observe.json"
LLM_FIXTURE = ROOT / "fixtures" / "llm" / "LLM_EFFECTIVE_BUDGET_PRESSURE.json"
IMPACT_FIXTURE = ROOT / "fixtures" / "impact" / "IMPACT_CPA_IMPROVED_KEEP.json"
NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
CAMPAIGN_NOW = datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc)
GOAL_NOW = CAMPAIGN_NOW


def load_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _scope(campaign: str = "campaign-1") -> TrustedScope:
    return TrustedScope(
        organization="sim-organization",
        connection="sim-connection",
        account="sim-direct-account",
        campaign=campaign,
        writer="sim-executor",
    )


def _approval_prepared(proposal_id: str) -> PreparedChange:
    current_value = 2_000_000_000
    return PreparedChange(
        proposal_id=proposal_id,
        proposal_hash="sha256:" + "1" * 64,
        scope=_scope(),
        action=OptimizationAction.INCREASE_WEEKLY_BUDGET,
        current_value=current_value,
        target_value=calculate_relative_target(current_value, 10),
        expected_diff={
            "operation": "INCREASE_WEEKLY_BUDGET",
            "relative_step_percent": 10,
        },
        snapshot_id="snapshot-e2e-approval",
        snapshot_generated_at="2026-07-30T11:55:00+00:00",
        direct_watermark="2026-07-30T11:55:00+00:00",
        metrika_watermark="2026-07-30T11:55:00+00:00",
        policy_version="mox-adv-gate0-2026-07-29",
        expected_fingerprint="sha256:" + "2" * 64,
        risk="WEEKLY_BUDGET_INCREASE",
    )


def _approval_request(prepared: PreparedChange) -> ExecutionRequest:
    return ExecutionRequest(
        proposal_id=prepared.proposal_id,
        execution_key=prepared.execution_key(),
        scope=prepared.scope,
        facts=ExecutionFacts(
            mode="APPROVAL_REQUIRED",
            automation_enabled=True,
            comparability_status="COMPARABLE",
            confidence_status="READY",
            financial_recommendations_allowed=True,
            direct_age_minutes=5,
            metrika_age_minutes=5,
            watermark_skew_minutes=1,
            clicks=100,
            conversions=12,
            impressions=10_000,
            spend_rub=1_900,
            cpa_rub="791.67",
            budget_utilization_percent="95",
            ctr_percent="1",
            campaign_state="ON",
            campaign_strategy="HIGHEST_POSITION",
            current_fingerprint=prepared.expected_fingerprint,
            cooldown_active=False,
            actions_in_last_24h=0,
            cumulative_daily_change_percent=0,
            monetary_exposure_rub=200,
            kill_switch_available=True,
        ),
    )


def _autonomy_prepared(proposal_id: str) -> PreparedChange:
    current_value = 100_000_000
    return PreparedChange(
        proposal_id=proposal_id,
        proposal_hash="sha256:" + "3" * 64,
        scope=_scope(),
        action=OptimizationAction.DECREASE_SEARCH_BID,
        current_value=current_value,
        target_value=calculate_relative_target(current_value, -10),
        expected_diff={
            "operation": "DECREASE_SEARCH_BID",
            "relative_step_percent": 10,
        },
        snapshot_id="snapshot-e2e-autonomy",
        snapshot_generated_at="2026-07-30T11:55:00+00:00",
        direct_watermark="2026-07-30T11:55:00+00:00",
        metrika_watermark="2026-07-30T11:55:00+00:00",
        policy_version="mox-adv-gate0-2026-07-29",
        expected_fingerprint="sha256:" + "4" * 64,
        risk="BOUNDED_AUTONOMY_REVERSIBLE_ACTION",
    )


def _mandate_payload(
    policy: Mapping[str, Any],
    issued_at: datetime = NOW,
) -> Mapping[str, Any]:
    return {
        "organization": "sim-organization",
        "connection": "sim-connection",
        "account": "sim-direct-account",
        "environment": "SIMULATION",
        "credential_profile": "DIRECT_PILOT_WRITE",
        "targets": ["campaign-1"],
        "allowed_action_classes": [
            "DECREASE_SEARCH_BID",
            "SUSPEND_CAMPAIGN",
        ],
        "prohibited_action_classes": list(
            policy["mandate"]["prohibited_action_classes"]
        ),
        "total_monetary_limit": 500,
        "daily_monetary_limit": 500,
        "maximum_step_change": 10,
        "maximum_daily_change": 10,
        "kpi": {"name": "CPA_RUB", "target_maximum": 1000},
        "minimum_sample": {"clicks": 50, "conversions": 3},
        "cooldown": {"hours": 72, "observation_window_hours": 72},
        "stop_conditions": list(policy["mandate"]["stop_conditions"]),
        "action_quotas": {"actions_per_24h": 1},
        "platform_side_spend_cap": 3000,
        "issuer": {
            "identity": "sviridov",
            "authentication": "authenticated_macos_user",
        },
        "policy_version": "mox-adv-gate0-2026-07-29",
        "issued_at": issued_at.isoformat(),
        "expiry": (issued_at + timedelta(hours=24)).isoformat(),
    }


def _autonomy_request(
    prepared: PreparedChange,
    mandate: MandateRecord,
) -> BoundedAutonomyRequest:
    return BoundedAutonomyRequest(
        mandate_id=mandate.mandate_id,
        proposal_id=prepared.proposal_id,
        execution_key=prepared.execution_key(),
        scope=prepared.scope,
        mode="BOUNDED_AUTONOMY",
        automation_enabled=True,
        comparability_status="COMPARABLE",
        confidence_status="READY",
        financial_recommendations_allowed=True,
        direct_age_minutes=5,
        metrika_age_minutes=5,
        watermark_skew_minutes=1,
        clicks=50,
        conversions=3,
        spend_rub=1_900,
        cpa_rub="1200",
        budget_utilization_percent="80",
        campaign_state="ON",
        campaign_strategy="HIGHEST_POSITION",
        current_fingerprint=prepared.expected_fingerprint,
    )


def _campaign_payload() -> Mapping[str, Any]:
    return {
        "schema_version": "campaign-draft-v1",
        "draft_id": "draft-campaign-e2e",
        "business_goal": {
            "event": "lead_submitted",
            "meaning": "A visitor submitted the lead form.",
        },
        "primary_conversion": {"event": "lead_submitted"},
        "campaign_type": "UNIFIED_CAMPAIGN",
        "strategy": {
            "placement": "SEARCH",
            "search": "HIGHEST_POSITION",
            "network": "SERVING_OFF",
        },
        "geography": ["RU"],
        "schedule": {
            "timezone": "Europe/Moscow",
            "days": ["MONDAY", "TUESDAY"],
            "start": "09:00",
            "end": "18:00",
        },
        "budget": {"currency": "RUB", "weekly_micros": 500_000_000},
        "limits": {
            "maximum_weekly_micros": 500_000_000,
            "maximum_bid_micros": 100_000_000,
        },
        "groups": [
            {
                "name": "Lead service",
                "keywords": ["lead service"],
                "negative_keywords": ["free"],
                "audiences": [],
                "ads": [
                    {
                        "variant_id": "A",
                        "title": "Lead service",
                        "text": "Submit a request",
                        "landing_page": "https://allowlisted.example/lead",
                        "utm": "utm_source=yandex&utm_content=a",
                        "media_reference": "prepared-media-1",
                    },
                    {
                        "variant_id": "B",
                        "title": "Lead service alternative",
                        "text": "Request a consultation",
                        "landing_page": "https://allowlisted.example/lead",
                        "utm": "utm_source=yandex&utm_content=b",
                        "media_reference": "prepared-media-2",
                    },
                ],
            }
        ],
        "landing_page": "https://allowlisted.example/lead",
        "media_references": ["prepared-media-1", "prepared-media-2"],
    }


def _campaign_safety() -> CampaignDraftSafetyBindings:
    return CampaignDraftSafetyBindings(
        allowed_landing_hosts=("allowlisted.example",),
        prohibited_phrases=("guaranteed results",),
        prepared_media_references=("prepared-media-1", "prepared-media-2"),
    )


def _campaign_reservation() -> CampaignCreationReservation:
    return CampaignCreationReservation(
        reservation_id="sim-campaign-creation-reservation",
        status=CreationReservationStatus.AVAILABLE,
        scope_binding="sim-direct-account",
        object_type="UNIFIED_CAMPAIGN",
        proposal_id="proposal-create-1",
        credential_profile="DIRECT_PILOT_WRITE",
        expires_at=CAMPAIGN_NOW + timedelta(minutes=30),
    )


def _campaign_request(draft: CampaignDraftV1) -> CampaignCreationRequest:
    return CampaignCreationRequest(
        run_id="run-create-e2e",
        execution_key="execution-create-e2e",
        proposal_id="proposal-create-1",
        approval_id="approval-create-e2e",
        account="sim-direct-account",
        credential_profile="DIRECT_PILOT_WRITE",
        reservation_id="sim-campaign-creation-reservation",
        draft=draft,
    )


def _register_campaign_authority(
    store: CampaignSagaStore,
    request: CampaignCreationRequest,
    policy: Mapping[str, Any],
) -> None:
    store.register_creation_reservation(_campaign_reservation(), CAMPAIGN_NOW)
    store.register_campaign_approval(
        CampaignApproval(
            approval_id=request.approval_id,
            proposal_id=request.proposal_id,
            binding_hash=request.approval_binding(str(policy["policy_id"])),
            approver="sviridov",
            authentication="authenticated_macos_user",
            expires_at=CAMPAIGN_NOW + timedelta(minutes=15),
        ),
        CAMPAIGN_NOW,
    )


def _goal_payload() -> Mapping[str, Any]:
    return {
        "schema_version": "goal-candidate-v1",
        "name": "Submitted lead",
        "event": "lead_submitted",
        "site_location": "#lead-form",
        "type": "ACTION",
        "business_meaning": "A visitor submitted the lead form.",
        "priority": 1,
        "duplicate_signals": [],
    }


def _build_snapshot(fixture_path: Path = OBSERVE_FIXTURE):
    observe_policy = load_observe_policy(POLICY_PATH)
    fixture = load_linked_fixture(fixture_path)
    connected = FixtureAnalyticsConnectorV1().read_linked(fixture)
    trusted_scope = trusted_fixture_scope(
        observe_policy,
        connected.observation_id,
    )
    reads = FixtureAnalyticsReadConnectorsV1(connected)
    return read_observe_snapshot(
        policy=observe_policy,
        observation_id=connected.observation_id,
        generated_at=connected.generated_at,
        period_start=connected.direct_report.period_start,
        period_end=connected.direct_report.period_end,
        trusted_scope=trusted_scope,
        direct_reports=reads,
        direct_state=reads,
        metrika_report=reads,
        baseline=connected.baseline,
    )


def _impact_observation(snapshot, label: str) -> ImpactObservation:
    return ImpactObservation.from_mapping(
        {
            "snapshot_id": snapshot.snapshot_id,
            "campaign": snapshot.scope.campaign,
            "period_start": snapshot.period_start,
            "period_end": snapshot.period_end,
            "watermarks": {
                "direct_report": snapshot.provenance.direct_report.watermark,
                "direct_state": snapshot.provenance.direct_state.watermark,
                "metrika_report": snapshot.provenance.metrika_report.watermark,
            },
            "metrics": {
                "impressions": int(snapshot.metrics["impressions"]),
                "clicks": int(snapshot.metrics["clicks"]),
                "cost_micros": int(snapshot.metrics["cost_micros"]),
                "visits": int(snapshot.metrics["visits"]),
                "goal_visits": int(snapshot.metrics["goal_visits"]),
            },
            "comparability_status": snapshot.comparability_status,
            "confidence_status": snapshot.confidence_status,
        },
        label,
    )


def _build_post_change_snapshot(
    working: Path,
    fixture: Mapping[str, Any],
    observed_budget: object,
    changed_at: datetime,
):
    post_fixture = copy.deepcopy(fixture)
    dates = (
        "2026-07-29",
        "2026-07-30",
        "2026-07-31",
        "2026-08-01",
        "2026-08-02",
        "2026-08-03",
        "2026-08-04",
    )
    direct_values = (
        (1_500, 30, 300_000_000),
        (1_500, 30, 300_000_000),
        (1_600, 32, 360_000_000),
        (1_600, 32, 360_000_000),
        (1_600, 32, 360_000_000),
        (1_600, 32, 360_000_000),
        (1_600, 32, 360_000_000),
    )
    metrika_values = (
        (25, 1),
        (25, 1),
        (26, 1),
        (26, 1),
        (26, 1),
        (26, 1),
        (26, 0),
    )
    post_fixture["generated_at"] = "2026-08-05T00:15:00+00:00"
    direct_report = post_fixture["direct_report"]
    direct_report.update(
        {
            "period_start": dates[0],
            "period_end": dates[-1],
            "retrieved_at": "2026-08-05T00:10:00+00:00",
            "watermark": "2026-08-04T23:59:00+00:00",
        }
    )
    for index, row in enumerate(direct_report["rows"]):
        impressions, clicks, cost_micros = direct_values[index]
        row.update(
            {
                "date": dates[index],
                "impressions": impressions,
                "clicks": clicks,
                "cost_micros": cost_micros,
            }
        )
    direct_state = post_fixture["direct_state"]
    direct_state.update(
        {
            "budget_period_start": "2026-07-29T00:00:00+00:00",
            "budget_period_end": "2026-08-05T00:00:00+00:00",
            "current_weekly_budget_micros": int(observed_budget),
            "object_config_version": "sim-campaign-config-v2",
            "retrieved_at": "2026-08-05T00:09:00+00:00",
            "watermark": "2026-08-04T23:58:00+00:00",
            "last_change": {
                "author": "sviridov",
                "occurred_at": changed_at.isoformat(),
            },
        }
    )
    metrika_report = post_fixture["metrika_report"]
    metrika_report.update(
        {
            "period_start": dates[0],
            "period_end": dates[-1],
            "retrieved_at": "2026-08-05T00:12:00+00:00",
            "watermark": "2026-08-04T23:57:00+00:00",
        }
    )
    for index, row in enumerate(metrika_report["rows"]):
        visits, goal_visits = metrika_values[index]
        row.update(
            {
                "date": dates[index],
                "visits": visits,
                "goal_visits": goal_visits,
            }
        )
    post_fixture_path = working / "linked-post-change.json"
    post_fixture_path.write_text(
        json.dumps(post_fixture, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return _build_snapshot(post_fixture_path)


class _FixedAuthenticator:
    def authenticate(self) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            identity="sviridov",
            authentication="authenticated_macos_user",
        )


class _FixtureReadSource:
    def __init__(self, read: MonitoringRead) -> None:
        self.value = read

    def read(self) -> MonitoringRead:
        return self.value


class _FixedClock:
    def __call__(self) -> datetime:
        return NOW


def _analytics_optimization_workflow(
    working: Path,
    policy: Mapping[str, Any],
) -> tuple[Mapping[str, Mapping[str, Any]], Mapping[str, Any]]:
    linked_fixture = json.loads(OBSERVE_FIXTURE.read_text(encoding="utf-8"))
    linked_fixture["direct_state"]["current_weekly_budget_micros"] = 2_700_000_000
    for row in linked_fixture["direct_report"]["rows"]:
        row["cost_micros"] = int(row["cost_micros"]) // 2
    linked_fixture_path = working / "linked-closed-loop.json"
    linked_fixture_path.write_text(
        json.dumps(linked_fixture, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    components = working / "components"
    outcome = run_observe_fixture(
        run_id="observe",
        runs_root=components,
        fixture_path=linked_fixture_path,
        policy_path=POLICY_PATH,
    )
    if outcome.status != "SUCCEEDED":
        raise AssertionError("OBSERVE did not complete.")
    observe_result = json.loads(
        (components / "observe" / "result.json").read_text(encoding="utf-8")
    )
    if observe_result["external_write_sent"] is not False:
        raise AssertionError("OBSERVE reported external write egress.")

    snapshot = _build_snapshot(linked_fixture_path)
    if snapshot.snapshot_id != observe_result["snapshot_id"]:
        raise AssertionError("OBSERVE snapshot linkage changed.")
    execution_now = datetime.fromisoformat(snapshot.generated_at)
    projection = projection_from_integrated_snapshot(
        snapshot,
        policy,
        execution_now,
    )
    provider = DeterministicFakeModelProvider()
    proposal_store = ImmutableProposalStore(working / "proposals")
    recommendation_service = RecommendationService(
        provider,
        proposal_store,
        policy,
    )
    recommendation = recommendation_service.recommend(
        projection=projection,
        run_id="recommend",
        snapshot_id=snapshot.snapshot_id,
        expected_fingerprint=campaign_fingerprint(snapshot),
        created_at=execution_now.isoformat(),
        expires_at=(execution_now + timedelta(minutes=30)).isoformat(),
    )
    if recommendation.status != "READY" or recommendation.proposal is None:
        raise AssertionError("RECOMMEND did not produce a valid proposal.")
    if recommendation_service.cost_ledger is None:
        raise AssertionError("RECOMMEND cost ledger was not configured.")
    cost_usage = recommendation_service.cost_ledger.usage()
    tariff = next(
        item
        for item in policy["llm_cost"]["tariffs"]
        if item["provider"] == recommendation.provider.provider
        and item["model_id"] == recommendation.provider.model_id
    )

    principal = _FixedAuthenticator().authenticate()
    control_state = DurableControlState(working / "control.sqlite3")
    prepared = control_state.register_optimization_proposal(
        proposal_store=proposal_store,
        proposal_id=recommendation.proposal.proposal_id,
        snapshot=snapshot,
        policy=policy,
        writer=str(policy["bindings"]["simulation"]["single_writer"]),
        at=execution_now,
    )
    linked_clock = lambda: execution_now
    approval = control_state.grant_approval(
        prepared.proposal_id,
        execution_now + timedelta(minutes=15),
        "Approve the exact simulated E2E change.",
        principal,
        execution_now,
    )
    approval_adapter = FakeWriteAdapter(
        initial_state={prepared.target_key(): prepared.current_value},
        current_fingerprints={
            prepared.target_key(): prepared.expected_fingerprint,
        },
    )
    approval_service = ApprovalExecutionService(
        policy,
        control_state,
        approval_adapter,
        clock=linked_clock,
    )
    first = approval_service.execute(_approval_request(prepared))
    repeated = approval_service.execute(_approval_request(prepared))
    if first.status != "APPLIED" or repeated.status != "ALREADY_PROCESSED":
        raise AssertionError("Approval fake execution was not idempotent.")
    if approval_adapter.write_calls != 1:
        raise AssertionError("Approval fake execution wrote more than once.")
    used_approval = control_state.load_approval(approval.approval_id)
    if used_approval.used_at is None:
        raise AssertionError("The exact approval was not consumed.")

    blocked_prepared = _approval_prepared("proposal-e2e-kill-switch")
    control_state.register_prepared_change(blocked_prepared)
    control_state.grant_approval(
        blocked_prepared.proposal_id,
        execution_now + timedelta(minutes=15),
        "Approve only if the kill switch remains inactive.",
        principal,
        execution_now,
    )
    control_state.engage_kill_switch(
        "global",
        "E2E verifies the next unsent command is blocked.",
        principal,
        execution_now,
    )
    blocked_adapter = FakeWriteAdapter(
        initial_state={
            blocked_prepared.target_key(): blocked_prepared.current_value,
        }
    )
    blocked = ApprovalExecutionService(
        policy,
        control_state,
        blocked_adapter,
        clock=linked_clock,
    ).execute(_approval_request(blocked_prepared))
    if blocked.status != "BLOCKED" or blocked_adapter.write_calls != 0:
        raise AssertionError("Kill switch did not block before fake dispatch.")
    control_state.release_kill_switch(
        "global",
        "E2E resumes local fake-only validation.",
        principal,
        execution_now,
    )

    autonomy_now = execution_now + timedelta(hours=73)
    signer = HMACMandateSigner(b"issue-33-local-e2e-mandate-key")
    authority = DurableMandateAuthority(
        control_state.path,
        policy,
        signer,
    )
    issued = authority.issue(
        _mandate_payload(policy, autonomy_now),
        principal,
        autonomy_now,
    )
    mandate = authority.activate(issued.mandate_id, principal, autonomy_now)
    autonomy_prepared = _autonomy_prepared("proposal-e2e-autonomy")
    control_state.register_prepared_change(autonomy_prepared)
    autonomy_adapter = FakeWriteAdapter(
        initial_state={
            autonomy_prepared.target_key(): autonomy_prepared.current_value,
        }
    )
    autonomy_result = BoundedAutonomyService(
        policy,
        control_state,
        authority,
        autonomy_adapter,
        clock=lambda: autonomy_now,
    ).execute(_autonomy_request(autonomy_prepared, mandate))
    if autonomy_result.status != "APPLIED" or autonomy_adapter.write_calls != 1:
        raise AssertionError("Bounded autonomy fake readback failed.")

    scheduler = MonitoringScheduler(
        policy=policy,
        source=_FixtureReadSource(MonitoringRead(snapshot=snapshot)),
        store=MonitoringStore(working / "monitoring.sqlite3"),
        clock=_FixedClock(),
    )
    monitoring = scheduler.poll()
    if monitoring.status != "POLLED":
        raise AssertionError("Monitoring did not produce a new snapshot.")

    impact_evaluated_at = datetime(2026, 8, 8, 0, 0, tzinfo=timezone.utc)
    post_snapshot = _build_post_change_snapshot(
        working,
        linked_fixture,
        first.observed_value,
        execution_now,
    )
    impact = ImpactEvaluator(policy).evaluate(
        ImpactEvaluationRequest(
            fixture_name=str(policy["impact"]["fixture"]["name"]),
            run_id="closed-loop-simulated",
            change_id=prepared.execution_key(),
            policy_version=str(policy["policy_id"]),
            change_applied_at=execution_now.isoformat(),
            evaluated_at=impact_evaluated_at.isoformat(),
            baseline=_impact_observation(snapshot, "Baseline"),
            post_change=_impact_observation(post_snapshot, "Post-change"),
            seasonality="NONE_OBSERVED",
            known_interventions=(),
            confounders=(),
            evidence=(
                "same_campaign_snapshot_chain",
                "sealed_fake_readback",
            ),
        )
    )
    if impact.status != "OBSERVED_POST_CHANGE":
        raise AssertionError("Impact evaluation did not complete.")

    change_diff = {
        "approval_required": {
            "proposal_id": prepared.proposal_id,
            "execution_key": prepared.execution_key(),
            "campaign": prepared.scope.campaign,
            "operation": dict(prepared.expected_diff),
            "before": prepared.current_value,
            "after": prepared.target_value,
            "readback": first.observed_value,
            "status": first.status,
        },
        "bounded_autonomy": {
            "proposal_id": autonomy_prepared.proposal_id,
            "execution_key": autonomy_prepared.execution_key(),
            "operation": dict(autonomy_prepared.expected_diff),
            "before": autonomy_prepared.current_value,
            "after": autonomy_prepared.target_value,
            "readback": autonomy_result.observed_value,
            "status": autonomy_result.status,
        },
    }
    observe_evidence = {
        "source": observe_result["source"],
        "snapshot_id": observe_result["snapshot_id"],
        "campaign": snapshot.scope.campaign,
        "period_start": observe_result["snapshot"]["period_start"],
        "period_end": observe_result["snapshot"]["period_end"],
        "provenance": observe_result["snapshot"]["provenance"],
        "metrics": observe_result["snapshot"]["metrics"],
        "comparability_status": observe_result["snapshot"]["comparability_status"],
        "confidence_status": observe_result["snapshot"]["confidence_status"],
        "external_write_sent": observe_result["external_write_sent"],
    }
    monitoring_evidence = asdict(monitoring)
    closed_loop_envelope = {
        "schema_version": "closed-loop-run-envelope-v1",
        "campaign": snapshot.scope.campaign,
        "snapshot_id": snapshot.snapshot_id,
        "proposal_id": prepared.proposal_id,
        "execution_key": prepared.execution_key(),
        "readback_status": first.status,
        "change_id": impact.change_id,
        "impact_campaign": snapshot.scope.campaign,
        "post_snapshot_id": impact.post_change["snapshot_id"],
        "post_observation_id": post_snapshot.observation_id,
        "post_snapshot_source": "LOCAL_FIXTURE",
        "next_decision": impact.next_decision,
        "evidence_type": "SIMULATED",
        "capability_status": "NOT_PROVEN",
    }
    supplemental = {
        "proposal.json": recommendation.proposal.as_dict(),
        "approval.json": asdict(used_approval),
        "change_diff.json": change_diff,
        "impact_report.json": impact.as_dict(),
        "observe-evidence.json": observe_evidence,
        "monitoring-evidence.json": monitoring_evidence,
        "closed-loop-envelope.json": closed_loop_envelope,
    }
    run_summary = {
        "source": observe_result["source"],
        "snapshot_id": observe_result["snapshot_id"],
        "period_start": observe_result["snapshot"]["period_start"],
        "period_end": observe_result["snapshot"]["period_end"],
        "provenance": observe_result["snapshot"]["provenance"],
        "metrics": observe_result["snapshot"]["metrics"],
        "provider": recommendation.provider.provider,
        "model_id": recommendation.provider.model_id,
        "input_tokens": recommendation.provider.input_tokens,
        "output_tokens": recommendation.provider.output_tokens,
        "cost_rub": recommendation.provider.cost_rub,
        "model_cost": {
            "provider": recommendation.provider.provider,
            "model_id": recommendation.provider.model_id,
            "currency": policy["llm_cost"]["currency"],
            "exchange_rate_rub_per_usd": policy["llm_cost"][
                "exchange_rate_rub_per_usd"
            ],
            "input_usd_per_million": tariff["input_usd_per_million"],
            "output_usd_per_million": tariff["output_usd_per_million"],
            "limit_rub": str(policy["limits"]["llm_total_cost_rub"]),
            "warning_percent": str(policy["limits"]["llm_warning_percent"]),
            "charged_cost_rub": cost_usage.charged_cost_rub,
            "reserved_cost_rub": cost_usage.reserved_cost_rub,
            "call_count": cost_usage.call_count,
            "warning": cost_usage.warning,
            "exhausted": cost_usage.exhausted,
            "configuration_hash": recommendation_service.cost_ledger.config_hash,
        },
        "duration_ms": (
            int(observe_result["duration_ms"]) + recommendation.provider.duration_ms
        ),
        "stage_durations_ms": {
            "observe": int(observe_result["duration_ms"]),
            "recommend": recommendation.provider.duration_ms,
        },
        "proposal_id": recommendation.proposal.proposal_id,
        "policy_decision": {
            "approval_required": first.status,
            "bounded_autonomy": autonomy_result.status,
            "kill_switch": blocked.status,
            "kill_switch_reason": blocked.reason_code,
            "closed_loop_next_decision": impact.next_decision,
        },
        "execution": {
            "technical_command": "SEALED_FAKE_ADAPTERS_AND_LOCAL_INTERCEPTION_ONLY",
            "before": {
                "approval_required": prepared.current_value,
                "bounded_autonomy": autonomy_prepared.current_value,
            },
            "after": {
                "approval_required": prepared.target_value,
                "bounded_autonomy": autonomy_prepared.target_value,
            },
            "readback": {
                "approval_required": first.observed_value,
                "bounded_autonomy": autonomy_result.observed_value,
            },
            "final_object_state": {
                "approval_required": first.status,
                "bounded_autonomy": autonomy_result.status,
                "kill_switch": blocked.status,
            },
        },
    }
    return supplemental, run_summary


def _campaign_goal_workflow(
    working: Path,
    policy: Mapping[str, Any],
    egress: ReadOnlyEgressRecorder,
) -> Mapping[str, Any]:
    control_state = DurableControlState(working / "control.sqlite3")
    lifecycle_authority = LifecycleAuthorityService(
        policy,
        _FixedAuthenticator(),
        HMACMandateSigner(b"issue-23-33-local-lifecycle-key"),
    )
    draft = validate_campaign_draft(
        _campaign_payload(),
        policy,
        _campaign_safety(),
    )
    request = _campaign_request(draft)
    campaign_store = CampaignSagaStore(
        working / "campaign.sqlite3",
        lifecycle_authority,
    )
    _register_campaign_authority(campaign_store, request, policy)
    campaign_adapter = FakeDirectManagementAdapter()
    campaign_service = CampaignLifecycleService(
        policy,
        campaign_store,
        DirectManagementConnectorV1(
            policy,
            campaign_adapter,
            campaign_store,
            control_state=control_state,
            trusted_scope=_scope("campaign-lifecycle"),
        ),
        _campaign_safety(),
    )
    campaign_result = campaign_service.execute(request, CAMPAIGN_NOW)
    repeated = campaign_service.execute(request, CAMPAIGN_NOW)
    if campaign_result.status != "APPLIED" or repeated.status != "ALREADY_PROCESSED":
        raise AssertionError("Campaign saga was not applied idempotently.")
    calls_after_repeat = tuple(campaign_adapter.calls)
    if not calls_after_repeat:
        raise AssertionError("Campaign saga did not exercise fake writes.")

    rollback_store = CampaignSagaStore(
        working / "campaign-rollback.sqlite3",
        lifecycle_authority,
    )
    _register_campaign_authority(rollback_store, request, policy)
    rollback_adapter = FakeDirectManagementAdapter(fail_on=("Ads", "moderate"))
    rollback = CampaignLifecycleService(
        policy,
        rollback_store,
        DirectManagementConnectorV1(
            policy,
            rollback_adapter,
            rollback_store,
            control_state=control_state,
            trusted_scope=_scope("campaign-lifecycle-rollback"),
        ),
        _campaign_safety(),
    ).execute(request, CAMPAIGN_NOW)
    if rollback.status != "PARTIALLY_APPLIED":
        raise AssertionError("Campaign compensation path did not run.")
    if rollback_adapter.object_ids():
        raise AssertionError("Campaign fake rollback left created objects.")

    simulation = policy["bindings"]["simulation"]
    goal_store = GoalLifecycleStore(
        working / "goals.sqlite3",
        lifecycle_authority,
    )
    goal_adapter = FakeMetrikaGoalAdapter(
        (simulation["test_counter"], simulation["pilot_counter"])
    )
    site_adapter = FakeSitePublishAdapter(
        {
            simulation["test_site_zone"]: "test-page-v1",
            simulation["pilot_site_zone"]: "pilot-page-v1",
        }
    )
    goal_service = GoalLifecycleService(
        policy,
        goal_store,
        goal_adapter,
        site_adapter,
        _FixedAuthenticator(),
        control_state,
    )
    run_id = "goal-run-e2e"
    proposal_id = "goal-proposal-e2e"
    reservation = GoalCreationReservation(
        reservation_id="goal-reservation-e2e",
        scope_binding="test_counter",
        object_type="METRIKA_GOAL",
        proposal_id=proposal_id,
        credential_profile="METRIKA_TEST_WRITE",
        expires_at=GOAL_NOW + timedelta(minutes=15),
    )
    candidate_id = "candidate-" + run_id
    creation_authority = GoalAuthority(
        authority_id="goal-authority-e2e",
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
            reservation_id=reservation.reservation_id,
            counter_id=str(simulation["test_counter"]),
            site_zone=str(simulation["test_site_zone"]),
            credential_profile="METRIKA_TEST_WRITE",
            payload=_goal_payload(),
        ),
    )
    goal_store.register_reservation(reservation)
    goal_store.register_authority(creation_authority, GOAL_NOW)
    candidate = goal_service.create_candidate(
        run_id=run_id,
        proposal_id=proposal_id,
        reservation_id=reservation.reservation_id,
        authority_id=creation_authority.authority_id,
        counter_id=str(simulation["test_counter"]),
        credential_profile="METRIKA_TEST_WRITE",
        payload=_goal_payload(),
        now=GOAL_NOW,
    )
    exact_site_diff = site_publish_diff(
        candidate,
        str(simulation["test_site_zone"]),
        "test-page-v1",
    )
    publish_authority = GoalAuthority(
        authority_id="site-publish-approval-e2e",
        kind=AuthorityKind.APPROVAL,
        principal="sviridov",
        authentication="authenticated_macos_user",
        proposal_id=candidate.proposal_id,
        counter_id=candidate.counter_id,
        site_zone=str(simulation["test_site_zone"]),
        allowed_actions=("SITE_PUBLISH",),
        expires_at=GOAL_NOW + timedelta(minutes=15),
        policy_id=str(policy["policy_id"]),
        binding_hash=site_publish_binding(
            policy_id=str(policy["policy_id"]),
            candidate=candidate,
            exact_diff=exact_site_diff,
        ),
    )
    goal_store.register_authority(publish_authority, GOAL_NOW)
    publication = goal_service.publish_candidate_event(
        candidate.candidate_id,
        authority_id=publish_authority.authority_id,
        site_zone=str(simulation["test_site_zone"]),
        expected_version="test-page-v1",
        now=GOAL_NOW,
    )
    event_evidence = exercise_goal_event(
        counter_id=candidate.counter_id,
        event="lead_submitted",
        trigger_selector="#lead-submit",
        configured_selector="#lead-form",
        egress=egress,
    )
    goal_adapter.set_visit_observations(
        candidate.counter_id,
        candidate.goal_id,
        ("PENDING", "DELIVERED"),
    )
    technical = goal_service.verify_candidate_delivery(
        candidate.candidate_id,
        event_evidence,
        now=GOAL_NOW,
    )
    rejected = goal_service.decide_business_semantics(
        candidate.candidate_id,
        approved=False,
        reviewer="sviridov",
        now=GOAL_NOW,
    )
    goal_service.cleanup_rejected_candidate(
        candidate.candidate_id,
        run_id=candidate.run_id,
    )
    if technical.status != "VERIFIED" or rejected.status != "REJECTED":
        raise AssertionError("Goal lifecycle verification failed.")
    if goal_adapter.delete_calls != 1 or site_adapter.rollback_calls != 1:
        raise AssertionError("Goal cleanup did not stay in fake rollback.")

    return {
        "campaign_status": campaign_result.status.value,
        "campaign_completed_steps": [
            str(item) for item in campaign_result.completed_steps
        ],
        "campaign_fake_call_count": len(calls_after_repeat),
        "campaign_rollback_status": rollback.status.value,
        "goal_technical_status": technical.status.value,
        "goal_semantic_status": rejected.status.value,
        "goal_event": asdict(event_evidence),
        "goal_technical_evidence": asdict(technical),
        "goal_site_diff": dict(publication.exact_diff),
        "goal_cleanup": {
            "fake_goal_deletes": 1,
            "fake_site_rollbacks": 1,
        },
        "external_write_sent": False,
    }


def tests_now() -> datetime:
    return NOW


def run_readonly_e2e(runs_root: Path, run_id: str) -> Path:
    policy = load_policy()
    runs_root.mkdir(parents=True, exist_ok=True)
    if RUN_ID_PATTERN.fullmatch(run_id) is None or run_id in {".", ".."}:
        safe_run_id = (
            "rejected-"
            + hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]
        )
        workspace = RunWorkspace.create(runs_root, safe_run_id)
        return write_failed_e2e_artifacts(
            workspace,
            run_id=safe_run_id,
            policy_version=str(policy["policy_id"]),
            reason_code="INVALID_RUN_ID",
            detail="Идентификатор запуска не прошёл локальную проверку.",
        )
    workspace = RunWorkspace.create(runs_root, run_id)
    egress = ReadOnlyEgressRecorder(policy)
    try:
        with TemporaryDirectory(
            prefix=".work-",
            dir=workspace.path,
        ) as temporary:
            work = Path(temporary)
            with egress.enforce_python_sockets():
                analytics_artifacts, summary = _analytics_optimization_workflow(
                    work,
                    policy,
                )
                supplemental = dict(analytics_artifacts)
                run_summary = dict(summary)
                lifecycle = _campaign_goal_workflow(work, policy, egress)
        supplemental["lifecycle-evidence.json"] = lifecycle
        execution = dict(run_summary["execution"])
        final_state = dict(execution["final_object_state"])
        final_state.update(
            {
                "campaign_lifecycle": lifecycle["campaign_status"],
                "campaign_compensation": lifecycle["campaign_rollback_status"],
                "goal_technical": lifecycle["goal_technical_status"],
                "goal_semantic": lifecycle["goal_semantic_status"],
            }
        )
        execution["final_object_state"] = final_state
        run_summary["execution"] = execution
        checks = (
            {"name": "analytics_optimization", "status": "PASSED"},
            {"name": "campaign_goal_lifecycle", "status": "PASSED"},
            {"name": "playwright_local_goal_event", "status": "PASSED"},
            {"name": "external_non_read_egress", "status": "PASSED"},
        )
        return write_final_e2e_artifacts(
            runs_root,
            run_id=run_id,
            policy_version=str(policy["policy_id"]),
            checks=checks,
            egress=egress,
            supplemental_artifacts=supplemental,
            run_summary=run_summary,
            workspace=workspace,
        )
    except BaseException as error:
        write_failed_e2e_artifacts(
            workspace,
            run_id=run_id,
            policy_version=str(policy["policy_id"]),
            reason_code=type(error).__name__.upper(),
            detail="Локальный этап завершился с безопасной ошибкой.",
        )
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mox-adv-readonly-e2e")
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument("--run-id", required=True)
    arguments = parser.parse_args(argv)
    path = run_readonly_e2e(arguments.runs_dir, arguments.run_id)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
