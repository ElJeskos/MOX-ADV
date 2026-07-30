"""Closed request and result types for post-change impact evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

from mox_adv.impact import (
    IMPACT_NEXT_DECISIONS,
    ImpactEvaluationRequest,
    ImpactObservation,
    ImpactRejected,
    ImpactReport,
)
from mox_adv.module_api.v1.contract_validation import (
    ContractValidationError,
    array_value,
    exact_fields,
    object_value,
    one_of,
    text,
    timestamp,
)

IMPACT_EVALUATION_COMMAND_SCHEMA_VERSION = (
    "direct-impact-evaluation-command-v1"
)
IMPACT_REPORT_SCHEMA_VERSION = "impact-report-v1"
_COMMAND_FIELDS = (
    "schema_version",
    "command",
    "fixture_name",
    "run_id",
    "change_id",
    "policy_version",
    "change_applied_at",
    "evaluated_at",
    "baseline",
    "post_change",
    "seasonality",
    "known_interventions",
    "confounders",
    "evidence",
)
_OUTCOME_FIELDS = (
    "schema_version",
    "policy_version",
    "run_id",
    "change_id",
    "fixture_name",
    "status",
    "effect_classification",
    "baseline",
    "post_change",
    "watermarks",
    "delayed_conversion_cutoff_hours",
    "observation_window_hours",
    "seasonality",
    "known_interventions",
    "confounders",
    "metric_changes",
    "confidence",
    "evidence",
    "next_decision",
)


def _string_tuple(value: Any, field: str) -> Tuple[str, ...]:
    return tuple(
        text(item, f"{field}[]", maximum=1_000)
        for item in array_value(value, field)
    )


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractValidationError(f"{field} must be a positive integer")
    return value


@dataclass(frozen=True)
class ImpactEvaluationCommandV1:
    """Typed evidence for the existing deterministic impact evaluator."""

    schema_version: str
    command: str
    fixture_name: str
    run_id: str
    change_id: str
    policy_version: str
    change_applied_at: str
    evaluated_at: str
    baseline: ImpactObservation
    post_change: ImpactObservation
    seasonality: str
    known_interventions: Tuple[str, ...]
    confounders: Tuple[str, ...]
    evidence: Tuple[str, ...]

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "ImpactEvaluationCommandV1":
        exact_fields(
            value,
            field="impact_evaluation_command",
            required=_COMMAND_FIELDS,
        )
        try:
            baseline = ImpactObservation.from_mapping(
                object_value(
                    value["baseline"],
                    "impact_evaluation_command.baseline",
                ),
                "Baseline",
            )
            post_change = ImpactObservation.from_mapping(
                object_value(
                    value["post_change"],
                    "impact_evaluation_command.post_change",
                ),
                "Post-change",
            )
        except ImpactRejected as error:
            raise ContractValidationError(str(error)) from error
        return cls(
            schema_version=one_of(
                text(
                    value["schema_version"],
                    "impact_evaluation_command.schema_version",
                    maximum=64,
                ),
                "impact_evaluation_command.schema_version",
                (IMPACT_EVALUATION_COMMAND_SCHEMA_VERSION,),
            ),
            command=one_of(
                text(
                    value["command"],
                    "impact_evaluation_command.command",
                    maximum=32,
                ),
                "impact_evaluation_command.command",
                ("EVALUATE_IMPACT",),
            ),
            fixture_name=text(
                value["fixture_name"],
                "impact_evaluation_command.fixture_name",
                maximum=128,
            ),
            run_id=text(
                value["run_id"],
                "impact_evaluation_command.run_id",
                maximum=128,
            ),
            change_id=text(
                value["change_id"],
                "impact_evaluation_command.change_id",
                maximum=128,
            ),
            policy_version=text(
                value["policy_version"],
                "impact_evaluation_command.policy_version",
                maximum=128,
            ),
            change_applied_at=timestamp(
                value["change_applied_at"],
                "impact_evaluation_command.change_applied_at",
            ),
            evaluated_at=timestamp(
                value["evaluated_at"],
                "impact_evaluation_command.evaluated_at",
            ),
            baseline=baseline,
            post_change=post_change,
            seasonality=text(
                value["seasonality"],
                "impact_evaluation_command.seasonality",
                maximum=256,
            ),
            known_interventions=_string_tuple(
                value["known_interventions"],
                "impact_evaluation_command.known_interventions",
            ),
            confounders=_string_tuple(
                value["confounders"],
                "impact_evaluation_command.confounders",
            ),
            evidence=_string_tuple(
                value["evidence"],
                "impact_evaluation_command.evidence",
            ),
        )

    def to_domain(self) -> ImpactEvaluationRequest:
        return ImpactEvaluationRequest(
            fixture_name=self.fixture_name,
            run_id=self.run_id,
            change_id=self.change_id,
            policy_version=self.policy_version,
            change_applied_at=self.change_applied_at,
            evaluated_at=self.evaluated_at,
            baseline=self.baseline,
            post_change=self.post_change,
            seasonality=self.seasonality,
            known_interventions=self.known_interventions,
            confounders=self.confounders,
            evidence=self.evidence,
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "command": self.command,
            "fixture_name": self.fixture_name,
            "run_id": self.run_id,
            "change_id": self.change_id,
            "policy_version": self.policy_version,
            "change_applied_at": self.change_applied_at,
            "evaluated_at": self.evaluated_at,
            "baseline": _observation_dict(self.baseline),
            "post_change": _observation_dict(self.post_change),
            "seasonality": self.seasonality,
            "known_interventions": list(self.known_interventions),
            "confounders": list(self.confounders),
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class ImpactResultObservationV1:
    snapshot_id: str
    period_start: str
    period_end: str
    cpa_rub: str

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        field: str,
    ) -> "ImpactResultObservationV1":
        exact_fields(
            value,
            field=field,
            required=("snapshot_id", "period_start", "period_end", "cpa_rub"),
        )
        return cls(
            snapshot_id=text(
                value["snapshot_id"],
                f"{field}.snapshot_id",
                maximum=128,
            ),
            period_start=text(
                value["period_start"],
                f"{field}.period_start",
                maximum=32,
            ),
            period_end=text(
                value["period_end"],
                f"{field}.period_end",
                maximum=32,
            ),
            cpa_rub=text(value["cpa_rub"], f"{field}.cpa_rub", maximum=128),
        )

    def as_dict(self) -> Dict[str, str]:
        return {
            "snapshot_id": self.snapshot_id,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "cpa_rub": self.cpa_rub,
        }


@dataclass(frozen=True)
class ImpactSourceWatermarksV1:
    direct_report: str
    direct_state: str
    metrika_report: str

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        field: str,
    ) -> "ImpactSourceWatermarksV1":
        exact_fields(
            value,
            field=field,
            required=("direct_report", "direct_state", "metrika_report"),
        )
        return cls(
            direct_report=timestamp(
                value["direct_report"],
                f"{field}.direct_report",
            ),
            direct_state=timestamp(
                value["direct_state"],
                f"{field}.direct_state",
            ),
            metrika_report=timestamp(
                value["metrika_report"],
                f"{field}.metrika_report",
            ),
        )

    def as_dict(self) -> Dict[str, str]:
        return {
            "direct_report": self.direct_report,
            "direct_state": self.direct_state,
            "metrika_report": self.metrika_report,
        }


@dataclass(frozen=True)
class ImpactWatermarksV1:
    baseline: ImpactSourceWatermarksV1
    post_change: ImpactSourceWatermarksV1

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ImpactWatermarksV1":
        exact_fields(
            value,
            field="impact_outcome.watermarks",
            required=("baseline", "post_change"),
        )
        return cls(
            baseline=ImpactSourceWatermarksV1.from_dict(
                object_value(
                    value["baseline"],
                    "impact_outcome.watermarks.baseline",
                ),
                field="impact_outcome.watermarks.baseline",
            ),
            post_change=ImpactSourceWatermarksV1.from_dict(
                object_value(
                    value["post_change"],
                    "impact_outcome.watermarks.post_change",
                ),
                field="impact_outcome.watermarks.post_change",
            ),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "baseline": self.baseline.as_dict(),
            "post_change": self.post_change.as_dict(),
        }


@dataclass(frozen=True)
class ImpactMetricChangeV1:
    baseline: str
    post_change: str
    improvement: str
    improvement_percent: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ImpactMetricChangeV1":
        exact_fields(
            value,
            field="impact_outcome.metric_changes.cpa_rub",
            required=(
                "baseline",
                "post_change",
                "improvement",
                "improvement_percent",
            ),
        )
        return cls(
            baseline=text(
                value["baseline"],
                "impact_outcome.metric_changes.cpa_rub.baseline",
                maximum=128,
            ),
            post_change=text(
                value["post_change"],
                "impact_outcome.metric_changes.cpa_rub.post_change",
                maximum=128,
            ),
            improvement=text(
                value["improvement"],
                "impact_outcome.metric_changes.cpa_rub.improvement",
                maximum=128,
            ),
            improvement_percent=text(
                value["improvement_percent"],
                "impact_outcome.metric_changes.cpa_rub.improvement_percent",
                maximum=128,
            ),
        )

    def as_dict(self) -> Dict[str, str]:
        return {
            "baseline": self.baseline,
            "post_change": self.post_change,
            "improvement": self.improvement,
            "improvement_percent": self.improvement_percent,
        }


@dataclass(frozen=True)
class ImpactEvaluationOutcomeV1:
    """Typed immutable projection of the existing ImpactReport."""

    schema_version: str
    policy_version: str
    run_id: str
    change_id: str
    fixture_name: str
    status: str
    effect_classification: str
    baseline: ImpactResultObservationV1
    post_change: ImpactResultObservationV1
    watermarks: ImpactWatermarksV1
    delayed_conversion_cutoff_hours: int
    observation_window_hours: int
    seasonality: str
    known_interventions: Tuple[str, ...]
    confounders: Tuple[str, ...]
    metric_changes: ImpactMetricChangeV1
    confidence: str
    evidence: Tuple[str, ...]
    next_decision: str

    @classmethod
    def from_report(cls, report: ImpactReport) -> "ImpactEvaluationOutcomeV1":
        return cls.from_dict(report.as_dict())

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "ImpactEvaluationOutcomeV1":
        exact_fields(value, field="impact_outcome", required=_OUTCOME_FIELDS)
        changes = object_value(
            value["metric_changes"],
            "impact_outcome.metric_changes",
        )
        exact_fields(
            changes,
            field="impact_outcome.metric_changes",
            required=("cpa_rub",),
        )
        return cls(
            schema_version=one_of(
                text(
                    value["schema_version"],
                    "impact_outcome.schema_version",
                    maximum=64,
                ),
                "impact_outcome.schema_version",
                (IMPACT_REPORT_SCHEMA_VERSION,),
            ),
            policy_version=text(
                value["policy_version"],
                "impact_outcome.policy_version",
                maximum=256,
            ),
            run_id=text(value["run_id"], "impact_outcome.run_id", maximum=256),
            change_id=text(
                value["change_id"],
                "impact_outcome.change_id",
                maximum=256,
            ),
            fixture_name=text(
                value["fixture_name"],
                "impact_outcome.fixture_name",
                maximum=256,
            ),
            status=one_of(
                text(value["status"], "impact_outcome.status", maximum=64),
                "impact_outcome.status",
                ("OBSERVED_POST_CHANGE",),
            ),
            effect_classification=one_of(
                text(
                    value["effect_classification"],
                    "impact_outcome.effect_classification",
                    maximum=64,
                ),
                "impact_outcome.effect_classification",
                ("OBSERVED_ASSOCIATION",),
            ),
            baseline=ImpactResultObservationV1.from_dict(
                object_value(value["baseline"], "impact_outcome.baseline"),
                field="impact_outcome.baseline",
            ),
            post_change=ImpactResultObservationV1.from_dict(
                object_value(
                    value["post_change"],
                    "impact_outcome.post_change",
                ),
                field="impact_outcome.post_change",
            ),
            watermarks=ImpactWatermarksV1.from_dict(
                object_value(value["watermarks"], "impact_outcome.watermarks")
            ),
            delayed_conversion_cutoff_hours=_positive_integer(
                value["delayed_conversion_cutoff_hours"],
                "impact_outcome.delayed_conversion_cutoff_hours",
            ),
            observation_window_hours=_positive_integer(
                value["observation_window_hours"],
                "impact_outcome.observation_window_hours",
            ),
            seasonality=text(
                value["seasonality"],
                "impact_outcome.seasonality",
                maximum=256,
            ),
            known_interventions=_string_tuple(
                value["known_interventions"],
                "impact_outcome.known_interventions",
            ),
            confounders=_string_tuple(
                value["confounders"],
                "impact_outcome.confounders",
            ),
            metric_changes=ImpactMetricChangeV1.from_dict(
                object_value(
                    changes["cpa_rub"],
                    "impact_outcome.metric_changes.cpa_rub",
                )
            ),
            confidence=text(
                value["confidence"],
                "impact_outcome.confidence",
                maximum=256,
            ),
            evidence=_string_tuple(
                value["evidence"],
                "impact_outcome.evidence",
            ),
            next_decision=one_of(
                text(
                    value["next_decision"],
                    "impact_outcome.next_decision",
                    maximum=64,
                ),
                "impact_outcome.next_decision",
                IMPACT_NEXT_DECISIONS,
            ),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "run_id": self.run_id,
            "change_id": self.change_id,
            "fixture_name": self.fixture_name,
            "status": self.status,
            "effect_classification": self.effect_classification,
            "baseline": self.baseline.as_dict(),
            "post_change": self.post_change.as_dict(),
            "watermarks": self.watermarks.as_dict(),
            "delayed_conversion_cutoff_hours": (
                self.delayed_conversion_cutoff_hours
            ),
            "observation_window_hours": self.observation_window_hours,
            "seasonality": self.seasonality,
            "known_interventions": list(self.known_interventions),
            "confounders": list(self.confounders),
            "metric_changes": {
                "cpa_rub": self.metric_changes.as_dict(),
            },
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "next_decision": self.next_decision,
        }


def _observation_dict(observation: ImpactObservation) -> Dict[str, Any]:
    return {
        "snapshot_id": observation.snapshot_id,
        "campaign": observation.campaign,
        "period_start": observation.period_start,
        "period_end": observation.period_end,
        "watermarks": dict(observation.watermarks),
        "metrics": dict(observation.metrics),
        "comparability_status": observation.comparability_status,
        "confidence_status": observation.confidence_status,
    }


__all__ = [
    "IMPACT_EVALUATION_COMMAND_SCHEMA_VERSION",
    "IMPACT_NEXT_DECISIONS",
    "ImpactEvaluationCommandV1",
    "ImpactEvaluationOutcomeV1",
]
