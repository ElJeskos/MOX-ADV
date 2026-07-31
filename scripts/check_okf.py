#!/usr/bin/env python3
"""Validate Open Knowledge Format v0.2 bundles and optional local policies."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - exercised by dependency checks.
    yaml = None


DATE_HEADING_RE = re.compile(r"^## \d{4}-\d{2}-\d{2}$")
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
INDEX_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
ACTOR_RE = re.compile(r"^(?:human:\S+|process:\S+|[^\s/]+/[^\s/]+)$")
STATUS_VALUES = {"draft", "stable", "deprecated"}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("file must be valid UTF-8") from exc


def has_frontmatter(path: Path) -> bool:
    return read_text(path).startswith("---\n")


def parse_frontmatter(path: Path) -> dict[str, object]:
    if yaml is None:
        raise ValueError("PyYAML is required to parse OKF v0.2 frontmatter")

    text = read_text(path)
    if not text.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")

    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("unterminated YAML frontmatter")

    raw = text[4:end].strip()
    try:
        loaded = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError("YAML frontmatter must be a mapping")
    return loaded


def concept_body(path: Path) -> str:
    text = read_text(path)
    end = text.find("\n---\n", 4)
    return text[end + 5 :] if end != -1 else ""


def non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def valid_iso_datetime(value: object) -> bool:
    if isinstance(value, dt.datetime):
        return value.tzinfo is not None
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def normalized_date(value: object) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return None
    if isinstance(value, dt.date):
        return value
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def check_actor(path: Path, field: str, value: object) -> list[str]:
    if not non_empty_string(value) or ACTOR_RE.fullmatch(str(value)) is None:
        return [
            (
                f"{path}: {field} must use <producer>/<version>, human:<id>, "
                "or process:<id>"
            )
        ]
    return []


def check_date_window(path: Path, field: str, value: object) -> list[str]:
    if not isinstance(value, dict):
        return [f"{path}: {field} must be a mapping with from and to dates"]

    start = normalized_date(value.get("from"))
    end = normalized_date(value.get("to"))
    errors: list[str] = []
    if start is None:
        errors.append(f"{path}: {field}.from must be YYYY-MM-DD")
    if end is None:
        errors.append(f"{path}: {field}.to must be YYYY-MM-DD")
    if start is not None and end is not None and start > end:
        errors.append(f"{path}: {field}.from must not be after {field}.to")
    return errors


def check_optional_metadata(path: Path, data: dict[str, object]) -> list[str]:
    errors: list[str] = []
    for field in ("title", "description", "resource"):
        if field in data and not non_empty_string(data[field]):
            errors.append(f"{path}: optional {field} must be a non-empty string")

    if "tags" in data:
        tags = data["tags"]
        if (
            not isinstance(tags, list)
            or any(not non_empty_string(tag) for tag in tags)
        ):
            errors.append(f"{path}: optional tags must be a list of non-empty strings")
    return errors


def check_sources(path: Path, data: dict[str, object]) -> list[str]:
    if "sources" not in data:
        return []

    sources = data["sources"]
    if not isinstance(sources, list):
        return [f"{path}: sources must be a list"]

    errors: list[str] = []
    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        field = f"sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{path}: {field} must be a mapping")
            continue
        if not non_empty_string(source.get("resource")):
            errors.append(f"{path}: {field}.resource is required")

        for key in ("id", "title", "author"):
            if key in source and not non_empty_string(source[key]):
                errors.append(f"{path}: {field}.{key} must be a non-empty string")

        source_id = source.get("id")
        if isinstance(source_id, str):
            if source_id in source_ids:
                errors.append(f"{path}: duplicate sources id: {source_id}")
            source_ids.add(source_id)

        if "usage_count" in source:
            usage_count = source["usage_count"]
            if isinstance(usage_count, bool) or not isinstance(usage_count, int) or usage_count < 0:
                errors.append(f"{path}: {field}.usage_count must be a non-negative integer")
        if "last_modified" in source and normalized_date(source["last_modified"]) is None:
            errors.append(f"{path}: {field}.last_modified must be YYYY-MM-DD")
        if "usage_window" in source:
            errors.extend(check_date_window(path, f"{field}.usage_window", source["usage_window"]))

    if "usage_window" in data:
        errors.extend(check_date_window(path, "usage_window", data["usage_window"]))
    return errors


def check_generated(path: Path, data: dict[str, object]) -> list[str]:
    if "generated" not in data:
        return []

    generated = data["generated"]
    if not isinstance(generated, dict):
        return [f"{path}: generated must be a mapping"]

    errors = check_actor(path, "generated.by", generated.get("by"))
    if "at" in generated and not valid_iso_datetime(generated["at"]):
        errors.append(f"{path}: generated.at must be an ISO 8601 datetime with timezone")
    return errors


def verification_events(value: object) -> list[object] | None:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return value
    return None


def check_verified(path: Path, data: dict[str, object]) -> list[str]:
    if "verified" not in data:
        return []

    events = verification_events(data["verified"])
    if events is None or not events:
        return [f"{path}: verified must be a non-empty mapping or list of mappings"]

    errors: list[str] = []
    for index, event in enumerate(events):
        field = f"verified[{index}]"
        if not isinstance(event, dict):
            errors.append(f"{path}: {field} must be a mapping")
            continue
        errors.extend(check_actor(path, f"{field}.by", event.get("by")))
        if not valid_iso_datetime(event.get("at")):
            errors.append(f"{path}: {field}.at must be an ISO 8601 datetime with timezone")
    return errors


def check_lifecycle(path: Path, data: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if "status" in data and data["status"] not in STATUS_VALUES:
        values = ", ".join(sorted(STATUS_VALUES))
        errors.append(f"{path}: status must be one of {values}")
    if "stale_after" in data and normalized_date(data["stale_after"]) is None:
        errors.append(f"{path}: stale_after must be YYYY-MM-DD")
    return errors


def fenced_blocks(section: str) -> tuple[int, bool]:
    count = 0
    open_marker: str | None = None
    for line in section.splitlines():
        stripped = line.lstrip()
        marker = "```" if stripped.startswith("```") else "~~~" if stripped.startswith("~~~") else None
        if marker is None:
            continue
        if open_marker is None:
            open_marker = marker
            count += 1
        elif marker == open_marker:
            open_marker = None
    return count, open_marker is None


def computation_section(body: str) -> str | None:
    heading = re.search(r"^# Computation[ \t]*$", body, flags=re.MULTILINE)
    if heading is None:
        return None
    remainder = body[heading.end() :]
    next_heading = re.search(r"^# [^#]", remainder, flags=re.MULTILINE)
    return remainder[: next_heading.start()] if next_heading else remainder


def check_parameters(path: Path, value: object) -> list[str]:
    if not isinstance(value, list):
        return [f"{path}: parameters must be a list"]

    errors: list[str] = []
    names: set[str] = set()
    for index, parameter in enumerate(value):
        field = f"parameters[{index}]"
        if not isinstance(parameter, dict):
            errors.append(f"{path}: {field} must be a mapping")
            continue
        for key in ("name", "type"):
            if not non_empty_string(parameter.get(key)):
                errors.append(f"{path}: {field}.{key} is required")
        if not isinstance(parameter.get("required"), bool):
            errors.append(f"{path}: {field}.required must be boolean")
        name = parameter.get("name")
        if isinstance(name, str):
            if name in names:
                errors.append(f"{path}: duplicate parameter name: {name}")
            names.add(name)
    return errors


def check_resource_mapping(path: Path, field: str, value: object) -> list[str]:
    if not isinstance(value, dict):
        return [f"{path}: {field} must be a mapping"]
    if not non_empty_string(value.get("resource")):
        return [f"{path}: {field}.resource is required"]
    return []


def check_attested_computation(
    path: Path,
    data: dict[str, object],
    body: str,
) -> list[str]:
    if data.get("type") != "Attested Computation":
        return []

    errors: list[str] = []
    if not non_empty_string(data.get("runtime")):
        errors.append(f"{path}: Attested Computation requires runtime")
    if "parameters" in data:
        errors.extend(check_parameters(path, data["parameters"]))
    if "executor" in data:
        errors.extend(check_resource_mapping(path, "executor", data["executor"]))
        executor = data["executor"]
        if isinstance(executor, dict) and "receipt" in executor:
            receipt = executor["receipt"]
            if (
                not isinstance(receipt, list)
                or not receipt
                or any(not non_empty_string(item) for item in receipt)
            ):
                errors.append(f"{path}: executor.receipt must be a non-empty list of strings")
    if "attester" in data:
        errors.extend(check_resource_mapping(path, "attester", data["attester"]))

    section = computation_section(body)
    block_count, fences_closed = fenced_blocks(section or "")
    if "computation" in data:
        if not non_empty_string(data["computation"]):
            errors.append(f"{path}: computation must be a non-empty path")
        if block_count:
            errors.append(f"{path}: file-backed computation must omit the body computation fence")
    else:
        if section is None:
            errors.append(f"{path}: inline computation requires a # Computation section")
        elif block_count != 1 or not fences_closed:
            errors.append(f"{path}: inline computation requires exactly one closed fenced code block")
    return errors


def check_recommended_metadata(path: Path, data: dict[str, object]) -> list[str]:
    errors: list[str] = []
    for field in ("title", "description"):
        if not non_empty_string(data.get(field)):
            errors.append(f"{path}: curated policy requires non-empty {field}")
    description = data.get("description")
    if isinstance(description, str) and "\n" in description:
        errors.append(f"{path}: curated policy requires a one-line description")

    tags = data.get("tags")
    if (
        not isinstance(tags, list)
        or not tags
        or any(not non_empty_string(tag) for tag in tags)
    ):
        errors.append(f"{path}: curated policy requires a non-empty tags list")
    return errors


def check_trust_metadata(path: Path, data: dict[str, object]) -> list[str]:
    errors: list[str] = []
    generated = data.get("generated")
    if not isinstance(generated, dict):
        errors.append(f"{path}: curated trust policy requires generated")
    elif not valid_iso_datetime(generated.get("at")):
        errors.append(f"{path}: curated trust policy requires generated.at")
    if "status" not in data:
        errors.append(f"{path}: curated trust policy requires status")
    return errors


def link_href(raw: str) -> str:
    href = raw.strip()
    if not href:
        return ""
    if href[0] in {"'", '"'}:
        end = href.find(href[0], 1)
        if end != -1:
            href = href[1:end]
    else:
        href = href.split()[0]
    return href.split("#", 1)[0]


def resolve_bundle_link(source: Path, href: str, root: Path) -> Path | None:
    if not href or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", href):
        return None
    if href.startswith("/"):
        return (root / href.lstrip("/")).resolve()
    return (source.parent / href).resolve()


def check_index_metadata(path: Path, root: Path, data: dict[str, object]) -> list[str]:
    index_path = path.parent / "index.md"
    if not index_path.is_file():
        return [f"{index_path}: curated policy requires an index for {path}"]

    title = data.get("title")
    description = data.get("description")
    target = path.resolve()
    for line_number, line in enumerate(read_text(index_path).splitlines(), start=1):
        for match in INDEX_LINK_RE.finditer(line):
            href = link_href(match.group(2))
            if resolve_bundle_link(index_path, href, root) != target:
                continue

            errors: list[str] = []
            if match.group(1).strip() != title:
                errors.append(
                    f"{index_path}:{line_number}: index title for {path.name} "
                    "must match frontmatter title"
                )
            if not isinstance(description, str) or description not in line:
                errors.append(
                    f"{index_path}:{line_number}: index entry for {path.name} "
                    "must include its description"
                )
            return errors
    return [f"{index_path}: curated policy requires an entry for {path}"]


def check_index(path: Path, root: Path) -> list[str]:
    try:
        if not has_frontmatter(path):
            return []
    except ValueError as exc:
        return [f"{path}: {exc}"]

    if path != root / "index.md":
        return [f"{path}: reserved index file must not contain YAML frontmatter"]

    try:
        data = parse_frontmatter(path)
    except ValueError as exc:
        return [f"{path}: {exc}"]

    unexpected = sorted(set(data) - {"okf_version"})
    if unexpected:
        keys = ", ".join(unexpected)
        return [f"{path}: root index frontmatter may only declare okf_version: {keys}"]

    version = data.get("okf_version")
    if version is not None and str(version) != "0.2":
        return [f"{path}: okf_version must be 0.2"]
    return []


def check_log(path: Path) -> list[str]:
    try:
        lines = read_text(path).splitlines()
    except ValueError as exc:
        return [f"{path}: {exc}"]

    dates: list[str] = []
    errors: list[str] = []
    for line in lines:
        if not line.startswith("## "):
            continue
        if not DATE_HEADING_RE.match(line):
            errors.append(f"{path}: log heading must be ISO YYYY-MM-DD: {line}")
            continue
        dates.append(line.removeprefix("## "))
    if dates != sorted(dates, reverse=True):
        errors.append(f"{path}: log date headings must be newest first")
    return errors


def check_concept(
    path: Path,
    root: Path,
    require_recommended_metadata: bool,
    require_trust_metadata: bool,
    require_index_metadata: bool,
) -> list[str]:
    try:
        data = parse_frontmatter(path)
        body = concept_body(path)
    except ValueError as exc:
        return [f"{path}: {exc}"]

    errors: list[str] = []
    if not non_empty_string(data.get("type")):
        errors.append(f"{path}: non-reserved concept must declare non-empty type")
    errors.extend(check_optional_metadata(path, data))
    errors.extend(check_sources(path, data))
    errors.extend(check_generated(path, data))
    errors.extend(check_verified(path, data))
    errors.extend(check_lifecycle(path, data))
    errors.extend(check_attested_computation(path, data, body))

    if require_recommended_metadata:
        errors.extend(check_recommended_metadata(path, data))
    if require_trust_metadata:
        errors.extend(check_trust_metadata(path, data))
    if require_index_metadata:
        errors.extend(check_index_metadata(path, root, data))
    return errors


def path_segments(value: str) -> list[str]:
    return [
        segment
        for segment in value.replace("\\", "/").split("/")
        if segment and segment != "."
    ]


def has_forbidden_prefix(href: str, prefixes: list[str]) -> str | None:
    segments = path_segments(href)
    for prefix in prefixes:
        prefix_segments = path_segments(prefix)
        if not prefix_segments:
            continue
        for index in range(0, len(segments) - len(prefix_segments) + 1):
            if segments[index : index + len(prefix_segments)] == prefix_segments:
                return prefix
    return None


def check_forbidden_links(path: Path, prefixes: list[str]) -> list[str]:
    if not prefixes:
        return []
    try:
        text = read_text(path)
    except ValueError as exc:
        return [f"{path}: {exc}"]

    errors: list[str] = []
    for match in MARKDOWN_LINK_RE.finditer(text):
        href = link_href(match.group(1))
        prefix = has_forbidden_prefix(href, prefixes)
        if prefix is not None:
            errors.append(f"{path}: forbidden link prefix {prefix}: {match.group(1)}")
    return errors


def check_bundle(
    root: Path,
    required_paths: list[str],
    forbidden_link_prefixes: list[str],
    require_recommended_metadata: bool,
    require_trust_metadata: bool,
    require_index_metadata: bool,
) -> list[str]:
    errors: list[str] = []
    if not root.is_dir():
        return [f"{root}: OKF bundle directory does not exist"]

    for required_path in required_paths:
        path = root / required_path
        if not path.exists():
            errors.append(f"{path}: missing required OKF path")

    for path in sorted(root.rglob("*.md")):
        if path.name == "index.md":
            errors.extend(check_index(path, root))
        elif path.name == "log.md":
            errors.extend(check_log(path))
        else:
            errors.extend(
                check_concept(
                    path,
                    root,
                    require_recommended_metadata,
                    require_trust_metadata,
                    require_index_metadata,
                )
            )
        errors.extend(check_forbidden_links(path, forbidden_link_prefixes))
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check OKF v0.2 conformance.")
    parser.add_argument("bundle", nargs="?", default="okf", help="OKF bundle root")
    parser.add_argument(
        "--require",
        action="append",
        default=[],
        metavar="PATH",
        help="Require a bundle-relative path as a repository-local policy.",
    )
    parser.add_argument(
        "--forbid-link-prefix",
        action="append",
        default=[],
        metavar="PATH",
        help="Reject links containing this path segment as a repository-local policy.",
    )
    parser.add_argument(
        "--require-recommended-metadata",
        action="store_true",
        help="Require title, description, and tags as a curated-bundle policy.",
    )
    parser.add_argument(
        "--require-trust-metadata",
        action="store_true",
        help="Require generated.by, generated.at, and status as a curated-bundle policy.",
    )
    parser.add_argument(
        "--require-index-metadata",
        action="store_true",
        help="Require every concept in its parent index with matching title and description.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON result.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if yaml is None:
        message = "PyYAML is required; install it with the repository's development dependencies"
        if args.json:
            print(json.dumps({"ok": False, "errors": [message]}, indent=2))
        else:
            print(message, file=sys.stderr)
        return 2

    errors = check_bundle(
        Path(args.bundle),
        args.require,
        args.forbid_link_prefix,
        args.require_recommended_metadata,
        args.require_trust_metadata,
        args.require_index_metadata,
    )
    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors}, indent=2))
    elif errors:
        for error in errors:
            print(error, file=sys.stderr)
    else:
        print("OKF v0.2 conformance and configured repository policies passed")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
