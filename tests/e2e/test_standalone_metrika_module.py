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
    MetrikaReportBlock,
    MetrikaReportReadQuery,
    MetrikaReportRow,
)
from mox_adv.environment import ExecutionEnvironment
from mox_adv.module_api.v1 import (
    HttpJsonModuleAdapterV1,
    InMemoryDecisionRecordStoreV1,
)
from mox_adv.modules.metrika import (
    BoundMetrikaReadProviderV1,
    MetrikaModuleV1,
)

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_METRIKA_METRICS = [
    {"name": "visits", "value": 150, "unit": "COUNT"},
    {"name": "goal_visits", "value": 10, "unit": "COUNT"},
    {
        "name": "conversion_rate_percent",
        "value": "6.666666666666666666666666667",
        "unit": "PERCENT",
    },
]


def customer_evidence_request() -> dict[str, Any]:
    return {
        "schema_version": "module-request-v1",
        "connection_ref": {"connection_id": "customer-metrika-primary"},
        "environment": "PRODUCTION",
        "scope": {
            "organization_id": "customer-42",
            "counter_id": "counter-9",
            "goal_id": "goal-3",
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
            "evidence_id": "customer-evidence-17",
            "source": "CUSTOMER_ECOSYSTEM",
            "observed_at": "2026-07-30T11:55:00+00:00",
            "watermark": "2026-07-30T11:50:00+00:00",
            "metrics": [
                {"name": "visits", "value": 150, "unit": "COUNT"},
                {"name": "goal_visits", "value": 10, "unit": "COUNT"},
            ],
        },
        "operation": {
            "kind": "ANALYZE",
            "operation_type": "ANALYZE_PERFORMANCE",
        },
        "idempotency_key": "customer-run-2026-07-30-001",
    }


class RecordingAuthorizedMetrikaReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, MetrikaReportReadQuery]] = []

    def read_metrika_report(
        self,
        connection_id: str,
        query: MetrikaReportReadQuery,
    ) -> MetrikaReportBlock:
        self.calls.append((connection_id, query))
        return MetrikaReportBlock(
            source="METRIKA_REPORT",
            retrieved_at="2026-07-30T11:55:00+00:00",
            watermark="2026-07-30T11:50:00+00:00",
            period_start="2026-07-23",
            period_end="2026-07-29",
            timezone="UTC",
            attribution="automatic",
            rows=tuple(
                MetrikaReportRow(
                    campaign="campaign-7",
                    goal="goal-3",
                    date=f"2026-07-{day}",
                    visits=20 if day < 29 else 30,
                    goal_visits=1 if day < 27 else 2,
                )
                for day in range(23, 30)
            ),
        )


class FailingAuthorizedMetrikaReader:
    def read_metrika_report(
        self,
        connection_id: str,
        query: MetrikaReportReadQuery,
    ) -> MetrikaReportBlock:
        del connection_id, query
        raise RuntimeError("provider temporarily unavailable: OAuth secret")


class NonUtcAuthorizedMetrikaReader(RecordingAuthorizedMetrikaReader):
    def read_metrika_report(
        self,
        connection_id: str,
        query: MetrikaReportReadQuery,
    ) -> MetrikaReportBlock:
        report = super().read_metrika_report(connection_id, query)
        return MetrikaReportBlock(
            source=report.source,
            retrieved_at="2026-07-30T14:55:00+03:00",
            watermark="2026-07-30T14:50:00+03:00",
            period_start=report.period_start,
            period_end=report.period_end,
            timezone="Europe/Moscow",
            attribution=report.attribution,
            rows=report.rows,
        )


class MalformedAuthorizedMetrikaReader(RecordingAuthorizedMetrikaReader):
    def read_metrika_report(
        self,
        connection_id: str,
        query: MetrikaReportReadQuery,
    ) -> MetrikaReportBlock:
        report = super().read_metrika_report(connection_id, query)
        return MetrikaReportBlock(
            source=report.source,
            retrieved_at=cast(str, 123),
            watermark=report.watermark,
            period_start=report.period_start,
            period_end=report.period_end,
            timezone=report.timezone,
            attribution=report.attribution,
            rows=report.rows,
        )


