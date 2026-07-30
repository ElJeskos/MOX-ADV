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
from mox_adv.module_api.v1 import InProcessModuleAdapterV1
from mox_adv.modules.direct import BoundDirectReadProviderV1, DirectModuleV1
from mox_adv.modules.metrika import BoundMetrikaReadProviderV1, MetrikaModuleV1
from mox_adv.observe import (
    load_linked_fixture,
    load_observe_policy,
    read_observe_snapshot,
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


class PairedModuleRuntimeTests(unittest.TestCase):
    def test_module_results_reconstruct_the_legacy_snapshot_byte_for_byte(
        self,
    ) -> None:
        policy = load_observe_policy(POLICY)
        fixture = load_linked_fixture(FIXTURE)
        connected = FixtureAnalyticsConnectorV1().read_linked(fixture)
        trusted_scope = trusted_fixture_scope(policy, connected.observation_id)
        legacy_reads = FixtureAnalyticsReadConnectorsV1(connected)
        legacy = read_observe_snapshot(
            policy=policy,
            observation_id=connected.observation_id,
            generated_at=connected.generated_at,
            period_start=connected.direct_report.period_start,
            period_end=connected.direct_report.period_end,
            trusted_scope=trusted_scope,
            direct_reports=legacy_reads,
            direct_state=legacy_reads,
            metrika_report=legacy_reads,
            baseline=connected.baseline,
        )

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

        def canonical(value: object) -> str:
            return json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )

        self.assertEqual(canonical(legacy.as_dict()), canonical(migrated.as_dict()))
        self.assertEqual(legacy.snapshot_id, migrated.snapshot_id)
        self.assertEqual(1, reads.direct_report_reads)
        self.assertEqual(1, reads.direct_state_reads)
        self.assertEqual(1, reads.metrika_report_reads)

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
