"""Pluggable model-provider boundary and deterministic Gate 0 fake."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
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
        elif projection["goal_visits"] == 0 and projection["cost_micros"] >= (
            projection["policy_limits"]["no_conversion_stop_spend_rub"] * 1_000_000
        ):
            payload = self._ineffective(projection)
        elif (
            comparability["confidence"] == "INSUFFICIENT_DATA"
            or projection["clicks"] < projection["policy_limits"]["minimum_clicks"]
            or projection["goal_visits"]
            < projection["policy_limits"]["minimum_conversions"]
        ):
            payload = self._insufficient(projection)
        elif projection["campaign_state"] == "SUSPENDED" and Decimal(
            str(projection["cpa"])
        ) <= Decimal(str(projection["policy_limits"]["cpa_target_rub"])):
            payload = self._resume_campaign(projection)
        elif (
            Decimal(str(projection["ctr"]))
            < Decimal(str(projection["policy_limits"]["low_ctr_percent"]))
            and projection["impressions"]
            >= projection["policy_limits"]["low_ctr_minimum_impressions"]
        ):
            payload = self._switch_ad_variant(projection)
        elif Decimal(str(projection["cpa"])) > Decimal(
            str(projection["policy_limits"]["cpa_target_rub"])
        ) and Decimal(str(projection["budget_utilization"])) >= Decimal(
            str(projection["policy_limits"]["budget_pressure_usage_percent"])
        ):
            payload = self._decrease_budget(projection)
        elif Decimal(str(projection["cpa"])) > Decimal(
            str(projection["policy_limits"]["cpa_target_rub"])
        ):
            payload = self._decrease_bid(projection)
        elif Decimal(str(projection["budget_utilization"])) >= Decimal(
            str(projection["policy_limits"]["budget_pressure_usage_percent"])
        ):
            payload = self._effective(projection)
        elif (
            Decimal(str(projection["budget_utilization"]))
            < Decimal(str(projection["policy_limits"]["budget_pressure_usage_percent"]))
            and projection["clicks"]
            <= projection["policy_limits"]["bid_increase_maximum_clicks"]
        ):
            payload = self._increase_bid(projection)
        else:
            payload = self._keep(projection)
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
    def _decrease_budget(
        cls,
        projection: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = cls._base(
            projection,
            "INEFFECTIVE",
            "DECREASE_WEEKLY_BUDGET",
            "Цена конверсии выше целевой при высоком использовании бюджета.",
        )
        payload["expected_diff"] = {
            "operation": "DECREASE_WEEKLY_BUDGET",
            "relative_step_percent": projection["policy_limits"][
                "maximum_step_percent"
            ],
        }
        return payload

    @classmethod
    def _decrease_bid(
        cls,
        projection: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = cls._base(
            projection,
            "INEFFECTIVE",
            "DECREASE_SEARCH_BID",
            "Цена конверсии выше целевой, а давление недельного бюджета отсутствует.",
        )
        payload["expected_diff"] = {
            "operation": "DECREASE_SEARCH_BID",
            "relative_step_percent": projection["policy_limits"][
                "maximum_step_percent"
            ],
        }
        return payload

    @classmethod
    def _increase_bid(
        cls,
        projection: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = cls._base(
            projection,
            "EFFECTIVE",
            "INCREASE_SEARCH_BID",
            "Цена конверсии не превышает целевую, а недельный бюджет не ограничивает показы.",
        )
        payload["expected_diff"] = {
            "operation": "INCREASE_SEARCH_BID",
            "relative_step_percent": projection["policy_limits"][
                "maximum_step_percent"
            ],
        }
        return payload

    @classmethod
    def _resume_campaign(
        cls,
        projection: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = cls._base(
            projection,
            "EFFECTIVE",
            "RESUME_CAMPAIGN",
            "Кампания приостановлена, а достаточная выборка соответствует целевому CPA.",
        )
        payload["expected_diff"] = {
            "operation": "RESUME_CAMPAIGN",
            "target_state": "ON",
        }
        return payload

    @classmethod
    def _keep(cls, projection: Mapping[str, Any]) -> dict[str, Any]:
        payload = cls._base(
            projection,
            "EFFECTIVE",
            "KEEP",
            "Цена конверсии соответствует цели, а дополнительное изменение не требуется.",
        )
        payload["expected_diff"] = {"operation": "NO_CHANGE"}
        return payload

    @classmethod
    def _switch_ad_variant(
        cls,
        projection: Mapping[str, Any],
    ) -> dict[str, Any]:
        variant = "B" if projection["current_ad_variant"] == "A" else "A"
        payload = cls._base(
            projection,
            "INEFFECTIVE",
            "SET_AD_VARIANT",
            "CTR ниже порога при достаточном числе показов; требуется проверить другой вариант объявления.",
        )
        payload["actions"][0]["parameters"] = {"variant_id": variant}
        payload["expected_diff"] = {
            "operation": "SET_AD_VARIANT",
            "variant_id": variant,
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
        context_incomplete = (
            "ANALYTICS_CONTEXT_INCOMPLETE" in projection["observed_facts"]
        )
        payload = cls._base(
            projection,
            "NEEDS_HUMAN",
            "REQUEST_HUMAN_HELP",
            (
                "Недоступны доверенный baseline и история изменений, "
                "поэтому финансовое предложение требует проверки человеком."
                if context_incomplete
                else ("Источники расходятся, поэтому нужно проверить трекинг вручную.")
            ),
        )
        payload["actions"][0]["parameters"] = {
            "reason_code": (
                "MISSING_ANALYTICS_CONTEXT" if context_incomplete else "AMBIGUOUS_DATA"
            )
        }
        payload["expected_diff"] = {"operation": "NO_CHANGE"}
        payload["missing_data_requests"] = (
            ["TRUSTED_BASELINE", "CHANGE_PROVENANCE"]
            if context_incomplete
            else ["TRACKING_VALIDATION"]
        )
        return payload
