"""Target-bound candidate-goal lifecycle for the controlled prototype."""

# ruff: noqa: UP045

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class GoalLifecycleRejected(RuntimeError):
    """A goal lifecycle request failed a deterministic boundary."""


class AuthorityKind(str, Enum):
    APPROVAL = "APPROVAL"
    MANDATE = "MANDATE"


class GoalCandidateStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class GoalTechnicalStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class CreationReservation:
    reservation_id: str
    scope_binding: str
    object_type: str
    proposal_id: str
    credential_profile: str
    expires_at: datetime


@dataclass(frozen=True)
class GoalAuthority:
    authority_id: str
    kind: AuthorityKind
    principal: str
    authentication: str
    proposal_id: str
    counter_id: str
    site_zone: str
    allowed_actions: tuple[str, ...]
    expires_at: datetime


@dataclass(frozen=True)
class GoalCandidateRecord:
    candidate_id: str
    run_id: str
    proposal_id: str
    counter_id: str
    goal_id: str
    name: str
    event: str
    site_location: str
    goal_type: str
    business_meaning: str
    priority: int
    status: GoalCandidateStatus
    technical_status: GoalTechnicalStatus
    semantic_reviewer: Optional[str] = None

    @property
    def optimization_eligible(self) -> bool:
        return (
            self.status == GoalCandidateStatus.APPROVED
            and self.technical_status == GoalTechnicalStatus.VERIFIED
        )


@dataclass(frozen=True)
class GoalEventEvidence:
    event: str
    selector: str
    emitted_count: int
    intercepted_locally: bool
    real_network_requests: int


@dataclass(frozen=True)
class GoalTechnicalEvidence:
    candidate_id: str
    counter_id: str
    goal_id: str
    goal_type: str
    site_zone: str
    event: str
    selector: str
    classification: str
    emitted_count: int
    duplicate_event_absent: bool
    intercepted_locally: bool
    real_network_requests: int
    delivery_observed: bool
    status: GoalTechnicalStatus
    virtual_elapsed_minutes: int
    poll_count: int
    external_reason: Optional[str]
    checked_at: str
    author: str
    configuration_version: str


@dataclass(frozen=True)
class SitePublication:
    candidate_id: str
    run_id: str
    site_zone: str
    event: str
    selector: str
    previous_version: str
    published_version: str
    author: str


