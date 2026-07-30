from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from mox_adv.connectors import (
    FixtureAnalyticsConnectorV1,
)
from mox_adv.contracts import (
    AnalyticsPeriod,
    AnalyticsScope,
    ConnectedAnalytics,
)
from mox_adv.observe import (
    collect_paired_fixture_snapshot_via_modules,
    trusted_fixture_scope,
)
from mox_adv.paired_production import PairedYandexProductionReaderV1
from mox_adv.ui_service import UiRunRejected, UiRunService

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "gate0-policy.json"
FIXTURE = ROOT / "fixtures" / "ui" / "linked-budget-pressure.json"


class StubProductionReader:
    def __init__(self) -> None:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        connected = FixtureAnalyticsConnectorV1().read_linked(fixture)
        self.direct_report = replace(
            connected.direct_report,
            source="DIRECT_REPORTS",
        )
        self.direct_state = replace(
            connected.direct_state,
            source="DIRECT_CAMPAIGN_STATE",
        )
        self.metrika_report = replace(
            connected.metrika_report,
            source="METRIKA_REPORT",
        )
        self.baseline = connected.baseline
        self.scope = trusted_fixture_scope(policy, "ui-linked-budget-pressure")
        self.period_start = self.direct_report.period_start
        self.period_end = self.direct_report.period_end
        self.last_records: tuple[Mapping[str, str], ...] = ()

    def readiness(self, policy: Mapping[str, Any]) -> dict[str, Any]:
        del policy
        return {
            "ready": True,
            "checks": [
                {
                    "id": "real_yandex_reads",
                    "label": "Реальные read-only API Яндекса настроены",
                    "ready": True,
                }
            ],
            "blockers": [],
            "access": "READ_ONLY",
            "data_source": "YANDEX_PRODUCTION_API",
            "external_reads_enabled": True,
            "write_requests_allowed": False,
            "write_flow": "DISABLED",
        }

    def collect_snapshot(
        self,
        *,
        policy: Mapping[str, Any],
        observation_id: str,
        generated_at: datetime,
    ) -> Any:
        observed_at = generated_at.isoformat()
        self.direct_report = replace(
            self.direct_report,
            retrieved_at=observed_at,
            watermark=observed_at,
        )
        self.direct_state = replace(
            self.direct_state,
            retrieved_at=observed_at,
            watermark=observed_at,
        )
        self.metrika_report = replace(
            self.metrika_report,
            retrieved_at=observed_at,
            watermark=observed_at,
        )
        connected = ConnectedAnalytics(
            observation_id=observation_id,
            generated_at=generated_at.isoformat(),
            scope=AnalyticsScope(
                organization=self.scope.organization,
                connection=self.scope.connection,
                account=self.scope.account,
                campaign=self.scope.campaign,
                counter=self.scope.counter,
                goal=self.scope.goal,
            ),
            requested_period=AnalyticsPeriod(
                period_start=self.period_start,
                period_end=self.period_end,
            ),
            direct_report=self.direct_report,
            direct_state=self.direct_state,
            metrika_report=self.metrika_report,
            baseline=self.baseline,
        )
        snapshot = collect_paired_fixture_snapshot_via_modules(
            policy=policy,
            connected=connected,
            trusted_scope=self.scope,
        )
        self.last_records = (
            {
                "system": "DIRECT_REPORTS",
                "http_method": "POST",
                "host": "api.direct.yandex.com",
                "path": "/json/v501/reports",
                "operation": "get",
            },
            {
                "system": "DIRECT",
                "http_method": "POST",
                "host": "api.direct.yandex.com",
                "path": "/json/v501/campaigns",
                "operation": "get",
            },
            {
                "system": "METRIKA",
                "http_method": "GET",
                "host": "api-metrika.yandex.net",
                "path": "/stat/v1/data",
                "operation": "get",
            },
        )
        return snapshot


