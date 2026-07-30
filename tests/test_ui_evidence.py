from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import cast

from mox_adv.ui_evidence import (
    build_dashboard_evidence_summary,
    verify_dashboard_evidence_bundle,
    write_dashboard_evidence_bundle,
)


def dashboard_run() -> dict[str, object]:
    return {
        "run_id": "ui-evidence-001",
        "policy_version": "mox-adv-gate0-2026-07-29",
        "mode": "TEST",
        "evidence_type": "SIMULATED",
        "status": "SUCCEEDED",
        "execution_status": "APPLIED",
        "source": "TEST_SCENARIO",
        "snapshot_id": "snapshot-ui-001",
        "period_start": "2026-07-01T00:00:00+00:00",
        "period_end": "2026-07-07T23:59:59+00:00",
        "provenance": {
            "direct": "fixture:direct-budget-increase",
            "metrika": "fixture:metrika-budget-increase",
        },
        "original_metrics": {
            "impressions": 10_000,
            "clicks": 200,
            "cost_rub": "5000.00",
            "goal_visits": 10,
        },
        "metrics": {
            "ctr_percent": "2.00",
            "cpc_rub": "25.00",
            "conversion_rate_percent": "5.00",
            "cpa_rub": "500.00",
        },
        "validation_results": [
            {"code": "READY", "status": "PASSED"},
        ],
        "blocking_code": None,
        "policy_decision": {
            "status": "ALLOWED",
            "reason_code": "WITHIN_GATE0_BOUNDARY",
        },
        "technical_command": {
            "action": "INCREASE_WEEKLY_BUDGET",
            "value_rub": "6050.00",
        },
        "before": {"weekly_budget_rub": "5500.00"},
        "after": {"weekly_budget_rub": "6050.00"},
        "readback": {"weekly_budget_rub": "6050.00"},
        "final_object_state": "ON",
        "provider": "fixture-provider",
        "model_id": "fixture-model-v1",
        "input_tokens": 120,
        "output_tokens": 48,
        "cost_rub": "12.50",
        "cost_limit_rub": "2000.00",
        "tariff_version": "fixture-tariff-2026-07",
        "exchange_rate_version": "RUB-native",
        "duration_ms": 410,
        "stage_durations_ms": {
            "measurement": 100,
            "analysis": 150,
            "policy": 60,
            "execution": 100,
        },
        "capability_evidence": {
            "INTEGRATED_ANALYTICS": {
                "status": "NOT_PROVEN",
                "evidence_type": "SIMULATED",
                "evidence_paths": [
                    "result.json",
                    "events.jsonl",
                ],
                "limitations": [
                    "Fixture evidence does not replace a linked real-data read.",
                ],
            },
            "SAFETY_CORE": {
                "status": "NOT_PROVEN",
                "evidence_type": "SIMULATED",
                "evidence_paths": [
                    "events.jsonl",
                    "signed-audit-anchor.json",
                ],
                "limitations": [
                    "The sealed fake does not prove controlled-pilot safety.",
                ],
            },
        },
        "gates": {
            "GATE_0": {
                "status": "READY",
                "evidence_paths": ["result.json"],
                "limitations": [],
            },
            "GATE_1": {
                "status": "NOT_READY",
                "evidence_paths": [],
                "limitations": ["Product and security sign-off is not attached."],
            },
        },
        "limitations": [
            "This Dashboard run used a sealed fake target.",
        ],
    }