class FakeMetrikaGoalAdapter:
    """In-memory Metrica goal adapter with no transport or URL dependency."""

    is_fake = True

    def __init__(self, allowed_counter_ids: Iterable[str]) -> None:
        self.allowed_counter_ids = frozenset(allowed_counter_ids)
        self._goals: dict[str, dict[str, dict[str, Any]]] = {
            counter_id: {} for counter_id in self.allowed_counter_ids
        }
        self._visit_observations: dict[tuple[str, str], tuple[str, ...]] = {}
        self._visit_poll_counts: dict[tuple[str, str], int] = {}
        self.add_calls = 0
        self.delete_calls = 0

    def list_goals(self, counter_id: str) -> tuple[Mapping[str, Any], ...]:
        self._require_counter(counter_id)
        return tuple(dict(item) for item in self._goals[counter_id].values())

    def seed_existing_goal(
        self,
        counter_id: str,
        goal: Mapping[str, Any],
    ) -> None:
        self._require_counter(counter_id)
        goal_id = str(goal.get("goal_id", ""))
        if not goal_id or goal_id in self._goals[counter_id]:
            raise GoalLifecycleRejected("EXISTING_GOAL_INVALID")
        self._goals[counter_id][goal_id] = dict(goal)

    def add_goal(
        self,
        counter_id: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._require_counter(counter_id)
        self.add_calls += 1
        goal_id = "goal-" + str(self.add_calls)
        goal = dict(payload)
        goal["goal_id"] = goal_id
        self._goals[counter_id][goal_id] = goal
        return dict(goal)

    def get_goal(self, counter_id: str, goal_id: str) -> Mapping[str, Any]:
        self._require_counter(counter_id)
        try:
            return dict(self._goals[counter_id][goal_id])
        except KeyError as error:
            raise GoalLifecycleRejected("GOAL_NOT_FOUND") from error

    def delete_goal(self, counter_id: str, goal_id: str) -> None:
        self._require_counter(counter_id)
        if goal_id not in self._goals[counter_id]:
            raise GoalLifecycleRejected("GOAL_NOT_FOUND")
        self.delete_calls += 1
        del self._goals[counter_id][goal_id]

    def set_visit_observations(
        self,
        counter_id: str,
        goal_id: str,
        observations: Sequence[str],
    ) -> None:
        self.get_goal(counter_id, goal_id)
        allowed = {"PENDING", "DELIVERED", "EXTERNAL_DELAY", "UNAVAILABLE"}
        values = tuple(str(item) for item in observations)
        if not values or any(item not in allowed for item in values):
            raise GoalLifecycleRejected("VISIT_OBSERVATIONS_INVALID")
        key = (counter_id, goal_id)
        self._visit_observations[key] = values
        self._visit_poll_counts[key] = 0

    def poll_goal_visit(self, counter_id: str, goal_id: str) -> str:
        self.get_goal(counter_id, goal_id)
        key = (counter_id, goal_id)
        observations = self._visit_observations.get(key, ("PENDING",))
        index = self._visit_poll_counts.get(key, 0)
        self._visit_poll_counts[key] = index + 1
        return observations[min(index, len(observations) - 1)]

    def visit_poll_count(self, counter_id: str, goal_id: str) -> int:
        return self._visit_poll_counts.get((counter_id, goal_id), 0)

    def _require_counter(self, counter_id: str) -> None:
        if counter_id not in self.allowed_counter_ids:
            raise GoalLifecycleRejected("COUNTER_NOT_ALLOWLISTED")


class FakeSitePublishAdapter:
    """In-memory site publisher constrained to configured page zones."""

    is_fake = True

    def __init__(self, zone_versions: Mapping[str, str]) -> None:
        self._versions = dict(zone_versions)
        self._publications: dict[str, SitePublication] = {}
        self.publish_calls = 0
        self.rollback_calls = 0

    def publish_event(
        self,
        candidate_id: str,
        run_id: str,
        site_zone: str,
        expected_version: str,
        event: str,
        selector: str,
        author: str,
    ) -> SitePublication:
        if site_zone not in self._versions:
            raise GoalLifecycleRejected("SITE_ZONE_NOT_ALLOWLISTED")
        if self._versions[site_zone] != expected_version:
            raise GoalLifecycleRejected("SITE_VERSION_MISMATCH")
        published_version = expected_version + "+" + run_id
        publication = SitePublication(
            candidate_id=candidate_id,
            run_id=run_id,
            site_zone=site_zone,
            event=event,
            selector=selector,
            previous_version=expected_version,
            published_version=published_version,
            author=author,
        )
        self.publish_calls += 1
        self._versions[site_zone] = published_version
        self._publications[candidate_id] = publication
        return publication

    def rollback_publication(
        self,
        publication: SitePublication,
        run_id: str,
    ) -> None:
        current = self._publications.get(publication.candidate_id)
        if (
            current != publication
            or publication.run_id != run_id
            or self._versions.get(publication.site_zone)
            != publication.published_version
        ):
            raise GoalLifecycleRejected("SITE_ROLLBACK_PRECONDITION_FAILED")
        self._versions[publication.site_zone] = publication.previous_version
        del self._publications[publication.candidate_id]
        self.rollback_calls += 1


class GoalLifecycleStore:
    """SQLite state for goal authorities, reservations, and candidates."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=1)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS goal_creation_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    scope_binding TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    proposal_id TEXT NOT NULL,
                    credential_profile TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_by_run TEXT
                );
                CREATE TABLE IF NOT EXISTS goal_authorities (
                    authority_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    principal TEXT NOT NULL,
                    authentication TEXT NOT NULL,
                    proposal_id TEXT NOT NULL,
                    counter_id TEXT NOT NULL,
                    site_zone TEXT NOT NULL,
                    allowed_actions TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS goal_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    proposal_id TEXT NOT NULL,
                    counter_id TEXT NOT NULL,
                    goal_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    event TEXT NOT NULL,
                    site_location TEXT NOT NULL,
                    goal_type TEXT NOT NULL,
                    business_meaning TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    technical_status TEXT NOT NULL,
                    semantic_reviewer TEXT,
                    UNIQUE(counter_id, goal_id)
                );
                CREATE TABLE IF NOT EXISTS goal_site_publications (
                    candidate_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    site_zone TEXT NOT NULL,
                    event TEXT NOT NULL,
                    selector TEXT NOT NULL,
                    previous_version TEXT NOT NULL,
                    published_version TEXT NOT NULL,
                    author TEXT NOT NULL
                );
                """
            )

    def register_reservation(self, reservation: CreationReservation) -> None:
        if reservation.expires_at.tzinfo is None:
            raise GoalLifecycleRejected("CREATION_RESERVATION_INVALID")
        values = (
            "AVAILABLE",
            reservation.scope_binding,
            reservation.object_type,
            reservation.proposal_id,
            reservation.credential_profile,
            _utc_text(reservation.expires_at),
        )
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT status, scope_binding, object_type, proposal_id, "
                "credential_profile, expires_at FROM goal_creation_reservations "
                "WHERE reservation_id = ?",
                (reservation.reservation_id,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != values:
                    raise GoalLifecycleRejected("IMMUTABLE_RESERVATION_CONFLICT")
                return
            connection.execute(
                "INSERT INTO goal_creation_reservations "
                "(reservation_id, status, scope_binding, object_type, proposal_id, "
                "credential_profile, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (reservation.reservation_id,) + values,
            )

    def register_authority(self, authority: GoalAuthority) -> None:
        if authority.expires_at.tzinfo is None:
            raise GoalLifecycleRejected("AUTHORITY_INVALID")
        actions = ",".join(sorted(set(authority.allowed_actions)))
        status = (
            "AVAILABLE"
            if AuthorityKind(authority.kind) == AuthorityKind.APPROVAL
            else "ACTIVE"
        )
        values = (
            AuthorityKind(authority.kind).value,
            status,
            authority.principal,
            authority.authentication,
            authority.proposal_id,
            authority.counter_id,
            authority.site_zone,
            actions,
            _utc_text(authority.expires_at),
        )
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT kind, status, principal, authentication, proposal_id, counter_id, "
                "site_zone, allowed_actions, expires_at FROM goal_authorities "
                "WHERE authority_id = ?",
                (authority.authority_id,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != values:
                    raise GoalLifecycleRejected("IMMUTABLE_AUTHORITY_CONFLICT")
                return
            connection.execute(
                "INSERT INTO goal_authorities "
                "(authority_id, kind, status, principal, authentication, proposal_id, "
                "counter_id, site_zone, allowed_actions, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (authority.authority_id,) + values,
            )

    def reserve_creation(
        self,
        reservation_id: str,
        run_id: str,
        proposal_id: str,
        scope_binding: str,
        credential_profile: str,
        now: datetime,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM goal_creation_reservations WHERE reservation_id = ?",
                (reservation_id,),
            ).fetchone()
            if (
                row is None
                or row["status"] != "AVAILABLE"
                or row["scope_binding"] != scope_binding
                or row["object_type"] != "METRIKA_GOAL"
                or row["proposal_id"] != proposal_id
                or row["credential_profile"] != credential_profile
                or row["expires_at"] <= _utc_text(now)
            ):
                raise GoalLifecycleRejected("CREATION_RESERVATION_INVALID")
            connection.execute(
                "UPDATE goal_creation_reservations SET status = 'USED', "
                "used_by_run = ? WHERE reservation_id = ?",
                (run_id, reservation_id),
            )

    def require_authority(
        self,
        authority_id: str,
        proposal_id: str,
        counter_id: str,
        action: str,
        expected_approval_principal: Mapping[str, str],
        expected_mandate_principal: Mapping[str, str],
        now: datetime,
        site_zone: Optional[str] = None,
        required_kind: Optional[AuthorityKind] = None,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM goal_authorities WHERE authority_id = ?",
                (authority_id,),
            ).fetchone()
        expected_principal = (
            expected_approval_principal
            if row is not None and row["kind"] == AuthorityKind.APPROVAL.value
            else expected_mandate_principal
        )
        if (
            row is None
            or row["proposal_id"] != proposal_id
            or row["counter_id"] != counter_id
            or (site_zone is not None and row["site_zone"] != site_zone)
            or (
                required_kind is not None
                and row["kind"] != AuthorityKind(required_kind).value
            )
            or (
                row["kind"] == AuthorityKind.APPROVAL.value
                and row["status"] != "AVAILABLE"
            )
            or (
                row["kind"] == AuthorityKind.MANDATE.value and row["status"] != "ACTIVE"
            )
            or row["principal"] != expected_principal["identity"]
            or row["authentication"] != expected_principal["authentication"]
            or action not in row["allowed_actions"].split(",")
            or row["expires_at"] <= _utc_text(now)
        ):
            raise GoalLifecycleRejected("AUTHORITY_INVALID")

    def consume_authority(self, authority_id: str) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT kind, status FROM goal_authorities WHERE authority_id = ?",
                (authority_id,),
            ).fetchone()
            if row is None:
                raise GoalLifecycleRejected("AUTHORITY_INVALID")
            if row["kind"] == AuthorityKind.MANDATE.value:
                if row["status"] != "ACTIVE":
                    raise GoalLifecycleRejected("AUTHORITY_INVALID")
                return
            updated = connection.execute(
                "UPDATE goal_authorities SET status = 'USED' "
                "WHERE authority_id = ? AND kind = 'APPROVAL' "
                "AND status = 'AVAILABLE'",
                (authority_id,),
            )
            if updated.rowcount != 1:
                raise GoalLifecycleRejected("AUTHORITY_INVALID")

    def authority_status(self, authority_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM goal_authorities WHERE authority_id = ?",
                (authority_id,),
            ).fetchone()
        if row is None:
            raise GoalLifecycleRejected("AUTHORITY_INVALID")
        return str(row["status"])

    def save_candidate(self, record: GoalCandidateRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO goal_candidates "
                "(candidate_id, run_id, proposal_id, counter_id, goal_id, name, "
                "event, site_location, goal_type, business_meaning, priority, status, "
                "technical_status, semantic_reviewer) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.candidate_id,
                    record.run_id,
                    record.proposal_id,
                    record.counter_id,
                    record.goal_id,
                    record.name,
                    record.event,
                    record.site_location,
                    record.goal_type,
                    record.business_meaning,
                    record.priority,
                    record.status.value,
                    record.technical_status.value,
                    record.semantic_reviewer,
                ),
            )

    def load_candidate(self, candidate_id: str) -> GoalCandidateRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM goal_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise GoalLifecycleRejected("GOAL_CANDIDATE_NOT_FOUND")
        return GoalCandidateRecord(
            candidate_id=row["candidate_id"],
            run_id=row["run_id"],
            proposal_id=row["proposal_id"],
            counter_id=row["counter_id"],
            goal_id=row["goal_id"],
            name=row["name"],
            event=row["event"],
            site_location=row["site_location"],
            goal_type=row["goal_type"],
            business_meaning=row["business_meaning"],
            priority=int(row["priority"]),
            status=GoalCandidateStatus(row["status"]),
            technical_status=GoalTechnicalStatus(row["technical_status"]),
            semantic_reviewer=row["semantic_reviewer"],
        )

    def save_publication(self, publication: SitePublication) -> None:
        with self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO goal_site_publications "
                    "(candidate_id, run_id, site_zone, event, selector, "
                    "previous_version, published_version, author) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        publication.candidate_id,
                        publication.run_id,
                        publication.site_zone,
                        publication.event,
                        publication.selector,
                        publication.previous_version,
                        publication.published_version,
                        publication.author,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise GoalLifecycleRejected("SITE_EVENT_ALREADY_PUBLISHED") from error

    def load_publication(self, candidate_id: str) -> SitePublication:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM goal_site_publications WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise GoalLifecycleRejected("SITE_EVENT_NOT_PUBLISHED")
        return SitePublication(
            candidate_id=row["candidate_id"],
            run_id=row["run_id"],
            site_zone=row["site_zone"],
            event=row["event"],
            selector=row["selector"],
            previous_version=row["previous_version"],
            published_version=row["published_version"],
            author=row["author"],
        )

    def set_technical_status(
        self,
        candidate_id: str,
        status: GoalTechnicalStatus,
    ) -> GoalCandidateRecord:
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE goal_candidates SET technical_status = ? "
                "WHERE candidate_id = ? AND status = 'CANDIDATE'",
                (GoalTechnicalStatus(status).value, candidate_id),
            )
            if updated.rowcount != 1:
                raise GoalLifecycleRejected("GOAL_CANDIDATE_NOT_VERIFIABLE")
        return self.load_candidate(candidate_id)

    def set_semantic_status(
        self,
        candidate_id: str,
        status: GoalCandidateStatus,
        reviewer: str,
    ) -> GoalCandidateRecord:
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE goal_candidates SET status = ?, semantic_reviewer = ? "
                "WHERE candidate_id = ? AND status = 'CANDIDATE'",
                (GoalCandidateStatus(status).value, reviewer, candidate_id),
            )
            if updated.rowcount != 1:
                raise GoalLifecycleRejected("SEMANTIC_DECISION_NOT_ALLOWED")
        return self.load_candidate(candidate_id)

    def reservation_status(self, reservation_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM goal_creation_reservations "
                "WHERE reservation_id = ?",
                (reservation_id,),
            ).fetchone()
        if row is None:
            raise GoalLifecycleRejected("CREATION_RESERVATION_NOT_FOUND")
        return str(row["status"])


