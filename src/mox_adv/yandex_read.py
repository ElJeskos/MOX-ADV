"""Strict real-data readers for the production read-only UI mode."""

from __future__ import annotations

import csv
import errno
import getpass
import hashlib
import io
import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mox_adv.connectors import (
    DirectCampaignStateReadConnectorV1,
    DirectReportsReadConnectorV1,
    MetrikaReportReadConnectorV1,
)
from mox_adv.contracts import (
    DirectCampaignStateBlock,
    DirectCampaignStateReadQuery,
    DirectReportBlock,
    DirectReportRow,
    DirectReportsReadQuery,
    IntegratedPerformanceSnapshot,
    MetrikaReportBlock,
    MetrikaReportReadQuery,
    MetrikaReportRow,
    TrustedAnalyticsScope,
    VersionedReadRequest,
)
from mox_adv.egress import (
    CredentialProfile,
    EgressAuthority,
    EgressDenied,
    HttpEgressGuard,
)
from mox_adv.observe import build_observe_snapshot_from_blocks

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = ROOT / "config" / "gate0-policy.json"
DEFAULT_PRODUCTION_READ_CONFIG_PATH = (
    Path.home() / ".config" / "mox-adv" / "production-read.json"
)
DEFAULT_ENVIRONMENT_PATH = ROOT / ".env"
DIRECT_CREDENTIAL_BINDING = "MOX_ADV_DIRECT_PROD_READ"
METRIKA_CREDENTIAL_BINDING = "MOX_ADV_METRIKA_PROD_READ"
DOTENV_VARIABLE_BY_BINDING = {
    DIRECT_CREDENTIAL_BINDING: "YANDEX_DIRECT_OAUTH_TOKEN",
    METRIKA_CREDENTIAL_BINDING: "YANDEX_METRICA_OAUTH_TOKEN",
}
DIRECT_CLIENT_LOGIN_VARIABLE = "YANDEX_DIRECT_CLIENT_LOGIN"
METRIKA_COUNTER_IDS_VARIABLE = "YANDEX_METRICA_COUNTER_IDS"
LOCAL_READ_ONLY_CREDENTIAL_POLICY = {
    "surface": "dashboard",
    "storage": "protected_dotenv_file",
    "path": ".env",
    "required_file_access": "owner_only_0600_or_stricter",
    "process_environment_import": False,
    "write_profiles_allowed": False,
    "bindings": {
        "DIRECT_PROD_READ": "YANDEX_DIRECT_OAUTH_TOKEN",
        "METRIKA_PROD_READ": "YANDEX_METRICA_OAUTH_TOKEN",
    },
    "configuration_bindings": {
        "direct_client_login": DIRECT_CLIENT_LOGIN_VARIABLE,
        "metrika_counter_ids": METRIKA_COUNTER_IDS_VARIABLE,
    },
}
_DOTENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SAFE_HTTP_HEADER_VALUE = re.compile(r"[\x21-\x7e]{1,4096}")
_SAFE_DIRECT_CLIENT_LOGIN = re.compile(r"[A-Za-z0-9._@-]{1,128}")
_POSITIVE_ASCII_ID = re.compile(r"[1-9][0-9]{0,19}")
_DOTENV_ALLOWED_VARIABLES = frozenset(
    (
        *DOTENV_VARIABLE_BY_BINDING.values(),
        DIRECT_CLIENT_LOGIN_VARIABLE,
        METRIKA_COUNTER_IDS_VARIABLE,
    )
)
MAX_ENVIRONMENT_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 20
DIRECT_CAMPAIGN_CATALOG_PAGE_SIZE = 500
DIRECT_CAMPAIGN_CATALOG_MAX_ITEMS = 10_000


class ProductionReadConfigurationError(ValueError):
    """The non-secret real-data binding is absent or invalid."""


