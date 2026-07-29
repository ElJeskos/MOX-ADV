"""Approval-required policy and guarded fake execution orchestration."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Mapping, Optional, Tuple

from mox_adv.commands import (
    ACTION_SPECS,
    ActionFamily,
    CommandRejected,
    OptimizationAction,
    build_high_level_command,
)
from mox_adv.control_state import (
    ControlRejected,
    DurableControlState,
    ExecutionStatus,
    PreparedChange,
    TrustedScope,
)
from mox_adv.egress import EgressDenied, HttpEgressGuard
from mox_adv.fake_write_adapter import AdapterTimeout
from mox_adv.write_window import DurableWriteWindowCoordinator

__all__ = [
    "ApprovalExecutionService",
    "ExecutionFacts",
    "ExecutionRequest",
    "PreparedChange",
    "TrustedScope",
]


@dataclass(frozen=True)
class ExecutionFacts:
    mode: str
    automation_enabled: bool
    comparability_status: str
    confidence_status: str
    financial_recommendations_allowed: bool
    direct_age_minutes: int
    metrika_age_minutes: int
    watermark_skew_minutes: int
    clicks: int
    conversions: int
    impressions: int
    spend_rub: int
    cpa_rub: str
    budget_utilization_percent: str
    ctr_percent: str
    campaign_state: str
    campaign_strategy: str
    current_fingerprint: str
    cooldown_active: bool
    actions_in_last_24h: int
    cumulative_daily_change_percent: int
    monetary_exposure_rub: int
    kill_switch_available: bool


@dataclass(frozen=True)
class ExecutionRequest:
    proposal_id: str
    execution_key: str
    scope: TrustedScope
    facts: ExecutionFacts


@dataclass(frozen=True)
class ExecutionOutcome:
    status: ExecutionStatus
    reason_code: Optional[str]
    observed_value: Any


@dataclass(frozen=True)
class PolicyOutcome:
    allowed: bool
    reason_code: Optional[str]


class ApprovalRequiredPolicy:
    """Evaluate every Gate 0 pre-write boundary deterministically."""

    def __init__(self, policy: Mapping[str, Any]) -> None:
        self.policy = policy

    def evaluate(
        self,
        prepared: PreparedChange,
        request: ExecutionRequest,
    ) -> PolicyOutcome:
        facts = request.facts
        checks = (
            (facts.mode == "APPROVAL_REQUIRED", "MODE_NOT_WRITE_CAPABLE"),
            (facts.automation_enabled, "AUTOMATION_DISABLED"),
            (request.scope == prepared.scope, "TARGET_BINDING_MISMATCH"),
            (
                request.execution_key == prepared.execution_key(),
                "EXECUTION_KEY_MISMATCH",
            ),
            (
                facts.comparability_status == "COMPARABLE"
                and facts.confidence_status == "READY"
                and facts.financial_recommendations_allowed,
                "SNAPSHOT_NOT_COMPARABLE",
            ),
            (
                facts.direct_age_minutes
                <= int(self.policy["timing"]["direct_freshness_minutes"]),
                "DIRECT_SNAPSHOT_STALE",
            ),
            (
                facts.metrika_age_minutes
                <= int(self.policy["timing"]["metrika_freshness_hours"]) * 60,
                "METRIKA_SNAPSHOT_STALE",
            ),
            (
                facts.watermark_skew_minutes
                <= int(self.policy["timing"]["maximum_watermark_skew_hours"]) * 60,
                "WATERMARK_SKEW_EXCEEDED",
            ),
            (
                facts.current_fingerprint == prepared.expected_fingerprint,
                "FINGERPRINT_MISMATCH",
            ),
            (not facts.cooldown_active, "COOLDOWN_ACTIVE"),
            (
                facts.actions_in_last_24h
                < int(self.policy["limits"]["mandate_actions_per_24h"]),
                "ACTION_QUOTA_REACHED",
            ),
            (
                facts.cumulative_daily_change_percent + self._step(prepared)
                <= int(
                    self.policy["limits"]["maximum_daily_cumulative_change_percent"]
                ),
                "DAILY_CHANGE_LIMIT_EXCEEDED",
            ),
            (
                facts.monetary_exposure_rub
                <= int(self.policy["limits"]["application_daily_spend_rub"]),
                "MONETARY_LIMIT_EXCEEDED",
            ),
            (facts.kill_switch_available, "KILL_SWITCH_UNAVAILABLE"),
            (
                prepared.scope.writer
                == self.policy["bindings"]["simulation"]["single_writer"],
                "SINGLE_WRITER_MISMATCH",
            ),
            (
                self._scope_matches_simulation(prepared.scope),
                "TRUSTED_SCOPE_MISMATCH",
            ),
            (
                prepared.policy_version == self.policy["policy_id"],
                "POLICY_VERSION_MISMATCH",
            ),
            (
                prepared.action
                in self.policy["actions"]["controlled_pilot_reversible"],
                "UNSUPPORTED_ACTION",
            ),
            (
                self._api_method_allowed(prepared.action),
                "API_METHOD_NOT_ALLOWLISTED",
            ),
            (self._action_is_safe(prepared, facts), "ACTION_POLICY_REJECTED"),
        )
        for passed, reason in checks:
            if not passed:
                return PolicyOutcome(False, reason)
        return PolicyOutcome(True, None)

    def numeric_bounds(self, prepared: PreparedChange) -> Tuple[int, int]:
        if ACTION_SPECS[prepared.action].family == ActionFamily.WEEKLY_BUDGET:
            return (
                1,
                int(self.policy["limits"]["platform_weekly_spend_rub"]) * 1_000_000,
            )
        return (1, 2**63 - 1)

    @staticmethod
    def _step(prepared: PreparedChange) -> int:
        if ACTION_SPECS[prepared.action].relative_percent is not None:
            return int(prepared.expected_diff.get("relative_step_percent", 101))
        return 0

    def _scope_matches_simulation(self, scope: TrustedScope) -> bool:
        binding = self.policy["bindings"]["simulation"]
        return (
            scope.organization == binding["organization"]
            and scope.connection == binding["connection"]
            and scope.account == binding["direct_account"]
        )

    def _api_method_allowed(self, action: OptimizationAction) -> bool:
        try:
            spec = ACTION_SPECS[OptimizationAction(action)]
        except (KeyError, ValueError):
            return False
        return any(
            item.get("system") == "DIRECT"
            and item.get("environment") == "production"
            and item.get("host") == "api.direct.yandex.com"
            and item.get("version") == "v501"
            and item.get("service") == spec.service
            and item.get("method") == spec.method
            and item.get("http_verb") == "POST"
            for item in self.policy["api_matrix"]
        )

    def _action_is_safe(
        self,
        prepared: PreparedChange,
        facts: ExecutionFacts,
    ) -> bool:
        state_on = facts.campaign_state == "ON"
        sufficient = facts.clicks >= 50 and facts.conversions >= 3
        cpa = Decimal(facts.cpa_rub)
        utilization = Decimal(facts.budget_utilization_percent)
        ctr = Decimal(facts.ctr_percent)
        checks = {
            OptimizationAction.INCREASE_WEEKLY_BUDGET: (
                state_on and sufficient and cpa <= 1000 and utilization >= 90
            ),
            OptimizationAction.DECREASE_WEEKLY_BUDGET: (
                state_on and sufficient and cpa > 1000 and utilization >= 90
            ),
            OptimizationAction.INCREASE_SEARCH_BID: (
                state_on
                and facts.campaign_strategy == "HIGHEST_POSITION"
                and sufficient
                and cpa <= 1000
                and utilization < 90
                and 50 <= facts.clicks <= 99
            ),
            OptimizationAction.DECREASE_SEARCH_BID: (
                state_on
                and facts.campaign_strategy == "HIGHEST_POSITION"
                and sufficient
                and cpa > 1000
                and utilization < 90
            ),
            OptimizationAction.SET_AD_VARIANT: (
                state_on and sufficient and ctr < 1 and facts.impressions >= 5000
            ),
            OptimizationAction.SUSPEND_CAMPAIGN: (
                state_on and facts.conversions == 0 and facts.spend_rub >= 2000
            ),
            OptimizationAction.RESUME_CAMPAIGN: (
                facts.campaign_state == "SUSPENDED"
                and facts.conversions >= 3
                and cpa <= 1000
            ),
        }
        return checks[prepared.action]


class ApprovalExecutionService:
    """Consume one exact approval and execute one fake-adapter command."""

    def __init__(
        self,
        policy: Mapping[str, Any],
        state: DurableControlState,
        adapter: Any,
        clock: Callable[[], Any],
    ) -> None:
        self.policy = ApprovalRequiredPolicy(policy)
        self.state = state
        self.adapter = adapter
        self.clock = clock
        self.egress_guard = HttpEgressGuard(policy)
        self.write_window = DurableWriteWindowCoordinator(
            state.path,
            policy,
            clock,
        )

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        try:
            prepared = self.state.load_prepared_change(request.proposal_id)
            decision = self.policy.evaluate(prepared, request)
            if not decision.allowed:
                return ExecutionOutcome(
                    ExecutionStatus.BLOCKED,
                    decision.reason_code,
                    None,
                )
            minimum, maximum = self.policy.numeric_bounds(prepared)
            command = build_high_level_command(prepared, minimum, maximum)
            self.egress_guard.enforce_adapter(self.adapter, command)
            before = self.adapter.readback(prepared.target_key())
            if before not in {prepared.current_value, prepared.target_value}:
                return ExecutionOutcome(
                    ExecutionStatus.BLOCKED,
                    "CURRENT_STATE_MISMATCH",
                    before,
                )
            approval = self.state.load_bound_approval(
                prepared.proposal_id,
                prepared.binding_hash(),
            )
            if before == prepared.target_value:
                reservation_status, reservation = self.state.reserve_execution(
                    prepared,
                    self.clock(),
                )
                if reservation_status != ExecutionStatus.RESERVED:
                    return ExecutionOutcome(
                        reservation_status,
                        reservation.detail,
                        before,
                    )
                self.state.begin_execution(prepared, approval, self.clock())
                self.state.release_approval_reservation(
                    approval.approval_id,
                    prepared.execution_key(),
                )
                self.state.finish_execution(
                    prepared.execution_key(),
                    ExecutionStatus.NO_CHANGE,
                    None,
                    self.clock(),
                )
                return ExecutionOutcome(ExecutionStatus.NO_CHANGE, None, before)
            try:
                send_status, execution = self.state.send_once(
                    prepared,
                    approval,
                    self.clock(),
                    lambda: self.adapter.apply(prepared.target_key(), command),
                    at_dispatch_boundary=lambda: self.write_window.reserve(
                        prepared.execution_key()
                    ),
                )
            except AdapterTimeout:
                return self._reconcile_timeout(prepared)
            if send_status != ExecutionStatus.IN_FLIGHT:
                return ExecutionOutcome(
                    send_status,
                    execution.detail,
                    self.adapter.readback(prepared.target_key()),
                )
            observed = self.adapter.readback(prepared.target_key())
            if observed == prepared.target_value:
                status = ExecutionStatus.APPLIED
                reason = None
            elif observed == prepared.current_value:
                status = ExecutionStatus.FAILED
                reason = "TARGET_STATE_NOT_APPLIED"
            else:
                status = ExecutionStatus.UNKNOWN_RESULT
                reason = "READBACK_INDETERMINATE"
            self.state.finish_execution(
                prepared.execution_key(),
                status,
                reason,
                self.clock(),
            )
            self.write_window.settle(prepared.execution_key(), status)
            return ExecutionOutcome(status, reason, observed)
        except CommandRejected as error:
            reason = (
                "OUT_OF_BOUNDS" if "OUT_OF_BOUNDS" in str(error) else "INVALID_INPUT"
            )
            return ExecutionOutcome(ExecutionStatus.BLOCKED, reason, None)
        except EgressDenied:
            return ExecutionOutcome(
                ExecutionStatus.BLOCKED,
                "EXTERNAL_WRITE_EGRESS_DENIED",
                None,
            )
        except ControlRejected as error:
            return ExecutionOutcome(
                ExecutionStatus.BLOCKED,
                error.reason_code,
                None,
            )
        except sqlite3.Error:
            try:
                execution = self.state.load_execution(request.execution_key)
            except (ControlRejected, sqlite3.Error):
                execution = None
            if execution is not None and execution.status == ExecutionStatus.IN_FLIGHT:
                return ExecutionOutcome(
                    ExecutionStatus.UNKNOWN_RESULT,
                    "CONTROL_STATE_UNAVAILABLE",
                    self.adapter.readback(execution.target_key),
                )
            return ExecutionOutcome(
                ExecutionStatus.BLOCKED,
                "CONTROL_STATE_UNAVAILABLE",
                None,
            )

    def reconcile(self, execution_key: str) -> ExecutionOutcome:
        """Resolve a durable RESERVED or IN_FLIGHT operation without a retry."""

        try:
            execution = self.state.load_execution(execution_key)
            if execution.status in {"APPLIED", "NO_CHANGE"}:
                return ExecutionOutcome(
                    ExecutionStatus.ALREADY_PROCESSED,
                    None,
                    self.adapter.readback(execution.target_key),
                )
            if execution.status not in {"RESERVED", "IN_FLIGHT"}:
                return ExecutionOutcome(
                    execution.status,
                    execution.detail,
                    self.adapter.readback(execution.target_key),
                )
            prepared = self.state.load_prepared_change(execution.proposal_id)
            observed = self.adapter.readback(prepared.target_key())
            if observed == prepared.target_value:
                status = ExecutionStatus.APPLIED
                reason = None
            elif observed == prepared.current_value:
                status = ExecutionStatus.FAILED
                reason = "RESTART_SOURCE_STATE_CONFIRMED"
            else:
                status = ExecutionStatus.UNKNOWN_RESULT
                reason = "RESTART_READBACK_INDETERMINATE"
            self.state.finish_execution(
                execution_key,
                status,
                reason,
                self.clock(),
            )
            self.write_window.settle(execution_key, status)
            return ExecutionOutcome(status, reason, observed)
        except ControlRejected as error:
            return ExecutionOutcome(
                ExecutionStatus.BLOCKED,
                error.reason_code,
                None,
            )

    def _reconcile_timeout(self, prepared: PreparedChange) -> ExecutionOutcome:
        observed = self.adapter.readback(prepared.target_key())
        if observed == prepared.target_value:
            status = ExecutionStatus.APPLIED
            reason = None
        elif observed == prepared.current_value:
            status = ExecutionStatus.FAILED
            reason = "TIMEOUT_SOURCE_STATE_CONFIRMED"
        else:
            status = ExecutionStatus.UNKNOWN_RESULT
            reason = "TIMEOUT_READBACK_INDETERMINATE"
        self.state.finish_execution(
            prepared.execution_key(),
            status,
            reason,
            self.clock(),
        )
        self.write_window.settle(prepared.execution_key(), status)
        return ExecutionOutcome(status, reason, observed)
