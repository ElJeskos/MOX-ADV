"""Yandex Direct composition root with no Metrika or Dashboard dependency."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from mox_adv.direct_analysis import (
    DIRECT_IDENTITY,
    StandaloneDirectAnalysisV1,
    utc_now,
)
from mox_adv.direct_provider import (
    AuthorizedDirectReadProviderV1,
    BoundDirectReadProviderV1,
    DirectReadAuthorizationError,
    DirectReportReaderV1,
    DirectStateReaderV1,
)
from mox_adv.module_api.v1 import (
    ContractValidationError,
    InMemoryDecisionRecordStoreV1,
    ModuleDecisionRecordStoreV1,
    ModuleRequestV1,
    ModuleResultV1,
)
from mox_adv.modules._bound import BoundProviderModuleV1


class DirectModuleV1(BoundProviderModuleV1):
    """Run standalone Direct or preserve the legacy injected composition."""

    def __init__(
        self,
        implementation: Optional[Callable[[ModuleRequestV1], ModuleResultV1]] = None,
        *,
        clock: Callable[[], datetime] = utc_now,
        decision_records: Optional[ModuleDecisionRecordStoreV1] = None,
        provider_reader: Optional[AuthorizedDirectReadProviderV1] = None,
    ) -> None:
        if implementation is not None and provider_reader is not None:
            raise ContractValidationError(
                "Direct cannot combine a legacy implementation "
                "with a standalone provider reader."
            )
        self.decision_records = (
            InMemoryDecisionRecordStoreV1()
            if decision_records is None
            else decision_records
        )
        if implementation is None:
            service = StandaloneDirectAnalysisV1(
                clock=clock,
                decision_records=self.decision_records,
                provider_reader=provider_reader,
            )
            implementation = service.invoke
        super().__init__(
            identity=DIRECT_IDENTITY,
            implementation=implementation,
        )


__all__ = [
    "AuthorizedDirectReadProviderV1",
    "BoundDirectReadProviderV1",
    "DirectModuleV1",
    "DirectReadAuthorizationError",
    "DirectReportReaderV1",
    "DirectStateReaderV1",
]