class UiRunServiceTests(unittest.TestCase):
    def test_manual_test_cycle_always_waits_for_operator_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(Path(temporary))

            report = service.run("test", origin="MANUAL")

            self.assertEqual("APPROVAL_REQUIRED", report["operating_mode"])
            self.assertEqual("PENDING_APPROVAL", report["execution"]["status"])
            self.assertEqual(0, report["execution"]["write_calls"])
            self.assertFalse(report["execution"]["executor_invoked"])

    def test_test_mode_runs_linked_analytics_and_returns_pending_proposal(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = UiRunService(
                root,
                production_reader=PairedYandexProductionReaderV1(
                    paired_configuration_path=root / "missing-paired.json",
                    direct_configuration_path=root / "missing-direct.json",
                    metrika_configuration_path=root / "missing-metrika.json",
                    direct_environment_path=root / "missing.env",
                    metrika_environment_path=root / "missing.env",
                ),
            )

            report = service.run("test")

            self.assertEqual("SUCCEEDED", report["status"])
            self.assertEqual("95.00", report["metrics"]["budget_utilization_percent"])
            self.assertEqual(
                "INCREASE_WEEKLY_BUDGET",
                report["recommendation"]["action"],
            )
            self.assertEqual(10, report["recommendation"]["relative_step_percent"])
            self.assertEqual("PENDING_APPROVAL", report["execution"]["status"])
            self.assertIsNone(report["execution"]["readback_micros"])
            self.assertEqual(0, report["execution"]["write_calls"])
            self.assertFalse(report["safety"]["external_write_sent"])
            self.assertTrue(
                (Path(temporary) / report["run_id"] / "ui-report.html").is_file()
            )
            self.assertFalse(
                (Path(temporary) / report["run_id"] / "ui-report.md").exists()
            )

    def test_test_mode_uses_operator_metrics_and_can_decide_to_keep(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(Path(temporary))

            report = service.run(
                "test",
                scenario={
                    "impressions": 2_000,
                    "clicks": 20,
                    "spend_rub": 400,
                    "visits": 24,
                    "conversions": 1,
                    "weekly_budget_rub": 2_000,
                    "baseline_spend_rub": 350,
                    "baseline_conversions": 1,
                },
            )

            self.assertEqual("20.00", report["metrics"]["budget_utilization_percent"])
            self.assertEqual("INSUFFICIENT_DATA", report["recommendation"]["status"])
            self.assertEqual("NO_CHANGE", report["recommendation"]["action"])
            self.assertEqual("NO_CHANGE", report["execution"]["status"])
            self.assertEqual(0, report["execution"]["write_calls"])
            self.assertEqual("CUSTOM", report["scenario"]["source"])
            self.assertIn(
                "недостаточно данных",
                report["decision"]["reason"].lower(),
            )

    def test_test_mode_decreases_budget_when_cpa_is_above_target_under_budget_pressure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(Path(temporary))

            report = service.run(
                "test",
                scenario={
                    "impressions": 10_000,
                    "clicks": 100,
                    "spend_rub": 19_000,
                    "visits": 100,
                    "conversions": 12,
                    "weekly_budget_rub": 2_000,
                    "baseline_spend_rub": 1_800,
                    "baseline_conversions": 10,
                },
            )

            self.assertEqual("1583.33", report["metrics"]["cpa_rub"])
            self.assertEqual(
                "DECREASE_WEEKLY_BUDGET",
                report["recommendation"]["action"],
            )
            self.assertIn(
                "выше целевой",
                report["decision"]["reason"].lower(),
            )
            self.assertEqual(10, report["recommendation"]["relative_step_percent"])
            self.assertEqual("PENDING_APPROVAL", report["execution"]["status"])
            self.assertLess(
                report["execution"]["after_micros"],
                report["execution"]["before_micros"],
            )
            html_report = (
                Path(temporary) / report["run_id"] / "ui-report.html"
            ).read_text(encoding="utf-8")
            self.assertIn('<div class="change">-10%</div>', html_report)

    def test_test_mode_suspends_campaign_after_spend_without_conversions(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(Path(temporary))

            report = service.run(
                "test",
                scenario={
                    "impressions": 10_000,
                    "clicks": 100,
                    "spend_rub": 2_000,
                    "visits": 100,
                    "conversions": 0,
                    "weekly_budget_rub": 10_000,
                    "baseline_spend_rub": 1_500,
                    "baseline_conversions": 0,
                },
            )

            self.assertEqual("NOT_APPLICABLE", report["metrics"]["cpa_rub"])
            self.assertEqual(
                "SUSPEND_CAMPAIGN",
                report["recommendation"]["action"],
            )
            self.assertEqual("PENDING_APPROVAL", report["execution"]["status"])
            self.assertIsNone(report["execution"]["readback_micros"])

    def test_test_mode_decreases_search_bid_when_cpa_is_high_without_budget_pressure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(Path(temporary))

            report = service.run(
                "test",
                scenario={
                    "impressions": 10_000,
                    "clicks": 100,
                    "spend_rub": 12_000,
                    "visits": 100,
                    "conversions": 10,
                    "weekly_budget_rub": 20_000,
                    "baseline_spend_rub": 10_000,
                    "baseline_conversions": 10,
                },
            )

            self.assertEqual("1200.00", report["metrics"]["cpa_rub"])
            self.assertEqual("60.00", report["metrics"]["budget_utilization_percent"])
            self.assertEqual(
                "DECREASE_SEARCH_BID",
                report["recommendation"]["action"],
            )
            self.assertEqual("PENDING_APPROVAL", report["execution"]["status"])
            self.assertLess(
                report["execution"]["after_micros"],
                report["execution"]["before_micros"],
            )

    def test_test_mode_increases_search_bid_for_efficient_campaign_with_limited_sample(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(Path(temporary))

            report = service.run(
                "test",
                scenario={
                    "impressions": 5_000,
                    "clicks": 75,
                    "spend_rub": 2_500,
                    "visits": 100,
                    "conversions": 5,
                    "weekly_budget_rub": 10_000,
                    "baseline_spend_rub": 2_000,
                    "baseline_conversions": 5,
                },
            )

            self.assertEqual("500.00", report["metrics"]["cpa_rub"])
            self.assertEqual("25.00", report["metrics"]["budget_utilization_percent"])
            self.assertEqual(
                "INCREASE_SEARCH_BID",
                report["recommendation"]["action"],
            )
            self.assertEqual("PENDING_APPROVAL", report["execution"]["status"])
            self.assertGreater(
                report["execution"]["after_micros"],
                report["execution"]["before_micros"],
            )

    def test_test_mode_keeps_settings_for_efficient_campaign_without_budget_pressure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(Path(temporary))

            report = service.run(
                "test",
                scenario={
                    "impressions": 10_000,
                    "clicks": 100,
                    "spend_rub": 5_000,
                    "visits": 100,
                    "conversions": 10,
                    "weekly_budget_rub": 10_000,
                    "baseline_spend_rub": 4_500,
                    "baseline_conversions": 10,
                },
            )

            self.assertEqual("500.00", report["metrics"]["cpa_rub"])
            self.assertEqual("50.00", report["metrics"]["budget_utilization_percent"])
            self.assertEqual("NO_CHANGE", report["recommendation"]["action"])
            self.assertEqual("NO_CHANGE", report["execution"]["status"])
            self.assertEqual(0, report["execution"]["write_calls"])

    def test_test_mode_switches_ad_variant_when_ctr_is_low_with_enough_impressions(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(Path(temporary))

            report = service.run(
                "test",
                scenario={
                    "impressions": 10_000,
                    "clicks": 50,
                    "spend_rub": 1_500,
                    "visits": 100,
                    "conversions": 3,
                    "weekly_budget_rub": 10_000,
                    "baseline_spend_rub": 1_200,
                    "baseline_conversions": 3,
                },
            )

            self.assertEqual("0.50", report["metrics"]["ctr_percent"])
            self.assertEqual(
                "SET_AD_VARIANT",
                report["recommendation"]["action"],
            )
            self.assertEqual("PENDING_APPROVAL", report["execution"]["status"])
            self.assertIsNone(report["execution"]["readback_micros"])

    def test_test_mode_uses_operator_recommendation_thresholds_without_weakening_gate0(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(Path(temporary))
            recommendation_rules = service.automation()["recommendation_rules"]
            recommendation_rules["target_cpa_rub"] = 800

            report = service.run(
                "test",
                scenario={
                    "impressions": 10_000,
                    "clicks": 100,
                    "spend_rub": 9_000,
                    "visits": 100,
                    "conversions": 10,
                    "weekly_budget_rub": 4_000,
                    "baseline_spend_rub": 8_000,
                    "baseline_conversions": 10,
                },
                recommendation_rules=recommendation_rules,
            )

            self.assertEqual("900.00", report["metrics"]["cpa_rub"])
            self.assertEqual(
                "DECREASE_WEEKLY_BUDGET",
                report["recommendation"]["action"],
            )
            self.assertEqual("PENDING_APPROVAL", report["execution"]["status"])
            self.assertEqual(
                "EXACT_APPROVAL_REQUIRED",
                report["execution"]["reason_code"],
            )
            self.assertEqual(
                800,
                report["decision"]["recommendation_rules"]["target_cpa_rub"],
            )

    def test_automation_settings_cannot_weaken_gate0_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(Path(temporary))
            settings = service.automation()

            settings["rules"]["budget_pressure"]["threshold_percent"] = 89
            with self.assertRaises(UiRunRejected) as rejected:
                service.configure_automation(settings)

            self.assertEqual(
                "RULE_OUTSIDE_SAFETY_BOUNDARY", rejected.exception.reason_code
            )

    def test_automation_is_test_only_and_survives_service_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = UiRunService(root)
            settings = service.automation()
            settings.update({"enabled": True, "interval_minutes": 360})
            service.configure_automation(settings)

            reopened = UiRunService(root)
            persisted = reopened.automation()
            self.assertTrue(persisted["enabled"])
            self.assertEqual("test", persisted["mode"])
            self.assertEqual(360, persisted["interval_minutes"])

            persisted["mode"] = "production"
            with self.assertRaises(UiRunRejected) as rejected:
                reopened.configure_automation(persisted)
            self.assertEqual("TEST_AUTOMATION_ONLY", rejected.exception.reason_code)

    def test_enabling_automation_runs_one_due_cycle_and_records_why(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(Path(temporary))
            settings = service.automation()
            settings.update(
                {
                    "enabled": True,
                    "mode": "test",
                    "operating_mode": "RECOMMEND",
                    "interval_minutes": 60,
                }
            )
            saved = service.configure_automation(settings)

            self.assertIsNotNone(saved["next_run_at"])
            report = service.run_due_automation()
            self.assertIsNotNone(report)
            assert report is not None
            self.assertEqual("SCHEDULED", report["origin"])
            self.assertEqual(
                ["BUDGET_PRESSURE"],
                [
                    item["reason_code"]
                    for item in report["decision"]["matched_triggers"]
                ],
            )
            self.assertEqual("RECOMMEND", report["operating_mode"])
            self.assertEqual("NOT_STARTED", report["execution"]["status"])
            self.assertIsNone(service.run_due_automation())
            history = service.decision_history()
            self.assertEqual(report["run_id"], history[0]["run_id"])
            self.assertIn("бюджет", history[0]["reason"].lower())

    def test_scheduled_failure_is_visible_in_decision_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(Path(temporary))
            settings = service.automation()
            settings.update(
                {
                    "enabled": True,
                    "mode": "test",
                    "operating_mode": "BOUNDED_AUTONOMY",
                    "interval_minutes": 60,
                }
            )
            service.configure_automation(settings)

            with self.assertRaisesRegex(UiRunRejected, "Mandate"):
                service.run_due_automation()

            history = service.decision_history()
            self.assertEqual(1, len(history))
            self.assertEqual("FAILED", history[0]["status"])
            self.assertEqual("BLOCKED", history[0]["execution_status"])
            self.assertIn("MANDATE_REQUIRED", history[0]["reason"])
            self.assertEqual("", history[0]["report_href"])

    def test_scheduled_mode_resolution_failure_is_visible_in_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(Path(temporary))
            settings = service.automation()
            settings.update(
                {
                    "enabled": True,
                    "mode": "test",
                    "operating_mode": "RECOMMEND",
                    "interval_minutes": 60,
                }
            )
            service.configure_automation(settings)

            def unavailable_mode() -> str:
                raise RuntimeError("durable mode unavailable")

            service.configure_operating_mode_provider(unavailable_mode)

            with self.assertRaisesRegex(RuntimeError, "mode unavailable"):
                service.run_due_automation()

            history = service.decision_history()
            self.assertEqual(1, len(history))
            self.assertEqual("FAILED", history[0]["status"])
            self.assertIn("RuntimeError", history[0]["reason"])
            self.assertIn("durable mode unavailable", history[0]["reason"])

    def test_scheduled_cycle_without_trigger_records_no_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(Path(temporary))
            settings = service.automation()
            settings["enabled"] = True
            settings["operating_mode"] = "RECOMMEND"
            settings["rules"]["budget_pressure"]["threshold_percent"] = 100
            settings["rules"]["spend_growth_without_conversion"]["enabled"] = False
            settings["rules"]["no_conversion_spend"]["enabled"] = False
            service.configure_automation(settings)

            report = service.run_due_automation()

            self.assertIsNotNone(report)
            assert report is not None
            self.assertEqual([], report["decision"]["matched_triggers"])
            self.assertEqual("NOT_STARTED", report["execution"]["status"])
            self.assertEqual("NO_TRIGGER_MATCH", report["execution"]["reason_code"])
            self.assertFalse(report["execution"]["executor_invoked"])
            self.assertEqual("SKIPPED", report["steps"][-1]["status"])

    def test_operator_can_revise_pending_change_size_before_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = UiRunService(root)
            pending = service.run(
                "test",
                origin="MANUAL",
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

            revised = service.revise_pending_run(
                pending["run_id"],
                relative_step_percent=5,
            )

            self.assertNotEqual(pending["run_id"], revised["run_id"])
            self.assertEqual(pending["run_id"], revised["source_run_id"])
            self.assertEqual(5, revised["recommendation"]["relative_step_percent"])
            self.assertEqual(5, revised["execution"]["relative_step_percent"])
            self.assertEqual(
                revised["execution"]["before_micros"] * 95 // 100,
                revised["execution"]["after_micros"],
            )
            self.assertEqual("PENDING_APPROVAL", revised["execution"]["status"])
            self.assertFalse(revised["execution"]["executor_invoked"])
            proposal = json.loads(
                (root / revised["run_id"] / "proposal.json").read_text(encoding="utf-8")
            )
            self.assertEqual(5, proposal["expected_diff"]["relative_step_percent"])
            self.assertIn("изменил размер", revised["decision"]["reason"])

    def test_operator_revision_rejects_step_outside_policy_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(Path(temporary))
            pending = service.run("test", origin="MANUAL")

            with self.assertRaises(UiRunRejected) as rejected:
                service.revise_pending_run(
                    pending["run_id"],
                    relative_step_percent=11,
                )

            self.assertEqual(
                "PROPOSAL_REVISION_OUTSIDE_POLICY",
                rejected.exception.reason_code,
            )

    def test_production_mode_runs_read_only_without_execution_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = UiRunService(
                Path(temporary),
                production_reader=StubProductionReader(),
            )

            with patch(
                "mox_adv.ui_service._execute_simulated_change"
            ) as execute_change:
                report = service.run("production")

            self.assertEqual("SUCCEEDED", report["status"])
            self.assertEqual("PRODUCTION_READ_ONLY", report["mode"])
            self.assertEqual(
                {
                    "direct": "YANDEX_DIRECT_API",
                    "metrika": "YANDEX_METRIKA_API",
                },
                report["sources"],
            )
            self.assertEqual("EFFECTIVE", report["recommendation"]["status"])
            self.assertEqual("NOT_STARTED", report["execution"]["status"])
            self.assertEqual("READ_ONLY_MODE", report["execution"]["reason_code"])
            self.assertEqual(0, report["execution"]["write_calls"])
            self.assertFalse(report["execution"]["executor_invoked"])
            self.assertFalse(report["safety"]["external_write_sent"])
            self.assertFalse(report["safety"]["write_requests_allowed"])
            self.assertTrue(report["safety"]["credential_loaded"])
            self.assertEqual(3, len(report["safety"]["read_requests"]))
            self.assertEqual("DISABLED", report["safety"]["approval"])
            self.assertEqual("SKIPPED", report["steps"][-1]["status"])
            run_directory = Path(temporary) / report["run_id"]
            self.assertTrue((run_directory / "ui-report.html").is_file())
            self.assertTrue((run_directory / "proposal.json").is_file())
            self.assertFalse((run_directory / "approval.json").exists())
            self.assertFalse((run_directory / "control.sqlite3").exists())
            execute_change.assert_not_called()
            html_report = (run_directory / "ui-report.html").read_text(encoding="utf-8")
            self.assertIn("Реальные read-only данные Яндекса", html_report)
            self.assertIn("Три разрешённых запроса чтения", html_report)
            self.assertIn(
                "Правила тестового автопилота в основном режиме не оценивались",
                html_report,
            )
            readiness = service.status()["production_mode"]
            self.assertTrue(readiness["ready"])
            self.assertEqual("READ_ONLY", readiness["access"])
            self.assertTrue(readiness["external_reads_enabled"])
            self.assertEqual([], readiness["blockers"])

    def test_production_mode_fails_closed_when_real_read_is_not_configured(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = UiRunService(
                root,
                production_reader=PairedYandexProductionReaderV1(
                    paired_configuration_path=root / "missing-paired.json",
                    direct_configuration_path=root / "missing-direct.json",
                    metrika_configuration_path=root / "missing-metrika.json",
                    direct_environment_path=root / ".env",
                    metrika_environment_path=root / ".env",
                ),
            )

            with self.assertRaises(UiRunRejected) as rejected:
                service.run("production")

            self.assertEqual(
                "PRODUCTION_NOT_READY",
                rejected.exception.reason_code,
            )
            readiness = service.status()["production_mode"]
            self.assertFalse(readiness["ready"])
            self.assertEqual(
                "YANDEX_PRODUCTION_API",
                readiness["data_source"],
            )
            self.assertTrue(readiness["external_reads_enabled"])


if __name__ == "__main__":
    unittest.main()