class DashboardEvidenceSummaryTests(unittest.TestCase):
    def test_summary_has_exact_capability_and_gate_contract_without_overclaiming(
        self,
    ) -> None:
        summary = build_dashboard_evidence_summary(dashboard_run())

        self.assertEqual("dashboard-evidence-summary-v1", summary["schema_version"])
        self.assertEqual("SIMULATED", summary["evidence_type"])
        self.assertEqual("NOT_PROVEN", summary["overall_status"])
        self.assertEqual(14, len(summary["capabilities"]))
        self.assertEqual(
            {
                "CAMPAIGN_LIFECYCLE",
                "GOAL_LIFECYCLE",
                "SOURCE_INTEGRATION",
                "INTEGRATED_ANALYTICS",
                "LLM_ANALYSIS",
                "APPROVAL_REQUIRED",
                "BOUNDED_AUTONOMY",
                "MONITORING_AND_ALERTING",
                "IMPACT_EVALUATION",
                "OPERATIONAL_MODES",
                "TOOL_CONTRACT",
                "ORIGINAL_INTEGRATION_COVERAGE",
                "SAFETY_CORE",
                "CLOSED_LOOP_CONTROL",
            },
            {item["capability"] for item in summary["capabilities"]},
        )
        self.assertEqual(
            ["GATE_0", "GATE_1", "GATE_2", "GATE_3", "GATE_4"],
            [item["gate"] for item in summary["gates"]],
        )
        self.assertEqual(
            "NOT_TESTED",
            next(
                item["status"]
                for item in summary["capabilities"]
                if item["capability"] == "CLOSED_LOOP_CONTROL"
            ),
        )
        self.assertEqual("READY", summary["gates"][0]["status"])
        self.assertEqual("NOT_READY", summary["gates"][1]["status"])

    def test_cost_policy_reports_ok_warning_and_block_boundaries(self) -> None:
        expected = (
            ("1599.99", "OK", True),
            ("1600.00", "WARNING", True),
            ("2000.00", "BLOCKED", False),
        )

        for cost, state, allowed in expected:
            with self.subTest(cost=cost):
                value = dashboard_run()
                value["cost_rub"] = cost
                summary = build_dashboard_evidence_summary(value)
                self.assertEqual(state, summary["cost_policy"]["state"])
                self.assertEqual(
                    allowed,
                    summary["cost_policy"]["new_model_calls_allowed"],
                )

    def test_missing_evidence_type_defaults_to_simulation_not_pilot(self) -> None:
        value = dashboard_run()
        del value["evidence_type"]

        summary = build_dashboard_evidence_summary(value)

        self.assertEqual("SIMULATED", summary["evidence_type"])
        self.assertNotEqual("PROVEN", summary["overall_status"])
        self.assertEqual(
            {"SIMULATED"},
            {item["evidence_type"] for item in summary["capabilities"]},
        )

    def test_simulation_cannot_claim_a_proven_capability_or_gate_four(self) -> None:
        proven_capability = dashboard_run()
        proven_capability["capability_evidence"] = {
            "INTEGRATED_ANALYTICS": {
                "status": "PROVEN",
                "evidence_type": "SIMULATED",
                "evidence_paths": ["result.json"],
                "limitations": [],
            }
        }
        with self.assertRaisesRegex(ValueError, "SIMULATED.*PROVEN"):
            build_dashboard_evidence_summary(proven_capability)

        gate_four = dashboard_run()
        gate_four["gates"] = {
            "GATE_0": {"status": "READY", "evidence_paths": ["gate0.json"]},
            "GATE_1": {"status": "READY", "evidence_paths": ["gate1.json"]},
            "GATE_2": {"status": "READY", "evidence_paths": ["gate2.json"]},
            "GATE_3": {"status": "READY", "evidence_paths": ["gate3.json"]},
            "GATE_4": {"status": "READY", "evidence_paths": ["gate4.json"]},
        }
        with self.assertRaisesRegex(ValueError, "GATE_4.*CONTROLLED_PILOT"):
            build_dashboard_evidence_summary(gate_four)

    def test_closed_loop_proven_requires_one_campaign_target_binding(self) -> None:
        value = dashboard_run()
        value["evidence_type"] = "CONTROLLED_PILOT"
        value["capability_evidence"] = {
            "CLOSED_LOOP_CONTROL": {
                "status": "PROVEN",
                "evidence_type": "CONTROLLED_PILOT",
                "evidence_paths": ["result.json"],
                "limitations": [],
            }
        }

        with self.assertRaisesRegex(ValueError, "target binding"):
            build_dashboard_evidence_summary(value)

        value["target_binding"] = {
            "analytics_campaign_id": "campaign-001",
            "proposal_campaign_id": "campaign-001",
            "execution_campaign_id": "campaign-001",
            "impact_campaign_id": "campaign-001",
        }
        summary = build_dashboard_evidence_summary(value)
        closed_loop = next(
            item
            for item in summary["capabilities"]
            if item["capability"] == "CLOSED_LOOP_CONTROL"
        )
        self.assertEqual("PROVEN", closed_loop["status"])


