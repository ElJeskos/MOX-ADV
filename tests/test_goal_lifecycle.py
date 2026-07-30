from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mox_adv.control_state import AuthenticatedPrincipal, DurableControlState
from mox_adv.goal_lifecycle import (
    AuthorityKind,
    CreationReservation,
    FakeMetrikaGoalAdapter,
    FakeSitePublishAdapter,
    GoalAuthority,
    GoalCandidateStatus,
    GoalEventEvidence,
    GoalLifecycleService,
    GoalLifecycleStore,
    GoalTechnicalStatus,
    goal_creation_binding,
    site_publish_binding,
    site_publish_diff,
)
from mox_adv.lifecycle_authority import LifecycleAuthorityService
from mox_adv.mandate_signing import HMACMandateSigner

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc)


def load_policy() -> dict:
    return json.loads((ROOT / "config" / "gate0-policy.json").read_text())


def goal_payload(event: str = "lead_submitted") -> dict:
    return {
        "schema_version": "goal-candidate-v1",
        "name": "Submitted lead",
        "event": event,
        "site_location": "#lead-form",
        "type": "ACTION",
        "business_meaning": "A visitor submitted the lead form.",
        "priority": 1,
        "duplicate_signals": [],
    }


class FakeSemanticAuthenticator:
    def __init__(
        self,
        identity: str = "sviridov",
        authentication: str = "authenticated_macos_user",
    ) -> None:
        self.identity = identity
        self.authentication = authentication

    def authenticate(self) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            identity=self.identity,
            authentication=self.authentication,
        )


class GoalLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_policy()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.authority_service = LifecycleAuthorityService(
            self.policy,
            FakeSemanticAuthenticator(),
            HMACMandateSigner(b"goal-lifecycle-authority-tests"),
        )
        self.store = GoalLifecycleStore(
            Path(self.temporary_directory.name) / "goals.sqlite3",
            self.authority_service,
        )
        self.control_state = DurableControlState(
            Path(self.temporary_directory.name) / "control.sqlite3"
        )
        simulation = self.policy["bindings"]["simulation"]
        self.goal_adapter = FakeMetrikaGoalAdapter(
            (simulation["test_counter"], simulation["pilot_counter"])
        )
        self.site_adapter = FakeSitePublishAdapter(
            {
                simulation["test_site_zone"]: "test-page-v1",
                simulation["pilot_site_zone"]: "pilot-page-v1",
            }
        )
        self.service = GoalLifecycleService(
            self.policy,
            self.store,
            self.goal_adapter,
            self.site_adapter,
            FakeSemanticAuthenticator(),
            self.control_state,
        )

    def create_test_candidate(
        self,
        run_id: str = "goal-run-1",
        proposal_id: str = "goal-proposal-1",
    ):
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
                payload=goal_payload(),
            ),
        )
        self.store.register_reservation(reservation)
        self.store.register_authority(authority, NOW)
        return self.service.create_candidate(
            run_id=run_id,
            proposal_id=proposal_id,
            reservation_id=reservation.reservation_id,
            authority_id=authority.authority_id,
            counter_id="sim-test-counter",
            credential_profile="METRIKA_TEST_WRITE",
            payload=goal_payload(),
            now=NOW,
        )

    def publish_test_candidate(self):
        candidate = self.create_test_candidate()
        publish_authority = GoalAuthority(
            authority_id="site-publish-approval-1",
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
        self.store.register_authority(publish_authority, NOW)
        self.service.publish_candidate_event(
            candidate.candidate_id,
            authority_id=publish_authority.authority_id,
            site_zone="sim-test-site-zone",
            expected_version="test-page-v1",
            now=NOW,
        )
        return candidate

    def test_goal_authoring_mandate_creates_candidate_with_bound_reservation(
        self,
    ) -> None:
        reservation = CreationReservation(
            reservation_id="sim-test-goal-creation-reservation",
            scope_binding="test_counter",
            object_type="METRIKA_GOAL",
            proposal_id="goal-proposal-1",
            credential_profile="METRIKA_TEST_WRITE",
            expires_at=NOW + timedelta(minutes=15),
        )
        authority = GoalAuthority(
            authority_id="mandate-goal-authoring-1",
            kind=AuthorityKind.MANDATE,
            principal="sviridov",
            authentication="authenticated_macos_user",
            proposal_id="goal-proposal-1",
            counter_id="sim-test-counter",
            site_zone="sim-test-site-zone",
            allowed_actions=("GOAL_AUTHORING",),
            expires_at=NOW + timedelta(hours=1),
            policy_id=self.policy["policy_id"],
            binding_hash=goal_creation_binding(
                policy_id=self.policy["policy_id"],
                run_id="goal-run-1",
                candidate_id="candidate-goal-run-1",
                proposal_id="goal-proposal-1",
                reservation_id=reservation.reservation_id,
                counter_id="sim-test-counter",
                site_zone="sim-test-site-zone",
                credential_profile="METRIKA_TEST_WRITE",
                payload=goal_payload(),
            ),
        )
        self.store.register_reservation(reservation)
        self.store.register_authority(authority, NOW)

        candidate = self.service.create_candidate(
            run_id="goal-run-1",
            proposal_id="goal-proposal-1",
            reservation_id=reservation.reservation_id,
            authority_id=authority.authority_id,
            counter_id="sim-test-counter",
            credential_profile="METRIKA_TEST_WRITE",
            payload=goal_payload(),
            now=NOW,
        )

        self.assertEqual(GoalCandidateStatus.CANDIDATE, candidate.status)
        self.assertEqual(GoalTechnicalStatus.PENDING, candidate.technical_status)
        self.assertEqual("goal-1", candidate.goal_id)
        self.assertEqual(1, self.goal_adapter.add_calls)
        self.assertEqual(
            "USED", self.store.reservation_status(reservation.reservation_id)
        )
        self.assertEqual(
            "EXHAUSTED",
            self.store.authority_status(authority.authority_id),
        )

    def test_goal_authoring_approval_can_create_only_in_bound_pilot_counter(
        self,
    ) -> None:
        reservation = CreationReservation(
            reservation_id="sim-pilot-goal-creation-reservation",
            scope_binding="pilot_counter",
            object_type="METRIKA_GOAL",
            proposal_id="goal-proposal-pilot",
            credential_profile="METRIKA_PILOT_WRITE",
            expires_at=NOW + timedelta(minutes=15),
        )
        authority = GoalAuthority(
            authority_id="approval-goal-pilot",
            kind=AuthorityKind.APPROVAL,
            principal="sviridov",
            authentication="authenticated_macos_user",
            proposal_id="goal-proposal-pilot",
            counter_id="sim-pilot-counter",
            site_zone="sim-pilot-site-zone",
            allowed_actions=("GOAL_AUTHORING",),
            expires_at=NOW + timedelta(minutes=15),
            policy_id=self.policy["policy_id"],
            binding_hash=goal_creation_binding(
                policy_id=self.policy["policy_id"],
                run_id="goal-run-pilot",
                candidate_id="candidate-goal-run-pilot",
                proposal_id="goal-proposal-pilot",
                reservation_id=reservation.reservation_id,
                counter_id="sim-pilot-counter",
                site_zone="sim-pilot-site-zone",
                credential_profile="METRIKA_PILOT_WRITE",
                payload=goal_payload(event="form_started"),
            ),
        )
        self.store.register_reservation(reservation)
        self.store.register_authority(authority, NOW)

        candidate = self.service.create_candidate(
            run_id="goal-run-pilot",
            proposal_id="goal-proposal-pilot",
            reservation_id=reservation.reservation_id,
            authority_id=authority.authority_id,
            counter_id="sim-pilot-counter",
            credential_profile="METRIKA_PILOT_WRITE",
            payload=goal_payload(event="form_started"),
            now=NOW,
        )

        self.assertEqual("sim-pilot-counter", candidate.counter_id)
        self.assertEqual(GoalCandidateStatus.CANDIDATE, candidate.status)
        self.assertEqual("USED", self.store.authority_status(authority.authority_id))

    def test_duplicate_candidate_is_rejected_before_goal_adapter_write(self) -> None:
        self.goal_adapter.seed_existing_goal(
            "sim-test-counter",
            {
                "goal_id": "historical-goal",
                "name": "Submitted lead",
                "event": "lead_submitted",
                "type": "ACTION",
            },
        )
        reservation = CreationReservation(
            reservation_id="sim-test-goal-creation-reservation",
            scope_binding="test_counter",
            object_type="METRIKA_GOAL",
            proposal_id="goal-proposal-duplicate",
            credential_profile="METRIKA_TEST_WRITE",
            expires_at=NOW + timedelta(minutes=15),
        )
        authority = GoalAuthority(
            authority_id="approval-goal-authoring-1",
            kind=AuthorityKind.APPROVAL,
            principal="sviridov",
            authentication="authenticated_macos_user",
            proposal_id="goal-proposal-duplicate",
            counter_id="sim-test-counter",
            site_zone="sim-test-site-zone",
            allowed_actions=("GOAL_AUTHORING",),
            expires_at=NOW + timedelta(minutes=15),
            policy_id=self.policy["policy_id"],
            binding_hash=goal_creation_binding(
                policy_id=self.policy["policy_id"],
                run_id="goal-run-duplicate",
                candidate_id="candidate-goal-run-duplicate",
                proposal_id="goal-proposal-duplicate",
                reservation_id=reservation.reservation_id,
                counter_id="sim-test-counter",
                site_zone="sim-test-site-zone",
                credential_profile="METRIKA_TEST_WRITE",
                payload=goal_payload(),
            ),
        )
        self.store.register_reservation(reservation)
        self.store.register_authority(authority, NOW)

        with self.assertRaisesRegex(
            RuntimeError,
            "DUPLICATE_GOAL_CANDIDATE",
        ):
            self.service.create_candidate(
                run_id="goal-run-duplicate",
                proposal_id="goal-proposal-duplicate",
                reservation_id=reservation.reservation_id,
                authority_id=authority.authority_id,
                counter_id="sim-test-counter",
                credential_profile="METRIKA_TEST_WRITE",
                payload=goal_payload(),
                now=NOW,
            )

        self.assertEqual(0, self.goal_adapter.add_calls)
        self.assertEqual(
            "AVAILABLE",
            self.store.reservation_status(reservation.reservation_id),
        )

    def test_goal_candidate_contract_rejects_schema_violations_before_write(
        self,
    ) -> None:
        invalid_payloads = []
        duplicate_signals = goal_payload()
        duplicate_signals["duplicate_signals"] = ["same", "same"]
        invalid_payloads.append(duplicate_signals)
        overlong_name = goal_payload()
        overlong_name["name"] = "x" * 129
        invalid_payloads.append(overlong_name)
        unknown_field = goal_payload()
        unknown_field["unexpected"] = True
        invalid_payloads.append(unknown_field)

        for index, payload in enumerate(invalid_payloads):
            with (
                self.subTest(index=index),
                self.assertRaisesRegex(
                    RuntimeError,
                    "GOAL_CANDIDATE_INVALID",
                ),
            ):
                self.service.create_candidate(
                    run_id="invalid-" + str(index),
                    proposal_id="missing",
                    reservation_id="missing",
                    authority_id="missing",
                    counter_id="sim-test-counter",
                    credential_profile="METRIKA_TEST_WRITE",
                    payload=payload,
                    now=NOW,
                )

        self.assertEqual(0, self.goal_adapter.add_calls)

    def test_site_publish_uses_separate_approval_and_exact_page_version(self) -> None:
        candidate = self.create_test_candidate()
        publish_authority = GoalAuthority(
            authority_id="site-publish-approval-1",
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
        self.store.register_authority(publish_authority, NOW)

        publication = self.service.publish_candidate_event(
            candidate.candidate_id,
            authority_id=publish_authority.authority_id,
            site_zone="sim-test-site-zone",
            expected_version="test-page-v1",
            now=NOW,
        )

        self.assertEqual("lead_submitted", publication.event)
        self.assertEqual("#lead-form", publication.selector)
        self.assertEqual("test-page-v1+goal-run-1", publication.published_version)
        self.assertEqual("INSTALL_REACH_GOAL", publication.exact_diff["operation"])
        self.assertEqual(
            "test-page-v1",
            publication.exact_diff["before"]["page_version"],
        )
        self.assertEqual(1, self.site_adapter.publish_calls)

        repeated = self.service.publish_candidate_event(
            candidate.candidate_id,
            authority_id=publish_authority.authority_id,
            site_zone="sim-test-site-zone",
            expected_version="test-page-v1",
            now=NOW,
        )
        self.assertEqual(publication, repeated)
        self.assertEqual(1, self.site_adapter.publish_calls)

    def test_site_publish_cannot_cross_the_counter_site_zone_binding(self) -> None:
        candidate = self.create_test_candidate()
        publish_authority = GoalAuthority(
            authority_id="site-publish-wrong-zone",
            kind=AuthorityKind.APPROVAL,
            principal="sviridov",
            authentication="authenticated_macos_user",
            proposal_id=candidate.proposal_id,
            counter_id=candidate.counter_id,
            site_zone="sim-pilot-site-zone",
            allowed_actions=("SITE_PUBLISH",),
            expires_at=NOW + timedelta(minutes=15),
            policy_id=self.policy["policy_id"],
            binding_hash=site_publish_binding(
                policy_id=self.policy["policy_id"],
                candidate=candidate,
                exact_diff=site_publish_diff(
                    candidate,
                    "sim-pilot-site-zone",
                    "pilot-page-v1",
                ),
            ),
        )
        self.store.register_authority(publish_authority, NOW)

        with self.assertRaisesRegex(
            RuntimeError,
            "SITE_ZONE_NOT_BOUND_TO_COUNTER",
        ):
            self.service.publish_candidate_event(
                candidate.candidate_id,
                authority_id=publish_authority.authority_id,
                site_zone="sim-pilot-site-zone",
                expected_version="pilot-page-v1",
                now=NOW,
            )

        self.assertEqual(0, self.site_adapter.publish_calls)

    def test_technical_verification_does_not_approve_business_semantics(self) -> None:
        candidate = self.publish_test_candidate()
        self.goal_adapter.set_visit_observations(
            candidate.counter_id,
            candidate.goal_id,
            ("PENDING", "DELIVERED"),
        )

        evidence = self.service.verify_candidate_delivery(
            candidate.candidate_id,
            GoalEventEvidence(
                event="lead_submitted",
                selector="#lead-form",
                trigger_selector="#lead-submit",
                counter_id="sim-test-counter",
                http_method="POST",
                request_url=(
                    "https://mc.yandex.ru/watch/sim-test-counter?event=lead_submitted"
                ),
                emitted_count=1,
                intercepted_locally=True,
                real_network_requests=0,
            ),
            now=NOW,
        )

        self.assertEqual(GoalTechnicalStatus.VERIFIED, evidence.status)
        self.assertEqual(5, evidence.virtual_elapsed_minutes)
        technically_verified = self.store.load_candidate(candidate.candidate_id)
        self.assertEqual(GoalCandidateStatus.CANDIDATE, technically_verified.status)
        self.assertFalse(technically_verified.optimization_eligible)

        spoofed_service = GoalLifecycleService(
            self.policy,
            self.store,
            self.goal_adapter,
            self.site_adapter,
            FakeSemanticAuthenticator(authentication="caller_supplied_string"),
            self.control_state,
        )
        with self.assertRaisesRegex(RuntimeError, "SEMANTIC_REVIEWER_INVALID"):
            spoofed_service.decide_business_semantics(
                candidate.candidate_id,
                approved=True,
                reviewer="sviridov",
                now=NOW,
            )

        approved = self.service.decide_business_semantics(
            candidate.candidate_id,
            approved=True,
            reviewer="sviridov",
            now=NOW,
        )

        self.assertEqual(GoalCandidateStatus.APPROVED, approved.status)
        self.assertFalse(approved.optimization_eligible)

        learning = self.service.evaluate_optimization_eligibility(
            candidate.candidate_id,
            observed_at=NOW + timedelta(hours=71),
            sample_clicks=50,
            sample_conversions=3,
        )
        self.assertFalse(learning.optimization_eligible)
        insufficient_sample = self.service.evaluate_optimization_eligibility(
            candidate.candidate_id,
            observed_at=NOW + timedelta(hours=72),
            sample_clicks=49,
            sample_conversions=2,
        )
        self.assertFalse(insufficient_sample.optimization_eligible)
        eligible = self.service.evaluate_optimization_eligibility(
            candidate.candidate_id,
            observed_at=NOW + timedelta(hours=72),
            sample_clicks=50,
            sample_conversions=3,
        )
        self.assertTrue(eligible.optimization_eligible)

    def test_technical_verification_rejects_spoofed_event_binding(self) -> None:
        candidate = self.publish_test_candidate()
        valid = GoalEventEvidence(
            event="lead_submitted",
            selector="#lead-form",
            trigger_selector="#lead-submit",
            counter_id="sim-test-counter",
            http_method="POST",
            request_url=(
                "https://mc.yandex.ru/watch/sim-test-counter?event=lead_submitted"
            ),
            emitted_count=1,
            intercepted_locally=True,
            real_network_requests=0,
        )
        cases = (
            replace(valid, counter_id="other-counter"),
            replace(valid, http_method="GET"),
            replace(
                valid,
                request_url=(
                    "https://mc.yandex.ru/watch/other-counter?event=lead_submitted"
                ),
            ),
            replace(
                valid,
                request_url=("https://mc.yandex.ru/watch/sim-test-counter?event=other"),
            ),
            replace(
                valid,
                request_url=(
                    "https://mc.yandex.ru/watch/sim-test-counter"
                    "?event=lead_submitted&ignored="
                ),
            ),
        )

        for evidence in cases:
            with (
                self.subTest(evidence=evidence),
                self.assertRaisesRegex(
                    RuntimeError,
                    "GOAL_EVENT_EVIDENCE_INVALID",
                ),
            ):
                self.service.verify_candidate_delivery(
                    candidate.candidate_id,
                    evidence,
                    now=NOW,
                )

    def test_virtual_polling_is_inconclusive_only_with_external_evidence(self) -> None:
        candidate = self.publish_test_candidate()
        self.goal_adapter.set_visit_observations(
            candidate.counter_id,
            candidate.goal_id,
            ("EXTERNAL_DELAY",),
        )
        event_evidence = GoalEventEvidence(
            event="lead_submitted",
            selector="#lead-form",
            trigger_selector="#lead-submit",
            counter_id="sim-test-counter",
            http_method="POST",
            request_url=(
                "https://mc.yandex.ru/watch/sim-test-counter?event=lead_submitted"
            ),
            emitted_count=1,
            intercepted_locally=True,
            real_network_requests=0,
        )

        evidence = self.service.verify_candidate_delivery(
            candidate.candidate_id,
            event_evidence,
            now=NOW,
        )

        self.assertEqual(GoalTechnicalStatus.INCONCLUSIVE, evidence.status)
        self.assertEqual(120, evidence.virtual_elapsed_minutes)
        self.assertEqual(25, evidence.poll_count)
        self.assertEqual("EXTERNAL_DELAY", evidence.external_reason)
        with self.assertRaisesRegex(RuntimeError, "TECHNICAL_VERIFICATION_REQUIRED"):
            self.service.decide_business_semantics(
                candidate.candidate_id,
                approved=True,
                reviewer="sviridov",
                now=NOW,
            )

    def test_pending_polling_without_external_evidence_is_not_inconclusive(
        self,
    ) -> None:
        candidate = self.publish_test_candidate()
        self.goal_adapter.set_visit_observations(
            candidate.counter_id,
            candidate.goal_id,
            ("PENDING",),
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "METRIKA_DELIVERY_NOT_EVIDENCED",
        ):
            self.service.verify_candidate_delivery(
                candidate.candidate_id,
                GoalEventEvidence(
                    event="lead_submitted",
                    selector="#lead-form",
                    trigger_selector="#lead-submit",
                    counter_id="sim-test-counter",
                    http_method="POST",
                    request_url=(
                        "https://mc.yandex.ru/watch/sim-test-counter"
                        "?event=lead_submitted"
                    ),
                    emitted_count=1,
                    intercepted_locally=True,
                    real_network_requests=0,
                ),
                now=NOW,
            )
        self.assertEqual(
            GoalTechnicalStatus.PENDING,
            self.store.load_candidate(candidate.candidate_id).technical_status,
        )

    def test_rejected_candidate_cleanup_removes_only_current_run_objects(self) -> None:
        candidate = self.publish_test_candidate()
        self.service.decide_business_semantics(
            candidate.candidate_id,
            approved=False,
            reviewer="sviridov",
            now=NOW,
        )
        self.goal_adapter.seed_existing_goal(
            candidate.counter_id,
            {
                "goal_id": "historical-goal",
                "name": "Historical purchase",
                "event": "purchase",
                "type": "ACTION",
            },
        )

        with self.assertRaisesRegex(RuntimeError, "CLEANUP_RUN_MISMATCH"):
            self.service.cleanup_rejected_candidate(
                candidate.candidate_id,
                run_id="another-run",
            )
        self.assertEqual(0, self.goal_adapter.delete_calls)

        self.service.cleanup_rejected_candidate(
            candidate.candidate_id,
            run_id=candidate.run_id,
        )

        self.assertEqual(1, self.goal_adapter.delete_calls)
        self.assertEqual(
            "historical-goal",
            self.goal_adapter.get_goal(
                candidate.counter_id,
                "historical-goal",
            )["goal_id"],
        )
        self.assertEqual(1, self.site_adapter.rollback_calls)
        self.assertFalse(
            self.store.load_candidate(candidate.candidate_id).optimization_eligible
        )


if __name__ == "__main__":
    unittest.main()