@dataclass(frozen=True)
class ProductionReadConfiguration:
    organization: str
    connection: str
    direct_account: str
    direct_client_login: str | None
    campaign_id: str
    metrika_counter_id: str
    metrika_goal_id: str
    currency: str
    lookback_days: int

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
    ) -> "ProductionReadConfiguration":
        expected = {
            "schema_version",
            "organization",
            "connection",
            "direct_account",
            "direct_client_login",
            "campaign_id",
            "metrika_counter_id",
            "metrika_goal_id",
            "currency",
            "lookback_days",
        }
        if set(value) != expected or value.get("schema_version") != (
            "mox-adv-production-read-v1"
        ):
            raise ProductionReadConfigurationError(
                "Конфигурация production-read имеет неподдерживаемую схему."
            )
        text_fields = (
            "organization",
            "connection",
            "direct_account",
        )
        if any(
            not isinstance(value.get(field), str)
            or not str(value[field]).strip()
            or len(str(value[field])) > 128
            for field in text_fields
        ):
            raise ProductionReadConfigurationError(
                "В production-read не заполнена доверенная область."
            )
        identifiers = (
            "campaign_id",
            "metrika_counter_id",
            "metrika_goal_id",
        )
        if any(
            not isinstance(value.get(field), str)
            or not str(value[field]).isdigit()
            or len(str(value[field])) > 20
            or int(str(value[field])) <= 0
            for field in identifiers
        ):
            raise ProductionReadConfigurationError(
                "ID кампании, счётчика и цели должны быть положительными числами."
            )
        client_login = value.get("direct_client_login")
        if client_login is not None and (
            not isinstance(client_login, str)
            or not client_login.strip()
            or len(client_login) > 128
        ):
            raise ProductionReadConfigurationError(
                "direct_client_login должен быть строкой или null."
            )
        if value.get("currency") != "RUB":
            raise ProductionReadConfigurationError(
                "Текущий аналитический контракт поддерживает валюту RUB."
            )
        lookback = value.get("lookback_days")
        if (
            isinstance(lookback, bool)
            or not isinstance(lookback, int)
            or not 1 <= lookback <= 30
        ):
            raise ProductionReadConfigurationError(
                "lookback_days должен быть целым числом от 1 до 30."
            )
        return cls(
            organization=str(value["organization"]),
            connection=str(value["connection"]),
            direct_account=str(value["direct_account"]),
            direct_client_login=client_login,
            campaign_id=str(value["campaign_id"]),
            metrika_counter_id=str(value["metrika_counter_id"]),
            metrika_goal_id=str(value["metrika_goal_id"]),
            currency="RUB",
            lookback_days=lookback,
        )

    @classmethod
    def read_mapping(cls, path: Path) -> Mapping[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ProductionReadConfigurationError(
                f"Не найден файл настроек {path}."
            ) from error
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ProductionReadConfigurationError(
                "Файл production-read нельзя безопасно прочитать."
            ) from error
        if not isinstance(raw, Mapping):
            raise ProductionReadConfigurationError(
                "Файл production-read должен содержать JSON-объект."
            )
        return raw

    @classmethod
    def load(cls, path: Path) -> "ProductionReadConfiguration":
        return cls.from_mapping(cls.read_mapping(path))

    def trusted_scope(self) -> TrustedAnalyticsScope:
        return TrustedAnalyticsScope(
            organization=self.organization,
            connection=self.connection,
            account=self.direct_account,
            campaign=self.campaign_id,
            counter=self.metrika_counter_id,
            goal=self.metrika_goal_id,
        )


class CredentialProvider(Protocol):
    def get(self, binding: str) -> str: ...

    def has(self, binding: str) -> bool: ...


@dataclass(frozen=True, repr=False)
class DotEnvCredentialSnapshot:
    """One immutable, validated-on-access view of the protected dotenv file."""

    path: Path
    direct_oauth_token: str
    direct_client_login: str
    metrika_oauth_token: str
    metrika_counter_ids: str

    def get(self, binding: str) -> str:
        token_by_binding = {
            DIRECT_CREDENTIAL_BINDING: (
                DOTENV_VARIABLE_BY_BINDING[DIRECT_CREDENTIAL_BINDING],
                self.direct_oauth_token,
            ),
            METRIKA_CREDENTIAL_BINDING: (
                DOTENV_VARIABLE_BY_BINDING[METRIKA_CREDENTIAL_BINDING],
                self.metrika_oauth_token,
            ),
        }
        value = token_by_binding.get(binding)
        if value is None:
            raise RuntimeError("Запрошена неподдерживаемая credential binding.")
        variable, token = value
        if _SAFE_HTTP_HEADER_VALUE.fullmatch(token) is None:
            raise RuntimeError(
                f"В файле {self.path} отсутствует корректная переменная {variable}."
            )
        return token

    def has(self, binding: str) -> bool:
        try:
            self.get(binding)
        except RuntimeError:
            return False
        return True

    def describe(self, binding: str) -> str:
        variable = DOTENV_VARIABLE_BY_BINDING.get(binding)
        if variable is None:
            return "Неподдерживаемая credential binding."
        return f"Read-only OAuth-токен {variable} загружен из {self.path}"

    def configuration_bindings(self) -> tuple[str, str]:
        direct_client_login = self.direct_configuration_binding()
        if _POSITIVE_ASCII_ID.fullmatch(self.metrika_counter_ids) is None:
            raise RuntimeError(
                f"Переменная {METRIKA_COUNTER_IDS_VARIABLE} в файле "
                f"{self.path} должна содержать ровно один положительный ID."
            )
        return direct_client_login, self.metrika_counter_ids

    def direct_configuration_binding(self) -> str:
        """Return the validated Direct account without requiring Metrika."""

        if _SAFE_DIRECT_CLIENT_LOGIN.fullmatch(self.direct_client_login) is None:
            raise RuntimeError(
                f"В файле {self.path} отсутствует корректная переменная "
                f"{DIRECT_CLIENT_LOGIN_VARIABLE}."
            )
        return self.direct_client_login


class DotEnvCredentialProvider:
    """Load one protected four-value dashboard credential snapshot."""

    def __init__(self, path: Path = DEFAULT_ENVIRONMENT_PATH) -> None:
        self.path = path

    def has(self, binding: str) -> bool:
        try:
            self.get(binding)
        except RuntimeError:
            return False
        return True

    def get(self, binding: str) -> str:
        return self.snapshot().get(binding)

    def describe(self, binding: str) -> str:
        variable = DOTENV_VARIABLE_BY_BINDING.get(binding)
        if variable is None:
            return "Неподдерживаемая credential binding."
        return f"Read-only OAuth-токен {variable} загружен из {self.path}"

    def configuration_bindings(self) -> tuple[str, str]:
        return self.snapshot().configuration_bindings()

    def snapshot(self) -> DotEnvCredentialSnapshot:
        values = self._load()
        return DotEnvCredentialSnapshot(
            path=self.path,
            direct_oauth_token=values.get(
                DOTENV_VARIABLE_BY_BINDING[DIRECT_CREDENTIAL_BINDING],
                "",
            ),
            direct_client_login=values.get(
                DIRECT_CLIENT_LOGIN_VARIABLE,
                "",
            ),
            metrika_oauth_token=values.get(
                DOTENV_VARIABLE_BY_BINDING[METRIKA_CREDENTIAL_BINDING],
                "",
            ),
            metrika_counter_ids=values.get(
                METRIKA_COUNTER_IDS_VARIABLE,
                "",
            ),
        )

    def _load(self) -> dict[str, str]:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.path, flags)
        except FileNotFoundError as error:
            raise RuntimeError(
                f"Не найден локальный файл токенов {self.path}."
            ) from error
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise RuntimeError(
                    f"Файл {self.path} не должен быть символической ссылкой."
                ) from error
            raise RuntimeError(
                f"Не удалось безопасно открыть файл {self.path}."
            ) from error
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError(
                    f"Путь {self.path} должен указывать на обычный файл."
                )
            if metadata.st_uid != os.getuid():
                raise RuntimeError(
                    f"Файл {self.path} должен принадлежать текущему пользователю."
                )
            if stat.S_IMODE(metadata.st_mode) not in {0o400, 0o600}:
                raise RuntimeError(
                    f"Права файла {self.path} должны быть 600 или 400; "
                    "выполните chmod 600."
                )
            if metadata.st_size > MAX_ENVIRONMENT_BYTES:
                raise RuntimeError(f"Файл {self.path} превышает безопасный размер.")
            with os.fdopen(descriptor, "rb", closefd=True) as stream:
                descriptor = -1
                content_bytes = stream.read(MAX_ENVIRONMENT_BYTES + 1)
        except OSError as error:
            raise RuntimeError(
                f"Не удалось безопасно прочитать файл {self.path}."
            ) from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if len(content_bytes) > MAX_ENVIRONMENT_BYTES:
            raise RuntimeError(f"Файл {self.path} превышает безопасный размер.")
        try:
            content = content_bytes.decode("utf-8")
        except UnicodeError as error:
            raise RuntimeError(
                f"Файл {self.path} должен иметь кодировку UTF-8."
            ) from error
        values: dict[str, str] = {}
        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, raw_value = line.partition("=")
            key = key.strip()
            if not separator or _DOTENV_KEY.fullmatch(key) is None:
                raise RuntimeError(
                    f"Файл {self.path} содержит некорректную строку {line_number}."
                )
            if key not in _DOTENV_ALLOWED_VARIABLES:
                continue
            if key in values:
                raise RuntimeError(
                    f"Файл {self.path} повторно определяет переменную {key}."
                )
            value = raw_value.strip()
            if value[:1] in {"'", '"'} or value[-1:] in {"'", '"'}:
                if len(value) < 2 or value[0] != value[-1]:
                    raise RuntimeError(
                        f"Файл {self.path} содержит незакрытые кавычки "
                        f"в строке {line_number}."
                    )
                value = value[1:-1]
            values[key] = value
        return values


