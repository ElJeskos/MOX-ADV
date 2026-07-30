from __future__ import annotations

import json
import unittest
from pathlib import Path

from mox_adv.ui_automation import (
    default_rules,
    evaluate_triggers,
    validate_scenario,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config" / "gate0-policy.json").read_text(encoding="utf-8"))


class UiAutomationTriggerTests(unittest.TestCase):
    def test_all_required_trigger_classes_are_evaluated(self) -> None:
        scenario = validate_scenario(
            {
                "impressions": 10_000,
                "clicks": 100,
                "spend_rub": 3_000,
                "visits": 100,
                "conversions": 3,
                "weekly_budget_rub": 10_000,
                "baseline_spend_rub": 1_000,
                "baseline_conversions": 10,
                "expected_spend_rub": 1_000,
                "baseline_impressions": 1_000,
                "baseline_clicks": 100,
                "baseline_visits": 100,
                "hours_since_last_conversion": 30,
                "source_mismatch_percent": 40,
                "direct_age_minutes": 31,
                "metrika_age_minutes": 361,
                "watermark_skew_minutes": 361,
                "external_change": 1,
                "campaign_state": "ON",
            }
        )
        snapshot = {"metrics": {"budget_utilization_percent": "30"}}

        reason_codes = {
            item["reason_code"]
            for item in evaluate_triggers(
                snapshot,
                scenario,
                default_rules(POLICY),
            )
        }

        self.assertTrue(
            {
                "PACING_AHEAD",
                "CPC_DEVIATION_FROM_BASELINE",
                "CTR_DEVIATION_FROM_BASELINE",
                "CONVERSION_RATE_DEVIATION_FROM_BASELINE",
                "GOAL_CESSATION",
                "SOURCE_MISMATCH",
                "UNKNOWN_EXTERNAL_CHANGE",
                "DIRECT_DATA_STALE",
                "METRIKA_DATA_STALE",
                "WATERMARK_SKEW_EXCEEDED",
            }.issubset(reason_codes)
        )


if __name__ == "__main__":
    unittest.main()
