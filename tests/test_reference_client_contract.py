from __future__ import annotations

import ast
import copy
import json
import subprocess
import unittest
from pathlib import Path
from urllib import error

from examples.reference_client.client import (
    ModuleHttpClientV1,
    ModuleResultEnvelopeV1,
    ModuleTransportError,
)
from examples.reference_client.requests import (
    direct_customer_evidence,
    direct_execute_proposal,
    direct_plan_intent,
    direct_provider_read,
    invalid_direct_customer_evidence,
    metrika_provider_read,
)
from mox_adv.module_api.v1 import (
    ContractValidationError,
    ModuleRequestV1,
    ModuleResultV1,
)
from scripts.check_module_openapi_compatibility import (
    backward_incompatibilities,
)

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "openapi" / "module-api-v1.openapi.json"
CLIENT_ROOT = ROOT / "examples" / "reference_client"


class _LostResponseClient(ModuleHttpClientV1):
    def __init__(self) -> None:
        super().__init__(
            endpoint="http://127.0.0.1:1/v1/runs",
            request_schema_version="module-request-v1",
            result_schema_version="module-result-v1",
            max_attempts=3,
        )
        self.attempts = 0

    def _post(self, encoded: bytes) -> tuple[int, bytes]:
        del encoded
        self.attempts += 1
        raise error.URLError("response was lost")


