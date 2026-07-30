from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mox_adv.control_state import AuthenticatedPrincipal
from mox_adv.e2e_browser import exercise_goal_event
from mox_adv.e2e_evidence import ReadOnlyEgressRecorder
from mox_adv.environment import ExecutionEnvironment
from mox_adv.goal_lifecycle import (
    AuthorityKind,
    CreationReservation,
    FakeMetrikaGoalAdapter,
    FakeSitePublishAdapter,
    GoalAuthority,
    GoalLifecycleService,
    GoalLifecycleStore,
    goal_creation_binding,
    site_publish_binding,
    site_publish_diff,
)
from mox_adv.module_api.v1 import (
    ContractValidationError,
    HttpJsonModuleAdapterV1,
    ModuleResultV1,
)
from mox_adv.modules.metrika import (
    BoundMetrikaGoalLifecycleProviderV1,
    MetrikaGoalLifecycleAuthorizationError,
    MetrikaModuleV1,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc)


def goal_candidate(event: str = "lead_submitted") -> dict[str, Any]:
    details = {
        "lead_submitted": (
            "Submitted lead",
            "#lead-form",
            "A visitor submitted the lead form.",
        ),
        "form_started": (
            "Started lead form",
            "#lead-name",
            "A visitor started completing the lead form.",
        ),
    }
    name, selector, meaning = details[event]
    return {
        "schema_version": "goal-candidate-input-v1",
        "name": name,
        "event": event,
        "site_location": selector,
        "type": "ACTION",
        "business_meaning": meaning,
        "priority": 1,
        "duplicate_signals": [],
    }


def legacy_goal_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    value = dict(candidate)
    value["schema_version"] = "goal-candidate-v1"
    return value


def goal_request(command: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "module-request-v1",
        "connection_ref": {"connection_id": "stored-test-metrika"},
        "environment": "TEST",
        "scope": {
            "organization_id": "customer-42",
            "counter_id": "sim-test-counter",
        },
        "period": {
            "start_date": "2026-07-30",
            "end_date": "2026-07-30",
            "timezone": "UTC",
        },
        "objective": {
            "code": "AUTHOR_GOAL_CANDIDATE",
            "description": "Validate a candidate conversion goal in test.",
        },
        "operation": {
            "kind": "EXECUTE",
            "operation_type": "MANAGE_GOAL_CANDIDATE",
        },
        "goal_lifecycle_command": command,
        "idempotency_key": "goal-lifecycle-create-1",
    }


class FakeSemanticAuthenticator:
    def authenticate(self) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            identity="sviridov",
            authentication="authenticated_macos_user",
        )


