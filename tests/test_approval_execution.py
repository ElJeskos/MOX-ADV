from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional
from unittest import mock

from mox_adv.approval_execution import (
    ApprovalExecutionService,
    ExecutionFacts,
    ExecutionRequest,
    PreparedChange,
    TrustedScope,
)
from mox_adv.cli import build_parser, main
from mox_adv.commands import (
    CommandRejected,
    OptimizationAction,
    build_high_level_command,
    calculate_relative_target,
)
from mox_adv.control_state import (
    AuthenticatedPrincipal,
    ControlRejected,
    DurableControlState,
    ExecutionStatus,
    MacOSLocalPrincipalAuthenticator,
)
from mox_adv.egress import EgressDenied, HttpEgressGuard
from mox_adv.fake_write_adapter import FakeWriteAdapter
from mox_adv.monitoring import DurableWriteWindowGate

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "gate0-policy.json"
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


class FixedAuthenticator:
    def authenticate(self) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            identity="sviridov",
            authentication="authenticated_macos_user",
        )

    def elevated_reauthenticate(self) -> AuthenticatedPrincipal:
        return self.authenticate()


class RecordingElevatedVerifier:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.calls = 0

    def verify(self, principal: AuthenticatedPrincipal) -> bool:
        self.calls += 1
        return self.allowed and principal.identity == "sviridov"


def load_policy() -> dict[str, object]:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def make_scope() -> TrustedScope:
    return TrustedScope(
        organization="sim-organization",
        connection="sim-connection",
        account="sim-direct-account",
        campaign="campaign-1",
        writer="sim-executor",
    )


def make_prepared(
    *,
    proposal_id: str = "proposal-approval-test",
    action: str = "INCREASE_WEEKLY_BUDGET",
    current_value: int = 2_000_000_000,
    expected_diff: Optional[Mapping[str, Any]] = None,
) -> PreparedChange:
    target_value = calculate_relative_target(current_value, 10)
    return PreparedChange(
        proposal_id=proposal_id,
        proposal_hash="sha256:" + "1" * 64,
        scope=make_scope(),
        action=OptimizationAction(action),
        current_value=current_value,
        target_value=target_value,
        expected_diff=(
            {
                "operation": action,
                "relative_step_percent": 10,
            }
            if expected_diff is None
            else expected_diff
        ),
        snapshot_id="snapshot-1",
        snapshot_generated_at="2026-07-29T11:55:00+00:00",
        direct_watermark="2026-07-29T11:55:00+00:00",
        metrika_watermark="2026-07-29T11:55:00+00:00",
        policy_version="mox-adv-gate0-2026-07-29",
        expected_fingerprint="sha256:" + "2" * 64,
        risk="WEEKLY_BUDGET_INCREASE",
    )


def make_facts() -> ExecutionFacts:
    return ExecutionFacts(
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
        current_fingerprint="sha256:" + "2" * 64,
        cooldown_active=False,
        actions_in_last_24h=0,
        cumulative_daily_change_percent=0,
        monetary_exposure_rub=200,
        kill_switch_available=True,
    )


def make_request(prepared: PreparedChange) -> ExecutionRequest:
    return ExecutionRequest(
        proposal_id=prepared.proposal_id,
        execution_key=prepared.execution_key(),
        scope=prepared.scope,
        facts=make_facts(),
    )


