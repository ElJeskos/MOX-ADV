from __future__ import annotations

import copy
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from mox_adv.analytics import IntegratedAnalyticsEngineV1
from mox_adv.connectors import (
    DirectCampaignStateReadConnectorV1,
    DirectReportsReadConnectorV1,
    FixtureAnalyticsConnectorV1,
    FixtureAnalyticsReadConnectorsV1,
    MetrikaReportReadConnectorV1,
)
from mox_adv.contracts import (
    AnalyticsPeriod,
    AnalyticsScope,
    ConnectedAnalytics,
    DirectCampaignStateReadQuery,
    DirectReportsReadQuery,
    MetrikaReportReadQuery,
    VersionedReadRequest,
)
from mox_adv.errors import RunRejectedError
from mox_adv.normalization import IntegratedSnapshotNormalizerV1
from mox_adv.observe import (
    load_linked_fixture,
    load_observe_policy,
    run_observe_fixture,
    trusted_fixture_scope,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
POLICY = ROOT / "config" / "gate0-policy.json"
FIXTURE = ROOT / "fixtures" / "linked-observe.json"


def linked_input() -> tuple[dict[str, object], dict[str, object]]:
    policy = load_observe_policy(POLICY)
    fixture = load_linked_fixture(FIXTURE)
    return policy, fixture


def build_snapshot(
    fixture: dict[str, object],
    policy: dict[str, object],
):
    connector = FixtureAnalyticsConnectorV1()
    connected = connector.read_linked(fixture)
    trusted_scope = trusted_fixture_scope(policy, connected.observation_id)
    fixture_reads = FixtureAnalyticsReadConnectorsV1(connected)
    return normalize_typed_reads(
        policy=policy,
        observation_id=connected.observation_id,
        generated_at=connected.generated_at,
        period_start=connected.direct_report.period_start,
        period_end=connected.direct_report.period_end,
        trusted_scope=trusted_scope,
        direct_reports=fixture_reads,
        direct_state=fixture_reads,
        metrika_report=fixture_reads,
        baseline=connected.baseline,
    )


def normalize_typed_reads(
    *,
    policy,
    observation_id,
    generated_at,
    period_start,
    period_end,
    trusted_scope,
    direct_reports,
    direct_state,
    metrika_report,
    baseline,
):
    """Exercise the normalizer seam without creating a runtime fallback."""

    direct_block = direct_reports.read_report(
        DirectReportsReadQuery(
            account=trusted_scope.account,
            campaign=trusted_scope.campaign,
            period_start=period_start,
            period_end=period_end,
            attribution=str(policy["attribution"]["direct"]),
        )
    )
    state_block = direct_state.read_campaign_state(
        DirectCampaignStateReadQuery(
            account=trusted_scope.account,
            campaign=trusted_scope.campaign,
        )
    )
    metrika_block = metrika_report.read_metrika_report(
        MetrikaReportReadQuery(
            counter=trusted_scope.counter,
            campaign=trusted_scope.campaign,
            goal=trusted_scope.goal,
            period_start=period_start,
            period_end=period_end,
            attribution=str(policy["attribution"]["metrika"]),
        )
    )
    connected = ConnectedAnalytics(
        observation_id=observation_id,
        generated_at=generated_at,
        scope=AnalyticsScope(
            organization=trusted_scope.organization,
            connection=trusted_scope.connection,
            account=trusted_scope.account,
            campaign=trusted_scope.campaign,
            counter=trusted_scope.counter,
            goal=trusted_scope.goal,
        ),
        requested_period=AnalyticsPeriod(
            period_start=period_start,
            period_end=period_end,
        ),
        direct_report=direct_block,
        direct_state=state_block,
        metrika_report=metrika_block,
        baseline=baseline,
    )
    draft = IntegratedSnapshotNormalizerV1().normalize(
        connected,
        policy,
        trusted_scope,
    )
    return IntegratedAnalyticsEngineV1().calculate(draft)


class IntegratedAnalyticsTests(unittest.TestCase):
    def test_linked_fixture_is_deterministic_and_calculates_required_metrics(
        self,
    ) -> None:
        policy, fixture = linked_input()

        first = build_snapshot(fixture, policy)
        second = build_snapshot(fixture, policy)

        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual("COMPARABLE", first.comparability_status)
        self.assertEqual("READY", first.confidence_status)
        self.assertTrue(first.financial_recommendations_allowed)
        self.assertEqual("2.00", first.display_metrics["ctr_percent"])
        self.assertEqual("25.00", first.display_metrics["cpc_rub"])
        self.assertEqual("3.33", first.display_metrics["conversion_rate_percent"])
        self.assertEqual("1000.00", first.display_metrics["cpa_rub"])
        self.assertEqual("NOT_APPLICABLE", first.metrics["cpl_rub"])
        self.assertEqual("50.00", first.display_metrics["budget_utilization_percent"])
        self.assertEqual("50.00", first.display_metrics["pacing_percent"])

    def test_zero_denominators_are_not_applicable(self) -> None:
        policy, fixture = linked_input()
        direct_rows = fixture["direct_report"]["rows"]
        metrika_rows = fixture["metrika_report"]["rows"]
        for row in direct_rows:
            row["impressions"] = 0
            row["clicks"] = 0
            row["cost_micros"] = 0
        for row in metrika_rows:
            row["visits"] = 0
            row["goal_visits"] = 0

        snapshot = build_snapshot(fixture, policy)

        for name in ("ctr_percent", "cpc_rub", "conversion_rate_percent", "cpa_rub"):
            self.assertEqual("NOT_APPLICABLE", snapshot.metrics[name])

    def test_unknown_trusted_identifier_is_rejected(self) -> None:
        for field_name in ("account", "campaign", "counter", "goal"):
            with self.subTest(field_name=field_name):
                policy, fixture = linked_input()
                fixture["scope"][field_name] = "unknown-" + field_name

                with self.assertRaisesRegex(RunRejectedError, "trusted scope"):
                    build_snapshot(fixture, policy)

    def test_internally_consistent_rogue_campaign_is_rejected(self) -> None:
        policy, fixture = linked_input()
        fixture["scope"]["campaign"] = "rogue-campaign"
        fixture["direct_state"]["campaign"] = "rogue-campaign"
        for row in fixture["direct_report"]["rows"]:
            row["campaign"] = "rogue-campaign"
        for row in fixture["metrika_report"]["rows"]:
            row["campaign"] = "rogue-campaign"

        with self.assertRaisesRegex(RunRejectedError, "trusted scope"):
            build_snapshot(fixture, policy)

    def test_internally_consistent_rogue_goal_is_rejected(self) -> None:
        policy, fixture = linked_input()
        fixture["scope"]["goal"] = "rogue-goal"
        for row in fixture["metrika_report"]["rows"]:
            row["goal"] = "rogue-goal"

        with self.assertRaisesRegex(RunRejectedError, "trusted scope"):
            build_snapshot(fixture, policy)

    def test_source_identifier_mismatch_is_incompatible(self) -> None:
        for source_name in ("direct_campaign", "metrika_goal"):
            with self.subTest(source_name=source_name):
                policy, fixture = linked_input()
                if source_name == "direct_campaign":
                    fixture["direct_report"]["rows"][0]["campaign"] = "rogue-campaign"
                else:
                    fixture["metrika_report"]["rows"][0]["goal"] = "rogue-goal"

                snapshot = build_snapshot(fixture, policy)

                self.assertEqual(
                    "INCOMPATIBLE",
                    snapshot.comparability_status,
                )
                self.assertIn(
                    "IDENTIFIER_MISMATCH",
                    snapshot.data_quality_gaps,
                )
                self.assertFalse(snapshot.financial_recommendations_allowed)

    def test_stale_data_fails_closed_as_incompatible(self) -> None:
        policy, fixture = linked_input()
        generated_at = datetime.fromisoformat(fixture["generated_at"])
        stale_at = (generated_at - timedelta(minutes=31)).isoformat()
        fixture["direct_report"]["retrieved_at"] = stale_at
        fixture["direct_report"]["watermark"] = stale_at

        snapshot = build_snapshot(fixture, policy)

        self.assertEqual("INCOMPATIBLE", snapshot.comparability_status)
        self.assertEqual("STALE_DATA", snapshot.confidence_status)
        self.assertFalse(snapshot.financial_recommendations_allowed)
        self.assertIn("DIRECT_DATA_STALE", snapshot.data_quality_gaps)

    def test_mismatched_attribution_is_incompatible(self) -> None:
        policy, fixture = linked_input()
        fixture["metrika_report"]["attribution"] = "last"

        snapshot = build_snapshot(fixture, policy)

        self.assertEqual("INCOMPATIBLE", snapshot.comparability_status)
        self.assertFalse(snapshot.financial_recommendations_allowed)
        self.assertIn("ATTRIBUTION_MISMATCH", snapshot.data_quality_gaps)

    def test_mismatched_period_is_incompatible_not_rejected(self) -> None:
        policy, fixture = linked_input()
        fixture["metrika_report"]["period_start"] = "2026-07-20"
        fixture["metrika_report"]["period_end"] = "2026-07-26"
        for row in fixture["metrika_report"]["rows"]:
            row["date"] = (
                (datetime.fromisoformat(row["date"]) - timedelta(days=1))
                .date()
                .isoformat()
            )

        snapshot = build_snapshot(fixture, policy)

        self.assertEqual("INCOMPATIBLE", snapshot.comparability_status)
        self.assertIn("PERIOD_MISMATCH", snapshot.data_quality_gaps)
        self.assertFalse(snapshot.financial_recommendations_allowed)

    def test_excessive_watermark_skew_is_incompatible(self) -> None:
        policy, fixture = linked_input()
        watermark = datetime.fromisoformat(fixture["direct_report"]["watermark"])
        fixture["metrika_report"]["watermark"] = (
            watermark - timedelta(hours=6, seconds=1)
        ).isoformat()

        snapshot = build_snapshot(fixture, policy)

        self.assertEqual("INCOMPATIBLE", snapshot.comparability_status)
        self.assertFalse(snapshot.financial_recommendations_allowed)
        self.assertIn("WATERMARK_SKEW_EXCEEDED", snapshot.data_quality_gaps)

    def test_read_only_baseline_identifier_is_not_exposed(self) -> None:
        policy, fixture = linked_input()

        serialized = json.dumps(build_snapshot(fixture, policy).as_dict())

        self.assertNotIn("sim-readonly-baseline", serialized)
        self.assertIn("baseline_deviation", serialized)

    def test_snapshot_fingerprint_detects_normative_field_change(self) -> None:
        policy, fixture = linked_input()
        snapshot = build_snapshot(fixture, policy)

        changed = copy.deepcopy(snapshot.as_dict())
        changed["metrics"]["clicks"] += 1

        self.assertFalse(IntegratedSnapshotNormalizerV1.verify_fingerprint(changed))

    def test_late_conversion_creates_a_new_snapshot_version(self) -> None:
        policy, fixture = linked_input()
        original = build_snapshot(fixture, policy)
        fixture["metrika_report"]["rows"][-1]["goal_visits"] = 1

        revised = build_snapshot(fixture, policy)

        self.assertNotEqual(original.snapshot_id, revised.snapshot_id)
        self.assertEqual(5, original.metrics["goal_visits"])
        self.assertEqual(6, revised.metrics["goal_visits"])
        self.assertNotIn(
            "LATE_CONVERSION_CUTOFF_EXCEEDED",
            revised.data_quality_gaps,
        )

    def test_conversion_data_after_gate0_cutoff_is_incompatible(self) -> None:
        policy, fixture = linked_input()
        after_cutoff = "2026-07-31T01:00:00+00:00"
        fixture["generated_at"] = after_cutoff
        fixture["direct_report"]["source"] = "DIRECT_REPORTS"
        fixture["direct_state"]["source"] = "DIRECT_CAMPAIGN_STATE"
        fixture["metrika_report"]["source"] = "METRIKA_REPORT"
        for block_name in ("direct_report", "direct_state", "metrika_report"):
            fixture[block_name]["retrieved_at"] = after_cutoff
            fixture[block_name]["watermark"] = after_cutoff

        snapshot = build_snapshot(fixture, policy)

        self.assertEqual("INCOMPATIBLE", snapshot.comparability_status)
        self.assertIn(
            "LATE_CONVERSION_CUTOFF_EXCEEDED",
            snapshot.data_quality_gaps,
        )
        self.assertFalse(snapshot.financial_recommendations_allowed)

    def test_pacing_uses_expected_spend_at_current_period_point(self) -> None:
        policy, fixture = linked_input()
        fixture["generated_at"] = "2026-07-24T12:00:00+00:00"
        fixture["direct_report"]["source"] = "DIRECT_REPORTS"
        fixture["direct_state"]["source"] = "DIRECT_CAMPAIGN_STATE"
        fixture["metrika_report"]["source"] = "METRIKA_REPORT"
        fixture["direct_report"]["period_end"] = "2026-07-23"
        fixture["metrika_report"]["period_end"] = "2026-07-23"
        fixture["direct_report"]["rows"] = fixture["direct_report"]["rows"][:3]
        fixture["metrika_report"]["rows"] = fixture["metrika_report"]["rows"][:3]
        for block_name in ("direct_report", "direct_state", "metrika_report"):
            fixture[block_name]["retrieved_at"] = "2026-07-24T12:00:00+00:00"
            fixture[block_name]["watermark"] = "2026-07-24T11:59:00+00:00"

        snapshot = build_snapshot(fixture, policy)

        self.assertEqual("COMPARABLE", snapshot.comparability_status)
        self.assertEqual(
            "20.00",
            snapshot.display_metrics["budget_utilization_percent"],
        )
        self.assertEqual("40.00", snapshot.display_metrics["pacing_percent"])

    def test_pacing_budget_period_start_boundary_is_not_applicable(self) -> None:
        policy, fixture = linked_input()
        boundary = "2026-07-28T00:00:00+00:00"
        fixture["generated_at"] = boundary
        fixture["direct_state"]["budget_period_start"] = boundary
        fixture["direct_state"]["budget_period_end"] = "2026-08-04T00:00:00+00:00"
        for block_name in ("direct_report", "direct_state", "metrika_report"):
            fixture[block_name]["retrieved_at"] = boundary
            fixture[block_name]["watermark"] = boundary

        snapshot = build_snapshot(fixture, policy)

        self.assertEqual("COMPARABLE", snapshot.comparability_status)
        self.assertEqual(
            "NOT_APPLICABLE",
            snapshot.display_metrics["pacing_percent"],
        )

    def test_pacing_budget_period_end_boundary_uses_full_budget(self) -> None:
        policy, fixture = linked_input()
        boundary = "2026-07-28T00:00:00+00:00"
        fixture["generated_at"] = boundary
        for block_name in ("direct_report", "direct_state", "metrika_report"):
            fixture[block_name]["retrieved_at"] = boundary
            fixture[block_name]["watermark"] = boundary

        snapshot = build_snapshot(fixture, policy)

        self.assertEqual("COMPARABLE", snapshot.comparability_status)
        self.assertEqual(
            snapshot.display_metrics["budget_utilization_percent"],
            snapshot.display_metrics["pacing_percent"],
        )


class RecordingReadTransport:
    def __init__(self, fixture: dict[str, object]) -> None:
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
        self.requests: list[VersionedReadRequest] = []

    def read(self, request: VersionedReadRequest):
        self.requests.append(request)
        if request.system == "DIRECT_REPORTS":
            return self.direct_report
        if request.system == "DIRECT":
            return self.direct_state
        return self.metrika_report


class ReadConnectorContractTests(unittest.TestCase):
    def test_connectors_expose_only_normative_read_requests(self) -> None:
        _, fixture = linked_input()
        transport = RecordingReadTransport(fixture)
        connectors = (
            DirectReportsReadConnectorV1(transport),
            DirectCampaignStateReadConnectorV1(transport),
            MetrikaReportReadConnectorV1(transport),
        )

        self.assertEqual(
            "DIRECT_REPORTS",
            connectors[0]
            .read_report(
                DirectReportsReadQuery(
                    account="allowed",
                    campaign="allowed",
                    period_start="2026-07-21",
                    period_end="2026-07-27",
                    attribution="AUTO",
                )
            )
            .source,
        )
        self.assertEqual(
            "sim-campaign",
            connectors[1]
            .read_campaign_state(
                DirectCampaignStateReadQuery(
                    account="allowed",
                    campaign="allowed",
                )
            )
            .campaign,
        )
        self.assertEqual(
            "automatic",
            connectors[2]
            .read_metrika_report(
                MetrikaReportReadQuery(
                    counter="allowed",
                    campaign="allowed",
                    goal="allowed",
                    period_start="2026-07-21",
                    period_end="2026-07-27",
                    attribution="automatic",
                )
            )
            .attribution,
        )

        self.assertEqual(
            [
                (
                    "DIRECT_REPORTS",
                    "/json/v5/reports",
                    "v5",
                    "Reports",
                    "get",
                ),
                (
                    "DIRECT",
                    "/json/v501/campaigns",
                    "v501",
                    "Campaigns",
                    "get",
                ),
                (
                    "METRIKA",
                    "/stat/v1/data",
                    "v1",
                    "Statistics",
                    "get",
                ),
            ],
            [
                (
                    request.system,
                    request.path,
                    request.version,
                    request.service,
                    request.method,
                )
                for request in transport.requests
            ],
        )
        for connector in connectors:
            self.assertFalse(hasattr(connector, "write"))
            self.assertFalse(hasattr(connector, "add"))
            self.assertFalse(hasattr(connector, "update"))

    def test_typed_read_connectors_build_a_non_fixture_snapshot(self) -> None:
        policy, fixture = linked_input()
        transport = RecordingReadTransport(fixture)
        trusted_scope = trusted_fixture_scope(policy, "linked-observe")

        snapshot = normalize_typed_reads(
            policy=policy,
            observation_id="stubbed-production-read",
            generated_at=fixture["generated_at"],
            period_start=fixture["direct_report"]["period_start"],
            period_end=fixture["direct_report"]["period_end"],
            trusted_scope=trusted_scope,
            direct_reports=DirectReportsReadConnectorV1(transport),
            direct_state=DirectCampaignStateReadConnectorV1(transport),
            metrika_report=MetrikaReportReadConnectorV1(transport),
            baseline=transport.baseline,
        )

        self.assertEqual("COMPARABLE", snapshot.comparability_status)
        self.assertEqual(3, len(transport.requests))
        self.assertEqual(
            "DIRECT_REPORTS",
            snapshot.provenance.direct_report.source,
        )
        self.assertEqual(
            "DIRECT_CAMPAIGN_STATE",
            snapshot.provenance.direct_state.source,
        )
        self.assertEqual(
            "METRIKA_REPORT",
            snapshot.provenance.metrika_report.source,
        )
        self.assertEqual(
            "sim-campaign",
            transport.requests[0].payload["campaign"],
        )
        self.assertEqual(
            "sim-campaign",
            transport.requests[1].payload["campaign"],
        )
        self.assertEqual(
            "sim-primary-goal",
            transport.requests[2].payload["goal"],
        )

    def test_read_response_for_wrong_requested_period_is_incompatible(
        self,
    ) -> None:
        policy, fixture = linked_input()
        transport = RecordingReadTransport(fixture)
        trusted_scope = trusted_fixture_scope(policy, "linked-observe")

        snapshot = normalize_typed_reads(
            policy=policy,
            observation_id="wrong-period-response",
            generated_at=fixture["generated_at"],
            period_start="2025-01-01",
            period_end="2025-01-07",
            trusted_scope=trusted_scope,
            direct_reports=DirectReportsReadConnectorV1(transport),
            direct_state=DirectCampaignStateReadConnectorV1(transport),
            metrika_report=MetrikaReportReadConnectorV1(transport),
            baseline=transport.baseline,
        )

        self.assertEqual("INCOMPATIBLE", snapshot.comparability_status)
        self.assertIn("PERIOD_MISMATCH", snapshot.data_quality_gaps)
        self.assertFalse(snapshot.financial_recommendations_allowed)

    def test_read_response_for_wrong_attribution_is_incompatible(self) -> None:
        policy, fixture = linked_input()
        transport = RecordingReadTransport(fixture)
        transport.metrika_report = replace(
            transport.metrika_report,
            attribution="last",
        )
        trusted_scope = trusted_fixture_scope(policy, "linked-observe")

        snapshot = normalize_typed_reads(
            policy=policy,
            observation_id="wrong-attribution-response",
            generated_at=fixture["generated_at"],
            period_start=fixture["direct_report"]["period_start"],
            period_end=fixture["direct_report"]["period_end"],
            trusted_scope=trusted_scope,
            direct_reports=DirectReportsReadConnectorV1(transport),
            direct_state=DirectCampaignStateReadConnectorV1(transport),
            metrika_report=MetrikaReportReadConnectorV1(transport),
            baseline=transport.baseline,
        )

        self.assertEqual("INCOMPATIBLE", snapshot.comparability_status)
        self.assertIn("ATTRIBUTION_MISMATCH", snapshot.data_quality_gaps)
        self.assertFalse(snapshot.financial_recommendations_allowed)

    def test_read_response_for_non_utc_timezone_is_incompatible(self) -> None:
        policy, fixture = linked_input()
        transport = RecordingReadTransport(fixture)
        transport.direct_report = replace(
            transport.direct_report,
            timezone="Europe/Moscow",
        )
        trusted_scope = trusted_fixture_scope(policy, "linked-observe")

        snapshot = normalize_typed_reads(
            policy=policy,
            observation_id="wrong-timezone-response",
            generated_at=fixture["generated_at"],
            period_start=fixture["direct_report"]["period_start"],
            period_end=fixture["direct_report"]["period_end"],
            trusted_scope=trusted_scope,
            direct_reports=DirectReportsReadConnectorV1(transport),
            direct_state=DirectCampaignStateReadConnectorV1(transport),
            metrika_report=MetrikaReportReadConnectorV1(transport),
            baseline=transport.baseline,
        )

        self.assertEqual("INCOMPATIBLE", snapshot.comparability_status)
        self.assertIn("TIMEZONE_MISMATCH", snapshot.data_quality_gaps)
        self.assertFalse(snapshot.financial_recommendations_allowed)


class ObserveRunTests(unittest.TestCase):
    def test_observe_cli_writes_mandatory_artifacts_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            runs_root = Path(temporary_directory) / "runs"
            with (
                mock.patch.object(
                    socket,
                    "create_connection",
                    side_effect=AssertionError("network access is forbidden"),
                ),
                mock.patch.object(
                    socket,
                    "socket",
                    side_effect=AssertionError("network access is forbidden"),
                ),
            ):
                outcome = run_observe_fixture(
                    run_id="observe-success",
                    runs_root=runs_root,
                    fixture_path=FIXTURE,
                    policy_path=POLICY,
                )

            self.assertEqual(0, outcome.exit_code)
            run_directory = runs_root / "observe-success"
            self.assertEqual(
                {
                    "capability-evidence.json",
                    "events.jsonl",
                    "report.md",
                    "result.json",
                },
                {
                    path.name
                    for path in run_directory.iterdir()
                    if not path.name.startswith(".")
                },
            )
            result = json.loads(
                (run_directory / "result.json").read_text(encoding="utf-8")
            )
            self.assertEqual("OBSERVE", result["mode"])
            self.assertEqual("NOT_STARTED", result["execution_status"])
            self.assertFalse(result["external_write_sent"])
            self.assertEqual(
                "capability-evidence.json",
                result["capability_evidence_path"],
            )
            capability_evidence = json.loads(
                (run_directory / "capability-evidence.json").read_text(encoding="utf-8")
            )
            observe_capability = next(
                item
                for item in capability_evidence["capabilities"]
                if item["capability"] == "INTEGRATED_ANALYTICS"
            )
            self.assertEqual("NOT_PROVEN", observe_capability["status"])
            self.assertEqual(
                ["08", "09", "27"],
                observe_capability["acceptance_cases"],
            )
            self.assertEqual(
                "COMPARABLE",
                result["snapshot"]["comparability_status"],
            )
            report = (run_directory / "report.md").read_text(encoding="utf-8")
            self.assertIn("Наблюдение", report)
            self.assertIn("CTR: `2.00%`", report)
            self.assertIn("изменяющие запросы не отправлялись", report)
            self.assertIn(
                "INTEGRATED_ANALYTICS: status=NOT_PROVEN",
                report,
            )

    def test_cli_command_has_no_traceback_and_never_executes_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(SRC)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "mox_adv",
                    "observe-fixture",
                    "--run-id",
                    "observe-cli",
                    "--runs-dir",
                    temporary_directory,
                    "--fixture",
                    str(FIXTURE),
                    "--policy",
                    str(POLICY),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertNotIn("Traceback", completed.stdout + completed.stderr)
        self.assertIn("SUCCEEDED", completed.stdout)

    def test_rejected_scope_still_writes_safe_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            _, fixture = linked_input()
            fixture["scope"]["account"] = "unknown-account"
            fixture_path = temporary_root / "rejected.json"
            fixture_path.write_text(
                json.dumps(fixture),
                encoding="utf-8",
            )

            outcome = run_observe_fixture(
                run_id="observe-rejected",
                runs_root=temporary_root / "runs",
                fixture_path=fixture_path,
                policy_path=POLICY,
            )

            self.assertEqual(2, outcome.exit_code)
            run_directory = Path(outcome.run_directory)
            artifacts = (
                run_directory / "result.json",
                run_directory / "report.md",
                run_directory / "events.jsonl",
            )
            self.assertTrue(all(path.is_file() for path in artifacts))
            result = json.loads(artifacts[0].read_text(encoding="utf-8"))
            self.assertEqual("REJECTED", result["status"])
            self.assertEqual("NOT_STARTED", result["execution_status"])
            self.assertFalse(result["external_write_sent"])


if __name__ == "__main__":
    unittest.main()
