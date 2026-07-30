"""Shared composition behavior for independently packaged provider modules."""

from __future__ import annotations

from typing import Callable

from mox_adv.module_api.v1 import (
    ContractValidationError,
    ModuleIdentityV1,
    ModuleRequestV1,
    ModuleResultV1,
)


class BoundProviderModuleV1:
    """Bind one provider identity to its independently supplied implementation."""

    def __init__(
        self,
        *,
        identity: ModuleIdentityV1,
        implementation: Callable[[ModuleRequestV1], ModuleResultV1],
    ) -> None:
        self.identity = identity
        self._implementation = implementation

    def invoke(self, request: ModuleRequestV1) -> ModuleResultV1:
        result = self._implementation(request)
        if result.module != self.identity:
            raise ContractValidationError(
                "provider implementation returned a different module identity"
            )
        return result
