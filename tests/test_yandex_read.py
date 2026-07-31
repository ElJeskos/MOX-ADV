from __future__ import annotations

import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from mox_adv.contracts import VersionedReadRequest
from mox_adv.egress import EgressDenied
from mox_adv.model_provider import DeterministicFakeModelProvider
from mox_adv.recommend_projection import build_sanitized_projection
from mox_adv.ui_service import UiRunService, _projection_source
from mox_adv.yandex_read import (
    DotEnvCredentialProvider,
    HttpResponse,
    MacOSKeychainCredentialProvider,
    ProductionReadConfiguration,
    UrllibHttpClient,
    YandexProductionReader,
    YandexReadOnlyTransport,
)


DIRECT_TOKEN = "direct-token-must-never-leak"
METRIKA_TOKEN = "metrika-token-must-never-leak"
UNRELATED_TOKEN = "unrelated-token-must-never-leak"


def prepare_production_read_configuration(root: Path) -> Path:
    configuration_path = root / "production-read.json"
    configuration_path.write_text(
        json.dumps(
            {
                "schema_version": "mox-adv-production-read-v1",
                "organization": "payplaine",
                "connection": "yandex-production",
                "direct_account": None,
                "direct_client_login": None,
                "campaign_id": "12345",
                "metrika_counter_id": None,
                "metrika_goal_id": "54321",
                "currency": "RUB",
                "lookback_days": 1,
            }
        ),
        encoding="utf-8",
    )
    return configuration_path


def prepare_production_read_inputs(root: Path) -> tuple[Path, Path]:
    environment_path = root / ".env"
    environment_path.write_text(
        "\n".join(
            (
                "YANDEX_DIRECT_OAUTH_TOKEN=" + DIRECT_TOKEN,
                "YANDEX_DIRECT_CLIENT_LOGIN=payplaine-direct",
                "YANDEX_METRICA_OAUTH_TOKEN=" + METRIKA_TOKEN,
                "YANDEX_METRICA_COUNTER_IDS=67890",
                "UNRELATED_SECRET=" + UNRELATED_TOKEN,
                "",
            )
        ),
        encoding="utf-8",
    )
    environment_path.chmod(0o600)
    configuration_path = prepare_production_read_configuration(root)
    return configuration_path, environment_path


def build_test_production_reader(
    root: Path,
    **kwargs: object,
) -> YandexProductionReader:
    with patch("mox_adv.yandex_read.ROOT", root):
        return YandexProductionReader(**kwargs)


class StubCredentials:
    def get(self, binding: str) -> str:
        return {
            "MOX_ADV_DIRECT_PROD_READ": DIRECT_TOKEN,
            "MOX_ADV_METRIKA_PROD_READ": METRIKA_TOKEN,
        }[binding]

    def has(self, binding: str) -> bool:
        return binding in {
            "MOX_ADV_DIRECT_PROD_READ",
            "MOX_ADV_METRIKA_PROD_READ",
        }


class RecordingHttpClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def perform(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: int,
    ) -> HttpResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": body,
                "timeout_seconds": timeout_seconds,
            }
        )
        if url.endswith("/json/v501/reports"):
            assert body is not None
            report_parameters = json.loads(body)["params"]["SelectionCriteria"]
            report_date = str(report_parameters["DateFrom"])
            return HttpResponse(
                status=200,
                headers={"content-type": "text/tab-separated-values"},
                body=(
                    b"Date\tCampaignId\tImpressions\tClicks\tCost\n"
                    + report_date.encode("utf-8")
                    + b"\t12345\t100\t10\t250000000\n"
                ),
            )
        if url.endswith("/json/v501/campaigns"):
            return HttpResponse(
                status=200,
                headers={"content-type": "application/json"},
                body=json.dumps(
                    {
                        "result": {
                            "Campaigns": [
                                {
                                    "Id": 12345,
                                    "Name": "Read only campaign",
                                    "Type": "UNIFIED_CAMPAIGN",
                                    "Status": "ACCEPTED",
                                    "State": "ON",
                                    "StartDate": "2026-01-01",
                                    "TimeZone": "Europe/Moscow",
                                    "UnifiedCampaign": {
                                        "AttributionModel": "AUTO",
                                        "BiddingStrategy": {
                                            "Search": {
                                                "BiddingStrategyType": ("AVERAGE_CPC"),
                                                "AverageCpc": {
                                                    "WeeklySpendLimit": 3_000_000_000,
                                                    "AverageCpc": 90_000_000,
                                                },
                                            }
                                        },
                                    },
                                }
                            ]
                        }
                    }
                ).encode("utf-8"),
            )
        if url.startswith("https://api-metrika.yandex.net/stat/v1/data?"):
            report_date = parse_qs(urlsplit(url).query)["date1"][0]
            return HttpResponse(
                status=200,
                headers={"content-type": "application/json"},
                body=json.dumps(
                    {
                        "data": [
                            {
                                "dimensions": [
                                    {"name": report_date},
                                    {
                                        "id": "12345",
                                        "name": "Read only campaign",
                                    },
                                ],
                                "metrics": [12.0, 2.0],
                            }
                        ]
                    }
                ).encode("utf-8"),
            )
        raise AssertionError(f"Unexpected request: {method} {url}")


