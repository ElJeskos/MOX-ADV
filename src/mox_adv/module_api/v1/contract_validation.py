"""Shared closed-contract validation primitives for module API v1."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
_IDENTIFIER = re.compile(IDENTIFIER_PATTERN)


class ContractValidationError(ValueError):
    """Raised when an object cannot cross the public module boundary."""


def object_value(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field} must be an object")
    return value


def array_value(value: Any, field: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractValidationError(f"{field} must be an array")
    return value


def exact_fields(
    value: Mapping[str, Any],
    *,
    field: str,
    required: Sequence[str],
    optional: Sequence[str] = (),
) -> None:
    allowed = set(required) | set(optional)
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise ContractValidationError(f"{field} has unexpected field: {unexpected[0]}")
    missing = sorted(set(required) - set(value))
    if missing:
        raise ContractValidationError(f"{field} is missing field: {missing[0]}")


def text(
    value: Any,
    field: str,
    *,
    minimum: int = 1,
    maximum: int = 500,
) -> str:
    if not isinstance(value, str):
        raise ContractValidationError(f"{field} must be a string")
    if not minimum <= len(value) <= maximum:
        raise ContractValidationError(
            f"{field} length must be between {minimum} and {maximum}"
        )
    return value


def optional_text(
    value: Any,
    field: str,
    *,
    maximum: int = 500,
) -> str | None:
    if value is None:
        return None
    return text(value, field, maximum=maximum)


def one_of(value: Any, field: str, allowed: Sequence[str]) -> str:
    parsed = text(value, field)
    if parsed not in allowed:
        raise ContractValidationError(f"{field} must be one of: {', '.join(allowed)}")
    return parsed


def iso_date(value: Any, field: str) -> str:
    parsed = text(value, field)
    try:
        date.fromisoformat(parsed)
    except ValueError as error:
        raise ContractValidationError(f"{field} must be an ISO date") from error
    return parsed


def timestamp(value: Any, field: str) -> str:
    parsed = text(value, field)
    try:
        parsed_timestamp = datetime.fromisoformat(parsed.replace("Z", "+00:00"))
    except ValueError as error:
        raise ContractValidationError(
            f"{field} must be an ISO-8601 timestamp"
        ) from error
    if parsed_timestamp.tzinfo is None:
        raise ContractValidationError(f"{field} must include a UTC offset")
    return parsed


def timezone_name(value: Any, field: str) -> str:
    parsed = text(value, field)
    try:
        ZoneInfo(parsed)
    except ZoneInfoNotFoundError as error:
        raise ContractValidationError(f"{field} must name an IANA timezone") from error
    return parsed


def boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ContractValidationError(f"{field} must be boolean")
    return value


def count(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractValidationError(f"{field} must be a non-negative integer")
    return value


def identifier(value: Any, field: str) -> str:
    parsed = text(value, field, maximum=128)
    if _IDENTIFIER.fullmatch(parsed) is None:
        raise ContractValidationError(f"{field} must match {IDENTIFIER_PATTERN}")
    return parsed
