"""Deterministic Gate 0 bounded-autonomy policy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Optional

from mox_adv.autonomy_contracts import BoundedAutonomyRequest
from mox_adv.commands import ACTION_SPECS, ActionFamily, OptimizationAction
from mox_adv.control_state import PreparedChange


@dataclass(frozen=True)
class _PolicyOutcome:
    allowed: bool
    reason_code: Optional[str]


class BoundedAutonomyPolicy:
    """Evaluate every deterministic Gate 0 boundary before reservation."""

    def __init__(self, policy: Mapping[str, Any]) -> None:
        self.policy = policy

    def evaluate(
        self,
        prepared: PreparedChange,
        request: BoundedAutonomyRequest,
    ) -> _PolicyOutcome:
        checks = (
            (request.mode == "BOUNDED_AUTONOMY", "MODE_NOT_WRITE_CAPABLE"),
            (request.automation_enabled, "AUTOMATION_DISABLED"),
            (request.scope == prepared.scope, "TARGET_BINDING_MISMATCH"),
            (
                request.execution_key == prepared.execution_key(),
                "EXECUTION_KEY_MISMATCH",
            ),
            (
                prepared.action.value in self.policy["actions"]["bounded_autonomy"],
                "UNSUPPORTED_ACTION",
            ),
            (
                prepared.action.value
                not in self.policy["actions"]["always_require_approval"],
                "APPROVAL_REQUIRED",
            ),
            (
                request.comparability_status == "COMPARABLE"
                and request.confidence_status == "READY"
                and request.financial_recommendations_allowed,
                "SNAPSHOT_NOT_COMPARABLE",
            ),
            (
                request.direct_age_minutes
                <= int(self.policy["timing"]["direct_freshness_minutes"]),
                "DIRECT_SNAPSHOT_STALE",
            ),
            (
                request.metrika_age_minutes
                <= int(self.policy["timing"]["metrika_freshness_hours"]) * 60,
                "METRIKA_SNAPSHOT_STALE",
            ),
            (
                request.watermark_skew_minutes
                <= int(self.policy["timing"]["maximum_watermark_skew_hours"]) * 60,
                "WATERMARK_SKEW_EXCEEDED",
            ),
            (
                request.current_fingerprint == prepared.expected_fingerprint,
                "FINGERPRINT_MISMATCH",
            ),
            (
                prepared.scope.writer
                == self.policy["bindings"]["simulation"]["single_writer"],
                "SINGLE_WRITER_MISMATCH",
            ),
            (
                prepared.policy_version == self.policy["policy_id"],
                "POLICY_VERSION_MISMATCH",
            ),
            (
                self._api_method_allowed(prepared.action),
                "API_METHOD_NOT_ALLOWLISTED",
            ),
            (
                self._action_is_safe(prepared, request),
                "ACTION_POLICY_REJECTED",
            ),
        )
        for passed, reason in checks:
            if not passed:
                return _PolicyOutcome(False, reason)
        return _PolicyOutcome(True, None)

    def numeric_bounds(self, prepared: PreparedChange) -> tuple[int, int]:
        if ACTION_SPECS[prepared.action].family == ActionFamily.WEEKLY_BUDGET:
            return (
                1,
                int(self.policy["limits"]["platform_weekly_spend_rub"]) * 1_000_000,
            )
        return (1, 2**63 - 1)

    def _api_method_allowed(self, action: OptimizationAction) -> bool:
        spec = ACTION_SPECS[action]
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

    @staticmethod
    def _action_is_safe(
        prepared: PreparedChange,
        request: BoundedAutonomyRequest,
    ) -> bool:
        cpa = Decimal(request.cpa_rub)
        utilization = Decimal(request.budget_utilization_percent)
        if prepared.action == OptimizationAction.DECREASE_SEARCH_BID:
            return (
                request.campaign_state == "ON"
                and request.campaign_strategy == "HIGHEST_POSITION"
                and request.clicks >= 50
                and request.conversions >= 3
                and cpa > 1000
                and utilization < 90
            )
        if prepared.action == OptimizationAction.SUSPEND_CAMPAIGN:
            return (
                request.campaign_state == "ON"
                and request.conversions == 0
                and request.spend_rub >= 2000
            )
        return False
