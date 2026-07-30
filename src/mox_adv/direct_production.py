"""Direct-only production read configuration and provider adapter."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mox_adv.contracts import (
    DirectCampaignStateBlock,
    DirectCampaignStateReadQuery,
    DirectReportBlock,
    DirectReportRow,
    DirectReportsReadQuery,
)
from mox_adv.direct_provider import DirectReadAuthorizationError
from mox_adv.environment import ExecutionEnvironment
from mox_adv.module_api.v1 import InProcessModuleAdapterV1
from mox_adv.modules.direct import DirectModuleV1
from mox_adv.yandex_credentials import DotenvValue
from mox_adv.yandex_transport import (
    HttpClient,
    HttpResponse,
    UrllibHttpClient,
    YandexReadEndpoint,
)
from mox_adv.yandex_values import json_response_object
from mox_adv.yandex_values import (
    nonempty_array as _array,
)
from mox_adv.yandex_values import (
    nonnegative_count as _count,
)
from mox_adv.yandex_values import (
    object_mapping as _object,
)
from mox_adv.yandex_values import (
    required_text as _text,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIRECT_CONFIGURATION_PATH = (
    ROOT / "config" / "direct-production-read.json"
)
DEFAULT_DIRECT_ENVIRONMENT_PATH = ROOT / ".env.direct-read"
DIRECT_REPORTS_READ = YandexReadEndpoint(
    system="DIRECT_REPORTS",
    method="POST",
    host="api.direct.yandex.com",
    path="/json/v501/reports",
    operation="get",
    body_required=True,
)
DIRECT_CAMPAIGN_STATE_READ = YandexReadEndpoint(
    system="DIRECT",
    method="POST",
    host="api.direct.yandex.com",
    path="/json/v501/campaigns",
    operation="get",
    body_required=True,
    json_method="get",
)
DIRECT_READ_ENDPOINTS = (
    DIRECT_REPORTS_READ,
    DIRECT_CAMPAIGN_STATE_READ,
)


@dataclass(frozen=True)
class DirectProductionReadSettingsV1:
    connection_id: str
    account_id: str
    campaign_id: str
    trusted_change_author: str

    @classmethod
    def from_path(cls, path: Path) -> DirectProductionReadSettingsV1:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(
                "Direct production read configuration is unavailable."
            ) from error
        if not isinstance(value, dict) or set(value) != {
            "connection_id",
            "account_id",
            "campaign_id",
            "trusted_change_author",
        }:
            raise ValueError(
                "Direct production read configuration has unexpected fields."
            )
        return cls(
            connection_id=_text(value["connection_id"], "connection_id"),
            account_id=_text(value["account_id"], "account_id"),
            campaign_id=_text(value["campaign_id"], "campaign_id"),
            trusted_change_author=_text(
                value["trusted_change_author"],
                "trusted_change_author",
            ),
        )


def _direct_report_rows(response: HttpResponse) -> tuple[DirectReportRow, ...]:
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
    expected = (
        "Date",
        "CampaignId",
        "Impressions",
        "Clicks",
        "Cost",
    )
    if tuple(lines[0].split("\t")) != expected:
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


def _json_object(response: HttpResponse) -> dict[str, Any]:
    return json_response_object(response, "Direct Campaigns")


def _response_times(response: HttpResponse) -> tuple[str, str]:
    retrieved_at = response.headers.get("X-MOX-Retrieved-At")
    watermark = response.headers.get("X-MOX-Watermark")
    now = datetime.now(timezone.utc).isoformat()
    return (
        now if not retrieved_at else retrieved_at,
        now if not watermark else watermark,
    )


class DirectProductionReadProviderV1:
    """Own only Direct configuration and credentials."""

    def __init__(
        self,
        *,
        settings: DirectProductionReadSettingsV1,
        token: DotenvValue,
        client_login: DotenvValue,
        http_client: HttpClient,
    ) -> None:
        self._settings = settings
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
            endpoint=DIRECT_REPORTS_READ,
            url=DIRECT_REPORTS_READ.base_url,
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
            endpoint=DIRECT_CAMPAIGN_STATE_READ,
            url=DIRECT_CAMPAIGN_STATE_READ.base_url,
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
        payload = _json_object(response)
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
        if connection_id != self._settings.connection_id:
            raise DirectReadAuthorizationError(
                "The stored connection does not authorize this Direct scope."
            )
        return author == self._settings.trusted_change_author

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
            connection_id != self._settings.connection_id
            or account_id != self._settings.account_id
            or campaign_id != self._settings.campaign_id
        ):
            raise DirectReadAuthorizationError(
                "The stored connection does not authorize this Direct scope."
            )


class DirectProductionReadCompositionV1:
    """Resolve only Direct configuration, credentials, transport, and module."""

    def __init__(
        self,
        *,
        configuration_path: Path = DEFAULT_DIRECT_CONFIGURATION_PATH,
        environment_path: Path = DEFAULT_DIRECT_ENVIRONMENT_PATH,
        http_client: HttpClient | None = None,
    ) -> None:
        self.configuration_path = configuration_path
        self.environment_path = environment_path
        self.http_client = http_client or UrllibHttpClient(
            DIRECT_READ_ENDPOINTS
        )

    def settings(self) -> DirectProductionReadSettingsV1:
        return DirectProductionReadSettingsV1.from_path(self.configuration_path)

    def settings_or_none(self) -> DirectProductionReadSettingsV1 | None:
        try:
            return self.settings()
        except (TypeError, ValueError):
            return None

    def credentials_ready(self) -> bool:
        return self._token().configured() and self._client_login().configured()

    def credential_checks(self) -> tuple[dict[str, object], ...]:
        return (
            {
                "id": "direct_token",
                "label": "YANDEX_DIRECT_OAUTH_TOKEN настроен",
                "ready": self._token().configured(),
            },
            {
                "id": "direct_client_login",
                "label": "YANDEX_DIRECT_CLIENT_LOGIN настроен",
                "ready": self._client_login().configured(),
            },
        )

    def adapter(
        self,
        *,
        clock: Callable[[], datetime],
        http_client: HttpClient | None = None,
    ) -> InProcessModuleAdapterV1:
        module = DirectModuleV1(
            clock=clock,
            provider_reader=DirectProductionReadProviderV1(
                settings=self.settings(),
                token=self._token(),
                client_login=self._client_login(),
                http_client=(
                    self.http_client
                    if http_client is None
                    else http_client
                ),
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        )
        return InProcessModuleAdapterV1(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        )

    def _token(self) -> DotenvValue:
        return DotenvValue(
            self.environment_path,
            "YANDEX_DIRECT_OAUTH_TOKEN",
        )

    def _client_login(self) -> DotenvValue:
        return DotenvValue(
            self.environment_path,
            "YANDEX_DIRECT_CLIENT_LOGIN",
        )
