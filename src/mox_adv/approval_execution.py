"""Approval-required policy and guarded fake execution orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Mapping, Optional, Tuple

from mox_adv.commands import CommandRejected, build_high_level_command
from mox_adv.control_state import (
    ControlRejected,
    DurableControlState,
    PreparedChange,
    TrustedScope,
)
from mox_adv.fake_write_adapter import AdapterTimeout, FakeWriteAdapter

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
    status: str
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
        if "WEEKLY_BUDGET" in prepared.action:
            return (
                1,
                int(self.policy["limits"]["platform_weekly_spend_rub"]) * 1_000_000,
            )
        return (1, 2**63 - 1)

    @staticmethod
    def _step(prepared: PreparedChange) -> int:
        if prepared.action in {
            "INCREASE_WEEKLY_BUDGET",
            "DECREASE_WEEKLY_BUDGET",
            "INCREASE_SEARCH_BID",
            "DECREASE_SEARCH_BID",
        }:
            return int(prepared.expected_diff.get("relative_step_percent", 101))
        return 0

    def _scope_matches_simulation(self, scope: TrustedScope) -> bool:
        binding = self.policy["bindings"]["simulation"]
        return (
            scope.organization == binding["organization"]
            and scope.connection == binding["connection"]
            and scope.account == binding["direct_account"]
        )

    def _api_method_allowed(self, action: str) -> bool:
        operation = {
            "INCREASE_WEEKLY_BUDGET": ("Campaigns", "update"),
            "DECREASE_WEEKLY_BUDGET": ("Campaigns", "update"),
            "INCREASE_SEARCH_BID": ("KeywordBids", "set"),
            "DECREASE_SEARCH_BID": ("KeywordBids", "set"),
            "SET_AD_VARIANT": ("Ads", "update"),
            "SUSPEND_CAMPAIGN": ("Campaigns", "suspend"),
            "RESUME_CAMPAIGN": ("Campaigns", "resume"),
        }.get(action)
        if operation is None:
            return False
        service, method = operation
        return any(
            item.get("system") == "DIRECT"
            and item.get("environment") == "production"
            and item.get("host") == "api.direct.yandex.com"
            and item.get("version") == "v501"
            and item.get("service") == service
            and item.get("method") == method
            and item.get("http_verb") == "POST"
            for item in self.policy["api_matrix"]
        )

    def _action_is_safe(
        self,
        prepared: PreparedChange,
        facts: ExecutionFacts,
    ) -> bool:
        action = prepared.action
        state_on = facts.campaign_state == "ON"
        sufficient = facts.clicks >= 50 and facts.conversions >= 3
        cpa = Decimal(facts.cpa_rub)
        utilization = Decimal(facts.budget_utilization_percent)
        ctr = Decimal(facts.ctr_percent)
        if action == "INCREASE_WEEKLY_BUDGET":
            return state_on and sufficient and cpa <= 1000 and utilization >= 90
        if action == "DECREASE_WEEKLY_BUDGET":
            return state_on and sufficient and cpa > 1000 and utilization >= 90
        if action == "INCREASE_SEARCH_BID":
            return (
                state_on
                and facts.campaign_strategy == "HIGHEST_POSITION"
                and sufficient
                and cpa <= 1000
                and utilization < 90
                and 50 <= facts.clicks <= 99
            )
        if action == "DECREASE_SEARCH_BID":
            return (
                state_on
                and facts.campaign_strategy == "HIGHEST_POSITION"
                and sufficient
                and cpa > 1000
                and utilization < 90
            )
        if action == "SET_AD_VARIANT":
            return state_on and sufficient and ctr < 1 and facts.impressions >= 5000
        if action == "SUSPEND_CAMPAIGN":
            return state_on and facts.conversions == 0 and facts.spend_rub >= 2000
        if action == "RESUME_CAMPAIGN":
            return (
                facts.campaign_state == "SUSPENDED"
                and facts.conversions >= 3
                and cpa <= 1000
            )
        return False


class ApprovalExecutionService:
    """Consume one exact approval and execute one fake-adapter command."""

    def __init__(
        self,
        policy: Mapping[str, Any],
        state: DurableControlState,
        adapter: FakeWriteAdapter,
        clock: Callable[[], Any],
    ) -> None:
        self.policy = ApprovalRequiredPolicy(policy)
        self.state = state
        self.adapter = adapter
        self.clock = clock

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        try:
            prepared = self.state.load_prepared_change(request.proposal_id)
            decision = self.policy.evaluate(prepared, request)
            if not decision.allowed:
                return ExecutionOutcome("BLOCKED", decision.reason_code, None)
            minimum, maximum = self.policy.numeric_bounds(prepared)
            command = build_high_level_command(prepared, minimum, maximum)
            if getattr(self.adapter, "is_fake", False) is not True:
                return ExecutionOutcome(
                    "BLOCKED",
                    "EXTERNAL_WRITE_EGRESS_DENIED",
                    None,
                )
            before = self.adapter.readback(prepared.target_key())
            if before not in {prepared.current_value, prepared.target_value}:
                return ExecutionOutcome("BLOCKED", "CURRENT_STATE_MISMATCH", before)
            reservation_status, reservation = self.state.reserve_execution(
                prepared,
                self.clock(),
            )
            if reservation_status != "RESERVED":
                return ExecutionOutcome(
                    reservation_status,
                    reservation.detail,
                    self.adapter.readback(prepared.target_key()),
                )
            if self.state.any_kill_switch_active(prepared.scope):
                self.state.finish_execution(
                    prepared.execution_key(),
                    "BLOCKED",
                    "KILL_SWITCH_ACTIVE",
                    self.clock(),
                )
                return ExecutionOutcome("BLOCKED", "KILL_SWITCH_ACTIVE", before)
            approval = self.state.load_active_approval(
                prepared.proposal_id,
                prepared.binding_hash(),
                self.clock(),
            )
            self.state.begin_execution(prepared, approval, self.clock())
            if before == prepared.target_value:
                self.state.finish_execution(
                    prepared.execution_key(),
                    "NO_CHANGE",
                    None,
                    self.clock(),
                )
                return ExecutionOutcome("NO_CHANGE", None, before)
            try:
                self.adapter.apply(prepared.target_key(), command)
            except AdapterTimeout:
                return self._reconcile_timeout(prepared)
            observed = self.adapter.readback(prepared.target_key())
            if observed == prepared.target_value:
                status = "APPLIED"
                reason = None
            elif observed == prepared.current_value:
                status = "FAILED"
                reason = "TARGET_STATE_NOT_APPLIED"
            else:
                status = "UNKNOWN_RESULT"
                reason = "READBACK_INDETERMINATE"
            self.state.finish_execution(
                prepared.execution_key(),
                status,
                reason,
                self.clock(),
            )
            return ExecutionOutcome(status, reason, observed)
        except CommandRejected as error:
            reason = (
                "OUT_OF_BOUNDS" if "OUT_OF_BOUNDS" in str(error) else "INVALID_INPUT"
            )
            return ExecutionOutcome("BLOCKED", reason, None)
        except ControlRejected as error:
            return ExecutionOutcome("BLOCKED", error.reason_code, None)

    def reconcile(self, execution_key: str) -> ExecutionOutcome:
        """Resolve a durable RESERVED or IN_FLIGHT operation without a retry."""

        try:
            execution = self.state.load_execution(execution_key)
            if execution.status in {"APPLIED", "NO_CHANGE"}:
                return ExecutionOutcome(
                    "ALREADY_PROCESSED",
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
                status = "APPLIED"
                reason = None
            elif observed == prepared.current_value:
                status = "FAILED"
                reason = "RESTART_SOURCE_STATE_CONFIRMED"
            else:
                status = "UNKNOWN_RESULT"
                reason = "RESTART_READBACK_INDETERMINATE"
            self.state.finish_execution(
                execution_key,
                status,
                reason,
                self.clock(),
            )
            return ExecutionOutcome(status, reason, observed)
        except ControlRejected as error:
            return ExecutionOutcome("BLOCKED", error.reason_code, None)

    def _reconcile_timeout(self, prepared: PreparedChange) -> ExecutionOutcome:
        observed = self.adapter.readback(prepared.target_key())
        if observed == prepared.target_value:
            status = "APPLIED"
            reason = None
        elif observed == prepared.current_value:
            status = "FAILED"
            reason = "TIMEOUT_SOURCE_STATE_CONFIRMED"
        else:
            status = "UNKNOWN_RESULT"
            reason = "TIMEOUT_READBACK_INDETERMINATE"
        self.state.finish_execution(
            prepared.execution_key(),
            status,
            reason,
            self.clock(),
        )
        return ExecutionOutcome(status, reason, observed)
