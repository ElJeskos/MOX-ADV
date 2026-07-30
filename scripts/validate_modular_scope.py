#!/usr/bin/env python3
"""Validate the normative MOX-ADV modular product-scope matrices."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List


REQUIRED_EDITIONS = {
    "METRIKA_STANDALONE",
    "DIRECT_STANDALONE",
    "DIRECT_METRIKA_PAIRED",
}
STANDALONE_EDITIONS = {
    "METRIKA_STANDALONE",
    "DIRECT_STANDALONE",
}
REQUIRED_CAPABILITIES = {
    "CAMPAIGN_LIFECYCLE",
    "GOAL_LIFECYCLE",
    "SOURCE_INTEGRATION",
    "INTEGRATED_ANALYTICS",
    "LLM_ANALYSIS",
    "APPROVAL_REQUIRED",
    "BOUNDED_AUTONOMY",
    "MONITORING_AND_ALERTING",
    "IMPACT_EVALUATION",
    "OPERATIONAL_MODES",
    "TOOL_CONTRACT",
    "ORIGINAL_INTEGRATION_COVERAGE",
    "SAFETY_CORE",
    "CLOSED_LOOP_CONTROL",
}
REQUIRED_ACCEPTANCE_CASES = {
    "AS-001",
    "AS-002",
    "AS-003",
    "AS-004",
    "AS-005",
    "AS-006",
    "AS-007",
    "AS-008",
}
ALLOWED_EVIDENCE_TYPES = {
    "LOCAL_CONTRACT",
    "TEST_COUNTER",
    "REAL_READ_ONLY",
    "SIMULATED",
    "TEST_CONTOUR",
    "DASHBOARD_REGRESSION",
}


def _plain(value: str) -> str:
    return value.strip().strip("`")


def _table(
    text: str,
    heading: str,
    errors: List[str],
) -> List[Dict[str, str]]:
    lines = text.splitlines()
    marker = f"## {heading}"
    try:
        heading_index = lines.index(marker)
    except ValueError:
        errors.append(f"missing section: {heading}")
        return []

    table_start = None
    for index in range(heading_index + 1, len(lines)):
        line = lines[index]
        if line.startswith("## "):
            break
        if line.startswith("|"):
            table_start = index
            break
    if table_start is None or table_start + 1 >= len(lines):
        errors.append(f"missing table: {heading}")
        return []

    def cells(line: str) -> List[str]:
        return [item.strip() for item in line.strip().strip("|").split("|")]

    headers = cells(lines[table_start])
    separator = cells(lines[table_start + 1])
    if len(separator) != len(headers) or any(
        not value or set(value) - {"-", ":", " "}
        for value in separator
    ):
        errors.append(f"invalid table separator: {heading}")
        return []

    rows = []
    for line in lines[table_start + 2 :]:
        if not line.startswith("|"):
            break
        values = cells(line)
        if len(values) != len(headers):
            errors.append(f"invalid row width: {heading}")
            continue
        rows.append(dict(zip(headers, values)))
    return rows


def _validate_product_matrix(
    rows: List[Dict[str, str]],
    errors: List[str],
) -> None:
    by_id = {_plain(row.get("Edition ID", "")): row for row in rows}
    if set(by_id) != REQUIRED_EDITIONS:
        errors.append("product matrix: edition set mismatch")
        return

    for edition_id, row in by_id.items():
        if row.get("Production capability") != (
            "Read, analyze, and recommend only"
        ):
            errors.append(
                f"product matrix: invalid production capability for {edition_id}"
            )
        if edition_id in STANDALONE_EDITIONS:
            if row.get("UI") != "None (headless)":
                errors.append(
                    f"product matrix: standalone UI is forbidden for {edition_id}"
                )
            if row.get("Customer adapter") != "HTTP/JSON":
                errors.append(
                    f"product matrix: standalone adapter mismatch for {edition_id}"
                )
    paired = by_id["DIRECT_METRIKA_PAIRED"]
    if paired.get("Customer adapter") != "In-process":
        errors.append("product matrix: paired adapter must be in-process")
    if "http://127.0.0.1:8878" not in paired.get("UI", ""):
        errors.append("product matrix: paired Dashboard URL is not preserved")


def _validate_integration_matrix(
    rows: List[Dict[str, str]],
    errors: List[str],
) -> None:
    by_consumer = {_plain(row.get("Consumer", "")): row for row in rows}
    expected = {
        "CUSTOMER_ECOSYSTEM": "HTTP/JSON",
        "PAIRED_RUNTIME": "In-process",
    }
    if set(by_consumer) != set(expected):
        errors.append("integration contract matrix: consumer set mismatch")
        return
    for consumer, adapter in expected.items():
        row = by_consumer[consumer]
        if row.get("Adapter") != adapter:
            errors.append(
                f"integration contract matrix: adapter mismatch for {consumer}"
            )
        if row.get("Request") != "`ModuleRequestV1`":
            errors.append(
                f"integration contract matrix: request mismatch for {consumer}"
            )
        if row.get("Result") != "`ModuleResultV1`":
            errors.append(
                f"integration contract matrix: result mismatch for {consumer}"
            )


def _validate_environment_matrix(
    rows: List[Dict[str, str]],
    errors: List[str],
) -> None:
    expected_profiles = {
        "DIRECT_PROD_READ": ("PRODUCTION", "Read only"),
        "METRIKA_PROD_READ": ("PRODUCTION", "Read only"),
        "DIRECT_TEST_WRITE": ("TEST", "Read and write"),
        "METRIKA_TEST_WRITE": ("TEST", "Read and write"),
        "TEST_SITE_PUBLISH": ("TEST", "Write"),
    }
    by_profile = {_plain(row.get("Credential profile", "")): row for row in rows}
    if set(by_profile) != set(expected_profiles):
        errors.append("environment matrix: credential profile set mismatch")
        return
    for profile, (environment, access) in expected_profiles.items():
        row = by_profile[profile]
        if _plain(row.get("Environment", "")) != environment:
            errors.append(f"environment matrix: environment mismatch for {profile}")
        if row.get("Access") != access:
            errors.append(f"environment matrix: access mismatch for {profile}")
        if environment == "PRODUCTION" and "write" in access.lower():
            errors.append(
                f"environment matrix: production write profile forbidden: {profile}"
            )


def _validate_gate_matrix(
    rows: List[Dict[str, str]],
    errors: List[str],
) -> None:
    by_gate = {_plain(row.get("Gate", "")): row for row in rows}
    expected_gates = {"GATE_0", "GATE_1", "GATE_2", "GATE_3", "GATE_4"}
    if set(by_gate) != expected_gates:
        errors.append("gate matrix: gate set mismatch")
        return
    for gate, row in by_gate.items():
        if row.get("Production write allowed") != "No":
            errors.append(f"gate matrix: production write enabled at {gate}")
    if "test-contour" not in by_gate["GATE_4"].get("Exit evidence", "").lower():
        errors.append("gate matrix: Gate 4 must use test-contour evidence")


def _validate_capability_matrix(
    rows: List[Dict[str, str]],
    errors: List[str],
) -> None:
    by_capability = {
        _plain(row.get("Capability", "")): row
        for row in rows
    }
    if set(by_capability) != REQUIRED_CAPABILITIES:
        errors.append("capability matrix: capability set mismatch")
        return
    for capability, row in by_capability.items():
        editions = {
            _plain(value)
            for value in row.get("Applicable editions", "").split("+")
        }
        if not editions or not editions <= REQUIRED_EDITIONS:
            errors.append(
                f"capability matrix: invalid edition mapping for {capability}"
            )
        evidence = {
            _plain(value)
            for value in row.get("Required evidence", "").split("+")
        }
        if "CONTROLLED_PILOT" in evidence:
            errors.append(
                f"capability matrix: CONTROLLED_PILOT is forbidden for {capability}"
            )
        if not evidence or not evidence <= ALLOWED_EVIDENCE_TYPES:
            errors.append(
                f"capability matrix: invalid evidence for {capability}"
            )


def _validate_acceptance_matrix(
    rows: List[Dict[str, str]],
    errors: List[str],
) -> None:
    case_ids = {_plain(row.get("ID", "")) for row in rows}
    if case_ids != REQUIRED_ACCEPTANCE_CASES:
        errors.append("acceptance matrix: case set mismatch")
    if any(
        not row.get("Required evidence", "").strip()
        for row in rows
    ):
        errors.append("acceptance matrix: every case requires evidence")


def _validate_signoffs(
    rows: List[Dict[str, str]],
    errors: List[str],
) -> None:
    expected = {
        "CUSTOMER_REQUIREMENTS",
        "PRODUCT",
        "ARCHITECTURE",
        "SECURITY",
    }
    by_signoff = {_plain(row.get("Sign-off", "")): row for row in rows}
    if set(by_signoff) != expected:
        errors.append("sign-off matrix: sign-off set mismatch")
        return
    for signoff, row in by_signoff.items():
        if _plain(row.get("Status", "")) != "APPROVED":
            errors.append(f"sign-off matrix: {signoff} is not approved")
        if not row.get("Evidence", "").strip():
            errors.append(f"sign-off matrix: {signoff} has no evidence")


def validate_scope(
    scope_path: Path,
    source_authority_path: Path,
) -> List[str]:
    errors: List[str] = []
    if not scope_path.is_file():
        return [f"{scope_path}: scope document is missing"]
    if not source_authority_path.is_file():
        return [f"{source_authority_path}: source authority is missing"]

    text = scope_path.read_text(encoding="utf-8")
    authority = source_authority_path.read_text(encoding="utf-8")
    _validate_product_matrix(_table(text, "Product matrix", errors), errors)
    _validate_integration_matrix(
        _table(text, "Integration contract matrix", errors),
        errors,
    )
    _validate_environment_matrix(
        _table(text, "Environment and credential matrix", errors),
        errors,
    )
    _validate_gate_matrix(_table(text, "Gate matrix", errors), errors)
    _validate_capability_matrix(
        _table(text, "Capability and evidence matrix", errors),
        errors,
    )
    _validate_acceptance_matrix(
        _table(text, "Acceptance matrix", errors),
        errors,
    )
    _validate_signoffs(
        _table(text, "Required sign-offs", errors),
        errors,
    )
    if (
        "requirements-modularization-v1.md" not in authority
        or "takes precedence" not in authority
    ):
        errors.append(
            "source authority: modularization amendment precedence is missing"
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "scope",
        nargs="?",
        type=Path,
        default=Path("requirements-modularization-v1.md"),
    )
    parser.add_argument(
        "--source-authority",
        type=Path,
        default=Path("okf/project/source-authority.md"),
    )
    args = parser.parse_args()
    errors = validate_scope(args.scope, args.source_authority)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"Modular product scope is valid: {args.scope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
