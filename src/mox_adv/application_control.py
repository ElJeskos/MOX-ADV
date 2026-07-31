"""Application-owned control plane for every write-class transport."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from mox_adv.control_state import DurableControlState, TrustedScope
from mox_adv.trust_boundary import (
    DurablePreWriteAudit,
    MacOSKeychainAuditAnchorSigner,
    PreWriteAudit,
    SimulationAuditAnchorSigner,
)

_APPLICATION_WRITE_BOUNDARY_SEAL = object()


class ApplicationWriteBoundary:
    """Bind one durable kill switch and audit authority to all write services."""

    def __init__(
        self,
        *,
        state: DurableControlState,
        pre_write_audit: PreWriteAudit,
        clock: Callable[[], datetime],
        simulation_only: bool,
        seal: object,
    ) -> None:
        if (
            seal is not _APPLICATION_WRITE_BOUNDARY_SEAL
            or type(state) is not DurableControlState
        ):
            raise TypeError("APPLICATION_WRITE_BOUNDARY_FACTORY_REQUIRED")
        self.state = state
        self.pre_write_audit = pre_write_audit
        self.clock = clock
        self.simulation_only = simulation_only

    @classmethod
    def production(
        cls,
        policy: Mapping[str, Any],
        clock: Callable[[], datetime],
    ) -> "ApplicationWriteBoundary":
        path = (
            Path.home()
            / "Library"
            / "Application Support"
            / "MOX-ADV"
            / "control.sqlite3"
        )
        state = DurableControlState(path)
        return cls(
            state=state,
            pre_write_audit=DurablePreWriteAudit(
                path,
                str(policy["policy_id"]),
                MacOSKeychainAuditAnchorSigner(),
            ),
            clock=clock,
            simulation_only=False,
            seal=_APPLICATION_WRITE_BOUNDARY_SEAL,
        )

    @classmethod
    def for_isolated_test(
        cls,
        path: Path,
        policy: Mapping[str, Any],
        clock: Callable[[], datetime],
        *,
        pre_write_audit: PreWriteAudit | None = None,
    ) -> "ApplicationWriteBoundary":
        state = DurableControlState(path)
        return cls(
            state=state,
            pre_write_audit=(
                pre_write_audit
                if pre_write_audit is not None
                else DurablePreWriteAudit(
                    path,
                    str(policy["policy_id"]),
                    SimulationAuditAnchorSigner(),
                )
            ),
            clock=clock,
            simulation_only=True,
            seal=_APPLICATION_WRITE_BOUNDARY_SEAL,
        )

    def require_dispatch_allowed(self, scope: TrustedScope) -> None:
        self.state.require_dispatch_allowed(scope)

    def authorize(
        self,
        execution_key: str,
        target_key: str,
        scope: TrustedScope,
        final_check: Callable[[], Any] | None = None,
    ) -> Any:
        self.require_dispatch_allowed(scope)
        result = None if final_check is None else final_check()
        self.pre_write_audit.authorize(
            execution_key,
            target_key,
            self.clock(),
        )
        self.require_dispatch_allowed(scope)
        return result