class GoalLifecycleService:
    """Create candidate goals through exact fake-adapter trust boundaries."""

    def __init__(
        self,
        policy: Mapping[str, Any],
        store: GoalLifecycleStore,
        goal_adapter: FakeMetrikaGoalAdapter,
        site_adapter: FakeSitePublishAdapter,
    ) -> None:
        if not goal_adapter.is_fake or not site_adapter.is_fake:
            raise GoalLifecycleRejected("FAKE_ADAPTER_REQUIRED")
        self.policy = policy
        self.store = store
        self.goal_adapter = goal_adapter
        self.site_adapter = site_adapter

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
        normalized = _validate_candidate(payload, self.policy)
        scope_binding = self._counter_scope(counter_id)
        existing_goals = self.goal_adapter.list_goals(counter_id)
        normalized_name = str(normalized["name"]).strip().casefold()
        normalized_event = str(normalized["event"]).strip().casefold()
        duplicate = bool(normalized["duplicate_signals"]) or any(
            str(item.get("name", "")).strip().casefold() == normalized_name
            or str(item.get("event", "")).strip().casefold() == normalized_event
            for item in existing_goals
        )
        if duplicate:
            raise GoalLifecycleRejected("DUPLICATE_GOAL_CANDIDATE")
        self.store.require_authority(
            authority_id,
            proposal_id,
            counter_id,
            "GOAL_AUTHORING",
            self.policy["principals"]["approver"],
            self.policy["principals"]["mandate_issuer"],
            now,
        )
        self.store.reserve_creation(
            reservation_id,
            run_id,
            proposal_id,
            scope_binding,
            credential_profile,
            now,
        )
        goal = self.goal_adapter.add_goal(counter_id, normalized)
        self.store.consume_authority(authority_id)
        record = GoalCandidateRecord(
            candidate_id="candidate-" + run_id,
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
        )
        self.store.save_candidate(record)
        return record

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
        self.store.require_authority(
            authority_id,
            candidate.proposal_id,
            candidate.counter_id,
            "SITE_PUBLISH",
            self.policy["principals"]["approver"],
            self.policy["principals"]["mandate_issuer"],
            now,
            site_zone=site_zone,
            required_kind=AuthorityKind.APPROVAL,
        )
        publication = self.site_adapter.publish_event(
            candidate_id=candidate.candidate_id,
            run_id=candidate.run_id,
            site_zone=site_zone,
            expected_version=expected_version,
            event=candidate.event,
            selector=candidate.site_location,
            author=str(self.policy["principals"]["approver"]["identity"]),
        )
        self.store.consume_authority(authority_id)
        self.store.save_publication(publication)
        return publication

    def verify_candidate_delivery(
        self,
        candidate_id: str,
        event_evidence: GoalEventEvidence,
        now: datetime,
    ) -> GoalTechnicalEvidence:
        candidate = self.store.load_candidate(candidate_id)
        publication = self.store.load_publication(candidate_id)
        if (
            event_evidence.event != candidate.event
            or event_evidence.selector != candidate.site_location
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
        external_reason: Optional[str] = None
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
                return GoalTechnicalEvidence(
                    candidate_id=candidate.candidate_id,
                    counter_id=candidate.counter_id,
                    goal_id=candidate.goal_id,
                    goal_type=candidate.goal_type,
                    site_zone=publication.site_zone,
                    event=candidate.event,
                    selector=candidate.site_location,
                    classification=self._event_classification(candidate.event),
                    emitted_count=event_evidence.emitted_count,
                    duplicate_event_absent=event_evidence.emitted_count == 1,
                    intercepted_locally=event_evidence.intercepted_locally,
                    real_network_requests=event_evidence.real_network_requests,
                    delivery_observed=True,
                    status=GoalTechnicalStatus.VERIFIED,
                    virtual_elapsed_minutes=elapsed,
                    poll_count=(
                        self.goal_adapter.visit_poll_count(
                            candidate.counter_id,
                            candidate.goal_id,
                        )
                    ),
                    external_reason=None,
                    checked_at=_utc_text(now),
                    author=publication.author,
                    configuration_version=publication.published_version,
                )
            if observation in {"EXTERNAL_DELAY", "UNAVAILABLE"}:
                external_reason = observation
        if external_reason is None:
            raise GoalLifecycleRejected("METRIKA_DELIVERY_NOT_EVIDENCED")
        self.store.set_technical_status(
            candidate_id,
            GoalTechnicalStatus.INCONCLUSIVE,
        )
        return GoalTechnicalEvidence(
            candidate_id=candidate.candidate_id,
            counter_id=candidate.counter_id,
            goal_id=candidate.goal_id,
            goal_type=candidate.goal_type,
            site_zone=publication.site_zone,
            event=candidate.event,
            selector=candidate.site_location,
            classification=self._event_classification(candidate.event),
            emitted_count=event_evidence.emitted_count,
            duplicate_event_absent=event_evidence.emitted_count == 1,
            intercepted_locally=event_evidence.intercepted_locally,
            real_network_requests=event_evidence.real_network_requests,
            delivery_observed=False,
            status=GoalTechnicalStatus.INCONCLUSIVE,
            virtual_elapsed_minutes=timeout_minutes,
            poll_count=self.goal_adapter.visit_poll_count(
                candidate.counter_id,
                candidate.goal_id,
            ),
            external_reason=external_reason,
            checked_at=_utc_text(now),
            author=publication.author,
            configuration_version=publication.published_version,
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
        product_signoff = self.policy["principals"]["product_signoff"]["identity"]
        if not reviewer or reviewer != product_signoff:
            raise GoalLifecycleRejected("SEMANTIC_REVIEWER_INVALID")
        if approved and candidate.technical_status != GoalTechnicalStatus.VERIFIED:
            raise GoalLifecycleRejected("TECHNICAL_VERIFICATION_REQUIRED")
        status = (
            GoalCandidateStatus.APPROVED if approved else GoalCandidateStatus.REJECTED
        )
        return self.store.set_semantic_status(candidate_id, status, reviewer)

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
        publication = self.store.load_publication(candidate_id)
        self.site_adapter.rollback_publication(publication, run_id)
        self.goal_adapter.delete_goal(candidate.counter_id, candidate.goal_id)

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


def _validate_candidate(
    payload: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    required = {
        "schema_version",
        "name",
        "event",
        "site_location",
        "type",
        "business_meaning",
        "priority",
        "duplicate_signals",
    }
    if set(payload) != required or payload.get("schema_version") != "goal-candidate-v1":
        raise GoalLifecycleRejected("GOAL_CANDIDATE_INVALID")
    allowed_events = {
        policy["conversion"]["primary"]["event"],
        *(item["event"] for item in policy["conversion"]["microconversions"]),
    }
    if payload.get("event") not in allowed_events:
        raise GoalLifecycleRejected("GOAL_EVENT_NOT_ALLOWLISTED")
    text_limits = {
        "name": 128,
        "event": 128,
        "site_location": 500,
        "type": 64,
        "business_meaning": 500,
    }
    if any(
        not isinstance(payload.get(field), str)
        or not 1 <= len(payload[field]) <= maximum
        for field, maximum in text_limits.items()
    ):
        raise GoalLifecycleRejected("GOAL_CANDIDATE_INVALID")
    duplicate_signals = payload.get("duplicate_signals")
    if (
        isinstance(payload.get("priority"), bool)
        or not isinstance(payload.get("priority"), int)
        or payload["priority"] < 1
        or not isinstance(duplicate_signals, list)
        or len(duplicate_signals) > 128
        or any(
            not isinstance(item, str) or not 1 <= len(item) <= 500
            for item in duplicate_signals
        )
        or len(set(duplicate_signals)) != len(duplicate_signals)
    ):
        raise GoalLifecycleRejected("GOAL_CANDIDATE_INVALID")
    return dict(payload)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise GoalLifecycleRejected("TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(timezone.utc).isoformat()
