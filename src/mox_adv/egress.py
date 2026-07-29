"""Fail-closed HTTP method guard for the prototype trust boundary."""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlparse


class EgressDenied(PermissionError):
    """HTTP egress is outside the current process authority."""


class HttpEgressGuard:
    """Allow reads and deny non-read egress unless a pilot is explicitly armed."""

    _READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
    _READ_HOSTS = frozenset(
        {
            "api.direct.yandex.com",
            "api-metrika.yandex.net",
        }
    )

    def __init__(self, policy: Mapping[str, Any]) -> None:
        record = policy.get("record")
        self._production_write_authorized = bool(
            isinstance(record, Mapping)
            and record.get("production_write_authorized") is True
        )

    def authorize(
        self,
        method: str,
        url: str,
        *,
        operation: str = "",
        pilot_armed: bool = False,
    ) -> None:
        normalized_method = method.upper()
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in self._READ_HOSTS:
            raise EgressDenied("EXTERNAL_EGRESS_DENIED: host is not allowlisted.")
        if normalized_method in self._READ_METHODS:
            return
        if (
            normalized_method == "POST"
            and parsed.hostname == "api.direct.yandex.com"
            and operation in {"get", "reports"}
        ):
            return
        if not pilot_armed or not self._production_write_authorized:
            raise EgressDenied(
                "EXTERNAL_WRITE_EGRESS_DENIED: pilot process is not armed."
            )
