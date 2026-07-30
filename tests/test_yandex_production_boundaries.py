from __future__ import annotations

import json
import tempfile
import threading
import unittest
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import mox_adv.paired_production
from mox_adv.contracts import (
    DirectReportsReadQuery,
    MetrikaReportReadQuery,
)
from mox_adv.direct_production import (
    DIRECT_CAMPAIGN_STATE_READ,
    DIRECT_REPORTS_READ,
    DirectProductionReadProviderV1,
    DirectProductionReadSettingsV1,
)
from mox_adv.metrika_production import (
    METRIKA_REPORT_READ,
    MetrikaProductionReadProviderV1,
    MetrikaProductionReadSettingsV1,
)
from mox_adv.observe import load_observe_policy
from mox_adv.paired_production import (
    PairedProductionReadFailure,
    PairedProductionReadResultV1,
    PairedYandexProductionReaderV1,
)
from mox_adv.yandex_credentials import DotenvValue
from mox_adv.yandex_transport import (
    HttpResponse,
    UrllibHttpClient,
    YandexReadEndpoint,
)


class RecordingHttpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[YandexReadEndpoint, str, Mapping[str, str]]] = []

    def perform(
        self,
        *,
        endpoint: YandexReadEndpoint,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> HttpResponse:
        del body
        self.calls.append((endpoint, url, headers))
        if endpoint == DIRECT_REPORTS_READ:
            return HttpResponse(
                status=200,
                headers={
                    "X-MOX-Retrieved-At": "2026-07-30T11:55:00+00:00",
                    "X-MOX-Watermark": "2026-07-30T11:50:00+00:00",
                },
                body=(
                    b"Date\tCampaignId\tImpressions\tClicks\tCost\n"
                    b"2026-07-29\tcampaign-1\t10000\t200\t5000000000\n"
                ),
            )
        if endpoint == METRIKA_REPORT_READ:
            return HttpResponse(
                status=200,
                headers={},
                body=json.dumps(
                    {
                        "meta": {
                            "retrieved_at": "2026-07-30T11:55:00+00:00",
                            "watermark": "2026-07-30T11:50:00+00:00",
                        },
                        "data": [
                            {
                                "dimensions": [{"name": "2026-07-29"}],
                                "metrics": [300.0, 5.0],
                            }
                        ],
                    }
                ).encode(),
            )
        if endpoint == DIRECT_CAMPAIGN_STATE_READ:
            return HttpResponse(
                status=200,
                headers={},
                body=json.dumps(
                    {
                        "meta": {
                            "retrieved_at": "2026-07-30T11:55:00+00:00",
                            "watermark": "2026-07-30T11:50:00+00:00",
                        },
                        "data": [
                            {
                                "campaign": "campaign-1",
                                "campaign_state": "ON",
                                "group_state": "ON",
                                "ad_state": "ON",
                                "strategy": "HIGHEST_POSITION",
                                "current_weekly_budget_micros": 10_000_000_000,
                                "budget_period_start": (
                                    "2026-07-27T12:00:00+00:00"
                                ),
                                "budget_period_end": (
                                    "2026-08-03T12:00:00+00:00"
                                ),
                                "current_search_bid_micros": 50_000_000,
                                "ad_variant": "A",
                                "object_config_version": "config-v1",
                                "last_change_author": "sviridov",
                                "last_change_occurred_at": (
                                    "2026-07-30T11:00:00+00:00"
                                ),
                            }
                        ],
                    }
                ).encode(),
            )
        raise AssertionError("Unknown endpoint.")


class YandexEndpointDescriptorTests(unittest.TestCase):
    def test_descriptor_is_the_single_source_for_url_and_audit_metadata(
        self,
    ) -> None:
        self.assertEqual(
            "https://api.direct.yandex.com/json/v501/reports",
            DIRECT_REPORTS_READ.base_url,
        )
        self.assertTrue(
            DIRECT_REPORTS_READ.allows(
                method="POST",
                url=DIRECT_REPORTS_READ.base_url,
            )
        )
        self.assertFalse(
            DIRECT_REPORTS_READ.allows(
                method="GET",
                url=DIRECT_REPORTS_READ.base_url,
            )
        )
        self.assertEqual(
            {
                "system": "DIRECT_REPORTS",
                "http_method": "POST",
                "host": "api.direct.yandex.com",
                "path": "/json/v501/reports",
                "operation": "get",
            },
            DIRECT_REPORTS_READ.audit_record(),
        )
        self.assertTrue(
            METRIKA_REPORT_READ.allows(
                method="GET",
                url=METRIKA_REPORT_READ.base_url + "?ids=123",
            )
        )
        self.assertFalse(
            METRIKA_REPORT_READ.allows(
                method="GET",
                url=METRIKA_REPORT_READ.base_url + "#redirect",
            )
        )

    def test_campaign_descriptor_rejects_a_mutating_json_method_before_egress(
        self,
    ) -> None:
        transport = UrllibHttpClient(
            (
                DIRECT_REPORTS_READ,
                DIRECT_CAMPAIGN_STATE_READ,
            )
        )

        with (
            patch("urllib.request.urlopen") as urlopen,
            self.assertRaisesRegex(ValueError, "not allowlisted"),
        ):
            transport.perform(
                endpoint=DIRECT_CAMPAIGN_STATE_READ,
                url=DIRECT_CAMPAIGN_STATE_READ.base_url,
                headers={"Content-Type": "application/json"},
                body=b'{"method":"update","params":{}}',
            )

        urlopen.assert_not_called()

    def test_campaign_descriptor_rejects_ambiguous_json_before_egress(
        self,
    ) -> None:
        transport = UrllibHttpClient(
            (
                DIRECT_REPORTS_READ,
                DIRECT_CAMPAIGN_STATE_READ,
            )
        )

        with (
            patch("urllib.request.urlopen") as urlopen,
            self.assertRaisesRegex(ValueError, "not allowlisted"),
        ):
            transport.perform(
                endpoint=DIRECT_CAMPAIGN_STATE_READ,
                url=DIRECT_CAMPAIGN_STATE_READ.base_url,
                headers={"Content-Type": "application/json"},
                body=b'{"method":"update","method":"get","params":{}}',
            )

        urlopen.assert_not_called()

    def test_direct_transport_rejects_a_metrika_descriptor_before_egress(
        self,
    ) -> None:
        transport = UrllibHttpClient(
            (
                DIRECT_REPORTS_READ,
                DIRECT_CAMPAIGN_STATE_READ,
            )
        )

        with (
            patch("urllib.request.urlopen") as urlopen,
            self.assertRaisesRegex(ValueError, "not allowlisted"),
        ):
            transport.perform(
                endpoint=METRIKA_REPORT_READ,
                url=METRIKA_REPORT_READ.base_url + "?ids=counter-1",
                headers={},
                body=None,
            )

        urlopen.assert_not_called()


class IndependentProductionProviderTests(unittest.TestCase):
    def test_direct_read_needs_only_direct_configuration_and_credentials(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configuration_path = root / "direct.json"
            configuration_path.write_text(
                json.dumps(
                    {
                        "connection_id": "direct-connection",
                        "account_id": "account-1",
                        "campaign_id": "campaign-1",
                        "trusted_change_author": "sviridov",
                    }
                ),
                encoding="utf-8",
            )
            environment_path = root / ".env"
            environment_path.write_text(
                "YANDEX_DIRECT_OAUTH_TOKEN=direct-token\n"
                "YANDEX_DIRECT_CLIENT_LOGIN=direct-login\n",
                encoding="utf-8",
            )
            settings = DirectProductionReadSettingsV1.from_path(
                configuration_path
            )
            http = RecordingHttpClient()
            provider = DirectProductionReadProviderV1(
                settings=settings,
                token=DotenvValue(
                    environment_path,
                    "YANDEX_DIRECT_OAUTH_TOKEN",
                ),
                client_login=DotenvValue(
                    environment_path,
                    "YANDEX_DIRECT_CLIENT_LOGIN",
                ),
                http_client=http,
            )

            report = provider.read_direct_report(
                "direct-connection",
                DirectReportsReadQuery(
                    account="account-1",
                    campaign="campaign-1",
                    period_start="2026-07-29",
                    period_end="2026-07-29",
                    attribution="AUTO",
                ),
            )

            self.assertEqual("campaign-1", report.rows[0].campaign)
            self.assertEqual(DIRECT_REPORTS_READ, http.calls[0][0])
            self.assertEqual(
                "Bearer direct-token",
                http.calls[0][2]["Authorization"],
            )

    def test_metrika_read_needs_only_metrika_configuration_and_credentials(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configuration_path = root / "metrika.json"
            configuration_path.write_text(
                json.dumps(
                    {
                        "connection_id": "metrika-connection",
                        "counter_id": "counter-1",
                        "goal_id": "goal-1",
                        "campaign_id": "campaign-1",
                    }
                ),
                encoding="utf-8",
            )
            environment_path = root / ".env"
            environment_path.write_text(
                "YANDEX_METRIKA_OAUTH_TOKEN=metrika-token\n",
                encoding="utf-8",
            )
            settings = MetrikaProductionReadSettingsV1.from_path(
                configuration_path
            )
            http = RecordingHttpClient()
            provider = MetrikaProductionReadProviderV1(
                settings=settings,
                token=DotenvValue(
                    environment_path,
                    "YANDEX_METRIKA_OAUTH_TOKEN",
                ),
                http_client=http,
            )

            report = provider.read_metrika_report(
                "metrika-connection",
                MetrikaReportReadQuery(
                    counter="counter-1",
                    campaign="campaign-1",
                    goal="goal-1",
                    period_start="2026-07-29",
                    period_end="2026-07-29",
                    attribution="automatic",
                ),
            )

            self.assertEqual("goal-1", report.rows[0].goal)
            self.assertEqual(METRIKA_REPORT_READ, http.calls[0][0])
            self.assertEqual(
                "OAuth metrika-token",
                http.calls[0][2]["Authorization"],
            )


class ConcurrentOutcomeHttpClient(RecordingHttpClient):
    def __init__(self) -> None:
        super().__init__()
        self._direct_reports_barrier = threading.Barrier(2)
        self._metrika_lock = threading.Lock()
        self._metrika_calls = 0

    def perform(
        self,
        *,
        endpoint: YandexReadEndpoint,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> HttpResponse:
        if endpoint == DIRECT_REPORTS_READ:
            self._direct_reports_barrier.wait(timeout=5)
        if endpoint == METRIKA_REPORT_READ:
            with self._metrika_lock:
                self._metrika_calls += 1
                should_fail = self._metrika_calls == 1
            if should_fail:
                raise RuntimeError("Metrika read failed before response.")
        return super().perform(
            endpoint=endpoint,
            url=url,
            headers=headers,
            body=body,
        )


class PairedProductionCompositionTests(unittest.TestCase):
    def test_split_provider_configs_build_one_explicitly_linked_snapshot(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            direct_path = root / "direct.json"
            direct_path.write_text(
                json.dumps(
                    {
                        "connection_id": "direct-connection",
                        "account_id": "account-1",
                        "campaign_id": "campaign-1",
                        "trusted_change_author": "sviridov",
                    }
                ),
                encoding="utf-8",
            )
            metrika_path = root / "metrika.json"
            metrika_path.write_text(
                json.dumps(
                    {
                        "connection_id": "metrika-connection",
                        "counter_id": "counter-1",
                        "goal_id": "goal-1",
                        "campaign_id": "campaign-1",
                    }
                ),
                encoding="utf-8",
            )
            paired_path = root / "paired.json"
            paired_path.write_text(
                json.dumps(
                    {
                        "organization_id": "organization-1",
                        "paired_connection_id": "paired-connection",
                        "period_days": 1,
                        "baseline": {
                            "source_campaign": "baseline-1",
                            "impressions": 8_000,
                            "clicks": 180,
                            "cost_micros": 4_000_000_000,
                            "visits": 260,
                            "goal_visits": 4,
                        },
                    }
                ),
                encoding="utf-8",
            )
            environment_path = root / ".env"
            environment_path.write_text(
                "YANDEX_DIRECT_OAUTH_TOKEN=direct-token\n"
                "YANDEX_DIRECT_CLIENT_LOGIN=direct-login\n"
                "YANDEX_METRIKA_OAUTH_TOKEN=metrika-token\n",
                encoding="utf-8",
            )
            direct_http = RecordingHttpClient()
            metrika_http = RecordingHttpClient()
            reader = PairedYandexProductionReaderV1(
                paired_configuration_path=paired_path,
                direct_configuration_path=direct_path,
                metrika_configuration_path=metrika_path,
                direct_environment_path=environment_path,
                metrika_environment_path=environment_path,
                direct_http_client=direct_http,
                metrika_http_client=metrika_http,
            )
            policy = load_observe_policy(
                Path(__file__).resolve().parents[1]
                / "config"
                / "gate0-policy.json"
            )

            result = reader.collect_snapshot(
                policy=policy,
                observation_id="paired-production-1",
                generated_at=datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
            )

            snapshot = result.snapshot
            self.assertEqual(
                [
                    DIRECT_REPORTS_READ,
                    DIRECT_CAMPAIGN_STATE_READ,
                ],
                [call[0] for call in direct_http.calls],
            )
            self.assertEqual(
                [METRIKA_REPORT_READ],
                [call[0] for call in metrika_http.calls],
            )
            self.assertTrue(
                all(
                    call[2]["Authorization"].startswith("Bearer ")
                    for call in direct_http.calls
                )
            )
            self.assertTrue(
                all(
                    call[2]["Authorization"].startswith("OAuth ")
                    for call in metrika_http.calls
                )
            )
            self.assertEqual(
                tuple(
                    endpoint.audit_record()
                    for endpoint in (
                        DIRECT_REPORTS_READ,
                        DIRECT_CAMPAIGN_STATE_READ,
                        METRIKA_REPORT_READ,
                    )
                ),
                tuple(receipt.as_dict() for receipt in result.receipts),
            )
            self.assertEqual("COMPARABLE", snapshot.comparability_status)
            self.assertEqual("READY", snapshot.confidence_status)

    def test_concurrent_success_and_failure_keep_only_their_own_receipts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            direct_path = root / "direct.json"
            direct_path.write_text(
                json.dumps(
                    {
                        "connection_id": "direct-connection",
                        "account_id": "account-1",
                        "campaign_id": "campaign-1",
                        "trusted_change_author": "sviridov",
                    }
                ),
                encoding="utf-8",
            )
            metrika_path = root / "metrika.json"
            metrika_path.write_text(
                json.dumps(
                    {
                        "connection_id": "metrika-connection",
                        "counter_id": "counter-1",
                        "goal_id": "goal-1",
                        "campaign_id": "campaign-1",
                    }
                ),
                encoding="utf-8",
            )
            paired_path = root / "paired.json"
            paired_path.write_text(
                json.dumps(
                    {
                        "organization_id": "organization-1",
                        "paired_connection_id": "paired-connection",
                        "period_days": 1,
                        "baseline": {
                            "source_campaign": "baseline-1",
                            "impressions": 8_000,
                            "clicks": 180,
                            "cost_micros": 4_000_000_000,
                            "visits": 260,
                            "goal_visits": 4,
                        },
                    }
                ),
                encoding="utf-8",
            )
            environment_path = root / ".env"
            environment_path.write_text(
                "YANDEX_DIRECT_OAUTH_TOKEN=direct-token\n"
                "YANDEX_DIRECT_CLIENT_LOGIN=direct-login\n"
                "YANDEX_METRIKA_OAUTH_TOKEN=metrika-token\n",
                encoding="utf-8",
            )
            http = ConcurrentOutcomeHttpClient()
            reader = PairedYandexProductionReaderV1(
                paired_configuration_path=paired_path,
                direct_configuration_path=direct_path,
                metrika_configuration_path=metrika_path,
                direct_environment_path=environment_path,
                metrika_environment_path=environment_path,
                direct_http_client=http,
                metrika_http_client=http,
            )
            policy = load_observe_policy(
                Path(__file__).resolve().parents[1]
                / "config"
                / "gate0-policy.json"
            )

            def collect(index: int) -> object:
                try:
                    return reader.collect_snapshot(
                        policy=policy,
                        observation_id=f"parallel-{index}",
                        generated_at=datetime(
                            2026,
                            7,
                            30,
                            12,
                            index,
                            tzinfo=timezone.utc,
                        ),
                    )
                except PairedProductionReadFailure as error:
                    return error

            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(collect, (1, 2)))

            success = next(
                outcome
                for outcome in outcomes
                if isinstance(outcome, PairedProductionReadResultV1)
            )
            failure = next(
                outcome
                for outcome in outcomes
                if isinstance(outcome, PairedProductionReadFailure)
            )
            self.assertEqual(
                ["DIRECT_REPORTS", "DIRECT", "METRIKA"],
                [receipt.system for receipt in success.receipts],
            )
            self.assertEqual(
                ["DIRECT_REPORTS", "DIRECT"],
                [receipt.system for receipt in failure.receipts],
            )

    def test_paired_root_contains_no_provider_credential_names(self) -> None:
        source = Path(mox_adv.paired_production.__file__).read_text(
            encoding="utf-8"
        )

        self.assertNotIn("YANDEX_DIRECT_OAUTH_TOKEN", source)
        self.assertNotIn("YANDEX_DIRECT_CLIENT_LOGIN", source)
        self.assertNotIn("YANDEX_METRIKA_OAUTH_TOKEN", source)


if __name__ == "__main__":
    unittest.main()
