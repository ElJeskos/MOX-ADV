from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mox_adv.campaign_lifecycle import CampaignDraftSafetyBindings
from mox_adv.ui_workflows import (
    DashboardWorkflowFacade,
    DashboardWorkflowRejected,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "gate0-policy.json"


def campaign_draft_payload() -> dict[str, object]:
    return {
        "schema_version": "campaign-draft-v1",
        "draft_id": "dashboard-draft-1",
        "business_goal": {
            "event": "lead_submitted",
            "meaning": "A visitor submitted the lead form.",
        },
        "primary_conversion": {"event": "lead_submitted"},
        "campaign_type": "UNIFIED_CAMPAIGN",
        "strategy": {
            "placement": "SEARCH",
            "search": "HIGHEST_POSITION",
            "network": "SERVING_OFF",
        },
        "geography": ["RU"],
        "schedule": {
            "timezone": "Europe/Moscow",
            "days": ["MONDAY", "TUESDAY"],
            "start": "09:00",
            "end": "18:00",
        },
        "budget": {"currency": "RUB", "weekly_micros": 500_000_000},
        "limits": {
            "maximum_weekly_micros": 500_000_000,
            "maximum_bid_micros": 100_000_000,
        },
        "groups": [
            {
                "name": "Lead service",
                "keywords": ["lead service"],
                "negative_keywords": ["free"],
                "audiences": [],
                "ads": [
                    {
                        "variant_id": "A",
                        "title": "Lead service",
                        "text": "Submit a request",
                        "landing_page": "https://allowlisted.example/lead",
                        "utm": "utm_source=yandex&utm_content=a",
                        "media_reference": "prepared-media-1",
                    },
                    {
                        "variant_id": "B",
                        "title": "Lead service alternative",
                        "text": "Request a consultation",
                        "landing_page": "https://allowlisted.example/lead",
                        "utm": "utm_source=yandex&utm_content=b",
                        "media_reference": "prepared-media-2",
                    },
                ],
            }
        ],
        "landing_page": "https://allowlisted.example/lead",
        "media_references": ["prepared-media-1", "prepared-media-2"],
    }


def campaign_safety() -> CampaignDraftSafetyBindings:
    return CampaignDraftSafetyBindings(
        allowed_landing_hosts=("allowlisted.example",),
        prohibited_phrases=("guaranteed results",),
        prepared_media_references=("prepared-media-1", "prepared-media-2"),
    )


def goal_candidate_payload() -> dict[str, object]:
    return {
        "schema_version": "goal-candidate-v1",
        "name": "Submitted lead",
        "event": "lead_submitted",
        "site_location": "#lead-form",
        "type": "ACTION",
        "business_meaning": "A visitor submitted the lead form.",
        "priority": 1,
        "duplicate_signals": [],
    }


class WorkflowFacadeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.runs_root = Path(self.temporary_directory.name)
        self.facade = DashboardWorkflowFacade(
            runs_root=self.runs_root,
            policy_path=POLICY_PATH,
            campaign_safety=campaign_safety(),
        )


class CampaignWorkflowFacadeTests(WorkflowFacadeTestCase):
    def test_campaign_preview_is_a_complete_json_operator_contract(self) -> None:
        draft = campaign_draft_payload()

        result = self.facade.preview_campaign(
            run_id="dashboard-campaign-preview-1",
            proposal_id="proposal-dashboard-campaign-1",
            draft_payload=draft,
        )

        json.dumps(result)
        self.assertEqual("READY_FOR_SIMULATION", result["status"])
        self.assertEqual("SIMULATION", result["execution_mode"])
        self.assertEqual(
            {
                "operation": "CREATE_UNIFIED_SEARCH_CAMPAIGN",
                "before": None,
                "after": draft,
            },
            result["exact_diff"],
        )
        self.assertEqual(
            ["CREATE_OBJECTS", "SUBMIT_MODERATION", "LAUNCH_CAMPAIGN"],
            result["risks"],
        )
        self.assertEqual("APPROVAL", result["authority_requirement"]["kind"])
        self.assertEqual(
            "sim-campaign-creation-reservation",
            result["authority_requirement"]["reservation_id"],
        )
        self.assertRegex(
            result["authority_requirement"]["exact_binding"],
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertEqual([], result["evidence_paths"])

    def test_campaign_simulation_runs_the_fake_saga_and_writes_evidence(self) -> None:
        result = self.facade.run_campaign(
            run_id="dashboard-campaign-run-1",
            proposal_id="proposal-dashboard-campaign-1",
            draft_payload=campaign_draft_payload(),
            execution_mode="SIMULATION",
            requested_at="2026-07-30T09:00:00+00:00",
        )

        json.dumps(result)
        self.assertEqual("APPLIED", result["status"])
        self.assertEqual(
            [
                "CAMPAIGN_ADD",
                "AD_GROUP_ADD",
                "ADS_ADD",
                "KEYWORD_ADD",
                "MODERATION_SUBMIT",
                "MODERATION_READBACK",
                "CAMPAIGN_LAUNCH",
                "FULL_READBACK",
            ],
            result["completed_steps"],
        )
        self.assertEqual(
            ["Campaigns", "AdGroups", "Ads", "Ads", "Keywords"],
            [item["service"] for item in result["created_objects"]],
        )
        self.assertGreater(result["fake_adapter_call_count"], 0)
        self.assertEqual(
            "SIMULATED",
            result["authority_evidence"]["evidence_type"],
        )
        self.assertTrue(result["authority_evidence"]["not_valid_for_production"])
        self.assertFalse(result["external_write_sent"])
        evidence_path = Path(result["evidence_paths"][0])
        self.assertEqual(
            self.runs_root / "dashboard-campaign-run-1" / "campaign_workflow.json",
            evidence_path,
        )
        self.assertEqual(
            result,
            json.loads(evidence_path.read_text(encoding="utf-8")),
        )

    def test_campaign_production_run_fails_closed_without_exact_authority(self) -> None:
        with self.assertRaisesRegex(
            DashboardWorkflowRejected,
            "PRODUCTION_WRITE_FORBIDDEN",
        ):
            self.facade.run_campaign(
                run_id="dashboard-campaign-production-1",
                proposal_id="proposal-dashboard-campaign-1",
                draft_payload=campaign_draft_payload(),
                execution_mode="PRODUCTION",
                requested_at="2026-07-30T09:00:00+00:00",
                authority=None,
            )

        self.assertFalse((self.runs_root / "dashboard-campaign-production-1").exists())

    def test_campaign_production_cannot_compose_a_write_executor(self) -> None:
        calls = []

        def controlled_executor(plan):
            calls.append(plan)
            raise AssertionError("Production executor must never be called.")

        with self.assertRaisesRegex(
            DashboardWorkflowRejected,
            "PRODUCTION_WRITE_FORBIDDEN",
        ):
            DashboardWorkflowFacade(
                runs_root=self.runs_root,
                policy_path=POLICY_PATH,
                campaign_safety=campaign_safety(),
                production_campaign_executor=controlled_executor,
            )
        with self.assertRaisesRegex(
            DashboardWorkflowRejected,
            "PRODUCTION_WRITE_FORBIDDEN",
        ):
            self.facade.preview_campaign(
                run_id="dashboard-campaign-production-2",
                proposal_id="proposal-dashboard-campaign-production-2",
                draft_payload=campaign_draft_payload(),
                execution_mode="PRODUCTION",
            )
        self.assertEqual([], calls)


class GoalWorkflowFacadeTests(WorkflowFacadeTestCase):
    def test_goal_preview_discloses_both_exact_authority_boundaries(self) -> None:
        candidate = goal_candidate_payload()

        result = self.facade.preview_goal(
            run_id="dashboard-goal-preview-1",
            proposal_id="proposal-dashboard-goal-1",
            candidate_payload=candidate,
            expected_site_version="test-page-v1",
        )

        json.dumps(result)
        self.assertEqual("READY_FOR_SIMULATION", result["status"])
        self.assertEqual("sim-test-counter", result["target"]["counter_id"])
        self.assertEqual(
            {
                "operation": "CREATE_GOAL_AND_INSTALL_REACH_GOAL",
                "before": {"metrika_goal": None, "site_event": None},
                "after": {
                    "metrika_goal": candidate,
                    "site_event": {
                        "event": "lead_submitted",
                        "selector": "#lead-form",
                        "page_version": "test-page-v1+dashboard-goal-preview-1",
                    },
                },
            },
            result["exact_diff"],
        )
        self.assertEqual(
            [
                "CREATE_METRIKA_GOAL",
                "PUBLISH_SITE_EVENT",
                "SEMANTIC_MISCLASSIFICATION",
            ],
            result["risks"],
        )
        creation = result["authority_requirement"]["goal_creation"]
        publication = result["authority_requirement"]["site_publish"]
        self.assertEqual("APPROVAL_OR_MANDATE", creation["kind"])
        self.assertEqual("APPROVAL", publication["kind"])
        self.assertRegex(creation["exact_binding"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(publication["exact_binding"], r"^sha256:[0-9a-f]{64}$")
        self.assertNotEqual(
            creation["exact_binding"],
            publication["exact_binding"],
        )
        self.assertEqual([], result["evidence_paths"])

    def test_goal_simulation_supports_human_approval_and_rejection(self) -> None:
        for decision, expected_status, cleanup_performed in (
            ("APPROVE", "APPROVED", False),
            ("REJECT", "REJECTED", True),
        ):
            with self.subTest(decision=decision):
                run_id = "dashboard-goal-" + decision.lower()
                result = self.facade.run_goal(
                    run_id=run_id,
                    proposal_id="proposal-" + run_id,
                    candidate_payload=goal_candidate_payload(),
                    expected_site_version="test-page-v1",
                    execution_mode="SIMULATION",
                    requested_at="2026-07-30T09:00:00+00:00",
                    semantic_decision=decision,
                    reviewer="sviridov",
                )

                json.dumps(result)
                self.assertEqual(expected_status, result["status"])
                self.assertEqual("VERIFIED", result["technical_status"])
                self.assertEqual(
                    "PRIMARY",
                    result["technical_evidence"]["classification"],
                )
                self.assertEqual(
                    cleanup_performed,
                    result["cleanup"]["performed"],
                )
                self.assertEqual(
                    "SIMULATED",
                    result["semantic_authentication"]["evidence_type"],
                )
                self.assertTrue(
                    result["semantic_authentication"]["not_valid_for_production"]
                )
                self.assertFalse(result["external_write_sent"])
                self.assertEqual(1, result["fake_adapter_calls"]["goal_add"])
                self.assertEqual(1, result["fake_adapter_calls"]["site_publish"])
                evidence_path = Path(result["evidence_paths"][0])
                self.assertEqual(
                    self.runs_root / run_id / "goal_workflow.json",
                    evidence_path,
                )
                self.assertEqual(
                    result,
                    json.loads(evidence_path.read_text(encoding="utf-8")),
                )

    def test_goal_technical_verification_precedes_separate_human_decision(
        self,
    ) -> None:
        run_id = "dashboard-goal-staged"
        technical = self.facade.run_goal_technical(
            run_id=run_id,
            proposal_id="proposal-" + run_id,
            candidate_payload=goal_candidate_payload(),
            expected_site_version="test-page-v1",
            requested_at="2026-07-30T09:00:00+00:00",
        )

        self.assertEqual(
            "AWAITING_SEMANTIC_DECISION",
            technical["status"],
        )
        self.assertEqual("VERIFIED", technical["technical_status"])
        self.assertIsNone(technical["semantic_decision"])
        self.assertFalse(technical["cleanup"]["performed"])

        decided = self.facade.decide_goal_simulation(
            run_id=run_id,
            semantic_decision="REJECT",
            reviewer="sviridov",
            requested_at="2026-07-30T09:01:00+00:00",
        )

        self.assertEqual("REJECTED", decided["status"])
        self.assertEqual("REJECT", decided["semantic_decision"])
        self.assertTrue(decided["cleanup"]["performed"])

    def test_goal_production_run_fails_closed_without_exact_authority(self) -> None:
        with self.assertRaisesRegex(
            DashboardWorkflowRejected,
            "PRODUCTION_WRITE_FORBIDDEN",
        ):
            self.facade.run_goal(
                run_id="dashboard-goal-production-1",
                proposal_id="proposal-dashboard-goal-production-1",
                candidate_payload=goal_candidate_payload(),
                expected_site_version="pilot-page-v1",
                execution_mode="PRODUCTION",
                requested_at="2026-07-30T09:00:00+00:00",
                semantic_decision="APPROVE",
                reviewer="sviridov",
                authority=None,
            )

        self.assertFalse((self.runs_root / "dashboard-goal-production-1").exists())

    def test_goal_production_cannot_compose_a_write_executor(self) -> None:
        calls = []

        def controlled_executor(plan):
            calls.append(plan)
            raise AssertionError("Production executor must never be called.")

        with self.assertRaisesRegex(
            DashboardWorkflowRejected,
            "PRODUCTION_WRITE_FORBIDDEN",
        ):
            DashboardWorkflowFacade(
                runs_root=self.runs_root,
                policy_path=POLICY_PATH,
                campaign_safety=campaign_safety(),
                production_goal_executor=controlled_executor,
            )
        with self.assertRaisesRegex(
            DashboardWorkflowRejected,
            "PRODUCTION_WRITE_FORBIDDEN",
        ):
            self.facade.preview_goal(
                run_id="dashboard-goal-production-2",
                proposal_id="proposal-dashboard-goal-production-2",
                candidate_payload=goal_candidate_payload(),
                expected_site_version="pilot-page-v1",
                execution_mode="PRODUCTION",
            )
        self.assertEqual([], calls)


class ImpactWorkflowFacadeTests(WorkflowFacadeTestCase):
    def test_impact_evaluation_exposes_all_four_safe_next_decisions(self) -> None:
        request = json.loads(
            (ROOT / "fixtures" / "impact" / "IMPACT_CPA_IMPROVED_KEEP.json").read_text(
                encoding="utf-8"
            )
        )

        result = self.facade.evaluate_impact(request)

        json.dumps(result)
        self.assertEqual("OBSERVED_POST_CHANGE", result["status"])
        self.assertEqual("KEEP_CHANGE", result["recommended_next_decision"])
        self.assertEqual(
            [
                "KEEP_CHANGE",
                "ROLLBACK_CHANGE",
                "ADJUST_CHANGE",
                "ESCALATE_TO_HUMAN",
            ],
            [item["decision"] for item in result["decision_options"]],
        )
        self.assertEqual(
            {
                "operation": "EVALUATE_POST_CHANGE",
                "before": request["baseline"],
                "after": request["post_change"],
            },
            result["exact_diff"],
        )
        self.assertEqual(
            [
                "OBSERVED_ASSOCIATION_NOT_CAUSAL",
                "DELAYED_CONVERSION_RISK",
            ],
            result["risks"],
        )
        self.assertEqual(
            "NONE",
            result["authority_requirement"]["kind"],
        )
        workflow_path, report_path = map(Path, result["evidence_paths"])
        self.assertEqual(
            self.runs_root / "impact-cpa-improved-keep" / "impact_workflow.json",
            workflow_path,
        )
        self.assertEqual("impact_report.json", report_path.name)
        self.assertEqual(
            result,
            json.loads(workflow_path.read_text(encoding="utf-8")),
        )
        self.assertEqual(
            "KEEP_CHANGE",
            json.loads(report_path.read_text(encoding="utf-8"))["next_decision"],
        )


if __name__ == "__main__":
    unittest.main()
