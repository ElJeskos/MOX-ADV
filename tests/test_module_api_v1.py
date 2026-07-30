from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from mox_adv.module_api.v1 import (
    ContractValidationError,
    HttpJsonModuleAdapterV1,
    InProcessModuleAdapterV1,
    ModuleIdentityV1,
    ModuleRequestV1,
    ModuleResultV1,
)


ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "openapi" / "module-api-v1.openapi.json"


def valid_request_payload() -> dict[str, Any]:
    return {
        "schema_version": "module-request-v1",
        "connection_ref": {"connection_id": "customer-metrika-primary"},
        "environment": "PRODUCTION",
        "scope": {
            "organization_id": "customer-42",
            "campaign_id": "campaign-7",
            "counter_id": "counter-9",
            "goal_id": "goal-3",
        },
        "period": {
            "start_date": "2026-07-01",
            "end_date": "2026-07-29",
            "timezone": "Europe/Moscow",
        },
        "objective": {
            "code": "REDUCE_CPA",
            "description": "Reduce CPA without losing qualified conversions.",
        },
        "external_evidence": {
            "schema_version": "normalized-metrics-evidence-v1",
            "evidence_id": "customer-evidence-17",
            "source": "CUSTOMER_ECOSYSTEM",
            "observed_at": "2026-07-30T09:00:00+00:00",
            "watermark": "2026-07-30T08:55:00+00:00",
            "metrics": [
                {
                    "name": "goal_visits",
                    "value": 21,
                    "unit": "COUNT",
                },
                {
                    "name": "cost_rub",
                    "value": "4200.00",
                    "unit": "RUB",
                },
            ],
        },
        "operation": {
            "kind": "ANALYZE",
            "operation_type": "ANALYZE_PERFORMANCE",
        },
        "idempotency_key": "customer-run-2026-07-30-001",
    }


def successful_result_payload() -> dict[str, Any]:
    return {
        "schema_version": "module-result-v1",
        "run_id": "module-run-1",
        "module": {
            "module_id": "YANDEX_METRIKA",
            "module_version": "1.0.0",
        },
        "status": "SUCCEEDED",
        "metrics": [
            {
                "name": "goal_visits",
                "value": 21,
                "unit": "COUNT",
            }
        ],
        "assessment": {
            "summary": "The supplied evidence is sufficient for analysis.",
            "data_quality_status": "READY",
            "confidence_status": "READY",
        },
        "recommendations": [
            {
                "code": "KEEP_GOAL",
                "summary": "Keep the current goal.",
                "rationale": "The goal is collecting qualified conversions.",
                "executable": False,
            }
        ],
        "proposal": None,
        "execution_result": None,
        "provenance": [
            {
                "source_type": "CUSTOMER_EVIDENCE",
                "source": "CUSTOMER_ECOSYSTEM",
                "retrieved_at": "2026-07-30T09:00:01+00:00",
                "watermark": "2026-07-30T08:55:00+00:00",
                "evidence_id": "customer-evidence-17",
            }
        ],
        "warnings": [],
        "errors": [],
        "decision_record_ref": "decision-records/module-run-1.json",
    }


class RecordingModule:
    def __init__(self, module_id: str) -> None:
        self.identity = ModuleIdentityV1(
            module_id=module_id,
            module_version="1.0.0",
        )
        self.requests: list[ModuleRequestV1] = []

    def invoke(self, request: ModuleRequestV1) -> ModuleResultV1:
        self.requests.append(request)
        payload = successful_result_payload()
        payload["module"]["module_id"] = self.identity.module_id
        return ModuleResultV1.from_dict(payload)


