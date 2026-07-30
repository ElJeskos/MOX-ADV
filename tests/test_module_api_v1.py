from __future__ import annotations

import json
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from mox_adv.environment import ExecutionEnvironment
from mox_adv.module_api.v1 import (
    OPERATION_TYPES_BY_KIND,
    ContractValidationError,
    HttpJsonModuleAdapterV1,
    InProcessModuleAdapterV1,
    ModuleExecutionResultV1,
    ModuleHypothesisV1,
    ModuleIdentityV1,
    ModuleOperationV1,
    ModuleProposalV1,
    ModuleRequestV1,
    ModuleResultV1,
)
from mox_adv.modules.direct import DirectModuleV1
from mox_adv.modules.metrika import MetrikaModuleV1

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

    def test_operation_constructor_rejects_an_invalid_kind_type_pair(self) -> None:
        with self.assertRaisesRegex(
            ContractValidationError,
            "operation.operation_type must be one of",
        ):
            ModuleOperationV1(
                kind="ANALYZE",
                operation_type="CREATE_CAMPAIGN",
            )

    def test_direct_action_rejects_raw_provider_authority(self) -> None:
        payload = valid_request_payload()
        payload["operation"] = {
            "kind": "EXECUTE",
            "operation_type": "APPLY_OPTIMIZATION",
        }
        payload["direct_action_command"] = {
            "schema_version": "direct-action-command-v1",
            "command": "EXECUTE_PROPOSAL",
            "proposal_id": "proposal-17",
            "endpoint": "https://api.direct.yandex.com/json/v501/campaigns",
        }
        with self.assertRaisesRegex(
            ContractValidationError,
            "unexpected field",
        ):
            ModuleRequestV1.from_dict(payload)

        command = payload["direct_action_command"]
        assert isinstance(command, dict)
        command.pop("endpoint")
        command["proposal_id"] = "POST /campaigns with caller payload"
        with self.assertRaisesRegex(
            ContractValidationError,
            "proposal_id is invalid",
        ):
            ModuleRequestV1.from_dict(payload)

    def test_closed_wire_values_fail_closed_on_direct_construction(self) -> None:
        request = ModuleRequestV1.from_dict(valid_request_payload())
        result = ModuleResultV1.from_dict(successful_result_payload())
        assert request.external_evidence is not None
        assert result.assessment is not None
        invalid_constructors = {
            "environment": lambda: replace(request, environment="STAGING"),
            "evidence_source": lambda: replace(
                request.external_evidence,
                source="UNTRUSTED",
            ),
            "module_id": lambda: ModuleIdentityV1(
                module_id="UNKNOWN",
                module_version="1.0.0",
            ),
            "assessment": lambda: replace(
                result.assessment,
                data_quality_status="UNKNOWN",
            ),
            "proposal": lambda: ModuleProposalV1(
                proposal_id="proposal-1",
                operation_type="PLAN_OPTIMIZATION",
                status="UNKNOWN",
            ),
            "execution": lambda: ModuleExecutionResultV1(
                execution_id="execution-1",
                operation_type="APPLY_OPTIMIZATION",
                status="UNKNOWN",
                applied=False,
            ),
            "provenance": lambda: replace(
                result.provenance[0],
                source_type="UNKNOWN",
            ),
            "result_status": lambda: replace(
                result,
                status="UNKNOWN",  # type: ignore[arg-type]
            ),
        }
        for field, construct in invalid_constructors.items():
            with self.subTest(field=field):
                with self.assertRaisesRegex(
                    ContractValidationError,
                    "must be one of",
                ):
                    construct()

    def test_result_limits_hypotheses_and_requires_metric_evidence(self) -> None:
        result = ModuleResultV1.from_dict(successful_result_payload())
        hypothesis = ModuleHypothesisV1(
            code="LOW_CTR",
            summary="The current ad may not match the search intent.",
            evidence_metric_names=("ctr_percent", "impressions"),
        )

        with self.assertRaisesRegex(
            ContractValidationError,
            "at most three hypotheses",
        ):
            replace(
                result,
                hypotheses=(hypothesis, hypothesis, hypothesis, hypothesis),
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "unknown metric",
        ):
            replace(
                result,
                hypotheses=(
                    replace(
                        hypothesis,
                        evidence_metric_names=("missing_metric",),
                    ),
                ),
            )

    def test_production_execution_intent_remains_representable_for_policy_guard(
        self,
    ) -> None:
        payload = valid_request_payload()
        operation = payload["operation"]
        assert isinstance(operation, dict)
        operation.update(
            kind="EXECUTE",
            operation_type="APPLY_OPTIMIZATION",
        )

        request = ModuleRequestV1.from_dict(payload)

        self.assertEqual("PRODUCTION", request.environment)
        self.assertEqual("EXECUTE", request.operation.kind)


