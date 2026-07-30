from __future__ import annotations

import json
import os
import tempfile
import unittest
from copy import deepcopy
from dataclasses import fields, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

from mox_adv.contracts import DirectCampaignStateReadQuery, DirectReportsReadQuery
from mox_adv.environment import ExecutionEnvironment
from mox_adv.impact import load_impact_fixture
from mox_adv.module_api.v1 import (
    DirectoryDecisionRecordStoreV1,
    HttpJsonModuleAdapterV1,
    InProcessModuleAdapterV1,
    ModuleRequestV1,
)
from mox_adv.modules.direct import DIRECT_IDENTITY, DirectModuleV1
from mox_adv.normalization import IntegratedSnapshotNormalizerV1
from mox_adv.observe import run_observe_fixture
from mox_adv.paired_cycle import (
    evaluate_paired_direct_impact,
    execute_paired_direct_test_action,
)
from mox_adv.recommend_projection import build_sanitized_projection
from mox_adv.ui_service import _projection_source

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
        request = self._internal_production_request()

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
                self._internal_production_request(),
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

    def test_http_rejects_forged_paired_evidence_before_module_invocation(
        self,
    ) -> None:
        reader = _ForbiddenProductionReader()
        response = HttpJsonModuleAdapterV1.for_embedded(
            DirectModuleV1(provider_reader=reader),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(self._production_payload("PAIRED_MODULE_RESULT"))

        self.assertEqual(400, response.status_code)
        self.assertEqual(
            "CONTRACT_VALIDATION_FAILED",
            response.body["errors"][0]["code"],
        )
        self.assertEqual(0, reader.report_reads)
        self.assertEqual(0, reader.state_reads)

    def test_openapi_exposes_only_customer_evidence_source(self) -> None:
        document = json.loads(
            (ROOT / "openapi" / "module-api-v1.openapi.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            "CUSTOMER_ECOSYSTEM",
            document["components"]["schemas"]["ExternalEvidenceV1"]["properties"][
                "source"
            ]["const"],
        )

    def test_paired_execution_cannot_accept_wholesale_policy_facts(self) -> None:
        parameter_names = execute_paired_direct_test_action.__annotations__
        self.assertNotIn("execution_facts", parameter_names)

        from mox_adv.direct_action_runtime import PairedDirectActionContextV1

        self.assertNotIn(
            "execution_facts",
            {field.name for field in fields(PairedDirectActionContextV1)},
        )

    def test_paired_projection_must_match_trusted_snapshot_policy_facts(
        self,
    ) -> None:
        policy = json.loads(
            (ROOT / "config" / "gate0-policy.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_observe_fixture(
                run_id="paired-projection",
                runs_root=root,
                fixture_path=ROOT / "fixtures" / "linked-observe.json",
                policy_path=ROOT / "config" / "gate0-policy.json",
            )
            snapshot = json.loads(
                (root / "paired-projection" / "result.json").read_text(encoding="utf-8")
            )["snapshot"]
        projection = build_sanitized_projection(
            _projection_source(snapshot),
            policy,
        )
        changed = deepcopy(snapshot)
        changed["comparability_status"] = "INCOMPATIBLE"
        changed["financial_recommendations_allowed"] = False
        changed["snapshot_id"] = IntegratedSnapshotNormalizerV1.fingerprint(changed)

        from mox_adv import paired_cycle

        validator = getattr(paired_cycle, "_validate_paired_projection")
        with self.assertRaisesRegex(ValueError, "comparability"):
            validator(changed, projection)

    @staticmethod
    def _internal_production_request() -> ModuleRequestV1:
        request = ModuleRequestV1.from_dict(
            PairedCycleSafetyTests._production_payload("CUSTOMER_ECOSYSTEM")
        )
        assert request.external_evidence is not None
        return replace(
            request,
            external_evidence=replace(
                request.external_evidence,
                source="PAIRED_MODULE_RESULT",
            ),
        )

    @staticmethod
    def _production_payload(source: str) -> dict[str, object]:
        return {
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
                "source": source,
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


if __name__ == "__main__":
    unittest.main()
