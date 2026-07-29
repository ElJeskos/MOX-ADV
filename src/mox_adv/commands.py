"""Typed high-level change commands with deterministic target calculation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping, Protocol, Union


class CommandRejected(ValueError):
    """A high-level command cannot be built without changing the approved diff."""


class PreparedCommandSource(Protocol):
    @property
    def action(self) -> str: ...

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
    action: str
    target_value: Any


@dataclass(frozen=True)
class HighLevelCommandBase:
    action: str
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

    action = prepared.action
    current = prepared.current_value
    target = prepared.target_value
    diff = dict(prepared.expected_diff)
    if diff.get("operation") != action:
        raise CommandRejected("INVALID_INPUT: expected diff operation is not exact.")

    if action in {
        "INCREASE_WEEKLY_BUDGET",
        "DECREASE_WEEKLY_BUDGET",
        "INCREASE_SEARCH_BID",
        "DECREASE_SEARCH_BID",
    }:
        if isinstance(current, bool) or not isinstance(current, int):
            raise CommandRejected("INVALID_INPUT: current numeric value is invalid.")
        step = 10 if action.startswith("INCREASE") else -10
        exact_target = calculate_relative_target(current, step)
        if target != exact_target or diff != {
            "operation": action,
            "relative_step_percent": 10,
        }:
            raise CommandRejected("INVALID_INPUT: numeric diff is not exact.")
        if exact_target < minimum_value or exact_target > maximum_value:
            raise CommandRejected("OUT_OF_BOUNDS: target value exceeds an exact limit.")
        rollback = RollbackCommand(
            action=(
                action.replace("INCREASE", "DECREASE")
                if action.startswith("INCREASE")
                else action.replace("DECREASE", "INCREASE")
            ),
            target_value=current,
        )
        command_type = (
            WeeklyBudgetCommand if "WEEKLY_BUDGET" in action else SearchBidCommand
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

    if action == "SET_AD_VARIANT":
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

    expected_states = {
        "SUSPEND_CAMPAIGN": ("ON", "SUSPENDED"),
        "RESUME_CAMPAIGN": ("SUSPENDED", "ON"),
    }
    if action in expected_states:
        expected_current, expected_target = expected_states[action]
        if current != expected_current or target != expected_target:
            raise CommandRejected(
                "INVALID_INPUT: campaign state transition is invalid."
            )
        if diff != {"operation": action, "target_state": target}:
            raise CommandRejected("INVALID_INPUT: campaign state diff is not exact.")
        inverse = (
            "RESUME_CAMPAIGN" if action == "SUSPEND_CAMPAIGN" else "SUSPEND_CAMPAIGN"
        )
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
            rollback=RollbackCommand(action=inverse, target_value=current),
        )

    raise CommandRejected("UNSUPPORTED_ACTION: high-level command is not supported.")


def _authority_fields(
    prepared: PreparedCommandSource,
    action: str,
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