class CommandContractTests(unittest.TestCase):
    def test_relative_values_use_round_half_up_and_never_clamp(self) -> None:
        self.assertEqual(11_006, calculate_relative_target(10_005, 10))
        self.assertEqual(9_005, calculate_relative_target(10_005, -10))
        with self.assertRaisesRegex(CommandRejected, "OUT_OF_BOUNDS"):
            build_high_level_command(
                prepared=make_prepared(current_value=2_900_000_000),
                minimum_value=1,
                maximum_value=3_000_000_000,
            )

    def test_all_required_high_level_actions_have_typed_commands(self) -> None:
        cases = {
            "INCREASE_WEEKLY_BUDGET": (2_000_000_000, 2_200_000_000),
            "DECREASE_WEEKLY_BUDGET": (2_000_000_000, 1_800_000_000),
            "INCREASE_SEARCH_BID": (100_000_000, 110_000_000),
            "DECREASE_SEARCH_BID": (100_000_000, 90_000_000),
            "SET_AD_VARIANT": ("A", "B"),
            "SUSPEND_CAMPAIGN": ("ON", "SUSPENDED"),
            "RESUME_CAMPAIGN": ("SUSPENDED", "ON"),
        }
        for action, (current, target) in cases.items():
            with self.subTest(action=action):
                diff: dict[str, object] = {"operation": action}
                if "BUDGET" in action or "BID" in action:
                    diff["relative_step_percent"] = 10
                elif action == "SET_AD_VARIANT":
                    diff["variant_id"] = target
                else:
                    diff["target_state"] = target
                prepared = replace(
                    make_prepared(action=action),
                    current_value=current,
                    target_value=target,
                    expected_diff=diff,
                )
                command = build_high_level_command(
                    prepared=prepared,
                    minimum_value=1,
                    maximum_value=3_000_000_000,
                )
                self.assertEqual(action, command.action)
                self.assertEqual(target, command.target_value)
                self.assertTrue(command.dry_run)
                self.assertIsNotNone(command.rollback)
                self.assertEqual("sim-organization", command.organization)
                self.assertEqual(prepared.proposal_id, command.proposal_id)
                self.assertEqual(prepared.execution_key(), command.execution_key)
                self.assertTrue(command.readback_required)
                self.assertEqual(
                    "sha256:" + "2" * 64,
                    command.expected_fingerprint,
                )


class ApprovalExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = Path(self.temporary_directory.name) / "control.sqlite3"
        self.state = DurableControlState(self.database)
        self.prepared = make_prepared()
        self.state.register_prepared_change(self.prepared)
        self.principal = FixedAuthenticator().authenticate()
        self.approval = self.state.grant_approval(
            proposal_id=self.prepared.proposal_id,
            expires_at=NOW + timedelta(minutes=15),
            reason="Approve the exact simulated budget change.",
            principal=self.principal,
            now=NOW,
        )

    def service(
        self,
        adapter: FakeWriteAdapter,
        now: datetime = NOW,
    ) -> ApprovalExecutionService:
        return ApprovalExecutionService(
            policy=load_policy(),
            state=self.state,
            adapter=adapter,
            clock=lambda: now,
        )

    def test_happy_path_is_applied_only_after_exact_fake_readback(self) -> None:
        adapter = FakeWriteAdapter(
            initial_state={self.prepared.target_key(): self.prepared.current_value}
        )
        result = self.service(adapter).execute(make_request(self.prepared))

        self.assertEqual("APPLIED", result.status)
        self.assertEqual(1, adapter.write_calls)
        self.assertEqual(self.prepared.target_value, result.observed_value)
        self.assertTrue(self.state.load_approval(self.approval.approval_id).used)
        self.assertEqual(
            "APPLIED",
            DurableControlState(self.database)
            .load_execution(self.prepared.execution_key())
            .status,
        )

    def test_durable_write_window_blocks_until_exact_72_hour_boundary(
        self,
    ) -> None:
        for label, elapsed, expected_status, expected_writes in (
            (
                "before",
                timedelta(hours=71, minutes=59, seconds=59),
                "BLOCKED",
                0,
            ),
            ("boundary", timedelta(hours=72), "APPLIED", 1),
        ):
            with self.subTest(label=label):
                database = Path(self.temporary_directory.name) / (
                    "approval-window-" + label + ".sqlite3"
                )
                state = DurableControlState(database)
                prepared = make_prepared(proposal_id="proposal-window-" + label)
                state.register_prepared_change(prepared)
                state.grant_approval(
                    prepared.proposal_id,
                    NOW + timedelta(minutes=15),
                    "Approve exact window test.",
                    self.principal,
                    NOW,
                )
                gate = DurableWriteWindowGate(database, load_policy())
                applied_at = NOW - elapsed
                self.assertTrue(gate.reserve("prior-execution", applied_at).allowed)
                gate.activate("prior-execution", applied_at)
                adapter = FakeWriteAdapter(
                    initial_state={
                        prepared.target_key(): prepared.current_value,
                    }
                )
                result = ApprovalExecutionService(
                    load_policy(),
                    state,
                    adapter,
                    clock=lambda: NOW,
                ).execute(make_request(prepared))

                self.assertEqual(expected_status, result.status)
                self.assertEqual(expected_writes, adapter.write_calls)
                if label == "before":
                    self.assertEqual(
                        "COOLDOWN_AND_OBSERVATION_ACTIVE",
                        result.reason_code,
                    )

    def test_approval_is_immutable_exact_and_single_use(self) -> None:
        with self.assertRaises(ControlRejected):
            self.state.register_prepared_change(
                replace(
                    self.prepared,
                    scope=replace(self.prepared.scope, campaign="campaign-widened"),
                )
            )

        adapter = FakeWriteAdapter(
            initial_state={self.prepared.target_key(): self.prepared.current_value}
        )
        first = self.service(adapter).execute(make_request(self.prepared))
        second = self.service(adapter).execute(make_request(self.prepared))

        self.assertEqual("APPLIED", first.status)
        self.assertEqual("ALREADY_PROCESSED", second.status)
        self.assertEqual(1, adapter.write_calls)

    def test_approval_authority_rejects_core_field_mutation(self) -> None:
        connection = sqlite3.connect(str(self.database))
        with connection, self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE approvals SET reason = ? WHERE approval_id = ?",
                ("Widened after approval.", self.approval.approval_id),
            )

    def test_each_policy_boundary_fails_closed_before_adapter_call(self) -> None:
        mutations: dict[str, dict[str, Any]] = {
            "mode": {"mode": "RECOMMEND"},
            "automation": {"automation_enabled": False},
            "comparability": {"comparability_status": "INCOMPATIBLE"},
            "confidence": {"confidence_status": "INSUFFICIENT_DATA"},
            "freshness": {"direct_age_minutes": 31},
            "watermark": {"watermark_skew_minutes": 361},
            "sample": {"clicks": 49},
            "fingerprint": {"current_fingerprint": "sha256:" + "9" * 64},
            "cooldown": {"cooldown_active": True},
            "quota": {"actions_in_last_24h": 1},
            "daily_limit": {"cumulative_daily_change_percent": 1},
            "monetary_limit": {"monetary_exposure_rub": 501},
            "kill_switch_unavailable": {"kill_switch_available": False},
        }
        for name, changes in mutations.items():
            with self.subTest(boundary=name):
                state = DurableControlState(
                    Path(self.temporary_directory.name) / f"{name}.sqlite3"
                )
                state.register_prepared_change(self.prepared)
                state.grant_approval(
                    proposal_id=self.prepared.proposal_id,
                    expires_at=NOW + timedelta(minutes=15),
                    reason="Approve exact change.",
                    principal=self.principal,
                    now=NOW,
                )
                adapter = FakeWriteAdapter(
                    initial_state={
                        self.prepared.target_key(): self.prepared.current_value
                    }
                )
                facts = replace(make_facts(), **changes)
                request = replace(make_request(self.prepared), facts=facts)
                result = ApprovalExecutionService(
                    load_policy(),
                    state,
                    adapter,
                    clock=lambda: NOW,
                ).execute(request)
                self.assertEqual("BLOCKED", result.status)
                self.assertEqual(0, adapter.write_calls)

    def test_search_bid_requires_the_supported_manual_strategy(self) -> None:
        prepared = replace(
            make_prepared(
                proposal_id="proposal-search-bid",
                action="INCREASE_SEARCH_BID",
                current_value=100_000_000,
            ),
            target_value=110_000_000,
        )
        state = DurableControlState(
            Path(self.temporary_directory.name) / "strategy.sqlite3"
        )
        state.register_prepared_change(prepared)
        state.grant_approval(
            prepared.proposal_id,
            NOW + timedelta(minutes=15),
            "Exact approval.",
            self.principal,
            NOW,
        )
        adapter = FakeWriteAdapter(
            initial_state={prepared.target_key(): prepared.current_value}
        )
        request = replace(
            make_request(prepared),
            facts=replace(
                make_facts(),
                campaign_strategy="AUTOMATIC",
                clicks=75,
                budget_utilization_percent="80",
            ),
        )
        result = ApprovalExecutionService(
            load_policy(),
            state,
            adapter,
            clock=lambda: NOW,
        ).execute(request)
        self.assertEqual("BLOCKED", result.status)
        self.assertEqual(0, adapter.write_calls)

    def test_scope_diff_snapshot_fingerprint_and_execution_key_cannot_change(
        self,
    ) -> None:
        mutations = (
            replace(
                make_request(self.prepared),
                scope=replace(make_scope(), campaign="campaign-other"),
            ),
            replace(
                make_request(self.prepared),
                execution_key="sha256:" + "8" * 64,
            ),
        )
        for request in mutations:
            with self.subTest(request=request):
                state = DurableControlState(
                    Path(self.temporary_directory.name)
                    / (request.execution_key[-8:] + ".sqlite3")
                )
                state.register_prepared_change(self.prepared)
                state.grant_approval(
                    self.prepared.proposal_id,
                    NOW + timedelta(minutes=15),
                    "Exact approval.",
                    self.principal,
                    NOW,
                )
                adapter = FakeWriteAdapter()
                result = ApprovalExecutionService(
                    load_policy(),
                    state,
                    adapter,
                    clock=lambda: NOW,
                ).execute(request)
                self.assertEqual("BLOCKED", result.status)
                self.assertEqual(0, adapter.write_calls)

    def test_concurrent_duplicate_execution_has_one_fake_adapter_call(self) -> None:
        adapter = FakeWriteAdapter(
            initial_state={self.prepared.target_key(): self.prepared.current_value},
            write_delay_seconds=0.05,
        )
        service = self.service(adapter)
        barrier = threading.Barrier(2)
        results: list[str] = []

        def execute() -> None:
            barrier.wait()
            results.append(service.execute(make_request(self.prepared)).status)

        threads = [threading.Thread(target=execute) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(1, adapter.write_calls)
        self.assertIn("APPLIED", results)
        self.assertTrue(
            set(results).issubset({"APPLIED", "ALREADY_PROCESSED", "IN_FLIGHT"})
        )

    def test_post_send_state_failure_keeps_in_flight_for_reconciliation(self) -> None:
        adapter = FakeWriteAdapter(
            initial_state={self.prepared.target_key(): self.prepared.current_value}
        )
        service = self.service(adapter)
        with mock.patch.object(
            self.state,
            "finish_execution",
            side_effect=sqlite3.OperationalError("post-send state failure"),
        ):
            result = service.execute(make_request(self.prepared))

        self.assertEqual("UNKNOWN_RESULT", result.status)
        self.assertEqual(1, adapter.write_calls)
        self.assertEqual(
            "IN_FLIGHT",
            DurableControlState(self.database)
            .load_execution(self.prepared.execution_key())
            .status,
        )

        reconciled = ApprovalExecutionService(
            load_policy(),
            DurableControlState(self.database),
            adapter,
            clock=lambda: NOW,
        ).reconcile(self.prepared.execution_key())
        self.assertEqual("APPLIED", reconciled.status)
        self.assertEqual(1, adapter.write_calls)

    def test_timeout_reconciliation_distinguishes_failed_and_unknown(self) -> None:
        for readback, expected in (
            (self.prepared.current_value, "FAILED"),
            (None, "UNKNOWN_RESULT"),
        ):
            with self.subTest(expected=expected):
                state = DurableControlState(
                    Path(self.temporary_directory.name) / f"{expected}.sqlite3"
                )
                state.register_prepared_change(self.prepared)
                state.grant_approval(
                    self.prepared.proposal_id,
                    NOW + timedelta(minutes=15),
                    "Exact approval.",
                    self.principal,
                    NOW,
                )
                adapter = FakeWriteAdapter(
                    initial_state={
                        self.prepared.target_key(): self.prepared.current_value
                    },
                    timeout_after_write=True,
                    timeout_readback=readback,
                )
                result = ApprovalExecutionService(
                    load_policy(),
                    state,
                    adapter,
                    clock=lambda: NOW,
                ).execute(make_request(self.prepared))
                self.assertEqual(expected, result.status)
                reopened = DurableControlState(state.path)
                self.assertEqual(
                    expected,
                    reopened.load_execution(self.prepared.execution_key()).status,
                )
                if expected == "UNKNOWN_RESULT":
                    next_prepared = replace(
                        make_prepared(proposal_id="proposal-next"),
                        proposal_hash="sha256:" + "3" * 64,
                    )
                    reopened.register_prepared_change(next_prepared)
                    reopened.grant_approval(
                        next_prepared.proposal_id,
                        NOW + timedelta(minutes=15),
                        "Next exact approval.",
                        self.principal,
                        NOW,
                    )
                    blocked = ApprovalExecutionService(
                        load_policy(),
                        reopened,
                        FakeWriteAdapter(),
                        clock=lambda: NOW,
                    ).execute(make_request(next_prepared))
                    self.assertEqual("BLOCKED", blocked.status)

    def test_restart_reconciles_in_flight_without_a_second_write(self) -> None:
        adapter = FakeWriteAdapter(
            initial_state={self.prepared.target_key(): self.prepared.current_value}
        )
        status, _ = self.state.reserve_execution(self.prepared, NOW)
        self.assertEqual("RESERVED", status)
        self.state.begin_execution(self.prepared, self.approval, NOW)

        reopened = DurableControlState(self.database)
        service = ApprovalExecutionService(
            load_policy(),
            reopened,
            adapter,
            clock=lambda: NOW,
        )
        result = service.reconcile(self.prepared.execution_key())

        self.assertEqual("FAILED", result.status)
        self.assertEqual(0, adapter.write_calls)
        self.assertEqual(
            "FAILED",
            reopened.load_execution(self.prepared.execution_key()).status,
        )

    def test_terminal_execution_state_cannot_be_rewritten(self) -> None:
        adapter = FakeWriteAdapter(
            initial_state={self.prepared.target_key(): self.prepared.current_value}
        )
        result = self.service(adapter).execute(make_request(self.prepared))
        self.assertEqual("APPLIED", result.status)

        with self.assertRaisesRegex(ControlRejected, "ILLEGAL_EXECUTION_TRANSITION"):
            self.state.finish_execution(
                self.prepared.execution_key(),
                ExecutionStatus.FAILED,
                "Attempted rewrite.",
                NOW,
            )
        self.assertEqual(
            "APPLIED",
            self.state.load_execution(self.prepared.execution_key()).status,
        )

    def test_kill_switch_storage_failure_blocks_before_adapter_send(self) -> None:
        adapter = FakeWriteAdapter(
            initial_state={self.prepared.target_key(): self.prepared.current_value}
        )
        with mock.patch.object(
            self.state,
            "_kill_switch_active_in_connection",
            side_effect=sqlite3.OperationalError("unavailable"),
        ):
            result = self.service(adapter).execute(make_request(self.prepared))

        self.assertEqual("BLOCKED", result.status)
        self.assertEqual("CONTROL_STATE_UNAVAILABLE", result.reason_code)
        self.assertEqual(0, adapter.write_calls)

    def test_locked_control_state_fails_closed_within_kill_switch_sla(self) -> None:
        adapter = FakeWriteAdapter(
            initial_state={self.prepared.target_key(): self.prepared.current_value}
        )
        lock = sqlite3.connect(str(self.database))
        lock.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        try:
            result = self.service(adapter).execute(make_request(self.prepared))
        finally:
            lock.rollback()
            lock.close()
        elapsed = time.monotonic() - started

        self.assertEqual("BLOCKED", result.status)
        self.assertEqual("CONTROL_STATE_UNAVAILABLE", result.reason_code)
        self.assertEqual(0, adapter.write_calls)
        self.assertLess(elapsed, 1)


class KillSwitchAndCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.state = DurableControlState(
            Path(self.temporary_directory.name) / "control.sqlite3"
        )
        self.authenticator = FixedAuthenticator()

    def test_exact_gate0_cli_commands_are_supported(self) -> None:
        parser = build_parser()
        parsed = parser.parse_args(
            [
                "approval",
                "grant",
                "--proposal-id",
                "proposal-1",
                "--expires-in",
                "15m",
                "--reason",
                "Exact approval.",
            ]
        )
        self.assertEqual(("approval", "grant"), (parsed.command, parsed.operation))
        parsed = parser.parse_args(
            [
                "kill-switch",
                "engage",
                "--scope",
                "global",
                "--reason",
                "Incident.",
            ]
        )
        self.assertEqual(("kill-switch", "engage"), (parsed.command, parsed.operation))
        parsed = parser.parse_args(
            [
                "kill-switch",
                "release",
                "--scope",
                "global",
                "--reason",
                "Resolved.",
                "--reauth",
            ]
        )
        self.assertTrue(parsed.reauth)

    def test_cli_grants_approval_and_controls_durable_kill_switch(self) -> None:
        prepared = make_prepared()
        self.state.register_prepared_change(prepared)
        self.assertEqual(
            0,
            main(
                [
                    "approval",
                    "grant",
                    "--proposal-id",
                    prepared.proposal_id,
                    "--expires-in",
                    "15m",
                    "--reason",
                    "Exact simulated change.",
                ],
                control_state=self.state,
                authenticator=self.authenticator,
                clock=lambda: NOW,
            ),
        )
        self.assertEqual(
            0,
            main(
                [
                    "kill-switch",
                    "engage",
                    "--scope",
                    "global",
                    "--reason",
                    "Incident.",
                ],
                control_state=self.state,
                authenticator=self.authenticator,
                clock=lambda: NOW,
            ),
        )
        self.assertTrue(
            DurableControlState(self.state.path).kill_switch_active("global")
        )
        self.assertEqual(
            0,
            main(
                [
                    "kill-switch",
                    "release",
                    "--scope",
                    "global",
                    "--reason",
                    "Resolved.",
                    "--reauth",
                ],
                control_state=self.state,
                authenticator=self.authenticator,
                clock=lambda: NOW,
            ),
        )
        self.assertFalse(self.state.kill_switch_active("global"))

    def test_engaged_kill_switch_blocks_next_unsent_command_within_sla(self) -> None:
        prepared = make_prepared()
        self.state.register_prepared_change(prepared)
        self.state.grant_approval(
            prepared.proposal_id,
            NOW + timedelta(minutes=15),
            "Exact approval.",
            self.authenticator.authenticate(),
            NOW,
        )
        self.state.engage_kill_switch(
            "campaign:" + prepared.scope.campaign,
            "Incident.",
            self.authenticator.authenticate(),
            NOW,
        )
        adapter = FakeWriteAdapter()
        started = time.monotonic()
        result = ApprovalExecutionService(
            load_policy(),
            self.state,
            adapter,
            clock=lambda: NOW,
        ).execute(make_request(prepared))
        elapsed = time.monotonic() - started
        self.assertEqual("BLOCKED", result.status)
        self.assertEqual(0, adapter.write_calls)
        self.assertLess(elapsed, 1)

    def test_elevated_reauthentication_uses_a_separate_fail_closed_verifier(
        self,
    ) -> None:
        allowed = RecordingElevatedVerifier(True)
        with mock.patch(
            "mox_adv.control_state.getpass.getuser",
            return_value="sviridov",
        ):
            principal = MacOSLocalPrincipalAuthenticator(
                elevated_verifier=allowed
            ).elevated_reauthenticate()
        self.assertEqual("sviridov", principal.identity)
        self.assertEqual(1, allowed.calls)

        denied = RecordingElevatedVerifier(False)
        with (
            mock.patch(
                "mox_adv.control_state.getpass.getuser",
                return_value="sviridov",
            ),
            self.assertRaisesRegex(
                ControlRejected,
                "ELEVATED_REAUTHENTICATION_FAILED",
            ),
        ):
            MacOSLocalPrincipalAuthenticator(
                elevated_verifier=denied
            ).elevated_reauthenticate()
        self.assertEqual(1, denied.calls)


class EgressGuardTests(unittest.TestCase):
    def test_http_guard_allows_only_exact_matrix_reads(self) -> None:
        guard = HttpEgressGuard(load_policy())
        guard.authorize(
            "POST",
            "https://api.direct.yandex.com/json/v501/campaigns",
            version="v501",
            service="Campaigns",
            operation="get",
            credential_profile="DIRECT_PILOT_WRITE",
        )
        guard.authorize(
            "GET",
            "https://api-metrika.yandex.net/stat/v1/data?ids=1",
            version="v1",
            service="Statistics",
            operation="get",
            credential_profile="METRIKA_TEST_WRITE",
        )

    def test_http_guard_rejects_path_host_version_method_and_redirect_changes(
        self,
    ) -> None:
        policy = copy.deepcopy(load_policy())
        record = policy["record"]
        assert isinstance(record, dict)
        record["production_write_authorized"] = True
        guard = HttpEgressGuard(policy)
        guard.authorize(
            "POST",
            "https://api.direct.yandex.com/json/v501/campaigns",
            version="v501",
            service="Campaigns",
            operation="update",
            credential_profile="DIRECT_PILOT_WRITE",
            pilot_armed=True,
        )
        cases = (
            (
                "DELETE",
                "https://api.direct.yandex.com/json/v501/campaigns",
                "v501",
                "Campaigns",
                "update",
                False,
            ),
            (
                "POST",
                "https://api.direct.yandex.com/not-allowlisted",
                "v501",
                "Campaigns",
                "update",
                False,
            ),
            (
                "POST",
                "https://example.invalid/json/v501/campaigns",
                "v501",
                "Campaigns",
                "update",
                False,
            ),
            (
                "POST",
                "https://api.direct.yandex.com/json/v501/campaigns",
                "v5",
                "Campaigns",
                "update",
                False,
            ),
            (
                "POST",
                "https://api.direct.yandex.com/json/v501/campaigns",
                "v501",
                "Campaigns",
                "update",
                True,
            ),
        )
        for method, url, version, service, operation, redirected in cases:
            with self.subTest(url=url, method=method), self.assertRaises(EgressDenied):
                guard.authorize(
                    method,
                    url,
                    version=version,
                    service=service,
                    operation=operation,
                    credential_profile="DIRECT_PILOT_WRITE",
                    redirected=redirected,
                    pilot_armed=True,
                )

    def test_service_blocks_an_adapter_not_connected_to_the_guard(self) -> None:
        class DisconnectedAdapter:
            is_fake = False

            def __init__(self) -> None:
                self.calls = 0

            def readback(self, target_key: str) -> object:
                self.calls += 1
                return None

            def apply(self, target_key: str, command: object) -> None:
                self.calls += 1

        with tempfile.TemporaryDirectory() as temporary_directory:
            state = DurableControlState(Path(temporary_directory) / "control.sqlite3")
            prepared = make_prepared()
            state.register_prepared_change(prepared)
            state.grant_approval(
                prepared.proposal_id,
                NOW + timedelta(minutes=15),
                "Exact approval.",
                FixedAuthenticator().authenticate(),
                NOW,
            )
            adapter = DisconnectedAdapter()
            result = ApprovalExecutionService(
                load_policy(),
                state,
                adapter,
                clock=lambda: NOW,
            ).execute(make_request(prepared))
        self.assertEqual("BLOCKED", result.status)
        self.assertEqual("EXTERNAL_WRITE_EGRESS_DENIED", result.reason_code)
        self.assertEqual(0, adapter.calls)


if __name__ == "__main__":
    unittest.main()
