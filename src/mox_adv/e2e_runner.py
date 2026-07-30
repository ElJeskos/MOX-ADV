"""Executable local E2E workflow with all write-class paths sealed locally."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from mox_adv.autonomy import (
    DurableMandateAuthority,
    HMACMandateSigner,
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
    write_final_e2e_artifacts,
)
from mox_adv.environment import ExecutionEnvironment
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
from mox_adv.impact import load_impact_fixture
from mox_adv.model_provider import DeterministicFakeModelProvider
from mox_adv.monitoring import MonitoringRead, MonitoringScheduler, MonitoringStore
from mox_adv.normalization import IntegratedSnapshotNormalizerV1
from mox_adv.observe import (
    load_linked_fixture,
    load_observe_policy,
    read_observe_snapshot,
    run_observe_fixture,
    trusted_fixture_scope,
)
from mox_adv.paired_cycle import (
    evaluate_paired_direct_impact,
    execute_paired_direct_test_action,
)
from mox_adv.proposal_store import ImmutableProposalStore
from mox_adv.recommend_contracts import CampaignDraftV1
from mox_adv.recommend_projection import build_sanitized_projection
from mox_adv.recommend_service import RecommendationService
from mox_adv.ui_service import _projection_source

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "gate0-policy.json"
OBSERVE_FIXTURE = ROOT / "fixtures" / "linked-observe.json"
IMPACT_FIXTURE = ROOT / "fixtures" / "impact" / "IMPACT_CPA_IMPROVED_KEEP.json"
NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
CAMPAIGN_NOW = datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc)
GOAL_NOW = CAMPAIGN_NOW


def load_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _scope(campaign: str = "sim-campaign") -> TrustedScope:
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


def _paired_module_snapshot(
    observe_result: Mapping[str, Any],
    *,
    current_weekly_budget_micros: int,
    current_search_bid_micros: int,
    impressions: int,
    clicks: int,
    cost_micros: int,
    visits: int,
    goal_visits: int,
) -> Mapping[str, Any]:
    """Build one self-consistent fingerprinted paired TEST snapshot."""

    observed = observe_result["snapshot"]
    records = observed["records"]

    def split(total: int) -> list[int]:
        quotient, remainder = divmod(total, len(records))
        return [
            quotient + (1 if index < remainder else 0) for index in range(len(records))
        ]

    impression_rows = split(impressions)
    click_rows = split(clicks)
    cost_rows = split(cost_micros)
    visit_rows = split(visits)
    goal_rows = split(goal_visits)
    paired_records = [
        {
            **dict(record),
            "impressions": impression_rows[index],
            "clicks": click_rows[index],
            "cost_micros": cost_rows[index],
            "visits": visit_rows[index],
            "goal_visits": goal_rows[index],
        }
        for index, record in enumerate(records)
    ]
    campaign = {
        **dict(observed["campaign"]),
        "current_weekly_budget_micros": current_weekly_budget_micros,
        "current_search_bid_micros": current_search_bid_micros,
    }
    metrics = {
        **dict(observed["metrics"]),
        "impressions": impressions,
        "clicks": clicks,
        "cost_micros": cost_micros,
        "visits": visits,
        "goal_visits": goal_visits,
        "ctr_percent": _ratio_text(clicks * 100, impressions),
        "cpc_rub": _ratio_text(cost_micros, clicks * 1_000_000),
        "conversion_rate_percent": _ratio_text(goal_visits * 100, visits),
        "cpa_rub": _ratio_text(cost_micros, goal_visits * 1_000_000),
        "budget_utilization_percent": _ratio_text(
            cost_micros * 100,
            current_weekly_budget_micros,
        ),
        "pacing_percent": _ratio_text(
            cost_micros * 100,
            current_weekly_budget_micros,
        ),
    }
    direct_retrieved = NOW - timedelta(minutes=5)
    metrika_retrieved = NOW - timedelta(minutes=5)
    metrika_watermark = metrika_retrieved - timedelta(minutes=1)
    direct_watermark = metrika_watermark + timedelta(minutes=1)
    provenance = {
        "direct_report": {
            **dict(observed["provenance"]["direct_report"]),
            "retrieved_at": direct_retrieved.isoformat(),
            "watermark": direct_watermark.isoformat(),
        },
        "direct_state": {
            **dict(observed["provenance"]["direct_state"]),
            "retrieved_at": direct_retrieved.isoformat(),
            "watermark": direct_watermark.isoformat(),
        },
        "metrika_report": {
            **dict(observed["provenance"]["metrika_report"]),
            "retrieved_at": metrika_retrieved.isoformat(),
            "watermark": metrika_watermark.isoformat(),
        },
    }
    snapshot = {
        **dict(observed),
        "generated_at": NOW.isoformat(),
        "campaign": campaign,
        "metrics": metrics,
        "records": paired_records,
        "provenance": provenance,
        "comparability_status": "COMPARABLE",
        "confidence_status": "READY",
        "financial_recommendations_allowed": True,
    }
    snapshot["snapshot_id"] = IntegratedSnapshotNormalizerV1.fingerprint(snapshot)
    return snapshot


def _ratio_text(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "NOT_APPLICABLE"
    return format((Decimal(numerator) / Decimal(denominator)).normalize(), "f")


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


def _mandate_payload(policy: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "organization": "sim-organization",
        "connection": "sim-connection",
        "account": "sim-direct-account",
        "environment": "SIMULATION",
        "credential_profile": "DIRECT_PILOT_WRITE",
        "targets": ["sim-campaign"],
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
        "issued_at": NOW.isoformat(),
        "expiry": (NOW + timedelta(hours=24)).isoformat(),
    }


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
        )
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


def _build_snapshot():
    observe_policy = load_observe_policy(POLICY_PATH)
    fixture = load_linked_fixture(OBSERVE_FIXTURE)
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
    components = working / "components"
    outcome = run_observe_fixture(
        run_id="observe",
        runs_root=components,
        fixture_path=OBSERVE_FIXTURE,
        policy_path=POLICY_PATH,
    )
    if outcome.status != "SUCCEEDED":
        raise AssertionError("OBSERVE did not complete.")
    observe_result = json.loads(
        (components / "observe" / "result.json").read_text(encoding="utf-8")
    )
    if observe_result["external_write_sent"] is not False:
        raise AssertionError("OBSERVE reported external write egress.")

    paired_snapshot = _paired_module_snapshot(
        observe_result,
        current_weekly_budget_micros=2_000_000_000,
        current_search_bid_micros=100_000_000,
        impressions=10_000,
        clicks=100,
        cost_micros=1_900_000_000,
        visits=100,
        goal_visits=12,
    )
    projection = build_sanitized_projection(
        _projection_source(paired_snapshot),
        policy,
    )
    provider = DeterministicFakeModelProvider()
    proposal_store = ImmutableProposalStore(working / "proposals")
    recommendation = RecommendationService(
        provider,
        proposal_store,
    ).recommend(
        projection=projection,
        run_id="recommend",
        snapshot_id=str(paired_snapshot["snapshot_id"]),
        expected_fingerprint="sha256:" + "2" * 64,
        created_at="2026-07-30T12:00:00+00:00",
        expires_at="2026-07-30T12:30:00+00:00",
    )
    if recommendation.status != "READY" or recommendation.proposal is None:
        raise AssertionError("RECOMMEND did not produce a valid proposal.")

    principal = _FixedAuthenticator().authenticate()
    approval_state = DurableControlState(working / "approval.sqlite3")
    prepared = replace(
        _approval_prepared(recommendation.proposal.proposal_id),
        proposal_hash=recommendation.canonical_hash,
        expected_diff=dict(recommendation.proposal.expected_diff),
        snapshot_id=recommendation.proposal.snapshot_id,
        snapshot_generated_at=str(paired_snapshot["generated_at"]),
        direct_watermark=str(
            paired_snapshot["provenance"]["direct_report"]["watermark"]
        ),
        metrika_watermark=str(
            paired_snapshot["provenance"]["metrika_report"]["watermark"]
        ),
        expected_fingerprint=recommendation.proposal.expected_fingerprint,
    )
    approval_state.register_prepared_change(prepared)
    approval = approval_state.grant_approval(
        prepared.proposal_id,
        tests_now() + timedelta(minutes=15),
        "Approve the exact simulated E2E change.",
        principal,
        tests_now(),
    )
    approval_adapter = FakeWriteAdapter(
        initial_state={prepared.target_key(): prepared.current_value}
    )
    direct_run_directory = working / "paired-direct"
    direct_run_directory.mkdir(parents=True, exist_ok=True)
    first_module = execute_paired_direct_test_action(
        run_directory=direct_run_directory,
        policy=policy,
        snapshot=paired_snapshot,
        projection=projection,
        prepared=prepared,
        state=approval_state,
        proposal_store=proposal_store,
        now=tests_now(),
        test_adapter=approval_adapter,
    )
    repeated_module = execute_paired_direct_test_action(
        run_directory=direct_run_directory,
        policy=policy,
        snapshot=paired_snapshot,
        projection=projection,
        prepared=prepared,
        state=approval_state,
        proposal_store=proposal_store,
        now=tests_now(),
        test_adapter=approval_adapter,
        persist_artifacts=False,
    )
    first_execution = first_module.result.execution_result
    repeated_execution = repeated_module.result.execution_result
    if (
        first_execution is None
        or repeated_execution is None
        or first_execution.status != "APPLIED"
        or repeated_execution.status != "ALREADY_PROCESSED"
    ):
        raise AssertionError("Approval fake execution was not idempotent.")
    if approval_adapter.write_calls != 1:
        raise AssertionError("Approval fake execution wrote more than once.")
    used_approval = approval_state.load_approval(approval.approval_id)
    if used_approval.used_at is None:
        raise AssertionError("The exact approval was not consumed.")

    blocked_recommendation = RecommendationService(
        provider,
        proposal_store,
    ).recommend(
        projection=projection,
        run_id="recommend-kill-switch",
        snapshot_id=str(paired_snapshot["snapshot_id"]),
        expected_fingerprint="sha256:" + "5" * 64,
        created_at="2026-07-30T12:00:00+00:00",
        expires_at="2026-07-30T12:30:00+00:00",
    )
    if (
        blocked_recommendation.status != "READY"
        or blocked_recommendation.proposal is None
    ):
        raise AssertionError("Kill-switch RECOMMEND did not produce a proposal.")
    blocked_prepared = replace(
        _approval_prepared(blocked_recommendation.proposal.proposal_id),
        proposal_hash=blocked_recommendation.canonical_hash,
        expected_diff=dict(blocked_recommendation.proposal.expected_diff),
        snapshot_id=blocked_recommendation.proposal.snapshot_id,
        snapshot_generated_at=str(paired_snapshot["generated_at"]),
        direct_watermark=str(
            paired_snapshot["provenance"]["direct_report"]["watermark"]
        ),
        metrika_watermark=str(
            paired_snapshot["provenance"]["metrika_report"]["watermark"]
        ),
        expected_fingerprint=(blocked_recommendation.proposal.expected_fingerprint),
    )
    kill_switch_state = DurableControlState(working / "kill-switch.sqlite3")
    kill_switch_state.register_prepared_change(blocked_prepared)
    kill_switch_state.grant_approval(
        blocked_prepared.proposal_id,
        tests_now() + timedelta(minutes=15),
        "Approve only if the kill switch remains inactive.",
        principal,
        tests_now(),
    )
    kill_switch_state.engage_kill_switch(
        "global",
        "E2E verifies the next unsent command is blocked.",
        principal,
        tests_now(),
    )
    blocked_adapter = FakeWriteAdapter(
        initial_state={
            blocked_prepared.target_key(): blocked_prepared.current_value,
        }
    )
    blocked_module = execute_paired_direct_test_action(
        run_directory=working / "paired-kill-switch",
        policy=policy,
        snapshot=paired_snapshot,
        projection=projection,
        prepared=blocked_prepared,
        state=kill_switch_state,
        proposal_store=proposal_store,
        now=tests_now(),
        test_adapter=blocked_adapter,
    )
    blocked_execution = blocked_module.result.execution_result
    if (
        blocked_module.result.status != "BLOCKED"
        or blocked_execution is None
        or blocked_execution.status != "BLOCKED"
        or blocked_module.result.errors[0].code != "KILL_SWITCH_ACTIVE"
        or blocked_adapter.write_calls != 0
    ):
        raise AssertionError("Kill switch did not block before fake dispatch.")

    autonomy_state = DurableControlState(working / "autonomy.sqlite3")
    signer = HMACMandateSigner(b"issue-33-local-e2e-mandate-key")
    authority = DurableMandateAuthority(
        autonomy_state.path,
        policy,
        signer,
    )
    issued = authority.issue(_mandate_payload(policy), principal, tests_now())
    mandate = authority.activate(issued.mandate_id, principal, tests_now())
    autonomy_snapshot = _paired_module_snapshot(
        observe_result,
        current_weekly_budget_micros=10_000_000_000,
        current_search_bid_micros=100_000_000,
        impressions=5_000,
        clicks=50,
        cost_micros=3_600_000_000,
        visits=100,
        goal_visits=3,
    )
    autonomy_projection = build_sanitized_projection(
        _projection_source(autonomy_snapshot),
        policy,
    )
    autonomy_recommendation = RecommendationService(
        provider,
        proposal_store,
    ).recommend(
        projection=autonomy_projection,
        run_id="recommend-autonomy",
        snapshot_id=str(autonomy_snapshot["snapshot_id"]),
        expected_fingerprint="sha256:" + "4" * 64,
        created_at="2026-07-30T12:00:00+00:00",
        expires_at="2026-07-30T12:30:00+00:00",
    )
    if (
        autonomy_recommendation.status != "READY"
        or autonomy_recommendation.proposal is None
        or autonomy_recommendation.proposal.expected_diff["operation"]
        != "DECREASE_SEARCH_BID"
    ):
        raise AssertionError("Mandate RECOMMEND did not produce the expected proposal.")
    autonomy_prepared = replace(
        _autonomy_prepared(autonomy_recommendation.proposal.proposal_id),
        proposal_hash=autonomy_recommendation.canonical_hash,
        expected_diff=dict(autonomy_recommendation.proposal.expected_diff),
        snapshot_id=autonomy_recommendation.proposal.snapshot_id,
        snapshot_generated_at=str(autonomy_snapshot["generated_at"]),
        direct_watermark=str(
            autonomy_snapshot["provenance"]["direct_report"]["watermark"]
        ),
        metrika_watermark=str(
            autonomy_snapshot["provenance"]["metrika_report"]["watermark"]
        ),
        expected_fingerprint=(autonomy_recommendation.proposal.expected_fingerprint),
    )
    autonomy_state.register_prepared_change(autonomy_prepared)
    autonomy_adapter = FakeWriteAdapter(
        initial_state={
            autonomy_prepared.target_key(): autonomy_prepared.current_value,
        }
    )
    autonomy_module = execute_paired_direct_test_action(
        run_directory=working / "paired-autonomy",
        policy=policy,
        snapshot=autonomy_snapshot,
        projection=autonomy_projection,
        prepared=autonomy_prepared,
        state=autonomy_state,
        proposal_store=proposal_store,
        now=tests_now(),
        test_adapter=autonomy_adapter,
        mandate_authority=authority,
        mandate_id=mandate.mandate_id,
    )
    autonomy_execution = autonomy_module.result.execution_result
    if (
        autonomy_module.result.status != "SUCCEEDED"
        or autonomy_execution is None
        or autonomy_execution.status != "APPLIED"
        or autonomy_adapter.write_calls != 1
    ):
        raise AssertionError("Bounded autonomy fake readback failed.")

    snapshot = _build_snapshot()
    scheduler = MonitoringScheduler(
        policy=policy,
        source=_FixtureReadSource(MonitoringRead(snapshot=snapshot)),
        store=MonitoringStore(working / "monitoring.sqlite3"),
        clock=_FixedClock(),
    )
    monitoring = scheduler.poll()
    if monitoring.status != "POLLED":
        raise AssertionError("Monitoring did not produce a new snapshot.")

    impact_module = evaluate_paired_direct_impact(
        run_directory=working / "paired-impact",
        policy=policy,
        request=load_impact_fixture(IMPACT_FIXTURE, policy),
    )
    impact = impact_module.report
    if impact.status != "OBSERVED_POST_CHANGE":
        raise AssertionError("Impact evaluation did not complete.")

    change_diff = {
        "approval_required": {
            "proposal_id": prepared.proposal_id,
            "execution_key": prepared.execution_key(),
            "operation": dict(prepared.expected_diff),
            "before": prepared.current_value,
            "after": prepared.target_value,
            "readback": first_module.observed_value,
            "status": first_execution.status,
        },
        "bounded_autonomy": {
            "proposal_id": autonomy_prepared.proposal_id,
            "execution_key": autonomy_prepared.execution_key(),
            "operation": dict(autonomy_prepared.expected_diff),
            "before": autonomy_prepared.current_value,
            "after": autonomy_prepared.target_value,
            "readback": autonomy_module.observed_value,
            "status": autonomy_execution.status,
        },
    }
    observe_evidence = {
        "source": observe_result["source"],
        "snapshot_id": observe_result["snapshot_id"],
        "period_start": observe_result["snapshot"]["period_start"],
        "period_end": observe_result["snapshot"]["period_end"],
        "provenance": observe_result["snapshot"]["provenance"],
        "metrics": observe_result["snapshot"]["metrics"],
        "comparability_status": observe_result["snapshot"]["comparability_status"],
        "confidence_status": observe_result["snapshot"]["confidence_status"],
        "external_write_sent": observe_result["external_write_sent"],
    }
    monitoring_evidence = asdict(monitoring)
    supplemental = {
        "proposal.json": recommendation.proposal.as_dict(),
        "approval.json": asdict(used_approval),
        "change_diff.json": change_diff,
        "impact_report.json": impact.as_dict(),
        "observe-evidence.json": observe_evidence,
        "monitoring-evidence.json": monitoring_evidence,
        "direct-module-result.json": first_module.result.as_dict(),
        "direct-decision-record.json": dict(first_module.decision_record),
        "mandate-direct-module-result.json": autonomy_module.result.as_dict(),
        "mandate-direct-decision-record.json": dict(autonomy_module.decision_record),
        "kill-switch-direct-module-result.json": (blocked_module.result.as_dict()),
        "kill-switch-direct-decision-record.json": dict(blocked_module.decision_record),
        "impact-module-result.json": impact_module.result.as_dict(),
        "impact-decision-record.json": dict(impact_module.decision_record),
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
        "duration_ms": (
            int(observe_result["duration_ms"]) + recommendation.provider.duration_ms
        ),
        "stage_durations_ms": {
            "observe": int(observe_result["duration_ms"]),
            "recommend": recommendation.provider.duration_ms,
        },
        "proposal_id": recommendation.proposal.proposal_id,
        "policy_decision": {
            "approval_required": first_execution.status,
            "bounded_autonomy": autonomy_execution.status,
            "kill_switch": blocked_execution.status,
            "kill_switch_reason": blocked_module.result.errors[0].code,
        },
        "execution": {
            "technical_command": "DIRECT_TEST_MODULE_AND_SEALED_FAKE_ADAPTERS_ONLY",
            "before": {
                "approval_required": prepared.current_value,
                "bounded_autonomy": autonomy_prepared.current_value,
            },
            "after": {
                "approval_required": prepared.target_value,
                "bounded_autonomy": autonomy_prepared.target_value,
            },
            "readback": {
                "approval_required": first_module.observed_value,
                "bounded_autonomy": autonomy_module.observed_value,
            },
            "final_object_state": {
                "approval_required": first_execution.status,
                "bounded_autonomy": autonomy_execution.status,
                "kill_switch": blocked_execution.status,
            },
        },
    }
    return supplemental, run_summary


def _campaign_goal_workflow(
    working: Path,
    policy: Mapping[str, Any],
    egress: ReadOnlyEgressRecorder,
) -> Mapping[str, Any]:
    draft = validate_campaign_draft(
        _campaign_payload(),
        policy,
        _campaign_safety(),
    )
    request = _campaign_request(draft)
    campaign_store = CampaignSagaStore(working / "campaign.sqlite3")
    _register_campaign_authority(campaign_store, request, policy)
    campaign_adapter = FakeDirectManagementAdapter()
    campaign_service = CampaignLifecycleService(
        policy,
        campaign_store,
        DirectManagementConnectorV1(
            policy,
            campaign_adapter,
            campaign_store,
            environment=ExecutionEnvironment.TEST,
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

    rollback_store = CampaignSagaStore(working / "campaign-rollback.sqlite3")
    _register_campaign_authority(rollback_store, request, policy)
    rollback_adapter = FakeDirectManagementAdapter(fail_on=("Ads", "moderate"))
    rollback = CampaignLifecycleService(
        policy,
        rollback_store,
        DirectManagementConnectorV1(
            policy,
            rollback_adapter,
            rollback_store,
            environment=ExecutionEnvironment.TEST,
        ),
        _campaign_safety(),
    ).execute(request, CAMPAIGN_NOW)
    if rollback.status != "PARTIALLY_APPLIED":
        raise AssertionError("Campaign compensation path did not run.")
    if rollback_adapter.object_ids():
        raise AssertionError("Campaign fake rollback left created objects.")

    simulation = policy["bindings"]["simulation"]
    goal_store = GoalLifecycleStore(working / "goals.sqlite3")
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
        environment=ExecutionEnvironment.TEST,
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
    goal_store.register_authority(creation_authority)
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
    goal_store.register_authority(publish_authority)
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
        "campaign_status": _status_value(campaign_result.status),
        "campaign_completed_steps": [
            str(item) for item in campaign_result.completed_steps
        ],
        "campaign_fake_call_count": len(calls_after_repeat),
        "campaign_rollback_status": _status_value(rollback.status),
        "goal_technical_status": _status_value(technical.status),
        "goal_semantic_status": _status_value(rejected.status),
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


def _status_value(value: object) -> str:
    return str(getattr(value, "value", value))


def run_readonly_e2e(
    runs_root: Path,
    run_id: str,
    *,
    additional_text_artifacts: Callable[[Path], Mapping[str, str]] | None = None,
) -> Path:
    policy = load_policy()
    runs_root.mkdir(parents=True, exist_ok=True)
    egress = ReadOnlyEgressRecorder(policy)
    with TemporaryDirectory(
        prefix="." + run_id + "-work-",
        dir=runs_root,
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
        additional_text_artifacts=additional_text_artifacts,
    )


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
