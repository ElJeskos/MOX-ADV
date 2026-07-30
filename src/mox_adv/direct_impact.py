"""Headless Direct exposure of the existing deterministic impact evaluator."""

from __future__ import annotations

from typing import Any, Mapping

from mox_adv.direct_analysis import DIRECT_IDENTITY
from mox_adv.impact import ImpactEvaluator, ImpactRejected
from mox_adv.module_analysis import terminal_module_result
from mox_adv.module_api.v1 import (
    MODULE_RESULT_SCHEMA_VERSION,
    ImpactEvaluationCommandV1,
    ImpactEvaluationOutcomeV1,
    MetricValueV1,
    ModuleAssessmentV1,
    ModuleDecisionFactsV1,
    ModuleDecisionRecordStoreV1,
    ModuleDecisionV1,
    ModuleErrorV1,
    ModuleRecommendationV1,
    ModuleRequestV1,
    ModuleResultV1,
    ModuleWarningV1,
)

_RECOMMENDATIONS = {
    "KEEP_CHANGE": (
        "KEEP_CHANGE",
        "Keep the observed change.",
        "The existing impact policy classified the observed result for retention.",
    ),
    "ROLLBACK_CHANGE": (
        "ROLLBACK_CHANGE",
        "Prepare a rollback for separate authorization.",
        "The existing impact policy classified the observed result for rollback.",
    ),
    "ADJUST_CHANGE": (
        "ADJUST_CHANGE",
        "Prepare an adjusted proposal for separate authorization.",
        "The existing impact policy classified the observed result for adjustment.",
    ),
    "ESCALATE_TO_HUMAN": (
        "REQUEST_HUMAN_REVIEW",
        "Request human review.",
        "The existing impact policy cannot support an automated next step.",
    ),
}


class StandaloneDirectImpactEvaluationV1:
    """Return one read-only impact decision through ModuleResultV1."""

    def __init__(
        self,
        *,
        policy: Mapping[str, Any],
        decision_records: ModuleDecisionRecordStoreV1,
    ) -> None:
        self._evaluator = ImpactEvaluator(policy)
        self._decision_records = decision_records

    def invoke(self, request: ModuleRequestV1) -> ModuleResultV1:
        command = request.impact_evaluation_command
        if not isinstance(command, ImpactEvaluationCommandV1):
            return self._rejected(
                request,
                "DIRECT_IMPACT_COMMAND_REQUIRED",
                "A typed impact evaluation command is required.",
            )
        if (
            request.scope.campaign_id != command.baseline.campaign
            or request.scope.campaign_id != command.post_change.campaign
        ):
            return self._rejected(
                request,
                "DIRECT_IMPACT_SCOPE_MISMATCH",
                "Impact observations must match the requested campaign scope.",
            )
        try:
            report = self._evaluator.evaluate(command.to_domain())
        except ImpactRejected as error:
            reason = str(error)
            if reason in {
                "OBSERVATION_WINDOW_ACTIVE",
                "DELAYED_CONVERSION_WINDOW_ACTIVE",
            }:
                return terminal_module_result(
                    module=DIRECT_IDENTITY,
                    request=request,
                    status="BLOCKED",
                    error=ModuleErrorV1(
                        code=reason,
                        message=(
                            "Impact evaluation is blocked until the existing "
                            "observation constraints complete."
                        ),
                        field="impact_evaluation_command.evaluated_at",
                        retryable=True,
                    ),
                )
            return self._rejected(request, "DIRECT_IMPACT_REJECTED", reason)

        outcome = ImpactEvaluationOutcomeV1.from_report(report)
        change = report.metric_changes["cpa_rub"]
        metrics = (
            MetricValueV1("baseline_cpa_rub", change["baseline"], "RUB"),
            MetricValueV1("post_change_cpa_rub", change["post_change"], "RUB"),
            MetricValueV1("cpa_improvement_rub", change["improvement"], "RUB"),
            MetricValueV1(
                "cpa_improvement_percent",
                change["improvement_percent"],
                "PERCENT",
            ),
        )
        confidence_status = (
            "READY" if report.confidence == "READY" else "INSUFFICIENT_DATA"
        )
        assessment = ModuleAssessmentV1(
            summary=(
                "The existing deterministic impact policy evaluated the linked "
                "baseline and post-change observations."
            ),
            data_quality_status=(
                "READY" if report.confidence == "READY" else "PARTIAL"
            ),
            confidence_status=confidence_status,
        )
        code, summary, rationale = _RECOMMENDATIONS[report.next_decision]
        recommendations = (
            ModuleRecommendationV1(
                code=code,
                summary=summary,
                rationale=rationale,
                executable=False,
            ),
        )
        warnings = (
            ()
            if report.confidence == "READY"
            else (
                ModuleWarningV1(
                    code=report.confidence,
                    message=(
                        "The impact decision preserves uncertainty and requires "
                        "human review."
                    ),
                ),
            )
        )
        receipt = self._decision_records.record_module_decision(
            DIRECT_IDENTITY,
            request,
            ModuleDecisionV1(
                outcome="SUCCEEDED",
                reason_codes=(report.next_decision,),
                facts=ModuleDecisionFactsV1(
                    metrics=metrics,
                    assessment=assessment,
                    recommendations=recommendations,
                    provenance=(),
                    impact_outcome=outcome,
                ),
            ),
        )
        return ModuleResultV1(
            schema_version=MODULE_RESULT_SCHEMA_VERSION,
            run_id="direct-impact-" + receipt.decision_id[:24],
            module=DIRECT_IDENTITY,
            status="SUCCEEDED",
            metrics=metrics,
            assessment=assessment,
            recommendations=recommendations,
            proposal=None,
            execution_result=None,
            provenance=(),
            warnings=warnings,
            errors=(),
            decision_record_ref=receipt.reference,
            impact_outcome=outcome,
        )

    @staticmethod
    def _rejected(
        request: ModuleRequestV1,
        code: str,
        message: str,
    ) -> ModuleResultV1:
        return terminal_module_result(
            module=DIRECT_IDENTITY,
            request=request,
            status="REJECTED",
            error=ModuleErrorV1(
                code=code,
                message=message,
                field="impact_evaluation_command",
                retryable=False,
            ),
        )


__all__ = ["StandaloneDirectImpactEvaluationV1"]
