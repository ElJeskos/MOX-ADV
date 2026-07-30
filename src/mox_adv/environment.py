"""One fail-closed environment capability for every provider write seam."""

from __future__ import annotations

from enum import Enum
from typing import Union


PRODUCTION_WRITE_FORBIDDEN = "PRODUCTION_WRITE_FORBIDDEN"


class ExecutionEnvironment(str, Enum):
    """The only environments that may reach a changing provider operation."""

    PRODUCTION = "PRODUCTION"
    TEST = "TEST"


class EnvironmentWriteDenied(PermissionError):
    """A changing command was attempted outside the explicit test contour."""

    reason_code = PRODUCTION_WRITE_FORBIDDEN

    def __init__(self) -> None:
        super().__init__(
            PRODUCTION_WRITE_FORBIDDEN
            + ": changing commands are available only in the TEST environment."
        )


def parse_execution_environment(
    value: Union[ExecutionEnvironment, str],
) -> ExecutionEnvironment:
    """Normalize a trusted environment value and fail closed on unknown input."""

    try:
        return ExecutionEnvironment(value)
    except ValueError as error:
        raise EnvironmentWriteDenied() from error


def require_test_write_environment(
    value: Union[ExecutionEnvironment, str],
) -> None:
    """Reject before credentials, state preparation, or provider egress."""

    if parse_execution_environment(value) is not ExecutionEnvironment.TEST:
        raise EnvironmentWriteDenied()
