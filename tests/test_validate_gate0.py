from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from scripts.validate_gate0 import BINDING_TYPES, load_policy, validate_policy


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "gate0-policy.json"


class Gate0PolicyValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_policy(POLICY_PATH)
        self.now = datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc)

    def trusted_manifest(
        self,
        observed_at: Optional[datetime] = None,
    ) -> dict[str, object]:
        observed_at = observed_at or self.now
        contract = self.policy["bindings"]["creation_reservation_contract"]
        binding_entries = {}
        for index, (name, binding_type) in enumerate(
            BINDING_TYPES.items(),
            start=1,
        ):
            entry = {
                "value": f"verified-production-value-{index}",
                "binding_type": binding_type,
                "source": "trusted_run_context",
                "allowlisted": True,
                "ownership_verified": True,
                "verification_status": "VERIFIED",
                "readback_evidence": {
                    "evidence_type": (
                        "LOCAL_RESERVATION"
                        if binding_type == "creation_reservation"
                        else "API_OR_SITE_READBACK"
                    ),
                    "evidence_id": f"evidence-{index}",
                    "observed_at": observed_at.isoformat(),
                },
            }
            if binding_type == "creation_reservation":
                reservation_contract = contract["bindings"][name]
                entry["reservation"] = {
                    "status": "UNUSED",
                    "scope_binding": reservation_contract["scope_binding"],
                    "object_type": reservation_contract["object_type"],
                    "proposal_id": f"proposal-{index}",
                    "credential_profile": reservation_contract[
                        "credential_profile"
                    ],
                    "expires_at": (
                        observed_at + timedelta(hours=1)
                    ).isoformat(),
                }
            binding_entries[name] = entry
        manifest: dict[str, object] = {
            "manifest_version": "trusted-binding-manifest-v1",
            "issuer": "sviridov",
            "issued_at": observed_at.isoformat(),
            "bindings": binding_entries,
        }
        return manifest

    def test_simulation_policy_is_valid(self) -> None:
        self.assertEqual([], validate_policy(self.policy, profile="simulation"))

    def test_pilot_policy_fails_closed_with_unresolved_bindings(self) -> None:
        errors = validate_policy(self.policy, profile="pilot")

        self.assertTrue(
            any("pilot bindings are unresolved" in error for error in errors),
            errors,
        )

    def test_pilot_policy_accepts_complete_external_trusted_bindings(self) -> None:
        errors = validate_policy(
            self.policy,
            profile="pilot",
            trusted_pilot_bindings=self.trusted_manifest(),
            validation_time=self.now,
        )

        self.assertEqual([], errors)

    def test_pilot_policy_rejects_unverified_readback_manifest(self) -> None:
        manifest = self.trusted_manifest()
        manifest["bindings"]["direct_account"][
            "verification_status"
        ] = "UNVERIFIED"

        errors = validate_policy(
            self.policy,
            profile="pilot",
            trusted_pilot_bindings=manifest,
            validation_time=self.now,
        )

        self.assertTrue(
            any("unverified authority" in error for error in errors),
            errors,
        )

    def test_pilot_policy_rejects_stale_readback_manifest(self) -> None:
        manifest = self.trusted_manifest(
            self.now - timedelta(minutes=16)
        )

        errors = validate_policy(
            self.policy,
            profile="pilot",
            trusted_pilot_bindings=manifest,
            validation_time=self.now,
        )

        self.assertTrue(
            any("stale or future" in error for error in errors),
            errors,
        )

    def test_pilot_policy_rejects_future_readback_manifest(self) -> None:
        manifest = self.trusted_manifest(
            self.now + timedelta(minutes=1)
        )

        errors = validate_policy(
            self.policy,
            profile="pilot",
            trusted_pilot_bindings=manifest,
            validation_time=self.now,
        )

        self.assertTrue(
            any("stale or future" in error for error in errors),
            errors,
        )

    def test_pilot_policy_rejects_expired_creation_reservation(self) -> None:
        manifest = self.trusted_manifest()
        reservation = manifest["bindings"][
            "campaign_creation_reservation"
        ]["reservation"]
        reservation["expires_at"] = (
            self.now - timedelta(seconds=1)
        ).isoformat()

        errors = validate_policy(
            self.policy,
            profile="pilot",
            trusted_pilot_bindings=manifest,
            validation_time=self.now,
        )

        self.assertTrue(
            any("invalid reservation expiry" in error for error in errors),
            errors,
        )

    def test_unknown_field_is_rejected(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["limits"]["unexpected_limit"] = 1

        errors = validate_policy(policy, profile="simulation")

        self.assertTrue(any("unknown field" in error for error in errors), errors)

    def test_nested_unknown_field_is_rejected(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["conversion"]["primary"]["unexpected"] = "value"

        errors = validate_policy(policy, profile="simulation")

        self.assertTrue(any("unknown field" in error for error in errors), errors)

    def test_unknown_mandate_field_is_rejected(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["mandate"]["unexpected"] = "value"

        errors = validate_policy(policy, profile="simulation")

        self.assertTrue(any("unknown field" in error for error in errors), errors)

    def test_changed_approved_value_is_rejected_by_digest(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["attribution"]["direct"] = "arbitrary"

        errors = validate_policy(policy, profile="simulation")

        self.assertTrue(
            any("approved record digest mismatch" in error for error in errors),
            errors,
        )

    def test_unknown_api_combination_is_rejected(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["api_matrix"].append(
            {
                "system": "DIRECT",
                "environment": "production",
                "host": "api.direct.yandex.com",
                "path": "/json/v501/campaigns",
                "version": "v501",
                "service": "Campaigns",
                "method": "invented",
                "http_verb": "POST",
                "access_class": "INTEGRATION_WRITE_ONLY",
                "verification_status": "DOCUMENTED_NOT_EXECUTED",
            }
        )

        errors = validate_policy(policy, profile="simulation")

        self.assertTrue(
            any("unknown API combination" in error for error in errors),
            errors,
        )

    def test_invalid_limits_are_rejected(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["limits"]["application_daily_spend_rub"] = 3_001

        errors = validate_policy(policy, profile="simulation")

        self.assertTrue(
            any("daily spend cap" in error for error in errors),
            errors,
        )

    def test_role_mismatch_is_rejected(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["principals"]["security_signoff"]["identity"] = "other-user"

        errors = validate_policy(policy, profile="simulation")

        self.assertTrue(any("role mismatch" in error for error in errors), errors)

    def test_llm_fixture_ambiguity_outcome_is_enforced(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["llm"]["reliability_fixtures"][3][
            "ambiguity_outcome"
        ] = "NOT_APPLICABLE"

        errors = validate_policy(policy, profile="simulation")

        self.assertTrue(
            any("ambiguity outcome mismatch" in error for error in errors),
            errors,
        )

    def test_llm_fixture_status_stays_bound_to_its_name(self) -> None:
        policy = copy.deepcopy(self.policy)
        first, second = policy["llm"]["reliability_fixtures"][:2]
        first["expected_status"], second["expected_status"] = (
            second["expected_status"],
            first["expected_status"],
        )

        errors = validate_policy(policy, profile="simulation")

        self.assertTrue(
            any("expected status mismatch" in error for error in errors),
            errors,
        )

    def test_direct_matrix_covers_every_fr_002_method(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["api_matrix"] = [
            entry
            for entry in policy["api_matrix"]
            if not (
                entry["system"] == "DIRECT"
                and entry["service"] == "KeywordBids"
                and entry["method"] == "set"
            )
        ]

        errors = validate_policy(policy, profile="simulation")

        self.assertTrue(
            any("missing API combination" in error for error in errors),
            errors,
        )

    def test_repository_policy_contains_no_production_identifier(self) -> None:
        serialized = json.dumps(
            self.policy["bindings"]["pilot"],
            ensure_ascii=False,
        )

        self.assertNotIn("account_id", serialized)
        self.assertNotIn("created_campaign", serialized)
        self.assertTrue(
            all(
                value is None
                for value in self.policy["bindings"]["pilot"].values()
            )
        )


if __name__ == "__main__":
    unittest.main()
