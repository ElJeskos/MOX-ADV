from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mox_adv.e2e_evidence import verify_e2e_artifact_manifest
from mox_adv.e2e_runner import run_readonly_e2e


class ReadOnlyRunnerTests(unittest.TestCase):
    def test_both_modules_complete_without_external_write_egress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = run_readonly_e2e(root, "e2e-test-1")
            second = run_readonly_e2e(root, "e2e-test-2")
            result = json.loads((path / "result.json").read_text(encoding="utf-8"))
            lifecycle = json.loads(
                (path / "lifecycle-evidence.json").read_text(encoding="utf-8")
            )
            proposal = json.loads((path / "proposal.json").read_text(encoding="utf-8"))
            direct_module_result = json.loads(
                (path / "direct-module-result.json").read_text(encoding="utf-8")
            )
            direct_decision_record = json.loads(
                (path / "direct-decision-record.json").read_text(encoding="utf-8")
            )
            mandate_module_result = json.loads(
                (path / "mandate-direct-module-result.json").read_text(encoding="utf-8")
            )
            mandate_decision_record = json.loads(
                (path / "mandate-direct-decision-record.json").read_text(
                    encoding="utf-8"
                )
            )
            kill_switch_module_result = json.loads(
                (path / "kill-switch-direct-module-result.json").read_text(
                    encoding="utf-8"
                )
            )
            kill_switch_decision_record = json.loads(
                (path / "kill-switch-direct-decision-record.json").read_text(
                    encoding="utf-8"
                )
            )
            impact_module_result = json.loads(
                (path / "impact-module-result.json").read_text(encoding="utf-8")
            )
            first_stability = json.loads(
                (path / "stability-fingerprint.json").read_text(encoding="utf-8")
            )
            second_stability = json.loads(
                (second / "stability-fingerprint.json").read_text(encoding="utf-8")
            )
            verify_e2e_artifact_manifest(path)
            verify_e2e_artifact_manifest(second)

        self.assertEqual("SUCCEEDED", result["status"])
        self.assertFalse(result["external_write_sent"])
        self.assertFalse(result["external_event_sent"])
        self.assertEqual(0, result["external_non_read_attempt_count"])
        self.assertEqual(1, result["browser_interception_count"])
        self.assertEqual(0, result["browser_websocket_block_count"])
        self.assertEqual(14, result["capability_count"])
        self.assertEqual("LOCAL_FIXTURE", result["source"])
        self.assertTrue(result["snapshot_id"])
        self.assertEqual("deterministic-fake", result["provider"])
        self.assertEqual(
            "DIRECT_TEST_MODULE_AND_SEALED_FAKE_ADAPTERS_ONLY",
            result["technical_command"],
        )
        self.assertEqual("SUCCEEDED", direct_module_result["status"])
        self.assertEqual(
            "APPLIED",
            direct_module_result["execution_result"]["status"],
        )
        self.assertEqual(
            direct_module_result["decision_record_ref"],
            "decision-records/" + direct_decision_record["decision_id"] + ".json",
        )
        self.assertEqual(
            "APPLY_OPTIMIZATION",
            direct_decision_record["operation_type"],
        )
        self.assertEqual("SUCCEEDED", direct_decision_record["outcome"])
        self.assertEqual("SUCCEEDED", mandate_module_result["status"])
        self.assertEqual(
            "APPLIED",
            mandate_module_result["execution_result"]["status"],
        )
        self.assertEqual("SUCCEEDED", mandate_decision_record["outcome"])
        self.assertEqual(
            mandate_module_result["decision_record_ref"],
            "decision-records/" + mandate_decision_record["decision_id"] + ".json",
        )
        self.assertEqual("BLOCKED", kill_switch_module_result["status"])
        self.assertEqual(
            "KILL_SWITCH_ACTIVE",
            kill_switch_module_result["errors"][0]["code"],
        )
        self.assertEqual(
            "BLOCKED",
            kill_switch_module_result["execution_result"]["status"],
        )
        self.assertEqual("BLOCKED", kill_switch_decision_record["outcome"])
        self.assertEqual(
            ["KILL_SWITCH_ACTIVE"],
            kill_switch_decision_record["reason_codes"],
        )
        self.assertEqual(
            kill_switch_module_result["decision_record_ref"],
            "decision-records/" + kill_switch_decision_record["decision_id"] + ".json",
        )
        self.assertEqual("SUCCEEDED", impact_module_result["status"])
        self.assertEqual(
            "OBSERVED_POST_CHANGE",
            impact_module_result["impact_outcome"]["status"],
        )
        self.assertEqual(
            sorted(proposal["observed_facts"]),
            proposal["observed_facts"],
        )
        self.assertEqual("APPLIED", lifecycle["campaign_status"])
        self.assertEqual("VERIFIED", lifecycle["goal_technical_status"])
        self.assertEqual(1, lifecycle["goal_cleanup"]["fake_site_rollbacks"])
        self.assertEqual("#lead-form", lifecycle["goal_event"]["selector"])
        self.assertEqual("#lead-submit", lifecycle["goal_event"]["trigger_selector"])
        self.assertEqual(
            "sim-test-counter",
            lifecycle["goal_event"]["counter_id"],
        )
        self.assertEqual("POST", lifecycle["goal_event"]["http_method"])
        self.assertEqual(
            "https://mc.yandex.ru/watch/sim-test-counter?event=lead_submitted",
            lifecycle["goal_event"]["request_url"],
        )
        self.assertEqual(
            "#lead-submit",
            lifecycle["goal_technical_evidence"]["trigger_selector"],
        )
        self.assertEqual(first_stability, second_stability)


if __name__ == "__main__":
    unittest.main()
