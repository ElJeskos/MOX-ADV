from __future__ import annotations

import ast
import copy
import json
import unittest
from pathlib import Path

from examples.reference_client.requests import (
    direct_customer_evidence,
    direct_execute_proposal,
    direct_plan_intent,
    direct_provider_read,
    metrika_provider_read,
)
from mox_adv.module_api.v1 import ModuleRequestV1, ModuleResultV1
from scripts.check_module_openapi_compatibility import (
    backward_incompatibilities,
)

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "openapi" / "module-api-v1.openapi.json"
CLIENT_ROOT = ROOT / "examples" / "reference_client"


class ReferenceClientContractTests(unittest.TestCase):
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
        baseline = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
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
            any("new required field" in finding for finding in findings),
            findings,
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