class MacOSKeychainCredentialProvider:
    """Read an exact generic-password service without logging its value."""

    def __init__(self, account: str | None = None) -> None:
        self.account = account or getpass.getuser()

    def has(self, binding: str) -> bool:
        completed = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a",
                self.account,
                "-s",
                binding,
            ],
            capture_output=True,
            check=False,
        )
        return completed.returncode == 0

    def get(self, binding: str) -> str:
        completed = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-w",
                "-a",
                self.account,
                "-s",
                binding,
            ],
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"В macOS Keychain отсутствует профиль {binding}.")
        try:
            token = completed.stdout.decode("utf-8").strip()
        except UnicodeError as error:
            raise RuntimeError(
                f"Профиль {binding} в macOS Keychain повреждён."
            ) from error
        if not token or len(token) > 4096:
            raise RuntimeError(
                f"Профиль {binding} в macOS Keychain пуст или некорректен."
            )
        return token

    def describe(self, binding: str) -> str:
        return f"Read-only OAuth-профиль {binding} в macOS Keychain"


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
        body: bytes | None,
        timeout_seconds: int,
    ) -> HttpResponse: ...


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, code, msg, headers, newurl
        fp.close()
        raise EgressDenied("EXTERNAL_EGRESS_DENIED: redirects are forbidden.")


class UrllibHttpClient:
    """Small no-redirect HTTPS client with a bounded response body."""

    def __init__(self, opener: Any | None = None) -> None:
        self._opener = opener or build_opener(_RejectRedirects())

    def perform(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: int,
    ) -> HttpResponse:
        request = Request(
            url=url,
            data=body,
            headers=dict(headers),
            method=method,
        )
        try:
            with self._opener.open(
                request,
                timeout=timeout_seconds,
            ) as response:
                status = int(response.status)
                response_headers = {
                    str(key).lower(): str(value)
                    for key, value in response.headers.items()
                }
                content = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            try:
                status = int(error.code)
                response_headers = {
                    str(key).lower(): str(value) for key, value in error.headers.items()
                }
                content = error.read(MAX_RESPONSE_BYTES + 1)
            finally:
                error.close()
        except EgressDenied:
            raise
        except (OSError, URLError) as error:
            raise RuntimeError(
                "Запрос чтения к Яндексу не выполнен из-за сетевой ошибки."
            ) from error
        if len(content) > MAX_RESPONSE_BYTES:
            raise RuntimeError("Ответ Яндекса превышает безопасный размер.")
        return HttpResponse(
            status=status,
            headers=response_headers,
            body=content,
        )


