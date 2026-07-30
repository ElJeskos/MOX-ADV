"""Run the customer-owned reference flow against two standalone endpoints."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from examples.reference_client.client import ModuleHttpClientV1
from examples.reference_client.requests import (
    direct_customer_evidence,
    direct_execute_proposal,
    direct_plan_intent,
    direct_provider_read,
    invalid_direct_customer_evidence,
    metrika_provider_read,
)


def run(
    *,
    openapi_document: Dict[str, Any],
    metrika_url: str,
    direct_url: str,
    environment: str,
    execute_approved_test_proposal: bool,
) -> Dict[str, Any]:
    """Return the versioned envelopes produced by the reference flow."""

    if execute_approved_test_proposal and environment != "TEST":
        raise ValueError(
            "An approved proposal can be executed only in the TEST environment."
        )
    metrika = ModuleHttpClientV1.from_openapi(
        base_url=metrika_url,
        document=openapi_document,
    )
    direct = ModuleHttpClientV1.from_openapi(
        base_url=direct_url,
        document=openapi_document,
    )
    results = {
        "metrika_provider_read": metrika.invoke(
            metrika_provider_read()
        ).body,
        "direct_provider_read": direct.invoke(direct_provider_read()).body,
        "direct_customer_evidence": direct.invoke(
            direct_customer_evidence()
        ).body,
        "direct_validation_error": direct.invoke(
            invalid_direct_customer_evidence()
        ).body,
    }
    planned = direct.invoke(direct_plan_intent(environment=environment))
    results["direct_plan"] = planned.body
    if execute_approved_test_proposal:
        proposal = planned.body.get("proposal")
        if not isinstance(proposal, dict) or not isinstance(
            proposal.get("proposal_id"),
            str,
        ):
            raise RuntimeError("Direct did not return an executable proposal.")
        results["direct_execution"] = direct.invoke(
            direct_execute_proposal(
                proposal_id=proposal["proposal_id"],
                environment="TEST",
            )
        ).body
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Call standalone Metrika and Direct over HTTP/JSON.",
    )
    parser.add_argument("--openapi", required=True, type=Path)
    parser.add_argument("--metrika-url", required=True)
    parser.add_argument("--direct-url", required=True)
    parser.add_argument(
        "--environment",
        choices=("PRODUCTION", "TEST"),
        default="PRODUCTION",
    )
    parser.add_argument(
        "--execute-approved-test-proposal",
        action="store_true",
        help=(
            "Execute the returned proposal only after trusted TEST approval "
            "has been granted server-side."
        ),
    )
    arguments = parser.parse_args()
    document = json.loads(arguments.openapi.read_text(encoding="utf-8"))
    results = run(
        openapi_document=document,
        metrika_url=arguments.metrika_url,
        direct_url=arguments.direct_url,
        environment=arguments.environment,
        execute_approved_test_proposal=(
            arguments.execute_approved_test_proposal
        ),
    )
    print(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
