#!/usr/bin/env python3
"""Validate the normative MOX-ADV modular product-scope matrices."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional


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
    "AUDITABILITY",
    "ORIGINAL_INTEGRATION_COVERAGE",
    "SAFETY_CORE",
    "CLOSED_LOOP_CONTROL",
}
EXPECTED_CAPABILITY_EDITIONS = {
    "CAMPAIGN_LIFECYCLE": {
        "DIRECT_STANDALONE",
        "DIRECT_METRIKA_PAIRED",
    },
    "GOAL_LIFECYCLE": {
        "METRIKA_STANDALONE",
        "DIRECT_METRIKA_PAIRED",
    },
    "SOURCE_INTEGRATION": {"DIRECT_METRIKA_PAIRED"},
    "INTEGRATED_ANALYTICS": {"DIRECT_METRIKA_PAIRED"},
    "LLM_ANALYSIS": REQUIRED_EDITIONS,
    "APPROVAL_REQUIRED": {
        "DIRECT_STANDALONE",
        "DIRECT_METRIKA_PAIRED",
    },
    "BOUNDED_AUTONOMY": {
        "DIRECT_STANDALONE",
        "DIRECT_METRIKA_PAIRED",
    },
    "MONITORING_AND_ALERTING": REQUIRED_EDITIONS,
    "IMPACT_EVALUATION": REQUIRED_EDITIONS,
    "OPERATIONAL_MODES": REQUIRED_EDITIONS,
    "TOOL_CONTRACT": REQUIRED_EDITIONS,
    "AUDITABILITY": REQUIRED_EDITIONS,
    "ORIGINAL_INTEGRATION_COVERAGE": {"DIRECT_METRIKA_PAIRED"},
    "SAFETY_CORE": REQUIRED_EDITIONS,
    "CLOSED_LOOP_CONTROL": {"DIRECT_METRIKA_PAIRED"},
}
EXPECTED_CAPABILITY_EVIDENCE = {
    "CAMPAIGN_LIFECYCLE": {"LOCAL_CONTRACT", "TEST_CONTOUR"},
    "GOAL_LIFECYCLE": {"TEST_COUNTER", "TEST_CONTOUR"},
    "SOURCE_INTEGRATION": {"REAL_READ_ONLY", "TEST_CONTOUR"},
    "INTEGRATED_ANALYTICS": {"REAL_READ_ONLY", "TEST_CONTOUR"},
    "LLM_ANALYSIS": {"SIMULATED", "REAL_READ_ONLY", "TEST_CONTOUR"},
    "APPROVAL_REQUIRED": {"SIMULATED", "TEST_CONTOUR"},
    "BOUNDED_AUTONOMY": {"SIMULATED", "TEST_CONTOUR"},
    "MONITORING_AND_ALERTING": {"SIMULATED", "REAL_READ_ONLY"},
    "IMPACT_EVALUATION": {"SIMULATED", "TEST_CONTOUR"},
    "OPERATIONAL_MODES": {"SIMULATED", "TEST_CONTOUR"},
    "TOOL_CONTRACT": {"SIMULATED", "LOCAL_CONTRACT"},
    "AUDITABILITY": {"SIMULATED", "TEST_CONTOUR"},
    "ORIGINAL_INTEGRATION_COVERAGE": {
        "LOCAL_CONTRACT",
        "TEST_COUNTER",
        "TEST_CONTOUR",
    },
    "SAFETY_CORE": {"SIMULATED", "LOCAL_CONTRACT", "TEST_CONTOUR"},
    "CLOSED_LOOP_CONTROL": {"TEST_CONTOUR", "DASHBOARD_REGRESSION"},
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


def _normalize_markdown_cell(value: str) -> str:
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
    by_id = {
        _normalize_markdown_cell(row.get("Edition ID", "")): row
        for row in rows
    }
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
    by_consumer = {
        _normalize_markdown_cell(row.get("Consumer", "")): row
        for row in rows
    }
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
    by_profile = {
        _normalize_markdown_cell(row.get("Credential profile", "")): row
        for row in rows
    }
    if set(by_profile) != set(expected_profiles):
        errors.append("environment matrix: credential profile set mismatch")
        return
    for profile, (environment, access) in expected_profiles.items():
        row = by_profile[profile]
        if _normalize_markdown_cell(
            row.get("Environment", "")
        ) != environment:
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
    by_gate = {
        _normalize_markdown_cell(row.get("Gate", "")): row
        for row in rows
    }
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
        _normalize_markdown_cell(row.get("Capability", "")): row
        for row in rows
    }
    if set(by_capability) != REQUIRED_CAPABILITIES:
        errors.append("capability matrix: capability set mismatch")
        return
    for capability, row in by_capability.items():
        editions = {
            _normalize_markdown_cell(value)
            for value in row.get("Applicable editions", "").split("+")
        }
        if editions != EXPECTED_CAPABILITY_EDITIONS[capability]:
            errors.append(
                f"capability matrix: edition mapping mismatch for {capability}"
            )
        evidence = {
            _normalize_markdown_cell(value)
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
        elif evidence != EXPECTED_CAPABILITY_EVIDENCE[capability]:
            errors.append(
                f"capability matrix: evidence mismatch for {capability}"
            )


def _validate_acceptance_matrix(
    rows: List[Dict[str, str]],
    errors: List[str],
) -> None:
    case_ids = {
        _normalize_markdown_cell(row.get("ID", ""))
        for row in rows
    }
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
    by_signoff = {
        _normalize_markdown_cell(row.get("Sign-off", "")): row
        for row in rows
    }
    if set(by_signoff) != expected:
        errors.append("sign-off matrix: sign-off set mismatch")
        return
    expected_statuses = {
        "CUSTOMER_REQUIREMENTS": "APPROVED",
        "PRODUCT": "PENDING",
        "ARCHITECTURE": "PENDING",
        "SECURITY": "PENDING",
    }
    for signoff, row in by_signoff.items():
        status = _normalize_markdown_cell(row.get("Status", ""))
        if status != expected_statuses[signoff]:
            errors.append(
                f"sign-off matrix: unexpected status for {signoff}"
            )
        expected_evidence = (
            f"`config/modularization-signoffs-v1.json#{signoff}`"
        )
        if row.get("Evidence") != expected_evidence:
            errors.append(
                f"sign-off matrix: invalid evidence reference for {signoff}"
            )


def _validate_signoff_artifact(
    scope_path: Path,
    signoff_path: Path,
    errors: List[str],
) -> None:
    if not signoff_path.is_file():
        errors.append(f"sign-off artifact is missing: {signoff_path}")
        return
    try:
        artifact = json.loads(signoff_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"sign-off artifact is invalid: {exc}")
        return
    if not isinstance(artifact, dict):
        errors.append("sign-off artifact must be an object")
        return
    expected_fields = {
        "schema_version",
        "scope_document",
        "scope_sha256",
        "recorded_at",
        "signoffs",
    }
    if set(artifact) != expected_fields:
        errors.append("sign-off artifact: field set mismatch")
        return
    expected_digest = hashlib.sha256(scope_path.read_bytes()).hexdigest()
    if artifact.get("scope_sha256") != expected_digest:
        errors.append("sign-off artifact: scope digest mismatch")
    if artifact.get("schema_version") != "modularization-signoffs-v1":
        errors.append("sign-off artifact: schema version mismatch")
    if artifact.get("scope_document") != "requirements-modularization-v1.md":
        errors.append("sign-off artifact: scope document mismatch")
    if not isinstance(artifact.get("recorded_at"), str):
        errors.append("sign-off artifact: recorded_at is required")

    raw_signoffs = artifact.get("signoffs")
    if not isinstance(raw_signoffs, list):
        errors.append("sign-off artifact: signoffs must be an array")
        return
    signoffs = {
        item.get("signoff"): item
        for item in raw_signoffs
        if isinstance(item, dict) and isinstance(item.get("signoff"), str)
    }
    expected_statuses = {
        "CUSTOMER_REQUIREMENTS": "APPROVED",
        "PRODUCT": "PENDING",
        "ARCHITECTURE": "PENDING",
        "SECURITY": "PENDING",
    }
    if set(signoffs) != set(expected_statuses):
        errors.append("sign-off artifact: sign-off set mismatch")
        return
    for signoff, expected_status in expected_statuses.items():
        item = signoffs[signoff]
        if item.get("status") != expected_status:
            errors.append(
                f"sign-off artifact: unexpected status for {signoff}"
            )
        if item.get("authority_role") not in {
            "PROJECT_OWNER",
            "PRODUCT_REVIEWER",
            "ARCHITECTURE_REVIEWER",
            "SECURITY_REVIEWER",
        }:
            errors.append(
                f"sign-off artifact: invalid authority role for {signoff}"
            )
        evidence = item.get("evidence")
        blocker = item.get("blocker")
        if expected_status == "APPROVED":
            if not isinstance(evidence, list) or not evidence:
                errors.append(
                    f"sign-off artifact: approved {signoff} needs evidence"
                )
            if blocker is not None:
                errors.append(
                    f"sign-off artifact: approved {signoff} has a blocker"
                )
        else:
            if evidence != []:
                errors.append(
                    f"sign-off artifact: pending {signoff} cannot claim evidence"
                )
            if not isinstance(blocker, str) or not blocker.strip():
                errors.append(
                    f"sign-off artifact: pending {signoff} needs a blocker"
                )


def validate_scope(
    scope_path: Path,
    source_authority_path: Path,
    signoff_path: Optional[Path] = None,
) -> List[str]:
    errors: List[str] = []
    if not scope_path.is_file():
        return [f"{scope_path}: scope document is missing"]
    if not source_authority_path.is_file():
        return [f"{source_authority_path}: source authority is missing"]
    if signoff_path is None:
        signoff_path = (
            scope_path.parent
            / "config"
            / "modularization-signoffs-v1.json"
        )

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
    _validate_signoff_artifact(scope_path, signoff_path, errors)
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
    parser.add_argument(
        "--signoffs",
        type=Path,
        default=Path("config/modularization-signoffs-v1.json"),
    )
    args = parser.parse_args()
    errors = validate_scope(
        args.scope,
        args.source_authority,
        args.signoffs,
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"Modular product scope is valid: {args.scope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
