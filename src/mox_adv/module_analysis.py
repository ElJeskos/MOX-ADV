"""Provider-neutral lifecycle helpers for standalone analysis modules."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Callable, Literal
from zoneinfo import ZoneInfo

from mox_adv.module_api.v1 import (
    MODULE_RESULT_SCHEMA_VERSION,
    ModuleErrorV1,
    ModuleIdentityV1,
    ModuleRequestV1,
    ModuleResultV1,
)

TerminalModuleStatus = Literal["BLOCKED", "REJECTED", "FAILED"]


def normalized_utc_now(
    clock: Callable[[], datetime],
    *,
    module_name: str,
) -> datetime:
    now = clock()
    if now.tzinfo is None:
        raise ValueError(module_name + " module clock must be timezone-aware.")
    return now.astimezone(timezone.utc)


def validate_closed_period(
    request: ModuleRequestV1,
    now: datetime,
    *,
    module_name: str,
) -> None:
    local_date = now.astimezone(ZoneInfo(request.period.timezone)).date()
    if datetime.fromisoformat(request.period.end_date).date() >= local_date:
        raise ValueError(
            "The requested " + module_name + " period must be closed."
        )


def failed_provider_read(
    *,
    module: ModuleIdentityV1,
    request: ModuleRequestV1,
    error_code: str,
    message: str,
) -> ModuleResultV1:
    return terminal_module_result(
        module=module,
        request=request,
        status="FAILED",
        error=ModuleErrorV1(
            code=error_code,
            message=message,
            field="connection_ref",
            retryable=True,
        ),
    )


def terminal_module_result(
    *,
    module: ModuleIdentityV1,
    request: ModuleRequestV1,
    status: TerminalModuleStatus,
    error: ModuleErrorV1,
) -> ModuleResultV1:
    return ModuleResultV1(
        schema_version=MODULE_RESULT_SCHEMA_VERSION,
        run_id=_bounded_run_id(status.lower(), module, request),
        module=module,
        status=status,
        metrics=(),
        assessment=None,
        recommendations=(),
        proposal=None,
        execution_result=None,
        provenance=(),
        warnings=(),
        errors=(error,),
        decision_record_ref=None,
    )


def _bounded_run_id(
    prefix: str,
    module: ModuleIdentityV1,
    request: ModuleRequestV1,
) -> str:
    digest = hashlib.sha256(
        request.idempotency_key.encode("utf-8")
    ).hexdigest()[:24]
    provider = module.module_id.removeprefix("YANDEX_").lower()
    return prefix + "-" + provider + "-" + digest
