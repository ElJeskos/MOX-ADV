"""Metrika-only production read configuration and provider adapter."""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from mox_adv.contracts import (
    MetrikaReportBlock,
    MetrikaReportReadQuery,
    MetrikaReportRow,
)
from mox_adv.environment import ExecutionEnvironment
from mox_adv.metrika_provider import MetrikaReadAuthorizationError
from mox_adv.module_api.v1 import InProcessModuleAdapterV1
from mox_adv.modules.metrika import MetrikaModuleV1
from mox_adv.yandex_transport import (
    METRIKA_REPORT_READ,
    DotenvValue,
    HttpClient,
    HttpResponse,
    UrllibHttpClient,
    json_response_object,
)
from mox_adv.yandex_transport import (
    nonempty_array as _array,
)
from mox_adv.yandex_transport import (
    nonnegative_count as _count,
)
from mox_adv.yandex_transport import (
    object_mapping as _object,
)
from mox_adv.yandex_transport import (
    required_text as _text,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_METRIKA_CONFIGURATION_PATH = (
    ROOT / "config" / "metrika-production-read.json"
)
DEFAULT_METRIKA_ENVIRONMENT_PATH = ROOT / ".env.metrika-read"


@dataclass(frozen=True)
class MetrikaProductionReadSettingsV1:
    connection_id: str
    counter_id: str
    goal_id: str
    campaign_id: str

    @classmethod
    def from_path(cls, path: Path) -> MetrikaProductionReadSettingsV1:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(
                "Metrika production read configuration is unavailable."
            ) from error
        if not isinstance(value, dict) or set(value) != {
            "connection_id",
            "counter_id",
            "goal_id",
            "campaign_id",
        }:
            raise ValueError(
                "Metrika production read configuration has unexpected fields."
            )
        return cls(
            connection_id=_text(value["connection_id"], "connection_id"),
            counter_id=_text(value["counter_id"], "counter_id"),
            goal_id=_text(value["goal_id"], "goal_id"),
            campaign_id=_text(value["campaign_id"], "campaign_id"),
        )


def _json_object(response: HttpResponse) -> dict[str, Any]:
    return json_response_object(response, "Metrika")


class MetrikaProductionReadProviderV1:
    """Own only Metrika configuration and its OAuth credential."""

    def __init__(
        self,
        *,
        settings: MetrikaProductionReadSettingsV1,
        token: DotenvValue,
        http_client: HttpClient,
    ) -> None:
        self._settings = settings
        self._token = token
        self._http = http_client

    def read_metrika_report(
        self,
        connection_id: str,
        query: MetrikaReportReadQuery,
    ) -> MetrikaReportBlock:
        self._authorize(connection_id, query)
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
            endpoint=METRIKA_REPORT_READ,
            url=METRIKA_REPORT_READ.base_url + "?" + query_string,
            headers={
                "Authorization": "OAuth " + self._token.resolve(),
                "Accept-Language": "ru",
            },
            body=None,
        )
        payload = _json_object(response)
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

    def _authorize(
        self,
        connection_id: str,
        query: MetrikaReportReadQuery,
    ) -> None:
        if (
            connection_id != self._settings.connection_id
            or query.counter != self._settings.counter_id
            or query.goal != self._settings.goal_id
            or query.campaign != self._settings.campaign_id
        ):
            raise MetrikaReadAuthorizationError(
                "The stored connection does not authorize this Metrika scope."
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


class MetrikaProductionReadCompositionV1:
    """Resolve only Metrika configuration, credential, transport, and module."""

    def __init__(
        self,
        *,
        configuration_path: Path = DEFAULT_METRIKA_CONFIGURATION_PATH,
        environment_path: Path = DEFAULT_METRIKA_ENVIRONMENT_PATH,
        http_client: HttpClient | None = None,
    ) -> None:
        self.configuration_path = configuration_path
        self.environment_path = environment_path
        self.http_client = http_client or UrllibHttpClient()

    def settings(self) -> MetrikaProductionReadSettingsV1:
        return MetrikaProductionReadSettingsV1.from_path(self.configuration_path)

    def settings_or_none(self) -> MetrikaProductionReadSettingsV1 | None:
        try:
            return self.settings()
        except (TypeError, ValueError):
            return None

    def credential_ready(self) -> bool:
        return self._token().configured()

    def credential_checks(self) -> tuple[dict[str, object], ...]:
        return (
            {
                "id": "metrika_token",
                "label": "YANDEX_METRIKA_OAUTH_TOKEN настроен",
                "ready": self._token().configured(),
            },
        )

    def adapter(
        self,
        *,
        clock: Callable[[], datetime],
    ) -> InProcessModuleAdapterV1:
        module = MetrikaModuleV1(
            clock=clock,
            provider_reader=MetrikaProductionReadProviderV1(
                settings=self.settings(),
                token=self._token(),
                http_client=self.http_client,
            ),
        )
        return InProcessModuleAdapterV1(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        )

    def _token(self) -> DotenvValue:
        return DotenvValue(
            self.environment_path,
            "YANDEX_METRIKA_OAUTH_TOKEN",
        )
