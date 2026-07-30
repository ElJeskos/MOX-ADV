"""Yandex Metrika composition root with no Direct or Dashboard dependency."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from mox_adv.metrika_analysis import (
    METRIKA_IDENTITY,
    StandaloneMetrikaAnalysisV1,
    utc_now,
)
from mox_adv.metrika_goal_lifecycle import (
    AuthorizedMetrikaGoalLifecycleProviderV1,
    BoundMetrikaGoalLifecycleProviderV1,
    MetrikaGoalLifecycleAuthorizationError,
    StandaloneMetrikaGoalLifecycleV1,
)
from mox_adv.metrika_provider import (
    AuthorizedMetrikaReadProviderV1,
    BoundMetrikaReadProviderV1,
    MetrikaReadAuthorizationError,
    MetrikaReportReaderV1,
)
from mox_adv.module_api.v1 import (
    ContractValidationError,
    InMemoryDecisionRecordStoreV1,
    ModuleDecisionRecordStoreV1,
    ModuleRequestV1,
    ModuleResultV1,
)
from mox_adv.modules._bound import BoundProviderModuleV1


class MetrikaModuleV1(BoundProviderModuleV1):
    """Run standalone Metrika or preserve the legacy injected composition."""

    def __init__(
        self,
        implementation: Optional[Callable[[ModuleRequestV1], ModuleResultV1]] = None,
        *,
        clock: Callable[[], datetime] = utc_now,
        decision_records: Optional[ModuleDecisionRecordStoreV1] = None,
        provider_reader: Optional[AuthorizedMetrikaReadProviderV1] = None,
        goal_lifecycle_provider: Optional[
            AuthorizedMetrikaGoalLifecycleProviderV1
        ] = None,
    ) -> None:
        if implementation is not None and (
            provider_reader is not None or goal_lifecycle_provider is not None
        ):
            raise ContractValidationError(
                "Metrika cannot combine a legacy implementation "
                "with standalone providers."
            )
        self.decision_records = (
            InMemoryDecisionRecordStoreV1()
            if decision_records is None
            else decision_records
        )
        if implementation is None:
            service = StandaloneMetrikaAnalysisV1(
                clock=clock,
                decision_records=self.decision_records,
                provider_reader=provider_reader,
            )
            if goal_lifecycle_provider is None:
                implementation = service.invoke
            else:
                lifecycle = StandaloneMetrikaGoalLifecycleV1(
                    identity=METRIKA_IDENTITY,
                    provider=goal_lifecycle_provider,
                    decision_records=self.decision_records,
                    clock=clock,
                )

                def invoke(request: ModuleRequestV1) -> ModuleResultV1:
                    if (
                        request.operation.operation_type
                        == "MANAGE_GOAL_CANDIDATE"
                    ):
                        return lifecycle.invoke(request)
                    return service.invoke(request)

                implementation = invoke
        super().__init__(
            identity=METRIKA_IDENTITY,
            implementation=implementation,
        )


__all__ = [
    "AuthorizedMetrikaReadProviderV1",
    "AuthorizedMetrikaGoalLifecycleProviderV1",
    "BoundMetrikaGoalLifecycleProviderV1",
    "BoundMetrikaReadProviderV1",
    "MetrikaModuleV1",
    "MetrikaReadAuthorizationError",
    "MetrikaGoalLifecycleAuthorizationError",
    "MetrikaReportReaderV1",
]
