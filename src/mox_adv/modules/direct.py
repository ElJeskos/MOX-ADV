"""Yandex Direct composition root with no Metrika or Dashboard dependency."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

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
from mox_adv.environment import ExecutionEnvironment, parse_execution_environment
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
    """Compose the trusted Direct analysis and TEST-only action services."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = utc_now,
        decision_records: ModuleDecisionRecordStoreV1 | None = None,
        provider_reader: AuthorizedDirectReadProviderV1 | None = None,
        action_runtime: DirectActionRuntimeV1 | None = None,
        campaign_creation_runtime: DirectCampaignCreationRuntimeV1 | None = None,
        impact_policy: Mapping[str, Any] | None = None,
        environment: ExecutionEnvironment = ExecutionEnvironment.PRODUCTION,
    ) -> None:
        self.decision_records = (
            InMemoryDecisionRecordStoreV1()
            if decision_records is None
            else decision_records
        )
        self._environment = parse_execution_environment(environment)
        if (
            campaign_creation_runtime is not None
            and campaign_creation_runtime.environment is not self._environment
        ):
            raise ContractValidationError(
                "Direct campaign creation runtime and module environments must match."
            )
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
        impact_evaluation = (
            None
            if impact_policy is None
            else self._impact_service(impact_policy)
        )

        def invoke(request: ModuleRequestV1) -> ModuleResultV1:
            if (
                impact_evaluation is not None
                and request.operation.operation_type == "EVALUATE_IMPACT"
            ):
                return impact_evaluation(request)
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

        def trusted_invoke(request: ModuleRequestV1) -> ModuleResultV1:
            if (
                request.operation.kind == "EXECUTE"
                and request.operation.operation_type == "CREATE_CAMPAIGN"
            ):
                blocked = self._block_campaign_creation(request)
                if blocked is not None:
                    return blocked
            return invoke(request)

        super().__init__(
            identity=DIRECT_IDENTITY,
            implementation=trusted_invoke,
        )

    def _action_service(
        self,
        clock: Callable[[], datetime],
        provider_reader: AuthorizedDirectReadProviderV1 | None,
        action_runtime: DirectActionRuntimeV1,
    ) -> Callable[[ModuleRequestV1], ModuleResultV1]:
        from mox_adv.direct_action import StandaloneDirectActionV1

        return StandaloneDirectActionV1(
            clock=clock,
            decision_records=self.decision_records,
            provider_reader=provider_reader,
            runtime=action_runtime,
        ).invoke

    def _impact_service(
        self,
        policy: Mapping[str, Any],
    ) -> Callable[[ModuleRequestV1], ModuleResultV1]:
        from mox_adv.direct_impact import StandaloneDirectImpactEvaluationV1

        return StandaloneDirectImpactEvaluationV1(
            policy=policy,
            decision_records=self.decision_records,
        ).invoke

    def _block_campaign_creation(
        self,
        request: ModuleRequestV1,
    ) -> ModuleResultV1 | None:
        if (
            self._environment is ExecutionEnvironment.TEST
            and request.environment == ExecutionEnvironment.TEST.value
        ):
            return None
        receipt = self.decision_records.record_production_write_block(
            DIRECT_IDENTITY,
            request,
            self._environment,
        )
        return ModuleResultV1.blocked_production_write(
            module=DIRECT_IDENTITY,
            request=request,
            decision_id=receipt.decision_id,
            decision_record_ref=receipt.reference,
        )

    def _campaign_creation_service(
        self,
        clock: Callable[[], datetime],
        runtime: DirectCampaignCreationRuntimeV1,
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
