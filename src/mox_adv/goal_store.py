"""Serialized durable state for candidate-goal lifecycle operations."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from mox_adv.goal_contracts import (
    AuthorityKind,
    BeginExecution,
    CreationReservation,
    GoalAuthority,
    GoalCandidateRecord,
    GoalCandidateStatus,
    GoalExecutionRecord,
    GoalExecutionStatus,
    GoalLifecycleRejected,
    GoalTechnicalStatus,
    SitePublication,
    canonical_json,
    parse_utc,
    utc_text,
)


class GoalLifecycleStore:
    """Own transactional reservations, execution state, and created targets."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=5)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

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
                    execution_key TEXT,
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
                    policy_id TEXT NOT NULL,
                    binding_hash TEXT NOT NULL,
                    action_quota INTEGER NOT NULL,
                    actions_used INTEGER NOT NULL DEFAULT 0,
                    expires_at TEXT NOT NULL,
                    execution_key TEXT
                );
                CREATE TABLE IF NOT EXISTS goal_executions (
                    execution_key TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    proposal_id TEXT NOT NULL,
                    counter_id TEXT NOT NULL,
                    plan_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    external_id TEXT,
                    detail TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS goal_signature_claims (
                    counter_id TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    execution_key TEXT NOT NULL UNIQUE,
                    PRIMARY KEY(counter_id, signature),
                    FOREIGN KEY(execution_key)
                        REFERENCES goal_executions(execution_key)
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
                    created_at TEXT NOT NULL,
                    optimization_gate_passed INTEGER NOT NULL DEFAULT 0,
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
                    author TEXT NOT NULL,
                    exact_diff_json TEXT NOT NULL
                );
                """
            )

    def register_reservation(self, reservation: CreationReservation) -> None:
        immutable = (
            reservation.scope_binding,
            reservation.object_type,
            reservation.proposal_id,
            reservation.credential_profile,
            utc_text(reservation.expires_at),
        )
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT scope_binding, object_type, proposal_id, "
                "credential_profile, expires_at FROM goal_creation_reservations "
                "WHERE reservation_id = ?",
                (reservation.reservation_id,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != immutable:
                    raise GoalLifecycleRejected("IMMUTABLE_RESERVATION_CONFLICT")
                return
            connection.execute(
                "INSERT INTO goal_creation_reservations "
                "(reservation_id, status, scope_binding, object_type, proposal_id, "
                "credential_profile, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (reservation.reservation_id, "AVAILABLE") + immutable,
            )

    def register_authority(self, authority: GoalAuthority) -> None:
        kind = AuthorityKind(authority.kind)
        if (
            not authority.policy_id
            or not authority.binding_hash
            or isinstance(authority.action_quota, bool)
            or authority.action_quota < 1
        ):
            raise GoalLifecycleRejected("AUTHORITY_INVALID")
        status = "AVAILABLE" if kind == AuthorityKind.APPROVAL else "ACTIVE"
        actions = ",".join(sorted(set(authority.allowed_actions)))
        values = (
            kind.value,
            authority.principal,
            authority.authentication,
            authority.proposal_id,
            authority.counter_id,
            authority.site_zone,
            actions,
            authority.policy_id,
            authority.binding_hash,
            authority.action_quota,
            utc_text(authority.expires_at),
        )
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT kind, principal, authentication, proposal_id, counter_id, "
                "site_zone, allowed_actions, policy_id, binding_hash, "
                "action_quota, expires_at "
                "FROM goal_authorities WHERE authority_id = ?",
                (authority.authority_id,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != values:
                    raise GoalLifecycleRejected("IMMUTABLE_AUTHORITY_CONFLICT")
                return
            connection.execute(
                "INSERT INTO goal_authorities "
                "(authority_id, kind, status, principal, authentication, proposal_id, "
                "counter_id, site_zone, allowed_actions, policy_id, binding_hash, "
                "action_quota, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (authority.authority_id, kind.value, status) + values[1:],
            )

    def begin_goal_creation(
        self,
        *,
        execution_key: str,
        run_id: str,
        candidate_id: str,
        proposal_id: str,
        counter_id: str,
        site_zone: str,
        reservation_id: str,
        scope_binding: str,
        credential_profile: str,
        authority_id: str,
        authority_binding_hash: str,
        policy_id: str,
        signature: str,
        plan_hash: str,
        expected_approval_principal: Mapping[str, str],
        expected_mandate_principal: Mapping[str, str],
        now: datetime,
    ) -> BeginExecution:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._execution_row(connection, execution_key)
            if existing is not None:
                record = self._execution_from_row(existing)
                if record.plan_hash != plan_hash:
                    raise GoalLifecycleRejected("EXECUTION_PLAN_CHANGED")
                return BeginExecution(record, False)
            self._reserve_authority(
                connection=connection,
                authority_id=authority_id,
                proposal_id=proposal_id,
                counter_id=counter_id,
                site_zone=site_zone,
                action="GOAL_AUTHORING",
                policy_id=policy_id,
                binding_hash=authority_binding_hash,
                execution_key=execution_key,
                expected_approval_principal=expected_approval_principal,
                expected_mandate_principal=expected_mandate_principal,
                now=now,
            )
            reservation = connection.execute(
                "SELECT * FROM goal_creation_reservations WHERE reservation_id = ?",
                (reservation_id,),
            ).fetchone()
            if (
                reservation is None
                or reservation["status"] != "AVAILABLE"
                or reservation["scope_binding"] != scope_binding
                or reservation["object_type"] != "METRIKA_GOAL"
                or reservation["proposal_id"] != proposal_id
                or reservation["credential_profile"] != credential_profile
                or reservation["expires_at"] <= utc_text(now)
            ):
                raise GoalLifecycleRejected("CREATION_RESERVATION_INVALID")
            now_text = utc_text(now)
            connection.execute(
                "INSERT INTO goal_executions "
                "(execution_key, operation, candidate_id, run_id, proposal_id, "
                "counter_id, plan_hash, status, created_at, updated_at) "
                "VALUES (?, 'GOAL_AUTHORING', ?, ?, ?, ?, ?, 'IN_FLIGHT', ?, ?)",
                (
                    execution_key,
                    candidate_id,
                    run_id,
                    proposal_id,
                    counter_id,
                    plan_hash,
                    now_text,
                    now_text,
                ),
            )
            try:
                connection.execute(
                    "INSERT INTO goal_signature_claims "
                    "(counter_id, signature, execution_key) VALUES (?, ?, ?)",
                    (counter_id, signature, execution_key),
                )
            except sqlite3.IntegrityError as error:
                raise GoalLifecycleRejected("DUPLICATE_GOAL_CANDIDATE") from error
            updated = connection.execute(
                "UPDATE goal_creation_reservations "
                "SET status = 'RESERVED', execution_key = ?, used_by_run = ? "
                "WHERE reservation_id = ? AND status = 'AVAILABLE'",
                (execution_key, run_id, reservation_id),
            )
            if updated.rowcount != 1:
                raise GoalLifecycleRejected("CREATION_RESERVATION_INVALID")
            execution = self._execution_row(connection, execution_key)
            if execution is None:
                raise GoalLifecycleRejected("EXECUTION_NOT_FOUND")
            record = self._execution_from_row(execution)
            return BeginExecution(record, True)

    def begin_site_publication(
        self,
        *,
        execution_key: str,
        candidate: GoalCandidateRecord,
        site_zone: str,
        authority_id: str,
        authority_binding_hash: str,
        policy_id: str,
        plan_hash: str,
        expected_approval_principal: Mapping[str, str],
        expected_mandate_principal: Mapping[str, str],
        now: datetime,
    ) -> BeginExecution:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._execution_row(connection, execution_key)
            if existing is not None:
                record = self._execution_from_row(existing)
                if record.plan_hash != plan_hash:
                    raise GoalLifecycleRejected("EXECUTION_PLAN_CHANGED")
                return BeginExecution(record, False)
            if connection.execute(
                "SELECT 1 FROM goal_site_publications WHERE candidate_id = ?",
                (candidate.candidate_id,),
            ).fetchone():
                raise GoalLifecycleRejected("SITE_EVENT_ALREADY_PUBLISHED")
            self._reserve_authority(
                connection=connection,
                authority_id=authority_id,
                proposal_id=candidate.proposal_id,
                counter_id=candidate.counter_id,
                site_zone=site_zone,
                action="SITE_PUBLISH",
                policy_id=policy_id,
                binding_hash=authority_binding_hash,
                execution_key=execution_key,
                expected_approval_principal=expected_approval_principal,
                expected_mandate_principal=expected_mandate_principal,
                now=now,
                required_kind=AuthorityKind.APPROVAL,
            )
            now_text = utc_text(now)
            connection.execute(
                "INSERT INTO goal_executions "
                "(execution_key, operation, candidate_id, run_id, proposal_id, "
                "counter_id, plan_hash, status, created_at, updated_at) "
                "VALUES (?, 'SITE_PUBLISH', ?, ?, ?, ?, ?, 'IN_FLIGHT', ?, ?)",
                (
                    execution_key,
                    candidate.candidate_id,
                    candidate.run_id,
                    candidate.proposal_id,
                    candidate.counter_id,
                    plan_hash,
                    now_text,
                    now_text,
                ),
            )
            execution = self._execution_row(connection, execution_key)
            if execution is None:
                raise GoalLifecycleRejected("EXECUTION_NOT_FOUND")
            record = self._execution_from_row(execution)
            return BeginExecution(record, True)

    def complete_goal_creation(
        self,
        execution_key: str,
        candidate: GoalCandidateRecord,
        authority_id: str,
        reservation_id: str,
        now: datetime,
    ) -> GoalCandidateRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            execution = self._require_reconcilable_execution(
                connection,
                execution_key,
                "GOAL_AUTHORING",
            )
            existing = connection.execute(
                "SELECT * FROM goal_candidates WHERE candidate_id = ?",
                (candidate.candidate_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO goal_candidates "
                    "(candidate_id, run_id, proposal_id, counter_id, goal_id, name, "
                    "event, site_location, goal_type, business_meaning, priority, "
                    "status, technical_status, created_at, "
                    "optimization_gate_passed, semantic_reviewer) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        candidate.candidate_id,
                        candidate.run_id,
                        candidate.proposal_id,
                        candidate.counter_id,
                        candidate.goal_id,
                        candidate.name,
                        candidate.event,
                        candidate.site_location,
                        candidate.goal_type,
                        candidate.business_meaning,
                        candidate.priority,
                        candidate.status.value,
                        candidate.technical_status.value,
                        utc_text(candidate.created_at),
                        int(candidate.optimization_gate_passed),
                        candidate.semantic_reviewer,
                    ),
                )
            elif existing["goal_id"] != candidate.goal_id:
                raise GoalLifecycleRejected("CREATED_TARGET_CONFLICT")
            self._finish_authority(connection, authority_id, execution_key)
            reservation = connection.execute(
                "UPDATE goal_creation_reservations SET status = 'USED' "
                "WHERE reservation_id = ? AND status = 'RESERVED' "
                "AND execution_key = ?",
                (reservation_id, execution_key),
            )
            if reservation.rowcount != 1:
                raise GoalLifecycleRejected("CREATION_RESERVATION_INVALID")
            connection.execute(
                "UPDATE goal_executions SET status = 'APPLIED', external_id = ?, "
                "updated_at = ? WHERE execution_key = ? AND status IN "
                "('IN_FLIGHT', 'UNKNOWN_RESULT')",
                (candidate.goal_id, utc_text(now), execution_key),
            )
            if execution["candidate_id"] != candidate.candidate_id:
                raise GoalLifecycleRejected("CREATED_TARGET_CONFLICT")
        return self.load_candidate(candidate.candidate_id)

    def complete_site_publication(
        self,
        execution_key: str,
        publication: SitePublication,
        authority_id: str,
        now: datetime,
    ) -> SitePublication:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            execution = self._require_reconcilable_execution(
                connection,
                execution_key,
                "SITE_PUBLISH",
            )
            existing = connection.execute(
                "SELECT * FROM goal_site_publications WHERE candidate_id = ?",
                (publication.candidate_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO goal_site_publications "
                    "(candidate_id, run_id, site_zone, event, selector, "
                    "previous_version, published_version, author, exact_diff_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        publication.candidate_id,
                        publication.run_id,
                        publication.site_zone,
                        publication.event,
                        publication.selector,
                        publication.previous_version,
                        publication.published_version,
                        publication.author,
                        canonical_json(publication.exact_diff),
                    ),
                )
            elif existing["published_version"] != publication.published_version:
                raise GoalLifecycleRejected("CREATED_TARGET_CONFLICT")
            self._finish_authority(connection, authority_id, execution_key)
            connection.execute(
                "UPDATE goal_executions SET status = 'APPLIED', external_id = ?, "
                "updated_at = ? WHERE execution_key = ? AND status IN "
                "('IN_FLIGHT', 'UNKNOWN_RESULT')",
                (publication.published_version, utc_text(now), execution_key),
            )
            if execution["candidate_id"] != publication.candidate_id:
                raise GoalLifecycleRejected("CREATED_TARGET_CONFLICT")
        return self.load_publication(publication.candidate_id)

    def mark_unknown(
        self,
        execution_key: str,
        detail: str,
        now: datetime,
    ) -> None:
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE goal_executions SET status = 'UNKNOWN_RESULT', detail = ?, "
                "updated_at = ? WHERE execution_key = ? AND status = 'IN_FLIGHT'",
                (detail, utc_text(now), execution_key),
            )
            if updated.rowcount not in {0, 1}:
                raise GoalLifecycleRejected("EXECUTION_STATE_INVALID")

    def abort_before_write(
        self,
        execution_key: str,
        authority_id: str,
        reservation_id: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            execution = self._execution_row(connection, execution_key)
            if execution is None or execution["status"] != "IN_FLIGHT":
                return
            self._release_authority(connection, authority_id, execution_key)
            if reservation_id is not None:
                connection.execute(
                    "UPDATE goal_creation_reservations "
                    "SET status = 'AVAILABLE', execution_key = NULL, used_by_run = NULL "
                    "WHERE reservation_id = ? AND execution_key = ? "
                    "AND status = 'RESERVED'",
                    (reservation_id, execution_key),
                )
            connection.execute(
                "DELETE FROM goal_signature_claims WHERE execution_key = ?",
                (execution_key,),
            )
            connection.execute(
                "DELETE FROM goal_executions WHERE execution_key = ?",
                (execution_key,),
            )

    def load_execution(self, execution_key: str) -> GoalExecutionRecord:
        with self._connect() as connection:
            row = self._execution_row(connection, execution_key)
        if row is None:
            raise GoalLifecycleRejected("EXECUTION_NOT_FOUND")
        return self._execution_from_row(row)

    def load_candidate(self, candidate_id: str) -> GoalCandidateRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM goal_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise GoalLifecycleRejected("GOAL_CANDIDATE_NOT_FOUND")
        return self._candidate_from_row(row)

    def load_publication(self, candidate_id: str) -> SitePublication:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM goal_site_publications WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise GoalLifecycleRejected("SITE_EVENT_NOT_PUBLISHED")
        return self._publication_from_row(row)

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

    def set_optimization_gate(
        self,
        candidate_id: str,
        passed: bool,
    ) -> GoalCandidateRecord:
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE goal_candidates SET optimization_gate_passed = ? "
                "WHERE candidate_id = ? AND status = 'APPROVED' "
                "AND technical_status = 'VERIFIED'",
                (int(passed), candidate_id),
            )
            if updated.rowcount != 1:
                raise GoalLifecycleRejected("OPTIMIZATION_GATE_NOT_APPLICABLE")
        return self.load_candidate(candidate_id)

    def finish_cleanup(self, candidate_id: str, execution_key: str) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            candidate = connection.execute(
                "SELECT status FROM goal_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            if candidate is None or candidate["status"] != "REJECTED":
                raise GoalLifecycleRejected("ONLY_REJECTED_CANDIDATE_CAN_BE_CLEANED")
            connection.execute(
                "DELETE FROM goal_signature_claims WHERE execution_key = ?",
                (execution_key,),
            )

    def reservation_status(self, reservation_id: str) -> str:
        return self._status(
            "goal_creation_reservations",
            "reservation_id",
            reservation_id,
        )

    def authority_status(self, authority_id: str) -> str:
        return self._status("goal_authorities", "authority_id", authority_id)

    def _status(self, table: str, key: str, value: str) -> str:
        if table not in {"goal_creation_reservations", "goal_authorities"}:
            raise ValueError("Unsupported status table.")
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT status FROM {table} WHERE {key} = ?",
                (value,),
            ).fetchone()
        if row is None:
            raise GoalLifecycleRejected("STATE_NOT_FOUND")
        return str(row["status"])

    @staticmethod
    def _reserve_authority(
        *,
        connection: sqlite3.Connection,
        authority_id: str,
        proposal_id: str,
        counter_id: str,
        site_zone: str,
        action: str,
        policy_id: str,
        binding_hash: str,
        execution_key: str,
        expected_approval_principal: Mapping[str, str],
        expected_mandate_principal: Mapping[str, str],
        now: datetime,
        required_kind: AuthorityKind | None = None,
    ) -> None:
        row = connection.execute(
            "SELECT * FROM goal_authorities WHERE authority_id = ?",
            (authority_id,),
        ).fetchone()
        if row is None:
            raise GoalLifecycleRejected("AUTHORITY_INVALID")
        kind = AuthorityKind(row["kind"])
        expected_principal = (
            expected_approval_principal
            if kind == AuthorityKind.APPROVAL
            else expected_mandate_principal
        )
        valid_status = "AVAILABLE" if kind == AuthorityKind.APPROVAL else "ACTIVE"
        if (
            (required_kind is not None and kind != required_kind)
            or row["status"] != valid_status
            or row["proposal_id"] != proposal_id
            or row["counter_id"] != counter_id
            or row["site_zone"] != site_zone
            or row["principal"] != expected_principal["identity"]
            or row["authentication"] != expected_principal["authentication"]
            or action not in row["allowed_actions"].split(",")
            or row["policy_id"] != policy_id
            or row["expires_at"] <= utc_text(now)
            or row["binding_hash"] != binding_hash
            or int(row["actions_used"]) >= int(row["action_quota"])
        ):
            raise GoalLifecycleRejected("AUTHORITY_INVALID")
        updated = connection.execute(
            "UPDATE goal_authorities SET status = 'RESERVED', execution_key = ? "
            "WHERE authority_id = ? AND status = ?",
            (execution_key, authority_id, valid_status),
        )
        if updated.rowcount != 1:
            raise GoalLifecycleRejected("AUTHORITY_INVALID")

    @staticmethod
    def _finish_authority(
        connection: sqlite3.Connection,
        authority_id: str,
        execution_key: str,
    ) -> None:
        row = connection.execute(
            "SELECT kind, action_quota, actions_used FROM goal_authorities "
            "WHERE authority_id = ? "
            "AND status = 'RESERVED' AND execution_key = ?",
            (authority_id, execution_key),
        ).fetchone()
        if row is None:
            raise GoalLifecycleRejected("AUTHORITY_INVALID")
        actions_used = int(row["actions_used"]) + 1
        if row["kind"] == AuthorityKind.APPROVAL.value:
            terminal = "USED"
        elif actions_used >= int(row["action_quota"]):
            terminal = "EXHAUSTED"
        else:
            terminal = "ACTIVE"
        connection.execute(
            "UPDATE goal_authorities SET status = ?, actions_used = ?, "
            "execution_key = NULL WHERE authority_id = ? "
            "AND status = 'RESERVED' AND execution_key = ?",
            (terminal, actions_used, authority_id, execution_key),
        )

    @staticmethod
    def _release_authority(
        connection: sqlite3.Connection,
        authority_id: str,
        execution_key: str,
    ) -> None:
        row = connection.execute(
            "SELECT kind FROM goal_authorities WHERE authority_id = ? "
            "AND status = 'RESERVED' AND execution_key = ?",
            (authority_id, execution_key),
        ).fetchone()
        if row is None:
            return
        released = (
            "AVAILABLE" if row["kind"] == AuthorityKind.APPROVAL.value else "ACTIVE"
        )
        connection.execute(
            "UPDATE goal_authorities SET status = ?, execution_key = NULL "
            "WHERE authority_id = ? AND execution_key = ?",
            (released, authority_id, execution_key),
        )

    @staticmethod
    def _execution_row(
        connection: sqlite3.Connection,
        execution_key: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM goal_executions WHERE execution_key = ?",
            (execution_key,),
        ).fetchone()

    @staticmethod
    def _require_reconcilable_execution(
        connection: sqlite3.Connection,
        execution_key: str,
        operation: str,
    ) -> sqlite3.Row:
        row = GoalLifecycleStore._execution_row(connection, execution_key)
        if (
            row is None
            or row["operation"] != operation
            or row["status"] not in {"IN_FLIGHT", "UNKNOWN_RESULT"}
        ):
            raise GoalLifecycleRejected("EXECUTION_NOT_RECONCILABLE")
        return row

    @staticmethod
    def _execution_from_row(row: sqlite3.Row) -> GoalExecutionRecord:
        return GoalExecutionRecord(
            execution_key=row["execution_key"],
            operation=row["operation"],
            candidate_id=row["candidate_id"],
            run_id=row["run_id"],
            proposal_id=row["proposal_id"],
            counter_id=row["counter_id"],
            plan_hash=row["plan_hash"],
            status=GoalExecutionStatus(row["status"]),
            external_id=row["external_id"],
            detail=row["detail"],
        )

    @staticmethod
    def _candidate_from_row(row: sqlite3.Row) -> GoalCandidateRecord:
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
            created_at=parse_utc(row["created_at"]),
            optimization_gate_passed=bool(row["optimization_gate_passed"]),
            semantic_reviewer=row["semantic_reviewer"],
        )

    @staticmethod
    def _publication_from_row(row: sqlite3.Row) -> SitePublication:
        return SitePublication(
            candidate_id=row["candidate_id"],
            run_id=row["run_id"],
            site_zone=row["site_zone"],
            event=row["event"],
            selector=row["selector"],
            previous_version=row["previous_version"],
            published_version=row["published_version"],
            author=row["author"],
            exact_diff=json.loads(row["exact_diff_json"]),
        )
