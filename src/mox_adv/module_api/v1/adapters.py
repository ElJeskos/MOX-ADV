"""Adapters that expose one module interface in-process and over HTTP/JSON."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Protocol

from mox_adv.environment import ExecutionEnvironment

from mox_adv.module_api.v1.contracts import (
    ContractValidationError,
    ModuleIdentityV1,
    ModuleRequestV1,
    ModuleResultV1,
)
from mox_adv.module_api.v1.decision_records import (
    InMemoryDecisionRecordStoreV1,
    ModuleDecisionRecordStoreV1,
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
    """Validate the paired-runtime seam without adding an HTTP hop."""

    def __init__(
        self,
        module: ModuleV1,
        *,
        decision_records: Optional[ModuleDecisionRecordStoreV1] = None,
    ) -> None:
        self._module = module
        self.decision_records = (
            InMemoryDecisionRecordStoreV1()
            if decision_records is None
            else decision_records
        )

    def invoke(self, request: ModuleRequestV1) -> ModuleResultV1:
        canonical_request = ModuleRequestV1.from_dict(request.as_dict())
        blocked = _block_production_execution(
            self._module,
            canonical_request,
            self.decision_records,
        )
        if blocked is not None:
            return blocked
        result = self._module.invoke(canonical_request)
        return ModuleResultV1.from_dict(result.as_dict())


class HttpJsonModuleAdapterV1:
    """Translate strict JSON objects to and from the same module interface."""

    def __init__(
        self,
        module: ModuleV1,
        *,
        decision_records: Optional[ModuleDecisionRecordStoreV1] = None,
    ) -> None:
        self._module = module
        self.decision_records = (
            InMemoryDecisionRecordStoreV1()
            if decision_records is None
            else decision_records
        )

    def handle(self, payload: Mapping[str, Any]) -> HttpJsonResponseV1:
        try:
            request = ModuleRequestV1.from_dict(payload)
        except ContractValidationError as error:
            result = ModuleResultV1.rejected_contract(
                module=self._module.identity,
                error=error,
            )
            return HttpJsonResponseV1(status_code=400, body=result.as_dict())

        blocked = _block_production_execution(
            self._module,
            request,
            self.decision_records,
        )
        result = (
            blocked
            if blocked is not None
            else ModuleResultV1.from_dict(self._module.invoke(request).as_dict())
        )
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


def _block_production_execution(
    module: ModuleV1,
    request: ModuleRequestV1,
    decision_records: ModuleDecisionRecordStoreV1,
) -> Optional[ModuleResultV1]:
    if (
        request.environment != ExecutionEnvironment.PRODUCTION.value
        or request.operation.kind != "EXECUTE"
    ):
        return None
    reference = decision_records.record_production_write_block(
        module.identity,
        request,
    )
    return ModuleResultV1.blocked_production_write(
        module=module.identity,
        request=request,
        decision_record_ref=reference,
    )
