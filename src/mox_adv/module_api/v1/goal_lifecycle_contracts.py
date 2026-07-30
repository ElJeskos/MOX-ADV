"""Typed goal-lifecycle payloads composed into the module API v1 boundary."""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, ClassVar

from mox_adv.module_api.v1.contract_validation import (
    ContractValidationError,
    array_value,
    boolean,
    count,
    exact_fields,
    identifier,
    object_value,
    one_of,
    text,
    timestamp,
)

GOAL_CANDIDATE_INPUT_SCHEMA_VERSION = "goal-candidate-input-v1"
GOAL_LIFECYCLE_COMMAND_SCHEMA_VERSION = "goal-lifecycle-command-v1"


@dataclass(frozen=True)
class GoalCandidateInputV1:
    """Customer input translated into the unchanged legacy goal candidate."""

    schema_version: str
    name: str
    event: str
    site_location: str
    goal_type: str
    business_meaning: str
    priority: int
    duplicate_signals: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> GoalCandidateInputV1:
        field = "goal_lifecycle_command.candidate"
        fields = (
            "schema_version",
            "name",
            "event",
            "site_location",
            "type",
            "business_meaning",
            "priority",
            "duplicate_signals",
        )
        exact_fields(value, field=field, required=fields)
        priority = count(value["priority"], f"{field}.priority")
        if priority < 1:
            raise ContractValidationError(
                f"{field}.priority must be a positive integer"
            )
        duplicate_signals = tuple(
            text(item, f"{field}.duplicate_signals[]", maximum=500)
            for item in array_value(
                value["duplicate_signals"],
                f"{field}.duplicate_signals",
            )
        )
        if len(duplicate_signals) > 128 or len(set(duplicate_signals)) != len(
            duplicate_signals
        ):
            raise ContractValidationError(
                f"{field}.duplicate_signals must contain at most 128 unique values"
            )
        return cls(
            schema_version=one_of(
                value["schema_version"],
                f"{field}.schema_version",
                (GOAL_CANDIDATE_INPUT_SCHEMA_VERSION,),
            ),
            name=text(value["name"], f"{field}.name", maximum=128),
            event=text(value["event"], f"{field}.event", maximum=128),
            site_location=text(
                value["site_location"],
                f"{field}.site_location",
                maximum=500,
            ),
            goal_type=text(value["type"], f"{field}.type", maximum=64),
            business_meaning=text(
                value["business_meaning"],
                f"{field}.business_meaning",
                maximum=500,
            ),
            priority=priority,
            duplicate_signals=duplicate_signals,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "event": self.event,
            "site_location": self.site_location,
            "type": self.goal_type,
            "business_meaning": self.business_meaning,
            "priority": self.priority,
            "duplicate_signals": list(self.duplicate_signals),
        }

    def as_legacy_payload(self) -> dict[str, Any]:
        """Translate only at the existing lifecycle seam."""

        value = self.as_dict()
        value["schema_version"] = "goal-candidate-v1"
        return value


