from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from unittest import mock

from mox_adv.audit import AuditWriteBlocked
from mox_adv.autonomy import (
    BoundedAutonomyRequest,
    BoundedAutonomyService,
    DurableMandateAuthority,
    HMACMandateSigner,
    MandateRecord,
)
from mox_adv.cli import build_parser, main
from mox_adv.commands import OptimizationAction, calculate_relative_target
from mox_adv.control_state import (
    AuthenticatedPrincipal,
    ControlRejected,
    DurableControlState,
    PreparedChange,
    TrustedScope,
)
from mox_adv.fake_write_adapter import FakeWriteAdapter
from mox_adv.monitoring import DurableWriteWindowGate
from mox_adv.trust_boundary import PreWriteAudit

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "gate0-policy.json"
NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)


class FixedAuthenticator:
    def authenticate(self) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            identity="sviridov",
            authentication="authenticated_macos_user",
        )

    def elevated_reauthenticate(self) -> AuthenticatedPrincipal:
        return self.authenticate()


class RejectingPreWriteAudit:
    def __init__(self, reason: str = "AUDIT_ANCHOR_INVALID") -> None:
        self.reason = reason

    def authorize(
        self,
        _execution_key: str,
        _target_key: str,
        _occurred_at: datetime,
    ) -> None:
        raise AuditWriteBlocked(self.reason)


def load_policy() -> dict[str, object]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def make_scope(campaign: str = "campaign-1") -> TrustedScope:
    return TrustedScope(
        organization="sim-organization",
        connection="sim-connection",
        account="sim-direct-account",
        campaign=campaign,
        writer="sim-executor",
    )


def make_prepared(
    *,
    proposal_id: str = "proposal-autonomy-1",
    campaign: str = "campaign-1",
    action: OptimizationAction = OptimizationAction.DECREASE_SEARCH_BID,
    current_bid_micros: int = 100_000_000,
) -> PreparedChange:
    if action == OptimizationAction.DECREASE_SEARCH_BID:
        current_value = current_bid_micros
        target_value = calculate_relative_target(current_value, -10)
        diff: dict[str, object] = {
            "operation": action,
            "relative_step_percent": 10,
        }
    else:
        current_value = "ON"
        target_value = "SUSPENDED"
        diff = {
            "operation": action,
            "target_state": target_value,
        }
    return PreparedChange(
        proposal_id=proposal_id,
        proposal_hash="sha256:" + "1" * 64,
        scope=make_scope(campaign),
        action=action,
        current_value=current_value,
        target_value=target_value,
        expected_diff=diff,
        snapshot_id="snapshot-autonomy-1",
        snapshot_generated_at="2026-07-30T11:55:00+00:00",
        direct_watermark="2026-07-30T11:55:00+00:00",
        metrika_watermark="2026-07-30T11:55:00+00:00",
        policy_version="mox-adv-gate0-2026-07-29",
        expected_fingerprint="sha256:" + "2" * 64,
        risk="BOUNDED_AUTONOMY_REVERSIBLE_ACTION",
    )


def make_mandate_payload(
    *,
    targets: list[str] | None = None,
    issued_at: datetime = NOW,
    expiry: datetime = NOW + timedelta(hours=24),
) -> dict[str, object]:
    policy = load_policy()
    return {
        "organization": "sim-organization",
        "connection": "sim-connection",
        "account": "sim-direct-account",
        "environment": "SIMULATION",
        "credential_profile": "DIRECT_PILOT_WRITE",
        "targets": ["campaign-1"] if targets is None else targets,
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
        "kpi": {
            "name": "CPA_RUB",
            "target_maximum": 1000,
        },
        "minimum_sample": {
            "clicks": 50,
            "conversions": 3,
        },
        "cooldown": {
            "hours": 72,
            "observation_window_hours": 72,
        },
        "stop_conditions": list(policy["mandate"]["stop_conditions"]),
        "action_quotas": {
            "actions_per_24h": 1,
        },
        "platform_side_spend_cap": 3000,
        "issuer": {
            "identity": "sviridov",
            "authentication": "authenticated_macos_user",
        },
        "policy_version": "mox-adv-gate0-2026-07-29",
        "issued_at": issued_at.isoformat(),
        "expiry": expiry.isoformat(),
    }


