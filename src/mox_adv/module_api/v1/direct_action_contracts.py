"""Closed commands for one supported standalone Direct action."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Literal, Mapping, Union, cast

from mox_adv.module_api.v1.contract_validation import (
    ContractValidationError,
    exact_fields,
    object_value,
    one_of,
    text,
)

DIRECT_ACTION_COMMAND_SCHEMA_VERSION = "direct-action-command-v1"
DirectActionCommandKind = Literal["PLAN_INTENT", "EXECUTE_PROPOSAL"]
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


@dataclass(frozen=True)
class PlanDirectActionCommandV1:
    schema_version: str
    command: Literal["PLAN_INTENT"]
    action: Literal["INCREASE_WEEKLY_BUDGET"]
    relative_step_percent: int

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "PlanDirectActionCommandV1":
        exact_fields(
            value,
            field="direct_action_command",
            required=(
                "schema_version",
                "command",
                "action",
                "relative_step_percent",
            ),
        )
        relative_step = value["relative_step_percent"]
        if (
            isinstance(relative_step, bool)
            or not isinstance(relative_step, int)
            or not 1 <= relative_step <= 10
        ):
            raise ContractValidationError(
                "direct_action_command.relative_step_percent "
                "must be an integer from 1 to 10"
            )
        return cls(
            schema_version=one_of(
                text(
                    value["schema_version"],
                    "direct_action_command.schema_version",
                    maximum=64,
                ),
                "direct_action_command.schema_version",
                (DIRECT_ACTION_COMMAND_SCHEMA_VERSION,),
            ),
            command=cast(
                Literal["PLAN_INTENT"],
                one_of(
                    text(
                        value["command"],
                        "direct_action_command.command",
                        maximum=32,
                    ),
                    "direct_action_command.command",
                    ("PLAN_INTENT",),
                ),
            ),
            action=cast(
                Literal["INCREASE_WEEKLY_BUDGET"],
                one_of(
                    text(
                        value["action"],
                        "direct_action_command.action",
                        maximum=64,
                    ),
                    "direct_action_command.action",
                    ("INCREASE_WEEKLY_BUDGET",),
                ),
            ),
            relative_step_percent=relative_step,
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "command": self.command,
            "action": self.action,
            "relative_step_percent": self.relative_step_percent,
        }


@dataclass(frozen=True)
class ExecuteDirectActionCommandV1:
    schema_version: str
    command: Literal["EXECUTE_PROPOSAL"]
    proposal_id: str

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "ExecuteDirectActionCommandV1":
        exact_fields(
            value,
            field="direct_action_command",
            required=("schema_version", "command", "proposal_id"),
        )
        proposal_id = text(
            value["proposal_id"],
            "direct_action_command.proposal_id",
            maximum=128,
        )
        if _SAFE_IDENTIFIER.fullmatch(proposal_id) is None:
            raise ContractValidationError(
                "direct_action_command.proposal_id is invalid"
            )
        return cls(
            schema_version=one_of(
                text(
                    value["schema_version"],
                    "direct_action_command.schema_version",
                    maximum=64,
                ),
                "direct_action_command.schema_version",
                (DIRECT_ACTION_COMMAND_SCHEMA_VERSION,),
            ),
            command=cast(
                Literal["EXECUTE_PROPOSAL"],
                one_of(
                    text(
                        value["command"],
                        "direct_action_command.command",
                        maximum=32,
                    ),
                    "direct_action_command.command",
                    ("EXECUTE_PROPOSAL",),
                ),
            ),
            proposal_id=proposal_id,
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "command": self.command,
            "proposal_id": self.proposal_id,
        }


DirectActionCommandV1 = Union[
    PlanDirectActionCommandV1,
    ExecuteDirectActionCommandV1,
]


def direct_action_command_from_dict(
    value: Mapping[str, Any],
) -> DirectActionCommandV1:
    command = text(
        value.get("command"),
        "direct_action_command.command",
        maximum=32,
    )
    if command == "PLAN_INTENT":
        return PlanDirectActionCommandV1.from_dict(value)
    if command == "EXECUTE_PROPOSAL":
        return ExecuteDirectActionCommandV1.from_dict(value)
    raise ContractValidationError(
        "direct_action_command.command must be one of: "
        "PLAN_INTENT, EXECUTE_PROPOSAL"
    )


def direct_action_command_object(value: Any) -> DirectActionCommandV1:
    return direct_action_command_from_dict(
        object_value(value, "direct_action_command")
    )