class DashboardEvidenceBundleTests(unittest.TestCase):
    def test_bundle_writes_normative_files_russian_report_and_verifiable_chain(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_directory = Path(temporary) / "ui-evidence-001"

            summary = write_dashboard_evidence_bundle(
                run_directory,
                dashboard_run(),
            )

            self.assertEqual(
                {
                    ".dashboard-audit.sqlite3",
                    "artifact-manifest.json",
                    "events.jsonl",
                    "report.md",
                    "result.json",
                    "signed-audit-anchor.json",
                },
                {path.name for path in run_directory.iterdir()},
            )
            result = json.loads(
                (run_directory / "result.json").read_text(encoding="utf-8")
            )
            self.assertEqual("dashboard-result-v1", result["schema_version"])
            self.assertEqual("fixture-provider", result["provider"])
            self.assertEqual("fixture-model-v1", result["model_id"])
            self.assertEqual(120, result["input_tokens"])
            self.assertEqual(48, result["output_tokens"])
            self.assertEqual("12.50", result["cost_rub"])
            self.assertEqual(410, result["duration_ms"])
            self.assertEqual(
                {
                    "measurement": 100,
                    "analysis": 150,
                    "policy": 60,
                    "execution": 100,
                },
                result["stage_durations_ms"],
            )
            self.assertEqual(summary, result["evidence_summary"])
            report = (run_directory / "report.md").read_text(encoding="utf-8")
            self.assertIn("# Отчёт Dashboard MOX-ADV", report)
            self.assertIn("## Способности", report)
            self.assertIn("## Готовность Gate 0–4", report)
            self.assertIn("Общий статус: `NOT_PROVEN`.", report)
            events = [
                json.loads(line)
                for line in (run_directory / "events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertGreaterEqual(len(events), 5)
            self.assertEqual(
                list(range(1, len(events) + 1)), [event["sequence"] for event in events]
            )
            self.assertEqual("0" * 64, events[0]["previous_hash"])
            self.assertEqual(
                events[-2]["event_hash"],
                events[-1]["previous_hash"],
            )
            verified = verify_dashboard_evidence_bundle(run_directory)
            self.assertEqual(result, verified)

    def test_optional_artifact_references_are_recorded_but_not_fabricated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_directory = Path(temporary) / "ui-evidence-001"
            run_directory.mkdir()
            (run_directory / "proposal.json").write_text(
                '{"proposal_id":"proposal-001"}\n',
                encoding="utf-8",
            )
            value = dashboard_run()
            value["artifact_references"] = {
                "proposal": "proposal.json",
            }

            write_dashboard_evidence_bundle(run_directory, value)

            result = json.loads(
                (run_directory / "result.json").read_text(encoding="utf-8")
            )
            self.assertEqual("proposal.json", result["proposal_path"])
            self.assertNotIn("approval_path", result)
            self.assertNotIn("impact_report_path", result)
            event_types = {
                json.loads(line)["event_type"]
                for line in (run_directory / "events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            }
            self.assertIn("dashboard.artifacts.linked", event_types)
            verify_dashboard_evidence_bundle(run_directory)

    def test_tampered_events_or_result_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_directory = Path(temporary) / "ui-evidence-001"
            write_dashboard_evidence_bundle(run_directory, dashboard_run())
            events_path = run_directory / "events.jsonl"
            original_events = events_path.read_text(encoding="utf-8")
            events_path.write_text(
                original_events.replace("SUCCEEDED", "FAILED", 1),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "manifest|hash chain"):
                verify_dashboard_evidence_bundle(run_directory)

        with tempfile.TemporaryDirectory() as temporary:
            run_directory = Path(temporary) / "ui-evidence-001"
            write_dashboard_evidence_bundle(run_directory, dashboard_run())
            result_path = run_directory / "result.json"
            result_path.write_text(
                result_path.read_text(encoding="utf-8").replace(
                    '"cost_rub": "12.50"',
                    '"cost_rub": "0.00"',
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "manifest"):
                verify_dashboard_evidence_bundle(run_directory)

    def test_secret_shaped_input_fails_before_any_evidence_is_written(self) -> None:
        value = copy.deepcopy(dashboard_run())
        provenance = cast(dict[str, object], value["provenance"])
        provenance["oauth_token"] = "secret-canary-value"
        with tempfile.TemporaryDirectory() as temporary:
            run_directory = Path(temporary) / "ui-evidence-001"

            with self.assertRaisesRegex(ValueError, "sensitive"):
                write_dashboard_evidence_bundle(run_directory, value)

            self.assertFalse((run_directory / "result.json").exists())
            self.assertFalse((run_directory / "events.jsonl").exists())

    def test_controlled_pilot_bundle_requires_non_simulation_signer(self) -> None:
        value = dashboard_run()
        value["evidence_type"] = "CONTROLLED_PILOT"
        with tempfile.TemporaryDirectory() as temporary:
            run_directory = Path(temporary) / "ui-evidence-001"

            with self.assertRaisesRegex(ValueError, "non-simulation audit signer"):
                write_dashboard_evidence_bundle(run_directory, value)

            self.assertFalse(run_directory.exists())

    def test_sensitive_optional_artifact_is_rejected_before_bundle_finalization(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_directory = Path(temporary) / "ui-evidence-001"
            run_directory.mkdir()
            (run_directory / "proposal.json").write_text(
                '{"proposal_id":"proposal-001","oauth_token":"secret-canary"}\n',
                encoding="utf-8",
            )
            value = dashboard_run()
            value["artifact_references"] = {"proposal": "proposal.json"}

            with self.assertRaisesRegex(ValueError, "sensitive"):
                write_dashboard_evidence_bundle(run_directory, value)

            self.assertFalse((run_directory / "result.json").exists())
            self.assertFalse((run_directory / "events.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
