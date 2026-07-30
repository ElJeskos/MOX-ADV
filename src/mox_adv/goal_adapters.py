"""Target-bound fake adapters for goal and site write-path simulation."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Callable

from mox_adv.goal_contracts import (
    GoalLifecycleRejected,
    SitePublication,
)


class FakeAdapterTimeout(TimeoutError):
    """The fake write completed but its response was lost."""


class FakeMetrikaGoalAdapter:
    """In-memory Metrica adapter with no URL or HTTP transport."""

    is_fake = True

    def __init__(
        self,
        allowed_counter_ids: Iterable[str],
        write_delay_seconds: float = 0,
        timeout_after_write: bool = False,
        before_add: Callable[[str], None] | None = None,
    ) -> None:
        self.allowed_counter_ids = frozenset(allowed_counter_ids)
        self.write_delay_seconds = write_delay_seconds
        self.timeout_after_write = timeout_after_write
        self.before_add = before_add
        self._goals: dict[str, dict[str, dict[str, Any]]] = {
            counter_id: {} for counter_id in self.allowed_counter_ids
        }
        self._visit_observations: dict[tuple[str, str], tuple[str, ...]] = {}
        self._visit_poll_counts: dict[tuple[str, str], int] = {}
        self._lock = threading.RLock()
        self.add_calls = 0
        self.delete_calls = 0

    def list_goals(self, counter_id: str) -> tuple[Mapping[str, Any], ...]:
        self._require_counter(counter_id)
        with self._lock:
            return tuple(dict(item) for item in self._goals[counter_id].values())

    def seed_existing_goal(
        self,
        counter_id: str,
        goal: Mapping[str, Any],
    ) -> None:
        self._require_counter(counter_id)
        goal_id = str(goal.get("goal_id", ""))
        with self._lock:
            if not goal_id or goal_id in self._goals[counter_id]:
                raise GoalLifecycleRejected("EXISTING_GOAL_INVALID")
            self._goals[counter_id][goal_id] = dict(goal)

    def add_goal(
        self,
        counter_id: str,
        payload: Mapping[str, Any],
        signature: str,
        execution_key: str,
    ) -> Mapping[str, Any]:
        self._require_counter(counter_id)
        if self.before_add is not None:
            self.before_add(execution_key)
        if self.write_delay_seconds:
            time.sleep(self.write_delay_seconds)
        with self._lock:
            self.add_calls += 1
            goal_id = "goal-" + str(self.add_calls)
            goal = dict(payload)
            goal.update(
                {
                    "goal_id": goal_id,
                    "_goal_signature": signature,
                    "_execution_key": execution_key,
                }
            )
            self._goals[counter_id][goal_id] = goal
        if self.timeout_after_write:
            raise FakeAdapterTimeout("Metrica goal response timed out after write.")
        return dict(goal)

    def find_goals_by_signature(
        self,
        counter_id: str,
        signature: str,
    ) -> tuple[Mapping[str, Any], ...]:
        return tuple(
            item
            for item in self.list_goals(counter_id)
            if item.get("_goal_signature") == signature
        )

    def get_goal(self, counter_id: str, goal_id: str) -> Mapping[str, Any]:
        self._require_counter(counter_id)
        with self._lock:
            try:
                return dict(self._goals[counter_id][goal_id])
            except KeyError as error:
                raise GoalLifecycleRejected("GOAL_NOT_FOUND") from error

    def delete_goal(self, counter_id: str, goal_id: str) -> None:
        self._require_counter(counter_id)
        with self._lock:
            if goal_id not in self._goals[counter_id]:
                raise GoalLifecycleRejected("GOAL_NOT_FOUND")
            self.delete_calls += 1
            del self._goals[counter_id][goal_id]

    def goal_exists(self, counter_id: str, goal_id: str) -> bool:
        self._require_counter(counter_id)
        with self._lock:
            return goal_id in self._goals[counter_id]

    def delete_goal_if_present(self, counter_id: str, goal_id: str) -> bool:
        self._require_counter(counter_id)
        with self._lock:
            if goal_id not in self._goals[counter_id]:
                return False
            self.delete_calls += 1
            del self._goals[counter_id][goal_id]
            return True

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
        with self._lock:
            self._visit_observations[key] = values
            self._visit_poll_counts[key] = 0

    def poll_goal_visit(self, counter_id: str, goal_id: str) -> str:
        self.get_goal(counter_id, goal_id)
        key = (counter_id, goal_id)
        with self._lock:
            observations = self._visit_observations.get(key, ("PENDING",))
            index = self._visit_poll_counts.get(key, 0)
            self._visit_poll_counts[key] = index + 1
            return observations[min(index, len(observations) - 1)]

    def visit_poll_count(self, counter_id: str, goal_id: str) -> int:
        with self._lock:
            return self._visit_poll_counts.get((counter_id, goal_id), 0)

    def _require_counter(self, counter_id: str) -> None:
        if counter_id not in self.allowed_counter_ids:
            raise GoalLifecycleRejected("COUNTER_NOT_ALLOWLISTED")


class FakeSitePublishAdapter:
    """In-memory publisher constrained to configured page zones."""

    is_fake = True

    def __init__(
        self,
        zone_versions: Mapping[str, str],
        write_delay_seconds: float = 0,
        timeout_after_write: bool = False,
    ) -> None:
        self.write_delay_seconds = write_delay_seconds
        self.timeout_after_write = timeout_after_write
        self._versions = dict(zone_versions)
        self._publications: dict[str, SitePublication] = {}
        self._lock = threading.RLock()
        self.publish_calls = 0
        self.rollback_calls = 0

    def current_version(self, site_zone: str) -> str:
        with self._lock:
            try:
                return self._versions[site_zone]
            except KeyError as error:
                raise GoalLifecycleRejected("SITE_ZONE_NOT_ALLOWLISTED") from error

    def publish_event(
        self,
        *,
        candidate_id: str,
        run_id: str,
        site_zone: str,
        expected_version: str,
        event: str,
        selector: str,
        author: str,
        exact_diff: Mapping[str, Any],
    ) -> SitePublication:
        if self.write_delay_seconds:
            time.sleep(self.write_delay_seconds)
        with self._lock:
            if self.current_version(site_zone) != expected_version:
                raise GoalLifecycleRejected("SITE_VERSION_MISMATCH")
            expected_after = expected_version + "+" + run_id
            if (
                exact_diff.get("candidate_id") != candidate_id
                or exact_diff.get("site_zone") != site_zone
                or exact_diff.get("event") != event
                or exact_diff.get("selector") != selector
                or exact_diff.get("before", {}).get("page_version") != expected_version
                or exact_diff.get("after", {}).get("page_version") != expected_after
            ):
                raise GoalLifecycleRejected("SITE_DIFF_MISMATCH")
            publication = SitePublication(
                candidate_id=candidate_id,
                run_id=run_id,
                site_zone=site_zone,
                event=event,
                selector=selector,
                previous_version=expected_version,
                published_version=expected_after,
                author=author,
                exact_diff=dict(exact_diff),
            )
            self.publish_calls += 1
            self._versions[site_zone] = expected_after
            self._publications[candidate_id] = publication
        if self.timeout_after_write:
            raise FakeAdapterTimeout("Site publish response timed out after write.")
        return publication

    def publication_for_candidate(
        self,
        candidate_id: str,
    ) -> SitePublication | None:
        with self._lock:
            return self._publications.get(candidate_id)

    def rollback_publication(
        self,
        publication: SitePublication,
        run_id: str,
    ) -> None:
        with self._lock:
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
