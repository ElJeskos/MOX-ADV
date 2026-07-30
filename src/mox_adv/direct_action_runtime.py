"""Trusted runtime dependencies for standalone Direct actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from mox_adv.control_state import DurableControlState
from mox_adv.environment import ExecutionEnvironment, parse_execution_environment
from mox_adv.fake_write_adapter import FakeWriteAdapter
from mox_adv.monitoring import MonitoringStore
from mox_adv.proposal_store import ImmutableProposalStore


@dataclass(frozen=True)
class DirectActionRuntimeV1:
    """Bind persistence and the one sealed Direct TEST write adapter."""

    policy: Mapping[str, Any]
    state: DurableControlState
    proposal_store: ImmutableProposalStore
    test_adapter: Optional[FakeWriteAdapter]
    environment: ExecutionEnvironment
    trigger_store: Optional[MonitoringStore] = None

    def __post_init__(self) -> None:
        trusted_environment = parse_execution_environment(self.environment)
        object.__setattr__(self, "environment", trusted_environment)
        if self.trigger_store is None:
            object.__setattr__(
                self,
                "trigger_store",
                MonitoringStore(
                    self.proposal_store.root.parent / "monitoring.sqlite3"
                ),
            )
        if (
            self.test_adapter is not None
            and type(self.test_adapter) is not FakeWriteAdapter
        ):
            raise ValueError(
                "Standalone Direct accepts only the sealed socket-free TEST adapter."
            )
        if (
            trusted_environment is ExecutionEnvironment.TEST
            and self.test_adapter is None
        ):
            raise ValueError(
                "Standalone Direct TEST execution requires the approved test adapter."
            )


__all__ = ["DirectActionRuntimeV1"]
