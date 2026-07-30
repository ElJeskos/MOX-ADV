from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from mox_adv.contracts import (
    DirectCampaignStateBlock,
    DirectCampaignStateReadQuery,
    DirectReportBlock,
    DirectReportRow,
    DirectReportsReadQuery,
)
from mox_adv.environment import ExecutionEnvironment
from mox_adv.module_api.v1 import (
    HttpJsonModuleAdapterV1,
    InMemoryDecisionRecordStoreV1,
)
from mox_adv.modules.direct import (
    BoundDirectReadProviderV1,
    DirectModuleV1,
)

ROOT = Path(__file__).resolve().parents[2]


def customer_evidence_request() -> dict[str, Any]:
    return {
        "schema_version": "module-request-v1",
        "connection_ref": {"connection_id": "customer-direct-primary"},
        "environment": "PRODUCTION",
        "scope": {
            "organization_id": "customer-42",
            "account_id": "account-8",
            "campaign_id": "campaign-7",
        },
        "period": {
            "start_date": "2026-07-23",
            "end_date": "2026-07-29",
            "timezone": "UTC",
        },
        "objective": {
            "code": "REDUCE_CPA",
            "description": "Reduce CPA without losing qualified conversions.",
        },
        "external_evidence": {
            "schema_version": "normalized-metrics-evidence-v1",
            "evidence_id": "customer-direct-evidence-17",
            "source": "CUSTOMER_ECOSYSTEM",
            "observed_at": "2026-07-30T11:55:00+00:00",
            "watermark": "2026-07-30T11:50:00+00:00",
            "metrics": [
                {"name": "impressions", "value": 10000, "unit": "COUNT"},
                {"name": "clicks", "value": 200, "unit": "COUNT"},
                {
                    "name": "cost_micros",
                    "value": 5000000000,
                    "unit": "MICROS_RUB",
                },
                {"name": "campaign_state", "value": "ON", "unit": "CODE"},
                {"name": "group_state", "value": "ON", "unit": "CODE"},
                {"name": "ad_state", "value": "ON", "unit": "CODE"},
                {
                    "name": "strategy",
                    "value": "HIGHEST_POSITION",
                    "unit": "CODE",
                },
                {
                    "name": "current_weekly_budget_micros",
                    "value": 10000000000,
                    "unit": "MICROS_RUB",
                },
                {
                    "name": "current_search_bid_micros",
                    "value": 100000000,
                    "unit": "MICROS_RUB",
                },
                {"name": "ad_variant", "value": "A", "unit": "CODE"},
                {
                    "name": "object_config_version",
                    "value": "campaign-config-v1",
                    "unit": "CODE",
                },
                {
                    "name": "budget_period_start",
                    "value": "2026-07-23T12:00:00+00:00",
                    "unit": "ISO_8601",
                },
                {
                    "name": "budget_period_end",
                    "value": "2026-07-30T12:00:00+00:00",
                    "unit": "ISO_8601",
                },
            ],
        },
        "operation": {
            "kind": "ANALYZE",
            "operation_type": "ANALYZE_PERFORMANCE",
        },
        "idempotency_key": "customer-direct-run-2026-07-30-001",
    }


class RecordingAuthorizedDirectReader:
    def __init__(self) -> None:
        self.report_calls: list[tuple[str, DirectReportsReadQuery]] = []
        self.state_calls: list[tuple[str, DirectCampaignStateReadQuery]] = []

    def read_direct_report(
        self,
        connection_id: str,
        query: DirectReportsReadQuery,
    ) -> DirectReportBlock:
        self.report_calls.append((connection_id, query))
        return DirectReportBlock(
            source="DIRECT_REPORTS",
            retrieved_at="2026-07-30T11:55:00+00:00",
            watermark="2026-07-30T11:50:00+00:00",
            period_start="2026-07-23",
            period_end="2026-07-29",
            timezone="UTC",
            attribution="AUTO",
            currency="RUB",
            rows=tuple(
                DirectReportRow(
                    campaign="campaign-7",
                    date=f"2026-07-{day}",
                    impressions=1000 if day < 29 else 4000,
                    clicks=20 if day < 29 else 80,
                    cost_micros=500000000 if day < 29 else 2000000000,
                )
                for day in range(23, 30)
            ),
        )

    def read_direct_state(
        self,
        connection_id: str,
        query: DirectCampaignStateReadQuery,
    ) -> DirectCampaignStateBlock:
        self.state_calls.append((connection_id, query))
        return DirectCampaignStateBlock(
            source="DIRECT_CAMPAIGN_STATE",
            retrieved_at="2026-07-30T11:54:00+00:00",
            watermark="2026-07-30T11:49:00+00:00",
            campaign="campaign-7",
            campaign_state="ON",
            group_state="ON",
            ad_state="ON",
            strategy="HIGHEST_POSITION",
            current_weekly_budget_micros=10000000000,
            budget_period_start="2026-07-23T12:00:00+00:00",
            budget_period_end="2026-07-30T12:00:00+00:00",
            current_search_bid_micros=100000000,
            ad_variant="A",
            object_config_version="campaign-config-v1",
            last_change_author="customer-42",
            last_change_occurred_at="2026-07-22T12:00:00+00:00",
        )


