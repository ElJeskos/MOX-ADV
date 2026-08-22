from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from mox_adv.control_state import (
    AuthenticatedPrincipal,
    ElevatedAuthenticatedPrincipal,
    MacOSElevatedSecurityVerifier,
)
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

    def elevated_reauthenticate(self) -> ElevatedAuthenticatedPrincipal:
        self.elevated_calls += 1
        with patch.object(
            MacOSElevatedSecurityVerifier,
            "verify",
            return_value=True,
        ):
            return ElevatedAuthenticatedPrincipal.verified(
                self.authenticate(),
                MacOSElevatedSecurityVerifier(),
            )


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
            draft = first.campaign_overview()
            technical = first.run_goal_technical_simulation(
                draft["draft_id"],
                expected_revision=draft["revision"],
            )
            pending = first.goal_lifecycle_overview(draft["draft_id"])
            self.assertEqual(
                "AWAITING_SEMANTIC_DECISION",
                pending["lifecycle_status"],
            )
            self.assertEqual("VERIFIED", pending["technical_status"])

            reopened = DashboardApplication(root)
            result = reopened.decide_pending_goal_simulation(
                "REJECT",
                draft_id=draft["draft_id"],
                expected_revision=draft["revision"],
                run_id=technical["run_id"],
            )

            self.assertEqual(technical["run_id"], result["run_id"])
            self.assertEqual("REJECTED", result["status"])
            self.assertTrue(result["cleanup"]["performed"])
            self.assertEqual(1, result["cleanup"]["fake_goal_deleted"])
            self.assertEqual(1, result["cleanup"]["fake_site_rollback"])
            rejected = DashboardApplication(root).goal_lifecycle_overview(
                draft["draft_id"]
            )
            self.assertEqual("REJECTED", rejected["lifecycle_status"])
            self.assertEqual(technical["run_id"], rejected["run_id"])

    def test_goal_technical_verification_requires_explicit_draft_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = DashboardApplication(Path(temporary))

            with self.assertRaisesRegex(
                ValueError,
                "Выберите тестовую кампанию",
            ):
                app.run_goal_technical_simulation("", expected_revision=0)

    def test_only_one_goal_technical_verification_can_be_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = DashboardApplication(root)
            draft = app.campaign_overview()

            def start_verification(_: int) -> str:
                result = app.run_goal_technical_simulation(
                    draft["draft_id"],
                    expected_revision=draft["revision"],
                )
                return str(result["run_id"])

            with ThreadPoolExecutor(max_workers=8) as executor:
                submitted = [
                    executor.submit(start_verification, index) for index in range(8)
                ]

            successes = []
            failures = []
            for future in submitted:
                try:
                    successes.append(future.result())
                except ValueError as error:
                    failures.append(str(error))

            self.assertEqual(1, len(successes))
            self.assertEqual(7, len(failures))
            self.assertTrue(
                all(
                    error == "GOAL_SEMANTIC_DECISION_ALREADY_PENDING"
                    for error in failures
                )
            )
            self.assertEqual(
                1,
                len(list(root.glob("ui-goal-*/goal_technical.json"))),
            )

    def test_outdated_pending_goal_can_be_rejected_and_reverified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = DashboardApplication(root)
            draft = app.campaign_overview()
            technical = app.run_goal_technical_simulation(
                draft["draft_id"],
                expected_revision=draft["revision"],
            )
            changed_goal = dict(draft["business_goal"])
            changed_goal["meaning"] = "Новая версия бизнес-смысла цели"
            saved = app.save_campaign_draft(
                {
                    "campaign": draft["campaign"],
                    "business_goal": changed_goal,
                    "goal_settings": draft["goal_settings"],
                    "ad_groups": draft["ad_groups"],
                },
                draft["revision"],
                draft["draft_id"],
            )

            outdated = app.goal_lifecycle_overview(draft["draft_id"])
            self.assertEqual("OUTDATED", outdated["lifecycle_status"])
            self.assertTrue(outdated["can_reject"])
            with self.assertRaisesRegex(
                ValueError,
                "GOAL_TECHNICAL_VERIFICATION_OUTDATED",
            ):
                app.decide_pending_goal_simulation(
                    "APPROVE",
                    draft_id=draft["draft_id"],
                    expected_revision=saved["revision"],
                    run_id=technical["run_id"],
                )

            rejected = app.decide_pending_goal_simulation(
                "REJECT",
                draft_id=draft["draft_id"],
                expected_revision=saved["revision"],
                run_id=technical["run_id"],
            )
            rerun = app.run_goal_technical_simulation(
                draft["draft_id"],
                expected_revision=saved["revision"],
            )

            self.assertEqual("REJECTED", rejected["status"])
            self.assertNotEqual(technical["run_id"], rerun["run_id"])

    def test_restart_reconciles_goal_evidence_after_semantic_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = DashboardApplication(root)
            draft = first.campaign_overview()
            technical = first.run_goal_technical_simulation(
                draft["draft_id"],
                expected_revision=draft["revision"],
            )

            with (
                patch.object(
                    first,
                    "_write_workflow_evidence",
                    side_effect=OSError("simulated evidence failure"),
                ),
                self.assertRaisesRegex(OSError, "evidence failure"),
            ):
                first.decide_pending_goal_simulation(
                    "APPROVE",
                    draft_id=draft["draft_id"],
                    expected_revision=draft["revision"],
                    run_id=technical["run_id"],
                )

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

    def test_restart_quarantines_corrupt_completed_goal_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_directory = root / "ui-goal-corrupt"
            run_directory.mkdir()
            (run_directory / "goal_workflow.json").write_text(
                "{not-json",
                encoding="utf-8",
            )
            for name in (
                ".dashboard-audit.sqlite3",
                "artifact-manifest.json",
                "events.jsonl",
                "report.md",
                "result.json",
                "signed-audit-anchor.json",
            ):
                (run_directory / name).write_text("corrupt", encoding="utf-8")

            DashboardApplication(root)

            self.assertFalse(run_directory.exists())
            quarantine = root / ".incomplete-dashboard-evidence"
            quarantined = list(quarantine.glob("ui-goal-corrupt-*"))
            self.assertEqual(1, len(quarantined))
            self.assertEqual(
                "{not-json",
                (quarantined[0] / "goal_workflow.json").read_text(encoding="utf-8"),
            )

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

    def test_failed_campaign_launch_is_not_reported_as_launched(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = DashboardApplication(root)
            editor = app.campaign_overview()
            draft = app.campaign_store.campaign_draft_payload()
            run_id = "ui-campaign-20260730T120000000000Z"
            run_directory = root / run_id
            run_directory.mkdir()
            (run_directory / "campaign_workflow.json").write_text(
                json.dumps(
                    {
                        "workflow": "CAMPAIGN_LIFECYCLE",
                        "status": "FAILED",
                        "execution_mode": "SIMULATION",
                        "run_id": run_id,
                        "requested_at": "2026-07-30T12:00:00+00:00",
                        "exact_diff": {
                            "operation": "CREATE_UNIFIED_SEARCH_CAMPAIGN",
                            "before": None,
                            "after": draft,
                        },
                        "completed_steps": ["CAMPAIGN_ADD"],
                        "external_write_sent": False,
                        "detail": "MODERATION_READBACK_FAILED",
                    }
                ),
                encoding="utf-8",
            )
            changed_campaign = dict(editor["campaign"])
            changed_campaign["name"] = "Изменённая версия кампании"
            app.save_campaign_draft(
                {
                    "campaign": changed_campaign,
                    "business_goal": editor["business_goal"],
                    "goal_settings": editor["goal_settings"],
                    "ad_groups": editor["ad_groups"],
                },
                editor["revision"],
                editor["draft_id"],
            )

            overview = DashboardApplication(root).campaign_launch_overview(
                draft["draft_id"]
            )

            self.assertEqual("FAILED", overview["launch_status"])
            self.assertEqual("FAILED", overview["workflow_status"])
            self.assertFalse(overview["current"])
            self.assertEqual(
                "MODERATION_READBACK_FAILED",
                overview["message"],
            )

    def test_campaign_launch_requires_explicit_draft_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = DashboardApplication(Path(temporary))

            with self.assertRaisesRegex(
                ValueError,
                "Выберите тестовую кампанию",
            ):
                app.run_campaign_simulation("", expected_revision=0)

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

            campaign_draft = app.campaign_overview()
            campaign = app.run_campaign_simulation(
                campaign_draft["draft_id"],
                expected_revision=campaign_draft["revision"],
            )
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
