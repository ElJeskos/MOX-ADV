from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mox_adv.control_state import AuthenticatedPrincipal
from mox_adv.goal_lifecycle import (
    AuthorityKind,
    CreationReservation,
    FakeMetrikaGoalAdapter,
    FakeSitePublishAdapter,
    GoalAuthority,
    GoalExecutionStatus,
    GoalLifecycleService,
    GoalLifecycleStore,
    goal_creation_binding,
    site_publish_binding,
    site_publish_diff,
)
from mox_adv.environment import ExecutionEnvironment

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc)


def load_policy() -> dict:
    return json.loads((ROOT / "config" / "gate0-policy.json").read_text())


def payload(
    event: str = "lead_submitted",
    name: str = "Submitted lead",
) -> dict:
    return {
        "schema_version": "goal-candidate-v1",
        "name": name,
        "event": event,
        "site_location": "#lead-form",
        "type": "ACTION",
        "business_meaning": "A visitor completed the selected action.",
        "priority": 1,
        "duplicate_signals": [],
    }


class FakeSemanticAuthenticator:
    def authenticate(self) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            identity="sviridov",
            authentication="authenticated_macos_user",
        )


class FailingFinalizeStore(GoalLifecycleStore):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.fail_goal_finalize_once = True

    def complete_goal_creation(self, *args, **kwargs):
        if self.fail_goal_finalize_once:
            self.fail_goal_finalize_once = False
            raise sqlite3.OperationalError("Injected persistence failure.")
        return super().complete_goal_creation(*args, **kwargs)


class FailingSiteFinalizeStore(GoalLifecycleStore):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.fail_site_finalize_once = True

    def complete_site_publication(self, *args, **kwargs):
        if self.fail_site_finalize_once:
            self.fail_site_finalize_once = False
            raise sqlite3.OperationalError("Injected site persistence failure.")
        return super().complete_site_publication(*args, **kwargs)


class GoalLifecycleSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_policy()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = Path(self.temporary_directory.name) / "goals.sqlite3"

    def service(
        self,
        store: GoalLifecycleStore,
        goal_adapter: FakeMetrikaGoalAdapter,
        site_adapter: FakeSitePublishAdapter | None = None,
    ) -> GoalLifecycleService:
        return GoalLifecycleService(
            self.policy,
            store,
            goal_adapter,
            site_adapter
            or FakeSitePublishAdapter(
                {
                    "sim-test-site-zone": "test-page-v1",
                    "sim-pilot-site-zone": "pilot-page-v1",
                }
            ),
            FakeSemanticAuthenticator(),
            environment=ExecutionEnvironment.TEST,
        )

    def register_creation(
        self,
        store: GoalLifecycleStore,
        *,
        run_id: str,
        proposal_id: str,
        reservation_id: str,
        authority_id: str,
        authority_kind: AuthorityKind,
        goal_payload: dict,
    ) -> None:
        reservation = CreationReservation(
            reservation_id=reservation_id,
            scope_binding="test_counter",
            object_type="METRIKA_GOAL",
            proposal_id=proposal_id,
            credential_profile="METRIKA_TEST_WRITE",
            expires_at=NOW + timedelta(minutes=15),
        )
        binding_hash = goal_creation_binding(
            policy_id=self.policy["policy_id"],
            run_id=run_id,
            candidate_id="candidate-" + run_id,
            proposal_id=proposal_id,
            reservation_id=reservation_id,
            counter_id="sim-test-counter",
            site_zone="sim-test-site-zone",
            credential_profile="METRIKA_TEST_WRITE",
            payload=goal_payload,
        )
        authority = GoalAuthority(
            authority_id=authority_id,
            kind=authority_kind,
            principal="sviridov",
            authentication="authenticated_macos_user",
            proposal_id=proposal_id,
            counter_id="sim-test-counter",
            site_zone="sim-test-site-zone",
            allowed_actions=("GOAL_AUTHORING",),
            expires_at=NOW + timedelta(hours=1),
            policy_id=self.policy["policy_id"],
            binding_hash=binding_hash,
        )
        store.register_reservation(reservation)
        store.register_authority(authority)

    def create(
        self,
        service: GoalLifecycleService,
        *,
        run_id: str,
        proposal_id: str,
        reservation_id: str,
        authority_id: str,
        goal_payload: dict,
    ):
        return service.create_candidate(
            run_id=run_id,
            proposal_id=proposal_id,
            reservation_id=reservation_id,
            authority_id=authority_id,
            counter_id="sim-test-counter",
            credential_profile="METRIKA_TEST_WRITE",
            payload=goal_payload,
            now=NOW,
        )

    def register_site_approval(
        self,
        store: GoalLifecycleStore,
        candidate,
        expected_version: str = "test-page-v1",
        authority_id: str = "site-approval",
    ) -> GoalAuthority:
        authority = GoalAuthority(
            authority_id=authority_id,
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
                    expected_version,
                ),
            ),
        )
        store.register_authority(authority)
        return authority

    def test_concurrent_reuse_of_one_approval_produces_one_adapter_write(self) -> None:
        store = GoalLifecycleStore(self.database)
        adapter = FakeMetrikaGoalAdapter(
            ("sim-test-counter", "sim-pilot-counter"),
            write_delay_seconds=0.05,
        )
        service = self.service(store, adapter)
        self.register_creation(
            store,
            run_id="approval-race",
            proposal_id="proposal-race",
            reservation_id="reservation-race",
            authority_id="approval-race",
            authority_kind=AuthorityKind.APPROVAL,
            goal_payload=payload(),
        )
        barrier = threading.Barrier(2)

        def attempt():
            barrier.wait()
            return self.create(
                service,
                run_id="approval-race",
                proposal_id="proposal-race",
                reservation_id="reservation-race",
                authority_id="approval-race",
                goal_payload=payload(),
            )

        results = []
        errors = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt) for _ in range(2)]
            for future in futures:
                try:
                    results.append(future.result())
                except RuntimeError as error:
                    errors.append(str(error))

        self.assertEqual(1, adapter.add_calls)
        self.assertTrue(results)
        self.assertTrue(all(item.goal_id == "goal-1" for item in results))
        self.assertTrue(all(error == "UNKNOWN_RESULT" for error in errors))
        self.assertEqual("USED", store.authority_status("approval-race"))
        self.assertEqual(
            GoalExecutionStatus.APPLIED,
            store.load_execution("goal-create:candidate-approval-race").status,
        )

    def test_in_flight_reservation_and_authority_are_durable_before_write(
        self,
    ) -> None:
        store = GoalLifecycleStore(self.database)
        saw_reserved_boundary = []

        def inspect_boundary(execution_key: str) -> None:
            saw_reserved_boundary.append(
                store.load_execution(execution_key).status
                == GoalExecutionStatus.IN_FLIGHT
                and store.reservation_status("reservation-inspection") == "RESERVED"
                and store.authority_status("approval-inspection") == "RESERVED"
            )

        adapter = FakeMetrikaGoalAdapter(
            ("sim-test-counter", "sim-pilot-counter"),
            before_add_goal=inspect_boundary,
        )
        service = self.service(store, adapter)
        self.register_creation(
            store,
            run_id="inspection",
            proposal_id="proposal-inspection",
            reservation_id="reservation-inspection",
            authority_id="approval-inspection",
            authority_kind=AuthorityKind.APPROVAL,
            goal_payload=payload(),
        )

        self.create(
            service,
            run_id="inspection",
            proposal_id="proposal-inspection",
            reservation_id="reservation-inspection",
            authority_id="approval-inspection",
            goal_payload=payload(),
        )

        self.assertEqual([True], saw_reserved_boundary)
        self.assertEqual("USED", store.reservation_status("reservation-inspection"))
        self.assertEqual("USED", store.authority_status("approval-inspection"))

    def test_mandate_cannot_authorize_a_different_candidate_payload(self) -> None:
        store = GoalLifecycleStore(self.database)
        adapter = FakeMetrikaGoalAdapter(
            ("sim-test-counter", "sim-pilot-counter")
        )
        service = self.service(store, adapter)
        self.register_creation(
            store,
            run_id="mandate-binding",
            proposal_id="proposal-mandate-binding",
            reservation_id="reservation-mandate-binding",
            authority_id="mandate-binding",
            authority_kind=AuthorityKind.MANDATE,
            goal_payload=payload(),
        )

        with self.assertRaisesRegex(RuntimeError, "AUTHORITY_INVALID"):
            self.create(
                service,
                run_id="mandate-binding",
                proposal_id="proposal-mandate-binding",
                reservation_id="reservation-mandate-binding",
                authority_id="mandate-binding",
                goal_payload=payload(
                    event="form_started",
                    name="Started form",
                ),
            )

        self.assertEqual(0, adapter.add_calls)
        self.assertEqual("ACTIVE", store.authority_status("mandate-binding"))
        self.assertEqual(
            "AVAILABLE",
            store.reservation_status("reservation-mandate-binding"),
        )

    def test_concurrent_duplicate_signatures_are_claimed_before_write(self) -> None:
        store = GoalLifecycleStore(self.database)
        adapter = FakeMetrikaGoalAdapter(
            ("sim-test-counter", "sim-pilot-counter"),
            write_delay_seconds=0.05,
        )
        service = self.service(store, adapter)
        for suffix in ("a", "b"):
            goal_payload = payload(name="Submitted lead " + suffix)
            self.register_creation(
                store,
                run_id="duplicate-" + suffix,
                proposal_id="proposal-" + suffix,
                reservation_id="reservation-" + suffix,
                authority_id="mandate-" + suffix,
                authority_kind=AuthorityKind.MANDATE,
                goal_payload=goal_payload,
            )
        barrier = threading.Barrier(2)

        def attempt(suffix: str):
            barrier.wait()
            return self.create(
                service,
                run_id="duplicate-" + suffix,
                proposal_id="proposal-" + suffix,
                reservation_id="reservation-" + suffix,
                authority_id="mandate-" + suffix,
                goal_payload=payload(name="Submitted lead " + suffix),
            )

        results = []
        errors = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt, suffix) for suffix in ("a", "b")]
            for future in futures:
                try:
                    results.append(future.result())
                except RuntimeError as error:
                    errors.append(str(error))

        self.assertEqual(1, adapter.add_calls)
        self.assertEqual(1, len(results))
        self.assertEqual(["DUPLICATE_GOAL_CANDIDATE"], errors)

    def test_persistence_failure_reconciles_created_goal_without_second_write(
        self,
    ) -> None:
        store = FailingFinalizeStore(self.database)
        adapter = FakeMetrikaGoalAdapter(("sim-test-counter", "sim-pilot-counter"))
        service = self.service(store, adapter)
        self.register_creation(
            store,
            run_id="persistence-window",
            proposal_id="proposal-persistence",
            reservation_id="reservation-persistence",
            authority_id="mandate-persistence",
            authority_kind=AuthorityKind.MANDATE,
            goal_payload=payload(),
        )

        with self.assertRaises(sqlite3.OperationalError):
            self.create(
                service,
                run_id="persistence-window",
                proposal_id="proposal-persistence",
                reservation_id="reservation-persistence",
                authority_id="mandate-persistence",
                goal_payload=payload(),
            )

        self.assertEqual(1, adapter.add_calls)
        self.assertEqual(
            GoalExecutionStatus.IN_FLIGHT,
            store.load_execution("goal-create:candidate-persistence-window").status,
        )

        reconciled = self.create(
            service,
            run_id="persistence-window",
            proposal_id="proposal-persistence",
            reservation_id="reservation-persistence",
            authority_id="mandate-persistence",
            goal_payload=payload(),
        )

        self.assertEqual("goal-1", reconciled.goal_id)
        self.assertEqual(1, adapter.add_calls)
        self.assertEqual(
            GoalExecutionStatus.APPLIED,
            store.load_execution("goal-create:candidate-persistence-window").status,
        )

    def test_timeout_after_goal_write_reconciles_without_blind_retry(self) -> None:
        store = GoalLifecycleStore(self.database)
        adapter = FakeMetrikaGoalAdapter(
            ("sim-test-counter", "sim-pilot-counter"),
            timeout_after_write=True,
        )
        service = self.service(store, adapter)
        self.register_creation(
            store,
            run_id="timeout-window",
            proposal_id="proposal-timeout",
            reservation_id="reservation-timeout",
            authority_id="mandate-timeout",
            authority_kind=AuthorityKind.MANDATE,
            goal_payload=payload(),
        )

        candidate = self.create(
            service,
            run_id="timeout-window",
            proposal_id="proposal-timeout",
            reservation_id="reservation-timeout",
            authority_id="mandate-timeout",
            goal_payload=payload(),
        )

        self.assertEqual("goal-1", candidate.goal_id)
        self.assertEqual(1, adapter.add_calls)
        self.assertEqual(
            GoalExecutionStatus.APPLIED,
            store.load_execution("goal-create:candidate-timeout-window").status,
        )

    def test_site_persistence_failure_reconciles_without_second_publish(self) -> None:
        store = FailingSiteFinalizeStore(self.database)
        goal_adapter = FakeMetrikaGoalAdapter(("sim-test-counter", "sim-pilot-counter"))
        site_adapter = FakeSitePublishAdapter(
            {
                "sim-test-site-zone": "test-page-v1",
                "sim-pilot-site-zone": "pilot-page-v1",
            }
        )
        service = self.service(store, goal_adapter, site_adapter)
        self.register_creation(
            store,
            run_id="site-persistence",
            proposal_id="proposal-site-persistence",
            reservation_id="reservation-site-persistence",
            authority_id="mandate-site-persistence",
            authority_kind=AuthorityKind.MANDATE,
            goal_payload=payload(),
        )
        candidate = self.create(
            service,
            run_id="site-persistence",
            proposal_id="proposal-site-persistence",
            reservation_id="reservation-site-persistence",
            authority_id="mandate-site-persistence",
            goal_payload=payload(),
        )
        authority = self.register_site_approval(store, candidate)

        with self.assertRaises(sqlite3.OperationalError):
            service.publish_candidate_event(
                candidate.candidate_id,
                authority_id=authority.authority_id,
                site_zone="sim-test-site-zone",
                expected_version="test-page-v1",
                now=NOW,
            )

        self.assertEqual(1, site_adapter.publish_calls)
        self.assertEqual(
            GoalExecutionStatus.IN_FLIGHT,
            store.load_execution("site-publish:" + candidate.candidate_id).status,
        )

        publication = service.publish_candidate_event(
            candidate.candidate_id,
            authority_id=authority.authority_id,
            site_zone="sim-test-site-zone",
            expected_version="test-page-v1",
            now=NOW,
        )

        self.assertEqual(1, site_adapter.publish_calls)
        self.assertEqual(
            "INSTALL_REACH_GOAL",
            publication.exact_diff["operation"],
        )
        self.assertEqual("USED", store.authority_status(authority.authority_id))

    def test_site_timeout_after_write_reconciles_without_blind_retry(self) -> None:
        store = GoalLifecycleStore(self.database)
        goal_adapter = FakeMetrikaGoalAdapter(("sim-test-counter", "sim-pilot-counter"))
        site_adapter = FakeSitePublishAdapter(
            {
                "sim-test-site-zone": "test-page-v1",
                "sim-pilot-site-zone": "pilot-page-v1",
            },
            timeout_after_write=True,
        )
        service = self.service(store, goal_adapter, site_adapter)
        self.register_creation(
            store,
            run_id="site-timeout",
            proposal_id="proposal-site-timeout",
            reservation_id="reservation-site-timeout",
            authority_id="mandate-site-timeout",
            authority_kind=AuthorityKind.MANDATE,
            goal_payload=payload(),
        )
        candidate = self.create(
            service,
            run_id="site-timeout",
            proposal_id="proposal-site-timeout",
            reservation_id="reservation-site-timeout",
            authority_id="mandate-site-timeout",
            goal_payload=payload(),
        )
        authority = self.register_site_approval(store, candidate)

        publication = service.publish_candidate_event(
            candidate.candidate_id,
            authority_id=authority.authority_id,
            site_zone="sim-test-site-zone",
            expected_version="test-page-v1",
            now=NOW,
        )

        self.assertEqual("test-page-v1+site-timeout", publication.published_version)
        self.assertEqual(1, site_adapter.publish_calls)
        self.assertEqual(
            GoalExecutionStatus.APPLIED,
            store.load_execution("site-publish:" + candidate.candidate_id).status,
        )

    def test_site_approval_cannot_cross_candidate_or_page_version_binding(self) -> None:
        store = GoalLifecycleStore(self.database)
        goal_adapter = FakeMetrikaGoalAdapter(("sim-test-counter", "sim-pilot-counter"))
        site_adapter = FakeSitePublishAdapter(
            {
                "sim-test-site-zone": "test-page-v2",
                "sim-pilot-site-zone": "pilot-page-v1",
            }
        )
        service = self.service(store, goal_adapter, site_adapter)
        candidates = []
        for suffix, event, name in (
            ("one", "lead_submitted", "Submitted lead"),
            ("two", "form_started", "Started lead form"),
        ):
            goal_payload = payload(event, name)
            self.register_creation(
                store,
                run_id="candidate-" + suffix,
                proposal_id="proposal-shared",
                reservation_id="reservation-" + suffix,
                authority_id="mandate-" + suffix,
                authority_kind=AuthorityKind.MANDATE,
                goal_payload=goal_payload,
            )
            candidates.append(
                self.create(
                    service,
                    run_id="candidate-" + suffix,
                    proposal_id="proposal-shared",
                    reservation_id="reservation-" + suffix,
                    authority_id="mandate-" + suffix,
                    goal_payload=goal_payload,
                )
            )
        first = candidates[0]
        authority = GoalAuthority(
            authority_id="site-binding-approval",
            kind=AuthorityKind.APPROVAL,
            principal="sviridov",
            authentication="authenticated_macos_user",
            proposal_id=first.proposal_id,
            counter_id=first.counter_id,
            site_zone="sim-test-site-zone",
            allowed_actions=("SITE_PUBLISH",),
            expires_at=NOW + timedelta(minutes=15),
            policy_id=self.policy["policy_id"],
            binding_hash=site_publish_binding(
                policy_id=self.policy["policy_id"],
                candidate=first,
                exact_diff=site_publish_diff(
                    first,
                    "sim-test-site-zone",
                    "test-page-v1",
                ),
            ),
        )
        store.register_authority(authority)

        with self.assertRaisesRegex(RuntimeError, "AUTHORITY_INVALID"):
            service.publish_candidate_event(
                candidates[1].candidate_id,
                authority_id=authority.authority_id,
                site_zone="sim-test-site-zone",
                expected_version="test-page-v2",
                now=NOW,
            )
        with self.assertRaisesRegex(RuntimeError, "AUTHORITY_INVALID"):
            service.publish_candidate_event(
                first.candidate_id,
                authority_id=authority.authority_id,
                site_zone="sim-test-site-zone",
                expected_version="test-page-v2",
                now=NOW,
            )
        with self.assertRaisesRegex(RuntimeError, "SITE_VERSION_MISMATCH"):
            service.publish_candidate_event(
                first.candidate_id,
                authority_id=authority.authority_id,
                site_zone="sim-test-site-zone",
                expected_version="test-page-v1",
                now=NOW,
            )

        self.assertEqual(0, site_adapter.publish_calls)
        self.assertEqual("AVAILABLE", store.authority_status(authority.authority_id))


if __name__ == "__main__":
    unittest.main()
