from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mox_adv.commands import OptimizationAction, calculate_relative_target
from mox_adv.control_state import (
    AuthenticatedPrincipal,
    ControlRejected,
    DurableControlState,
    PreparedChange,
    TrustedScope,
)
from mox_adv.mandate_signing import HMACMandateSigner
from mox_adv.mandate_store import DurableMandateAuthority
from mox_adv.ui_control_plane import DashboardControlPlane

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


def load_policy() -> dict[str, object]:
    return json.loads(
        (ROOT / "config" / "gate0-policy.json").read_text(encoding="utf-8")
    )


def principal(identity: str = "sviridov") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        identity=identity,
        authentication="authenticated_macos_user",
    )


def prepared_change(proposal_id: str = "proposal-ui-control") -> PreparedChange:
    current_value = 2_000_000_000
    return PreparedChange(
        proposal_id=proposal_id,
        proposal_hash="sha256:" + "1" * 64,
        scope=TrustedScope(
            organization="sim-organization",
            connection="sim-connection",
            account="sim-direct-account",
            campaign="campaign-1",
            writer="sim-executor",
        ),
        action=OptimizationAction.INCREASE_WEEKLY_BUDGET,
        current_value=current_value,
        target_value=calculate_relative_target(current_value, 10),
        expected_diff={
            "operation": "INCREASE_WEEKLY_BUDGET",
            "relative_step_percent": 10,
        },
        snapshot_id="snapshot-ui-control",
        snapshot_generated_at="2026-07-29T11:55:00+00:00",
        direct_watermark="2026-07-29T11:55:00+00:00",
        metrika_watermark="2026-07-29T11:55:00+00:00",
        policy_version="mox-adv-gate0-2026-07-29",
        expected_fingerprint="sha256:" + "2" * 64,
        risk="WEEKLY_BUDGET_INCREASE",
    )


def mandate_payload(
    policy: dict[str, object],
    *,
    expiry: datetime = NOW + timedelta(hours=24),
) -> dict[str, object]:
    mandate = policy["mandate"]
    assert isinstance(mandate, dict)
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
        "prohibited_action_classes": list(mandate["prohibited_action_classes"]),
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
        "stop_conditions": list(mandate["stop_conditions"]),
        "action_quotas": {
            "actions_per_24h": 1,
        },
        "platform_side_spend_cap": 3000,
        "issuer": {
            "identity": "sviridov",
            "authentication": "authenticated_macos_user",
        },
        "policy_version": "mox-adv-gate0-2026-07-29",
        "issued_at": NOW.isoformat(),
        "expiry": expiry.isoformat(),
    }


class DashboardControlPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = Path(self.temporary_directory.name) / "control.sqlite3"
        self.policy = load_policy()
        self.state = DurableControlState(self.database)
        self.authority = DurableMandateAuthority(
            self.database,
            self.policy,
            HMACMandateSigner(b"test-only-dashboard-control-key"),
        )
        self.facade = DashboardControlPlane(
            self.state,
            self.authority,
            self.policy,
        )

    def test_default_mode_catalog_is_json_safe_and_mode_is_durable(self) -> None:
        overview = self.facade.overview(now=NOW)

        self.assertEqual("dashboard-control-plane-v1", overview["schema_version"])
        self.assertEqual("OBSERVE", overview["operating_mode"]["selected"])
        self.assertEqual(
            [
                "OBSERVE",
                "RECOMMEND",
                "APPROVAL_REQUIRED",
                "BOUNDED_AUTONOMY",
            ],
            [item["name"] for item in overview["operating_modes"]],
        )
        self.assertFalse(overview["execution_authorized"])
        json.dumps(overview)

        changed = self.facade.select_mode(
            "APPROVAL_REQUIRED",
            principal(),
            NOW,
        )
        reopened = DashboardControlPlane(
            DurableControlState(self.database),
            DurableMandateAuthority(
                self.database,
                self.policy,
                HMACMandateSigner(b"test-only-dashboard-control-key"),
            ),
            self.policy,
        )

        self.assertEqual("APPROVAL_REQUIRED", changed["selected"])
        self.assertEqual(
            "APPROVAL_REQUIRED",
            reopened.overview(now=NOW)["operating_mode"]["selected"],
        )
        self.assertEqual(1, changed["version"])

    def test_mode_selection_rejects_unknown_mode_and_wrong_principal(self) -> None:
        with self.assertRaisesRegex(ControlRejected, "INVALID_OPERATING_MODE"):
            self.facade.select_mode("TEST", principal(), NOW)

        with self.assertRaisesRegex(ControlRejected, "UNAUTHENTICATED_PRINCIPAL"):
            self.facade.select_mode("RECOMMEND", principal("intruder"), NOW)

        self.assertEqual(
            "OBSERVE",
            self.facade.overview(now=NOW)["operating_mode"]["selected"],
        )

    def test_approval_grant_list_and_revoke_use_immutable_backend_record(self) -> None:
        prepared = prepared_change()
        self.state.register_prepared_change(prepared)

        granted = self.facade.grant_approval(
            proposal_id=prepared.proposal_id,
            expires_at=NOW + timedelta(minutes=15),
            reason="Exact dashboard approval.",
            principal=principal(),
            now=NOW,
        )
        approvals = self.facade.list_approvals(now=NOW)

        self.assertEqual(granted, approvals[0])
        self.assertEqual("AVAILABLE", granted["status"])
        self.assertEqual(prepared.binding_hash(), granted["binding_hash"])
        self.assertEqual(
            {
                "organization": "sim-organization",
                "connection": "sim-connection",
                "account": "sim-direct-account",
                "campaign": "campaign-1",
            },
            granted["scope"],
        )
        self.assertNotIn("canonical_hash", granted)

        revoked = self.facade.revoke_approval(
            granted["approval_id"],
            principal(),
            NOW + timedelta(minutes=1),
        )
        self.assertEqual("REVOKED", revoked["status"])
        self.assertEqual(granted["binding_hash"], revoked["binding_hash"])

    def test_mandate_lifecycle_returns_redacted_scope_expiry_and_quotas(self) -> None:
        issued = self.facade.issue_mandate(
            mandate_payload(self.policy),
            principal(),
            NOW,
        )

        self.assertEqual("ISSUED", issued["status"])
        self.assertEqual(["campaign-1"], issued["scope"]["targets"])
        self.assertEqual(1, issued["quotas"]["actions_per_24h"]["limit"])
        self.assertEqual(0, issued["quotas"]["actions_per_24h"]["used"])
        self.assertEqual(500, issued["quotas"]["total_monetary_rub"]["limit"])
        self.assertNotIn("signature", issued)
        self.assertNotIn("credential_profile", json.dumps(issued))

        active = self.facade.activate_mandate(
            issued["mandate_id"],
            principal(),
            NOW + timedelta(minutes=1),
        )
        revoked = self.facade.revoke_mandate(
            issued["mandate_id"],
            "Operator revoked OAuth secret-value",
            principal(),
            NOW + timedelta(minutes=2),
        )

        self.assertEqual("ACTIVE", active["status"])
        self.assertEqual("REVOKED", revoked["status"])
        self.assertNotIn("secret-value", json.dumps(revoked))
        self.assertIn("[REDACTED]", revoked["revocation_reason"])

    def test_kill_switch_state_is_scoped_durable_and_redacts_reason(self) -> None:
        engaged = self.facade.engage_kill_switch(
            "campaign:campaign-1",
            "Incident token=top-secret",
            principal(),
            NOW,
        )

        self.assertTrue(engaged["active"])
        self.assertEqual("campaign:campaign-1", engaged["scope"])
        self.assertNotIn("top-secret", json.dumps(engaged))
        self.assertTrue(
            DashboardControlPlane(
                DurableControlState(self.database),
                self.authority,
                self.policy,
            ).list_kill_switches()[0]["active"]
        )

        released = self.facade.release_kill_switch(
            "campaign:campaign-1",
            "Incident resolved.",
            principal(),
            NOW + timedelta(minutes=1),
        )
        self.assertFalse(released["active"])

    def test_execution_ledger_is_presented_without_mutating_execution(self) -> None:
        prepared = prepared_change()
        self.state.register_prepared_change(prepared)
        self.state.reserve_execution(prepared, NOW)

        executions = self.facade.list_executions()

        self.assertEqual(1, len(executions))
        self.assertEqual("RESERVED", executions[0]["status"])
        self.assertEqual(prepared.execution_key(), executions[0]["execution_key"])
        self.assertEqual(2_000_000_000, executions[0]["current_value"])
        self.assertEqual(2_200_000_000, executions[0]["target_value"])
        self.assertFalse(executions[0]["terminal"])
        json.dumps(executions)

    def test_preconditions_fail_closed_until_exact_authority_exists(self) -> None:
        self.facade.select_mode("APPROVAL_REQUIRED", principal(), NOW)

        missing = self.facade.precondition_state(now=NOW)
        self.assertEqual("BLOCKED", missing["status"])
        self.assertIn("MISSING_PROPOSAL_CONTEXT", missing["reason_codes"])
        self.assertFalse(missing["execution_authorized"])

        prepared = prepared_change()
        self.state.register_prepared_change(prepared)
        self.facade.grant_approval(
            proposal_id=prepared.proposal_id,
            expires_at=NOW + timedelta(minutes=15),
            reason="Exact dashboard approval.",
            principal=principal(),
            now=NOW,
        )
        ready = self.facade.precondition_state(
            now=NOW,
            proposal_id=prepared.proposal_id,
            binding_hash=prepared.binding_hash(),
            scope=prepared.scope,
            environment="SIMULATION",
        )

        self.assertEqual("READY_TO_REQUEST_EXECUTION", ready["status"])
        self.assertEqual([], ready["reason_codes"])
        self.assertFalse(ready["execution_authorized"])

        self.facade.engage_kill_switch(
            "campaign:campaign-1",
            "Safety stop.",
            principal(),
            NOW,
        )
        blocked = self.facade.precondition_state(
            now=NOW,
            proposal_id=prepared.proposal_id,
            binding_hash=prepared.binding_hash(),
            scope=prepared.scope,
            environment="SIMULATION",
        )
        self.assertEqual("BLOCKED", blocked["status"])
        self.assertIn("KILL_SWITCH_ACTIVE", blocked["reason_codes"])

    def test_production_gate_is_visible_and_bounded_autonomy_requires_mandate(
        self,
    ) -> None:
        gates = self.facade.gate_state()
        self.assertEqual("READY", gates["simulation"]["status"])
        self.assertEqual("BLOCKED", gates["controlled_pilot"]["status"])
        self.assertFalse(gates["production_write"]["authorized"])

        self.facade.select_mode("BOUNDED_AUTONOMY", principal(), NOW)
        missing = self.facade.precondition_state(
            now=NOW,
            scope=prepared_change().scope,
        )
        self.assertEqual("BLOCKED", missing["status"])
        self.assertIn("MISSING_MANDATE_CONTEXT", missing["reason_codes"])

        issued = self.facade.issue_mandate(
            mandate_payload(self.policy),
            principal(),
            NOW,
        )
        inactive = self.facade.precondition_state(
            now=NOW,
            mandate_id=issued["mandate_id"],
            scope=prepared_change().scope,
        )
        self.assertEqual("BLOCKED", inactive["status"])
        self.assertIn("MANDATE_INACTIVE", inactive["reason_codes"])
        self.facade.activate_mandate(
            issued["mandate_id"],
            principal(),
            NOW + timedelta(minutes=1),
        )
        ready = self.facade.precondition_state(
            now=NOW + timedelta(minutes=1),
            mandate_id=issued["mandate_id"],
            scope=prepared_change().scope,
            environment="SIMULATION",
        )
        self.assertEqual("READY_TO_REQUEST_EXECUTION", ready["status"])
        self.assertFalse(ready["execution_authorized"])

    def test_controlled_pilot_preconditions_cannot_bypass_blocked_gate(self) -> None:
        prepared = prepared_change()
        self.state.register_prepared_change(prepared)
        self.facade.grant_approval(
            proposal_id=prepared.proposal_id,
            expires_at=NOW + timedelta(minutes=15),
            reason="Exact dashboard approval.",
            principal=principal(),
            now=NOW,
        )
        self.facade.select_mode("APPROVAL_REQUIRED", principal(), NOW)

        blocked = self.facade.precondition_state(
            now=NOW,
            proposal_id=prepared.proposal_id,
            binding_hash=prepared.binding_hash(),
            scope=prepared.scope,
            environment="CONTROLLED_PILOT",
        )

        self.assertEqual("BLOCKED", blocked["status"])
        self.assertIn(
            "CONTROLLED_PILOT_NOT_AUTHORIZED",
            blocked["reason_codes"],
        )
        self.assertIn(
            "PRODUCTION_WRITE_NOT_AUTHORIZED",
            blocked["reason_codes"],
        )
        self.assertFalse(blocked["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
