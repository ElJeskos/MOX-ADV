"""Read-only Yandex provider composition for the paired Dashboard."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Protocol, Tuple

from mox_adv.contracts import (
    BaselineAggregate,
    DirectCampaignStateBlock,
    DirectCampaignStateReadQuery,
    DirectReportBlock,
    DirectReportRow,
    DirectReportsReadQuery,
    MetrikaReportBlock,
    MetrikaReportReadQuery,
    MetrikaReportRow,
    TrustedAnalyticsScope,
)
from mox_adv.direct_provider import DirectReadAuthorizationError
from mox_adv.environment import ExecutionEnvironment
from mox_adv.metrika_provider import MetrikaReadAuthorizationError
from mox_adv.module_api.v1 import InProcessModuleAdapterV1
from mox_adv.modules.direct import DirectModuleV1
from mox_adv.modules.metrika import MetrikaModuleV1
from mox_adv.paired_runtime import PairedConnectionRefsV1, PairedModuleRuntimeV1

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIGURATION_PATH = ROOT / "config" / "yandex-production-read.json"
DEFAULT_ENVIRONMENT_PATH = ROOT / ".env"
DIRECT_REPORT_URL = "https://api.direct.yandex.com/json/v501/reports"
DIRECT_STATE_URL = "https://api.direct.yandex.com/json/v501/campaigns"
METRIKA_REPORT_URL = "https://api-metrika.yandex.net/stat/v1/data"


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class HttpClient(Protocol):
    def perform(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Optional[bytes],
    ) -> HttpResponse: ...


class UrllibHttpClient:
    """Perform only the explicit HTTP operation supplied by a provider reader."""

    def perform(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Optional[bytes],
    ) -> HttpResponse:
        parsed = urllib.parse.urlsplit(url)
        permitted = (
            (method, url)
            in {
                ("POST", DIRECT_REPORT_URL),
                ("POST", DIRECT_STATE_URL),
            }
            or (
                method == "GET"
                and parsed.scheme == "https"
                and parsed.hostname == "api-metrika.yandex.net"
                and parsed.port is None
                and parsed.path == "/stat/v1/data"
                and not parsed.fragment
            )
        )
        if not permitted:
            raise ValueError("The provider read URL is not allowlisted.")
        request = urllib.request.Request(  # noqa: S310
            url=url,
            data=body,
            headers=dict(headers),
            method=method,
        )
        try:
            with urllib.request.urlopen(  # noqa: S310
                request,
                timeout=30,
            ) as response:
                return HttpResponse(
                    status=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except urllib.error.HTTPError as error:
            return HttpResponse(
                status=error.code,
                headers=dict(error.headers.items()),
                body=error.read(),
            )


class DotenvValue:
    """Resolve one named value without exposing other provider credentials."""

    def __init__(self, path: Path, name: str) -> None:
        self._path = path
        self._name = name

    def configured(self) -> bool:
        try:
            return bool(self._read())
        except (OSError, ValueError):
            return False

    def resolve(self) -> str:
        value = self._read()
        if not value:
            raise RuntimeError(self._name + " is not configured.")
        return value

    def _read(self) -> str:
        content = self._path.read_text(encoding="utf-8")
        values: Dict[str, str] = {}
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip()
        return values.get(self._name, "")


def _json_object(response: HttpResponse, provider: str) -> Dict[str, Any]:
    if response.status < 200 or response.status >= 300:
        raise RuntimeError(f"{provider} read failed with HTTP {response.status}.")
    try:
        value = json.loads(response.body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"{provider} returned invalid JSON.") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"{provider} returned a non-object JSON response.")
    return value


def _direct_report_rows(response: HttpResponse) -> Tuple[DirectReportRow, ...]:
    if response.status < 200 or response.status >= 300:
        raise RuntimeError(
            f"Direct Reports read failed with HTTP {response.status}."
        )
    try:
        lines = [
            line
            for line in response.body.decode("utf-8").splitlines()
            if line.strip()
        ]
    except UnicodeError as error:
        raise RuntimeError("Direct Reports returned invalid UTF-8 TSV.") from error
    if len(lines) < 2:
        raise ValueError("Direct Reports returned an empty TSV report.")
    header = lines[0].split("\t")
    expected = (
        "Date",
        "CampaignId",
        "Impressions",
        "Clicks",
        "Cost",
    )
    if tuple(header) != expected:
        raise ValueError("Direct Reports returned unexpected TSV columns.")
    rows = []
    for index, line in enumerate(lines[1:]):
        values = line.split("\t")
        if len(values) != len(expected):
            raise ValueError(
                f"Direct Reports TSV row {index + 1} has an invalid width."
            )
        row = dict(zip(expected, values))
        try:
            rows.append(
                DirectReportRow(
                    campaign=_text(row["CampaignId"], "CampaignId"),
                    date=_text(row["Date"], "Date"),
                    impressions=_count(int(row["Impressions"]), "Impressions"),
                    clicks=_count(int(row["Clicks"]), "Clicks"),
                    cost_micros=_count(int(row["Cost"]), "Cost"),
                )
            )
        except ValueError as error:
            raise ValueError(
                f"Direct Reports TSV row {index + 1} is invalid."
            ) from error
    return tuple(rows)


def _response_times(response: HttpResponse) -> Tuple[str, str]:
    retrieved_at = response.headers.get("X-MOX-Retrieved-At")
    watermark = response.headers.get("X-MOX-Watermark")
    now = datetime.now(timezone.utc).isoformat()
    return (
        now if not retrieved_at else retrieved_at,
        now if not watermark else watermark,
    )


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError(field + " must be a non-empty string.")
    return value


def _count(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(field + " must be a non-negative integer.")
    return value


def _object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(field + " must be an object.")
    return value


def _array(value: object, field: str) -> Tuple[object, ...]:
    if not isinstance(value, list) or not value or len(value) > 1_000:
        raise ValueError(field + " must contain 1 to 1000 items.")
    return tuple(value)


class DirectProductionReadProviderV1:
    """Own only Direct credentials and expose authorized typed reads."""

    def __init__(
        self,
        *,
        connection_id: str,
        account_id: str,
        campaign_id: str,
        trusted_change_author: str,
        token: DotenvValue,
        client_login: DotenvValue,
        http_client: HttpClient,
    ) -> None:
        self._connection_id = connection_id
        self._account_id = account_id
        self._campaign_id = campaign_id
        self._trusted_change_author = trusted_change_author
        self._token = token
        self._client_login = client_login
        self._http = http_client

    def read_direct_report(
        self,
        connection_id: str,
        query: DirectReportsReadQuery,
    ) -> DirectReportBlock:
        self._authorize(connection_id, query.account, query.campaign)
        response = self._http.perform(
            method="POST",
            url=DIRECT_REPORT_URL,
            headers={
                **self._headers(),
                "processingMode": "auto",
                "returnMoneyInMicros": "true",
                "skipReportHeader": "true",
                "skipColumnHeader": "false",
                "skipReportSummary": "true",
            },
            body=json.dumps(
                {
                    "params": {
                        "SelectionCriteria": {
                            "DateFrom": query.period_start,
                            "DateTo": query.period_end,
                            "Filter": [
                                {
                                    "Field": "CampaignId",
                                    "Operator": "EQUALS",
                                    "Values": [query.campaign],
                                }
                            ],
                        },
                        "FieldNames": [
                            "Date",
                            "CampaignId",
                            "Impressions",
                            "Clicks",
                            "Cost",
                        ],
                        "ReportName": "MOX-ADV paired read",
                        "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
                        "DateRangeType": "CUSTOM_DATE",
                        "Format": "TSV",
                        "IncludeVAT": "NO",
                        "IncludeDiscount": "NO",
                    }
                },
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        rows = _direct_report_rows(response)
        retrieved_at, watermark = _response_times(response)
        return DirectReportBlock(
            source="DIRECT_REPORTS",
            retrieved_at=retrieved_at,
            watermark=watermark,
            period_start=query.period_start,
            period_end=query.period_end,
            timezone="UTC",
            attribution=query.attribution,
            currency="RUB",
            rows=rows,
        )

    def read_direct_state(
        self,
        connection_id: str,
        query: DirectCampaignStateReadQuery,
    ) -> DirectCampaignStateBlock:
        self._authorize(connection_id, query.account, query.campaign)
        response = self._http.perform(
            method="POST",
            url=DIRECT_STATE_URL,
            headers=self._headers(),
            body=json.dumps(
                {
                    "method": "get",
                    "params": {
                        "SelectionCriteria": {"Ids": [query.campaign]},
                        "FieldNames": [
                            "Id",
                            "State",
                            "Status",
                            "DailyBudget",
                        ],
                    },
                },
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        payload = _json_object(response, "Direct Campaigns")
        campaigns = _array(payload.get("data"), "Direct Campaigns data")
        if len(campaigns) != 1:
            raise ValueError("Direct Campaigns must return exactly one campaign.")
        value = _object(campaigns[0], "Direct Campaigns data[0]")
        meta = _object(payload.get("meta"), "Direct Campaigns meta")
        return DirectCampaignStateBlock(
            source="DIRECT_CAMPAIGN_STATE",
            retrieved_at=_text(meta.get("retrieved_at"), "retrieved_at"),
            watermark=_text(meta.get("watermark"), "watermark"),
            campaign=_text(value.get("campaign"), "campaign"),
            campaign_state=_text(value.get("campaign_state"), "campaign_state"),
            group_state=_text(value.get("group_state"), "group_state"),
            ad_state=_text(value.get("ad_state"), "ad_state"),
            strategy=_text(value.get("strategy"), "strategy"),
            current_weekly_budget_micros=_count(
                value.get("current_weekly_budget_micros"),
                "current_weekly_budget_micros",
            ),
            budget_period_start=_text(
                value.get("budget_period_start"),
                "budget_period_start",
            ),
            budget_period_end=_text(
                value.get("budget_period_end"),
                "budget_period_end",
            ),
            current_search_bid_micros=_count(
                value.get("current_search_bid_micros"),
                "current_search_bid_micros",
            ),
            ad_variant=_text(value.get("ad_variant"), "ad_variant"),
            object_config_version=_text(
                value.get("object_config_version"),
                "object_config_version",
            ),
            last_change_author=_text(
                value.get("last_change_author"),
                "last_change_author",
            ),
            last_change_occurred_at=_text(
                value.get("last_change_occurred_at"),
                "last_change_occurred_at",
            ),
        )

    def authorizes_change_author(
        self,
        connection_id: str,
        author: str,
    ) -> bool:
        if connection_id != self._connection_id:
            raise DirectReadAuthorizationError(
                "The stored connection does not authorize this Direct scope."
            )
        return author == self._trusted_change_author

    def _headers(self) -> Mapping[str, str]:
        return {
            "Authorization": "Bearer " + self._token.resolve(),
            "Client-Login": self._client_login.resolve(),
            "Accept-Language": "ru",
            "Content-Type": "application/json",
        }

    def _authorize(
        self,
        connection_id: str,
        account_id: str,
        campaign_id: str,
    ) -> None:
        if (
            connection_id != self._connection_id
            or account_id != self._account_id
            or campaign_id != self._campaign_id
        ):
            raise DirectReadAuthorizationError(
                "The stored connection does not authorize this Direct scope."
            )

class MetrikaProductionReadProviderV1:
    """Own only the Metrika credential and expose one typed report read."""

    def __init__(
        self,
        *,
        connection_id: str,
        counter_id: str,
        goal_id: str,
        campaign_id: str,
        token: DotenvValue,
        http_client: HttpClient,
    ) -> None:
        self._connection_id = connection_id
        self._counter_id = counter_id
        self._goal_id = goal_id
        self._campaign_id = campaign_id
        self._token = token
        self._http = http_client

    def read_metrika_report(
        self,
        connection_id: str,
        query: MetrikaReportReadQuery,
    ) -> MetrikaReportBlock:
        if (
            connection_id != self._connection_id
            or query.counter != self._counter_id
            or query.goal != self._goal_id
            or query.campaign != self._campaign_id
        ):
            raise MetrikaReadAuthorizationError(
                "The stored connection does not authorize this Metrika scope."
            )
        query_string = urllib.parse.urlencode(
            {
                "ids": query.counter,
                "date1": query.period_start,
                "date2": query.period_end,
                "dimensions": "ym:s:date",
                "metrics": (
                    "ym:s:visits,"
                    + "ym:s:goal"
                    + query.goal
                    + "reaches"
                ),
                "filters": "ym:s:UTMCampaign=='" + query.campaign + "'",
            }
        )
        response = self._http.perform(
            method="GET",
            url=METRIKA_REPORT_URL + "?" + query_string,
            headers={
                "Authorization": "OAuth " + self._token.resolve(),
                "Accept-Language": "ru",
            },
            body=None,
        )
        payload = _json_object(response, "Metrika")
        rows = tuple(
            self._report_row(
                _object(item, "Metrika data[]"),
                campaign=query.campaign,
                goal=query.goal,
            )
            for item in _array(payload.get("data"), "Metrika data")
        )
        meta = _object(payload.get("meta"), "Metrika meta")
        return MetrikaReportBlock(
            source="METRIKA_REPORT",
            retrieved_at=_text(meta.get("retrieved_at"), "retrieved_at"),
            watermark=_text(meta.get("watermark"), "watermark"),
            period_start=query.period_start,
            period_end=query.period_end,
            timezone="UTC",
            attribution=query.attribution,
            rows=rows,
        )

    @staticmethod
    def _report_row(
        value: Mapping[str, Any],
        *,
        campaign: str,
        goal: str,
    ) -> MetrikaReportRow:
        dimensions = _array(value.get("dimensions"), "Metrika dimensions")
        metrics = _array(value.get("metrics"), "Metrika metrics")
        if len(dimensions) != 1 or len(metrics) != 2:
            raise ValueError("Metrika row has an unexpected grain.")
        dimension = _object(dimensions[0], "Metrika dimensions[0]")
        visits = metrics[0]
        goal_visits = metrics[1]
        if isinstance(visits, float) and visits.is_integer():
            visits = int(visits)
        if isinstance(goal_visits, float) and goal_visits.is_integer():
            goal_visits = int(goal_visits)
        return MetrikaReportRow(
            campaign=campaign,
            goal=goal,
            date=_text(dimension.get("name"), "Metrika date"),
            visits=_count(visits, "Metrika visits"),
            goal_visits=_count(goal_visits, "Metrika goal visits"),
        )


class YandexProductionReader:
    """Compose isolated read-only providers through the paired module runtime."""

    def __init__(
        self,
        *,
        configuration_path: Path = DEFAULT_CONFIGURATION_PATH,
        environment_path: Path = DEFAULT_ENVIRONMENT_PATH,
        http_client: Optional[HttpClient] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.configuration_path = configuration_path
        self.environment_path = environment_path
        self.http_client = http_client or UrllibHttpClient()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.last_records: Tuple[Mapping[str, str], ...] = ()

    def readiness(self, policy: Mapping[str, Any]) -> Dict[str, Any]:
        del policy
        configuration = self._configuration_or_none()
        checks = [
            {
                "id": "production_read_configuration",
                "label": "Конфигурация production read-only Яндекса доступна",
                "ready": configuration is not None,
            },
            {
                "id": "direct_token",
                "label": "YANDEX_DIRECT_OAUTH_TOKEN настроен",
                "ready": DotenvValue(
                    self.environment_path,
                    "YANDEX_DIRECT_OAUTH_TOKEN",
                ).configured(),
            },
            {
                "id": "direct_client_login",
                "label": "YANDEX_DIRECT_CLIENT_LOGIN настроен",
                "ready": DotenvValue(
                    self.environment_path,
                    "YANDEX_DIRECT_CLIENT_LOGIN",
                ).configured(),
            },
            {
                "id": "metrika_token",
                "label": "YANDEX_METRIKA_OAUTH_TOKEN настроен",
                "ready": DotenvValue(
                    self.environment_path,
                    "YANDEX_METRIKA_OAUTH_TOKEN",
                ).configured(),
            },
        ]
        blockers = [item["label"] for item in checks if not item["ready"]]
        return {
            "ready": not blockers,
            "checks": checks,
            "blockers": blockers,
            "access": "READ_ONLY",
            "data_source": "YANDEX_PRODUCTION_API",
            "external_reads_enabled": True,
            "write_requests_allowed": False,
            "write_flow": "DISABLED",
        }

    def collect_snapshot(
        self,
        *,
        policy: Mapping[str, Any],
        observation_id: str,
        generated_at: datetime,
        progress_callback: Optional[
            Callable[[Dict[str, str]], None]
        ] = None,
    ):
        configuration = self._configuration()
        direct_token = DotenvValue(
            self.environment_path,
            "YANDEX_DIRECT_OAUTH_TOKEN",
        )
        direct_login = DotenvValue(
            self.environment_path,
            "YANDEX_DIRECT_CLIENT_LOGIN",
        )
        metrika_token = DotenvValue(
            self.environment_path,
            "YANDEX_METRIKA_OAUTH_TOKEN",
        )
        self._progress(progress_callback, "direct", "RUNNING")
        direct_module = DirectModuleV1(
            clock=lambda: generated_at,
            provider_reader=DirectProductionReadProviderV1(
                connection_id=configuration["direct_connection_id"],
                account_id=configuration["account_id"],
                campaign_id=configuration["campaign_id"],
                trusted_change_author=configuration["trusted_change_author"],
                token=direct_token,
                client_login=direct_login,
                http_client=self.http_client,
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        )
        metrika_module = MetrikaModuleV1(
            clock=lambda: generated_at,
            provider_reader=MetrikaProductionReadProviderV1(
                connection_id=configuration["metrika_connection_id"],
                counter_id=configuration["counter_id"],
                goal_id=configuration["goal_id"],
                campaign_id=configuration["campaign_id"],
                token=metrika_token,
                http_client=self.http_client,
            ),
        )
        runtime = PairedModuleRuntimeV1(
            direct=InProcessModuleAdapterV1(
                direct_module,
                environment=ExecutionEnvironment.PRODUCTION,
            ),
            metrika=InProcessModuleAdapterV1(
                metrika_module,
                environment=ExecutionEnvironment.PRODUCTION,
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        )
        period_end = (generated_at.date() - timedelta(days=1)).isoformat()
        period_days = configuration["period_days"]
        period_start = (
            generated_at.date() - timedelta(days=period_days)
        ).isoformat()
        trusted_scope = TrustedAnalyticsScope(
            organization=configuration["organization_id"],
            connection=configuration["paired_connection_id"],
            account=configuration["account_id"],
            campaign=configuration["campaign_id"],
            counter=configuration["counter_id"],
            goal=configuration["goal_id"],
            baseline_campaign=configuration["baseline"]["source_campaign"],
        )
        try:
            snapshot = runtime.collect_snapshot(
                policy=policy,
                observation_id=observation_id,
                generated_at=generated_at.isoformat(),
                period_start=period_start,
                period_end=period_end,
                trusted_scope=trusted_scope,
                connection_refs=PairedConnectionRefsV1(
                    direct=configuration["direct_connection_id"],
                    metrika=configuration["metrika_connection_id"],
                ),
                baseline=BaselineAggregate(**configuration["baseline"]),
                progress_callback=lambda step, status: self._progress(
                    progress_callback,
                    step,
                    status,
                ),
            )
        except Exception:
            self.last_records = ()
            raise
        self.last_records = (
            {
                "system": "DIRECT_REPORTS",
                "http_method": "POST",
                "host": "api.direct.yandex.com",
                "path": "/json/v501/reports",
                "operation": "get",
            },
            {
                "system": "DIRECT",
                "http_method": "POST",
                "host": "api.direct.yandex.com",
                "path": "/json/v501/campaigns",
                "operation": "get",
            },
            {
                "system": "METRIKA",
                "http_method": "GET",
                "host": "api-metrika.yandex.net",
                "path": "/stat/v1/data",
                "operation": "get",
            },
        )
        return snapshot

    def _configuration(self) -> Dict[str, Any]:
        configuration = self._configuration_or_none()
        if configuration is None:
            raise RuntimeError(
                "Production read-only configuration is unavailable."
            )
        return configuration

    def _configuration_or_none(self) -> Optional[Dict[str, Any]]:
        try:
            value = json.loads(
                self.configuration_path.read_text(encoding="utf-8")
            )
            if not isinstance(value, dict):
                return None
            required_text = (
                "organization_id",
                "paired_connection_id",
                "direct_connection_id",
                "metrika_connection_id",
                "account_id",
                "campaign_id",
                "counter_id",
                "goal_id",
                "trusted_change_author",
            )
            parsed = {
                name: _text(value.get(name), name)
                for name in required_text
            }
            period_days = value.get("period_days")
            if (
                isinstance(period_days, bool)
                or not isinstance(period_days, int)
                or period_days < 1
                or period_days > 90
            ):
                return None
            baseline = _object(value.get("baseline"), "baseline")
            expected_baseline = {
                "source_campaign",
                "impressions",
                "clicks",
                "cost_micros",
                "visits",
                "goal_visits",
            }
            if set(baseline) != expected_baseline:
                return None
            parsed_baseline: Dict[str, Any] = {
                "source_campaign": _text(
                    baseline["source_campaign"],
                    "baseline.source_campaign",
                )
            }
            for field in expected_baseline - {"source_campaign"}:
                parsed_baseline[field] = _count(
                    baseline[field],
                    "baseline." + field,
                )
            return {
                **parsed,
                "period_days": period_days,
                "baseline": parsed_baseline,
            }
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _progress(
        callback: Optional[Callable[[Dict[str, str]], None]],
        step: str,
        status: str,
    ) -> None:
        if callback is not None:
            callback({"step": step, "status": status})
