"""Fail-closed HTTP egress guard backed by the Gate 0 API matrix."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse

from mox_adv.commands import ACTION_SPECS, OptimizationAction


class EgressDenied(PermissionError):
    """HTTP egress is outside the current process authority."""


@dataclass(frozen=True)
class ApprovedEndpoint:
    host: str
    path_template: str
    version: str
    service: str
    operation: str
    http_method: str

    def matches(
        self,
        host: str,
        path: str,
        version: str,
        service: str,
        operation: str,
        http_method: str,
    ) -> bool:
        escaped = re.escape(self.path_template)
        path_pattern = re.sub(r"\\\{[^{}]+\\\}", r"[^/]+", escaped)
        return (
            host == self.host
            and re.fullmatch(path_pattern, path) is not None
            and version == self.version
            and service == self.service
            and operation == self.operation
            and http_method == self.http_method
        )

    @property
    def is_read(self) -> bool:
        return self.operation.lower().startswith("get")


class HttpEgressGuard:
    """Authorize only an exact matrix entry and reject every redirect."""

    def __init__(self, policy: Mapping[str, Any]) -> None:
        record = policy.get("record")
        self._production_write_authorized = bool(
            isinstance(record, Mapping)
            and record.get("production_write_authorized") is True
        )
        self._endpoints = tuple(
            ApprovedEndpoint(
                host=str(item["host"]),
                path_template=str(item["path"]),
                version=str(item["version"]),
                service=str(item["service"]),
                operation=str(item["method"]),
                http_method=str(item["http_verb"]).upper(),
            )
            for item in policy["api_matrix"]
        )

    def authorize(
        self,
        http_method: str,
        url: str,
        *,
        version: str,
        service: str,
        operation: str,
        redirected: bool = False,
        pilot_armed: bool = False,
    ) -> None:
        if redirected:
            raise EgressDenied("EXTERNAL_EGRESS_DENIED: redirects are forbidden.")
        parsed = urlparse(url)
        try:
            port = parsed.port
        except ValueError as error:
            raise EgressDenied(
                "EXTERNAL_EGRESS_DENIED: URL port is invalid."
            ) from error
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise EgressDenied("EXTERNAL_EGRESS_DENIED: URL authority is invalid.")
        normalized_method = http_method.upper()
        endpoint = next(
            (
                item
                for item in self._endpoints
                if item.matches(
                    parsed.hostname,
                    parsed.path,
                    version,
                    service,
                    operation,
                    normalized_method,
                )
            ),
            None,
        )
        if endpoint is None:
            raise EgressDenied(
                "EXTERNAL_EGRESS_DENIED: endpoint is absent from the Gate 0 matrix."
            )
        if endpoint.is_read:
            return
        if not pilot_armed or not self._production_write_authorized:
            raise EgressDenied(
                "EXTERNAL_WRITE_EGRESS_DENIED: pilot process is not armed."
            )

    def enforce_adapter(self, adapter: Any, command: Any) -> None:
        """Bind every non-fake adapter to its exact approved matrix operation."""

        if getattr(adapter, "is_fake", False) is True:
            return
        try:
            spec = ACTION_SPECS[OptimizationAction(command.action)]
            self.authorize(
                adapter.http_method,
                adapter.url,
                version=adapter.version,
                service=spec.service,
                operation=spec.method,
                redirected=adapter.redirected,
                pilot_armed=adapter.pilot_armed,
            )
        except (AttributeError, KeyError, ValueError) as error:
            raise EgressDenied(
                "EXTERNAL_WRITE_EGRESS_DENIED: adapter is not guard-connected."
            ) from error