class FailingAuthorizedDirectReader(RecordingAuthorizedDirectReader):
    def read_direct_report(
        self,
        connection_id: str,
        query: DirectReportsReadQuery,
    ) -> DirectReportBlock:
        del connection_id, query
        raise RuntimeError("provider unavailable: OAuth secret")


class MalformedAuthorizedDirectReader(RecordingAuthorizedDirectReader):
    def read_direct_report(
        self,
        connection_id: str,
        query: DirectReportsReadQuery,
    ) -> DirectReportBlock:
        report = super().read_direct_report(connection_id, query)
        return DirectReportBlock(
            source=report.source,
            retrieved_at=cast(str, 123),
            watermark=report.watermark,
            period_start=report.period_start,
            period_end=report.period_end,
            timezone=report.timezone,
            attribution=report.attribution,
            currency=report.currency,
            rows=report.rows,
        )


class StaleReportAuthorizedDirectReader(RecordingAuthorizedDirectReader):
    def read_direct_report(
        self,
        connection_id: str,
        query: DirectReportsReadQuery,
    ) -> DirectReportBlock:
        report = super().read_direct_report(connection_id, query)
        return DirectReportBlock(
            source=report.source,
            retrieved_at="2026-07-30T11:29:59+00:00",
            watermark="2026-07-30T11:25:00+00:00",
            period_start=report.period_start,
            period_end=report.period_end,
            timezone=report.timezone,
            attribution=report.attribution,
            currency=report.currency,
            rows=report.rows,
        )


class RecordingDirectReportReader:
    def __init__(self) -> None:
        self.queries: list[DirectReportsReadQuery] = []

    def read_report(self, query: DirectReportsReadQuery) -> DirectReportBlock:
        self.queries.append(query)
        return RecordingAuthorizedDirectReader().read_direct_report(
            "bound-connection",
            query,
        )


class RecordingDirectStateReader:
    def __init__(self) -> None:
        self.queries: list[DirectCampaignStateReadQuery] = []

    def read_campaign_state(
        self,
        query: DirectCampaignStateReadQuery,
    ) -> DirectCampaignStateBlock:
        self.queries.append(query)
        return RecordingAuthorizedDirectReader().read_direct_state(
            "bound-connection",
            query,
        )


