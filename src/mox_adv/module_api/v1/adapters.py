"""Adapters that expose one module interface in-process and over HTTP/JSON."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Protocol

from mox_adv.module_api.v1.contracts import (
    ContractValidationError,
    ModuleIdentityV1,
    ModuleRequestV1,
    ModuleResultV1,
)


class ModuleV1(Protocol):
    """The provider-neutral deep module interface."""

    identity: ModuleIdentityV1

    def invoke(self, request: ModuleRequestV1) -> ModuleResultV1: ...


@dataclass(frozen=True)
class HttpJsonResponseV1:
    status_code: int
    body: Dict[str, Any]


class InProcessModuleAdapterV1:
    """Invoke a module without crossing an HTTP boundary."""

    def __init__(self, module: ModuleV1) -> None:
        self._module = module

    def invoke(self, request: ModuleRequestV1) -> ModuleResultV1:
        return self._module.invoke(request)


class HttpJsonModuleAdapterV1:
    """Translate strict JSON objects to and from the same module interface."""

    def __init__(self, module: ModuleV1) -> None:
        self._module = module

    def handle(self, payload: Mapping[str, Any]) -> HttpJsonResponseV1:
        try:
            request = ModuleRequestV1.from_dict(payload)
        except ContractValidationError as error:
            result = ModuleResultV1.rejected_contract(
                module=self._module.identity,
                error=error,
            )
            return HttpJsonResponseV1(status_code=400, body=result.as_dict())

        result = self._module.invoke(request)
        status_code = {
            "SUCCEEDED": 200,
            "PARTIAL": 200,
            "BLOCKED": 422,
            "REJECTED": 422,
            "FAILED": 500,
        }[result.status]
        return HttpJsonResponseV1(
            status_code=status_code,
            body=result.as_dict(),
        )
