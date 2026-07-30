from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

from mox_adv.contracts import DirectCampaignStateReadQuery, DirectReportsReadQuery
from mox_adv.environment import ExecutionEnvironment
from mox_adv.impact import load_impact_fixture
from mox_adv.module_api.v1 import (
    DirectoryDecisionRecordStoreV1,
    InProcessModuleAdapterV1,
    ModuleRequestV1,
)
from mox_adv.modules.direct import DIRECT_IDENTITY, DirectModuleV1
from mox_adv.paired_cycle import evaluate_paired_direct_impact

ROOT = Path(__file__).resolve().parents[1]


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
        request = self._production_request()

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

    def test_directory_decision_record_rejects_canonical_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = DirectoryDecisionRecordStoreV1(root)
            receipt = store.record_production_write_block(
                DIRECT_IDENTITY,
                self._production_request(),
                ExecutionEnvironment.PRODUCTION,
            )
            path = root / (receipt.decision_id + ".json")
            value = json.loads(path.read_text(encoding="utf-8"))
            value["outcome"] = "SUCCEEDED"
            os.chmod(path, 0o600)
            path.write_text(
                json.dumps(
                    value,
                    ensure_ascii=True,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            os.chmod(path, 0o400)

            with self.assertRaisesRegex(KeyError, "integrity"):
                store.read(receipt.reference)

    def test_paired_impact_hashes_a_maximum_length_change_idempotency_key(
        self,
    ) -> None:
        policy = json.loads(
            (ROOT / "config" / "gate0-policy.json").read_text(encoding="utf-8")
        )
        fixture = load_impact_fixture(
            ROOT / "fixtures" / "impact" / "IMPACT_CPA_IMPROVED_KEEP.json",
            policy,
        )
        request = replace(fixture, change_id="c" * 128)

        with tempfile.TemporaryDirectory() as temporary:
            outcome = evaluate_paired_direct_impact(
                run_directory=Path(temporary),
                policy=policy,
                request=request,
            )

        key = str(outcome.decision_record["idempotency_key"])
        self.assertLessEqual(len(key), 128)
        self.assertRegex(key, r"^paired-impact-sha256-[0-9a-f]{64}$")

    @staticmethod
    def _production_request() -> ModuleRequestV1:
        return ModuleRequestV1.from_dict(
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


if __name__ == "__main__":
    unittest.main()
