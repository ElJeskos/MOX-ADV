from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

from mox_adv.observe import load_observe_policy
from mox_adv.yandex_read import (
    DIRECT_REPORT_URL,
    DIRECT_STATE_URL,
    METRIKA_REPORT_URL,
    HttpResponse,
    YandexProductionReader,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "gate0-policy.json"
DIRECT_TOKEN = "direct-test-token-never-persist"
METRIKA_TOKEN = "metrika-test-token-never-persist"
OBSERVED_AT = "2026-07-30T11:55:00+00:00"
WATERMARK = "2026-07-30T11:50:00+00:00"


class RecordingHttpClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def perform(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Optional[bytes],
    ) -> HttpResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": body,
            }
        )
        if url == DIRECT_REPORT_URL:
            return HttpResponse(
                status=200,
                headers={
                    "Content-Type": "text/tab-separated-values",
                    "X-MOX-Retrieved-At": OBSERVED_AT,
                    "X-MOX-Watermark": WATERMARK,
                },
                body=(
                    "Date\tCampaignId\tImpressions\tClicks\tCost\n"
                    "2026-07-29\tproduction-campaign\t10000\t200\t5000000000\n"
                ).encode("utf-8"),
            )
        elif url == DIRECT_STATE_URL:
            payload = {
                "meta": {
                    "retrieved_at": OBSERVED_AT,
                    "watermark": WATERMARK,
                },
                "data": [
                    {
                        "campaign": "production-campaign",
                        "campaign_state": "ON",
                        "group_state": "ON",
                        "ad_state": "ON",
                        "strategy": "HIGHEST_POSITION",
                        "current_weekly_budget_micros": 10_000_000_000,
                        "budget_period_start": "2026-07-27T12:00:00+00:00",
                        "budget_period_end": "2026-08-03T12:00:00+00:00",
                        "current_search_bid_micros": 100_000_000,
                        "ad_variant": "A",
                        "object_config_version": "production-config-v1",
                        "last_change_author": "sviridov",
                        "last_change_occurred_at": (
                            "2026-07-30T11:00:00+00:00"
                        ),
                    }
                ],
            }
        elif url.startswith(METRIKA_REPORT_URL + "?"):
            payload = {
                "meta": {
                    "retrieved_at": OBSERVED_AT,
                    "watermark": WATERMARK,
                },
                "data": [
                    {
                        "dimensions": [{"name": "2026-07-29"}],
                        "metrics": [300.0, 5.0],
                    }
                ],
            }
        else:
            raise AssertionError("Unexpected provider URL: " + url)
        return HttpResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload).encode("utf-8"),
        )


def prepare_production_read_inputs(root: Path) -> tuple[Path, Path]:
    configuration_path = root / "yandex-production-read.json"
    configuration_path.write_text(
        json.dumps(
            {
                "organization_id": "production-organization",
                "paired_connection_id": "production-paired",
                "direct_connection_id": "production-direct",
                "metrika_connection_id": "production-metrika",
                "account_id": "production-account",
                "campaign_id": "production-campaign",
                "counter_id": "production-counter",
                "goal_id": "production-goal",
                "trusted_change_author": "sviridov",
                "period_days": 1,
                "baseline": {
                    "source_campaign": "production-baseline",
                    "impressions": 8_000,
                    "clicks": 180,
                    "cost_micros": 4_000_000_000,
                    "visits": 260,
                    "goal_visits": 4,
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    environment_path = root / ".env"
    environment_path.write_text(
        "\n".join(
            (
                "YANDEX_DIRECT_OAUTH_TOKEN=" + DIRECT_TOKEN,
                "YANDEX_DIRECT_CLIENT_LOGIN=payplaine-direct",
                "YANDEX_METRIKA_OAUTH_TOKEN=" + METRIKA_TOKEN,
            )
        )
        + "\n",
        encoding="utf-8",
    )
    environment_path.chmod(0o600)
    return configuration_path, environment_path


def build_test_production_reader(
    root: Path,
    *,
    configuration_path: Path,
    environment_path: Path,
    http_client: RecordingHttpClient,
) -> YandexProductionReader:
    del root
    return YandexProductionReader(
        configuration_path=configuration_path,
        environment_path=environment_path,
        http_client=http_client,
        clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
    )


class YandexProductionReaderTests(unittest.TestCase):
    def test_three_provider_reads_build_the_paired_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configuration_path, environment_path = prepare_production_read_inputs(root)
            http_client = RecordingHttpClient()
            reader = build_test_production_reader(
                root,
                configuration_path=configuration_path,
                environment_path=environment_path,
                http_client=http_client,
            )
            policy = load_observe_policy(POLICY)

            snapshot = reader.collect_snapshot(
                policy=policy,
                observation_id="production-read-1",
                generated_at=datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
            )

            self.assertEqual(3, len(http_client.calls))
            self.assertEqual(
                ["POST", "POST", "GET"],
                [call["method"] for call in http_client.calls],
            )
            self.assertTrue(
                all(
                    call["headers"]["Authorization"]
                    == "Bearer " + DIRECT_TOKEN
                    for call in http_client.calls[:2]
                )
            )
            self.assertEqual(
                "OAuth " + METRIKA_TOKEN,
                http_client.calls[2]["headers"]["Authorization"],
            )
            self.assertNotIn(
                "Client-Login",
                http_client.calls[2]["headers"],
            )
            self.assertEqual("COMPARABLE", snapshot.comparability_status)
            self.assertEqual("READY", snapshot.confidence_status)
            self.assertEqual(
                ["DIRECT_REPORTS", "DIRECT", "METRIKA"],
                [record["system"] for record in reader.last_records],
            )
            serialized = json.dumps(snapshot.as_dict(), ensure_ascii=False)
            self.assertNotIn(DIRECT_TOKEN, serialized)
            self.assertNotIn(METRIKA_TOKEN, serialized)

    def test_missing_direct_login_is_reported_without_provider_egress(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configuration_path, environment_path = prepare_production_read_inputs(root)
            environment_path.write_text(
                environment_path.read_text(encoding="utf-8").replace(
                    "YANDEX_DIRECT_CLIENT_LOGIN=payplaine-direct",
                    "YANDEX_DIRECT_CLIENT_LOGIN=",
                ),
                encoding="utf-8",
            )
            http_client = RecordingHttpClient()
            reader = build_test_production_reader(
                root,
                configuration_path=configuration_path,
                environment_path=environment_path,
                http_client=http_client,
            )

            readiness = reader.readiness(load_observe_policy(POLICY))

            self.assertFalse(readiness["ready"])
            self.assertIn(
                "YANDEX_DIRECT_CLIENT_LOGIN настроен",
                readiness["blockers"],
            )
            self.assertEqual([], http_client.calls)


if __name__ == "__main__":
    unittest.main()
