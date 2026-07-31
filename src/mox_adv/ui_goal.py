"""Dashboard index for durable candidate-goal lifecycle evidence."""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


class DashboardGoalLifecycleHistory:
    """Index the latest goal lifecycle result for each local campaign draft."""

    def __init__(self, runs_root: Path) -> None:
        self.runs_root = Path(runs_root)
        self._lock = threading.RLock()
        self._latest_by_draft: dict[str, dict[str, Any]] = {}
        self._pending: dict[str, str] | None = None
        self._load_existing()

    def latest(self, draft_id: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._latest_by_draft.get(draft_id)
            return deepcopy(value) if value is not None else None

    def record(self, result: Mapping[str, Any]) -> None:
        normalized = self._normalize(result)
        with self._lock:
            self._record(normalized)

    def pending(self) -> dict[str, str] | None:
        with self._lock:
            return deepcopy(self._pending)

    def reserve(self, run_id: str, draft_id: str) -> None:
        if not run_id or not draft_id:
            raise ValueError("GOAL_PENDING_RESERVATION_INVALID")
        with self._lock:
            if self._pending is not None:
                raise ValueError("GOAL_SEMANTIC_DECISION_ALREADY_PENDING")
            self._pending = {
                "run_id": run_id,
                "draft_id": draft_id,
            }

    def release(self, run_id: str) -> None:
        with self._lock:
            if self._pending is not None and self._pending["run_id"] == run_id:
                self._pending = None

    def _load_existing(self) -> None:
        for run_directory in sorted(self.runs_root.glob("ui-goal-*")):
            if not run_directory.is_dir():
                continue
            final_path = run_directory / "goal_workflow.json"
            technical_path = run_directory / "goal_technical.json"
            path = final_path if final_path.is_file() else technical_path
            if not path.is_file():
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                normalized = self._normalize(value)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
            self._record(normalized)

    def _record(self, result: dict[str, Any]) -> None:
        source = result["source_draft"]
        draft_id = str(source["draft_id"])
        status = str(result.get("status", ""))
        if status == "AWAITING_SEMANTIC_DECISION":
            requested_at = self._requested_at(result)
            current_pending = self._pending
            current_result = (
                self._latest_by_draft.get(current_pending["draft_id"])
                if current_pending is not None
                else None
            )
            if (
                current_result is None
                or requested_at >= self._requested_at(current_result)
                or current_pending["run_id"] == result["run_id"]
            ):
                self._pending = {
                    "run_id": str(result["run_id"]),
                    "draft_id": draft_id,
                }
        elif self._pending is not None and self._pending["run_id"] == result["run_id"]:
            self._pending = None
        current = self._latest_by_draft.get(draft_id)
        if current is None:
            self._latest_by_draft[draft_id] = deepcopy(result)
            return
        current_time = self._requested_at(current)
        candidate_time = self._requested_at(result)
        same_run = result["run_id"] == current["run_id"]
        if candidate_time > current_time or same_run:
            self._latest_by_draft[draft_id] = deepcopy(result)

    @staticmethod
    def _requested_at(value: Mapping[str, Any]) -> datetime:
        requested_at = value.get("requested_at")
        if not isinstance(requested_at, str):
            raise TypeError("GOAL_REQUESTED_AT_INVALID")
        return datetime.fromisoformat(requested_at.replace("Z", "+00:00"))

    @classmethod
    def _normalize(cls, value: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError("GOAL_HISTORY_INVALID")
        source = value.get("source_draft")
        if not isinstance(source, Mapping) or set(source) != {
            "draft_id",
            "revision",
            "candidate_hash",
        }:
            raise ValueError("GOAL_SOURCE_DRAFT_INVALID")
        draft_id = source.get("draft_id")
        revision = source.get("revision")
        candidate_hash = source.get("candidate_hash")
        if (
            not isinstance(draft_id, str)
            or not draft_id
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 0
            or not isinstance(candidate_hash, str)
            or not candidate_hash.startswith("sha256:")
            or not isinstance(value.get("run_id"), str)
            or not value["run_id"]
        ):
            raise ValueError("GOAL_SOURCE_DRAFT_INVALID")
        cls._requested_at(value)
        return deepcopy(dict(value))