def make_request(
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


class MandateAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = Path(self.temporary_directory.name) / "control.sqlite3"
        self.policy = load_policy()
        self.signer = HMACMandateSigner(b"test-only-mandate-key")
        self.authority = DurableMandateAuthority(
            self.database,
            self.policy,
            self.signer,
        )
        self.principal = FixedAuthenticator().authenticate()

    def issue_and_activate(self) -> MandateRecord:
        mandate = self.authority.issue(
            make_mandate_payload(),
            self.principal,
            NOW,
        )
        return self.authority.activate(mandate.mandate_id, self.principal, NOW)

    def test_issue_creates_an_immutable_canonical_signed_binding(self) -> None:
        mandate = self.authority.issue(
            make_mandate_payload(),
            self.principal,
            NOW,
        )

        self.assertEqual("ISSUED", mandate.status)
        self.assertTrue(mandate.mandate_id.startswith("mandate-"))
        self.assertTrue(mandate.canonical_hash.startswith("sha256:"))
        self.assertTrue(mandate.signature.startswith("hmac-sha256:"))
        reopened = DurableMandateAuthority(
            self.database,
            self.policy,
            self.signer,
        )
        self.assertEqual(mandate, reopened.load(mandate.mandate_id))

        connection = sqlite3.connect(str(self.database))
        with connection, self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE mandates SET canonical_json = ? WHERE mandate_id = ?",
                ("{}", mandate.mandate_id),
            )

    def test_invalid_signature_and_illegal_state_rewrite_fail_closed(self) -> None:
        mandate = self.issue_and_activate()
        connection = sqlite3.connect(str(self.database))
        with connection, self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE mandates SET status = 'ISSUED' WHERE mandate_id = ?",
                (mandate.mandate_id,),
            )
        with connection:
            connection.execute("DROP TRIGGER mandates_immutable_fields")
            connection.execute(
                "UPDATE mandates SET signature = ? WHERE mandate_id = ?",
                ("hmac-sha256:" + "0" * 64, mandate.mandate_id),
            )
        with self.assertRaisesRegex(ControlRejected, "MANDATE_INTEGRITY_FAILURE"):
            self.authority.load(mandate.mandate_id)

    def test_unsigned_tampered_widened_and_mismatched_mandates_fail_closed(
        self,
    ) -> None:
        invalid_cases: dict[str, dict[str, object]] = {}
        widened_action = make_mandate_payload()
        widened_action["allowed_action_classes"] = [
            "DECREASE_SEARCH_BID",
            "SUSPEND_CAMPAIGN",
            "INCREASE_SEARCH_BID",
        ]
        invalid_cases["widened-action"] = widened_action
        widened_step = make_mandate_payload()
        widened_step["maximum_step_change"] = 11
        invalid_cases["widened-step"] = widened_step
        wrong_scope = make_mandate_payload()
        wrong_scope["account"] = "unknown-account"
        invalid_cases["wrong-scope"] = wrong_scope
        expired = make_mandate_payload(expiry=NOW)
        invalid_cases["expired"] = expired

        for name, payload in invalid_cases.items():
            with self.subTest(name=name), self.assertRaises(ControlRejected):
                self.authority.issue(payload, self.principal, NOW)

    def test_expired_revoked_and_reactivation_attempts_fail_closed(self) -> None:
        mandate = self.issue_and_activate()
        self.authority.revoke(
            mandate.mandate_id,
            "Issuer revoked bounded authority.",
            self.principal,
            NOW,
        )

        with self.assertRaisesRegex(ControlRejected, "MANDATE_REACTIVATION_FORBIDDEN"):
            self.authority.activate(mandate.mandate_id, self.principal, NOW)

        reopened = DurableMandateAuthority(
            self.database,
            self.policy,
            self.signer,
        )
        self.assertEqual("REVOKED", reopened.load(mandate.mandate_id).status)
        self.assertEqual(1, reopened.load(mandate.mandate_id).revocation_version)

    def test_issuer_cannot_replace_an_existing_mandate_id_with_wider_authority(
        self,
    ) -> None:
        mandate = self.authority.issue(
            make_mandate_payload(),
            self.principal,
            NOW,
        )
        wider = make_mandate_payload()
        wider["maximum_step_change"] = 11
        with self.assertRaises(ControlRejected):
            self.authority.issue(wider, self.principal, NOW)
        self.assertEqual(mandate, self.authority.load(mandate.mandate_id))


class BoundedAutonomyExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = Path(self.temporary_directory.name) / "control.sqlite3"
        self.policy = load_policy()
        self.signer = HMACMandateSigner(b"test-only-mandate-key")
        self.control = DurableControlState(self.database)
        self.authority = DurableMandateAuthority(
            self.database,
            self.policy,
            self.signer,
        )
        self.principal = FixedAuthenticator().authenticate()
        issued = self.authority.issue(
            make_mandate_payload(),
            self.principal,
            NOW,
        )
        self.mandate = self.authority.activate(
            issued.mandate_id,
            self.principal,
            NOW,
        )

    def execute(
        self,
        prepared: PreparedChange,
        *,
        adapter: FakeWriteAdapter | object | None = None,
        now: datetime = NOW,
        request: BoundedAutonomyRequest | None = None,
        pre_write_audit: PreWriteAudit | None = None,
    ):
        self.control.register_prepared_change(prepared)
        write_adapter = (
            FakeWriteAdapter(
                initial_state={prepared.target_key(): prepared.current_value}
            )
            if adapter is None
            else adapter
        )
        service = BoundedAutonomyService(
            self.policy,
            self.control,
            self.authority,
            write_adapter,
            clock=lambda: now,
            pre_write_audit=pre_write_audit,
        )
        return service.execute(
            make_request(prepared, self.mandate) if request is None else request
        ), write_adapter

    def test_end_to_end_autonomy_reaches_exact_fake_readback(self) -> None:
        prepared = make_prepared()
        request = make_request(prepared, self.mandate)

        result, adapter = self.execute(prepared, request=request)

        self.assertEqual("APPLIED", result.status)
        self.assertFalse(hasattr(request, "monetary_exposure_rub"))
        self.assertEqual(prepared.target_value, result.observed_value)
        self.assertEqual(1, adapter.write_calls)
        usage = DurableMandateAuthority(
            self.database,
            self.policy,
            self.signer,
        ).usage(self.mandate.mandate_id)
        self.assertEqual(1, usage.action_count)
        self.assertEqual(10, usage.total_monetary_exposure_rub)
        self.assertEqual(10, usage.daily_cumulative_change_percent)

    def test_missing_or_stale_anchor_blocks_actual_mandate_dispatch(self) -> None:
        prepared = make_prepared()
        adapter = FakeWriteAdapter(
            initial_state={prepared.target_key(): prepared.current_value}
        )

        result, _ = self.execute(
            prepared,
            adapter=adapter,
            pre_write_audit=RejectingPreWriteAudit(),
        )

        self.assertEqual("BLOCKED", result.status)
        self.assertEqual("AUDIT_EVIDENCE_UNAVAILABLE", result.reason_code)
        self.assertEqual(0, adapter.write_calls)
        self.assertEqual(
            "BLOCKED",
            self.control.load_execution(prepared.execution_key()).status,
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
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                database = Path(temporary) / "control.sqlite3"
                policy = load_policy()
                signer = HMACMandateSigner(b"window-gate-test-key")
                control = DurableControlState(database)
                authority = DurableMandateAuthority(database, policy, signer)
                principal = FixedAuthenticator().authenticate()
                issued = authority.issue(
                    make_mandate_payload(),
                    principal,
                    NOW,
                )
                mandate = authority.activate(issued.mandate_id, principal, NOW)
                prepared = make_prepared(
                    proposal_id="proposal-window-" + label,
                )
                control.register_prepared_change(prepared)
                gate = DurableWriteWindowGate(database, policy)
                applied_at = NOW - elapsed
                self.assertTrue(gate.reserve("prior-execution", applied_at).allowed)
                gate.activate("prior-execution", applied_at)
                adapter = FakeWriteAdapter(
                    initial_state={
                        prepared.target_key(): prepared.current_value,
                    }
                )
                result = BoundedAutonomyService(
                    policy,
                    control,
                    authority,
                    adapter,
                    clock=lambda: NOW,
                ).execute(make_request(prepared, mandate))

                self.assertEqual(expected_status, result.status)
                self.assertEqual(expected_writes, adapter.write_calls)
                if label == "before":
                    self.assertEqual(
                        "COOLDOWN_AND_OBSERVATION_ACTIVE",
                        result.reason_code,
                    )

    def test_suspend_campaign_reaches_exact_fake_readback(self) -> None:
        prepared = make_prepared(
            proposal_id="proposal-suspend",
            action=OptimizationAction.SUSPEND_CAMPAIGN,
        )
        request = replace(
            make_request(prepared, self.mandate),
            conversions=0,
            spend_rub=2000,
        )

        result, adapter = self.execute(prepared, request=request)

        self.assertEqual("APPLIED", result.status)
        self.assertEqual("SUSPENDED", result.observed_value)
        self.assertEqual(1, adapter.write_calls)

    def test_only_decrease_bid_and_suspend_are_permitted(self) -> None:
        for action in OptimizationAction:
            if action in {
                OptimizationAction.DECREASE_SEARCH_BID,
                OptimizationAction.SUSPEND_CAMPAIGN,
            }:
                continue
            with self.subTest(action=action):
                prepared = make_prepared(
                    proposal_id="proposal-" + action.value.lower(),
                    action=action,
                )
                self.control.register_prepared_change(prepared)
                adapter = FakeWriteAdapter(
                    initial_state={prepared.target_key(): prepared.current_value}
                )
                result = BoundedAutonomyService(
                    self.policy,
                    self.control,
                    self.authority,
                    adapter,
                    clock=lambda: NOW,
                ).execute(make_request(prepared, self.mandate))
                self.assertEqual("BLOCKED", result.status)
                self.assertEqual("UNSUPPORTED_ACTION", result.reason_code)
                self.assertEqual(0, adapter.write_calls)

    def test_unknown_target_mismatch_expiry_revocation_and_bad_signature_block(
        self,
    ) -> None:
        cases: list[tuple[str, Callable[[], BoundedAutonomyRequest]]] = [
            (
                "unknown-target",
                lambda: replace(
                    make_request(make_prepared(campaign="unknown"), self.mandate),
                    scope=make_scope("unknown"),
                ),
            ),
            (
                "scope-mismatch",
                lambda: replace(
                    make_request(make_prepared(), self.mandate),
                    scope=replace(make_scope(), account="other-account"),
                ),
            ),
        ]
        for name, request_factory in cases:
            with self.subTest(name=name):
                prepared = (
                    make_prepared(campaign="unknown")
                    if name == "unknown-target"
                    else make_prepared(proposal_id="proposal-scope")
                )
                self.control.register_prepared_change(prepared)
                adapter = FakeWriteAdapter()
                result = BoundedAutonomyService(
                    self.policy,
                    self.control,
                    self.authority,
                    adapter,
                    clock=lambda: NOW,
                ).execute(request_factory())
                self.assertEqual("BLOCKED", result.status)
                self.assertEqual(0, adapter.write_calls)

        revoked_prepared = make_prepared(proposal_id="proposal-revoked")
        self.control.register_prepared_change(revoked_prepared)
        self.authority.revoke(
            self.mandate.mandate_id,
            "Stop autonomy.",
            self.principal,
            NOW,
        )
        revoked_adapter = FakeWriteAdapter(
            initial_state={
                revoked_prepared.target_key(): revoked_prepared.current_value
            }
        )
        revoked = BoundedAutonomyService(
            self.policy,
            self.control,
            self.authority,
            revoked_adapter,
            clock=lambda: NOW,
        ).execute(make_request(revoked_prepared, self.mandate))
        self.assertEqual("BLOCKED", revoked.status)
        self.assertEqual("MANDATE_REVOKED", revoked.reason_code)
        self.assertEqual(0, revoked_adapter.write_calls)

    def test_action_quota_daily_limit_and_observation_window_are_durable(self) -> None:
        first = make_prepared()
        first_result, _ = self.execute(first)
        self.assertEqual("APPLIED", first_result.status)

        for elapsed, reason in (
            (timedelta(hours=23, minutes=59), "ACTION_QUOTA_REACHED"),
            (timedelta(hours=24), "OBSERVATION_WINDOW_ACTIVE"),
            (timedelta(hours=71, minutes=59), "OBSERVATION_WINDOW_ACTIVE"),
        ):
            with self.subTest(elapsed=elapsed):
                effective_mandate = self.mandate
                if elapsed >= timedelta(hours=24):
                    effective_now = NOW + elapsed
                    newly_issued = self.authority.issue(
                        make_mandate_payload(
                            issued_at=effective_now,
                            expiry=effective_now + timedelta(hours=24),
                        ),
                        self.principal,
                        effective_now,
                    )
                    effective_mandate = self.authority.activate(
                        newly_issued.mandate_id,
                        self.principal,
                        effective_now,
                    )
                prepared = make_prepared(
                    proposal_id="proposal-" + str(int(elapsed.total_seconds())),
                )
                self.control.register_prepared_change(prepared)
                adapter = FakeWriteAdapter(
                    initial_state={prepared.target_key(): prepared.current_value}
                )
                result = BoundedAutonomyService(
                    self.policy,
                    self.control,
                    DurableMandateAuthority(
                        self.database,
                        self.policy,
                        self.signer,
                    ),
                    adapter,
                    clock=lambda elapsed=elapsed: NOW + elapsed,
                ).execute(make_request(prepared, effective_mandate))
                self.assertEqual("BLOCKED", result.status)
                self.assertEqual(reason, result.reason_code)
                self.assertEqual(0, adapter.write_calls)

    def test_expired_and_over_monetary_limit_mandates_fail_before_send(self) -> None:
        expired_database = Path(self.temporary_directory.name) / "expired.sqlite3"
        expired_control = DurableControlState(expired_database)
        expired_authority = DurableMandateAuthority(
            expired_database,
            self.policy,
            self.signer,
        )
        issued = expired_authority.issue(
            make_mandate_payload(expiry=NOW + timedelta(hours=1)),
            self.principal,
            NOW,
        )
        expired_mandate = expired_authority.activate(
            issued.mandate_id,
            self.principal,
            NOW,
        )
        expired_prepared = make_prepared(proposal_id="proposal-expired")
        expired_control.register_prepared_change(expired_prepared)
        expired_adapter = FakeWriteAdapter(
            initial_state={
                expired_prepared.target_key(): expired_prepared.current_value
            }
        )
        expired = BoundedAutonomyService(
            self.policy,
            expired_control,
            expired_authority,
            expired_adapter,
            clock=lambda: NOW + timedelta(hours=1),
        ).execute(make_request(expired_prepared, expired_mandate))
        self.assertEqual("BLOCKED", expired.status)
        self.assertEqual("MANDATE_EXPIRED", expired.reason_code)
        self.assertEqual(0, expired_adapter.write_calls)

        over_limit_prepared = make_prepared(
            proposal_id="proposal-over-limit",
            current_bid_micros=6_000_000_000,
        )
        self.control.register_prepared_change(over_limit_prepared)
        over_limit_adapter = FakeWriteAdapter(
            initial_state={
                over_limit_prepared.target_key(): over_limit_prepared.current_value
            }
        )
        over_limit = BoundedAutonomyService(
            self.policy,
            self.control,
            self.authority,
            over_limit_adapter,
            clock=lambda: NOW,
        ).execute(make_request(over_limit_prepared, self.mandate))
        self.assertEqual("BLOCKED", over_limit.status)
        self.assertEqual("MONETARY_CAP_REACHED", over_limit.reason_code)
        self.assertEqual(0, over_limit_adapter.write_calls)

    def test_policy_inputs_fail_closed_before_fake_send(self) -> None:
        mutations: dict[str, dict[str, object]] = {
            "mode": {"mode": "APPROVAL_REQUIRED"},
            "automation": {"automation_enabled": False},
            "comparability": {"comparability_status": "INCOMPATIBLE"},
            "confidence": {"confidence_status": "INSUFFICIENT_DATA"},
            "freshness": {"direct_age_minutes": 31},
            "watermark": {"watermark_skew_minutes": 361},
            "sample": {"clicks": 49},
            "fingerprint": {"current_fingerprint": "sha256:" + "9" * 64},
            "strategy": {"campaign_strategy": "AUTOMATIC"},
            "invalid-number": {"cpa_rub": "not-a-number"},
        }
        for name, changes in mutations.items():
            with self.subTest(name=name):
                database = (
                    Path(self.temporary_directory.name) / f"policy-{name}.sqlite3"
                )
                control = DurableControlState(database)
                authority = DurableMandateAuthority(
                    database,
                    self.policy,
                    self.signer,
                )
                issued = authority.issue(
                    make_mandate_payload(),
                    self.principal,
                    NOW,
                )
                mandate = authority.activate(issued.mandate_id, self.principal, NOW)
                prepared = make_prepared(proposal_id="proposal-" + name)
                control.register_prepared_change(prepared)
                adapter = FakeWriteAdapter(
                    initial_state={prepared.target_key(): prepared.current_value}
                )
                request = replace(
                    make_request(prepared, mandate),
                    **changes,
                )
                result = BoundedAutonomyService(
                    self.policy,
                    control,
                    authority,
                    adapter,
                    clock=lambda: NOW,
                ).execute(request)
                self.assertEqual("BLOCKED", result.status)
                self.assertEqual(0, adapter.write_calls)

    def test_concurrent_attempts_consume_one_quota_and_send_one_fake_command(
        self,
    ) -> None:
        prepared = make_prepared()
        self.control.register_prepared_change(prepared)
        adapter = FakeWriteAdapter(
            initial_state={prepared.target_key(): prepared.current_value},
            write_delay_seconds=0.05,
        )
        service = BoundedAutonomyService(
            self.policy,
            self.control,
            self.authority,
            adapter,
            clock=lambda: NOW,
        )
        barrier = threading.Barrier(2)
        results: list[str] = []

        def execute() -> None:
            barrier.wait()
            results.append(service.execute(make_request(prepared, self.mandate)).status)

        threads = [threading.Thread(target=execute) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(1, adapter.write_calls)
        self.assertIn("APPLIED", results)
        self.assertEqual(1, self.authority.usage(self.mandate.mandate_id).action_count)

    def test_restart_preserves_activation_revocation_and_consumed_quotas(self) -> None:
        prepared = make_prepared()
        result, adapter = self.execute(prepared)
        self.assertEqual("APPLIED", result.status)

        reopened_control = DurableControlState(self.database)
        reopened_authority = DurableMandateAuthority(
            self.database,
            self.policy,
            self.signer,
        )
        self.assertEqual(
            "ACTIVE", reopened_authority.load(self.mandate.mandate_id).status
        )
        self.assertEqual(
            1, reopened_authority.usage(self.mandate.mandate_id).action_count
        )

        reconciled = BoundedAutonomyService(
            self.policy,
            reopened_control,
            reopened_authority,
            adapter,
            clock=lambda: NOW,
        ).reconcile(prepared.execution_key())
        self.assertEqual("ALREADY_PROCESSED", reconciled.status)
        self.assertEqual(1, adapter.write_calls)

        reopened_authority.revoke(
            self.mandate.mandate_id,
            "Restart-safe revocation.",
            self.principal,
            NOW,
        )
        self.assertEqual(
            "REVOKED",
            DurableMandateAuthority(
                self.database,
                self.policy,
                self.signer,
            )
            .load(self.mandate.mandate_id)
            .status,
        )

    def test_restart_recovers_reserved_execution_without_retrying_send(self) -> None:
        prepared = make_prepared(proposal_id="proposal-reserved-restart")
        self.control.register_prepared_change(prepared)
        status, _ = self.authority.reserve_execution(
            prepared,
            self.mandate.mandate_id,
            NOW,
        )
        self.assertEqual("RESERVED", status)

        reopened_control = DurableControlState(self.database)
        reopened_authority = DurableMandateAuthority(
            self.database,
            self.policy,
            self.signer,
        )
        adapter = FakeWriteAdapter(
            initial_state={prepared.target_key(): prepared.current_value}
        )
        result = BoundedAutonomyService(
            self.policy,
            reopened_control,
            reopened_authority,
            adapter,
            clock=lambda: NOW,
        ).reconcile(prepared.execution_key())

        self.assertEqual("FAILED", result.status)
        self.assertEqual(0, adapter.write_calls)
        self.assertEqual(
            1,
            reopened_authority.usage(self.mandate.mandate_id).action_count,
        )
        self.assertEqual(
            "FAILED",
            reopened_control.load_execution(prepared.execution_key()).status,
        )

    def test_revocation_and_linked_kill_switch_block_next_unsent_command_under_sla(
        self,
    ) -> None:
        for name in ("revocation", "kill-switch"):
            with self.subTest(name=name):
                database = Path(self.temporary_directory.name) / f"{name}.sqlite3"
                control = DurableControlState(database)
                authority = DurableMandateAuthority(
                    database,
                    self.policy,
                    self.signer,
                )
                issued = authority.issue(
                    make_mandate_payload(),
                    self.principal,
                    NOW,
                )
                mandate = authority.activate(issued.mandate_id, self.principal, NOW)
                prepared = make_prepared(proposal_id="proposal-" + name)
                control.register_prepared_change(prepared)
                if name == "revocation":
                    authority.revoke(
                        mandate.mandate_id,
                        "Immediate revoke.",
                        self.principal,
                        NOW,
                    )
                else:
                    control.engage_kill_switch(
                        "campaign:campaign-1",
                        "Immediate incident stop.",
                        self.principal,
                        NOW,
                    )
                adapter = FakeWriteAdapter()
                started = time.monotonic()
                result = BoundedAutonomyService(
                    self.policy,
                    control,
                    authority,
                    adapter,
                    clock=lambda: NOW,
                ).execute(make_request(prepared, mandate))
                elapsed = time.monotonic() - started
                self.assertEqual("BLOCKED", result.status)
                self.assertEqual(0, adapter.write_calls)
                self.assertLess(elapsed, 1)

    def test_non_fake_adapter_is_rejected_before_any_apply(self) -> None:
        class UnsafeAdapter:
            is_fake = False
            apply_calls = 0

            def readback(self, target_key: str):
                return make_prepared().current_value

            def apply(self, target_key: str, command: object) -> None:
                self.apply_calls += 1

        prepared = make_prepared()
        unsafe = UnsafeAdapter()
        result, _ = self.execute(prepared, adapter=unsafe)
        self.assertEqual("BLOCKED", result.status)
        self.assertEqual("EXTERNAL_WRITE_EGRESS_DENIED", result.reason_code)
        self.assertEqual(0, unsafe.apply_calls)

    def test_fake_adapter_subclass_cannot_override_the_sealed_write_boundary(
        self,
    ) -> None:
        class NetworkCapableSubclass(FakeWriteAdapter):
            network_calls = 0

            def apply(self, target_key: str, command: object) -> None:
                self.network_calls += 1

        prepared = make_prepared(proposal_id="proposal-fake-subclass")
        adapter = NetworkCapableSubclass(
            initial_state={prepared.target_key(): prepared.current_value}
        )

        result, _ = self.execute(prepared, adapter=adapter)

        self.assertEqual("BLOCKED", result.status)
        self.assertEqual("EXTERNAL_WRITE_EGRESS_DENIED", result.reason_code)
        self.assertEqual(0, adapter.network_calls)

    def test_post_send_sqlite_failure_reconciles_without_a_second_send(self) -> None:
        prepared = make_prepared(proposal_id="proposal-post-send-db-failure")
        self.control.register_prepared_change(prepared)
        adapter = FakeWriteAdapter(
            initial_state={prepared.target_key(): prepared.current_value}
        )
        service = BoundedAutonomyService(
            self.policy,
            self.control,
            self.authority,
            adapter,
            clock=lambda: NOW,
        )
        with mock.patch.object(
            self.control,
            "finish_execution",
            side_effect=sqlite3.OperationalError("post-send state failure"),
        ):
            result = service.execute(make_request(prepared, self.mandate))

        self.assertEqual("UNKNOWN_RESULT", result.status)
        self.assertEqual(1, adapter.write_calls)
        self.assertEqual(
            "IN_FLIGHT",
            self.control.load_execution(prepared.execution_key()).status,
        )
        reconciled = BoundedAutonomyService(
            self.policy,
            DurableControlState(self.database),
            DurableMandateAuthority(self.database, self.policy, self.signer),
            adapter,
            clock=lambda: NOW,
        ).reconcile(prepared.execution_key())
        self.assertEqual("APPLIED", reconciled.status)
        self.assertEqual(1, adapter.write_calls)

    def test_concurrent_revoke_and_kill_committed_before_dispatch_win(self) -> None:
        for blocker_name in ("kill-switch", "revocation"):
            with self.subTest(blocker=blocker_name):
                database = (
                    Path(self.temporary_directory.name)
                    / f"concurrent-{blocker_name}.sqlite3"
                )
                control = DurableControlState(database)
                authority = DurableMandateAuthority(
                    database,
                    self.policy,
                    self.signer,
                )
                issued = authority.issue(
                    make_mandate_payload(),
                    self.principal,
                    NOW,
                )
                mandate = authority.activate(issued.mandate_id, self.principal, NOW)
                prepared = make_prepared(
                    proposal_id="proposal-concurrent-" + blocker_name
                )
                control.register_prepared_change(prepared)
                adapter = FakeWriteAdapter(
                    initial_state={prepared.target_key(): prepared.current_value}
                )
                barrier = threading.Barrier(2)
                release_dispatch = threading.Event()

                def before_dispatch(
                    current_barrier=barrier,
                    current_release=release_dispatch,
                ) -> None:
                    current_barrier.wait()
                    current_release.wait(timeout=1)

                service = BoundedAutonomyService(
                    self.policy,
                    control,
                    authority,
                    adapter,
                    clock=lambda: NOW,
                    before_dispatch=before_dispatch,
                )
                results = []

                def run_execution(
                    current_results=results,
                    current_service=service,
                    current_prepared=prepared,
                    current_mandate=mandate,
                ) -> None:
                    current_results.append(
                        current_service.execute(
                            make_request(current_prepared, current_mandate)
                        )
                    )

                worker = threading.Thread(
                    target=run_execution,
                )
                worker.start()
                barrier.wait()
                started = time.monotonic()
                if blocker_name == "kill-switch":
                    control.engage_kill_switch(
                        "campaign:campaign-1",
                        "Concurrent incident stop.",
                        self.principal,
                        NOW,
                    )
                else:
                    authority.revoke(
                        mandate.mandate_id,
                        "Concurrent authority revoke.",
                        self.principal,
                        NOW,
                    )
                release_dispatch.set()
                worker.join(timeout=2)

                self.assertFalse(worker.is_alive())
                self.assertEqual("BLOCKED", results[0].status)
                self.assertEqual(0, adapter.write_calls)
                self.assertLess(time.monotonic() - started, 1)
                self.assertEqual(
                    "BLOCKED",
                    control.load_execution(prepared.execution_key()).status,
                )
                if blocker_name == "kill-switch":
                    control.release_kill_switch(
                        "campaign:campaign-1",
                        "Incident resolved.",
                        self.principal,
                        NOW,
                    )
                    rechecked = service.recheck(make_request(prepared, mandate))
                    self.assertEqual("BLOCKED", rechecked.status)
                    self.assertEqual(
                        "OBSERVATION_WINDOW_ACTIVE",
                        rechecked.reason_code,
                    )
                    self.assertEqual(0, adapter.write_calls)

    def test_failed_execution_recheck_is_readback_only_without_retry(self) -> None:
        prepared = make_prepared(proposal_id="proposal-safe-recheck")
        self.control.register_prepared_change(prepared)
        adapter = FakeWriteAdapter(
            initial_state={prepared.target_key(): prepared.current_value},
            timeout_after_write=True,
            timeout_readback=prepared.current_value,
        )
        service = BoundedAutonomyService(
            self.policy,
            self.control,
            self.authority,
            adapter,
            clock=lambda: NOW,
        )
        request = make_request(prepared, self.mandate)

        first = service.execute(request)
        self.assertEqual("FAILED", first.status)
        self.assertEqual(1, adapter.write_calls)
        self.assertEqual(1, self.authority.usage(self.mandate.mandate_id).action_count)

        second = service.recheck(request)

        self.assertEqual("FAILED", second.status)
        self.assertEqual("RECHECK_SOURCE_STATE_CONFIRMED", second.reason_code)
        self.assertEqual(1, adapter.write_calls)
        self.assertEqual(1, self.authority.usage(self.mandate.mandate_id).action_count)

    def test_indeterminate_terminal_recheck_persists_unknown_and_blocks_writes(
        self,
    ) -> None:
        prepared = make_prepared(proposal_id="proposal-recheck-unknown")
        self.control.register_prepared_change(prepared)
        first_adapter = FakeWriteAdapter(
            initial_state={prepared.target_key(): prepared.current_value},
            timeout_after_write=True,
            timeout_readback=prepared.current_value,
        )
        request = make_request(prepared, self.mandate)
        first = BoundedAutonomyService(
            self.policy,
            self.control,
            self.authority,
            first_adapter,
            clock=lambda: NOW,
        ).execute(request)
        self.assertEqual("FAILED", first.status)

        unknown_adapter = FakeWriteAdapter()
        rechecked = BoundedAutonomyService(
            self.policy,
            self.control,
            self.authority,
            unknown_adapter,
            clock=lambda: NOW,
        ).recheck(request)
        self.assertEqual("UNKNOWN_RESULT", rechecked.status)
        self.assertEqual(
            "UNKNOWN_RESULT",
            self.control.load_execution(prepared.execution_key()).status,
        )

        next_prepared = make_prepared(proposal_id="proposal-after-unknown")
        self.control.register_prepared_change(next_prepared)
        blocked_adapter = FakeWriteAdapter(
            initial_state={next_prepared.target_key(): next_prepared.current_value}
        )
        blocked = BoundedAutonomyService(
            self.policy,
            self.control,
            self.authority,
            blocked_adapter,
            clock=lambda: NOW,
        ).execute(make_request(next_prepared, self.mandate))
        self.assertEqual("BLOCKED", blocked.status)
        self.assertEqual("UNKNOWN_RESULT", blocked.reason_code)
        self.assertEqual(0, blocked_adapter.write_calls)

    def test_recheck_records_existing_target_without_resending(self) -> None:
        prepared = make_prepared(proposal_id="proposal-recheck-target")
        self.control.register_prepared_change(prepared)
        first_adapter = FakeWriteAdapter(
            initial_state={prepared.target_key(): prepared.current_value},
            timeout_after_write=True,
            timeout_readback=prepared.current_value,
        )
        request = make_request(prepared, self.mandate)
        first = BoundedAutonomyService(
            self.policy,
            self.control,
            self.authority,
            first_adapter,
            clock=lambda: NOW,
        ).execute(request)
        self.assertEqual("FAILED", first.status)

        readback_adapter = FakeWriteAdapter(
            initial_state={prepared.target_key(): prepared.target_value}
        )
        rechecked = BoundedAutonomyService(
            self.policy,
            self.control,
            self.authority,
            readback_adapter,
            clock=lambda: NOW,
        ).recheck(request)

        self.assertEqual("APPLIED", rechecked.status)
        self.assertEqual(0, readback_adapter.write_calls)
        self.assertEqual(
            "APPLIED",
            self.control.load_execution(prepared.execution_key()).status,
        )
        self.assertEqual(1, self.authority.usage(self.mandate.mandate_id).action_count)

    def test_control_state_failure_fails_closed_without_fake_send(self) -> None:
        prepared = make_prepared()
        self.control.register_prepared_change(prepared)
        adapter = FakeWriteAdapter(
            initial_state={prepared.target_key(): prepared.current_value}
        )
        service = BoundedAutonomyService(
            self.policy,
            self.control,
            self.authority,
            adapter,
            clock=lambda: NOW,
        )
        with mock.patch.object(
            self.authority,
            "reserve_execution",
            side_effect=sqlite3.OperationalError("unavailable"),
        ):
            result = service.execute(make_request(prepared, self.mandate))
        self.assertEqual("BLOCKED", result.status)
        self.assertEqual("CONTROL_STATE_UNAVAILABLE", result.reason_code)
        self.assertEqual(0, adapter.write_calls)


class MandateCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = Path(self.temporary_directory.name) / "control.sqlite3"
        self.mandate_file = Path(self.temporary_directory.name) / "mandate.json"
        self.mandate_file.write_text(
            json.dumps(make_mandate_payload()),
            encoding="utf-8",
        )
        self.policy = load_policy()
        self.signer = HMACMandateSigner(b"test-only-mandate-key")
        self.authority = DurableMandateAuthority(
            self.database,
            self.policy,
            self.signer,
        )
        self.authenticator = FixedAuthenticator()

    def test_exact_gate0_mandate_commands_are_supported(self) -> None:
        parser = build_parser()
        issue = parser.parse_args(
            ["mandate", "issue", "--file", str(self.mandate_file)]
        )
        activate = parser.parse_args(
            ["mandate", "activate", "--mandate-id", "mandate-1"]
        )
        revoke = parser.parse_args(
            [
                "mandate",
                "revoke",
                "--mandate-id",
                "mandate-1",
                "--reason",
                "Stop.",
            ]
        )
        self.assertEqual(("mandate", "issue"), (issue.command, issue.operation))
        self.assertEqual(
            ("mandate", "activate"),
            (activate.command, activate.operation),
        )
        self.assertEqual(("mandate", "revoke"), (revoke.command, revoke.operation))

    def test_cli_issues_activates_and_revokes_durable_mandate(self) -> None:
        self.assertEqual(
            0,
            main(
                ["mandate", "issue", "--file", str(self.mandate_file)],
                control_state=DurableControlState(self.database),
                mandate_authority=self.authority,
                authenticator=self.authenticator,
                clock=lambda: NOW,
            ),
        )
        mandate_id = self.authority.list_records()[0].mandate_id
        self.assertEqual(
            0,
            main(
                ["mandate", "activate", "--mandate-id", mandate_id],
                control_state=DurableControlState(self.database),
                mandate_authority=self.authority,
                authenticator=self.authenticator,
                clock=lambda: NOW,
            ),
        )
        self.assertEqual(
            0,
            main(
                [
                    "mandate",
                    "revoke",
                    "--mandate-id",
                    mandate_id,
                    "--reason",
                    "Stop bounded autonomy.",
                ],
                control_state=DurableControlState(self.database),
                mandate_authority=self.authority,
                authenticator=self.authenticator,
                clock=lambda: NOW,
            ),
        )
        self.assertEqual("REVOKED", self.authority.load(mandate_id).status)


if __name__ == "__main__":
    unittest.main()
