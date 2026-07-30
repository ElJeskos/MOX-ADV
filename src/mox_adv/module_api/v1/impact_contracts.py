"""Closed request and result types for post-change impact evaluation."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

from mox_adv.impact import (
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
IMPACT_NEXT_DECISIONS = (
    "KEEP_CHANGE",
    "ROLLBACK_CHANGE",
    "ADJUST_CHANGE",
    "ESCALATE_TO_HUMAN",
)

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
class ImpactEvaluationOutcomeV1:
    """Validated, immutable projection of the existing ImpactReport."""

    payload: Mapping[str, Any]

    @classmethod
    def from_report(cls, report: ImpactReport) -> "ImpactEvaluationOutcomeV1":
        return cls.from_dict(report.as_dict())

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "ImpactEvaluationOutcomeV1":
        exact_fields(value, field="impact_outcome", required=_OUTCOME_FIELDS)
        one_of(
            text(value["schema_version"], "impact_outcome.schema_version", maximum=64),
            "impact_outcome.schema_version",
            (IMPACT_REPORT_SCHEMA_VERSION,),
        )
        one_of(
            text(value["status"], "impact_outcome.status", maximum=64),
            "impact_outcome.status",
            ("OBSERVED_POST_CHANGE",),
        )
        one_of(
            text(
                value["effect_classification"],
                "impact_outcome.effect_classification",
                maximum=64,
            ),
            "impact_outcome.effect_classification",
            ("OBSERVED_ASSOCIATION",),
        )
        one_of(
            text(
                value["next_decision"],
                "impact_outcome.next_decision",
                maximum=64,
            ),
            "impact_outcome.next_decision",
            IMPACT_NEXT_DECISIONS,
        )
        for field in (
            "policy_version",
            "run_id",
            "change_id",
            "fixture_name",
            "seasonality",
            "confidence",
        ):
            text(value[field], f"impact_outcome.{field}", maximum=256)
        _positive_integer(
            value["delayed_conversion_cutoff_hours"],
            "impact_outcome.delayed_conversion_cutoff_hours",
        )
        _positive_integer(
            value["observation_window_hours"],
            "impact_outcome.observation_window_hours",
        )
        for name in ("baseline", "post_change"):
            observation = object_value(value[name], f"impact_outcome.{name}")
            exact_fields(
                observation,
                field=f"impact_outcome.{name}",
                required=("snapshot_id", "period_start", "period_end", "cpa_rub"),
            )
            for field in observation:
                text(
                    observation[field],
                    f"impact_outcome.{name}.{field}",
                    maximum=256,
                )
        watermarks = object_value(value["watermarks"], "impact_outcome.watermarks")
        exact_fields(
            watermarks,
            field="impact_outcome.watermarks",
            required=("baseline", "post_change"),
        )
        for period_name in ("baseline", "post_change"):
            period_watermarks = object_value(
                watermarks[period_name],
                f"impact_outcome.watermarks.{period_name}",
            )
            exact_fields(
                period_watermarks,
                field=f"impact_outcome.watermarks.{period_name}",
                required=("direct_report", "direct_state", "metrika_report"),
            )
            for source, observed_at in period_watermarks.items():
                timestamp(
                    observed_at,
                    f"impact_outcome.watermarks.{period_name}.{source}",
                )
        changes = object_value(
            value["metric_changes"],
            "impact_outcome.metric_changes",
        )
        exact_fields(
            changes,
            field="impact_outcome.metric_changes",
            required=("cpa_rub",),
        )
        cpa_change = object_value(
            changes["cpa_rub"],
            "impact_outcome.metric_changes.cpa_rub",
        )
        exact_fields(
            cpa_change,
            field="impact_outcome.metric_changes.cpa_rub",
            required=(
                "baseline",
                "post_change",
                "improvement",
                "improvement_percent",
            ),
        )
        for field, metric in cpa_change.items():
            text(metric, f"impact_outcome.metric_changes.cpa_rub.{field}", maximum=128)
        for field in ("known_interventions", "confounders", "evidence"):
            _string_tuple(value[field], f"impact_outcome.{field}")
        return cls(payload=copy.deepcopy(dict(value)))

    def as_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(dict(self.payload))


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