class ModuleRequestContractTests(unittest.TestCase):
    def test_complete_request_round_trips_without_transport_details(self) -> None:
        payload = valid_request_payload()

        request = ModuleRequestV1.from_dict(payload)

        self.assertEqual(payload, request.as_dict())
        serialized = json.dumps(request.as_dict())
        self.assertNotIn("oauth", serialized.lower())
        self.assertNotIn("endpoint", serialized.lower())
        self.assertNotIn("http_method", serialized.lower())

    def test_request_rejects_credential_endpoint_and_raw_payload_fields(self) -> None:
        forbidden_cases = (
            ("oauth_token", "secret"),
            ("endpoint", "https://api-metrika.yandex.net"),
            ("raw_yandex_payload", {"query": "anything"}),
        )
        for field, value in forbidden_cases:
            with self.subTest(field=field):
                payload = valid_request_payload()
                payload[field] = value

                with self.assertRaisesRegex(
                    ContractValidationError,
                    "unexpected field",
                ):
                    ModuleRequestV1.from_dict(payload)

    def test_external_evidence_accepts_only_normalized_scalar_metrics(self) -> None:
        payload = valid_request_payload()
        evidence = payload["external_evidence"]
        assert isinstance(evidence, dict)
        evidence["raw_response"] = {
            "headers": {"Authorization": "OAuth secret"},
            "rows": [],
        }

        with self.assertRaisesRegex(
            ContractValidationError,
            "unexpected field",
        ):
            ModuleRequestV1.from_dict(payload)

    def test_optional_external_evidence_is_omitted_instead_of_null(self) -> None:
        payload = valid_request_payload()
        payload.pop("external_evidence")

        request = ModuleRequestV1.from_dict(payload)

        self.assertNotIn("external_evidence", request.as_dict())
        payload["external_evidence"] = None
        with self.assertRaisesRegex(
            ContractValidationError,
            "must be an object when present",
        ):
            ModuleRequestV1.from_dict(payload)

    def test_operation_is_a_closed_high_level_type(self) -> None:
        payload = valid_request_payload()
        operation = payload["operation"]
        assert isinstance(operation, dict)
        operation["operation_type"] = "POST /campaigns"

        with self.assertRaisesRegex(
            ContractValidationError,
            "operation.operation_type must be one of",
        ):
            ModuleRequestV1.from_dict(payload)


class ModuleAdapterContractTests(unittest.TestCase):
    def test_http_and_in_process_adapters_invoke_the_same_module_contract(self) -> None:
        request_payload = valid_request_payload()
        request = ModuleRequestV1.from_dict(request_payload)
        module = RecordingModule("YANDEX_METRIKA")

        in_process_result = InProcessModuleAdapterV1(module).invoke(request)
        http_response = HttpJsonModuleAdapterV1(module).handle(request_payload)

        self.assertEqual(200, http_response.status_code)
        self.assertEqual(in_process_result.as_dict(), http_response.body)
        self.assertEqual([request, request], module.requests)

    def test_invalid_http_request_returns_typed_module_result(self) -> None:
        module = RecordingModule("YANDEX_DIRECT")
        payload = valid_request_payload()
        payload["oauth_token"] = "must-not-cross-the-boundary"

        response = HttpJsonModuleAdapterV1(module).handle(payload)

        self.assertEqual(400, response.status_code)
        self.assertEqual("module-result-v1", response.body["schema_version"])
        self.assertEqual("REJECTED", response.body["status"])
        self.assertEqual("CONTRACT_VALIDATION_FAILED", response.body["errors"][0]["code"])
        self.assertEqual([], module.requests)
        self.assertNotIn("must-not-cross-the-boundary", json.dumps(response.body))

    def test_direct_and_metrika_modules_need_no_cross_provider_configuration(
        self,
    ) -> None:
        direct = RecordingModule("YANDEX_DIRECT")
        metrika = RecordingModule("YANDEX_METRIKA")

        direct_result = InProcessModuleAdapterV1(direct).invoke(
            ModuleRequestV1.from_dict(valid_request_payload())
        )
        metrika_result = InProcessModuleAdapterV1(metrika).invoke(
            ModuleRequestV1.from_dict(valid_request_payload())
        )

        self.assertEqual("YANDEX_DIRECT", direct_result.module.module_id)
        self.assertEqual("YANDEX_METRIKA", metrika_result.module.module_id)


class OpenAPIContractTests(unittest.TestCase):
    def test_openapi_publishes_the_same_request_and_result_contract(self) -> None:
        document = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))

        self.assertEqual("3.1.0", document["openapi"])
        schemas = document["components"]["schemas"]
        self.assertIn("ModuleRequestV1", schemas)
        self.assertIn("ModuleResultV1", schemas)
        request_example = document["paths"]["/v1/runs"]["post"]["requestBody"][
            "content"
        ]["application/json"]["example"]
        result_example = document["paths"]["/v1/runs"]["post"]["responses"]["200"][
            "content"
        ]["application/json"]["example"]

        ModuleRequestV1.from_dict(request_example)
        ModuleResultV1.from_dict(result_example)


if __name__ == "__main__":
    unittest.main()
