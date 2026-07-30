"""Pluggable model-provider boundary and deterministic Gate 0 fake."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mox_adv.recommend_contracts import (
    _FACT_EVIDENCE,
    ModelResponse,
)
from mox_adv.recommend_projection import validate_projection


class DeterministicFakeModelProvider:
    """A zero-network provider for the four approved Gate 0 fixtures."""

    def __init__(self) -> None:
        self.invocation_count = 0

    def generate(self, projection: Mapping[str, Any]) -> ModelResponse:
        validate_projection(projection)
        self.invocation_count += 1
        comparability = projection["comparability"]
        if comparability["status"] != "COMPARABLE":
            payload = self._needs_human(projection)
        elif comparability["confidence"] == "INSUFFICIENT_DATA":
            payload = self._insufficient(projection)
        elif projection["goal_visits"] == 0 and projection["cost_micros"] >= (
            projection["policy_limits"]["no_conversion_stop_spend_rub"] * 1_000_000
        ):
            payload = self._ineffective(projection)
        else:
            payload = self._effective(projection)
        return ModelResponse(
            payload=payload,
            provider="deterministic-fake",
            model_id="gate0-fixtures-v1",
            input_tokens=0,
            output_tokens=0,
            cost_rub="0",
            duration_ms=0,
        )

    @staticmethod
    def _base(
        projection: Mapping[str, Any],
        status: str,
        action: str,
        explanation: str,
    ) -> dict[str, Any]:
        limits = projection["policy_limits"]
        observed_facts = sorted(projection["observed_facts"])
        evidence = {field for fact in observed_facts for field in _FACT_EVIDENCE[fact]}
        return {
            "status": status,
            "observed_facts": observed_facts,
            "hypotheses": [{"rank": 1, "code": status + "_CONDITION"}],
            "actions": [
                {
                    "action": action,
                    "parameters": {},
                    "dependencies": [],
                    "limits": ["GATE0_POLICY_LIMITS"],
                    "rollback_conditions": ["OBSERVATION_WINDOW_RESULT"],
                }
            ],
            "evidence_fields": sorted(evidence),
            "expected_effect_direction": (
                "NO_CHANGE" if action in {"KEEP", "REQUEST_HUMAN_HELP"} else "POSITIVE"
            ),
            "minimum_observation_window_hours": limits["observation_window_hours"],
            "risks": ["PERFORMANCE_MAY_NOT_IMPROVE"],
            "preconditions": ["POLICY_RECHECK_REQUIRED"],
            "rollback_condition": "KPI_DEGRADES_AFTER_OBSERVATION",
            "missing_data_requests": [],
            "expected_diff": {"operation": action},
            "explanation_ru": explanation,
        }

    @classmethod
    def _effective(cls, projection: Mapping[str, Any]) -> dict[str, Any]:
        payload = cls._base(
            projection,
            "EFFECTIVE",
            "INCREASE_WEEKLY_BUDGET",
            "Бюджет почти исчерпан, а цена конверсии не превышает целевую.",
        )
        payload["expected_diff"] = {
            "operation": "INCREASE_WEEKLY_BUDGET",
            "relative_step_percent": projection["policy_limits"][
                "maximum_step_percent"
            ],
        }
        return payload

    @classmethod
    def _ineffective(cls, projection: Mapping[str, Any]) -> dict[str, Any]:
        payload = cls._base(
            projection,
            "INEFFECTIVE",
            "SUSPEND_CAMPAIGN",
            "Расход достиг порога остановки, а подтверждённых конверсий нет.",
        )
        payload["expected_diff"] = {
            "operation": "SUSPEND_CAMPAIGN",
            "target_state": "SUSPENDED",
        }
        return payload

    @classmethod
    def _insufficient(cls, projection: Mapping[str, Any]) -> dict[str, Any]:
        payload = cls._base(
            projection,
            "INSUFFICIENT_DATA",
            "KEEP",
            "Выборка не достигла минимального объёма для финансового решения.",
        )
        payload["expected_diff"] = {"operation": "NO_CHANGE"}
        payload["missing_data_requests"] = ["MORE_CLICKS_AND_CONVERSIONS"]
        return payload

    @classmethod
    def _needs_human(cls, projection: Mapping[str, Any]) -> dict[str, Any]:
        payload = cls._base(
            projection,
            "NEEDS_HUMAN",
            "REQUEST_HUMAN_HELP",
            "Источники расходятся, поэтому нужно проверить трекинг вручную.",
        )
        payload["actions"][0]["parameters"] = {"reason_code": "AMBIGUOUS_DATA"}
        payload["expected_diff"] = {"operation": "NO_CHANGE"}
        payload["missing_data_requests"] = ["TRACKING_VALIDATION"]
        return payload
