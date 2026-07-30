"""Strict shared value parsing for Yandex provider responses."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from mox_adv.yandex_transport import HttpResponse


def json_response_object(
    response: HttpResponse,
    provider: str,
) -> dict[str, Any]:
    if response.status < 200 or response.status >= 300:
        raise RuntimeError(f"{provider} read failed with HTTP {response.status}.")
    try:
        value = json.loads(response.body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"{provider} returned invalid JSON.") from error
    if not isinstance(value, dict):
        raise TypeError(f"{provider} returned a non-object JSON response.")
    return value


def required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError(field + " must be a non-empty string.")
    return value


def nonnegative_count(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(field + " must be a non-negative integer.")
    return value


def object_mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(field + " must be an object.")
    return value


def nonempty_array(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, list) or not value or len(value) > 1_000:
        raise ValueError(field + " must contain 1 to 1000 items.")
    return tuple(value)
