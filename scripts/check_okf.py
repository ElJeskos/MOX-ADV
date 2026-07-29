#!/usr/bin/env python3
"""Generic Open Knowledge Format v0.1 conformance checker."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - developer fallback.
    yaml = None


DATE_HEADING_RE = re.compile(r"^## \d{4}-\d{2}-\d{2}$")
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
INDEX_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def has_frontmatter(path: Path) -> bool:
    return read_text(path).startswith("---\n")


def parse_frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")

    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("unterminated YAML frontmatter")

    raw = text[4:end].strip()
    if yaml is not None:
        try:
            loaded = yaml.safe_load(raw) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML frontmatter: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ValueError("YAML frontmatter must be a mapping")
        return loaded

    data: dict[str, object] = {}
    for line_number, line in enumerate(raw.splitlines(), start=2):
        stripped = line.strip()
        if not stripped:
            continue
        if ":" not in stripped:
            raise ValueError(f"invalid YAML line {line_number}: {line}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"empty YAML key on line {line_number}")
        data[key] = value.strip().strip('"').strip("'")
    return data


def check_index(path: Path, root: Path) -> list[str]:
    if not has_frontmatter(path):
        return []

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
    if version is not None and str(version) != "0.1":
        return [f"{path}: okf_version must be 0.1"]
    return []


def check_log(path: Path) -> list[str]:
    dates: list[str] = []
    errors: list[str] = []
    for line in read_text(path).splitlines():
        if not line.startswith("## "):
            continue
        if not DATE_HEADING_RE.match(line):
            errors.append(f"{path}: log heading must be ISO YYYY-MM-DD: {line}")
            continue
        dates.append(line.removeprefix("## "))

    if dates != sorted(dates, reverse=True):
        errors.append(f"{path}: log date headings must be newest first")
    return errors


def check_recommended_metadata(path: Path, data: dict[str, object]) -> list[str]:
    errors: list[str] = []

    for key in ("title", "description"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{path}: recommended {key} must be a non-empty string")

    description = data.get("description")
    if isinstance(description, str) and "\n" in description:
        errors.append(f"{path}: recommended description must fit on one line")

    tags = data.get("tags")
    if yaml is None and isinstance(tags, str):
        tags = [item.strip() for item in tags.removeprefix("[").removesuffix("]").split(",") if item.strip()]
    if (
        not isinstance(tags, list)
        or not tags
        or any(not isinstance(tag, str) or not tag.strip() for tag in tags)
    ):
        errors.append(f"{path}: recommended tags must be a non-empty list of strings")

    timestamp = data.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp.strip():
        errors.append(f"{path}: recommended timestamp must be a non-empty ISO 8601 string")
    else:
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"{path}: recommended timestamp must be valid ISO 8601: {timestamp}")
        else:
            if parsed_timestamp.tzinfo is None:
                errors.append(f"{path}: recommended timestamp must include a timezone: {timestamp}")

    return errors


def check_concept(path: Path, require_recommended_metadata: bool) -> list[str]:
    try:
        data = parse_frontmatter(path)
    except ValueError as exc:
        return [f"{path}: {exc}"]

    errors: list[str] = []
    concept_type = data.get("type")
    if concept_type is None or str(concept_type).strip() == "":
        errors.append(f"{path}: non-reserved concept must declare non-empty type")
    if require_recommended_metadata:
        errors.extend(check_recommended_metadata(path, data))
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


def check_index_metadata(path: Path, root: Path) -> list[str]:
    index_path = path.parent / "index.md"
    if not index_path.is_file():
        return [f"{index_path}: local policy requires an index for {path}"]

    try:
        data = parse_frontmatter(path)
    except ValueError:
        return []

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
                    f"{index_path}:{line_number}: index title for {path.name} must match frontmatter title"
                )
            if not isinstance(description, str) or description not in line:
                errors.append(
                    f"{index_path}:{line_number}: index entry for {path.name} must include its description"
                )
            return errors

    return [f"{index_path}: local policy requires an entry for {path}"]


def path_segments(value: str) -> list[str]:
    return [segment for segment in value.replace("\\", "/").split("/") if segment and segment != "."]


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


def check_bundle(
    root: Path,
    required_paths: list[str],
    forbidden_link_prefixes: list[str],
    require_recommended_metadata: bool,
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
            continue
        if path.name == "log.md":
            errors.extend(check_log(path))
            continue

        errors.extend(check_concept(path, require_recommended_metadata))
        if require_index_metadata:
            errors.extend(check_index_metadata(path, root))

        if forbidden_link_prefixes:
            for match in MARKDOWN_LINK_RE.finditer(read_text(path)):
                href = link_href(match.group(1))
                prefix = has_forbidden_prefix(href, forbidden_link_prefixes)
                if prefix is not None:
                    errors.append(f"{path}: forbidden link prefix {prefix}: {match.group(1)}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check OKF v0.1 conformance.")
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
        help="Reject markdown links whose path contains this segment/prefix as a local policy.",
    )
    parser.add_argument(
        "--require-recommended-metadata",
        action="store_true",
        help=(
            "Require the optional OKF v0.1 title, description, tags, and timestamp fields "
            "as a repository-local policy."
        ),
    )
    parser.add_argument(
        "--require-index-metadata",
        action="store_true",
        help=(
            "Require every concept to appear in its parent index with the frontmatter "
            "title and description as a repository-local policy."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON result.")
    args = parser.parse_args(argv)

    errors = check_bundle(
        Path(args.bundle),
        args.require,
        args.forbid_link_prefix,
        args.require_recommended_metadata,
        args.require_index_metadata,
    )
    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors}, indent=2))
    elif errors:
        for error in errors:
            print(error, file=sys.stderr)
    else:
        print("OKF conformance and configured repository policies passed")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
