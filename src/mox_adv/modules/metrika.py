"""Yandex Metrika composition root with no Direct dependency."""

from __future__ import annotations

from typing import Callable

from mox_adv.module_api.v1 import ModuleIdentityV1, ModuleRequestV1, ModuleResultV1
from mox_adv.modules._bound import BoundProviderModuleV1


class MetrikaModuleV1(BoundProviderModuleV1):
    """Bind a Metrika implementation to the stable module identity."""

    def __init__(
        self,
        implementation: Callable[[ModuleRequestV1], ModuleResultV1],
    ) -> None:
        super().__init__(
            identity=ModuleIdentityV1(
                module_id="YANDEX_METRIKA",
                module_version="1.0.0",
            ),
            implementation=implementation,
        )
