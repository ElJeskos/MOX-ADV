from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path

from mox_adv.connectors import (
    FixtureAnalyticsConnectorV1,
    FixtureAnalyticsReadConnectorsV1,
)
from mox_adv.environment import ExecutionEnvironment
from mox_adv.errors import RunRejectedError
from mox_adv.module_api.v1 import (
    InProcessModuleAdapterV1,
    ModuleErrorV1,
    ModuleIdentityV1,
    ModuleResultV1,
)
from mox_adv.modules.direct import BoundDirectReadProviderV1, DirectModuleV1
from mox_adv.modules.metrika import BoundMetrikaReadProviderV1, MetrikaModuleV1
from mox_adv.observe import (
    load_linked_fixture,
    load_observe_policy,
    trusted_fixture_scope,
)
from mox_adv.paired_runtime import (
    PairedConnectionRefsV1,
    PairedModuleRuntimeV1,
)
from tests.test_observe_analytics import FIXTURE, POLICY


class CountingFixtureReads(FixtureAnalyticsReadConnectorsV1):
    def __init__(self, connected: object) -> None:
        super().__init__(connected)
        self.direct_report_reads = 0
        self.direct_state_reads = 0
        self.metrika_report_reads = 0

    def read_report(self, query: object):
        self.direct_report_reads += 1
        return super().read_report(query)

    def read_campaign_state(self, query: object):
        self.direct_state_reads += 1
        return super().read_campaign_state(query)

    def read_metrika_report(self, query: object):
        self.metrika_report_reads += 1
        return super().read_metrika_report(query)


class StaticResultAdapter:
    def __init__(self, result: ModuleResultV1) -> None:
        self.result = result
        self.invocations = 0

    def invoke(self, request: object) -> ModuleResultV1:
        del request
        self.invocations += 1
        return self.result


def failed_result(module_id: str) -> ModuleResultV1:
    return ModuleResultV1(
        schema_version="module-result-v1",
        run_id="failed-provider-run",
        module=ModuleIdentityV1(
            module_id=module_id,
            module_version="1.0.0",
        ),
        status="FAILED",
        metrics=(),
        assessment=None,
        recommendations=(),
        proposal=None,
        execution_result=None,
        provenance=(),
        warnings=(),
        errors=(
            ModuleErrorV1(
                code="PROVIDER_READ_FAILED",
                message="Provider result is unavailable.",
                field=None,
                retryable=True,
            ),
        ),
        decision_record_ref=None,
    )


class PairedModuleRuntimeTests(unittest.TestCase):
    def test_module_results_reconstruct_the_approved_snapshot_exactly(
        self,
    ) -> None:
        policy = load_observe_policy(POLICY)
        fixture = load_linked_fixture(FIXTURE)
        connected = FixtureAnalyticsConnectorV1().read_linked(fixture)
        trusted_scope = trusted_fixture_scope(policy, connected.observation_id)
        reads = CountingFixtureReads(connected)
        observed_at = datetime.fromisoformat(connected.generated_at)
        direct = DirectModuleV1(
            clock=lambda: observed_at,
            provider_reader=BoundDirectReadProviderV1(
                connection_id="paired-direct",
                account_id=trusted_scope.account,
                campaign_id=trusted_scope.campaign,
                trusted_change_author=connected.direct_state.last_change_author,
                report_reader=reads,
                state_reader=reads,
            ),
            environment=ExecutionEnvironment.TEST,
        )
        metrika = MetrikaModuleV1(
            clock=lambda: observed_at,
            provider_reader=BoundMetrikaReadProviderV1(
                connection_id="paired-metrika",
                counter_id=trusted_scope.counter,
                goal_id=trusted_scope.goal,
                campaign_id=trusted_scope.campaign,
                reader=reads,
            ),
        )
        runtime = PairedModuleRuntimeV1(
            direct=InProcessModuleAdapterV1(
                direct,
                environment=ExecutionEnvironment.TEST,
            ),
            metrika=InProcessModuleAdapterV1(
                metrika,
                environment=ExecutionEnvironment.TEST,
            ),
            environment=ExecutionEnvironment.TEST,
        )

        migrated = runtime.collect_snapshot(
            policy=policy,
            observation_id=connected.observation_id,
            generated_at=connected.generated_at,
            period_start=connected.direct_report.period_start,
            period_end=connected.direct_report.period_end,
            trusted_scope=trusted_scope,
            connection_refs=PairedConnectionRefsV1(
                direct="paired-direct",
                metrika="paired-metrika",
            ),
            baseline=connected.baseline,
        )

        self.assertEqual(
            (
                "sha256:"
                "ae97465bcf3f2bb45cae25898336f3e037dfd7ae12e5d45613335be72c2c4a28"
            ),
            migrated.snapshot_id,
        )
        self.assertEqual(1, reads.direct_report_reads)
        self.assertEqual(1, reads.direct_state_reads)
        self.assertEqual(1, reads.metrika_report_reads)

    def test_invalid_direct_result_stops_before_metrika_and_is_not_passed(
        self,
    ) -> None:
        policy = load_observe_policy(POLICY)
        fixture = load_linked_fixture(FIXTURE)
        connected = FixtureAnalyticsConnectorV1().read_linked(fixture)
        trusted_scope = trusted_fixture_scope(policy, connected.observation_id)
        direct = StaticResultAdapter(failed_result("YANDEX_DIRECT"))
        metrika = StaticResultAdapter(failed_result("YANDEX_METRIKA"))
        progress = []
        runtime = PairedModuleRuntimeV1(
            direct=direct,  # type: ignore[arg-type]
            metrika=metrika,  # type: ignore[arg-type]
            environment=ExecutionEnvironment.TEST,
        )

        with self.assertRaisesRegex(
            RunRejectedError,
            "Provider result is unavailable",
        ):
            runtime.collect_snapshot(
                policy=policy,
                observation_id=connected.observation_id,
                generated_at=connected.generated_at,
                period_start=connected.direct_report.period_start,
                period_end=connected.direct_report.period_end,
                trusted_scope=trusted_scope,
                connection_refs=PairedConnectionRefsV1(
                    direct="paired-direct",
                    metrika="paired-metrika",
                ),
                baseline=connected.baseline,
                progress_callback=lambda step, status: progress.append(
                    (step, status)
                ),
            )

        self.assertEqual(1, direct.invocations)
        self.assertEqual(0, metrika.invocations)
        self.assertNotIn(("direct", "PASSED"), progress)
        self.assertNotIn(("metrika", "RUNNING"), progress)

    def test_openapi_publishes_the_lossless_paired_observation(self) -> None:
        specification = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "openapi"
                / "module-api-v1.openapi.json"
            ).read_text(encoding="utf-8")
        )
        schemas = specification["components"]["schemas"]
        observation = schemas["ModuleResultV1"]["properties"][
            "provider_observation"
        ]

        self.assertEqual(
            {
                "#/components/schemas/DirectProviderObservationV1",
                "#/components/schemas/MetrikaProviderObservationV1",
            },
            {item["$ref"] for item in observation["oneOf"]},
        )


if __name__ == "__main__":
    unittest.main()