class ModuleAdapterContractTests(unittest.TestCase):
    def test_http_and_in_process_adapters_invoke_the_same_module_contract(self) -> None:
        request_payload = valid_request_payload()
        request = ModuleRequestV1.from_dict(request_payload)
        module = RecordingModule("YANDEX_METRIKA")

        in_process_result = InProcessModuleAdapterV1(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        ).invoke(request)
        http_response = HttpJsonModuleAdapterV1(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request_payload)

        self.assertEqual(200, http_response.status_code)
        self.assertEqual(in_process_result.as_dict(), http_response.body)
        self.assertEqual([request, request], module.requests)

    def test_invalid_http_request_returns_typed_module_result(self) -> None:
        module = RecordingModule("YANDEX_DIRECT")
        payload = valid_request_payload()
        payload["oauth_token"] = "must-not-cross-the-boundary"

        response = HttpJsonModuleAdapterV1(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(payload)

        self.assertEqual(400, response.status_code)
        self.assertEqual("module-result-v1", response.body["schema_version"])
        self.assertEqual("REJECTED", response.body["status"])
        self.assertEqual(
            "CONTRACT_VALIDATION_FAILED",
            response.body["errors"][0]["code"],
        )
        self.assertEqual([], module.requests)
        self.assertNotIn("must-not-cross-the-boundary", json.dumps(response.body))

    def test_direct_and_metrika_modules_need_no_cross_provider_configuration(
        self,
    ) -> None:
        direct = DirectModuleV1(RecordingModule("YANDEX_DIRECT").invoke)
        metrika = MetrikaModuleV1(RecordingModule("YANDEX_METRIKA").invoke)

        direct_result = InProcessModuleAdapterV1(
            direct,
            environment=ExecutionEnvironment.PRODUCTION,
        ).invoke(ModuleRequestV1.from_dict(valid_request_payload()))
        metrika_result = InProcessModuleAdapterV1(
            metrika,
            environment=ExecutionEnvironment.PRODUCTION,
        ).invoke(ModuleRequestV1.from_dict(valid_request_payload()))

        self.assertEqual("YANDEX_DIRECT", direct_result.module.module_id)
        self.assertEqual("YANDEX_METRIKA", metrika_result.module.module_id)

    def test_each_provider_composition_root_imports_without_the_other(self) -> None:
        for provider, absent_provider in (
            ("direct", "metrika"),
            ("metrika", "direct"),
        ):
            with self.subTest(provider=provider):
                script = (
                    "import sys; "
                    f"import mox_adv.modules.{provider}; "
                    f"assert 'mox_adv.modules.{absent_provider}' not in sys.modules"
                )
                completed = subprocess.run(
                    [sys.executable, "-c", script],
                    check=False,
                    capture_output=True,
                    env={"PYTHONPATH": str(ROOT / "src")},
                    text=True,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)


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

    def test_openapi_operation_pairs_match_the_python_contract(self) -> None:
        document = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
        operation_schema = document["components"]["schemas"]["ModuleOperationV1"]
        openapi_pairs = {
            branch["properties"]["kind"]["const"]: tuple(
                branch["properties"]["operation_type"]["enum"]
            )
            for branch in operation_schema["oneOf"]
        }

        self.assertEqual(OPERATION_TYPES_BY_KIND, openapi_pairs)

    def test_openapi_publishes_the_bounded_hypothesis_contract(self) -> None:
        document = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
        schemas = document["components"]["schemas"]

        self.assertEqual(
            3,
            schemas["ModuleResultV1"]["properties"]["hypotheses"]["maxItems"],
        )
        self.assertEqual(
            1,
            schemas["ModuleHypothesisV1"]["properties"]["evidence_metric_names"][
                "minItems"
            ],
        )
        self.assertIn(
            "hypotheses",
            schemas["ModuleResultV1"]["required"],
        )

    def test_openapi_publishes_the_typed_goal_lifecycle_contract(self) -> None:
        document = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
        schemas = document["components"]["schemas"]
        request_properties = schemas["ModuleRequestV1"]["properties"]
        result_properties = schemas["ModuleResultV1"]["properties"]
        actions = {
            branch["properties"]["action"]["const"]
            for branch in schemas["GoalLifecycleCommandV1"]["oneOf"]
        }

        self.assertEqual(
            {
                "$ref": "#/components/schemas/GoalLifecycleCommandV1",
            },
            request_properties["goal_lifecycle_command"],
        )
        self.assertEqual(
            {
                "$ref": "#/components/schemas/GoalLifecycleOutcomeV1",
            },
            result_properties["lifecycle_outcome"],
        )
        self.assertEqual(
            {
                "CREATE_CANDIDATE",
                "PUBLISH_EVENT",
                "VERIFY_DELIVERY",
                "DECIDE_BUSINESS_SEMANTICS",
                "EVALUATE_OPTIMIZATION_ELIGIBILITY",
                "CLEANUP_REJECTED_CANDIDATE",
            },
            actions,
        )
        self.assertEqual(
            "^[0-9a-f]{64}$",
            schemas["GoalLifecycleOutcomeV1"]["properties"]["evidence_digest"][
                "pattern"
            ],
        )
        self.assertEqual(
            "goal-candidate-input-v1",
            schemas["GoalCandidateInputV1"]["properties"]["schema_version"]["const"],
        )
        for field in (
            "run_id",
            "proposal_id",
            "reservation_id",
            "authority_id",
            "candidate_id",
        ):
            identifier_schema = schemas["GoalLifecycleCommandV1"]["properties"][field]
            self.assertEqual(128, identifier_schema["maxLength"])
            self.assertEqual(
                "^[A-Za-z0-9][A-Za-z0-9._:-]*$",
                identifier_schema["pattern"],
            )
        self.assertEqual(
            2,
            len(schemas["ModuleRequestV1"]["allOf"]),
        )

    def test_openapi_publishes_the_closed_direct_action_contract(self) -> None:
        document = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
        schemas = document["components"]["schemas"]
        request_properties = schemas["ModuleRequestV1"]["properties"]
        command_schemas = {
            branch["$ref"].rsplit("/", 1)[-1]
            for branch in schemas["DirectActionCommandV1"]["oneOf"]
        }

        self.assertEqual(
            {"$ref": "#/components/schemas/DirectActionCommandV1"},
            request_properties["direct_action_command"],
        )
        self.assertEqual(
            {
                "PlanDirectActionCommandV1",
                "ExecuteDirectActionCommandV1",
            },
            command_schemas,
        )
        plan = schemas["PlanDirectActionCommandV1"]
        self.assertEqual(
            ["INCREASE_WEEKLY_BUDGET"],
            plan["properties"]["action"]["enum"],
        )
        self.assertEqual(
            10,
            plan["properties"]["relative_step_percent"]["maximum"],
        )
        self.assertFalse(plan["additionalProperties"])
        self.assertFalse(
            schemas["ExecuteDirectActionCommandV1"]["additionalProperties"]
        )

    def test_result_proposal_and_execution_are_optional_inputs(self) -> None:
        payload = successful_result_payload()
        payload.pop("proposal")
        payload.pop("execution_result")

        result = ModuleResultV1.from_dict(payload)

        self.assertIsNone(result.proposal)
        self.assertIsNone(result.execution_result)


if __name__ == "__main__":
    unittest.main()
