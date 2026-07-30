from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mox_adv.ui_dashboard import DashboardApplication
from mox_adv.ui_service import UiRunRejected, UiRunService


class UiOperatingModeTests(unittest.TestCase):
    def test_observe_and_recommend_have_distinct_artifacts_and_no_executor(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = UiRunService(root)

            observe = service.run("test", operating_mode="OBSERVE")
            recommend = service.run("test", operating_mode="RECOMMEND")

            observe_dir = root / observe["run_id"]
            recommend_dir = root / recommend["run_id"]
            self.assertEqual("OBSERVE", observe["operating_mode"])
            self.assertEqual("NOT_STARTED", observe["execution"]["status"])
            self.assertFalse(observe["safety"]["executor_invoked"])
            self.assertFalse((observe_dir / "proposal.json").exists())
            self.assertEqual("RECOMMEND", recommend["operating_mode"])
            self.assertEqual("NOT_STARTED", recommend["execution"]["status"])
            self.assertFalse(recommend["safety"]["executor_invoked"])
            self.assertTrue((recommend_dir / "proposal.json").is_file())
            for directory in (observe_dir, recommend_dir):
                self.assertTrue((directory / "result.json").is_file())
                self.assertTrue((directory / "report.md").is_file())
                self.assertTrue((directory / "events.jsonl").is_file())

    def test_write_modes_fail_closed_without_exact_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(Path(temporary))

            approval = service.run(
                "test",
                operating_mode="APPROVAL_REQUIRED",
            )
            self.assertEqual("PENDING_APPROVAL", approval["execution"]["status"])
            self.assertFalse(approval["safety"]["executor_invoked"])

            with self.assertRaisesRegex(UiRunRejected, "Mandate"):
                service.run(
                    "test",
                    operating_mode="BOUNDED_AUTONOMY",
                )

    def test_no_change_does_not_create_an_unfulfillable_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(Path(temporary))

            report = service.run(
                "test",
                operating_mode="APPROVAL_REQUIRED",
                scenario={
                    "impressions": 10,
                    "clicks": 0,
                    "conversions": 0,
                    "visits": 0,
                    "spend_rub": 0,
                    "weekly_budget_rub": 10_000,
                    "baseline_spend_rub": 0,
                    "baseline_conversions": 0,
                },
            )

            self.assertEqual("NO_CHANGE", report["recommendation"]["action"])
            self.assertEqual("NO_CHANGE", report["execution"]["status"])
            self.assertEqual(
                "NO_CHANGE_RECOMMENDED",
                report["execution"]["reason_code"],
            )
            self.assertFalse(report["execution"]["executor_invoked"])

    def test_bounded_autonomy_consumes_active_test_mandate_and_applies_fake_change(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = UiRunService(root)
            dashboard = DashboardApplication(root, service)
            mandate = dashboard.issue_test_mandate()

            report = service.run(
                "test",
                operating_mode="BOUNDED_AUTONOMY",
                mandate_id=str(mandate["mandate_id"]),
                scenario={
                    "impressions": 5000,
                    "clicks": 100,
                    "conversions": 3,
                    "visits": 100,
                    "spend_rub": 4000,
                    "weekly_budget_rub": 10000,
                    "baseline_spend_rub": 3000,
                    "baseline_conversions": 3,
                },
            )

            self.assertEqual(
                "DECREASE_SEARCH_BID",
                report["recommendation"]["action"],
            )
            self.assertEqual("APPLIED", report["execution"]["status"])
            self.assertEqual(1, report["execution"]["write_calls"])
            self.assertEqual(
                mandate["mandate_id"],
                report["execution"]["mandate_id"],
            )
            usage = dashboard.mandate_authority.usage(str(mandate["mandate_id"]))
            self.assertEqual(1, usage.action_count)
            run_directory = root / report["run_id"]
            module_result = json.loads(
                (run_directory / "direct-module-result.json").read_text(
                    encoding="utf-8"
                )
            )
            decision = json.loads(
                (run_directory / "direct-decision-record.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("APPLIED", module_result["execution_result"]["status"])
            self.assertEqual("APPLY_OPTIMIZATION", decision["operation_type"])
            self.assertEqual("SUCCEEDED", decision["outcome"])

    def test_bounded_quota_rejection_still_produces_normative_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = UiRunService(root)
            dashboard = DashboardApplication(root, service)
            mandate = dashboard.issue_test_mandate()
            scenario = {
                "impressions": 5000,
                "clicks": 100,
                "conversions": 3,
                "visits": 100,
                "spend_rub": 4000,
                "weekly_budget_rub": 10000,
                "baseline_spend_rub": 3000,
                "baseline_conversions": 3,
            }

            service.run(
                "test",
                operating_mode="BOUNDED_AUTONOMY",
                mandate_id=str(mandate["mandate_id"]),
                scenario=scenario,
            )
            rejected = service.run(
                "test",
                operating_mode="BOUNDED_AUTONOMY",
                mandate_id=str(mandate["mandate_id"]),
                scenario=scenario,
            )

            self.assertEqual("BLOCKED", rejected["execution"]["status"])
            self.assertEqual(
                "ACTION_QUOTA_REACHED",
                rejected["execution"]["reason_code"],
            )
            run_directory = root / rejected["run_id"]
            self.assertTrue((run_directory / "result.json").is_file())
            self.assertTrue((run_directory / "events.jsonl").is_file())
            self.assertFalse((run_directory / "change_diff.json").exists())
            module_result = json.loads(
                (run_directory / "direct-module-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("BLOCKED", module_result["status"])
            self.assertEqual(
                "ACTION_QUOTA_REACHED",
                module_result["errors"][0]["code"],
            )

    def test_suspended_effective_campaign_recommends_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(Path(temporary))

            report = service.run(
                "test",
                operating_mode="RECOMMEND",
                scenario={
                    "impressions": 10_000,
                    "clicks": 100,
                    "conversions": 10,
                    "visits": 100,
                    "spend_rub": 5_000,
                    "weekly_budget_rub": 10_000,
                    "baseline_spend_rub": 5_000,
                    "baseline_conversions": 10,
                    "campaign_state": "SUSPENDED",
                },
            )

            self.assertEqual(
                "RESUME_CAMPAIGN",
                report["recommendation"]["action"],
            )
            self.assertEqual("NOT_STARTED", report["execution"]["status"])

    def test_unsafe_source_signal_blocks_bounded_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = UiRunService(root)
            dashboard = DashboardApplication(root, service)
            mandate = dashboard.issue_test_mandate()

            report = service.run(
                "test",
                operating_mode="BOUNDED_AUTONOMY",
                mandate_id=str(mandate["mandate_id"]),
                scenario={
                    "impressions": 5000,
                    "clicks": 100,
                    "conversions": 3,
                    "visits": 100,
                    "spend_rub": 4000,
                    "weekly_budget_rub": 10000,
                    "baseline_spend_rub": 3000,
                    "baseline_conversions": 3,
                    "source_mismatch_percent": 40,
                },
            )

            self.assertEqual("BLOCKED", report["execution"]["status"])
            self.assertEqual(
                "REQUEST_HUMAN_HELP",
                report["recommendation"]["primary_action"],
            )
            self.assertEqual(
                "SOURCE_MISMATCH",
                report["execution"]["reason_code"],
            )
            self.assertFalse(report["execution"]["executor_invoked"])
            usage = dashboard.mandate_authority.usage(str(mandate["mandate_id"]))
            self.assertEqual(0, usage.action_count)


if __name__ == "__main__":
    unittest.main()