class StandaloneDirectCustomerE2ETests(unittest.TestCase):
    def test_customer_evidence_returns_headless_direct_analysis(self) -> None:
        decision_records = InMemoryDecisionRecordStoreV1()
        module = DirectModuleV1(
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
            decision_records=decision_records,
        )
        adapter = HttpJsonModuleAdapterV1(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        )

        response = adapter.handle(customer_evidence_request())

        self.assertEqual(200, response.status_code)
        result = response.body
        self.assertEqual("PARTIAL", result["status"])
        metrics = {item["name"]: item for item in result["metrics"]}
        self.assertEqual(
            {"value": "2", "unit": "PERCENT"},
            {
                "value": metrics["ctr_percent"]["value"],
                "unit": metrics["ctr_percent"]["unit"],
            },
        )
        self.assertEqual("25", metrics["cpc_rub"]["value"])
        self.assertEqual("50", metrics["budget_utilization_percent"]["value"])
        self.assertEqual("50", metrics["pacing_percent"]["value"])
        self.assertEqual("ON", metrics["campaign_state"]["value"])
        self.assertEqual(
            "PARTIAL",
            result["assessment"]["data_quality_status"],
        )
        self.assertEqual(
            ["CONVERSION_CONTEXT_REQUIRED"],
            [item["code"] for item in result["recommendations"]],
        )
        self.assertEqual(
            ["DIRECT_TRAFFIC_EFFICIENCY_STABLE"],
            [item["code"] for item in result["hypotheses"]],
        )
        self.assertEqual(
            ["ctr_percent", "cpc_rub"],
            result["hypotheses"][0]["evidence_metric_names"],
        )
        self.assertLessEqual(len(result["hypotheses"]), 3)
        self.assertTrue(
            all(not item["executable"] for item in result["recommendations"])
        )
        self.assertEqual(
            ["CONVERSION_CONTEXT_UNAVAILABLE"],
            [item["code"] for item in result["warnings"]],
        )
        self.assertEqual(
            [
                {
                    "source_type": "CUSTOMER_EVIDENCE",
                    "source": "CUSTOMER_ECOSYSTEM",
                    "retrieved_at": "2026-07-30T11:55:00+00:00",
                    "watermark": "2026-07-30T11:50:00+00:00",
                    "evidence_id": "customer-direct-evidence-17",
                }
            ],
            result["provenance"],
        )
        self.assertIsNone(result["proposal"])
        self.assertIsNone(result["execution_result"])
        record = decision_records.read(result["decision_record_ref"])
        self.assertEqual("PARTIAL", record["outcome"])
        self.assertEqual(result["metrics"], record["facts"]["metrics"])
        self.assertEqual(result["hypotheses"], record["facts"]["hypotheses"])

    def test_authorized_provider_read_returns_statistics_state_and_provenance(
        self,
    ) -> None:
        reader = RecordingAuthorizedDirectReader()
        module = DirectModuleV1(
            provider_reader=reader,
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
        )
        request = customer_evidence_request()
        request.pop("external_evidence")

        response = HttpJsonModuleAdapterV1(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(200, response.status_code)
        self.assertEqual("PARTIAL", response.body["status"])
        metrics = {
            item["name"]: item["value"] for item in response.body["metrics"]
        }
        self.assertEqual(10000, metrics["impressions"])
        self.assertEqual(200, metrics["clicks"])
        self.assertEqual(5000000000, metrics["cost_micros"])
        self.assertEqual("2", metrics["ctr_percent"])
        self.assertEqual("25", metrics["cpc_rub"])
        self.assertEqual("ON", metrics["campaign_state"])
        self.assertEqual(10000000000, metrics["current_weekly_budget_micros"])
        self.assertEqual(
            [
                {
                    "source_type": "PROVIDER",
                    "source": "DIRECT_REPORTS",
                    "retrieved_at": "2026-07-30T11:55:00+00:00",
                    "watermark": "2026-07-30T11:50:00+00:00",
                },
                {
                    "source_type": "PROVIDER",
                    "source": "DIRECT_CAMPAIGN_STATE",
                    "retrieved_at": "2026-07-30T11:54:00+00:00",
                    "watermark": "2026-07-30T11:49:00+00:00",
                },
            ],
            response.body["provenance"],
        )
        self.assertEqual(
            [
                (
                    "customer-direct-primary",
                    DirectReportsReadQuery(
                        account="account-8",
                        campaign="campaign-7",
                        period_start="2026-07-23",
                        period_end="2026-07-29",
                        attribution="AUTO",
                    ),
                )
            ],
            reader.report_calls,
        )
        self.assertEqual(
            [
                (
                    "customer-direct-primary",
                    DirectCampaignStateReadQuery(
                        account="account-8",
                        campaign="campaign-7",
                    ),
                )
            ],
            reader.state_calls,
        )

    def test_valid_neutral_conversion_context_completes_the_conclusion(
        self,
    ) -> None:
        request = customer_evidence_request()
        evidence = request["external_evidence"]
        assert isinstance(evidence, dict)
        metrics = evidence["metrics"]
        assert isinstance(metrics, list)
        metrics.append(
            {"name": "conversions", "value": 5, "unit": "COUNT"}
        )
        module = DirectModuleV1(
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        )

        response = HttpJsonModuleAdapterV1(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(200, response.status_code)
        self.assertEqual("SUCCEEDED", response.body["status"])
        values = {
            item["name"]: item["value"] for item in response.body["metrics"]
        }
        self.assertEqual(5, values["conversions"])
        self.assertEqual("1000", values["cpa_rub"])
        self.assertEqual([], response.body["warnings"])
        self.assertEqual(
            "READY",
            response.body["assessment"]["data_quality_status"],
        )
        self.assertEqual(
            ["CONTINUE_MONITORING"],
            [item["code"] for item in response.body["recommendations"]],
        )

    def test_hypotheses_are_bounded_and_linked_to_returned_metrics(self) -> None:
        request = customer_evidence_request()
        evidence = request["external_evidence"]
        assert isinstance(evidence, dict)
        metrics = evidence["metrics"]
        assert isinstance(metrics, list)
        by_name = {item["name"]: item for item in metrics}
        by_name["impressions"]["value"] = 100000
        by_name["clicks"]["value"] = 100
        by_name["cost_micros"]["value"] = 12000000000
        metrics.append(
            {"name": "conversions", "value": 3, "unit": "COUNT"}
        )

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                )
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(200, response.status_code)
        hypotheses = response.body["hypotheses"]
        self.assertEqual(3, len(hypotheses))
        metric_names = {item["name"] for item in response.body["metrics"]}
        for hypothesis in hypotheses:
            self.assertTrue(hypothesis["evidence_metric_names"])
            self.assertTrue(
                set(hypothesis["evidence_metric_names"]).issubset(metric_names)
            )

    def test_raw_provider_payload_is_rejected_at_the_public_contract(self) -> None:
        request = customer_evidence_request()
        evidence = request["external_evidence"]
        assert isinstance(evidence, dict)
        evidence["raw_provider_payload"] = {
            "method": "campaigns.get",
            "result": {"Campaigns": []},
        }

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(400, response.status_code)
        self.assertEqual("REJECTED", response.body["status"])
        self.assertEqual(
            "CONTRACT_VALIDATION_FAILED",
            response.body["errors"][0]["code"],
        )

    def test_unknown_normalized_metric_is_rejected_without_analysis(self) -> None:
        request = customer_evidence_request()
        evidence = request["external_evidence"]
        assert isinstance(evidence, dict)
        metrics = evidence["metrics"]
        assert isinstance(metrics, list)
        metrics.append(
            {"name": "provider_http_body", "value": "opaque", "unit": "RAW"}
        )

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                )
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(422, response.status_code)
        self.assertEqual("REJECTED", response.body["status"])
        self.assertEqual(
            "DIRECT_EVIDENCE_REJECTED",
            response.body["errors"][0]["code"],
        )

    def test_invalid_neutral_conversion_context_is_rejected(self) -> None:
        request = customer_evidence_request()
        evidence = request["external_evidence"]
        assert isinstance(evidence, dict)
        metrics = evidence["metrics"]
        assert isinstance(metrics, list)
        metrics.append(
            {"name": "conversions", "value": 201, "unit": "COUNT"}
        )

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                )
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(422, response.status_code)
        self.assertEqual(
            "DIRECT_EVIDENCE_REJECTED",
            response.body["errors"][0]["code"],
        )
        self.assertIn(
            "conversions exceed clicks",
            response.body["errors"][0]["message"],
        )

    def test_stale_direct_evidence_is_partial_and_non_executable(self) -> None:
        request = customer_evidence_request()
        evidence = request["external_evidence"]
        assert isinstance(evidence, dict)
        evidence["observed_at"] = "2026-07-30T11:29:59+00:00"
        evidence["watermark"] = "2026-07-30T11:25:00+00:00"

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                )
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(200, response.status_code)
        self.assertEqual("PARTIAL", response.body["status"])
        self.assertEqual(
            "STALE_DATA",
            response.body["assessment"]["confidence_status"],
        )
        self.assertIn(
            "DIRECT_DATA_STALE",
            [item["code"] for item in response.body["warnings"]],
        )
        self.assertTrue(
            all(not item["executable"] for item in response.body["recommendations"])
        )
        self.assertIsNone(response.body["proposal"])

    def test_provider_failure_returns_a_retryable_error_without_secrets(
        self,
    ) -> None:
        request = customer_evidence_request()
        request.pop("external_evidence")

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                provider_reader=FailingAuthorizedDirectReader(),
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(500, response.status_code)
        self.assertEqual("FAILED", response.body["status"])
        self.assertEqual(
            "DIRECT_PROVIDER_READ_FAILED",
            response.body["errors"][0]["code"],
        )
        self.assertTrue(response.body["errors"][0]["retryable"])
        self.assertNotIn("OAuth secret", str(response.body))

    def test_stale_provider_report_makes_the_combined_result_stale(self) -> None:
        request = customer_evidence_request()
        request.pop("external_evidence")

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                provider_reader=StaleReportAuthorizedDirectReader(),
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            "STALE_DATA",
            response.body["assessment"]["confidence_status"],
        )
        self.assertIn(
            "DIRECT_DATA_STALE",
            [item["code"] for item in response.body["warnings"]],
        )

    def test_malformed_provider_response_is_rejected(self) -> None:
        request = customer_evidence_request()
        request.pop("external_evidence")

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                provider_reader=MalformedAuthorizedDirectReader(),
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(422, response.status_code)
        self.assertEqual("REJECTED", response.body["status"])
        self.assertEqual(
            "DIRECT_EVIDENCE_REJECTED",
            response.body["errors"][0]["code"],
        )

    def test_bound_provider_rejects_an_untrusted_scope_before_reading(self) -> None:
        report_reader = RecordingDirectReportReader()
        state_reader = RecordingDirectStateReader()
        provider = BoundDirectReadProviderV1(
            connection_id="customer-direct-primary",
            account_id="account-8",
            campaign_id="campaign-7",
            report_reader=report_reader,
            state_reader=state_reader,
        )
        request = customer_evidence_request()
        request.pop("external_evidence")
        scope = request["scope"]
        assert isinstance(scope, dict)
        scope["campaign_id"] = "rogue-campaign"

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                provider_reader=provider,
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(422, response.status_code)
        self.assertEqual(
            "DIRECT_SCOPE_REJECTED",
            response.body["errors"][0]["code"],
        )
        self.assertEqual([], report_reader.queries)
        self.assertEqual([], state_reader.queries)

    def test_clean_process_needs_no_metrika_credentials_requests_or_ui(
        self,
    ) -> None:
        payload = json.dumps(customer_evidence_request())
        script = f"""
import builtins
import json
blocked = []
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    protected = (
        name == "mox_adv.modules.metrika"
        or name.startswith("mox_adv.metrika")
        or name.startswith("mox_adv.ui")
        or name in ("mox_adv.egress", "mox_adv.host_launcher")
    )
    if protected:
        blocked.append(name)
        raise AssertionError("standalone Direct imported " + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
from datetime import datetime, timezone
from mox_adv.environment import ExecutionEnvironment
from mox_adv.module_api.v1 import HttpJsonModuleAdapterV1
from mox_adv.modules.direct import DirectModuleV1
module = DirectModuleV1(
    clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
)
response = HttpJsonModuleAdapterV1(
    module,
    environment=ExecutionEnvironment.PRODUCTION,
).handle(json.loads({payload!r}))
assert response.status_code == 200, response.body
assert response.body["status"] == "PARTIAL", response.body
assert blocked == [], blocked
"""

        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            env={"PYTHONPATH": str(ROOT / "src")},
            text=True,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_standalone_wheel_contains_no_metrika_or_dashboard_and_runs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            (temporary / "egg-info").mkdir()
            build = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "packaging" / "direct" / "setup.py"),
                    "egg_info",
                    "--egg-base",
                    str(temporary / "egg-info"),
                    "build",
                    "--build-base",
                    str(temporary / "build"),
                    "bdist_wheel",
                    "--dist-dir",
                    str(temporary / "dist"),
                    "--bdist-dir",
                    str(temporary / "wheel"),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, build.returncode, build.stderr)
            wheels = tuple((temporary / "dist").glob("*.whl"))
            self.assertEqual(1, len(wheels))
            with zipfile.ZipFile(wheels[0]) as archive:
                names = set(archive.namelist())
            self.assertNotIn("mox_adv/modules/metrika.py", names)
            self.assertFalse(
                any(name.startswith("mox_adv/metrika") for name in names),
                names,
            )
            self.assertFalse(
                any(name.startswith("mox_adv/ui/") for name in names),
                names,
            )

            installed = temporary / "installed"
            install = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--quiet",
                    "--no-deps",
                    "--target",
                    str(installed),
                    str(wheels[0]),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, install.returncode, install.stderr)
            script = """
import json
from datetime import datetime, timezone
from mox_adv.environment import ExecutionEnvironment
from mox_adv.module_api.v1 import HttpJsonModuleAdapterV1
from mox_adv.modules.direct import DirectModuleV1
request = json.loads(__import__("os").environ["DIRECT_REQUEST"])
module = DirectModuleV1(
    clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
)
response = HttpJsonModuleAdapterV1(
    module,
    environment=ExecutionEnvironment.PRODUCTION,
).handle(request)
assert response.status_code == 200, response.body
assert response.body["status"] == "PARTIAL", response.body
assert response.body["module"]["module_id"] == "YANDEX_DIRECT", response.body
"""
            completed = subprocess.run(
                [sys.executable, "-c", script],
                check=False,
                capture_output=True,
                env={
                    "DIRECT_REQUEST": json.dumps(customer_evidence_request()),
                    "PYTHONPATH": str(installed),
                },
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)


if __name__ == "__main__":
    unittest.main()
