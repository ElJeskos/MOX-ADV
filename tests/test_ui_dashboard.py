from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mox_adv.control_state import AuthenticatedPrincipal
from mox_adv.e2e_evidence import verify_e2e_artifact_manifest
from mox_adv.ui_dashboard import DashboardApplication
from mox_adv.ui_service import UiRunService


class StubDashboardAuthenticator:
    def __init__(self) -> None:
        self.elevated_calls = 0

    @staticmethod
    def authenticate() -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            identity="sviridov",
            authentication="authenticated_macos_user",
        )

    def elevated_reauthenticate(self) -> AuthenticatedPrincipal:
        self.elevated_calls += 1
        return self.authenticate()


class DashboardApplicationTests(unittest.TestCase):
    def test_enabling_autopilot_issues_authority_and_fixes_autonomous_mode(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = UiRunService(root)
            app = DashboardApplication(
                root,
                service,
                authenticator=StubDashboardAuthenticator(),
            )
            settings = service.automation()
            settings.update(
                {
                    "enabled": True,
                    "mode": "test",
                    "operating_mode": "OBSERVE",
                    "interval_minutes": 60,
                }
            )

            saved = app.configure_test_automation(settings)

            self.assertTrue(saved["enabled"])
            self.assertEqual("BOUNDED_AUTONOMY", saved["operating_mode"])
            active = [
                item
                for item in app.control_overview()["mandates"]
                if item["status"] == "ACTIVE"
            ]
            self.assertEqual(1, len(active))

    def test_empty_dashboard_does_not_claim_gate_one_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            overview = DashboardApplication(Path(temporary)).evidence_overview()

            gate_one = next(
                item for item in overview["gates"] if item["gate"] == "GATE_1"
            )
            self.assertEqual("NOT_READY", gate_one["status"])

    def test_approval_is_bound_to_the_explicitly_displayed_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = UiRunService(root)
            app = DashboardApplication(root, service)
            first = service.run(
                "test",
                operating_mode="APPROVAL_REQUIRED",
            )
            service.run(
                "test",
                operating_mode="APPROVAL_REQUIRED",
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

            approval = app.grant_pending_proposal(first["run_id"])

            self.assertEqual(
                first["recommendation"]["proposal_id"],
                approval["proposal_id"],
            )

    def test_pending_goal_semantic_decision_survives_dashboard_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = DashboardApplication(root)
            technical = first.run_goal_technical_simulation()

            reopened = DashboardApplication(root)
            result = reopened.decide_pending_goal_simulation("REJECT")

            self.assertEqual(technical["run_id"], result["run_id"])
            self.assertEqual("REJECTED", result["status"])
            self.assertTrue(result["cleanup"]["performed"])
            self.assertEqual(1, result["cleanup"]["fake_goal_deleted"])
            self.assertEqual(1, result["cleanup"]["fake_site_rollback"])

    def test_restart_reconciles_goal_evidence_after_semantic_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = DashboardApplication(root)
            technical = first.run_goal_technical_simulation()

            with (
                patch.object(
                    first,
                    "_write_workflow_evidence",
                    side_effect=OSError("simulated evidence failure"),
                ),
                self.assertRaisesRegex(OSError, "evidence failure"),
            ):
                first.decide_pending_goal_simulation("APPROVE")

            run_directory = root / technical["run_id"]
            self.assertTrue((run_directory / "goal_workflow.json").is_file())
            self.assertFalse((run_directory / "result.json").exists())
            (run_directory / "events.jsonl").write_text(
                '{"partial":true}\n',
                encoding="utf-8",
            )
            (run_directory / ".result.json.crash-tmp").write_text(
                "partial result",
                encoding="utf-8",
            )

            DashboardApplication(root)

            self.assertTrue((run_directory / "result.json").is_file())
            self.assertTrue((run_directory / "events.jsonl").is_file())
            quarantine = root / ".incomplete-dashboard-evidence"
            quarantined_events = list(quarantine.glob("*/events.jsonl"))
            self.assertEqual(1, len(quarantined_events))
            self.assertEqual(
                '{"partial":true}\n',
                quarantined_events[0].read_text(encoding="utf-8"),
            )
            self.assertEqual(
                1,
                len(list(quarantine.glob("*/.result.json.crash-tmp"))),
            )
            manifest = json.loads(
                (run_directory / "artifact-manifest.json").read_text(encoding="utf-8")
            )
            self.assertNotIn(".result.json.crash-tmp", manifest["artifacts"])

    def test_scheduler_uses_autopilot_authority_without_visible_mode_switch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = UiRunService(root)
            app = DashboardApplication(
                root,
                service,
                authenticator=StubDashboardAuthenticator(),
            )
            settings = service.automation()
            settings.update({"enabled": True, "operating_mode": "OBSERVE"})
            settings["scenario"].update(
                {
                    "spend_rub": 12_000,
                    "conversions": 10,
                    "weekly_budget_rub": 20_000,
                    "baseline_spend_rub": 10_000,
                    "baseline_conversions": 10,
                }
            )
            configured = app.configure_test_automation(settings)
            report = service.run_due_automation()

            self.assertEqual("BOUNDED_AUTONOMY", configured["operating_mode"])
            self.assertIsNotNone(report)
            assert report is not None
            self.assertEqual("BOUNDED_AUTONOMY", report["operating_mode"])
            self.assertEqual("APPLIED", report["execution"]["status"])
            self.assertTrue(report["execution"]["executor_invoked"])

    def test_kill_switch_release_requires_elevated_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authenticator = StubDashboardAuthenticator()
            app = DashboardApplication(
                Path(temporary),
                authenticator=authenticator,
            )
            app.engage_kill_switch("campaign")

            with self.assertRaisesRegex(
                ValueError,
                "ELEVATED_RELEASE_CONFIRMATION_REQUIRED",
            ):
                app.release_kill_switch("campaign", "")

            released = app.release_kill_switch("campaign", "RELEASE")
            self.assertFalse(released["active"])
            self.assertEqual(1, authenticator.elevated_calls)

    def test_control_workflows_and_evidence_use_public_json_and_artifact_seams(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = DashboardApplication(root)

            control = app.control_overview()
            self.assertEqual(
                [
                    "OBSERVE",
                    "RECOMMEND",
                    "APPROVAL_REQUIRED",
                    "BOUNDED_AUTONOMY",
                ],
                [item["name"] for item in control["operating_modes"]],
            )
            self.assertEqual(
                "RECOMMEND",
                app.select_operating_mode("RECOMMEND")["selected"],
            )

            campaign = app.run_campaign_simulation()
            goal = app.run_goal_simulation("APPROVE")
            impact = app.run_impact_fixture("IMPACT_CPA_WORSE_ROLLBACK")

            self.assertEqual("APPLIED", campaign["status"])
            self.assertEqual("APPROVED", goal["status"])
            self.assertEqual("ROLLBACK_CHANGE", impact["recommended_next_decision"])
            for result in (campaign, goal, impact):
                run_directory = root / result["run_id"]
                self.assertTrue((run_directory / "result.json").is_file())
                self.assertTrue((run_directory / "report.md").is_file())
                self.assertTrue((run_directory / "events.jsonl").is_file())

            evidence = app.run_full_evidence()
            self.assertEqual(14, len(evidence["capabilities"]))
            self.assertEqual("NOT_PROVEN", evidence["overall_status"])
            self.assertTrue(
                (root / evidence["run_id"] / "artifact-manifest.json").is_file()
            )
            self.assertTrue(
                (root / evidence["run_id"] / "acceptance-report.html").is_file()
            )
            self.assertIn(
                "acceptance-report.html",
                evidence["artifacts"],
            )
            verify_e2e_artifact_manifest(root / evidence["run_id"])
            partial = root / "newer-partial-observe"
            partial.mkdir()
            (partial / "result.json").write_text(
                json.dumps(
                    {
                        "run_id": partial.name,
                        "evidence_type": "SIMULATED",
                        "status": "SUCCEEDED",
                    }
                ),
                encoding="utf-8",
            )
            (partial / "capability-evidence.json").write_text(
                json.dumps({"capabilities": []}),
                encoding="utf-8",
            )

            overview = app.evidence_overview()

            self.assertEqual(evidence["run_id"], overview["run_id"])


if __name__ == "__main__":
    unittest.main()