class YandexReadOnlyTransport:
    """Allow exactly three typed read operations against Yandex production APIs."""

    _ALLOWED = frozenset(
        {
            (
                "DIRECT_REPORTS",
                "api.direct.yandex.com",
                "/json/v501/reports",
                "v501",
                "Reports",
                "get",
                "POST",
            ),
            (
                "DIRECT",
                "api.direct.yandex.com",
                "/json/v501/campaigns",
                "v501",
                "Campaigns",
                "get",
                "POST",
            ),
            (
                "METRIKA",
                "api-metrika.yandex.net",
                "/stat/v1/data",
                "v1",
                "Statistics",
                "get",
                "GET",
            ),
        }
    )

    def __init__(
        self,
        *,
        configuration: ProductionReadConfiguration,
        credential_provider: CredentialProvider,
        http_client: HttpClient | None = None,
        policy: Mapping[str, Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if policy is None:
            raw_policy = json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
            if not isinstance(raw_policy, Mapping):
                raise RuntimeError("Gate 0 policy must be an object.")
            policy = raw_policy
        self.configuration = configuration
        self._credentials = credential_provider
        self._http = http_client or UrllibHttpClient()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._guard = HttpEgressGuard(
            policy,
            production_read_bindings={
                "direct_account": configuration.direct_account,
                "metrika_counter": configuration.metrika_counter_id,
            },
        )
        self._campaign_timezone_name: str | None = None
        self._campaign_timezone: ZoneInfo | None = None
        self.records: list[dict[str, str]] = []

    def read(self, request: VersionedReadRequest) -> Any:
        signature = (
            request.system,
            request.host,
            request.path,
            request.version,
            request.service,
            request.method,
            request.http_verb.upper(),
        )
        if signature not in self._ALLOWED:
            raise EgressDenied(
                "EXTERNAL_EGRESS_DENIED: request is outside the production "
                "read-only allowlist."
            )
        if request.system == "DIRECT_REPORTS":
            return self._read_direct_report(request)
        if request.system == "DIRECT":
            return self._read_direct_campaign(request)
        return self._read_metrika_report(request)

    @property
    def campaign_timezone(self) -> ZoneInfo:
        if self._campaign_timezone is None:
            raise RuntimeError("Часовой пояс кампании ещё не прочитан.")
        return self._campaign_timezone

    def _read_direct_report(
        self,
        request: VersionedReadRequest,
    ) -> DirectReportBlock:
        expected = {
            "account": self.configuration.direct_account,
            "campaign": self.configuration.campaign_id,
        }
        self._validate_payload(request.payload, expected, includes_period=True)
        if self._campaign_timezone_name is None:
            raise RuntimeError(
                "Часовой пояс кампании должен быть прочитан до отчёта Директа."
            )
        url = "https://api.direct.yandex.com/json/v501/reports"
        self._authorize(
            request,
            url,
            CredentialProfile.DIRECT_PROD_READ,
            self.configuration.direct_account,
        )
        params = {
            "SelectionCriteria": {
                "DateFrom": request.payload["period_start"],
                "DateTo": request.payload["period_end"],
                "Filter": [
                    {
                        "Field": "CampaignId",
                        "Operator": "IN",
                        "Values": [self.configuration.campaign_id],
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
            "OrderBy": [{"Field": "Date"}],
            "ReportName": (
                "MOX_ADV_RO_"
                + self.configuration.campaign_id
                + "_"
                + self._clock().astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            ),
            "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
            "DateRangeType": "CUSTOM_DATE",
            "Format": "TSV",
            "IncludeVAT": "NO",
            "IncludeDiscount": "NO",
        }
        headers = self._direct_headers()
        headers.update(
            {
                "Content-Type": "application/json; charset=utf-8",
                "processingMode": "online",
                "skipReportHeader": "true",
                "skipReportSummary": "true",
            }
        )
        response = self._perform(
            method="POST",
            url=url,
            headers=headers,
            body=json.dumps(
                {"params": params},
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        if response.status in {201, 202}:
            raise RuntimeError(
                "Отчёт Директа поставлен в очередь; повторите read-only запуск позже."
            )
        self._require_success(response, "Яндекс.Директ Reports")
        rows_by_date: dict[str, DirectReportRow] = {}
        try:
            reader = csv.DictReader(
                io.StringIO(response.body.decode("utf-8")),
                delimiter="\t",
            )
            if reader.fieldnames != [
                "Date",
                "CampaignId",
                "Impressions",
                "Clicks",
                "Cost",
            ]:
                raise ValueError
            for row in reader:
                if row["CampaignId"] != self.configuration.campaign_id:
                    raise ValueError
                report_row = DirectReportRow(
                    campaign=str(row["CampaignId"]),
                    date=str(row["Date"]),
                    impressions=self._nonnegative_integer(row["Impressions"]),
                    clicks=self._nonnegative_integer(row["Clicks"]),
                    cost_micros=self._nonnegative_integer(row["Cost"]),
                )
                rows_by_date[report_row.date] = report_row
        except (UnicodeError, TypeError, ValueError) as error:
            raise RuntimeError(
                "Ответ Яндекс.Директ Reports не соответствует read-only контракту."
            ) from error
        rows = tuple(
            rows_by_date.get(
                day.isoformat(),
                DirectReportRow(
                    campaign=self.configuration.campaign_id,
                    date=day.isoformat(),
                    impressions=0,
                    clicks=0,
                    cost_micros=0,
                ),
            )
            for day in self._date_range(request.payload)
        )
        retrieved_at = self._timestamp()
        self._record(request)
        return DirectReportBlock(
            source="DIRECT_REPORTS",
            retrieved_at=retrieved_at,
            watermark=retrieved_at,
            period_start=str(request.payload["period_start"]),
            period_end=str(request.payload["period_end"]),
            timezone=self._campaign_timezone_name,
            attribution=str(request.payload["attribution"]),
            currency=self.configuration.currency,
            rows=rows,
        )

    def _read_direct_campaign(
        self,
        request: VersionedReadRequest,
    ) -> DirectCampaignStateBlock:
        self._validate_payload(
            request.payload,
            {
                "account": self.configuration.direct_account,
                "campaign": self.configuration.campaign_id,
            },
        )
        url = "https://api.direct.yandex.com/json/v501/campaigns"
        self._authorize(
            request,
            url,
            CredentialProfile.DIRECT_PROD_READ,
            self.configuration.direct_account,
        )
        response = self._perform(
            method="POST",
            url=url,
            headers={
                **self._direct_headers(),
                "Content-Type": "application/json; charset=utf-8",
            },
            body=json.dumps(
                {
                    "method": "get",
                    "params": {
                        "SelectionCriteria": {
                            "Ids": [int(self.configuration.campaign_id)],
                            "Types": ["UNIFIED_CAMPAIGN"],
                        },
                        "FieldNames": [
                            "Id",
                            "Name",
                            "StartDate",
                            "EndDate",
                            "Type",
                            "Status",
                            "State",
                            "TimeZone",
                        ],
                        "UnifiedCampaignFieldNames": [
                            "AttributionModel",
                            "BiddingStrategy",
                        ],
                    },
                },
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        self._require_success(response, "Яндекс.Директ Campaigns.get")
        try:
            payload = json.loads(response.body.decode("utf-8"))
            campaigns = payload["result"]["Campaigns"]
            if not isinstance(campaigns, list) or len(campaigns) != 1:
                raise ValueError
            campaign = campaigns[0]
            if (
                str(campaign["Id"]) != self.configuration.campaign_id
                or campaign["Type"] != "UNIFIED_CAMPAIGN"
            ):
                raise ValueError
            timezone_name = str(campaign["TimeZone"])
            if not timezone_name or len(timezone_name) > 64:
                raise ValueError
            campaign_timezone = ZoneInfo(timezone_name)
            unified = campaign.get("UnifiedCampaign") or {}
            bidding = unified.get("BiddingStrategy") or {}
            search = bidding.get("Search") or {}
            strategy = str(search.get("BiddingStrategyType") or "UNKNOWN")
            weekly_budget = self._find_positive_integer(
                search,
                ("WeeklySpendLimit",),
            )
            if weekly_budget is None or weekly_budget <= 0:
                raise ValueError
            bid = self._find_positive_integer(
                search,
                ("BidCeiling", "AverageCpc", "Cpa"),
            )
            current_bid = 0 if bid is None else bid
            state = str(campaign["State"])
            status = str(campaign["Status"])
        except (
            json.JSONDecodeError,
            KeyError,
            TypeError,
            UnicodeError,
            ValueError,
            ZoneInfoNotFoundError,
        ) as error:
            raise RuntimeError(
                "Ответ Яндекс.Директ Campaigns.get не соответствует "
                "read-only контракту."
            ) from error
        self._campaign_timezone_name = timezone_name
        self._campaign_timezone = campaign_timezone
        retrieved = self._clock().astimezone(timezone.utc)
        retrieved_local = retrieved.astimezone(campaign_timezone)
        week_start = retrieved_local.date() - timedelta(days=retrieved_local.weekday())
        retrieved_at = retrieved.isoformat()
        self._record(request)
        return DirectCampaignStateBlock(
            source="DIRECT_CAMPAIGN_STATE",
            retrieved_at=retrieved_at,
            watermark=retrieved_at,
            campaign=self.configuration.campaign_id,
            campaign_state=state,
            group_state="NOT_REQUESTED",
            ad_state=status,
            strategy=strategy,
            current_weekly_budget_micros=weekly_budget,
            budget_period_start=datetime.combine(
                week_start,
                time.min,
                tzinfo=campaign_timezone,
            )
            .astimezone(timezone.utc)
            .isoformat(),
            budget_period_end=datetime.combine(
                week_start + timedelta(days=7),
                time.min,
                tzinfo=campaign_timezone,
            )
            .astimezone(timezone.utc)
            .isoformat(),
            current_search_bid_micros=current_bid,
            ad_variant="NOT_REQUESTED",
            object_config_version=(
                "sha256:" + hashlib.sha256(response.body).hexdigest()
            ),
            last_change_author="UNAVAILABLE_READ_ONLY",
            last_change_occurred_at=retrieved_at,
        )

    def _read_metrika_report(
        self,
        request: VersionedReadRequest,
    ) -> MetrikaReportBlock:
        expected = {
            "counter": self.configuration.metrika_counter_id,
            "campaign": self.configuration.campaign_id,
            "goal": self.configuration.metrika_goal_id,
        }
        self._validate_payload(request.payload, expected, includes_period=True)
        attribution = str(request.payload["attribution"])
        dimension = f"ym:s:{attribution}DirectClickOrder"
        metrika_timezone = self._metrika_timezone_offset(request.payload)
        query = urlencode(
            {
                "ids": self.configuration.metrika_counter_id,
                "date1": request.payload["period_start"],
                "date2": request.payload["period_end"],
                "dimensions": f"ym:s:date,{dimension}",
                "metrics": (
                    f"ym:s:visits,ym:s:goal{self.configuration.metrika_goal_id}visits"
                ),
                "filters": (f"{dimension}=='{self.configuration.campaign_id}'"),
                "accuracy": "full",
                "limit": "100000",
                "timezone": metrika_timezone,
            }
        )
        url = "https://api-metrika.yandex.net/stat/v1/data?" + query
        self._authorize(
            request,
            url,
            CredentialProfile.METRIKA_PROD_READ,
            self.configuration.metrika_counter_id,
        )
        response = self._perform(
            method="GET",
            url=url,
            headers={
                "Authorization": (
                    "OAuth " + self._credentials.get(METRIKA_CREDENTIAL_BINDING)
                ),
                "Accept": "application/json",
            },
            body=None,
        )
        self._require_success(response, "Яндекс.Метрика Statistics.get")
        rows_by_date: dict[str, MetrikaReportRow] = {}
        try:
            payload = json.loads(response.body.decode("utf-8"))
            raw_rows = payload["data"]
            if not isinstance(raw_rows, list):
                raise ValueError
            for raw in raw_rows:
                dimensions = raw["dimensions"]
                metrics = raw["metrics"]
                row_date = str(dimensions[0]["name"])
                campaign_dimension = dimensions[1]
                if not isinstance(campaign_dimension, Mapping):
                    raise ValueError
                campaign_value = campaign_dimension.get("id")
                if campaign_value is None:
                    campaign_value = campaign_dimension["name"]
                campaign = str(campaign_value)
                if campaign != self.configuration.campaign_id:
                    raise ValueError
                rows_by_date[row_date] = MetrikaReportRow(
                    campaign=campaign,
                    goal=self.configuration.metrika_goal_id,
                    date=row_date,
                    visits=self._metric_integer(metrics[0]),
                    goal_visits=self._metric_integer(metrics[1]),
                )
        except (
            json.JSONDecodeError,
            KeyError,
            TypeError,
            UnicodeError,
            ValueError,
        ) as error:
            raise RuntimeError(
                "Ответ Яндекс.Метрики не соответствует read-only контракту."
            ) from error
        rows = tuple(
            rows_by_date.get(
                day.isoformat(),
                MetrikaReportRow(
                    campaign=self.configuration.campaign_id,
                    goal=self.configuration.metrika_goal_id,
                    date=day.isoformat(),
                    visits=0,
                    goal_visits=0,
                ),
            )
            for day in self._date_range(request.payload)
        )
        retrieved_at = self._timestamp()
        self._record(request)
        return MetrikaReportBlock(
            source="METRIKA_REPORT",
            retrieved_at=retrieved_at,
            watermark=retrieved_at,
            period_start=str(request.payload["period_start"]),
            period_end=str(request.payload["period_end"]),
            timezone=str(self._campaign_timezone_name),
            attribution=attribution,
            rows=rows,
        )

    def _authorize(
        self,
        request: VersionedReadRequest,
        url: str,
        profile: CredentialProfile,
        trusted_target: str,
    ) -> None:
        self._guard.authorize(
            request.http_verb,
            url,
            version=request.version,
            service=request.service,
            operation=request.method,
            authority=EgressAuthority(
                credential_profile=profile,
                trusted_target=trusted_target,
            ),
        )

    def _perform(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> HttpResponse:
        response = self._http.perform(
            method=method,
            url=url,
            headers=headers,
            body=body,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
        )
        if len(response.body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("Ответ Яндекса превышает безопасный размер.")
        return response

    def _direct_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": (
                "Bearer " + self._credentials.get(DIRECT_CREDENTIAL_BINDING)
            ),
            "Accept": "application/json, text/tab-separated-values",
            "Accept-Language": "ru",
        }
        if self.configuration.direct_client_login is not None:
            headers["Client-Login"] = self.configuration.direct_client_login
        return headers

    @staticmethod
    def _validate_payload(
        payload: Mapping[str, Any],
        expected: Mapping[str, str],
        *,
        includes_period: bool = False,
    ) -> None:
        fields = set(expected)
        if includes_period:
            fields.update({"period_start", "period_end", "attribution"})
        if set(payload) != fields or any(
            payload.get(field) != expected_value
            for field, expected_value in expected.items()
        ):
            raise EgressDenied(
                "EXTERNAL_EGRESS_DENIED: request payload is outside the "
                "trusted production scope."
            )
        if includes_period:
            try:
                start = date.fromisoformat(str(payload["period_start"]))
                end = date.fromisoformat(str(payload["period_end"]))
            except ValueError as error:
                raise EgressDenied(
                    "EXTERNAL_EGRESS_DENIED: report period is invalid."
                ) from error
            if end < start or (end - start).days > 30:
                raise EgressDenied(
                    "EXTERNAL_EGRESS_DENIED: report period is outside limits."
                )
            attribution = payload.get("attribution")
            if attribution not in {"AUTO", "automatic"}:
                raise EgressDenied(
                    "EXTERNAL_EGRESS_DENIED: attribution is not approved."
                )

    @staticmethod
    def _require_success(response: HttpResponse, service: str) -> None:
        if response.status != 200:
            raise RuntimeError(
                f"{service} вернул безопасно скрытую ошибку HTTP {response.status}."
            )

    @staticmethod
    def _nonnegative_integer(value: Any) -> int:
        parsed = int(str(value))
        if parsed < 0:
            raise ValueError
        return parsed

    @classmethod
    def _optional_nonnegative_integer(cls, value: Any) -> int | None:
        if value is None:
            return None
        return cls._nonnegative_integer(value)

    @classmethod
    def _find_positive_integer(
        cls,
        value: Any,
        keys: Sequence[str],
    ) -> int | None:
        if isinstance(value, Mapping):
            for key in keys:
                if key in value:
                    candidate = value[key]
                    if isinstance(candidate, (Mapping, list)):
                        parsed = cls._find_positive_integer(candidate, keys)
                    else:
                        parsed = cls._optional_nonnegative_integer(candidate)
                    if parsed is not None and parsed > 0:
                        return parsed
            for nested in value.values():
                found = cls._find_positive_integer(nested, keys)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = cls._find_positive_integer(nested, keys)
                if found is not None:
                    return found
        return None

    def _metrika_timezone_offset(
        self,
        payload: Mapping[str, Any],
    ) -> str:
        campaign_timezone = self._campaign_timezone
        if campaign_timezone is None:
            raise RuntimeError("Часовой пояс кампании должен быть прочитан до Метрики.")
        offsets: set[timedelta] = set()
        for field in ("period_start", "period_end"):
            local_noon = datetime.combine(
                date.fromisoformat(str(payload[field])),
                time(hour=12),
                tzinfo=campaign_timezone,
            )
            offset = local_noon.utcoffset()
            if offset is None:
                raise RuntimeError("Не удалось определить часовой пояс кампании.")
            offsets.add(offset)
        if len(offsets) != 1:
            raise RuntimeError(
                "Период пересекает смену UTC-смещения кампании; "
                "read-only анализ остановлен."
            )
        total_minutes = int(offsets.pop().total_seconds() // 60)
        sign = "+" if total_minutes >= 0 else "-"
        hours, minutes = divmod(abs(total_minutes), 60)
        return f"{sign}{hours:02d}:{minutes:02d}"

    @staticmethod
    def _metric_integer(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError
        parsed = int(value)
        if parsed < 0 or float(value) != parsed:
            raise ValueError
        return parsed

    @staticmethod
    def _date_range(payload: Mapping[str, Any]) -> tuple[date, ...]:
        start = date.fromisoformat(str(payload["period_start"]))
        end = date.fromisoformat(str(payload["period_end"]))
        return tuple(
            start + timedelta(days=offset) for offset in range((end - start).days + 1)
        )

    def _timestamp(self) -> str:
        return self._clock().astimezone(timezone.utc).isoformat()

    def _record(self, request: VersionedReadRequest) -> None:
        self.records.append(
            {
                "system": request.system,
                "http_method": request.http_verb.upper(),
                "host": request.host,
                "path": request.path,
                "operation": request.method,
            }
        )


class YandexCampaignCatalogTransport:
    """Read a bounded campaign catalog with the Direct read-only profile."""

    _URL = "https://api.direct.yandex.com/json/v501/campaigns"
    _FIELD_NAMES = (
        "Id",
        "Name",
        "ClientInfo",
        "StartDate",
        "EndDate",
        "TimeZone",
        "DailyBudget",
        "Type",
        "Status",
        "State",
        "StatusPayment",
    )

    def __init__(
        self,
        *,
        direct_account: str,
        credential_provider: CredentialProvider,
        policy: Mapping[str, Any],
        http_client: HttpClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if _SAFE_DIRECT_CLIENT_LOGIN.fullmatch(direct_account) is None:
            raise RuntimeError("Client login Яндекс Директа некорректен.")
        self.direct_account = direct_account
        self._credentials = credential_provider
        self._http = http_client or UrllibHttpClient()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._guard = HttpEgressGuard(
            policy,
            production_read_bindings={"direct_account": direct_account},
        )
        self.records: list[dict[str, str]] = []

    def read(self) -> dict[str, Any]:
        self._guard.authorize(
            "POST",
            self._URL,
            version="v501",
            service="Campaigns",
            operation="get",
            authority=EgressAuthority(
                credential_profile=CredentialProfile.DIRECT_PROD_READ,
                trusted_target=self.direct_account,
            ),
        )
        items: list[dict[str, Any]] = []
        offset = 0
        truncated = False
        while True:
            response = self._http.perform(
                method="POST",
                url=self._URL,
                headers=self._headers(),
                body=json.dumps(
                    {
                        "method": "get",
                        "params": {
                            "SelectionCriteria": {},
                            "FieldNames": list(self._FIELD_NAMES),
                            "Page": {
                                "Limit": DIRECT_CAMPAIGN_CATALOG_PAGE_SIZE,
                                "Offset": offset,
                            },
                        },
                    },
                    separators=(",", ":"),
                ).encode("utf-8"),
                timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            )
            if len(response.body) > MAX_RESPONSE_BYTES:
                raise RuntimeError("Ответ Яндекса превышает безопасный размер.")
            if response.status != 200:
                raise RuntimeError(
                    "Яндекс.Директ Campaigns.get вернул безопасно скрытую "
                    f"ошибку HTTP {response.status}."
                )
            page_items, limited_by = self._parse_page(response.body)
            items.extend(page_items)
            self.records.append(
                {
                    "system": "DIRECT",
                    "http_method": "POST",
                    "host": "api.direct.yandex.com",
                    "path": "/json/v501/campaigns",
                    "operation": "get",
                }
            )
            if limited_by is None:
                break
            if len(items) >= DIRECT_CAMPAIGN_CATALOG_MAX_ITEMS:
                items = items[:DIRECT_CAMPAIGN_CATALOG_MAX_ITEMS]
                truncated = True
                break
            if limited_by <= offset or limited_by > DIRECT_CAMPAIGN_CATALOG_MAX_ITEMS:
                raise RuntimeError(
                    "Пагинация Яндекс.Директа не соответствует read-only контракту."
                )
            offset = limited_by

        fetched_at = self._clock().astimezone(timezone.utc).isoformat()
        return {
            "source": "YANDEX_DIRECT",
            "access": "READ_ONLY",
            "write_requests_allowed": False,
            "account": self.direct_account,
            "fetched_at": fetched_at,
            "total": len(items),
            "truncated": truncated,
            "items": items,
        }

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": (
                "Bearer " + self._credentials.get(DIRECT_CREDENTIAL_BINDING)
            ),
            "Client-Login": self.direct_account,
            "Accept": "application/json",
            "Accept-Language": "ru",
            "Content-Type": "application/json; charset=utf-8",
        }

    @classmethod
    def _parse_page(
        cls,
        body: bytes,
    ) -> tuple[list[dict[str, Any]], int | None]:
        try:
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, Mapping) or "error" in payload:
                raise ValueError
            result = payload["result"]
            if not isinstance(result, Mapping):
                raise ValueError
            raw_campaigns = result["Campaigns"]
            if not isinstance(raw_campaigns, list):
                raise ValueError
            campaigns = [cls._parse_campaign(item) for item in raw_campaigns]
            raw_limited_by = result.get("LimitedBy")
            limited_by = (
                None
                if raw_limited_by is None
                else cls._nonnegative_integer(raw_limited_by)
            )
        except (
            json.JSONDecodeError,
            KeyError,
            TypeError,
            UnicodeError,
            ValueError,
        ) as error:
            raise RuntimeError(
                "Ответ Яндекс.Директ Campaigns.get не соответствует "
                "контракту каталога."
            ) from error
        return campaigns, limited_by

    @classmethod
    def _parse_campaign(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ValueError
        campaign_id = cls._positive_id(value["Id"])
        name = cls._bounded_text(value["Name"], maximum=255)
        campaign_type = cls._code(value["Type"])
        status = cls._code(value["Status"])
        state = cls._code(value["State"])
        status_payment = cls._optional_code(value.get("StatusPayment"))
        start_date = cls._date(value["StartDate"])
        end_date = cls._optional_date(value.get("EndDate"))
        timezone_name = cls._optional_text(value.get("TimeZone"), maximum=64)
        client_info = cls._optional_text(value.get("ClientInfo"), maximum=255)
        daily_budget = value.get("DailyBudget")
        daily_budget_micros: int | None = None
        daily_budget_mode: str | None = None
        if daily_budget is not None:
            if not isinstance(daily_budget, Mapping):
                raise ValueError
            daily_budget_micros = cls._nonnegative_integer(daily_budget["Amount"])
            daily_budget_mode = cls._optional_code(daily_budget.get("Mode"))
        return {
            "campaign_id": campaign_id,
            "name": name,
            "client_info": client_info,
            "start_date": start_date,
            "end_date": end_date,
            "timezone": timezone_name,
            "daily_budget_micros": daily_budget_micros,
            "daily_budget_mode": daily_budget_mode,
            "type": campaign_type,
            "status": status,
            "state": state,
            "status_payment": status_payment,
        }

    @staticmethod
    def _positive_id(value: Any) -> str:
        parsed = str(value)
        if _POSITIVE_ASCII_ID.fullmatch(parsed) is None:
            raise ValueError
        return parsed

    @staticmethod
    def _nonnegative_integer(value: Any) -> int:
        if isinstance(value, bool):
            raise ValueError
        serialized = str(value)
        if re.fullmatch(r"[0-9]+", serialized) is None:
            raise ValueError
        return int(serialized)

    @staticmethod
    def _bounded_text(value: Any, *, maximum: int) -> str:
        if not isinstance(value, str) or not 1 <= len(value) <= maximum:
            raise ValueError
        return value

    @classmethod
    def _optional_text(cls, value: Any, *, maximum: int) -> str | None:
        if value is None:
            return None
        return cls._bounded_text(value, maximum=maximum)

    @staticmethod
    def _code(value: Any) -> str:
        if (
            not isinstance(value, str)
            or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value) is None
        ):
            raise ValueError
        return value

    @classmethod
    def _optional_code(cls, value: Any) -> str | None:
        if value is None:
            return None
        return cls._code(value)

    @staticmethod
    def _date(value: Any) -> str:
        parsed = str(value)
        date.fromisoformat(parsed)
        return parsed

    @classmethod
    def _optional_date(cls, value: Any) -> str | None:
        if value is None:
            return None
        return cls._date(value)


class YandexProductionReader:
    """Load non-secret bindings and collect one linked real-data snapshot."""

    def __init__(
        self,
        *,
        configuration_path: Path = DEFAULT_PRODUCTION_READ_CONFIG_PATH,
        environment_path: Path = DEFAULT_ENVIRONMENT_PATH,
        credential_provider: CredentialProvider | None = None,
        http_client: HttpClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._credential_root = ROOT
        self.configuration_path = configuration_path
        self.credential_provider = credential_provider or DotEnvCredentialProvider(
            environment_path
        )
        self.http_client = http_client
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.last_records: tuple[Mapping[str, str], ...] = ()
        self.last_catalog_records: tuple[Mapping[str, str], ...] = ()

    def campaign_catalog_readiness(
        self,
        policy: Mapping[str, Any],
    ) -> dict[str, Any]:
        credential_policy_ready = self._credential_policy_matches(policy)
        checks: list[dict[str, Any]] = [
            {
                "id": "production_read_credential_policy",
                "label": (
                    "Политика защищённого read-only .env активна"
                    if credential_policy_ready
                    else (
                        "Политика защищённого read-only .env отсутствует "
                        "или изменена"
                    )
                ),
                "ready": credential_policy_ready,
            }
        ]
        if credential_policy_ready:
            try:
                snapshot = self.credential_provider.snapshot()
                snapshot.get(DIRECT_CREDENTIAL_BINDING)
                direct_account = snapshot.direct_configuration_binding()
            except RuntimeError as error:
                checks.append(
                    {
                        "id": "direct_catalog_binding",
                        "label": str(error),
                        "ready": False,
                    }
                )
            else:
                checks.extend(
                    [
                        {
                            "id": "direct_read_credential",
                            "label": snapshot.describe(
                                DIRECT_CREDENTIAL_BINDING
                            ),
                            "ready": True,
                        },
                        {
                            "id": "direct_catalog_binding",
                            "label": (
                                "Client login Яндекс Директа настроен: "
                                f"{direct_account}"
                            ),
                            "ready": True,
                        },
                    ]
                )
        blockers = [item["label"] for item in checks if not item["ready"]]
        return {
            "ready": not blockers,
            "checks": checks,
            "blockers": blockers,
            "access": "READ_ONLY",
            "data_source": "YANDEX_DIRECT_API",
            "external_reads_enabled": True,
            "write_requests_allowed": False,
        }

    def list_campaigns(
        self,
        *,
        policy: Mapping[str, Any],
    ) -> dict[str, Any]:
        readiness = self.campaign_catalog_readiness(policy)
        if not readiness["ready"]:
            raise RuntimeError("; ".join(readiness["blockers"]))
        snapshot = self.credential_provider.snapshot()
        transport = YandexCampaignCatalogTransport(
            direct_account=snapshot.direct_configuration_binding(),
            credential_provider=snapshot,
            http_client=self.http_client,
            policy=policy,
            clock=self.clock,
        )
        catalog = transport.read()
        self.last_catalog_records = tuple(transport.records)
        return catalog

    def readiness(self, policy: Mapping[str, Any]) -> dict[str, Any]:
        credential_policy_ready = self._credential_policy_matches(policy)
        credential_snapshot: DotEnvCredentialSnapshot | None = None
        credential_snapshot_error: RuntimeError | None = None
        if credential_policy_ready:
            try:
                credential_snapshot = self.credential_provider.snapshot()
            except RuntimeError as error:
                credential_snapshot_error = error
            if credential_snapshot is None:
                config_ready = False
                config_message = str(credential_snapshot_error)
            else:
                try:
                    self._load_configuration(credential_snapshot)
                    config_ready = True
                    config_message = (
                        "Привязки client login, кампании, счётчика и цели настроены"
                    )
                except ProductionReadConfigurationError as error:
                    config_ready = False
                    config_message = str(error)
        else:
            config_ready = False
            config_message = (
                "Production-конфигурация не читается без доверенной политики .env"
            )
        if credential_policy_ready:
            credential_policy_message = "Политика защищённого read-only .env активна"
            if credential_snapshot is None:
                credential_error = str(credential_snapshot_error)
                direct_credential = {
                    "label": f"Яндекс.Директ: {credential_error}",
                    "ready": False,
                }
                metrika_credential = {
                    "label": f"Яндекс.Метрика: {credential_error}",
                    "ready": False,
                }
            else:
                direct_credential = self._credential_readiness(
                    DIRECT_CREDENTIAL_BINDING,
                    "Яндекс.Директ",
                    credential_provider=credential_snapshot,
                )
                metrika_credential = self._credential_readiness(
                    METRIKA_CREDENTIAL_BINDING,
                    "Яндекс.Метрика",
                    credential_provider=credential_snapshot,
                )
        else:
            credential_policy_message = (
                "Политика защищённого read-only .env отсутствует или изменена"
            )
            direct_credential = {
                "label": "Яндекс.Директ: чтение токена запрещено политикой",
                "ready": False,
            }
            metrika_credential = {
                "label": "Яндекс.Метрика: чтение токена запрещено политикой",
                "ready": False,
            }
        checks = [
            {
                "id": "production_read_bindings",
                "label": config_message,
                "ready": config_ready,
            },
            {
                "id": "production_read_credential_policy",
                "label": credential_policy_message,
                "ready": credential_policy_ready,
            },
            {
                "id": "direct_read_credential",
                **direct_credential,
            },
            {
                "id": "metrika_read_credential",
                **metrika_credential,
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

    def _credential_policy_matches(self, policy: Mapping[str, Any]) -> bool:
        credentials = policy.get("credentials")
        if not isinstance(credentials, Mapping):
            return False
        override = credentials.get("local_read_only_override")
        if (
            override != LOCAL_READ_ONLY_CREDENTIAL_POLICY
            or type(self.credential_provider) is not DotEnvCredentialProvider
        ):
            return False
        expected_path = (
            self._credential_root / LOCAL_READ_ONLY_CREDENTIAL_POLICY["path"]
        )
        return self.credential_provider.path.absolute() == expected_path.absolute()

    def _credential_readiness(
        self,
        binding: str,
        service: str,
        *,
        credential_provider: CredentialProvider | None = None,
    ) -> dict[str, Any]:
        provider = credential_provider or self.credential_provider
        try:
            provider.get(binding)
        except RuntimeError as error:
            return {
                "label": f"{service}: {error}",
                "ready": False,
            }
        describe = getattr(provider, "describe", None)
        if callable(describe):
            label = str(describe(binding))
        else:
            label = f"Read-only OAuth-профиль для {service} в настроенном хранилище"
        return {
            "label": label,
            "ready": True,
        }

    def _load_configuration(
        self,
        credential_snapshot: DotEnvCredentialSnapshot | None = None,
    ) -> ProductionReadConfiguration:
        raw_configuration = dict(
            ProductionReadConfiguration.read_mapping(self.configuration_path)
        )
        if type(self.credential_provider) is not DotEnvCredentialProvider:
            return ProductionReadConfiguration.from_mapping(raw_configuration)
        try:
            snapshot = credential_snapshot or self.credential_provider.snapshot()
            client_login, counter_id = snapshot.configuration_bindings()
        except RuntimeError as error:
            raise ProductionReadConfigurationError(str(error)) from error
        raw_configuration.update(
            {
                "direct_account": client_login,
                "direct_client_login": client_login,
                "metrika_counter_id": counter_id,
            }
        )
        return ProductionReadConfiguration.from_mapping(raw_configuration)

    def collect_snapshot(
        self,
        *,
        policy: Mapping[str, Any],
        observation_id: str,
        generated_at: datetime,
        progress_callback: Callable[[dict[str, str]], None] | None = None,
    ) -> IntegratedPerformanceSnapshot:
        if not self._credential_policy_matches(policy):
            raise RuntimeError(
                "Политика защищённого read-only .env отсутствует или изменена."
            )
        credential_snapshot = self.credential_provider.snapshot()
        configuration = self._load_configuration(credential_snapshot)
        transport = YandexReadOnlyTransport(
            configuration=configuration,
            credential_provider=credential_snapshot,
            http_client=self.http_client,
            policy=policy,
            clock=self.clock,
        )
        if progress_callback is not None:
            progress_callback({"step": "direct", "status": "RUNNING"})
        state_block = DirectCampaignStateReadConnectorV1(transport).read_campaign_state(
            DirectCampaignStateReadQuery(
                account=configuration.direct_account,
                campaign=configuration.campaign_id,
            )
        )
        period_anchor = generated_at.astimezone(transport.campaign_timezone)
        period_end = period_anchor.date() - timedelta(days=1)
        period_start = period_end - timedelta(days=configuration.lookback_days - 1)
        direct_block = DirectReportsReadConnectorV1(transport).read_report(
            DirectReportsReadQuery(
                account=configuration.direct_account,
                campaign=configuration.campaign_id,
                period_start=period_start.isoformat(),
                period_end=period_end.isoformat(),
                attribution=str(policy["attribution"]["direct"]),
            )
        )
        if progress_callback is not None:
            progress_callback({"step": "direct", "status": "PASSED"})
            progress_callback({"step": "metrika", "status": "RUNNING"})
        metrika_block = MetrikaReportReadConnectorV1(transport).read_metrika_report(
            MetrikaReportReadQuery(
                counter=configuration.metrika_counter_id,
                campaign=configuration.campaign_id,
                goal=configuration.metrika_goal_id,
                period_start=period_start.isoformat(),
                period_end=period_end.isoformat(),
                attribution=str(policy["attribution"]["metrika"]),
            )
        )
        if progress_callback is not None:
            progress_callback({"step": "metrika", "status": "PASSED"})
            progress_callback({"step": "analytics", "status": "RUNNING"})
        completed_at = self.clock().astimezone(timezone.utc)
        snapshot = build_observe_snapshot_from_blocks(
            policy=policy,
            observation_id=observation_id,
            generated_at=completed_at.isoformat(),
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            trusted_scope=configuration.trusted_scope(),
            direct_block=direct_block,
            state_block=state_block,
            metrika_block=metrika_block,
        )
        if progress_callback is not None:
            progress_callback({"step": "analytics", "status": "PASSED"})
        self.last_records = tuple(transport.records)
        return snapshot