class ReferenceClientContractTests(unittest.TestCase):
    def test_result_parser_validates_every_public_envelope_section(self) -> None:
        document = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
        example = document["paths"]["/v1/runs"]["post"]["responses"]["200"][
            "content"
        ]["application/json"]["example"]
        malformed_values = {
            "metrics": {},
            "assessment": [],
            "recommendations": {},
            "provenance": {},
            "warnings": {},
            "proposal": [],
            "execution_result": [],
            "decision_record_ref": 42,
        }

        for field, malformed in malformed_values.items():
            with self.subTest(field=field):
                payload = copy.deepcopy(example)
                payload[field] = malformed
                with self.assertRaises(ModuleTransportError):
                    ModuleResultEnvelopeV1.from_dict(
                        payload,
                        expected_schema_version="module-result-v1",
                    )

    def test_client_never_blindly_retries_an_execute_after_lost_response(
        self,
    ) -> None:
        client = _LostResponseClient()
        payload = direct_execute_proposal(
            proposal_id="proposal-reference-1",
            environment="TEST",
        )

        with self.assertRaises(ModuleTransportError):
            client.invoke(payload)

        self.assertEqual(1, client.attempts)

    def test_generated_requests_and_published_examples_remain_valid(self) -> None:
        generated = (
            metrika_provider_read(),
            direct_provider_read(),
            direct_customer_evidence(),
            direct_plan_intent(environment="PRODUCTION"),
            direct_plan_intent(environment="TEST"),
            direct_execute_proposal(
                proposal_id="proposal-reference-1",
                environment="PRODUCTION",
            ),
            direct_execute_proposal(
                proposal_id="proposal-reference-1",
                environment="TEST",
            ),
        )
        for payload in generated:
            with self.subTest(idempotency_key=payload["idempotency_key"]):
                ModuleRequestV1.from_dict(payload)

        with self.assertRaises(ContractValidationError):
            ModuleRequestV1.from_dict(invalid_direct_customer_evidence())

        document = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
        operation = document["paths"]["/v1/runs"]["post"]
        request_example = operation["requestBody"]["content"][
            "application/json"
        ]["example"]
        result_example = operation["responses"]["200"]["content"][
            "application/json"
        ]["example"]
        ModuleRequestV1.from_dict(request_example)
        ModuleResultV1.from_dict(result_example)
        self.assertEqual(
            {"$ref": "#/components/responses/IdempotencyConflict"},
            operation["responses"]["409"],
        )

    def test_compatibility_checker_allows_additions_and_rejects_breaking_v1(
        self,
    ) -> None:
        baseline = json.loads(
            subprocess.run(
                [
                    "git",
                    "show",
                    "0d8ea21:openapi/module-api-v1.openapi.json",
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        current = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
        self.assertEqual([], backward_incompatibilities(baseline, current))

        additive = copy.deepcopy(baseline)
        additive["components"]["schemas"]["ModuleResultV1"]["properties"][
            "optional_future_field"
        ] = {"type": "string"}

        self.assertEqual([], backward_incompatibilities(baseline, additive))

        breaking = copy.deepcopy(additive)
        breaking["components"]["schemas"]["ModuleRequestV1"]["required"].append(
            "future_required_field"
        )
        findings = backward_incompatibilities(baseline, breaking)
        self.assertTrue(
            any(
                "new required request field" in finding
                for finding in findings
            ),
            findings,
        )

        missing_request = copy.deepcopy(baseline)
        del missing_request["paths"]["/v1/runs"]["post"]["requestBody"]
        self.assertTrue(
            any(
                "requestBody" in finding
                for finding in backward_incompatibilities(
                    baseline,
                    missing_request,
                )
            )
        )

        changed_response = copy.deepcopy(baseline)
        changed_response["paths"]["/v1/runs"]["post"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"] = {"type": "string"}
        self.assertTrue(
            any(
                "responses.200" in finding
                for finding in backward_incompatibilities(
                    baseline,
                    changed_response,
                )
            )
        )

        widened_status = copy.deepcopy(baseline)
        widened_status["components"]["schemas"]["ModuleResultV1"][
            "properties"
        ]["status"]["enum"].append("FUTURE_STATUS")
        self.assertTrue(
            any(
                "enum" in finding
                for finding in backward_incompatibilities(
                    baseline,
                    widened_status,
                )
            )
        )

        relaxed_result = copy.deepcopy(baseline)
        relaxed_result["components"]["schemas"]["ModuleResultV1"][
            "required"
        ].remove("status")
        self.assertTrue(
            any(
                "removed required response field" in finding
                for finding in backward_incompatibilities(
                    baseline,
                    relaxed_result,
                )
            )
        )

        relaxed_request = copy.deepcopy(baseline)
        relaxed_request["components"]["schemas"]["ModuleRequestV1"][
            "required"
        ].remove("operation")
        self.assertEqual(
            [],
            backward_incompatibilities(baseline, relaxed_request),
        )

        stronger_result = copy.deepcopy(baseline)
        stronger_result["components"]["schemas"]["ModuleResultV1"][
            "required"
        ].append("decision_record_ref")
        self.assertEqual(
            [],
            backward_incompatibilities(baseline, stronger_result),
        )

        relaxed_response_bound = copy.deepcopy(baseline)
        relaxed_response_bound["components"]["schemas"][
            "ModuleIdentityV1"
        ]["properties"]["module_version"]["minLength"] = 0
        self.assertTrue(
            any(
                "relaxed response minLength" in finding
                for finding in backward_incompatibilities(
                    baseline,
                    relaxed_response_bound,
                )
            )
        )

        relaxed_request_bound = copy.deepcopy(baseline)
        relaxed_request_bound["components"]["schemas"]["ModuleRequestV1"][
            "properties"
        ]["idempotency_key"]["minLength"] = 0
        self.assertEqual(
            [],
            backward_incompatibilities(
                baseline,
                relaxed_request_bound,
            ),
        )

    def test_reference_client_has_no_provider_or_dashboard_imports(self) -> None:
        forbidden = {
            "mox_adv",
            "playwright",
            "requests",
        }
        for path in CLIENT_ROOT.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = {
                node.names[0].name.split(".", 1)[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
            }
            imports.update(
                node.module.split(".", 1)[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module
            )
            with self.subTest(path=path.name):
                self.assertTrue(forbidden.isdisjoint(imports), imports)


if __name__ == "__main__":
    unittest.main()
