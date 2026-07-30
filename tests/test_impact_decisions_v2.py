from __future__ import annotations

import json
import unittest
from pathlib import Path

from mox_adv.impact import ImpactEvaluator, load_impact_fixture

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "gate0-policy.json"
FIXTURE_ROOT = ROOT / "fixtures" / "impact"


class ImpactDecisionMatrixTests(unittest.TestCase):
    def test_named_fixtures_cover_every_normative_next_decision(self) -> None:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        expected = {
            "IMPACT_CPA_IMPROVED_KEEP": "KEEP_CHANGE",
            "IMPACT_CPA_WORSE_ROLLBACK": "ROLLBACK_CHANGE",
            "IMPACT_MIXED_ADJUST": "ADJUST_CHANGE",
            "IMPACT_INCONCLUSIVE_HUMAN": "ESCALATE_TO_HUMAN",
        }

        actual = {
            fixture_name: ImpactEvaluator(policy)
            .evaluate(
                load_impact_fixture(
                    FIXTURE_ROOT / f"{fixture_name}.json",
                    policy,
                )
            )
            .next_decision
            for fixture_name in expected
        }

        self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
