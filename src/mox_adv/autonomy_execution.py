"""Fake-only bounded-autonomy execution and reconciliation."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import InvalidOperation
from typing import Any, Callable, Mapping, Optional

from mox_adv.audit import AuditWriteBlocked
from mox_adv.autonomy_contracts import (
    BoundedAutonomyOutcome,
    BoundedAutonomyRequest,
    ReadbackClassification,
    classify_readback,
)
from mox_adv.autonomy_policy import BoundedAutonomyPolicy
from mox_adv.commands import CommandRejected, build_high_level_command
from mox_adv.control_state import (
    ControlRejected,
    DurableControlState,
    ExecutionStatus,
    PreparedChange,
)
from mox_adv.egress import EgressDenied, HttpEgressGuard
from mox_adv.fake_write_adapter import AdapterTimeout, FakeWriteAdapter
from mox_adv.mandate_store import DurableMandateAuthority
from mox_adv.trust_boundary import (
    DurablePreWriteAudit,
    GuardedDispatchBoundary,
    MacOSKeychainAuditAnchorSigner,
    PreWriteAudit,
    SimulationAuditAnchorSigner,
)
from mox_adv.write_window import DurableWriteWindowCoordinator


class BoundedAutonomyService:
    """Execute and safely recheck one Mandate-bound fake command."""

    def __init__(
        self,
        policy: Mapping[str, Any],
        control_state: DurableControlState,
        mandate_authority: DurableMandateAuthority,
        adapter: Any,
        clock: Callable[[], datetime],
        before_dispatch: Optional[Callable[[], None]] = None,
        pre_write_audit: Optional[PreWriteAudit] = None,
    ) -> None:
        self.policy = BoundedAutonomyPolicy(policy)
        self.control_state = control_state
        self.mandate_authority = mandate_authority
        self.adapter = adapter
        self.clock = clock
        self.before_dispatch = before_dispatch
        self.egress_guard = HttpEgressGuard(policy)
        self.write_window = DurableWriteWindowCoordinator(
            control_state.path,
            policy,
            clock,
        )
        self.pre_write_audit = pre_write_audit or DurablePreWriteAudit(
            control_state.path,
            str(policy["policy_id"]),
            (
                SimulationAuditAnchorSigner()
                if type(adapter) is FakeWriteAdapter
                else MacOSKeychainAuditAnchorSigner()
            ),
        )
        self.dispatch_boundary = GuardedDispatchBoundary(
            self.pre_write_audit,
            self.write_window,
            self.clock,
        )

    def execute(
        self,
        request: BoundedAutonomyRequest,
    ) -> BoundedAutonomyOutcome:
        try:
            prepared = self._prepare(request)
            before = self.adapter.readback(prepared.target_key())
            if before not in {prepared.current_value, prepared.target_value}:
                return BoundedAutonomyOutcome(
                    ExecutionStatus.BLOCKED,
                    "CURRENT_STATE_MISMATCH",
                    before,
                )
            reservation_status, reservation = self.mandate_authority.reserve_execution(
                prepared,
                request.mandate_id,
                self.clock(),
            )
            if reservation_status != ExecutionStatus.RESERVED:
                return BoundedAutonomyOutcome(
                    reservation_status,
                    reservation.detail,
                    before,
                )
            if before == prepared.target_value:
                self.control_state.finish_execution(
                    prepared.execution_key(),
                    ExecutionStatus.NO_CHANGE,
                    None,
                    self.clock(),
                )
                return BoundedAutonomyOutcome(
                    ExecutionStatus.NO_CHANGE,
                    None,
                    before,
                )
            return self._dispatch(prepared, request.mandate_id)
        except AdapterTimeout:
            return self._reconcile_request(request, "TARGET_STATE_NOT_APPLIED")
        except CommandRejected as error:
            reason = (
                "OUT_OF_BOUNDS" if "OUT_OF_BOUNDS" in str(error) else "INVALID_INPUT"
            )
            return BoundedAutonomyOutcome(ExecutionStatus.BLOCKED, reason, None)
        except (InvalidOperation, TypeError, ValueError):
            return BoundedAutonomyOutcome(
                ExecutionStatus.BLOCKED,
                "INVALID_INPUT",
                None,
            )
        except EgressDenied:
            return BoundedAutonomyOutcome(
                ExecutionStatus.BLOCKED,
                "EXTERNAL_WRITE_EGRESS_DENIED",
                None,
            )
        except AuditWriteBlocked:
            self._finish_active_as_blocked(
                request.execution_key,
                "AUDIT_EVIDENCE_UNAVAILABLE",
            )
            return BoundedAutonomyOutcome(
                ExecutionStatus.BLOCKED,
                "AUDIT_EVIDENCE_UNAVAILABLE",
                None,
            )
        except ControlRejected as error:
            self._finish_active_as_blocked(request.execution_key, error.reason_code)
            return BoundedAutonomyOutcome(
                ExecutionStatus.BLOCKED,
                error.reason_code,
                None,
            )
        except sqlite3.Error:
            return self._state_failure_outcome(request.execution_key)

    def recheck(
        self,
        request: BoundedAutonomyRequest,
    ) -> BoundedAutonomyOutcome:
        """Re-evaluate one exact BLOCKED/FAILED plan after readback confirms safety."""

        try:
            prepared = self.control_state.load_prepared_change(request.proposal_id)
            execution = self.control_state.load_execution(request.execution_key)
            if (
                execution.execution_key != prepared.execution_key()
                or execution.proposal_id != prepared.proposal_id
                or request.scope != prepared.scope
            ):
                raise ControlRejected(
                    "EXECUTION_KEY_MISMATCH",
                    "recheck must use the existing canonical plan.",
                )
            if execution.status not in {
                ExecutionStatus.BLOCKED,
                ExecutionStatus.FAILED,
            }:
                raise ControlRejected(
                    "EXECUTION_NOT_RECHECKABLE",
                    "only BLOCKED or FAILED execution can be rechecked.",
                )
            observed = self.adapter.readback(prepared.target_key())
            if observed == prepared.target_value:
                self.mandate_authority.record_recheck_applied(
                    prepared,
                    request.mandate_id,
                    self.clock(),
                )
                return BoundedAutonomyOutcome(
                    ExecutionStatus.APPLIED,
                    None,
                    observed,
                )
            if observed != prepared.current_value:
                self.mandate_authority.record_recheck_unknown(
                    prepared,
                    request.mandate_id,
                    self.clock(),
                )
                return BoundedAutonomyOutcome(
                    ExecutionStatus.UNKNOWN_RESULT,
                    "RECHECK_READBACK_INDETERMINATE",
                    observed,
                )
            if execution.status == ExecutionStatus.BLOCKED:
                self._prepare(request)
                self.mandate_authority.validate_blocked_recheck(
                    prepared,
                    request.mandate_id,
                    self.clock(),
                )
                return BoundedAutonomyOutcome(
                    ExecutionStatus.BLOCKED,
                    "NEW_AUTHORIZED_EXECUTION_REQUIRED",
                    observed,
                )
            return BoundedAutonomyOutcome(
                ExecutionStatus.FAILED,
                "RECHECK_SOURCE_STATE_CONFIRMED",
                observed,
            )
        except AdapterTimeout:
            return self._reconcile_request(request, "RECHECK_SOURCE_STATE_CONFIRMED")
        except (CommandRejected, InvalidOperation, TypeError, ValueError):
            return BoundedAutonomyOutcome(
                ExecutionStatus.BLOCKED,
                "INVALID_INPUT",
                None,
            )
        except (ControlRejected, EgressDenied) as error:
            reason = (
                error.reason_code
                if isinstance(error, ControlRejected)
                else "EXTERNAL_WRITE_EGRESS_DENIED"
            )
            self._finish_active_as_blocked(request.execution_key, reason)
            return BoundedAutonomyOutcome(ExecutionStatus.BLOCKED, reason, None)
        except sqlite3.Error:
            return self._state_failure_outcome(request.execution_key)

    def reconcile(self, execution_key: str) -> BoundedAutonomyOutcome:
        try:
            execution = self.control_state.load_execution(execution_key)
            observed = self.adapter.readback(execution.target_key)
            if execution.status in {
                ExecutionStatus.APPLIED,
                ExecutionStatus.NO_CHANGE,
            }:
                return BoundedAutonomyOutcome(
                    ExecutionStatus.ALREADY_PROCESSED,
                    None,
                    observed,
                )
            if execution.status not in {
                ExecutionStatus.RESERVED,
                ExecutionStatus.IN_FLIGHT,
            }:
                return BoundedAutonomyOutcome(
                    execution.status,
                    execution.detail,
                    observed,
                )
            prepared = self.control_state.load_prepared_change(execution.proposal_id)
            classification = classify_readback(
                prepared,
                observed,
                source_reason="RESTART_SOURCE_STATE_CONFIRMED",
                unknown_reason="RESTART_READBACK_INDETERMINATE",
            )
            return self._persist_classification(
                prepared,
                observed,
                classification,
            )
        except ControlRejected as error:
            return BoundedAutonomyOutcome(
                ExecutionStatus.BLOCKED,
                error.reason_code,
                None,
            )
        except sqlite3.Error:
            return BoundedAutonomyOutcome(
                ExecutionStatus.UNKNOWN_RESULT,
                "CONTROL_STATE_UNAVAILABLE",
                None,
            )

    def _prepare(self, request: BoundedAutonomyRequest) -> PreparedChange:
        prepared = self.control_state.load_prepared_change(request.proposal_id)
        decision = self.policy.evaluate(prepared, request)
        if not decision.allowed:
            raise ControlRejected(
                decision.reason_code or "ACTION_POLICY_REJECTED",
                "bounded-autonomy policy rejected the exact plan.",
            )
        minimum, maximum = self.policy.numeric_bounds(prepared)
        command = build_high_level_command(prepared, minimum, maximum)
        if type(self.adapter) is not FakeWriteAdapter:
            raise EgressDenied("Only the sealed fake adapter is permitted.")
        self.egress_guard.enforce_adapter(self.adapter, command)
        return prepared

    def _dispatch(
        self,
        prepared: PreparedChange,
        mandate_id: str,
    ) -> BoundedAutonomyOutcome:
        minimum, maximum = self.policy.numeric_bounds(prepared)
        command = build_high_level_command(prepared, minimum, maximum)
        send_status, execution = self.mandate_authority.send_once(
            prepared,
            mandate_id,
            self.clock(),
            lambda: self.adapter.apply(prepared.target_key(), command),
            before_dispatch=self.before_dispatch,
            at_dispatch_boundary=lambda: self.dispatch_boundary.authorize(
                prepared.execution_key(),
                prepared.target_key(),
            ),
        )
        if send_status != ExecutionStatus.IN_FLIGHT:
            return BoundedAutonomyOutcome(
                send_status,
                execution.detail,
                self.adapter.readback(prepared.target_key()),
            )
        observed = self.adapter.readback(prepared.target_key())
        classification = classify_readback(
            prepared,
            observed,
            source_reason="TARGET_STATE_NOT_APPLIED",
            unknown_reason="READBACK_INDETERMINATE",
        )
        return self._persist_classification(prepared, observed, classification)

    def _reconcile_request(
        self,
        request: BoundedAutonomyRequest,
        source_reason: str,
    ) -> BoundedAutonomyOutcome:
        try:
            prepared = self.control_state.load_prepared_change(request.proposal_id)
            observed = self.adapter.readback(prepared.target_key())
            classification = classify_readback(
                prepared,
                observed,
                source_reason=source_reason,
                unknown_reason="READBACK_INDETERMINATE",
            )
            return self._persist_classification(
                prepared,
                observed,
                classification,
            )
        except (ControlRejected, sqlite3.Error):
            return BoundedAutonomyOutcome(
                ExecutionStatus.UNKNOWN_RESULT,
                "CONTROL_STATE_UNAVAILABLE",
                None,
            )

    def _persist_classification(
        self,
        prepared: PreparedChange,
        observed: Any,
        classification: ReadbackClassification,
    ) -> BoundedAutonomyOutcome:
        try:
            self.control_state.finish_execution(
                prepared.execution_key(),
                classification.status,
                classification.reason_code,
                self.clock(),
            )
            self.write_window.settle(
                prepared.execution_key(),
                classification.status,
            )
        except (ControlRejected, sqlite3.Error):
            return BoundedAutonomyOutcome(
                ExecutionStatus.UNKNOWN_RESULT,
                "CONTROL_STATE_UNAVAILABLE",
                observed,
            )
        return BoundedAutonomyOutcome(
            classification.status,
            classification.reason_code,
            observed,
        )

    def _finish_active_as_blocked(
        self,
        execution_key: str,
        reason: str,
    ) -> None:
        try:
            execution = self.control_state.load_execution(execution_key)
            if execution.status in {
                ExecutionStatus.RESERVED,
                ExecutionStatus.IN_FLIGHT,
            }:
                self.control_state.finish_execution(
                    execution_key,
                    ExecutionStatus.BLOCKED,
                    reason,
                    self.clock(),
                )
        except (ControlRejected, sqlite3.Error):
            return

    def _state_failure_outcome(
        self,
        execution_key: str,
    ) -> BoundedAutonomyOutcome:
        try:
            execution = self.control_state.load_execution(execution_key)
        except (ControlRejected, sqlite3.Error):
            return BoundedAutonomyOutcome(
                ExecutionStatus.BLOCKED,
                "CONTROL_STATE_UNAVAILABLE",
                None,
            )
        status = (
            ExecutionStatus.UNKNOWN_RESULT
            if execution.status == ExecutionStatus.IN_FLIGHT
            else ExecutionStatus.BLOCKED
        )
        return BoundedAutonomyOutcome(
            status,
            "CONTROL_STATE_UNAVAILABLE",
            None,
        )
