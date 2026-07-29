"""Executor that can only produce a local no-write simulation result."""

from __future__ import annotations

from mox_adv.contracts import (
    Decision,
    ExecutionResult,
    PolicyDecision,
    RunContext,
)
from mox_adv.errors import RunRejectedError


class SimulationExecutorV1:
    def execute(
        self,
        context: RunContext,
        decision: Decision,
        policy_decision: PolicyDecision,
    ) -> ExecutionResult:
        if (
            context.mode != "SIMULATION"
            or not policy_decision.allowed
            or policy_decision.external_write_egress
        ):
            raise RunRejectedError(
                "EXTERNAL_WRITE_EGRESS_DENIED",
                "execution",
                "The executor denied an operation outside safe simulation.",
            )
        return ExecutionResult(
            execution_status="NO_CHANGE",
            external_write_sent=False,
            technical_command="simulate:" + decision.action,
        )