def configuration() -> ProductionReadConfiguration:
    return ProductionReadConfiguration(
        organization="payplaine",
        connection="yandex-production",
        direct_account="payplaine-direct",
        direct_client_login="payplaine-direct",
        campaign_id="12345",
        metrika_counter_id="67890",
        metrika_goal_id="54321",
        currency="RUB",
        lookback_days=1,
    )


def report_request() -> VersionedReadRequest:
    return VersionedReadRequest(
        system="DIRECT_REPORTS",
        host="api.direct.yandex.com",
        path="/json/v501/reports",
        version="v501",
        service="Reports",
        method="get",
        http_verb="POST",
        payload={
            "account": "payplaine-direct",
            "campaign": "12345",
            "period_start": "2026-07-28",
            "period_end": "2026-07-28",
            "attribution": "AUTO",
        },
    )


class TickingClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value


class YandexReadOnlyTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.http = RecordingHttpClient()
        self.transport = YandexReadOnlyTransport(
            configuration=configuration(),
            credential_provider=StubCredentials(),
            http_client=self.http,
            clock=lambda: datetime(
                2026,
                7,
                29,
                12,
                tzinfo=timezone.utc,
            ),
        )

    def test_reads_only_the_three_exact_yandex_operations(self) -> None:
        direct_state = self.transport.read(
            VersionedReadRequest(
                system="DIRECT",
                host="api.direct.yandex.com",
                path="/json/v501/campaigns",
                version="v501",
                service="Campaigns",
                method="get",
                http_verb="POST",
                payload={
                    "account": "payplaine-direct",
                    "campaign": "12345",
                },
            )
        )
        direct_report = self.transport.read(report_request())
        metrika_report = self.transport.read(
            VersionedReadRequest(
                system="METRIKA",
                host="api-metrika.yandex.net",
                path="/stat/v1/data",
                version="v1",
                service="Statistics",
                method="get",
                http_verb="GET",
                payload={
                    "counter": "67890",
                    "campaign": "12345",
                    "goal": "54321",
                    "period_start": "2026-07-28",
                    "period_end": "2026-07-28",
                    "attribution": "automatic",
                },
            )
        )

        self.assertEqual(250_000_000, direct_report.rows[0].cost_micros)
        self.assertEqual(3_000_000_000, direct_state.current_weekly_budget_micros)
        self.assertEqual(90_000_000, direct_state.current_search_bid_micros)
        self.assertEqual(12, metrika_report.rows[0].visits)
        self.assertEqual(2, metrika_report.rows[0].goal_visits)
        self.assertEqual(
            [
                ("POST", "/json/v501/campaigns"),
                ("POST", "/json/v501/reports"),
                ("GET", "/stat/v1/data"),
            ],
            [
                (
                    record["http_method"],
                    record["path"],
                )
                for record in self.transport.records
            ],
        )
        direct_headers = self.http.calls[0]["headers"]
        metrika_headers = self.http.calls[2]["headers"]
        assert isinstance(direct_headers, dict)
        assert isinstance(metrika_headers, dict)
        self.assertEqual(f"Bearer {DIRECT_TOKEN}", direct_headers["Authorization"])
        self.assertEqual(f"OAuth {METRIKA_TOKEN}", metrika_headers["Authorization"])
        self.assertIn(
            "timezone=%2B03%3A00",
            str(self.http.calls[2]["url"]),
        )
        self.assertEqual("Europe/Moscow", direct_report.timezone)
        self.assertEqual("Europe/Moscow", metrika_report.timezone)
        self.assertNotIn(DIRECT_TOKEN, json.dumps(self.transport.records))
        self.assertNotIn(METRIKA_TOKEN, json.dumps(self.transport.records))

    def test_rejects_any_non_allowlisted_request_before_http(self) -> None:
        cases = (
            report_request().__class__(
                **{**report_request().__dict__, "method": "add"}
            ),
            report_request().__class__(
                **{**report_request().__dict__, "path": "/json/v501/campaigns"}
            ),
            report_request().__class__(
                **{**report_request().__dict__, "http_verb": "PUT"}
            ),
        )

        for request in cases:
            with self.subTest(request=request), self.assertRaises(EgressDenied):
                self.transport.read(request)

        self.assertEqual([], self.http.calls)

    def test_response_errors_do_not_disclose_credentials(self) -> None:
        class FailingHttpClient(RecordingHttpClient):
            def perform(self, **kwargs: object) -> HttpResponse:
                del kwargs
                return HttpResponse(
                    status=500,
                    headers={"content-type": "application/json"},
                    body=(
                        b'{"error":"'
                        + DIRECT_TOKEN.encode("utf-8")
                        + b" "
                        + METRIKA_TOKEN.encode("utf-8")
                        + b'"}'
                    ),
                )

        transport = YandexReadOnlyTransport(
            configuration=configuration(),
            credential_provider=StubCredentials(),
            http_client=FailingHttpClient(),
            clock=lambda: datetime(
                2026,
                7,
                29,
                12,
                tzinfo=timezone.utc,
            ),
        )

        with self.assertRaises(RuntimeError) as rejected:
            transport.read(report_request())

        message = str(rejected.exception)
        self.assertNotIn(DIRECT_TOKEN, message)
        self.assertNotIn(METRIKA_TOKEN, message)

    def test_keychain_lookup_is_bound_to_service_and_account(self) -> None:
        with patch("mox_adv.yandex_read.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = b"read-token\n"
            provider = MacOSKeychainCredentialProvider(account="dashboard-user")

            self.assertTrue(provider.has("MOX_ADV_DIRECT_PROD_READ"))
            self.assertEqual(
                "read-token",
                provider.get("MOX_ADV_DIRECT_PROD_READ"),
            )

        for call in run.call_args_list:
            arguments = call.args[0]
            self.assertIn("-a", arguments)
            self.assertEqual(
                "dashboard-user",
                arguments[arguments.index("-a") + 1],
            )
            self.assertIn("-s", arguments)
            self.assertEqual(
                "MOX_ADV_DIRECT_PROD_READ",
                arguments[arguments.index("-s") + 1],
            )

    def test_http_error_response_is_closed_after_bounded_read(self) -> None:
        body = io.BytesIO(b'{"error":"safe"}')
        error = HTTPError(
            "https://api.direct.yandex.com/json/v501/campaigns",
            500,
            "failure",
            {},
            body,
        )

        class FailingOpener:
            def open(self, *args: object, **kwargs: object) -> object:
                del args, kwargs
                raise error

        response = UrllibHttpClient(opener=FailingOpener()).perform(
            method="POST",
            url="https://api.direct.yandex.com/json/v501/campaigns",
            headers={},
            body=b"{}",
            timeout_seconds=1,
        )

        self.assertEqual(500, response.status)
        self.assertTrue(body.closed)

    def test_reader_lists_account_campaigns_with_direct_read_only_access(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment_path = root / ".env"
            environment_path.write_text(
                "\n".join(
                    (
                        "YANDEX_DIRECT_OAUTH_TOKEN=" + DIRECT_TOKEN,
                        "YANDEX_DIRECT_CLIENT_LOGIN=payplaine-direct",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            environment_path.chmod(0o600)
            http_client = RecordingHttpClient()
            reader = build_test_production_reader(
                root,
                environment_path=environment_path,
                http_client=http_client,
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    9,
                    tzinfo=timezone.utc,
                ),
            )
            policy = json.loads(
                (
                    Path(__file__).resolve().parents[1]
                    / "config"
                    / "gate0-policy.json"
                ).read_text(encoding="utf-8")
            )

            readiness = reader.campaign_catalog_readiness(policy)
            catalog = reader.list_campaigns(policy=policy)

            self.assertTrue(readiness["ready"])
            self.assertEqual("READ_ONLY", catalog["access"])
            self.assertFalse(catalog["write_requests_allowed"])
            self.assertEqual("payplaine-direct", catalog["account"])
            self.assertEqual(1, catalog["total"])
            self.assertEqual("12345", catalog["items"][0]["campaign_id"])
            self.assertEqual(
                "Read only campaign",
                catalog["items"][0]["name"],
            )
            self.assertEqual(1, len(http_client.calls))
            call = http_client.calls[0]
            self.assertEqual("POST", call["method"])
            request = json.loads(bytes(call["body"]).decode("utf-8"))
            self.assertEqual("get", request["method"])
            self.assertEqual(
                {},
                request["params"]["SelectionCriteria"],
            )
            self.assertEqual(
                {"Limit": 500, "Offset": 0},
                request["params"]["Page"],
            )
            serialized = json.dumps(catalog, ensure_ascii=False)
            self.assertNotIn(DIRECT_TOKEN, serialized)
            self.assertNotIn(METRIKA_TOKEN, serialized)
            self.assertEqual(
                [
                    {
                        "system": "DIRECT",
                        "http_method": "POST",
                        "host": "api.direct.yandex.com",
                        "path": "/json/v501/campaigns",
                        "operation": "get",
                    }
                ],
                list(reader.last_catalog_records),
            )

    def test_real_reader_builds_a_projection_after_all_reads_complete(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configuration_path, environment_path = prepare_production_read_inputs(root)
            clock = TickingClock(datetime(2026, 7, 29, 12, tzinfo=timezone.utc))
            http_client = RecordingHttpClient()
            reader = build_test_production_reader(
                root,
                configuration_path=configuration_path,
                environment_path=environment_path,
                http_client=http_client,
                clock=clock,
            )
            policy = json.loads(
                (
                    Path(__file__).resolve().parents[1] / "config" / "gate0-policy.json"
                ).read_text(encoding="utf-8")
            )

            snapshot = reader.collect_snapshot(
                policy=policy,
                observation_id="real-reader-projection",
                generated_at=datetime(
                    2026,
                    7,
                    29,
                    12,
                    tzinfo=timezone.utc,
                ),
            )
            projection = build_sanitized_projection(
                _projection_source(snapshot.as_dict()),
                policy,
            )

            self.assertEqual("PARTIAL", snapshot.comparability_status)
            self.assertFalse(snapshot.financial_recommendations_allowed)
            self.assertIn(
                "BASELINE_UNAVAILABLE",
                snapshot.data_quality_gaps,
            )
            self.assertIn(
                "CHANGE_PROVENANCE_UNAVAILABLE",
                snapshot.data_quality_gaps,
            )
            self.assertEqual("Europe/Moscow", projection["timezone"])
            self.assertEqual("AVERAGE_CPC", projection["campaign_strategy"])
            self.assertEqual("NOT_REQUESTED", projection["current_ad_variant"])
            self.assertEqual(
                ["ANALYTICS_CONTEXT_INCOMPLETE"],
                projection["observed_facts"],
            )
            recommendation = DeterministicFakeModelProvider().generate(projection)
            self.assertEqual("NEEDS_HUMAN", recommendation.payload["status"])
            self.assertIn(
                "baseline",
                recommendation.payload["explanation_ru"],
            )
            self.assertNotIn(
                "расходятся",
                recommendation.payload["explanation_ru"],
            )
            retrieved = [
                datetime.fromisoformat(entry["retrieved_at"])
                for entry in snapshot.as_dict()["provenance"].values()
            ]
            self.assertGreaterEqual(
                datetime.fromisoformat(snapshot.generated_at),
                max(retrieved),
            )

    def test_real_reader_uses_one_immutable_dotenv_snapshot_per_run(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configuration_path, environment_path = prepare_production_read_inputs(root)
            reader = build_test_production_reader(
                root,
                configuration_path=configuration_path,
                environment_path=environment_path,
                http_client=RecordingHttpClient(),
            )
            policy = json.loads(
                (
                    Path(__file__).resolve().parents[1] / "config" / "gate0-policy.json"
                ).read_text(encoding="utf-8")
            )
            provider = reader.credential_provider
            assert isinstance(provider, DotEnvCredentialProvider)

            with patch.object(
                provider,
                "_load",
                wraps=provider._load,
            ) as load:
                reader.collect_snapshot(
                    policy=policy,
                    observation_id="one-dotenv-snapshot",
                    generated_at=datetime(
                        2026,
                        7,
                        29,
                        12,
                        tzinfo=timezone.utc,
                    ),
                )

            self.assertEqual(1, load.call_count)

    def test_main_ui_uses_the_real_reader_and_reports_missing_context(
        self,
    ) -> None:
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
            service = UiRunService(
                root / "runs",
                production_reader=reader,
            )

            readiness = service.status()["production_mode"]
            report = service.run("production")
            serialized_readiness = json.dumps(
                readiness,
                ensure_ascii=False,
            )

            self.assertTrue(readiness["ready"])
            self.assertNotIn(DIRECT_TOKEN, serialized_readiness)
            self.assertNotIn(METRIKA_TOKEN, serialized_readiness)
            self.assertNotIn(UNRELATED_TOKEN, serialized_readiness)
            self.assertTrue(
                all(
                    ".env" in item["label"]
                    for item in readiness["checks"]
                    if item["id"].endswith("_read_credential")
                )
            )
            self.assertEqual("PRODUCTION_READ_ONLY", report["mode"])
            self.assertEqual("payplaine-direct", report["scope"]["account"])
            self.assertEqual("67890", report["scope"]["counter"])
            direct_headers = [
                call["headers"]
                for call in http_client.calls
                if "api.direct.yandex.com" in str(call["url"])
            ]
            self.assertTrue(direct_headers)
            self.assertTrue(
                all(
                    headers.get("Client-Login") == "payplaine-direct"
                    for headers in direct_headers
                    if isinstance(headers, Mapping)
                )
            )
            self.assertEqual("NEEDS_HUMAN", report["recommendation"]["status"])
            self.assertEqual("NO_CHANGE", report["recommendation"]["action"])
            self.assertTrue(
                {
                    "BASELINE_UNAVAILABLE",
                    "CHANGE_PROVENANCE_UNAVAILABLE",
                }.issubset(set(report["data_quality"]["gaps"]))
            )
            self.assertEqual(3, len(report["safety"]["read_requests"]))
            self.assertFalse(report["safety"]["write_requests_allowed"])
            self.assertFalse(report["safety"]["executor_invoked"])
            self.assertNotIn(
                UNRELATED_TOKEN,
                json.dumps(report, ensure_ascii=False),
            )
            html = service.html_report_path(report["run_id"]).read_text(
                encoding="utf-8"
            )
            self.assertIn("Статус рекомендации: NEEDS_HUMAN", html)
            self.assertIn("BASELINE_UNAVAILABLE", html)

    def test_main_ui_emits_confirmed_progress_at_real_stage_boundaries(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configuration_path, environment_path = prepare_production_read_inputs(root)
            reader = build_test_production_reader(
                root,
                configuration_path=configuration_path,
                environment_path=environment_path,
                http_client=RecordingHttpClient(),
            )
            service = UiRunService(
                root / "runs",
                production_reader=reader,
            )
            events: list[dict[str, str]] = []

            service.run("production", progress_callback=events.append)

            self.assertEqual(
                [
                    {"step": "direct", "status": "RUNNING"},
                    {"step": "direct", "status": "PASSED"},
                    {"step": "metrika", "status": "RUNNING"},
                    {"step": "metrika", "status": "PASSED"},
                    {"step": "analytics", "status": "RUNNING"},
                    {"step": "analytics", "status": "PASSED"},
                    {"step": "recommend", "status": "RUNNING"},
                    {"step": "recommend", "status": "PASSED"},
                    {"step": "apply", "status": "SKIPPED"},
                ],
                events,
            )

    def test_main_ui_rejects_unprotected_dotenv_without_exposing_tokens(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment_path = root / ".env"
            environment_path.write_text(
                "\n".join(
                    (
                        "YANDEX_DIRECT_OAUTH_TOKEN=" + DIRECT_TOKEN,
                        "YANDEX_METRICA_OAUTH_TOKEN=" + METRIKA_TOKEN,
                        "",
                    )
                ),
                encoding="utf-8",
            )
            environment_path.chmod(0o644)
            reader = build_test_production_reader(
                root,
                configuration_path=root / "missing-production-read.json",
                environment_path=environment_path,
            )
            service = UiRunService(
                root / "runs",
                production_reader=reader,
            )

            readiness = service.status()["production_mode"]
            serialized = json.dumps(readiness, ensure_ascii=False)

            self.assertFalse(readiness["ready"])
            self.assertIn("chmod 600", serialized)
            self.assertNotIn(DIRECT_TOKEN, serialized)
            self.assertNotIn(METRIKA_TOKEN, serialized)

    def test_main_ui_rejects_symlinked_dotenv_without_exposing_tokens(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target_path = root / "tokens"
            target_path.write_text(
                "\n".join(
                    (
                        "YANDEX_DIRECT_OAUTH_TOKEN=" + DIRECT_TOKEN,
                        "YANDEX_METRICA_OAUTH_TOKEN=" + METRIKA_TOKEN,
                        "",
                    )
                ),
                encoding="utf-8",
            )
            target_path.chmod(0o600)
            environment_path = root / ".env"
            environment_path.symlink_to(target_path)
            reader = build_test_production_reader(
                root,
                configuration_path=root / "missing-production-read.json",
                environment_path=environment_path,
            )
            service = UiRunService(
                root / "runs",
                production_reader=reader,
            )

            readiness = service.status()["production_mode"]
            serialized = json.dumps(readiness, ensure_ascii=False)

            self.assertFalse(readiness["ready"])
            self.assertIn("символической ссылкой", serialized)
            self.assertNotIn(DIRECT_TOKEN, serialized)
            self.assertNotIn(METRIKA_TOKEN, serialized)

    def test_main_ui_does_not_import_tokens_from_process_environment(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reader = build_test_production_reader(
                root,
                configuration_path=root / "missing-production-read.json",
                environment_path=root / ".env",
            )
            service = UiRunService(
                root / "runs",
                production_reader=reader,
            )

            with patch.dict(
                "os.environ",
                {
                    "YANDEX_DIRECT_OAUTH_TOKEN": DIRECT_TOKEN,
                    "YANDEX_METRICA_OAUTH_TOKEN": METRIKA_TOKEN,
                },
            ):
                readiness = service.status()["production_mode"]
            serialized = json.dumps(readiness, ensure_ascii=False)

            self.assertFalse(readiness["ready"])
            self.assertIn("Не найден локальный файл токенов", serialized)
            self.assertNotIn(DIRECT_TOKEN, serialized)
            self.assertNotIn(METRIKA_TOKEN, serialized)

    def test_main_ui_rejects_invalid_dotenv_without_exposing_values(
        self,
    ) -> None:
        cases = {
            "empty direct token": (
                (
                    "YANDEX_DIRECT_OAUTH_TOKEN=\n"
                    "YANDEX_METRICA_OAUTH_TOKEN=" + METRIKA_TOKEN
                ).encode("utf-8"),
                "YANDEX_DIRECT_OAUTH_TOKEN",
            ),
            "whitespace token": (
                (
                    'YANDEX_DIRECT_OAUTH_TOKEN="invalid token"\n'
                    "YANDEX_METRICA_OAUTH_TOKEN=" + METRIKA_TOKEN
                ).encode("utf-8"),
                "YANDEX_DIRECT_OAUTH_TOKEN",
            ),
            "control character in token": (
                (
                    "YANDEX_DIRECT_OAUTH_TOKEN=invalid\x00token\n"
                    "YANDEX_DIRECT_CLIENT_LOGIN=payplaine-direct\n"
                    "YANDEX_METRICA_OAUTH_TOKEN="
                    + METRIKA_TOKEN
                    + "\nYANDEX_METRICA_COUNTER_IDS=67890\n"
                ).encode("utf-8"),
                "YANDEX_DIRECT_OAUTH_TOKEN",
            ),
            "unicode token": (
                (
                    "YANDEX_DIRECT_OAUTH_TOKEN=токен\n"
                    "YANDEX_DIRECT_CLIENT_LOGIN=payplaine-direct\n"
                    "YANDEX_METRICA_OAUTH_TOKEN="
                    + METRIKA_TOKEN
                    + "\nYANDEX_METRICA_COUNTER_IDS=67890\n"
                ).encode("utf-8"),
                "YANDEX_DIRECT_OAUTH_TOKEN",
            ),
            "oversized token": (
                (
                    "YANDEX_DIRECT_OAUTH_TOKEN="
                    + ("a" * 4097)
                    + "\nYANDEX_METRICA_OAUTH_TOKEN="
                    + METRIKA_TOKEN
                ).encode("utf-8"),
                "YANDEX_DIRECT_OAUTH_TOKEN",
            ),
            "duplicate token": (
                (
                    "YANDEX_DIRECT_OAUTH_TOKEN=first\n"
                    "YANDEX_DIRECT_OAUTH_TOKEN=second\n"
                    "YANDEX_METRICA_OAUTH_TOKEN=" + METRIKA_TOKEN
                ).encode("utf-8"),
                "повторно определяет",
            ),
            "malformed assignment": (
                b"not-an-assignment\n",
                "некорректную строку",
            ),
            "invalid utf8": (
                b"\xff\xfe",
                "UTF-8",
            ),
            "oversized file": (
                b"#" * (64 * 1024 + 1),
                "превышает безопасный размер",
            ),
            "missing client login": (
                (
                    "YANDEX_DIRECT_OAUTH_TOKEN="
                    + DIRECT_TOKEN
                    + "\nYANDEX_DIRECT_CLIENT_LOGIN=\n"
                    + "YANDEX_METRICA_OAUTH_TOKEN="
                    + METRIKA_TOKEN
                    + "\nYANDEX_METRICA_COUNTER_IDS=67890\n"
                ).encode("utf-8"),
                "YANDEX_DIRECT_CLIENT_LOGIN",
            ),
            "control character in client login": (
                (
                    "YANDEX_DIRECT_OAUTH_TOKEN="
                    + DIRECT_TOKEN
                    + "\nYANDEX_DIRECT_CLIENT_LOGIN=payplaine\x00direct\n"
                    + "YANDEX_METRICA_OAUTH_TOKEN="
                    + METRIKA_TOKEN
                    + "\nYANDEX_METRICA_COUNTER_IDS=67890\n"
                ).encode("utf-8"),
                "YANDEX_DIRECT_CLIENT_LOGIN",
            ),
            "multiple counter ids": (
                (
                    "YANDEX_DIRECT_OAUTH_TOKEN="
                    + DIRECT_TOKEN
                    + "\nYANDEX_DIRECT_CLIENT_LOGIN=payplaine-direct\n"
                    + "YANDEX_METRICA_OAUTH_TOKEN="
                    + METRIKA_TOKEN
                    + "\nYANDEX_METRICA_COUNTER_IDS=67890,67891\n"
                ).encode("utf-8"),
                "ровно один положительный ID",
            ),
            "trailing counter separator": (
                (
                    "YANDEX_DIRECT_OAUTH_TOKEN="
                    + DIRECT_TOKEN
                    + "\nYANDEX_DIRECT_CLIENT_LOGIN=payplaine-direct\n"
                    + "YANDEX_METRICA_OAUTH_TOKEN="
                    + METRIKA_TOKEN
                    + "\nYANDEX_METRICA_COUNTER_IDS=67890,\n"
                ).encode("utf-8"),
                "ровно один положительный ID",
            ),
            "leading counter separator": (
                (
                    "YANDEX_DIRECT_OAUTH_TOKEN="
                    + DIRECT_TOKEN
                    + "\nYANDEX_DIRECT_CLIENT_LOGIN=payplaine-direct\n"
                    + "YANDEX_METRICA_OAUTH_TOKEN="
                    + METRIKA_TOKEN
                    + "\nYANDEX_METRICA_COUNTER_IDS=,67890\n"
                ).encode("utf-8"),
                "ровно один положительный ID",
            ),
            "empty counter list item": (
                (
                    "YANDEX_DIRECT_OAUTH_TOKEN="
                    + DIRECT_TOKEN
                    + "\nYANDEX_DIRECT_CLIENT_LOGIN=payplaine-direct\n"
                    + "YANDEX_METRICA_OAUTH_TOKEN="
                    + METRIKA_TOKEN
                    + "\nYANDEX_METRICA_COUNTER_IDS=67890,,67890\n"
                ).encode("utf-8"),
                "ровно один положительный ID",
            ),
            "unicode counter digits": (
                (
                    "YANDEX_DIRECT_OAUTH_TOKEN="
                    + DIRECT_TOKEN
                    + "\nYANDEX_DIRECT_CLIENT_LOGIN=payplaine-direct\n"
                    + "YANDEX_METRICA_OAUTH_TOKEN="
                    + METRIKA_TOKEN
                    + "\nYANDEX_METRICA_COUNTER_IDS=٦٧٨٩٠\n"
                ).encode("utf-8"),
                "ровно один положительный ID",
            ),
        }
        for name, (content, expected_message) in cases.items():
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    environment_path = root / ".env"
                    environment_path.write_bytes(content)
                    environment_path.chmod(0o600)
                    configuration_path = prepare_production_read_configuration(root)
                    reader = build_test_production_reader(
                        root,
                        configuration_path=configuration_path,
                        environment_path=environment_path,
                    )
                    service = UiRunService(
                        root / "runs",
                        production_reader=reader,
                    )

                    readiness = service.status()["production_mode"]
                    serialized = json.dumps(readiness, ensure_ascii=False)

                    self.assertFalse(readiness["ready"])
                    self.assertIn(expected_message, serialized)
                    self.assertNotIn(DIRECT_TOKEN, serialized)
                    self.assertNotIn(METRIKA_TOKEN, serialized)

    def test_main_ui_accepts_only_owner_read_write_or_read_only_modes(
        self,
    ) -> None:
        for mode, expected_ready in ((0o600, True), (0o400, True), (0o700, False)):
            with self.subTest(mode=oct(mode)):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    configuration_path, environment_path = (
                        prepare_production_read_inputs(root)
                    )
                    environment_path.chmod(mode)
                    reader = build_test_production_reader(
                        root,
                        configuration_path=configuration_path,
                        environment_path=environment_path,
                    )
                    service = UiRunService(
                        root / "runs",
                        production_reader=reader,
                    )

                    readiness = service.status()["production_mode"]

                    self.assertEqual(expected_ready, readiness["ready"])
                    if not expected_ready:
                        self.assertIn(
                            "chmod 600",
                            json.dumps(readiness, ensure_ascii=False),
                        )

    def test_main_ui_does_not_read_dotenv_when_policy_override_changes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configuration_path, environment_path = prepare_production_read_inputs(root)
            reader = build_test_production_reader(
                root,
                configuration_path=configuration_path,
                environment_path=environment_path,
            )
            service = UiRunService(
                root / "runs",
                production_reader=reader,
            )
            service.policy["credentials"]["local_read_only_override"][
                "write_profiles_allowed"
            ] = True

            with patch.object(
                reader.credential_provider,
                "get",
                side_effect=AssertionError(
                    "Policy mismatch must block before credential access."
                ),
            ):
                readiness = service.status()["production_mode"]

            self.assertFalse(readiness["ready"])
            self.assertIn(
                "политикой",
                json.dumps(readiness, ensure_ascii=False),
            )
            with self.assertRaisesRegex(
                RuntimeError,
                "Политика защищённого read-only",
            ):
                reader.collect_snapshot(
                    policy=service.policy,
                    observation_id="policy-mismatch",
                    generated_at=datetime.now(timezone.utc),
                )

    def test_main_ui_binds_policy_to_repo_dotenv_provider_and_path(
        self,
    ) -> None:
        class CredentialProviderSubclass(DotEnvCredentialProvider):
            def get(self, binding: str) -> str:
                del binding
                return DIRECT_TOKEN

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configuration_path, environment_path = prepare_production_read_inputs(root)
            wrong_path = root / "credentials.txt"
            wrong_path.write_bytes(environment_path.read_bytes())
            wrong_path.chmod(0o600)
            wrong_path_reader = build_test_production_reader(
                root,
                configuration_path=configuration_path,
                environment_path=wrong_path,
            )
            wrong_provider_reader = build_test_production_reader(
                root,
                configuration_path=configuration_path,
                credential_provider=object(),
            )
            subclass_provider = CredentialProviderSubclass(environment_path)
            subclass_reader = build_test_production_reader(
                root,
                configuration_path=configuration_path,
                credential_provider=subclass_provider,
            )

            for reader in (
                wrong_path_reader,
                wrong_provider_reader,
                subclass_reader,
            ):
                with self.subTest(provider=type(reader.credential_provider)):
                    service = UiRunService(
                        root / "runs",
                        production_reader=reader,
                    )

                    readiness = service.status()["production_mode"]

                    self.assertFalse(readiness["ready"])
                    self.assertIn(
                        "политикой",
                        json.dumps(readiness, ensure_ascii=False),
                    )
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "Политика защищённого read-only",
                    ):
                        reader.collect_snapshot(
                            policy=service.policy,
                            observation_id="credential-source-mismatch",
                            generated_at=datetime.now(timezone.utc),
                        )


if __name__ == "__main__":
    unittest.main()
