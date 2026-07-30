"""Trusted runtime dependencies for standalone Direct actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from mox_adv.control_state import DurableControlState
from mox_adv.direct_provider import DirectStateValuesV1
from mox_adv.environment import ExecutionEnvironment, parse_execution_environment
from mox_adv.fake_write_adapter import FakeWriteAdapter
from mox_adv.mandate_store import DurableMandateAuthority
from mox_adv.monitoring import MonitoringStore
from mox_adv.proposal_store import ImmutableProposalStore
from mox_adv.recommend_projection import SanitizedProjection


@dataclass(frozen=True)
class PairedDirectActionContextV1:
    """Bind one trusted paired snapshot and its unchanged model projection."""

    projection: SanitizedProjection
    snapshot_id: str
    expected_fingerprint: str
    expected_state: DirectStateValuesV1

    def __post_init__(self) -> None:
        if not isinstance(self.projection, SanitizedProjection):
            raise ValueError(
                "Paired Direct execution requires a trusted sanitized projection."
            )
        if (
            not isinstance(self.snapshot_id, str)
            or not self.snapshot_id.startswith("sha256:")
            or len(self.snapshot_id) != 71
        ):
            raise ValueError(
                "Paired Direct execution requires the integrated snapshot id."
            )
        if (
            not isinstance(self.expected_fingerprint, str)
            or not self.expected_fingerprint.startswith("sha256:")
            or len(self.expected_fingerprint) != 71
        ):
            raise ValueError(
                "Paired Direct execution requires the expected target fingerprint."
            )
        if not isinstance(self.expected_state, DirectStateValuesV1):
            raise ValueError(
                "Paired Direct execution requires the trusted Direct state."
            )


@dataclass(frozen=True)
class DirectActionRuntimeV1:
    """Bind persistence and the one sealed Direct TEST write adapter."""

    policy: Mapping[str, Any]
    state: DurableControlState
    proposal_store: ImmutableProposalStore
    trigger_store: MonitoringStore
    test_adapter: Optional[FakeWriteAdapter]
    environment: ExecutionEnvironment
    paired_context: Optional[PairedDirectActionContextV1] = None
    mandate_authority: Optional[DurableMandateAuthority] = None

    def __post_init__(self) -> None:
        trusted_environment = parse_execution_environment(self.environment)
        object.__setattr__(self, "environment", trusted_environment)
        if not isinstance(self.trigger_store, MonitoringStore):
            raise ValueError("Standalone Direct requires an explicit MonitoringStore.")
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
        if (
            self.paired_context is not None
            and trusted_environment is not ExecutionEnvironment.TEST
        ):
            raise ValueError("Paired Direct execution context is allowed only in TEST.")
        if self.mandate_authority is not None and not isinstance(
            self.mandate_authority,
            DurableMandateAuthority,
        ):
            raise TypeError("Direct Mandate execution requires the durable authority.")


__all__ = [
    "DirectActionRuntimeV1",
    "PairedDirectActionContextV1",
]