class StandaloneMetrikaGoalLifecycleE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = json.loads(
            (ROOT / "config" / "gate0-policy.json").read_text(encoding="utf-8")
        )
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = GoalLifecycleStore(Path(temporary.name) / "goals.sqlite3")
        self.goal_adapter = FakeMetrikaGoalAdapter(
            ("sim-test-counter", "sim-pilot-counter")
        )
        self.site_adapter = FakeSitePublishAdapter(
            {
                "sim-test-site-zone": "test-page-v1",
                "sim-pilot-site-zone": "pilot-page-v1",
            }
        )
        self.lifecycle = GoalLifecycleService(
            self.policy,
            self.store,
            self.goal_adapter,
            self.site_adapter,
            FakeSemanticAuthenticator(),
            environment=ExecutionEnvironment.TEST,
        )
        self.provider = BoundMetrikaGoalLifecycleProviderV1(
            connection_id="stored-test-metrika",
            counter_id="sim-test-counter",
            credential_profile="METRIKA_TEST_WRITE",
            lifecycle=self.lifecycle,
        )
        self.module = MetrikaModuleV1(
            goal_lifecycle_provider=self.provider,
            clock=lambda: NOW,
        )
        self.adapter = HttpJsonModuleAdapterV1.for_embedded(
            self.module,
            environment=ExecutionEnvironment.TEST,
        )

    def _create_candidate(
        self,
        *,
        run_id: str = "goal-run-1",
        proposal_id: str = "goal-proposal-1",
        event: str = "lead_submitted",
    ) -> dict[str, Any]:
        candidate = goal_candidate(event)
        reservation = CreationReservation(
            reservation_id="reservation-" + run_id,
            scope_binding="test_counter",
            object_type="METRIKA_GOAL",
            proposal_id=proposal_id,
            credential_profile="METRIKA_TEST_WRITE",
            expires_at=NOW + timedelta(minutes=15),
        )
        authority = GoalAuthority(
            authority_id="goal-authority-" + run_id,
            kind=AuthorityKind.MANDATE,
            principal="sviridov",
            authentication="authenticated_macos_user",
            proposal_id=proposal_id,
            counter_id="sim-test-counter",
            site_zone="sim-test-site-zone",
            allowed_actions=("GOAL_AUTHORING",),
            expires_at=NOW + timedelta(hours=1),
            policy_id=self.policy["policy_id"],
            binding_hash=goal_creation_binding(
                policy_id=self.policy["policy_id"],
                run_id=run_id,
                candidate_id="candidate-" + run_id,
                proposal_id=proposal_id,
                reservation_id=reservation.reservation_id,
                counter_id="sim-test-counter",
                site_zone="sim-test-site-zone",
                credential_profile="METRIKA_TEST_WRITE",
                payload=legacy_goal_candidate(candidate),
            ),
        )
        self.store.register_reservation(reservation)
        self.store.register_authority(authority)
        request = goal_request(
            {
                "schema_version": "goal-lifecycle-command-v1",
                "action": "CREATE_CANDIDATE",
                "run_id": run_id,
                "proposal_id": proposal_id,
                "reservation_id": reservation.reservation_id,
                "authority_id": authority.authority_id,
                "candidate": candidate,
            }
        )
        request["idempotency_key"] = "create-" + run_id
        return self.adapter.handle(request).body

    def _publish_candidate(
        self,
        candidate_id: str,
    ) -> dict[str, Any]:
        candidate = self.store.load_candidate(candidate_id)
        authority = GoalAuthority(
            authority_id="site-authority-" + candidate.run_id,
            kind=AuthorityKind.APPROVAL,
            principal="sviridov",
            authentication="authenticated_macos_user",
            proposal_id=candidate.proposal_id,
            counter_id=candidate.counter_id,
            site_zone="sim-test-site-zone",
            allowed_actions=("SITE_PUBLISH",),
            expires_at=NOW + timedelta(minutes=15),
            policy_id=self.policy["policy_id"],
            binding_hash=site_publish_binding(
                policy_id=self.policy["policy_id"],
                candidate=candidate,
                exact_diff=site_publish_diff(
                    candidate,
                    "sim-test-site-zone",
                    "test-page-v1",
                ),
            ),
        )
        self.store.register_authority(authority)
        request = goal_request(
            {
                "schema_version": "goal-lifecycle-command-v1",
                "action": "PUBLISH_EVENT",
                "candidate_id": candidate_id,
                "authority_id": authority.authority_id,
                "site_zone": "sim-test-site-zone",
                "expected_version": "test-page-v1",
            }
        )
        request["idempotency_key"] = "publish-" + candidate.run_id
        return self.adapter.handle(request).body

    def _seed_pilot_candidate(self) -> str:
        run_id = "pilot-run"
        proposal_id = "pilot-proposal"
        candidate = goal_candidate("form_started")
        reservation = CreationReservation(
            reservation_id="pilot-reservation",
            scope_binding="pilot_counter",
            object_type="METRIKA_GOAL",
            proposal_id=proposal_id,
            credential_profile="METRIKA_PILOT_WRITE",
            expires_at=NOW + timedelta(minutes=15),
        )
        authority = GoalAuthority(
            authority_id="pilot-authority",
            kind=AuthorityKind.MANDATE,
            principal="sviridov",
            authentication="authenticated_macos_user",
            proposal_id=proposal_id,
            counter_id="sim-pilot-counter",
            site_zone="sim-pilot-site-zone",
            allowed_actions=("GOAL_AUTHORING",),
            expires_at=NOW + timedelta(hours=1),
            policy_id=self.policy["policy_id"],
            binding_hash=goal_creation_binding(
                policy_id=self.policy["policy_id"],
                run_id=run_id,
                candidate_id="candidate-" + run_id,
                proposal_id=proposal_id,
                reservation_id=reservation.reservation_id,
                counter_id="sim-pilot-counter",
                site_zone="sim-pilot-site-zone",
                credential_profile="METRIKA_PILOT_WRITE",
                payload=legacy_goal_candidate(candidate),
            ),
        )
        self.store.register_reservation(reservation)
        self.store.register_authority(authority)
        created = self.lifecycle.create_candidate(
            run_id=run_id,
            proposal_id=proposal_id,
            reservation_id=reservation.reservation_id,
            authority_id=authority.authority_id,
            counter_id="sim-pilot-counter",
            credential_profile="METRIKA_PILOT_WRITE",
            payload=legacy_goal_candidate(candidate),
            now=NOW,
        )
        return created.candidate_id

    def _invoke(
        self,
        command: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = goal_request(command)
        request["idempotency_key"] = idempotency_key
        return self.adapter.handle(request).body

    def test_customer_creates_a_candidate_through_the_headless_contract(
        self,
    ) -> None:
        result = self._create_candidate()

        self.assertEqual("SUCCEEDED", result["status"])
        self.assertEqual(
            {
                "action": "CREATE_CANDIDATE",
                "lifecycle_status": "CANDIDATE",
                "candidate_id": "candidate-goal-run-1",
                "goal_id": "goal-1",
                "candidate_status": "CANDIDATE",
                "technical_status": "PENDING",
                "optimization_eligible": False,
                "cleaned_up": False,
                "event_evidence": None,
                "evidence_digest": result["lifecycle_outcome"]["evidence_digest"],
            },
            result["lifecycle_outcome"],
        )
        self.assertRegex(
            result["lifecycle_outcome"]["evidence_digest"],
            r"^[0-9a-f]{64}$",
        )
        self.assertEqual(1, self.goal_adapter.add_calls)
        self.assertRegex(
            result["decision_record_ref"],
            r"^decision-records/[0-9a-f]{64}\.json$",
        )
        record = self.module.decision_records.read(result["decision_record_ref"])
        self.assertEqual(
            result["lifecycle_outcome"],
            record["facts"]["lifecycle_outcome"],
        )

    def test_approved_test_scenario_proves_exactly_one_reach_goal_event(
        self,
    ) -> None:
        created = self._create_candidate()
        candidate_id = created["lifecycle_outcome"]["candidate_id"]
        published = self._publish_candidate(candidate_id)
        self.assertEqual(
            "EVENT_PUBLISHED",
            published["lifecycle_outcome"]["lifecycle_status"],
        )
        candidate = self.store.load_candidate(candidate_id)
        recorder = ReadOnlyEgressRecorder(self.policy)
        browser_evidence = exercise_goal_event(
            counter_id=candidate.counter_id,
            event=candidate.event,
            trigger_selector="#lead-submit",
            configured_selector=candidate.site_location,
            egress=recorder,
        )
        self.assertEqual(1, browser_evidence.emitted_count)
        self.assertEqual(1, len(recorder.browser_interceptions))
        self.assertEqual(0, browser_evidence.real_network_requests)
        self.goal_adapter.set_visit_observations(
            candidate.counter_id,
            candidate.goal_id,
            ("PENDING", "DELIVERED"),
        )
        verified = self._invoke(
            {
                "schema_version": "goal-lifecycle-command-v1",
                "action": "VERIFY_DELIVERY",
                "candidate_id": candidate_id,
                "event_evidence": {
                    "event": browser_evidence.event,
                    "selector": browser_evidence.selector,
                    "trigger_selector": browser_evidence.trigger_selector,
                    "counter_id": browser_evidence.counter_id,
                    "http_method": browser_evidence.http_method,
                    "request_url": browser_evidence.request_url,
                    "emitted_count": browser_evidence.emitted_count,
                    "intercepted_locally": browser_evidence.intercepted_locally,
                    "real_network_requests": (browser_evidence.real_network_requests),
                },
            },
            "verify-goal-run-1",
        )
        outcome = verified["lifecycle_outcome"]
        self.assertEqual("TECHNICALLY_VERIFIED", outcome["lifecycle_status"])
        self.assertEqual(1, outcome["event_evidence"]["emitted_count"])
        self.assertTrue(outcome["event_evidence"]["duplicate_event_absent"])
        self.assertEqual(2, outcome["event_evidence"]["poll_count"])
        approved = self._invoke(
            {
                "schema_version": "goal-lifecycle-command-v1",
                "action": "DECIDE_BUSINESS_SEMANTICS",
                "candidate_id": candidate_id,
                "approved": True,
                "reviewer": "sviridov",
            },
            "approve-goal-run-1",
        )
        self.assertEqual(
            "APPROVED",
            approved["lifecycle_outcome"]["candidate_status"],
        )
        eligible = self._invoke(
            {
                "schema_version": "goal-lifecycle-command-v1",
                "action": "EVALUATE_OPTIMIZATION_ELIGIBILITY",
                "candidate_id": candidate_id,
                "observed_at": (NOW + timedelta(hours=72)).isoformat(),
                "sample_clicks": 50,
                "sample_conversions": 3,
            },
            "evaluate-goal-run-1",
        )
        self.assertEqual(
            "OPTIMIZATION_ELIGIBLE",
            eligible["lifecycle_outcome"]["lifecycle_status"],
        )
        self.assertTrue(eligible["lifecycle_outcome"]["optimization_eligible"])
        parsed = ModuleResultV1.from_dict(verified)
        tampered = parsed.as_dict()
        tampered["lifecycle_outcome"]["event_evidence"]["emitted_count"] = 2
        with self.assertRaisesRegex(
            ContractValidationError,
            "evidence digest",
        ):
            ModuleResultV1.from_dict(tampered)

    def test_human_rejection_and_cleanup_preserve_historical_goals(
        self,
    ) -> None:
        created = self._create_candidate(
            run_id="goal-run-rejected",
            proposal_id="goal-proposal-rejected",
            event="form_started",
        )
        candidate_id = created["lifecycle_outcome"]["candidate_id"]
        self._publish_candidate(candidate_id)
        rejected = self._invoke(
            {
                "schema_version": "goal-lifecycle-command-v1",
                "action": "DECIDE_BUSINESS_SEMANTICS",
                "candidate_id": candidate_id,
                "approved": False,
                "reviewer": "sviridov",
            },
            "reject-goal-run-rejected",
        )
        self.assertEqual(
            "REJECTED",
            rejected["lifecycle_outcome"]["candidate_status"],
        )
        self.assertFalse(rejected["lifecycle_outcome"]["optimization_eligible"])
        self.goal_adapter.seed_existing_goal(
            "sim-test-counter",
            {
                "goal_id": "historical-goal",
                "name": "Historical purchase",
                "event": "purchase",
                "type": "ACTION",
            },
        )
        cleaned = self._invoke(
            {
                "schema_version": "goal-lifecycle-command-v1",
                "action": "CLEANUP_REJECTED_CANDIDATE",
                "candidate_id": candidate_id,
                "run_id": "goal-run-rejected",
            },
            "cleanup-goal-run-rejected",
        )
        self.assertEqual(
            "CLEANED_UP",
            cleaned["lifecycle_outcome"]["lifecycle_status"],
        )
        self.assertTrue(cleaned["lifecycle_outcome"]["cleaned_up"])
        self.assertEqual(
            "historical-goal",
            self.goal_adapter.get_goal(
                "sim-test-counter",
                "historical-goal",
            )["goal_id"],
        )

    def test_production_is_blocked_before_stored_connection_resolution(
        self,
    ) -> None:
        class RecordingProvider:
            def __init__(self) -> None:
                self.calls = 0

            def manage_goal_candidate(self, *args: object) -> object:
                self.calls += 1
                raise AssertionError("production resolved a test connection")

        provider = RecordingProvider()
        module = MetrikaModuleV1(
            goal_lifecycle_provider=provider,
            clock=lambda: NOW,
        )
        adapter = HttpJsonModuleAdapterV1.for_embedded(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        )
        request = goal_request(
            {
                "schema_version": "goal-lifecycle-command-v1",
                "action": "CREATE_CANDIDATE",
                "run_id": "blocked-run",
                "proposal_id": "blocked-proposal",
                "reservation_id": "blocked-reservation",
                "authority_id": "blocked-authority",
                "candidate": goal_candidate(),
            }
        )
        request["environment"] = "PRODUCTION"

        response = adapter.handle(request)

        self.assertEqual(422, response.status_code)
        self.assertEqual("BLOCKED", response.body["status"])
        self.assertEqual(
            "PRODUCTION_WRITE_FORBIDDEN",
            response.body["errors"][0]["code"],
        )
        self.assertEqual(0, provider.calls)

    def test_contract_and_stored_connection_reject_untrusted_scope_before_write(
        self,
    ) -> None:
        command: dict[str, Any] = {
            "schema_version": "goal-lifecycle-command-v1",
            "action": "CREATE_CANDIDATE",
            "run_id": "untrusted-run",
            "proposal_id": "untrusted-proposal",
            "reservation_id": "untrusted-reservation",
            "authority_id": "untrusted-authority",
            "candidate": goal_candidate(),
        }
        arbitrary_payload = dict(command)
        arbitrary_payload["yandex_http_payload"] = {
            "method": "POST",
            "url": "https://api-metrika.yandex.net/management/v1/counter/other/goals",
        }
        rejected_contract = self.adapter.handle(goal_request(arbitrary_payload))
        self.assertEqual(400, rejected_contract.status_code)
        self.assertEqual(0, self.goal_adapter.add_calls)
        wrong_scope = goal_request(command)
        wrong_scope["scope"]["counter_id"] = "other-counter"

        rejected_scope = self.adapter.handle(wrong_scope)

        self.assertEqual(422, rejected_scope.status_code)
        self.assertEqual(
            "METRIKA_GOAL_SCOPE_REJECTED",
            rejected_scope.body["errors"][0]["code"],
        )
        self.assertEqual(0, self.goal_adapter.add_calls)

    def test_non_create_action_cannot_cross_the_bound_candidate_counter(
        self,
    ) -> None:
        candidate_id = self._seed_pilot_candidate()

        result = self._invoke(
            {
                "schema_version": "goal-lifecycle-command-v1",
                "action": "DECIDE_BUSINESS_SEMANTICS",
                "candidate_id": candidate_id,
                "approved": False,
                "reviewer": "sviridov",
            },
            "cross-counter-decision",
        )

        self.assertEqual("REJECTED", result["status"])
        self.assertEqual(
            "METRIKA_GOAL_SCOPE_REJECTED",
            result["errors"][0]["code"],
        )
        self.assertEqual(
            "CANDIDATE",
            self.store.load_candidate(candidate_id).status.value,
        )

    def test_trusted_composition_requires_test_counter_and_write_profile(
        self,
    ) -> None:
        for counter_id, credential_profile in (
            ("sim-pilot-counter", "METRIKA_TEST_WRITE"),
            ("sim-test-counter", "METRIKA_PILOT_WRITE"),
        ):
            with (
                self.subTest(
                    counter_id=counter_id,
                    credential_profile=credential_profile,
                ),
                self.assertRaises(MetrikaGoalLifecycleAuthorizationError),
            ):
                BoundMetrikaGoalLifecycleProviderV1(
                    connection_id="invalid-binding",
                    counter_id=counter_id,
                    credential_profile=credential_profile,
                    lifecycle=self.lifecycle,
                )

    def test_missing_or_malformed_typed_command_is_a_contract_rejection(
        self,
    ) -> None:
        valid = goal_request(
            {
                "schema_version": "goal-lifecycle-command-v1",
                "action": "CREATE_CANDIDATE",
                "run_id": "valid-run",
                "proposal_id": "valid-proposal",
                "reservation_id": "valid-reservation",
                "authority_id": "valid-authority",
                "candidate": goal_candidate(),
            }
        )
        missing = dict(valid)
        missing.pop("goal_lifecycle_command")
        missing_response = self.adapter.handle(missing)
        malformed = goal_request(
            {
                "schema_version": "goal-lifecycle-command-v1",
                "action": "CLEANUP_REJECTED_CANDIDATE",
                "candidate_id": "../pilot-candidate",
                "run_id": "valid-run",
            }
        )
        malformed_response = self.adapter.handle(malformed)

        for response in (missing_response, malformed_response):
            self.assertEqual(400, response.status_code)
            self.assertEqual("REJECTED", response.body["status"])
            self.assertEqual(
                "CONTRACT_VALIDATION_FAILED",
                response.body["errors"][0]["code"],
            )


if __name__ == "__main__":
    unittest.main()
