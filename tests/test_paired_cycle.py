from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import NoReturn

from mox_adv.contracts import DirectCampaignStateReadQuery, DirectReportsReadQuery
from mox_adv.environment import ExecutionEnvironment
from mox_adv.module_api.v1 import InProcessModuleAdapterV1, ModuleRequestV1
from mox_adv.modules.direct import DirectModuleV1


class _ForbiddenProductionReader:
    def __init__(self) -> None:
        self.report_reads = 0
        self.state_reads = 0

    def read_direct_report(
        self,
        connection_id: str,
        query: DirectReportsReadQuery,
    ) -> NoReturn:
        self.report_reads += 1
        raise AssertionError("Production block happened after a Direct report read.")

    def read_direct_state(
        self,
        connection_id: str,
        query: DirectCampaignStateReadQuery,
    ) -> NoReturn:
        self.state_reads += 1
        raise AssertionError("Production block happened after a Direct state read.")

    def authorizes_change_author(
        self,
        connection_id: str,
        author: str,
    ) -> bool:
        raise AssertionError("Production block happened after provider authorization.")


class PairedCycleSafetyTests(unittest.TestCase):
    def test_paired_execute_stops_before_provider_read_in_production(self) -> None:
        reader = _ForbiddenProductionReader()
        module = DirectModuleV1(
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
            provider_reader=reader,
        )
        request = ModuleRequestV1.from_dict(
            {
                "schema_version": "module-request-v1",
                "connection_ref": {"connection_id": "sim-connection"},
                "environment": "PRODUCTION",
                "scope": {
                    "organization_id": "sim-organization",
                    "account_id": "sim-direct-account",
                    "campaign_id": "sim-campaign",
                },
                "period": {
                    "start_date": "2026-07-21",
                    "end_date": "2026-07-27",
                    "timezone": "UTC",
                },
                "objective": {
                    "code": "PAIRED_MONITORING_CYCLE",
                    "description": "Apply an exact paired proposal.",
                },
                "external_evidence": {
                    "schema_version": "normalized-metrics-evidence-v1",
                    "evidence_id": "sha256:" + "1" * 64,
                    "source": "PAIRED_MODULE_RESULT",
                    "observed_at": "2026-07-30T11:55:00+00:00",
                    "watermark": "2026-07-30T11:54:00+00:00",
                    "metrics": [{"name": "impressions", "value": 100, "unit": "COUNT"}],
                },
                "operation": {
                    "kind": "EXECUTE",
                    "operation_type": "APPLY_OPTIMIZATION",
                },
                "direct_action_command": {
                    "schema_version": "direct-action-command-v1",
                    "command": "EXECUTE_PROPOSAL",
                    "proposal_id": "proposal-production-block",
                },
                "idempotency_key": "paired-production-block",
            }
        )

        result = InProcessModuleAdapterV1(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        ).invoke(request)

        self.assertEqual("BLOCKED", result.status)
        self.assertEqual(
            "PRODUCTION_WRITE_FORBIDDEN",
            result.errors[0].code,
        )
        self.assertEqual(0, reader.report_reads)
        self.assertEqual(0, reader.state_reads)
        self.assertIsNotNone(result.decision_record_ref)


if __name__ == "__main__":
    unittest.main()
