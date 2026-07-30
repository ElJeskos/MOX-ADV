"""Technical delivery evidence kept separate from business approval."""

# ruff: noqa: UP045

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from mox_adv.goal_contracts import GoalTechnicalStatus


@dataclass(frozen=True)
class GoalEventEvidence:
    event: str
    selector: str
    trigger_selector: str
    counter_id: str
    http_method: str
    request_url: str
    emitted_count: int
    intercepted_locally: bool
    real_network_requests: int


@dataclass(frozen=True)
class GoalTechnicalEvidence:
    candidate_id: str
    counter_id: str
    goal_id: str
    goal_type: str
    site_zone: str
    event: str
    selector: str
    trigger_selector: str
    http_method: str
    request_url: str
    classification: str
    emitted_count: int
    duplicate_event_absent: bool
    intercepted_locally: bool
    real_network_requests: int
    delivery_observed: bool
    status: GoalTechnicalStatus
    virtual_elapsed_minutes: int
    poll_count: int
    external_reason: Optional[str]
    checked_at: str
    author: str
    configuration_version: str
