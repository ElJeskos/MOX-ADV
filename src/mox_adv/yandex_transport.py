"""Allowlisted Yandex read transport and invocation-local receipts."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


@dataclass(frozen=True)
class YandexReadEndpoint:
    """Describe one immutable production read operation."""

    system: str
    method: str
    host: str
    path: str
    operation: str
    query_allowed: bool = False
    body_required: bool = False
    json_method: str | None = None

    def __post_init__(self) -> None:
        if self.method not in {"GET", "POST"}:
            raise ValueError("Yandex read endpoint method is unsupported.")
        if not self.host or not self.path.startswith("/"):
            raise ValueError("Yandex read endpoint target is invalid.")
        if self.method == "GET" and (
            self.body_required or self.json_method is not None
        ):
            raise ValueError("A GET read endpoint cannot require a request body.")
        if self.json_method is not None and (
            not self.body_required or self.json_method != self.operation
        ):
            raise ValueError(
                "A JSON method constraint must match the audited operation."
            )

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

    def allows_request(
        self,
        *,
        method: str,
        url: str,
        body: bytes | None,
    ) -> bool:
        if not self.allows(method=method, url=url):
            return False
        if method == "GET":
            return body is None
        if self.body_required and body is None:
            return False
        if self.json_method is None:
            return True
        try:
            payload = (
                json.loads(
                    body.decode("utf-8"),
                    object_pairs_hook=_reject_duplicate_json_keys,
                )
                if body is not None
                else None
            )
        except (UnicodeError, json.JSONDecodeError, ValueError):
            return False
        return (
            isinstance(payload, dict)
            and payload.get("method") == self.json_method
        )

    def audit_record(self) -> Mapping[str, str]:
        return {
            "system": self.system,
            "http_method": self.method,
            "host": self.host,
            "path": self.path,
            "operation": self.operation,
        }


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class CompletedReadReceiptV1:
    """Record one provider request only after the transport returns."""

    system: str
    http_method: str
    host: str
    path: str
    operation: str
    http_status: int

    @classmethod
    def from_response(
        cls,
        endpoint: YandexReadEndpoint,
        response: HttpResponse,
    ) -> CompletedReadReceiptV1:
        return cls(
            system=endpoint.system,
            http_method=endpoint.method,
            host=endpoint.host,
            path=endpoint.path,
            operation=endpoint.operation,
            http_status=response.status,
        )

    def as_dict(self) -> Mapping[str, str]:
        return {
            "system": self.system,
            "http_method": self.http_method,
            "host": self.host,
            "path": self.path,
            "operation": self.operation,
        }


class HttpClient(Protocol):
    def perform(
        self,
        *,
        endpoint: YandexReadEndpoint,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> HttpResponse: ...


class HttpReadSessionV1:
    """Bind immutable completed-request receipts to one read invocation."""

    def __init__(self, http_client: HttpClient) -> None:
        self._http_client = http_client
        self._receipts: list[CompletedReadReceiptV1] = []

    @property
    def receipts(self) -> tuple[CompletedReadReceiptV1, ...]:
        return tuple(self._receipts)

    def perform(
        self,
        *,
        endpoint: YandexReadEndpoint,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> HttpResponse:
        response = self._http_client.perform(
            endpoint=endpoint,
            url=url,
            headers=headers,
            body=body,
        )
        self._receipts.append(
            CompletedReadReceiptV1.from_response(endpoint, response)
        )
        return response


class UrllibHttpClient:
    """Send only one of the immutable, allowlisted read operations."""

    def __init__(
        self,
        allowed_endpoints: tuple[YandexReadEndpoint, ...],
    ) -> None:
        if not allowed_endpoints or len(set(allowed_endpoints)) != len(
            allowed_endpoints
        ):
            raise ValueError(
                "A provider transport requires unique read endpoints."
            )
        self._allowed_endpoints = frozenset(allowed_endpoints)

    def perform(
        self,
        *,
        endpoint: YandexReadEndpoint,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> HttpResponse:
        if (
            endpoint not in self._allowed_endpoints
            or not endpoint.allows_request(
                method=endpoint.method,
                url=url,
                body=body,
            )
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