@dataclass(frozen=True)
class GoalEventEvidenceV1:
    """Browser evidence accepted by technical lifecycle verification."""

    event: str
    selector: str
    trigger_selector: str
    counter_id: str
    http_method: str
    request_url: str
    emitted_count: int
    intercepted_locally: bool
    real_network_requests: int

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> GoalEventEvidenceV1:
        field = "goal_lifecycle_command.event_evidence"
        fields = (
            "event",
            "selector",
            "trigger_selector",
            "counter_id",
            "http_method",
            "request_url",
            "emitted_count",
            "intercepted_locally",
            "real_network_requests",
        )
        exact_fields(value, field=field, required=fields)
        return cls(
            event=text(value["event"], f"{field}.event", maximum=128),
            selector=text(value["selector"], f"{field}.selector", maximum=500),
            trigger_selector=text(
                value["trigger_selector"],
                f"{field}.trigger_selector",
                maximum=500,
            ),
            counter_id=identifier(value["counter_id"], f"{field}.counter_id"),
            http_method=one_of(
                value["http_method"],
                f"{field}.http_method",
                ("POST",),
            ),
            request_url=text(
                value["request_url"],
                f"{field}.request_url",
                maximum=2_000,
            ),
            emitted_count=count(
                value["emitted_count"],
                f"{field}.emitted_count",
            ),
            intercepted_locally=boolean(
                value["intercepted_locally"],
                f"{field}.intercepted_locally",
            ),
            real_network_requests=count(
                value["real_network_requests"],
                f"{field}.real_network_requests",
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "selector": self.selector,
            "trigger_selector": self.trigger_selector,
            "counter_id": self.counter_id,
            "http_method": self.http_method,
            "request_url": self.request_url,
            "emitted_count": self.emitted_count,
            "intercepted_locally": self.intercepted_locally,
            "real_network_requests": self.real_network_requests,
        }


class GoalLifecycleCommandV1(ABC):
    """Closed base for one of six typed lifecycle commands."""

    action: ClassVar[str]
    schema_version: ClassVar[str] = GOAL_LIFECYCLE_COMMAND_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> GoalLifecycleCommandV1:
        action = one_of(
            value.get("action"),
            "goal_lifecycle_command.action",
            tuple(GOAL_LIFECYCLE_COMMAND_TYPES),
        )
        return GOAL_LIFECYCLE_COMMAND_TYPES[action].from_dict(value)

    @abstractmethod
    def as_dict(self) -> dict[str, Any]:
        """Return the closed public JSON representation."""

    def _envelope(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "action": self.action,
        }


class CandidateGoalLifecycleCommandV1(GoalLifecycleCommandV1):
    """Typed base for actions targeting an existing candidate."""

    candidate_id: str


def _command_fields(
    value: Mapping[str, Any],
    action: str,
    fields: tuple[str, ...],
) -> None:
    exact_fields(
        value,
        field="goal_lifecycle_command",
        required=("schema_version", "action", *fields),
    )
    one_of(
        value["schema_version"],
        "goal_lifecycle_command.schema_version",
        (GOAL_LIFECYCLE_COMMAND_SCHEMA_VERSION,),
    )
    one_of(value["action"], "goal_lifecycle_command.action", (action,))


@dataclass(frozen=True)
class CreateGoalCandidateCommandV1(GoalLifecycleCommandV1):
    action: ClassVar[str] = "CREATE_CANDIDATE"
    run_id: str
    proposal_id: str
    reservation_id: str
    authority_id: str
    candidate: GoalCandidateInputV1

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> CreateGoalCandidateCommandV1:
        fields = (
            "run_id",
            "proposal_id",
            "reservation_id",
            "authority_id",
            "candidate",
        )
        _command_fields(value, cls.action, fields)
        return cls(
            run_id=identifier(value["run_id"], "goal_lifecycle_command.run_id"),
            proposal_id=identifier(
                value["proposal_id"],
                "goal_lifecycle_command.proposal_id",
            ),
            reservation_id=identifier(
                value["reservation_id"],
                "goal_lifecycle_command.reservation_id",
            ),
            authority_id=identifier(
                value["authority_id"],
                "goal_lifecycle_command.authority_id",
            ),
            candidate=GoalCandidateInputV1.from_dict(
                object_value(
                    value["candidate"],
                    "goal_lifecycle_command.candidate",
                )
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            **self._envelope(),
            "run_id": self.run_id,
            "proposal_id": self.proposal_id,
            "reservation_id": self.reservation_id,
            "authority_id": self.authority_id,
            "candidate": self.candidate.as_dict(),
        }


@dataclass(frozen=True)
class PublishGoalEventCommandV1(CandidateGoalLifecycleCommandV1):
    action: ClassVar[str] = "PUBLISH_EVENT"
    candidate_id: str
    authority_id: str
    site_zone: str
    expected_version: str

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> PublishGoalEventCommandV1:
        fields = (
            "candidate_id",
            "authority_id",
            "site_zone",
            "expected_version",
        )
        _command_fields(value, cls.action, fields)
        return cls(
            candidate_id=identifier(
                value["candidate_id"],
                "goal_lifecycle_command.candidate_id",
            ),
            authority_id=identifier(
                value["authority_id"],
                "goal_lifecycle_command.authority_id",
            ),
            site_zone=text(
                value["site_zone"],
                "goal_lifecycle_command.site_zone",
                maximum=500,
            ),
            expected_version=text(
                value["expected_version"],
                "goal_lifecycle_command.expected_version",
                maximum=500,
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            **self._envelope(),
            "candidate_id": self.candidate_id,
            "authority_id": self.authority_id,
            "site_zone": self.site_zone,
            "expected_version": self.expected_version,
        }


@dataclass(frozen=True)
class VerifyGoalDeliveryCommandV1(CandidateGoalLifecycleCommandV1):
    action: ClassVar[str] = "VERIFY_DELIVERY"
    candidate_id: str
    event_evidence: GoalEventEvidenceV1

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> VerifyGoalDeliveryCommandV1:
        fields = ("candidate_id", "event_evidence")
        _command_fields(value, cls.action, fields)
        return cls(
            candidate_id=identifier(
                value["candidate_id"],
                "goal_lifecycle_command.candidate_id",
            ),
            event_evidence=GoalEventEvidenceV1.from_dict(
                object_value(
                    value["event_evidence"],
                    "goal_lifecycle_command.event_evidence",
                )
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            **self._envelope(),
            "candidate_id": self.candidate_id,
            "event_evidence": self.event_evidence.as_dict(),
        }


@dataclass(frozen=True)
class DecideGoalSemanticsCommandV1(CandidateGoalLifecycleCommandV1):
    action: ClassVar[str] = "DECIDE_BUSINESS_SEMANTICS"
    candidate_id: str
    approved: bool
    reviewer: str

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> DecideGoalSemanticsCommandV1:
        fields = ("candidate_id", "approved", "reviewer")
        _command_fields(value, cls.action, fields)
        return cls(
            candidate_id=identifier(
                value["candidate_id"],
                "goal_lifecycle_command.candidate_id",
            ),
            approved=boolean(
                value["approved"],
                "goal_lifecycle_command.approved",
            ),
            reviewer=identifier(
                value["reviewer"],
                "goal_lifecycle_command.reviewer",
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            **self._envelope(),
            "candidate_id": self.candidate_id,
            "approved": self.approved,
            "reviewer": self.reviewer,
        }


@dataclass(frozen=True)
class EvaluateGoalEligibilityCommandV1(CandidateGoalLifecycleCommandV1):
    action: ClassVar[str] = "EVALUATE_OPTIMIZATION_ELIGIBILITY"
    candidate_id: str
    observed_at: str
    sample_clicks: int
    sample_conversions: int

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> EvaluateGoalEligibilityCommandV1:
        fields = (
            "candidate_id",
            "observed_at",
            "sample_clicks",
            "sample_conversions",
        )
        _command_fields(value, cls.action, fields)
        return cls(
            candidate_id=identifier(
                value["candidate_id"],
                "goal_lifecycle_command.candidate_id",
            ),
            observed_at=timestamp(
                value["observed_at"],
                "goal_lifecycle_command.observed_at",
            ),
            sample_clicks=count(
                value["sample_clicks"],
                "goal_lifecycle_command.sample_clicks",
            ),
            sample_conversions=count(
                value["sample_conversions"],
                "goal_lifecycle_command.sample_conversions",
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            **self._envelope(),
            "candidate_id": self.candidate_id,
            "observed_at": self.observed_at,
            "sample_clicks": self.sample_clicks,
            "sample_conversions": self.sample_conversions,
        }


@dataclass(frozen=True)
class CleanupRejectedGoalCommandV1(CandidateGoalLifecycleCommandV1):
    action: ClassVar[str] = "CLEANUP_REJECTED_CANDIDATE"
    candidate_id: str
    run_id: str

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> CleanupRejectedGoalCommandV1:
        fields = ("candidate_id", "run_id")
        _command_fields(value, cls.action, fields)
        return cls(
            candidate_id=identifier(
                value["candidate_id"],
                "goal_lifecycle_command.candidate_id",
            ),
            run_id=identifier(value["run_id"], "goal_lifecycle_command.run_id"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            **self._envelope(),
            "candidate_id": self.candidate_id,
            "run_id": self.run_id,
        }


GOAL_LIFECYCLE_COMMAND_TYPES = {
    command.action: command
    for command in (
        CreateGoalCandidateCommandV1,
        PublishGoalEventCommandV1,
        VerifyGoalDeliveryCommandV1,
        DecideGoalSemanticsCommandV1,
        EvaluateGoalEligibilityCommandV1,
        CleanupRejectedGoalCommandV1,
    )
}


@dataclass(frozen=True)
class GoalLifecycleEvidenceOutcomeV1:
    """Sanitized event and polling facts preserved in the public result."""

    event: str
    counter_id: str
    emitted_count: int
    duplicate_event_absent: bool
    intercepted_locally: bool
    real_network_requests: int
    delivery_observed: bool
    virtual_elapsed_minutes: int
    poll_count: int
    checked_at: str

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> GoalLifecycleEvidenceOutcomeV1:
        field = "lifecycle_outcome.event_evidence"
        fields = (
            "event",
            "counter_id",
            "emitted_count",
            "duplicate_event_absent",
            "intercepted_locally",
            "real_network_requests",
            "delivery_observed",
            "virtual_elapsed_minutes",
            "poll_count",
            "checked_at",
        )
        exact_fields(value, field=field, required=fields)
        return cls(
            event=text(value["event"], f"{field}.event", maximum=128),
            counter_id=identifier(value["counter_id"], f"{field}.counter_id"),
            emitted_count=count(
                value["emitted_count"],
                f"{field}.emitted_count",
            ),
            duplicate_event_absent=boolean(
                value["duplicate_event_absent"],
                f"{field}.duplicate_event_absent",
            ),
            intercepted_locally=boolean(
                value["intercepted_locally"],
                f"{field}.intercepted_locally",
            ),
            real_network_requests=count(
                value["real_network_requests"],
                f"{field}.real_network_requests",
            ),
            delivery_observed=boolean(
                value["delivery_observed"],
                f"{field}.delivery_observed",
            ),
            virtual_elapsed_minutes=count(
                value["virtual_elapsed_minutes"],
                f"{field}.virtual_elapsed_minutes",
            ),
            poll_count=count(value["poll_count"], f"{field}.poll_count"),
            checked_at=timestamp(value["checked_at"], f"{field}.checked_at"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "counter_id": self.counter_id,
            "emitted_count": self.emitted_count,
            "duplicate_event_absent": self.duplicate_event_absent,
            "intercepted_locally": self.intercepted_locally,
            "real_network_requests": self.real_network_requests,
            "delivery_observed": self.delivery_observed,
            "virtual_elapsed_minutes": self.virtual_elapsed_minutes,
            "poll_count": self.poll_count,
            "checked_at": self.checked_at,
        }


@dataclass(frozen=True)
class GoalLifecycleOutcomeV1:
    """Typed lifecycle state with a digest over all returned evidence."""

    action: str
    lifecycle_status: str
    candidate_id: str
    goal_id: str
    candidate_status: str
    technical_status: str
    optimization_eligible: bool
    cleaned_up: bool
    event_evidence: GoalLifecycleEvidenceOutcomeV1 | None
    evidence_digest: str

    def __post_init__(self) -> None:
        one_of(
            self.action,
            "lifecycle_outcome.action",
            tuple(GOAL_LIFECYCLE_COMMAND_TYPES),
        )
        one_of(
            self.lifecycle_status,
            "lifecycle_outcome.lifecycle_status",
            (
                "CANDIDATE",
                "EVENT_PUBLISHED",
                "TECHNICALLY_VERIFIED",
                "TECHNICALLY_INCONCLUSIVE",
                "APPROVED",
                "REJECTED",
                "OPTIMIZATION_ELIGIBLE",
                "OPTIMIZATION_INELIGIBLE",
                "CLEANED_UP",
            ),
        )
        identifier(self.candidate_id, "lifecycle_outcome.candidate_id")
        identifier(self.goal_id, "lifecycle_outcome.goal_id")
        one_of(
            self.candidate_status,
            "lifecycle_outcome.candidate_status",
            ("CANDIDATE", "APPROVED", "REJECTED"),
        )
        one_of(
            self.technical_status,
            "lifecycle_outcome.technical_status",
            ("PENDING", "VERIFIED", "INCONCLUSIVE"),
        )
        boolean(
            self.optimization_eligible,
            "lifecycle_outcome.optimization_eligible",
        )
        boolean(self.cleaned_up, "lifecycle_outcome.cleaned_up")
        if len(self.evidence_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.evidence_digest
        ):
            raise ContractValidationError(
                "lifecycle_outcome.evidence_digest must be a SHA-256 hex digest"
            )

    @classmethod
    def create(
        cls,
        *,
        action: str,
        lifecycle_status: str,
        candidate_id: str,
        goal_id: str,
        candidate_status: str,
        technical_status: str,
        optimization_eligible: bool,
        cleaned_up: bool,
        event_evidence: GoalLifecycleEvidenceOutcomeV1 | None,
    ) -> GoalLifecycleOutcomeV1:
        outcome = cls(
            action=action,
            lifecycle_status=lifecycle_status,
            candidate_id=candidate_id,
            goal_id=goal_id,
            candidate_status=candidate_status,
            technical_status=technical_status,
            optimization_eligible=optimization_eligible,
            cleaned_up=cleaned_up,
            event_evidence=event_evidence,
            evidence_digest="0" * 64,
        )
        return replace(
            outcome,
            evidence_digest=outcome.computed_evidence_digest(),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> GoalLifecycleOutcomeV1:
        fields = (
            "action",
            "lifecycle_status",
            "candidate_id",
            "goal_id",
            "candidate_status",
            "technical_status",
            "optimization_eligible",
            "cleaned_up",
            "event_evidence",
            "evidence_digest",
        )
        exact_fields(value, field="lifecycle_outcome", required=fields)
        event_evidence = value["event_evidence"]
        outcome = cls(
            action=one_of(
                value["action"],
                "lifecycle_outcome.action",
                tuple(GOAL_LIFECYCLE_COMMAND_TYPES),
            ),
            lifecycle_status=text(
                value["lifecycle_status"],
                "lifecycle_outcome.lifecycle_status",
                maximum=128,
            ),
            candidate_id=identifier(
                value["candidate_id"],
                "lifecycle_outcome.candidate_id",
            ),
            goal_id=identifier(
                value["goal_id"],
                "lifecycle_outcome.goal_id",
            ),
            candidate_status=text(
                value["candidate_status"],
                "lifecycle_outcome.candidate_status",
                maximum=32,
            ),
            technical_status=text(
                value["technical_status"],
                "lifecycle_outcome.technical_status",
                maximum=32,
            ),
            optimization_eligible=boolean(
                value["optimization_eligible"],
                "lifecycle_outcome.optimization_eligible",
            ),
            cleaned_up=boolean(
                value["cleaned_up"],
                "lifecycle_outcome.cleaned_up",
            ),
            event_evidence=(
                None
                if event_evidence is None
                else GoalLifecycleEvidenceOutcomeV1.from_dict(
                    object_value(
                        event_evidence,
                        "lifecycle_outcome.event_evidence",
                    )
                )
            ),
            evidence_digest=text(
                value["evidence_digest"],
                "lifecycle_outcome.evidence_digest",
                minimum=64,
                maximum=64,
            ),
        )
        if outcome.evidence_digest != outcome.computed_evidence_digest():
            raise ContractValidationError(
                "lifecycle_outcome evidence digest does not match its facts"
            )
        return outcome

    def evidence_facts(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "lifecycle_status": self.lifecycle_status,
            "candidate_id": self.candidate_id,
            "goal_id": self.goal_id,
            "candidate_status": self.candidate_status,
            "technical_status": self.technical_status,
            "optimization_eligible": self.optimization_eligible,
            "cleaned_up": self.cleaned_up,
            "event_evidence": (
                None if self.event_evidence is None else self.event_evidence.as_dict()
            ),
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
