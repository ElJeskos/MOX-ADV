"""Paired Direct and Metrika composition over the public module seam."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from mox_adv.analytics import IntegratedAnalyticsEngineV1
from mox_adv.contracts import (
    AnalyticsPeriod,
    AnalyticsScope,
    BaselineAggregate,
    ConnectedAnalytics,
    IntegratedPerformanceSnapshot,
    TrustedAnalyticsScope,
)
from mox_adv.environment import ExecutionEnvironment, parse_execution_environment
from mox_adv.errors import RunRejectedError
from mox_adv.module_api.v1 import (
    ClosedPeriodV1,
    DirectProviderObservationV1,
    InProcessModuleAdapterV1,
    MetrikaProviderObservationV1,
    ModuleObjectiveV1,
    ModuleOperationV1,
    ModuleRequestV1,
    ModuleResultV1,
    ModuleScopeV1,
    StoredConnectionRefV1,
)
from mox_adv.normalization import IntegratedSnapshotNormalizerV1


@dataclass(frozen=True)
class PairedConnectionRefsV1:
    """Keep provider connection references separate at the paired boundary."""

    direct: str
    metrika: str

    def __post_init__(self) -> None:
        for name, value in (("direct", self.direct), ("metrika", self.metrika)):
            if not isinstance(value, str) or not value or len(value) > 128:
                raise ValueError(
                    f"Paired {name} connection reference must be a non-empty string."
                )


class PairedModuleRuntimeV1:
    """Reconstruct the unchanged integrated snapshot from two module results."""

    def __init__(
        self,
        *,
        direct: InProcessModuleAdapterV1,
        metrika: InProcessModuleAdapterV1,
        environment: ExecutionEnvironment,
    ) -> None:
        self._direct = direct
        self._metrika = metrika
        self._environment = parse_execution_environment(environment)

    def collect_snapshot(
        self,
        *,
        policy: Mapping[str, Any],
        observation_id: str,
        generated_at: str,
        period_start: str,
        period_end: str,
        trusted_scope: TrustedAnalyticsScope,
        connection_refs: PairedConnectionRefsV1,
        baseline: Optional[BaselineAggregate] = None,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> IntegratedPerformanceSnapshot:
        direct_result = self._direct.invoke(
            self._request(
                provider="DIRECT",
                observation_id=observation_id,
                connection_ref=connection_refs.direct,
                trusted_scope=trusted_scope,
                period_start=period_start,
                period_end=period_end,
            )
        )
        direct_observation = self._direct_observation(direct_result)
        self._progress(progress_callback, "direct", "PASSED")
        self._progress(progress_callback, "metrika", "RUNNING")
        metrika_result = self._metrika.invoke(
            self._request(
                provider="METRIKA",
                observation_id=observation_id,
                connection_ref=connection_refs.metrika,
                trusted_scope=trusted_scope,
                period_start=period_start,
                period_end=period_end,
            )
        )
        metrika_observation = self._metrika_observation(metrika_result)
        self._progress(progress_callback, "metrika", "PASSED")
        self._progress(progress_callback, "analytics", "RUNNING")
        connected = ConnectedAnalytics(
            observation_id=observation_id,
            generated_at=generated_at,
            scope=AnalyticsScope(
                organization=trusted_scope.organization,
                connection=trusted_scope.connection,
                account=trusted_scope.account,
                campaign=trusted_scope.campaign,
                counter=trusted_scope.counter,
                goal=trusted_scope.goal,
            ),
            requested_period=AnalyticsPeriod(
                period_start=period_start,
                period_end=period_end,
            ),
            direct_report=direct_observation.report,
            direct_state=direct_observation.state,
            metrika_report=metrika_observation.report,
            baseline=baseline,
        )
        draft = IntegratedSnapshotNormalizerV1().normalize(
            connected,
            policy,
            trusted_scope,
        )
        snapshot = IntegratedAnalyticsEngineV1().calculate(draft)
        if not IntegratedSnapshotNormalizerV1.verify_fingerprint(
            snapshot.as_dict()
        ):
            raise RunRejectedError(
                "SNAPSHOT_FINGERPRINT_MISMATCH",
                "analytics",
                "The integrated snapshot fingerprint does not match its fields.",
            )
        self._progress(progress_callback, "analytics", "PASSED")
        return snapshot

    def _request(
        self,
        *,
        provider: str,
        observation_id: str,
        connection_ref: str,
        trusted_scope: TrustedAnalyticsScope,
        period_start: str,
        period_end: str,
    ) -> ModuleRequestV1:
        scope = (
            ModuleScopeV1(
                organization_id=trusted_scope.organization,
                account_id=trusted_scope.account,
                campaign_id=trusted_scope.campaign,
            )
            if provider == "DIRECT"
            else ModuleScopeV1(
                organization_id=trusted_scope.organization,
                campaign_id=trusted_scope.campaign,
                counter_id=trusted_scope.counter,
                goal_id=trusted_scope.goal,
            )
        )
        digest = hashlib.sha256(
            (
                provider
                + "\0"
                + observation_id
                + "\0"
                + period_start
                + "\0"
                + period_end
            ).encode("utf-8")
        ).hexdigest()
        return ModuleRequestV1(
            schema_version="module-request-v1",
            connection_ref=StoredConnectionRefV1(connection_ref),
            environment=self._environment.value,
            scope=scope,
            period=ClosedPeriodV1(
                start_date=period_start,
                end_date=period_end,
                timezone="UTC",
            ),
            objective=ModuleObjectiveV1(
                code="PAIRED_PERFORMANCE",
                description=(
                    "Collect the provider observation for integrated analytics."
                ),
            ),
            external_evidence=None,
            operation=ModuleOperationV1(
                kind="ANALYZE",
                operation_type="ANALYZE_PERFORMANCE",
            ),
            idempotency_key="paired-" + digest,
        )

    @staticmethod
    def _direct_observation(
        result: ModuleResultV1,
    ) -> DirectProviderObservationV1:
        if result.status not in {"SUCCEEDED", "PARTIAL"}:
            raise RunRejectedError(
                "DIRECT_MODULE_ANALYSIS_FAILED",
                "analytics",
                PairedModuleRuntimeV1._result_error(result),
            )
        if not isinstance(
            result.provider_observation,
            DirectProviderObservationV1,
        ):
            raise RunRejectedError(
                "DIRECT_MODULE_OBSERVATION_MISSING",
                "analytics",
                "Direct did not return a lossless normalized observation.",
            )
        return result.provider_observation

    @staticmethod
    def _metrika_observation(
        result: ModuleResultV1,
    ) -> MetrikaProviderObservationV1:
        if result.status not in {"SUCCEEDED", "PARTIAL"}:
            raise RunRejectedError(
                "METRIKA_MODULE_ANALYSIS_FAILED",
                "analytics",
                PairedModuleRuntimeV1._result_error(result),
            )
        if not isinstance(
            result.provider_observation,
            MetrikaProviderObservationV1,
        ):
            raise RunRejectedError(
                "METRIKA_MODULE_OBSERVATION_MISSING",
                "analytics",
                "Metrika did not return a lossless normalized observation.",
            )
        return result.provider_observation

    @staticmethod
    def _result_error(result: ModuleResultV1) -> str:
        if result.errors:
            return result.errors[0].message
        return "The provider module did not return a usable analysis result."

    @staticmethod
    def _progress(
        callback: Optional[Callable[[str, str], None]],
        step: str,
        status: str,
    ) -> None:
        if callback is not None:
            callback(step, status)
