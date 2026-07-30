"""Typed campaign-creation payloads for the public module API v1 boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional, Tuple

from mox_adv.campaign_vocabulary import (
    CAMPAIGN_CREATION_RESULT_STATUS_VALUES,
    CAMPAIGN_SAGA_PUBLIC_STATUS_VALUES,
    CAMPAIGN_SAGA_STEP_VALUES,
)
from mox_adv.module_api.v1.contract_validation import (
    ContractValidationError,
    array_value,
    boolean,
    exact_fields,
    identifier,
    object_value,
    one_of,
    optional_text,
    text,
)
from mox_adv.recommend_contracts import CampaignDraftV1, SchemaValidationError

CAMPAIGN_CREATION_COMMAND_SCHEMA_VERSION = "campaign-creation-command-v1"
CAMPAIGN_CREATION_STATUSES = CAMPAIGN_CREATION_RESULT_STATUS_VALUES
CAMPAIGN_SAGA_STATUSES = CAMPAIGN_SAGA_PUBLIC_STATUS_VALUES
CAMPAIGN_SAGA_STEPS = CAMPAIGN_SAGA_STEP_VALUES


@dataclass(frozen=True)
class CreateCampaignCommandV1:
    """One exact approved campaign-creation request."""

    schema_version: str
    command: str
    run_id: str
    execution_key: str
    proposal_id: str
    approval_id: str
    reservation_id: str
    draft: CampaignDraftV1

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CreateCampaignCommandV1":
        field = "campaign_creation_command"
        exact_fields(
            value,
            field=field,
            required=(
                "schema_version",
                "command",
                "run_id",
                "execution_key",
                "proposal_id",
                "approval_id",
                "reservation_id",
                "draft",
            ),
        )
        try:
            draft = CampaignDraftV1.from_mapping(
                object_value(value["draft"], f"{field}.draft")
            )
        except SchemaValidationError as error:
            raise ContractValidationError(
                f"{field}.draft is invalid: {error}"
            ) from error
        return cls(
            schema_version=one_of(
                value["schema_version"],
                f"{field}.schema_version",
                (CAMPAIGN_CREATION_COMMAND_SCHEMA_VERSION,),
            ),
            command=one_of(
                value["command"],
                f"{field}.command",
                ("CREATE_CAMPAIGN",),
            ),
            run_id=identifier(value["run_id"], f"{field}.run_id"),
            execution_key=identifier(
                value["execution_key"],
                f"{field}.execution_key",
            ),
            proposal_id=identifier(
                value["proposal_id"],
                f"{field}.proposal_id",
            ),
            approval_id=identifier(
                value["approval_id"],
                f"{field}.approval_id",
            ),
            reservation_id=identifier(
                value["reservation_id"],
                f"{field}.reservation_id",
            ),
            draft=draft,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "command": self.command,
            "run_id": self.run_id,
            "execution_key": self.execution_key,
            "proposal_id": self.proposal_id,
            "approval_id": self.approval_id,
            "reservation_id": self.reservation_id,
            "draft": self.draft.as_dict(),
        }


@dataclass(frozen=True)
class CampaignCreatedObjectV1:
    """An actual provider object touched by the saga."""

    service: str
    object_id: str
    actual_type: str
    compensated: bool

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        field: str,
    ) -> "CampaignCreatedObjectV1":
        exact_fields(
            value,
            field=field,
            required=("service", "object_id", "actual_type", "compensated"),
        )
        return cls(
            service=one_of(
                value["service"],
                f"{field}.service",
                ("Campaigns", "AdGroups", "Ads", "Keywords"),
            ),
            object_id=identifier(value["object_id"], f"{field}.object_id"),
            actual_type=text(
                value["actual_type"],
                f"{field}.actual_type",
                maximum=128,
            ),
            compensated=boolean(
                value["compensated"],
                f"{field}.compensated",
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "object_id": self.object_id,
            "actual_type": self.actual_type,
            "compensated": self.compensated,
        }


@dataclass(frozen=True)
class CampaignReadbackV1:
    """Normalized identifiers from the persisted full-readback step."""

    campaign_ids: Tuple[str, ...]
    ad_group_ids: Tuple[str, ...]
    ad_ids: Tuple[str, ...]
    keyword_ids: Tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignReadbackV1":
        field = "campaign_creation_outcome.readback"
        names = (
            "campaign_ids",
            "ad_group_ids",
            "ad_ids",
            "keyword_ids",
        )
        exact_fields(value, field=field, required=names)
        parsed = {
            name: tuple(
                identifier(item, f"{field}.{name}[]")
                for item in array_value(value[name], f"{field}.{name}")
            )
            for name in names
        }
        if (
            len(parsed["campaign_ids"]) != 1
            or len(parsed["ad_group_ids"]) != 1
            or len(parsed["ad_ids"]) != 2
            or len(parsed["keyword_ids"]) != 1
        ):
            raise ContractValidationError(
                f"{field} must describe one campaign, one group, two ads, "
                "and one keyword"
            )
        return cls(**parsed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "campaign_ids": list(self.campaign_ids),
            "ad_group_ids": list(self.ad_group_ids),
            "ad_ids": list(self.ad_ids),
            "keyword_ids": list(self.keyword_ids),
        }


@dataclass(frozen=True)
class CampaignCreationOutcomeV1:
    """Closed saga outcome with a digest over all returned evidence."""

    execution_key: str
    status: str
    saga_status: str
    completed_steps: Tuple[str, ...]
    created_objects: Tuple[CampaignCreatedObjectV1, ...]
    readback: Optional[CampaignReadbackV1]
    detail: Optional[str]
    evidence_digest: str

    def __post_init__(self) -> None:
        identifier(
            self.execution_key,
            "campaign_creation_outcome.execution_key",
        )
        one_of(
            self.status,
            "campaign_creation_outcome.status",
            CAMPAIGN_CREATION_STATUSES,
        )
        one_of(
            self.saga_status,
            "campaign_creation_outcome.saga_status",
            CAMPAIGN_SAGA_STATUSES,
        )
        expected_steps = CAMPAIGN_SAGA_STEPS[: len(self.completed_steps)]
        if self.completed_steps != expected_steps:
            raise ContractValidationError(
                "campaign_creation_outcome.completed_steps must be an ordered "
                "prefix of the campaign saga"
            )
        if len(self.evidence_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.evidence_digest
        ):
            raise ContractValidationError(
                "campaign_creation_outcome.evidence_digest must be a SHA-256 hex digest"
            )

    @classmethod
    def create(
        cls,
        *,
        execution_key: str,
        status: str,
        saga_status: str,
        completed_steps: Tuple[str, ...],
        created_objects: Tuple[CampaignCreatedObjectV1, ...],
        readback: Optional[CampaignReadbackV1],
        detail: Optional[str],
    ) -> "CampaignCreationOutcomeV1":
        outcome = cls(
            execution_key=execution_key,
            status=status,
            saga_status=saga_status,
            completed_steps=completed_steps,
            created_objects=created_objects,
            readback=readback,
            detail=detail,
            evidence_digest="0" * 64,
        )
        return replace(
            outcome,
            evidence_digest=outcome.computed_evidence_digest(),
        )

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "CampaignCreationOutcomeV1":
        field = "campaign_creation_outcome"
        exact_fields(
            value,
            field=field,
            required=(
                "execution_key",
                "status",
                "saga_status",
                "completed_steps",
                "created_objects",
                "readback",
                "detail",
                "evidence_digest",
            ),
        )
        readback_value = value["readback"]
        outcome = cls(
            execution_key=identifier(
                value["execution_key"],
                f"{field}.execution_key",
            ),
            status=text(value["status"], f"{field}.status", maximum=32),
            saga_status=text(
                value["saga_status"],
                f"{field}.saga_status",
                maximum=32,
            ),
            completed_steps=tuple(
                one_of(item, f"{field}.completed_steps[]", CAMPAIGN_SAGA_STEPS)
                for item in array_value(
                    value["completed_steps"],
                    f"{field}.completed_steps",
                )
            ),
            created_objects=tuple(
                CampaignCreatedObjectV1.from_dict(
                    object_value(item, f"{field}.created_objects[{index}]"),
                    field=f"{field}.created_objects[{index}]",
                )
                for index, item in enumerate(
                    array_value(
                        value["created_objects"],
                        f"{field}.created_objects",
                    )
                )
            ),
            readback=(
                None
                if readback_value is None
                else CampaignReadbackV1.from_dict(
                    object_value(readback_value, f"{field}.readback")
                )
            ),
            detail=optional_text(
                value["detail"],
                f"{field}.detail",
                maximum=2_000,
            ),
            evidence_digest=text(
                value["evidence_digest"],
                f"{field}.evidence_digest",
                minimum=64,
                maximum=64,
            ),
        )
        if outcome.evidence_digest != outcome.computed_evidence_digest():
            raise ContractValidationError(
                "campaign_creation_outcome evidence digest does not match its facts"
            )
        return outcome

    def evidence_facts(self) -> dict[str, Any]:
        return {
            "execution_key": self.execution_key,
            "status": self.status,
            "saga_status": self.saga_status,
            "completed_steps": list(self.completed_steps),
            "created_objects": [item.as_dict() for item in self.created_objects],
            "readback": (None if self.readback is None else self.readback.as_dict()),
            "detail": self.detail,
        }

    def computed_evidence_digest(self) -> str:
        canonical = json.dumps(
            self.evidence_facts(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.evidence_facts(),
            "evidence_digest": self.evidence_digest,
        }


__all__ = [
    "CAMPAIGN_CREATION_COMMAND_SCHEMA_VERSION",
    "CAMPAIGN_CREATION_STATUSES",
    "CAMPAIGN_SAGA_STATUSES",
    "CAMPAIGN_SAGA_STEPS",
    "CampaignCreatedObjectV1",
    "CampaignCreationOutcomeV1",
    "CampaignReadbackV1",
    "CreateCampaignCommandV1",
]
