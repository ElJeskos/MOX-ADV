"""Provider-neutral validation primitives for explicit TEST resource files."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mox_adv.control_state import AuthenticatedPrincipal


def json_object_v1(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("TEST resource JSON is unavailable.") from error
    if not isinstance(value, dict):
        raise TypeError("TEST resource JSON must contain one object.")
    return value


def relative_path_v1(owner: Path, value: Any, field: str) -> Path:
    path = Path(required_text_v1(value, field))
    return path if path.is_absolute() else owner.parent / path


def required_text_v1(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(field + " must be non-empty text.")
    return value


def text_array_v1(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(field + " must be an array.")
    return tuple(required_text_v1(item, field) for item in value)


def utc_timestamp_v1(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(
            required_text_v1(value, field).replace("Z", "+00:00")
        )
    except ValueError as error:
        raise ValueError(field + " must be ISO-8601.") from error
    if parsed.tzinfo is None:
        raise ValueError(field + " must be timezone-aware.")
    return parsed.astimezone(timezone.utc)


def mapping_v1(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(field + " must be an object.")
    return value


def principal_v1(value: Any, field: str) -> AuthenticatedPrincipal:
    if not isinstance(value, dict) or set(value) != {
        "identity",
        "authentication",
    }:
        raise ValueError(field + " must contain identity and authentication.")
    return AuthenticatedPrincipal(
        identity=required_text_v1(value["identity"], field + ".identity"),
        authentication=required_text_v1(
            value["authentication"],
            field + ".authentication",
        ),
    )


__all__ = [
    "json_object_v1",
    "mapping_v1",
    "principal_v1",
    "relative_path_v1",
    "required_text_v1",
    "text_array_v1",
    "utc_timestamp_v1",
]
