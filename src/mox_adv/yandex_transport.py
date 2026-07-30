"""Allowlisted Yandex read transport and isolated credential resolution."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TextIO


@dataclass(frozen=True)
class YandexReadEndpoint:
    """Describe one immutable production read operation."""

    system: str
    method: str
    host: str
    path: str
    operation: str
    query_allowed: bool = False

    def __post_init__(self) -> None:
        if self.method not in {"GET", "POST"}:
            raise ValueError("Yandex read endpoint method is unsupported.")
        if not self.host or not self.path.startswith("/"):
            raise ValueError("Yandex read endpoint target is invalid.")

    @property
    def base_url(self) -> str:
        return "https://" + self.host + self.path

    def allows(self, *, method: str, url: str) -> bool:
        parsed = urllib.parse.urlsplit(url)
        return (
            method == self.method
            and parsed.scheme == "https"
            and parsed.hostname == self.host
            and parsed.port is None
            and parsed.path == self.path
            and not parsed.fragment
            and (self.query_allowed or not parsed.query)
        )

    def audit_record(self) -> Mapping[str, str]:
        return {
            "system": self.system,
            "http_method": self.method,
            "host": self.host,
            "path": self.path,
            "operation": self.operation,
        }


DIRECT_REPORTS_READ = YandexReadEndpoint(
    system="DIRECT_REPORTS",
    method="POST",
    host="api.direct.yandex.com",
    path="/json/v501/reports",
    operation="get",
)
DIRECT_CAMPAIGN_STATE_READ = YandexReadEndpoint(
    system="DIRECT",
    method="POST",
    host="api.direct.yandex.com",
    path="/json/v501/campaigns",
    operation="get",
)
METRIKA_REPORT_READ = YandexReadEndpoint(
    system="METRIKA",
    method="GET",
    host="api-metrika.yandex.net",
    path="/stat/v1/data",
    operation="get",
    query_allowed=True,
)
YANDEX_READ_ENDPOINTS: tuple[YandexReadEndpoint, ...] = (
    DIRECT_REPORTS_READ,
    DIRECT_CAMPAIGN_STATE_READ,
    METRIKA_REPORT_READ,
)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


def json_response_object(
    response: HttpResponse,
    provider: str,
) -> dict[str, Any]:
    if response.status < 200 or response.status >= 300:
        raise RuntimeError(f"{provider} read failed with HTTP {response.status}.")
    try:
        value = json.loads(response.body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"{provider} returned invalid JSON.") from error
    if not isinstance(value, dict):
        raise TypeError(f"{provider} returned a non-object JSON response.")
    return value


def required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError(field + " must be a non-empty string.")
    return value


def nonnegative_count(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(field + " must be a non-negative integer.")
    return value


def object_mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(field + " must be an object.")
    return value


def nonempty_array(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, list) or not value or len(value) > 1_000:
        raise ValueError(field + " must contain 1 to 1000 items.")
    return tuple(value)


class HttpClient(Protocol):
    def perform(
        self,
        *,
        endpoint: YandexReadEndpoint,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> HttpResponse: ...


class UrllibHttpClient:
    """Send only one of the immutable, allowlisted read operations."""

    def perform(
        self,
        *,
        endpoint: YandexReadEndpoint,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> HttpResponse:
        if endpoint not in YANDEX_READ_ENDPOINTS or not endpoint.allows(
            method=endpoint.method,
            url=url,
        ):
            raise ValueError("The provider read URL is not allowlisted.")
        request = urllib.request.Request(
            url=url,
            data=body,
            headers=dict(headers),
            method=endpoint.method,
        )
        try:
            with urllib.request.urlopen(
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
    """Resolve exactly one named secret without exposing sibling credentials."""

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
        with self._path.open(encoding="utf-8") as stream:
            return self._read_from(stream)

    def _read_from(self, stream: TextIO) -> str:
        for raw_line in stream:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == self._name:
                return value.strip()
        return ""
