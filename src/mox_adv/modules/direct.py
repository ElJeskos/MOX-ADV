"""Yandex Direct composition root with no Metrika or Dashboard dependency."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Callable, Optional

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

if TYPE_CHECKING:
    from mox_adv.direct_action import DirectActionRuntimeV1
    from mox_adv.direct_campaign_creation import DirectCampaignCreationRuntimeV1


class DirectModuleV1(BoundProviderModuleV1):
    """Run standalone Direct or preserve the legacy injected composition."""

    def __init__(
        self,
        implementation: Optional[Callable[[ModuleRequestV1], ModuleResultV1]] = None,
        *,
        clock: Callable[[], datetime] = utc_now,
        decision_records: Optional[ModuleDecisionRecordStoreV1] = None,
        provider_reader: Optional[AuthorizedDirectReadProviderV1] = None,
        action_runtime: Optional["DirectActionRuntimeV1"] = None,
        campaign_creation_runtime: Optional["DirectCampaignCreationRuntimeV1"] = None,
    ) -> None:
        if implementation is not None and (
            provider_reader is not None
            or action_runtime is not None
            or campaign_creation_runtime is not None
        ):
            raise ContractValidationError(
                "Direct cannot combine a legacy implementation "
                "with a standalone provider composition."
            )
        self.decision_records = (
            InMemoryDecisionRecordStoreV1()
            if decision_records is None
            else decision_records
        )
        if implementation is None:
            analysis = StandaloneDirectAnalysisV1(
                clock=clock,
                decision_records=self.decision_records,
                provider_reader=provider_reader,
            )
            action = (
                None
                if action_runtime is None
                else self._action_service(
                    clock,
                    provider_reader,
                    action_runtime,
                )
            )
            campaign_creation = (
                None
                if campaign_creation_runtime is None
                else self._campaign_creation_service(
                    clock,
                    campaign_creation_runtime,
                )
            )

            def invoke(request: ModuleRequestV1) -> ModuleResultV1:
                if (
                    campaign_creation is not None
                    and request.operation.operation_type == "CREATE_CAMPAIGN"
                ):
                    return campaign_creation(request)
                if action is not None and request.operation.operation_type in {
                    "PLAN_OPTIMIZATION",
                    "APPLY_OPTIMIZATION",
                }:
                    return action(request)
                return analysis.invoke(request)

            implementation = invoke
        super().__init__(
            identity=DIRECT_IDENTITY,
            implementation=implementation,
        )

    def _action_service(
        self,
        clock: Callable[[], datetime],
        provider_reader: Optional[AuthorizedDirectReadProviderV1],
        action_runtime: "DirectActionRuntimeV1",
    ) -> Callable[[ModuleRequestV1], ModuleResultV1]:
        from mox_adv.direct_action import StandaloneDirectActionV1

        return StandaloneDirectActionV1(
            clock=clock,
            decision_records=self.decision_records,
            provider_reader=provider_reader,
            runtime=action_runtime,
        ).invoke

    def _campaign_creation_service(
        self,
        clock: Callable[[], datetime],
        runtime: "DirectCampaignCreationRuntimeV1",
    ) -> Callable[[ModuleRequestV1], ModuleResultV1]:
        from mox_adv.direct_campaign_creation import (
            StandaloneDirectCampaignCreationV1,
        )

        return StandaloneDirectCampaignCreationV1(
            clock=clock,
            decision_records=self.decision_records,
            runtime=runtime,
        ).invoke


__all__ = [
    "AuthorizedDirectReadProviderV1",
    "BoundDirectReadProviderV1",
    "DirectModuleV1",
    "DirectReadAuthorizationError",
    "DirectReportReaderV1",
    "DirectStateReaderV1",
]