class RecordingMetrikaReportReader:
    def __init__(self) -> None:
        self.queries: list[MetrikaReportReadQuery] = []

    def read_metrika_report(
        self,
        query: MetrikaReportReadQuery,
    ) -> MetrikaReportBlock:
        self.queries.append(query)
        return RecordingAuthorizedMetrikaReader().read_metrika_report(
            "bound-connection",
            query,
        )


class StandaloneMetrikaCustomerE2ETests(unittest.TestCase):
    def test_customer_evidence_returns_a_headless_partial_analysis(self) -> None:
        decision_records = InMemoryDecisionRecordStoreV1()
        module = MetrikaModuleV1(
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
            decision_records=decision_records,
        )
        adapter = HttpJsonModuleAdapterV1.for_embedded(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        )

        response = adapter.handle(customer_evidence_request())

        self.assertEqual(200, response.status_code)
        result = response.body
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual(EXPECTED_METRIKA_METRICS, result["metrics"])
        self.assertEqual("PARTIAL", result["assessment"]["data_quality_status"])
        self.assertEqual(
            ["CAMPAIGN_CONTEXT_REQUIRED"],
            [item["code"] for item in result["recommendations"]],
        )
        self.assertTrue(
            all(not item["executable"] for item in result["recommendations"])
        )
        self.assertEqual(
            [
                {
                    "source_type": "CUSTOMER_EVIDENCE",
                    "source": "CUSTOMER_ECOSYSTEM",
                    "retrieved_at": "2026-07-30T11:55:00+00:00",
                    "watermark": "2026-07-30T11:50:00+00:00",
                    "evidence_id": "customer-evidence-17",
                }
            ],
            result["provenance"],
        )
        self.assertEqual(
            ["CAMPAIGN_SPEND_UNAVAILABLE", "CAMPAIGN_STATE_UNAVAILABLE"],
            [item["code"] for item in result["warnings"]],
        )
        self.assertIsNone(result["proposal"])
        self.assertIsNone(result["execution_result"])
        self.assertRegex(
            result["decision_record_ref"],
            r"^decision-records/[0-9a-f]{64}\.json$",
        )
        record = decision_records.read(result["decision_record_ref"])
        self.assertEqual("PARTIAL", record["outcome"])
        self.assertEqual(result["metrics"], record["facts"]["metrics"])
        self.assertEqual(
            [
                "CAMPAIGN_SPEND_UNAVAILABLE",
                "CAMPAIGN_STATE_UNAVAILABLE",
            ],
            record["reason_codes"],
        )

    def test_authorized_provider_read_uses_the_closed_customer_scope(self) -> None:
        reader = RecordingAuthorizedMetrikaReader()
        module = MetrikaModuleV1(
            provider_reader=reader,
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
        )
        adapter = HttpJsonModuleAdapterV1.for_embedded(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        )
        request = customer_evidence_request()
        request.pop("external_evidence")
        request["scope"]["campaign_id"] = "campaign-7"

        response = adapter.handle(request)

        self.assertEqual(200, response.status_code)
        self.assertEqual("PARTIAL", response.body["status"])
        self.assertEqual(EXPECTED_METRIKA_METRICS, response.body["metrics"])
        self.assertEqual(
            [
                {
                    "source_type": "PROVIDER",
                    "source": "METRIKA_REPORT",
                    "retrieved_at": "2026-07-30T11:55:00+00:00",
                    "watermark": "2026-07-30T11:50:00+00:00",
                }
            ],
            response.body["provenance"],
        )
        self.assertEqual(
            [
                (
                    "customer-metrika-primary",
                    MetrikaReportReadQuery(
                        counter="counter-9",
                        campaign="campaign-7",
                        goal="goal-3",
                        period_start="2026-07-23",
                        period_end="2026-07-29",
                        attribution="automatic",
                    ),
                )
            ],
            reader.calls,
        )

    def test_small_conversion_sample_is_reported_without_executable_advice(
        self,
    ) -> None:
        request = customer_evidence_request()
        evidence = request["external_evidence"]
        assert isinstance(evidence, dict)
        metrics = evidence["metrics"]
        assert isinstance(metrics, list)
        metrics[1]["value"] = 2
        module = MetrikaModuleV1(
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        )

        response = HttpJsonModuleAdapterV1.for_embedded(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(200, response.status_code)
        self.assertEqual("PARTIAL", response.body["status"])
        self.assertEqual(
            "INSUFFICIENT_DATA",
            response.body["assessment"]["confidence_status"],
        )
        self.assertIn(
            "INSUFFICIENT_SAMPLE",
            [item["code"] for item in response.body["warnings"]],
        )
        self.assertTrue(
            all(not item["executable"] for item in response.body["recommendations"])
        )

    def test_provider_failure_returns_a_retryable_typed_error_without_secrets(
        self,
    ) -> None:
        request = customer_evidence_request()
        request.pop("external_evidence")
        request["scope"]["campaign_id"] = "campaign-7"
        module = MetrikaModuleV1(
            provider_reader=FailingAuthorizedMetrikaReader(),
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
        )

        response = HttpJsonModuleAdapterV1.for_embedded(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(500, response.status_code)
        self.assertEqual("FAILED", response.body["status"])
        self.assertEqual(
            "METRIKA_PROVIDER_READ_FAILED",
            response.body["errors"][0]["code"],
        )
        self.assertTrue(response.body["errors"][0]["retryable"])
        self.assertNotIn("OAuth secret", str(response.body))

    def test_stale_evidence_is_explicit_and_non_executable(self) -> None:
        request = customer_evidence_request()
        evidence = request["external_evidence"]
        assert isinstance(evidence, dict)
        evidence["observed_at"] = "2026-07-30T05:59:59+00:00"
        evidence["watermark"] = "2026-07-30T05:55:00+00:00"
        module = MetrikaModuleV1(
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        )

        response = HttpJsonModuleAdapterV1.for_embedded(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            "STALE_DATA",
            response.body["assessment"]["confidence_status"],
        )
        self.assertIn(
            "METRIKA_DATA_STALE",
            [item["code"] for item in response.body["warnings"]],
        )
        self.assertIsNone(response.body["proposal"])

    def test_stale_small_sample_reports_both_quality_gaps(self) -> None:
        request = customer_evidence_request()
        evidence = request["external_evidence"]
        assert isinstance(evidence, dict)
        evidence["observed_at"] = "2026-07-30T05:59:59+00:00"
        evidence["watermark"] = "2026-07-30T05:55:00+00:00"
        metrics = evidence["metrics"]
        assert isinstance(metrics, list)
        metrics[1]["value"] = 2
        module = MetrikaModuleV1(
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        )

        response = HttpJsonModuleAdapterV1.for_embedded(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "CAMPAIGN_SPEND_UNAVAILABLE",
                "CAMPAIGN_STATE_UNAVAILABLE",
                "INSUFFICIENT_SAMPLE",
                "METRIKA_DATA_STALE",
            },
            {item["code"] for item in response.body["warnings"]},
        )
        self.assertEqual(
            "INSUFFICIENT_DATA",
            response.body["assessment"]["confidence_status"],
        )

    def test_provider_read_rejects_non_utc_report_provenance(self) -> None:
        request = customer_evidence_request()
        request.pop("external_evidence")
        request["scope"]["campaign_id"] = "campaign-7"
        request["period"]["timezone"] = "Europe/Moscow"
        module = MetrikaModuleV1(
            provider_reader=NonUtcAuthorizedMetrikaReader(),
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
        )

        response = HttpJsonModuleAdapterV1.for_embedded(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(422, response.status_code)
        self.assertEqual("REJECTED", response.body["status"])
        self.assertEqual(
            "METRIKA_EVIDENCE_REJECTED",
            response.body["errors"][0]["code"],
        )

    def test_malformed_typed_provider_evidence_returns_a_typed_error(self) -> None:
        request = customer_evidence_request()
        request.pop("external_evidence")
        request["scope"]["campaign_id"] = "campaign-7"
        module = MetrikaModuleV1(
            provider_reader=MalformedAuthorizedMetrikaReader(),
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
        )

        response = HttpJsonModuleAdapterV1.for_embedded(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(422, response.status_code)
        self.assertEqual("REJECTED", response.body["status"])
        self.assertEqual(
            "METRIKA_EVIDENCE_REJECTED",
            response.body["errors"][0]["code"],
        )

    def test_invalid_normalized_evidence_is_rejected_before_analysis(self) -> None:
        request = customer_evidence_request()
        evidence = request["external_evidence"]
        assert isinstance(evidence, dict)
        metrics = evidence["metrics"]
        assert isinstance(metrics, list)
        metrics[0]["value"] = 2
        metrics[1]["value"] = 3
        module = MetrikaModuleV1(
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        )

        response = HttpJsonModuleAdapterV1.for_embedded(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(422, response.status_code)
        self.assertEqual("REJECTED", response.body["status"])
        self.assertEqual(
            "METRIKA_EVIDENCE_REJECTED",
            response.body["errors"][0]["code"],
        )
        self.assertEqual([], response.body["recommendations"])
        self.assertIsNone(response.body["proposal"])

    def test_open_period_is_rejected_before_the_provider_is_called(self) -> None:
        request = customer_evidence_request()
        request.pop("external_evidence")
        request["scope"]["campaign_id"] = "campaign-7"
        request["period"]["end_date"] = "2026-07-30"
        reader = RecordingAuthorizedMetrikaReader()
        module = MetrikaModuleV1(
            provider_reader=reader,
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
        )

        response = HttpJsonModuleAdapterV1.for_embedded(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(422, response.status_code)
        self.assertEqual("REJECTED", response.body["status"])
        self.assertEqual([], reader.calls)

    def test_stored_connection_binding_rejects_an_unauthorized_counter(
        self,
    ) -> None:
        report_reader = RecordingMetrikaReportReader()
        provider_reader = BoundMetrikaReadProviderV1(
            connection_id="customer-metrika-primary",
            counter_id="counter-9",
            goal_id="goal-3",
            campaign_id="campaign-7",
            reader=report_reader,
        )
        request = customer_evidence_request()
        request.pop("external_evidence")
        request["scope"]["campaign_id"] = "campaign-7"
        request["scope"]["counter_id"] = "unauthorized-counter"
        module = MetrikaModuleV1(
            provider_reader=provider_reader,
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
        )

        response = HttpJsonModuleAdapterV1.for_embedded(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(422, response.status_code)
        self.assertEqual("REJECTED", response.body["status"])
        self.assertEqual(
            "METRIKA_SCOPE_REJECTED",
            response.body["errors"][0]["code"],
        )
        self.assertEqual([], report_reader.queries)

    def test_clean_process_needs_no_direct_credentials_requests_or_ui(
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
        name == "mox_adv.modules.direct"
        or name.startswith("mox_adv.ui")
        or name in ("mox_adv.egress", "mox_adv.host_launcher")
    )
    if protected:
        blocked.append(name)
        raise AssertionError("standalone Metrika imported " + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
from datetime import datetime, timezone
from mox_adv.environment import ExecutionEnvironment
from mox_adv.module_api.v1 import HttpJsonModuleAdapterV1
from mox_adv.modules.metrika import MetrikaModuleV1
module = MetrikaModuleV1(
    clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
)
response = HttpJsonModuleAdapterV1.for_embedded(
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

    def test_standalone_wheel_contains_no_direct_module_or_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            (temporary / "egg-info").mkdir()
            build = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "packaging" / "metrika" / "setup.py"),
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
            self.assertIn("mox_adv/metrika_goal_lifecycle.py", names)
            self.assertIn("mox_adv/goal_service.py", names)
            self.assertNotIn("mox_adv/modules/direct.py", names)
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
from mox_adv.modules.metrika import MetrikaModuleV1
request = json.loads(__import__("os").environ["METRIKA_REQUEST"])
module = MetrikaModuleV1(
    clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
)
response = HttpJsonModuleAdapterV1.for_embedded(
    module,
    environment=ExecutionEnvironment.PRODUCTION,
).handle(request)
assert response.status_code == 200, response.body
assert response.body["status"] == "PARTIAL", response.body
"""
            completed = subprocess.run(
                [sys.executable, "-c", script],
                check=False,
                capture_output=True,
                env={
                    "METRIKA_REQUEST": json.dumps(customer_evidence_request()),
                    "PYTHONPATH": str(installed),
                },
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)


if __name__ == "__main__":
    unittest.main()
