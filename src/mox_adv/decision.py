"""Minimal deterministic decision boundary for the bootstrap."""

from __future__ import annotations

from mox_adv.contracts import AnalyticsSummary, Decision, RunContext


class DecisionEngineV1:
    def decide(
        self,
        context: RunContext,
        summary: AnalyticsSummary,
    ) -> Decision:
        del context
        if summary.impressions == 0:
            return Decision(
                action="REQUEST_HUMAN_HELP",
                reason_code="INSUFFICIENT_SAMPLE",
            )
        return Decision(action="KEEP", reason_code="BOOTSTRAP_OBSERVATION_ONLY")
