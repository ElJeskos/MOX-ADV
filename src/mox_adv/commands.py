"""Typed high-level change commands with deterministic target calculation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any, Mapping, Optional, Protocol, Union


class CommandRejected(ValueError):
    """A high-level command cannot be built without changing the approved diff."""


class OptimizationAction(str, Enum):
    INCREASE_WEEKLY_BUDGET = "INCREASE_WEEKLY_BUDGET"
    DECREASE_WEEKLY_BUDGET = "DECREASE_WEEKLY_BUDGET"
    INCREASE_SEARCH_BID = "INCREASE_SEARCH_BID"
    DECREASE_SEARCH_BID = "DECREASE_SEARCH_BID"
    SET_AD_VARIANT = "SET_AD_VARIANT"
    SUSPEND_CAMPAIGN = "SUSPEND_CAMPAIGN"
    RESUME_CAMPAIGN = "RESUME_CAMPAIGN"


class ActionFamily(str, Enum):
    WEEKLY_BUDGET = "weekly_budget"
    SEARCH_BID = "search_bid"
    AD_VARIANT = "ad_variant"
    CAMPAIGN_STATE = "campaign_state"


@dataclass(frozen=True)
class ActionSpec:
    family: ActionFamily
    service: str
    method: str
    relative_percent: Optional[int] = None
    source_state: Optional[str] = None
    target_state: Optional[str] = None
    rollback_action: Optional[OptimizationAction] = None


ACTION_SPECS = {
    OptimizationAction.INCREASE_WEEKLY_BUDGET: ActionSpec(
        ActionFamily.WEEKLY_BUDGET,
        "Campaigns",
        "update",
        10,
        rollback_action=OptimizationAction.DECREASE_WEEKLY_BUDGET,
    ),
    OptimizationAction.DECREASE_WEEKLY_BUDGET: ActionSpec(
        ActionFamily.WEEKLY_BUDGET,
        "Campaigns",
        "update",
        -10,
        rollback_action=OptimizationAction.INCREASE_WEEKLY_BUDGET,
    ),
    OptimizationAction.INCREASE_SEARCH_BID: ActionSpec(
        ActionFamily.SEARCH_BID,
        "KeywordBids",
        "set",
        10,
        rollback_action=OptimizationAction.DECREASE_SEARCH_BID,
    ),
    OptimizationAction.DECREASE_SEARCH_BID: ActionSpec(
        ActionFamily.SEARCH_BID,
        "KeywordBids",
        "set",
        -10,
        rollback_action=OptimizationAction.INCREASE_SEARCH_BID,
    ),
    OptimizationAction.SET_AD_VARIANT: ActionSpec(
        ActionFamily.AD_VARIANT,
        "Ads",
        "update",
        rollback_action=OptimizationAction.SET_AD_VARIANT,
    ),
    OptimizationAction.SUSPEND_CAMPAIGN: ActionSpec(
        ActionFamily.CAMPAIGN_STATE,
        "Campaigns",
        "suspend",
        source_state="ON",
        target_state="SUSPENDED",
        rollback_action=OptimizationAction.RESUME_CAMPAIGN,
    ),
    OptimizationAction.RESUME_CAMPAIGN: ActionSpec(
        ActionFamily.CAMPAIGN_STATE,
        "Campaigns",
        "resume",
        source_state="SUSPENDED",
        target_state="ON",
        rollback_action=OptimizationAction.SUSPEND_CAMPAIGN,
    ),
}


class PreparedCommandSource(Protocol):
    @property
    def action(self) -> OptimizationAction: ...

    @property
    def current_value(self) -> Any: ...

    @property
    def target_value(self) -> Any: ...

    @property
    def expected_diff(self) -> Mapping[str, Any]: ...

    @property
    def scope(self) -> Any: ...

    @property
    def proposal_id(self) -> str: ...

    @property
    def expected_fingerprint(self) -> str: ...

    def execution_key(self) -> str: ...


@dataclass(frozen=True)
class RollbackCommand:
    action: OptimizationAction
    target_value: Any


@dataclass(frozen=True)
class HighLevelCommandBase:
    action: OptimizationAction
    current_value: Any
    target_value: Any
    dry_run: bool
    expected_diff: Mapping[str, Any]
    organization: str
    connection: str
    account: str
    campaign: str
    proposal_id: str
    execution_key: str
    expected_fingerprint: str
    preconditions: tuple[str, ...]
    numeric_limits: Mapping[str, int]
    readback_required: bool
    rollback: RollbackCommand


@dataclass(frozen=True)
class WeeklyBudgetCommand(HighLevelCommandBase):
    """A typed Campaigns.update weekly-budget command."""


@dataclass(frozen=True)
class SearchBidCommand(HighLevelCommandBase):
    """A typed KeywordBids.set search-bid command."""


@dataclass(frozen=True)
class AdVariantCommand(HighLevelCommandBase):
    """A typed Ads.update variant command."""


@dataclass(frozen=True)
class CampaignStateCommand(HighLevelCommandBase):
    """A typed Campaigns.suspend or Campaigns.resume command."""


HighLevelCommand = Union[
    WeeklyBudgetCommand,
    SearchBidCommand,
    AdVariantCommand,
    CampaignStateCommand,
]


def calculate_relative_target(current_value: int, percent: int) -> int:
    """Apply an integer percentage using the normative ROUND_HALF_UP rule."""

    if isinstance(current_value, bool) or not isinstance(current_value, int):
        raise CommandRejected("INVALID_INPUT: current value must be an integer.")
    if isinstance(percent, bool) or not isinstance(percent, int):
        raise CommandRejected("INVALID_INPUT: percent must be an integer.")
    multiplier = Decimal(100 + percent) / Decimal(100)
    return int(
        (Decimal(current_value) * multiplier).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def build_high_level_command(
    prepared: PreparedCommandSource,
    minimum_value: int,
    maximum_value: int,
) -> HighLevelCommand:
    """Build only the exact typed command represented by an approved proposal."""

    try:
        action = OptimizationAction(prepared.action)
    except ValueError as error:
        raise CommandRejected(
            "UNSUPPORTED_ACTION: high-level command is not supported."
        ) from error
    spec = ACTION_SPECS[action]
    current = prepared.current_value
    target = prepared.target_value
    diff = dict(prepared.expected_diff)
    if diff.get("operation") != action:
        raise CommandRejected("INVALID_INPUT: expected diff operation is not exact.")

    if spec.relative_percent is not None:
        if isinstance(current, bool) or not isinstance(current, int):
            raise CommandRejected("INVALID_INPUT: current numeric value is invalid.")
        exact_target = calculate_relative_target(current, spec.relative_percent)
        if target != exact_target or diff != {
            "operation": action,
            "relative_step_percent": 10,
        }:
            raise CommandRejected("INVALID_INPUT: numeric diff is not exact.")
        if exact_target < minimum_value or exact_target > maximum_value:
            raise CommandRejected("OUT_OF_BOUNDS: target value exceeds an exact limit.")
        assert spec.rollback_action is not None
        rollback = RollbackCommand(
            action=spec.rollback_action,
            target_value=current,
        )
        command_type = (
            WeeklyBudgetCommand
            if spec.family == ActionFamily.WEEKLY_BUDGET
            else SearchBidCommand
        )
        return command_type(
            **_authority_fields(
                prepared,
                action,
                current,
                exact_target,
                diff,
                minimum_value,
                maximum_value,
            ),
            rollback=rollback,
        )

    if spec.family == ActionFamily.AD_VARIANT:
        if current not in {"A", "B"} or target not in {"A", "B"} or current == target:
            raise CommandRejected("INVALID_INPUT: ad variant transition is invalid.")
        if diff != {"operation": action, "variant_id": target}:
            raise CommandRejected("INVALID_INPUT: ad variant diff is not exact.")
        return AdVariantCommand(
            **_authority_fields(
                prepared,
                action,
                current,
                target,
                diff,
                minimum_value,
                maximum_value,
            ),
            rollback=RollbackCommand(action=action, target_value=current),
        )

    if spec.family == ActionFamily.CAMPAIGN_STATE:
        if current != spec.source_state or target != spec.target_state:
            raise CommandRejected(
                "INVALID_INPUT: campaign state transition is invalid."
            )
        if diff != {"operation": action, "target_state": target}:
            raise CommandRejected("INVALID_INPUT: campaign state diff is not exact.")
        assert spec.rollback_action is not None
        return CampaignStateCommand(
            **_authority_fields(
                prepared,
                action,
                current,
                target,
                diff,
                minimum_value,
                maximum_value,
            ),
            rollback=RollbackCommand(
                action=spec.rollback_action,
                target_value=current,
            ),
        )

    raise CommandRejected("UNSUPPORTED_ACTION: high-level command is not supported.")


def _authority_fields(
    prepared: PreparedCommandSource,
    action: OptimizationAction,
    current_value: Any,
    target_value: Any,
    expected_diff: Mapping[str, Any],
    minimum_value: int,
    maximum_value: int,
) -> dict[str, Any]:
    scope = prepared.scope
    return {
        "action": action,
        "current_value": current_value,
        "target_value": target_value,
        "dry_run": True,
        "expected_diff": dict(expected_diff),
        "organization": scope.organization,
        "connection": scope.connection,
        "account": scope.account,
        "campaign": scope.campaign,
        "proposal_id": prepared.proposal_id,
        "execution_key": prepared.execution_key(),
        "expected_fingerprint": prepared.expected_fingerprint,
        "preconditions": (
            "DRY_RUN_SUCCEEDED",
            "FINGERPRINT_MATCH",
            "READBACK_REQUIRED",
        ),
        "numeric_limits": {
            "minimum_value": minimum_value,
            "maximum_value": maximum_value,
        },
        "readback_required": True,
    }
