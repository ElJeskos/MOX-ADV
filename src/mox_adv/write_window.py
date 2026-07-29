"""Shared durable write-window coordination for both execution modes."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from mox_adv.control_state import ControlRejected, ExecutionStatus
from mox_adv.monitoring import DurableWriteWindowGate, MonitoringRejected


class DurableWriteWindowCoordinator:
    """Translate one durable Gate 0 write window into execution controls."""

    def __init__(
        self,
        path: Path,
        policy: Mapping[str, Any],
        clock: Callable[[], datetime],
    ) -> None:
        self.gate = DurableWriteWindowGate(path, policy)
        self.clock = clock

    def reserve(self, execution_key: str) -> None:
        try:
            decision = self.gate.reserve(execution_key, self.clock())
        except (MonitoringRejected, sqlite3.Error) as error:
            raise self._state_unavailable() from error
        if not decision.allowed:
            raise ControlRejected(
                decision.reason_code or "COOLDOWN_AND_OBSERVATION_ACTIVE",
                "durable cooldown and observation window block the unsent command.",
            )

    def settle(self, execution_key: str, status: ExecutionStatus) -> None:
        try:
            if status == ExecutionStatus.APPLIED:
                self.gate.activate(execution_key, self.clock())
            elif status == ExecutionStatus.FAILED:
                self.gate.release(execution_key)
        except (MonitoringRejected, sqlite3.Error) as error:
            raise self._state_unavailable() from error

    @staticmethod
    def _state_unavailable() -> ControlRejected:
        return ControlRejected(
            "WRITE_WINDOW_STATE_UNAVAILABLE",
            "durable write-window state is unavailable.",
        )
