"""Fail-closed simulation policy for the bootstrap."""

from __future__ import annotations

from mox_adv.contracts import Decision, PolicyDecision, RunContext


class SimulationPolicyV1:
    def evaluate(
        self,
        context: RunContext,
        decision: Decision,
    ) -> PolicyDecision:
        allowed = context.mode == "SIMULATION" and decision.action in {
            "KEEP",
            "REQUEST_HUMAN_HELP",
        }
        return PolicyDecision(
            allowed=allowed,
            reason_code=(
                "SIMULATION_NO_WRITE" if allowed else "EXTERNAL_WRITE_EGRESS_DENIED"
            ),
            external_write_egress=False,
        )
