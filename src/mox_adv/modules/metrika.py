"""Yandex Metrika composition root with no Direct or Dashboard dependency."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

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
    InMemoryDecisionRecordStoreV1,
    ModuleDecisionRecordStoreV1,
    ModuleRequestV1,
    ModuleResultV1,
)
from mox_adv.modules._bound import BoundProviderModuleV1


class MetrikaModuleV1(BoundProviderModuleV1):
    """Compose trusted Metrika analysis and TEST goal lifecycle services."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = utc_now,
        decision_records: ModuleDecisionRecordStoreV1 | None = None,
        provider_reader: AuthorizedMetrikaReadProviderV1 | None = None,
        goal_lifecycle_provider: (
            AuthorizedMetrikaGoalLifecycleProviderV1 | None
        ) = None,
    ) -> None:
        self.decision_records = (
            InMemoryDecisionRecordStoreV1()
            if decision_records is None
            else decision_records
        )
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

            def implementation(request: ModuleRequestV1) -> ModuleResultV1:
                if (
                    request.operation.kind == "EXECUTE"
                    and request.operation.operation_type == "MANAGE_GOAL_CANDIDATE"
                ):
                    return lifecycle.invoke(request)
                return service.invoke(request)
        super().__init__(
            identity=METRIKA_IDENTITY,
            implementation=implementation,
        )


__all__ = [
    "AuthorizedMetrikaGoalLifecycleProviderV1",
    "AuthorizedMetrikaReadProviderV1",
    "BoundMetrikaGoalLifecycleProviderV1",
    "BoundMetrikaReadProviderV1",
    "MetrikaGoalLifecycleAuthorizationError",
    "MetrikaModuleV1",
    "MetrikaReadAuthorizationError",
    "MetrikaReportReaderV1",
]
