"""Candidate-goal orchestration over durable state and fake write adapters."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlparse

from mox_adv.application_control import ApplicationWriteBoundary
from mox_adv.audit import AuditWriteBlocked
from mox_adv.control_state import (
    ControlRejected,
    MacOSLocalPrincipalAuthenticator,
    TrustedScope,
)
from mox_adv.goal_adapters import (
    FakeAdapterTimeout,
    FakeMetrikaGoalAdapter,
    FakeSitePublishAdapter,
)
from mox_adv.goal_contracts import (
    GoalCandidateRecord,
    GoalCandidateStatus,
    GoalExecutionStatus,
    GoalLifecycleRejected,
    GoalTechnicalStatus,
    SitePublication,
    canonical_hash,
    goal_creation_binding,
    goal_creation_plan,
    goal_signature,
    site_publish_binding,
    site_publish_diff,
    site_publish_plan,
    utc_text,
    validate_candidate,
)
from mox_adv.goal_evidence import GoalEventEvidence, GoalTechnicalEvidence
from mox_adv.goal_store import GoalLifecycleStore


class GoalLifecycleService:
    """Execute one serialized candidate-goal lifecycle in fake/local mode."""

    def __init__(
        self,
        policy: Mapping[str, Any],
        store: GoalLifecycleStore,
        goal_adapter: FakeMetrikaGoalAdapter,
        site_adapter: FakeSitePublishAdapter,
        semantic_authenticator: Any = None,
        write_boundary: ApplicationWriteBoundary | None = None,
    ) -> None:
        if (
            type(goal_adapter) is not FakeMetrikaGoalAdapter
            or type(site_adapter) is not FakeSitePublishAdapter
        ):
            raise GoalLifecycleRejected("FAKE_ADAPTER_REQUIRED")
        if type(write_boundary) is not ApplicationWriteBoundary:
            raise GoalLifecycleRejected("DURABLE_DISPATCH_GUARD_REQUIRED")
        self.policy = policy
        self.store = store
        self.goal_adapter = goal_adapter
        self.site_adapter = site_adapter
        self.write_boundary = write_boundary
        self.semantic_authenticator = (
            MacOSLocalPrincipalAuthenticator(
                expected_identity=str(
                    policy["principals"]["product_signoff"]["identity"]
                )
            )
            if semantic_authenticator is None
            else semantic_authenticator
        )

    def create_candidate(
        self,
        run_id: str,
        proposal_id: str,
        reservation_id: str,
        authority_id: str,
        counter_id: str,
        credential_profile: str,
        payload: Mapping[str, Any],
        now: datetime,
    ) -> GoalCandidateRecord:
        normalized = validate_candidate(payload, self.policy)
        scope_binding = self._counter_scope(counter_id)
        site_zone = self._site_zone_for_counter(counter_id)
        signature = goal_signature(normalized)
        candidate_id = "candidate-" + run_id
        plan = goal_creation_plan(
            policy_id=str(self.policy["policy_id"]),
            run_id=run_id,
            candidate_id=candidate_id,
            proposal_id=proposal_id,
            reservation_id=reservation_id,
            counter_id=counter_id,
            site_zone=site_zone,
            credential_profile=credential_profile,
            payload=normalized,
        )
        binding_hash = goal_creation_binding(
            policy_id=str(self.policy["policy_id"]),
            run_id=run_id,
            candidate_id=candidate_id,
            proposal_id=proposal_id,
            reservation_id=reservation_id,
            counter_id=counter_id,
            site_zone=site_zone,
            credential_profile=credential_profile,
            payload=normalized,
        )
        execution_key = "goal-create:" + candidate_id
        begun = self.store.begin_goal_creation(
            execution_key=execution_key,
            run_id=run_id,
            candidate_id=candidate_id,
            proposal_id=proposal_id,
            counter_id=counter_id,
            site_zone=site_zone,
            reservation_id=reservation_id,
            scope_binding=scope_binding,
            credential_profile=credential_profile,
            authority_id=authority_id,
            authority_binding_hash=binding_hash,
            policy_id=str(self.policy["policy_id"]),
            signature=signature,
            plan_hash=canonical_hash(plan),
            expected_approval_principal=self.policy["principals"]["approver"],
            expected_mandate_principal=self.policy["principals"]["mandate_issuer"],
            now=now,
        )
        if begun.record.status == GoalExecutionStatus.APPLIED:
            return self.store.load_candidate(candidate_id)
        if not begun.newly_started:
            return self._reconcile_goal_creation(
                execution_key=execution_key,
                candidate_id=candidate_id,
                run_id=run_id,
                proposal_id=proposal_id,
                counter_id=counter_id,
                authority_id=authority_id,
                reservation_id=reservation_id,
                signature=signature,
                normalized=normalized,
                now=now,
            )
        try:
            self._reject_existing_duplicate(counter_id, normalized)
        except GoalLifecycleRejected:
            self.store.abort_before_write(
                execution_key,
                authority_id,
                reservation_id,
            )
            raise
        try:
            self._authorize_write(
                execution_key,
                "MetrikaGoals:add:" + counter_id,
                counter_id,
            )
            goal = self.goal_adapter.add_goal(
                counter_id,
                normalized,
                signature,
                execution_key,
            )
        except FakeAdapterTimeout:
            return self._reconcile_goal_creation(
                execution_key=execution_key,
                candidate_id=candidate_id,
                run_id=run_id,
                proposal_id=proposal_id,
                counter_id=counter_id,
                authority_id=authority_id,
                reservation_id=reservation_id,
                signature=signature,
                normalized=normalized,
                now=now,
            )
        except GoalLifecycleRejected:
            self.store.abort_before_write(
                execution_key,
                authority_id,
                reservation_id,
            )
            raise
        candidate = self._candidate_from_goal(
            candidate_id,
            run_id,
            proposal_id,
            counter_id,
            normalized,
            goal,
            now,
        )
        return self.store.complete_goal_creation(
            execution_key,
            candidate,
            authority_id,
            reservation_id,
            now,
        )

    def publish_candidate_event(
        self,
        candidate_id: str,
        authority_id: str,
        site_zone: str,
        expected_version: str,
        now: datetime,
    ) -> SitePublication:
        candidate = self.store.load_candidate(candidate_id)
        if site_zone != self._site_zone_for_counter(candidate.counter_id):
            raise GoalLifecycleRejected("SITE_ZONE_NOT_BOUND_TO_COUNTER")
        exact_diff = site_publish_diff(candidate, site_zone, expected_version)
        plan = site_publish_plan(
            policy_id=str(self.policy["policy_id"]),
            candidate=candidate,
            exact_diff=exact_diff,
        )
        binding_hash = site_publish_binding(
            policy_id=str(self.policy["policy_id"]),
            candidate=candidate,
            exact_diff=exact_diff,
        )
        execution_key = "site-publish:" + candidate.candidate_id
        begun = self.store.begin_site_publication(
            execution_key=execution_key,
            candidate=candidate,
            site_zone=site_zone,
            authority_id=authority_id,
            authority_binding_hash=binding_hash,
            policy_id=str(self.policy["policy_id"]),
            plan_hash=canonical_hash(plan),
            expected_approval_principal=self.policy["principals"]["approver"],
            expected_mandate_principal=self.policy["principals"]["mandate_issuer"],
            now=now,
        )
        if begun.record.status == GoalExecutionStatus.APPLIED:
            return self.store.load_publication(candidate_id)
        if not begun.newly_started:
            return self._reconcile_site_publication(
                execution_key,
                candidate,
                authority_id,
                now,
            )
        if self.site_adapter.current_version(site_zone) != expected_version:
            self.store.abort_before_write(execution_key, authority_id)
            raise GoalLifecycleRejected("SITE_VERSION_MISMATCH")
        author = self.store.reserved_authority_principal(
            authority_id,
            execution_key,
        )
        try:
            self._authorize_write(
                execution_key,
                "SitePublish:publish:" + candidate.candidate_id,
                candidate.counter_id,
            )
            publication = self.site_adapter.publish_event(
                candidate_id=candidate.candidate_id,
                run_id=candidate.run_id,
                site_zone=site_zone,
                expected_version=expected_version,
                event=candidate.event,
                selector=candidate.site_location,
                author=author,
                exact_diff=exact_diff,
            )
        except FakeAdapterTimeout:
            return self._reconcile_site_publication(
                execution_key,
                candidate,
                authority_id,
                now,
            )
        except GoalLifecycleRejected:
            self.store.abort_before_write(execution_key, authority_id)
            raise
        return self.store.complete_site_publication(
            execution_key,
            publication,
            authority_id,
            now,
        )

    def verify_candidate_delivery(
        self,
        candidate_id: str,
        event_evidence: GoalEventEvidence,
        now: datetime,
    ) -> GoalTechnicalEvidence:
        candidate = self.store.load_candidate(candidate_id)
        publication = self.store.load_publication(candidate_id)
        request_url = urlparse(event_evidence.request_url)
        if (
            event_evidence.event != candidate.event
            or event_evidence.selector != candidate.site_location
            or not event_evidence.trigger_selector
            or event_evidence.counter_id != candidate.counter_id
            or event_evidence.http_method != "POST"
            or request_url.scheme != "https"
            or request_url.hostname != "mc.yandex.ru"
            or request_url.port not in {None, 443}
            or request_url.path != "/watch/" + candidate.counter_id
            or request_url.query != urlencode({"event": candidate.event})
            or request_url.fragment
            or event_evidence.emitted_count != 1
            or not event_evidence.intercepted_locally
            or event_evidence.real_network_requests != 0
            or publication.event != candidate.event
            or publication.selector != candidate.site_location
        ):
            raise GoalLifecycleRejected("GOAL_EVENT_EVIDENCE_INVALID")
        poll_minutes = int(self.policy["timing"]["goal_verification_poll_minutes"])
        timeout_minutes = int(
            self.policy["timing"]["goal_verification_timeout_minutes"]
        )
        external_reason = None
        for elapsed in range(0, timeout_minutes + 1, poll_minutes):
            observation = self.goal_adapter.poll_goal_visit(
                candidate.counter_id,
                candidate.goal_id,
            )
            if observation == "DELIVERED":
                self.store.set_technical_status(
                    candidate_id,
                    GoalTechnicalStatus.VERIFIED,
                )
                return self._technical_evidence(
                    candidate,
                    publication,
                    event_evidence,
                    GoalTechnicalStatus.VERIFIED,
                    elapsed,
                    None,
                    now,
                )
            if observation in {"EXTERNAL_DELAY", "UNAVAILABLE"}:
                external_reason = observation
        if external_reason is None:
            raise GoalLifecycleRejected("METRIKA_DELIVERY_NOT_EVIDENCED")
        self.store.set_technical_status(
            candidate_id,
            GoalTechnicalStatus.INCONCLUSIVE,
        )
        return self._technical_evidence(
            candidate,
            publication,
            event_evidence,
            GoalTechnicalStatus.INCONCLUSIVE,
            timeout_minutes,
            external_reason,
            now,
        )

    def decide_business_semantics(
        self,
        candidate_id: str,
        approved: bool,
        reviewer: str,
        now: datetime,
    ) -> GoalCandidateRecord:
        del now
        candidate = self.store.load_candidate(candidate_id)
        expected = self.policy["principals"]["product_signoff"]
        try:
            principal = self.semantic_authenticator.authenticate()
        except ControlRejected as error:
            raise GoalLifecycleRejected("SEMANTIC_AUTHENTICATION_FAILED") from error
        if (
            not reviewer
            or reviewer != principal.identity
            or principal.identity != expected["identity"]
            or principal.authentication != expected["authentication"]
        ):
            raise GoalLifecycleRejected("SEMANTIC_REVIEWER_INVALID")
        if approved and candidate.technical_status != GoalTechnicalStatus.VERIFIED:
            raise GoalLifecycleRejected("TECHNICAL_VERIFICATION_REQUIRED")
        status = (
            GoalCandidateStatus.APPROVED if approved else GoalCandidateStatus.REJECTED
        )
        return self.store.set_semantic_status(candidate_id, status, reviewer)

    def evaluate_optimization_eligibility(
        self,
        candidate_id: str,
        observed_at: datetime,
        sample_clicks: int,
        sample_conversions: int,
    ) -> GoalCandidateRecord:
        candidate = self.store.load_candidate(candidate_id)
        if (
            observed_at.tzinfo is None
            or isinstance(sample_clicks, bool)
            or isinstance(sample_conversions, bool)
            or sample_clicks < 0
            or sample_conversions < 0
        ):
            raise GoalLifecycleRejected("OPTIMIZATION_SAMPLE_INVALID")
        required_age = int(self.policy["timing"]["observation_window_hours"])
        age_hours = (
            observed_at.astimezone(candidate.created_at.tzinfo) - candidate.created_at
        ).total_seconds() / 3600
        minimum = self.policy["mandate"]["minimum_sample"]
        passed = (
            age_hours >= required_age
            and sample_clicks >= int(minimum["clicks"])
            and sample_conversions >= int(minimum["conversions"])
        )
        return self.store.set_optimization_gate(candidate_id, passed)

    def cleanup_rejected_candidate(
        self,
        candidate_id: str,
        run_id: str,
    ) -> None:
        candidate = self.store.load_candidate(candidate_id)
        if candidate.run_id != run_id:
            raise GoalLifecycleRejected("CLEANUP_RUN_MISMATCH")
        if candidate.status != GoalCandidateStatus.REJECTED:
            raise GoalLifecycleRejected("ONLY_REJECTED_CANDIDATE_CAN_BE_CLEANED")
        publication_done, goal_done, completed = self.store.begin_cleanup(
            candidate_id
        )
        if completed:
            return
        if not publication_done:
            publication = self.store.load_publication_optional(candidate_id)
            if publication is not None:
                current = self.site_adapter.publication_for_candidate(candidate_id)
                if current is not None:
                    self._authorize_write(
                        "goal-cleanup:"
                        + candidate.candidate_id
                        + ":publication",
                        "SitePublish:rollback:" + candidate.candidate_id,
                        candidate.counter_id,
                    )
                    self.site_adapter.rollback_publication(publication, run_id)
                elif (
                    self.site_adapter.current_version(publication.site_zone)
                    != publication.previous_version
                ):
                    raise GoalLifecycleRejected(
                        "SITE_ROLLBACK_PRECONDITION_FAILED"
                    )
            self.store.mark_cleanup_publication_rolled_back(candidate_id)
        if not goal_done:
            if self.goal_adapter.goal_exists(
                candidate.counter_id,
                candidate.goal_id,
            ):
                self._authorize_write(
                    "goal-cleanup:" + candidate.candidate_id + ":goal",
                    "MetrikaGoals:delete:" + candidate.goal_id,
                    candidate.counter_id,
                )
                self.goal_adapter.delete_goal_if_present(
                    candidate.counter_id,
                    candidate.goal_id,
                )
            self.store.mark_cleanup_goal_deleted(candidate_id)
        self.store.finish_cleanup(
            candidate_id,
            "goal-create:" + candidate.candidate_id,
            datetime.now(timezone.utc),
        )

    def _authorize_write(
        self,
        execution_key: str,
        target_key: str,
        counter_id: str,
    ) -> None:
        simulation = self.policy["bindings"]["simulation"]
        try:
            self.write_boundary.authorize(
                execution_key,
                target_key,
                TrustedScope(
                    organization=str(simulation["organization"]),
                    connection=str(simulation["connection"]),
                    account=str(simulation["direct_account"]),
                    campaign="goal-lifecycle:" + counter_id,
                    writer=str(simulation["single_writer"]),
                ),
            )
        except AuditWriteBlocked as error:
            raise GoalLifecycleRejected("AUDIT_EVIDENCE_UNAVAILABLE") from error
        except ControlRejected as error:
            raise GoalLifecycleRejected(error.reason_code) from error

    def _reconcile_goal_creation(
        self,
        *,
        execution_key: str,
        candidate_id: str,
        run_id: str,
        proposal_id: str,
        counter_id: str,
        authority_id: str,
        reservation_id: str,
        signature: str,
        normalized: Mapping[str, Any],
        now: datetime,
    ) -> GoalCandidateRecord:
        matches = self.goal_adapter.find_goals_by_signature(counter_id, signature)
        if len(matches) != 1:
            self.store.mark_unknown(
                execution_key,
                "Goal readback did not identify exactly one created target.",
                now,
            )
            raise GoalLifecycleRejected("UNKNOWN_RESULT")
        candidate = self._candidate_from_goal(
            candidate_id,
            run_id,
            proposal_id,
            counter_id,
            normalized,
            matches[0],
            now,
        )
        return self.store.complete_goal_creation(
            execution_key,
            candidate,
            authority_id,
            reservation_id,
            now,
        )

    def _reconcile_site_publication(
        self,
        execution_key: str,
        candidate: GoalCandidateRecord,
        authority_id: str,
        now: datetime,
    ) -> SitePublication:
        publication = self.site_adapter.publication_for_candidate(
            candidate.candidate_id
        )
        if publication is None:
            self.store.mark_unknown(
                execution_key,
                "Site readback did not identify the published page version.",
                now,
            )
            raise GoalLifecycleRejected("UNKNOWN_RESULT")
        return self.store.complete_site_publication(
            execution_key,
            publication,
            authority_id,
            now,
        )

    @staticmethod
    def _candidate_from_goal(
        candidate_id: str,
        run_id: str,
        proposal_id: str,
        counter_id: str,
        normalized: Mapping[str, Any],
        goal: Mapping[str, Any],
        now: datetime,
    ) -> GoalCandidateRecord:
        return GoalCandidateRecord(
            candidate_id=candidate_id,
            run_id=run_id,
            proposal_id=proposal_id,
            counter_id=counter_id,
            goal_id=str(goal["goal_id"]),
            name=str(normalized["name"]),
            event=str(normalized["event"]),
            site_location=str(normalized["site_location"]),
            goal_type=str(normalized["type"]),
            business_meaning=str(normalized["business_meaning"]),
            priority=int(normalized["priority"]),
            status=GoalCandidateStatus.CANDIDATE,
            technical_status=GoalTechnicalStatus.PENDING,
            created_at=now,
        )

    def _technical_evidence(
        self,
        candidate: GoalCandidateRecord,
        publication: SitePublication,
        event_evidence: GoalEventEvidence,
        status: GoalTechnicalStatus,
        elapsed: int,
        external_reason: str | None,
        now: datetime,
    ) -> GoalTechnicalEvidence:
        return GoalTechnicalEvidence(
            candidate_id=candidate.candidate_id,
            counter_id=candidate.counter_id,
            goal_id=candidate.goal_id,
            goal_type=candidate.goal_type,
            site_zone=publication.site_zone,
            event=candidate.event,
            selector=candidate.site_location,
            trigger_selector=event_evidence.trigger_selector,
            http_method=event_evidence.http_method,
            request_url=event_evidence.request_url,
            classification=self._event_classification(candidate.event),
            emitted_count=event_evidence.emitted_count,
            duplicate_event_absent=event_evidence.emitted_count == 1,
            intercepted_locally=event_evidence.intercepted_locally,
            real_network_requests=event_evidence.real_network_requests,
            delivery_observed=status == GoalTechnicalStatus.VERIFIED,
            status=status,
            virtual_elapsed_minutes=elapsed,
            poll_count=self.goal_adapter.visit_poll_count(
                candidate.counter_id,
                candidate.goal_id,
            ),
            external_reason=external_reason,
            checked_at=utc_text(now),
            author=publication.author,
            configuration_version=publication.published_version,
        )

    def _reject_existing_duplicate(
        self,
        counter_id: str,
        normalized: Mapping[str, Any],
    ) -> None:
        event = str(normalized["event"]).strip().casefold()
        duplicate = bool(normalized["duplicate_signals"]) or any(
            str(item.get("event", "")).strip().casefold() == event
            for item in self.goal_adapter.list_goals(counter_id)
        )
        if duplicate:
            raise GoalLifecycleRejected("DUPLICATE_GOAL_CANDIDATE")

    def _counter_scope(self, counter_id: str) -> str:
        simulation = self.policy["bindings"]["simulation"]
        if counter_id == simulation["test_counter"]:
            return "test_counter"
        if counter_id == simulation["pilot_counter"]:
            return "pilot_counter"
        raise GoalLifecycleRejected("COUNTER_NOT_ALLOWLISTED")

    def _site_zone_for_counter(self, counter_id: str) -> str:
        simulation = self.policy["bindings"]["simulation"]
        if counter_id == simulation["test_counter"]:
            return str(simulation["test_site_zone"])
        if counter_id == simulation["pilot_counter"]:
            return str(simulation["pilot_site_zone"])
        raise GoalLifecycleRejected("COUNTER_NOT_ALLOWLISTED")

    def _event_classification(self, event: str) -> str:
        if event == self.policy["conversion"]["primary"]["event"]:
            return str(self.policy["conversion"]["primary"]["classification"])
        for item in self.policy["conversion"]["microconversions"]:
            if event == item["event"]:
                return str(item["classification"])
        raise GoalLifecycleRejected("GOAL_EVENT_NOT_ALLOWLISTED")
