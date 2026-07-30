#!/usr/bin/env python3
"""Check that a module API OpenAPI document remains backward-compatible."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, List, Mapping, Sequence


def backward_incompatibilities(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> List[str]:
    """Return deterministic compatibility findings for existing v1 consumers."""

    findings: List[str] = []
    _compare_major_version(baseline, candidate, findings)
    _compare_paths(baseline, candidate, findings)
    baseline_schemas = _mapping_at(
        baseline,
        ("components", "schemas"),
        findings,
        "baseline",
    )
    candidate_schemas = _mapping_at(
        candidate,
        ("components", "schemas"),
        findings,
        "candidate",
    )
    for name, baseline_schema in baseline_schemas.items():
        if name not in candidate_schemas:
            findings.append("removed schema: components.schemas." + name)
            continue
        _compare_schema(
            baseline_schema,
            candidate_schemas[name],
            "components.schemas." + name,
            findings,
        )
    return sorted(set(findings))


def _compare_major_version(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    findings: List[str],
) -> None:
    for field in ("openapi",):
        old = baseline.get(field)
        new = candidate.get(field)
        if _major(old) != _major(new):
            findings.append(field + " major version changed")
    old_info = baseline.get("info")
    new_info = candidate.get("info")
    old_api = old_info.get("version") if isinstance(old_info, Mapping) else None
    new_api = new_info.get("version") if isinstance(new_info, Mapping) else None
    if _major(old_api) != _major(new_api):
        findings.append("info.version major version changed")


def _compare_paths(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    findings: List[str],
) -> None:
    baseline_paths = baseline.get("paths")
    candidate_paths = candidate.get("paths")
    if not isinstance(baseline_paths, Mapping):
        findings.append("baseline paths is not an object")
        return
    if not isinstance(candidate_paths, Mapping):
        findings.append("candidate paths is not an object")
        return
    for route, baseline_path in baseline_paths.items():
        candidate_path = candidate_paths.get(route)
        if not isinstance(candidate_path, Mapping):
            findings.append("removed path: " + str(route))
            continue
        if not isinstance(baseline_path, Mapping):
            continue
        for method, baseline_operation in baseline_path.items():
            if method not in {
                "get",
                "put",
                "post",
                "delete",
                "options",
                "head",
                "patch",
                "trace",
            }:
                continue
            candidate_operation = candidate_path.get(method)
            location = "paths." + str(route) + "." + method
            if not isinstance(candidate_operation, Mapping):
                findings.append("removed operation: " + location)
                continue
            if isinstance(baseline_operation, Mapping):
                old_id = baseline_operation.get("operationId")
                new_id = candidate_operation.get("operationId")
                if old_id != new_id:
                    findings.append("changed operationId: " + location)
                _compare_responses(
                    baseline_operation,
                    candidate_operation,
                    location,
                    findings,
                )


def _compare_responses(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    location: str,
    findings: List[str],
) -> None:
    old_responses = baseline.get("responses")
    new_responses = candidate.get("responses")
    if not isinstance(old_responses, Mapping):
        return
    if not isinstance(new_responses, Mapping):
        findings.append("removed responses: " + location)
        return
    for status_code in old_responses:
        if status_code not in new_responses:
            findings.append(
                "removed response " + str(status_code) + ": " + location
            )


def _compare_schema(
    baseline: Any,
    candidate: Any,
    location: str,
    findings: List[str],
) -> None:
    if not isinstance(baseline, Mapping):
        if baseline != candidate:
            findings.append("changed schema value: " + location)
        return
    if not isinstance(candidate, Mapping):
        findings.append("schema is no longer an object: " + location)
        return

    for exact_field in ("$ref", "const", "type", "pattern"):
        if (
            exact_field in baseline
            and candidate.get(exact_field) != baseline[exact_field]
        ):
            findings.append(
                "changed " + exact_field + ": " + location
            )

    old_enum = baseline.get("enum")
    new_enum = candidate.get("enum")
    if isinstance(old_enum, list):
        if not isinstance(new_enum, list) or not set(old_enum).issubset(new_enum):
            findings.append("removed enum value: " + location)

    old_required = baseline.get("required", [])
    new_required = candidate.get("required", [])
    if isinstance(old_required, list) and isinstance(new_required, list):
        added_required = sorted(set(new_required) - set(old_required))
        for field in added_required:
            findings.append(
                "new required field " + str(field) + ": " + location
            )

    _compare_bounds(baseline, candidate, location, findings)
    _compare_properties(baseline, candidate, location, findings)
    _compare_items(baseline, candidate, location, findings)
    for branch_name in ("oneOf", "anyOf", "allOf"):
        _compare_branches(
            baseline,
            candidate,
            branch_name,
            location,
            findings,
        )


def _compare_bounds(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    location: str,
    findings: List[str],
) -> None:
    for field in ("minimum", "minLength", "minItems"):
        old = baseline.get(field)
        new = candidate.get(field)
        if isinstance(new, (int, float)) and (
            not isinstance(old, (int, float)) or new > old
        ):
            findings.append("tightened " + field + ": " + location)
    for field in ("maximum", "maxLength", "maxItems"):
        old = baseline.get(field)
        new = candidate.get(field)
        if isinstance(new, (int, float)) and (
            not isinstance(old, (int, float)) or new < old
        ):
            findings.append("tightened " + field + ": " + location)
    if baseline.get("additionalProperties", True) is not False and (
        candidate.get("additionalProperties") is False
    ):
        findings.append("closed additionalProperties: " + location)


def _compare_properties(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    location: str,
    findings: List[str],
) -> None:
    old_properties = baseline.get("properties")
    new_properties = candidate.get("properties")
    if not isinstance(old_properties, Mapping):
        return
    if not isinstance(new_properties, Mapping):
        findings.append("removed properties: " + location)
        return
    for name, schema in old_properties.items():
        if name not in new_properties:
            findings.append("removed property " + str(name) + ": " + location)
            continue
        _compare_schema(
            schema,
            new_properties[name],
            location + ".properties." + str(name),
            findings,
        )


def _compare_items(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    location: str,
    findings: List[str],
) -> None:
    if "items" in baseline:
        _compare_schema(
            baseline["items"],
            candidate.get("items"),
            location + ".items",
            findings,
        )


def _compare_branches(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    branch_name: str,
    location: str,
    findings: List[str],
) -> None:
    old_branches = baseline.get(branch_name)
    if not isinstance(old_branches, list):
        return
    new_branches = candidate.get(branch_name)
    if not isinstance(new_branches, list) or len(new_branches) < len(
        old_branches
    ):
        findings.append("removed " + branch_name + " branch: " + location)
        return
    for index, old_branch in enumerate(old_branches):
        _compare_schema(
            old_branch,
            new_branches[index],
            location + "." + branch_name + "[" + str(index) + "]",
            findings,
        )


def _mapping_at(
    document: Mapping[str, Any],
    path: Sequence[str],
    findings: List[str],
    label: str,
) -> Mapping[str, Any]:
    value: Any = document
    for part in path:
        if not isinstance(value, Mapping) or part not in value:
            findings.append(label + " missing " + ".".join(path))
            return {}
        value = value[part]
    if not isinstance(value, Mapping):
        findings.append(label + " " + ".".join(path) + " is not an object")
        return {}
    return value


def _major(value: Any) -> Any:
    if not isinstance(value, str):
        return None
    return value.split(".", 1)[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    arguments = parser.parse_args()
    baseline = json.loads(arguments.baseline.read_text(encoding="utf-8"))
    candidate = json.loads(arguments.candidate.read_text(encoding="utf-8"))
    findings = backward_incompatibilities(baseline, candidate)
    if findings:
        for finding in findings:
            print(finding)
        return 1
    print("OpenAPI compatibility: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
