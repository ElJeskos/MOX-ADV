"""Pure calculations and public projections for standalone Direct actions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping, Optional, Tuple

from mox_adv.commands import OptimizationAction
from mox_adv.control_state import (
    ExecutionStatus,
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
    PlanDirectActionCommandV1,
)

SUPPORTED_ACTION = OptimizationAction.INCREASE_WEEKLY_BUDGET
ACTION_OPERATION_TYPE = "APPLY_OPTIMIZATION"


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
    return {
        "observed_facts": ["BUDGET_UTILIZATION_AT_OR_ABOVE_THRESHOLD"],
        "budget_utilization": metrics["budget_utilization_percent"],
        "policy_limits": {
            "maximum_step_percent": runtime.policy["limits"][
                "maximum_step_percent"
            ]
        },
    }


def proposal_id(
    request: ModuleRequestV1,
    command: PlanDirectActionCommandV1,
) -> str:
    canonical = json.dumps(
        {
            "idempotency_key": request.idempotency_key,
            "scope": request.scope.as_dict(),
            "command": command.as_dict(),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return "direct-action-" + digest[:32]


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


def result_metrics(
    calculated: Mapping[str, DirectMetric],
    current: DirectObservationV1,
    target_budget: int,
) -> Tuple[MetricValueV1, ...]:
    return (
        MetricValueV1("impressions", calculated["impressions"], "COUNT"),
        MetricValueV1("clicks", calculated["clicks"], "COUNT"),
        MetricValueV1("conversions", calculated["conversions"], "COUNT"),
        MetricValueV1("cpa_rub", calculated["cpa_rub"], "RUB"),
        MetricValueV1(
            "budget_utilization_percent",
            calculated["budget_utilization_percent"],
            "PERCENT",
        ),
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
) -> Tuple[ModuleAssessmentV1, Tuple[ModuleRecommendationV1, ...]]:
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
                code="INCREASE_WEEKLY_BUDGET",
                summary="Increase the weekly budget by the approved step.",
                rationale=(
                    "The deterministic policy accepted the validated "
                    "evidence and current target state."
                ),
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
