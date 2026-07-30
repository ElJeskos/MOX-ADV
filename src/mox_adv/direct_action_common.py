"""Pure calculations and public projections for standalone Direct actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional, Tuple

from mox_adv.approval_execution import ExecutionFacts
from mox_adv.commands import ACTION_SPECS, ActionFamily, OptimizationAction
from mox_adv.control_state import (
    ExecutionStatus,
    PreparedChange,
    TrustedScope,
    canonical_hash,
)
from mox_adv.direct_action_runtime import DirectActionRuntimeV1
from mox_adv.direct_metrics import DirectMetric, calculate_direct_metrics
from mox_adv.direct_provider import DirectObservationV1
from mox_adv.environment import ExecutionEnvironment
from mox_adv.module_api.v1 import (
    MetricValueV1,
    ModuleAssessmentV1,
    ModuleRecommendationV1,
    ModuleRequestV1,
    ModuleStatus,
)

SUPPORTED_ACTION = OptimizationAction.INCREASE_WEEKLY_BUDGET
ACTION_OPERATION_TYPE = "APPLY_OPTIMIZATION"
TRIGGER_REASON_CODE = "BUDGET_UTILIZATION_AT_OR_ABOVE_THRESHOLD"


@dataclass(frozen=True)
class DirectActionContext:
    """One validated request paired with its evidence and trusted reread."""

    request: ModuleRequestV1
    now: datetime
    evidence: DirectObservationV1
    current: DirectObservationV1
    metrics: Mapping[str, DirectMetric]


@dataclass(frozen=True)
class DirectActionEligibilitySnapshot:
    """The provider/evidence facts consumed by the shared policy rule."""

    campaign_state: str
    campaign_strategy: str
    clicks: int
    conversions: int
    impressions: int
    spend_rub: int
    cpa_rub: str
    budget_utilization_percent: str
    ctr_percent: str


def eligibility_snapshot(
    context: DirectActionContext,
) -> DirectActionEligibilitySnapshot:
    assert context.evidence.conversions is not None
    return DirectActionEligibilitySnapshot(
        campaign_state=context.current.state.campaign_state,
        campaign_strategy=context.current.state.strategy,
        clicks=context.evidence.clicks,
        conversions=context.evidence.conversions,
        impressions=context.evidence.impressions,
        spend_rub=context.evidence.cost_micros // 1_000_000,
        cpa_rub=str(context.metrics["cpa_rub"]),
        budget_utilization_percent=str(context.metrics["budget_utilization_percent"]),
        ctr_percent=str(context.metrics["ctr_percent"]),
    )


def calculated_metrics(
    evidence: DirectObservationV1,
    current: DirectObservationV1,
    now: datetime,
) -> Mapping[str, DirectMetric]:
    return calculate_direct_metrics(
        impressions=evidence.impressions,
        clicks=evidence.clicks,
        cost_micros=evidence.cost_micros,
        current_weekly_budget_micros=current.state.current_weekly_budget_micros,
        budget_period_start=current.state.budget_period_start,
        budget_period_end=current.state.budget_period_end,
        observed_at=now,
        conversions=evidence.conversions,
    )


def state_fingerprint(
    request: ModuleRequestV1,
    observation: DirectObservationV1,
) -> str:
    state = observation.state
    return canonical_hash(
        {
            "connection_id": request.connection_ref.connection_id,
            "organization_id": request.scope.organization_id,
            "account_id": request.scope.account_id,
            "campaign_id": request.scope.campaign_id,
            "campaign_state": state.campaign_state,
            "strategy": state.strategy,
            "current_weekly_budget_micros": state.current_weekly_budget_micros,
            "current_search_bid_micros": state.current_search_bid_micros,
            "ad_variant": state.ad_variant,
            "object_config_version": state.object_config_version,
        }
    )


def proposal_projection(
    runtime: DirectActionRuntimeV1,
    metrics: Mapping[str, DirectMetric],
) -> Mapping[str, Any]:
    if runtime.paired_context is not None:
        return runtime.paired_context.projection
    return {
        "observed_facts": ["BUDGET_UTILIZATION_AT_OR_ABOVE_THRESHOLD"],
        "budget_utilization": metrics["budget_utilization_percent"],
        "policy_limits": {
            "maximum_step_percent": runtime.policy["limits"]["maximum_step_percent"]
        },
    }


def trusted_scope(
    runtime: DirectActionRuntimeV1,
    request: ModuleRequestV1,
) -> TrustedScope:
    assert request.scope.account_id is not None
    assert request.scope.campaign_id is not None
    return TrustedScope(
        organization=request.scope.organization_id,
        connection=request.connection_ref.connection_id,
        account=request.scope.account_id,
        campaign=request.scope.campaign_id,
        writer=str(runtime.policy["bindings"]["simulation"]["single_writer"]),
    )


def execution_result_metrics(
    calculated: Mapping[str, DirectMetric],
    current: DirectObservationV1,
    prepared: PreparedChange,
    facts: ExecutionFacts,
) -> Tuple[MetricValueV1, ...]:
    common = (
        MetricValueV1("impressions", facts.impressions, "COUNT"),
        MetricValueV1("clicks", facts.clicks, "COUNT"),
        MetricValueV1(
            "cost_micros",
            facts.spend_rub * 1_000_000,
            "MICROS_RUB",
        ),
        MetricValueV1("conversions", facts.conversions, "COUNT"),
        MetricValueV1("ctr_percent", facts.ctr_percent, "PERCENT"),
        MetricValueV1("cpa_rub", facts.cpa_rub, "RUB"),
        MetricValueV1(
            "budget_utilization_percent",
            facts.budget_utilization_percent,
            "PERCENT",
        ),
        MetricValueV1("pacing_percent", calculated["pacing_percent"], "PERCENT"),
        MetricValueV1(
            "current_weekly_budget_micros",
            current.state.current_weekly_budget_micros,
            "MICROS_RUB",
        ),
    )
    target: tuple[MetricValueV1, ...]
    family = ACTION_SPECS[prepared.action].family
    if family is ActionFamily.WEEKLY_BUDGET:
        target = (
            MetricValueV1(
                "target_weekly_budget_micros",
                prepared.target_value,
                "MICROS_RUB",
            ),
        )
    elif family is ActionFamily.SEARCH_BID:
        target = (
            MetricValueV1(
                "current_search_bid_micros",
                current.state.current_search_bid_micros,
                "MICROS_RUB",
            ),
            MetricValueV1(
                "target_search_bid_micros",
                prepared.target_value,
                "MICROS_RUB",
            ),
        )
    elif family is ActionFamily.CAMPAIGN_STATE:
        target = (
            MetricValueV1(
                "current_campaign_state",
                current.state.campaign_state,
                "CODE",
            ),
            MetricValueV1(
                "target_campaign_state",
                prepared.target_value,
                "CODE",
            ),
        )
    else:
        target = (
            MetricValueV1(
                "current_ad_variant",
                current.state.ad_variant,
                "CODE",
            ),
            MetricValueV1(
                "target_ad_variant",
                prepared.target_value,
                "CODE",
            ),
        )
    return common + target


def result_metrics(
    calculated: Mapping[str, DirectMetric],
    current: DirectObservationV1,
    target_budget: int,
) -> Tuple[MetricValueV1, ...]:
    """Preserve the standalone Direct planning projection."""

    return (
        MetricValueV1("impressions", calculated["impressions"], "COUNT"),
        MetricValueV1("clicks", calculated["clicks"], "COUNT"),
        MetricValueV1("cost_micros", calculated["cost_micros"], "MICROS_RUB"),
        MetricValueV1("conversions", calculated["conversions"], "COUNT"),
        MetricValueV1("ctr_percent", calculated["ctr_percent"], "PERCENT"),
        MetricValueV1("cpa_rub", calculated["cpa_rub"], "RUB"),
        MetricValueV1(
            "budget_utilization_percent",
            calculated["budget_utilization_percent"],
            "PERCENT",
        ),
        MetricValueV1("pacing_percent", calculated["pacing_percent"], "PERCENT"),
        MetricValueV1(
            "current_weekly_budget_micros",
            current.state.current_weekly_budget_micros,
            "MICROS_RUB",
        ),
        MetricValueV1(
            "target_weekly_budget_micros",
            target_budget,
            "MICROS_RUB",
        ),
    )


def decision_summary(
    runtime: DirectActionRuntimeV1,
    action: OptimizationAction = SUPPORTED_ACTION,
) -> Tuple[ModuleAssessmentV1, Tuple[ModuleRecommendationV1, ...]]:
    summaries = {
        OptimizationAction.INCREASE_WEEKLY_BUDGET: (
            "Increase the weekly budget by the approved step.",
            "The deterministic policy accepted the validated budget change.",
        ),
        OptimizationAction.DECREASE_WEEKLY_BUDGET: (
            "Decrease the weekly budget by the approved step.",
            "The deterministic policy accepted the validated budget change.",
        ),
        OptimizationAction.INCREASE_SEARCH_BID: (
            "Increase the search bid by the approved step.",
            "The deterministic policy accepted the validated bid change.",
        ),
        OptimizationAction.DECREASE_SEARCH_BID: (
            "Decrease the search bid by the approved step.",
            "The deterministic policy accepted the validated bid change.",
        ),
        OptimizationAction.SET_AD_VARIANT: (
            "Activate the approved ad variant.",
            "The deterministic policy accepted the validated ad change.",
        ),
        OptimizationAction.SUSPEND_CAMPAIGN: (
            "Suspend the approved campaign.",
            "The deterministic policy accepted the validated state change.",
        ),
        OptimizationAction.RESUME_CAMPAIGN: (
            "Resume the approved campaign.",
            "The deterministic policy accepted the validated state change.",
        ),
    }
    summary, rationale = summaries[action]
    return (
        ModuleAssessmentV1(
            summary=(
                "Typed evidence and the current Direct target passed "
                "deterministic validation."
            ),
            data_quality_status="READY",
            confidence_status="READY",
        ),
        (
            ModuleRecommendationV1(
                code=action.value,
                summary=summary,
                rationale=rationale,
                executable=runtime.environment is ExecutionEnvironment.TEST,
            ),
        ),
    )


def public_execution_status(
    status: ExecutionStatus,
    reason_code: Optional[str],
) -> Tuple[ModuleStatus, str, Optional[str]]:
    if status in {
        ExecutionStatus.APPLIED,
        ExecutionStatus.NO_CHANGE,
        ExecutionStatus.ALREADY_PROCESSED,
    }:
        return "SUCCEEDED", status.value, reason_code
    if status in {
        ExecutionStatus.RESERVED,
        ExecutionStatus.IN_FLIGHT,
    }:
        return "BLOCKED", "BLOCKED", "EXECUTION_IN_FLIGHT"
    if status is ExecutionStatus.UNKNOWN_RESULT:
        return "FAILED", "UNKNOWN_RESULT", reason_code or "UNKNOWN_RESULT"
    if status is ExecutionStatus.FAILED:
        return "FAILED", "FAILED", reason_code or "EXECUTION_FAILED"
    return "BLOCKED", "BLOCKED", reason_code or "EXECUTION_BLOCKED"


def age_minutes(now: datetime, observed_at: datetime) -> int:
    return max(0, int((now - observed_at).total_seconds() // 60))


def watermark_skew_minutes(left: str, right: str) -> int:
    left_at = datetime.fromisoformat(left.replace("Z", "+00:00"))
    right_at = datetime.fromisoformat(right.replace("Z", "+00:00"))
    return int(abs((left_at - right_at).total_seconds()) // 60)
