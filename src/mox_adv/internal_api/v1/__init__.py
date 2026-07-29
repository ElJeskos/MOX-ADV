"""Version 1 internal API boundaries for the modular monolith."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol

from mox_adv.contracts import (
    AnalyticsSummary,
    AuditVerification,
    ConnectedFixture,
    Decision,
    DirectCampaignStateBlock,
    DirectCampaignStateReadQuery,
    DirectReportBlock,
    DirectReportsReadQuery,
    ExecutionResult,
    IntegratedPerformanceSnapshot,
    IntegratedSnapshotDraft,
    MetrikaReportBlock,
    MetrikaReportReadQuery,
    NormalizedSnapshot,
    PersistedEvent,
    PolicyDecision,
    RunContext,
)


class ConnectorsAPI(Protocol):
    def read_fixture(
        self,
        context: RunContext,
        raw_fixture: Mapping[str, Any],
    ) -> ConnectedFixture: ...


class DirectReportsReadAPI(Protocol):
    def read_report(self, query: DirectReportsReadQuery) -> DirectReportBlock: ...


class DirectCampaignStateReadAPI(Protocol):
    def read_campaign_state(
        self,
        query: DirectCampaignStateReadQuery,
    ) -> DirectCampaignStateBlock: ...


class MetrikaReportReadAPI(Protocol):
    def read_metrika_report(
        self,
        query: MetrikaReportReadQuery,
    ) -> MetrikaReportBlock: ...


class NormalizationAPI(Protocol):
    def normalize(
        self,
        context: RunContext,
        connected: ConnectedFixture,
    ) -> NormalizedSnapshot: ...


class AnalyticsAPI(Protocol):
    def calculate(
        self,
        context: RunContext,
        snapshot: NormalizedSnapshot,
    ) -> AnalyticsSummary: ...


class IntegratedAnalyticsAPI(Protocol):
    def calculate(
        self,
        snapshot: IntegratedSnapshotDraft,
    ) -> IntegratedPerformanceSnapshot: ...


class DecisionAPI(Protocol):
    def decide(
        self,
        context: RunContext,
        summary: AnalyticsSummary,
    ) -> Decision: ...


class PolicyAPI(Protocol):
    def evaluate(
        self,
        context: RunContext,
        decision: Decision,
    ) -> PolicyDecision: ...


class ExecutionAPI(Protocol):
    def execute(
        self,
        context: RunContext,
        decision: Decision,
        policy_decision: PolicyDecision,
    ) -> ExecutionResult: ...


class AuditAPI(Protocol):
    def append(
        self,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> PersistedEvent: ...

    def seal(self) -> AuditVerification: ...

    def verify(self) -> AuditVerification: ...

    def export_jsonl(self, path: Path) -> None: ...
