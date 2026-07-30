"""Fail-closed HTTP egress guard backed by the Gate 0 API matrix."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from mox_adv.commands import ACTION_SPECS, OptimizationAction
from mox_adv.environment import (
    ExecutionEnvironment,
    EnvironmentWriteDenied,
    parse_execution_environment,
    require_test_write_environment,
)
from mox_adv.fake_write_adapter import FakeWriteAdapter


class EgressSystem(str, Enum):
    DIRECT = "DIRECT"
    DIRECT_REPORTS = "DIRECT_REPORTS"
    METRIKA = "METRIKA"
    METRIKA_BROWSER = "METRIKA_BROWSER"


class MatrixAccessClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    MANAGEMENT_READBACK = "MANAGEMENT_READBACK"
    INTEGRATION_WRITE_ONLY = "INTEGRATION_WRITE_ONLY"
    GOAL_READBACK = "GOAL_READBACK"
    GOAL_LIFECYCLE_WRITE = "GOAL_LIFECYCLE_WRITE"
    SITE_EVENT_WRITE = "SITE_EVENT_WRITE"


class CredentialAccess(str, Enum):
    DIRECT_REPORTS_READ_ONLY = "direct_reports_read_only"
    DIRECT_PILOT_WRITE = "one_allowlisted_account_write_disabled_by_default"
    METRIKA_TEST = "one_test_counter_read_write"
    METRIKA_PILOT = "one_pilot_counter_candidate_goal_write"
    TEST_SITE = "test_page_only"
    PILOT_SITE = "one_allowlisted_production_site_zone"


class CredentialProfile(str, Enum):
    DIRECT_PROD_READ = "DIRECT_PROD_READ"
    DIRECT_PILOT_WRITE = "DIRECT_PILOT_WRITE"
    METRIKA_TEST_WRITE = "METRIKA_TEST_WRITE"
    METRIKA_PILOT_WRITE = "METRIKA_PILOT_WRITE"
    TEST_SITE_PUBLISH = "TEST_SITE_PUBLISH"
    PILOT_SITE_PUBLISH = "PILOT_SITE_PUBLISH"


_CREDENTIAL_ACCESS_BY_MATRIX_CLASS = {
    (EgressSystem.DIRECT_REPORTS, MatrixAccessClass.READ_ONLY): frozenset(
        {CredentialAccess.DIRECT_REPORTS_READ_ONLY}
    ),
    (EgressSystem.DIRECT, MatrixAccessClass.MANAGEMENT_READBACK): frozenset(
        {CredentialAccess.DIRECT_PILOT_WRITE}
    ),
    (EgressSystem.DIRECT, MatrixAccessClass.INTEGRATION_WRITE_ONLY): frozenset(
        {CredentialAccess.DIRECT_PILOT_WRITE}
    ),
    (EgressSystem.METRIKA, MatrixAccessClass.READ_ONLY): frozenset(
        {CredentialAccess.METRIKA_TEST, CredentialAccess.METRIKA_PILOT}
    ),
    (EgressSystem.METRIKA, MatrixAccessClass.GOAL_READBACK): frozenset(
        {CredentialAccess.METRIKA_TEST, CredentialAccess.METRIKA_PILOT}
    ),
    (EgressSystem.METRIKA, MatrixAccessClass.GOAL_LIFECYCLE_WRITE): frozenset(
        {CredentialAccess.METRIKA_TEST, CredentialAccess.METRIKA_PILOT}
    ),
    (EgressSystem.METRIKA_BROWSER, MatrixAccessClass.SITE_EVENT_WRITE): frozenset(
        {CredentialAccess.TEST_SITE, CredentialAccess.PILOT_SITE}
    ),
}
_PROFILE_BINDING_FIELD = {
    CredentialProfile.DIRECT_PROD_READ: "direct_account",
    CredentialProfile.DIRECT_PILOT_WRITE: "direct_account",
    CredentialProfile.METRIKA_TEST_WRITE: "test_counter",
    CredentialProfile.METRIKA_PILOT_WRITE: "pilot_counter",
    CredentialProfile.TEST_SITE_PUBLISH: "test_site_zone",
    CredentialProfile.PILOT_SITE_PUBLISH: "pilot_site_zone",
}
_PROFILE_COUNTER_FIELD = {
    CredentialProfile.TEST_SITE_PUBLISH: "test_counter",
    CredentialProfile.PILOT_SITE_PUBLISH: "pilot_counter",
}


class EgressDenied(PermissionError):
    """HTTP egress is outside the current process authority."""


@dataclass(frozen=True)
class ApprovedEndpoint:
    system: EgressSystem
    host: str
    path_template: str
    version: str
    service: str
    operation: str
    http_method: str
    access_class: MatrixAccessClass

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


@dataclass(frozen=True)
class EgressAuthority:
    credential_profile: CredentialProfile
    trusted_target: str
    counter_id: str | None = None


class HttpEgressGuard:
    """Authorize only an exact matrix entry and reject every redirect."""

    def __init__(
        self,
        policy: Mapping[str, Any],
        *,
        environment: ExecutionEnvironment,
    ) -> None:
        self._environment = parse_execution_environment(environment)
        record = policy.get("record")
        self._production_write_authorized = bool(
            isinstance(record, Mapping)
            and record.get("production_write_authorized") is True
        )
        self._endpoints = tuple(
            ApprovedEndpoint(
                system=EgressSystem(str(item["system"])),
                host=str(item["host"]),
                path_template=str(item["path"]),
                version=str(item["version"]),
                service=str(item["service"]),
                operation=str(item["method"]),
                http_method=str(item["http_verb"]).upper(),
                access_class=MatrixAccessClass(str(item["access_class"])),
            )
            for item in policy["api_matrix"]
        )
        self._credential_access = {
            CredentialProfile(str(item["name"])): CredentialAccess(str(item["access"]))
            for item in policy["credentials"]["profiles"]
        }
        pilot_bindings = policy["bindings"]["pilot"]
        self._profile_bindings = {
            profile: pilot_bindings[_PROFILE_BINDING_FIELD[profile]]
            for profile in CredentialProfile
        }
        self._profile_counters = {
            profile: pilot_bindings[field]
            for profile, field in _PROFILE_COUNTER_FIELD.items()
        }

    def authorize(
        self,
        http_method: str,
        url: str,
        *,
        version: str,
        service: str,
        operation: str,
        authority: EgressAuthority,
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
        if not endpoint.is_read:
            try:
                require_test_write_environment(self._environment)
            except EnvironmentWriteDenied as error:
                raise EgressDenied(str(error)) from error
        if not self._credential_matches(endpoint, authority, parsed):
            raise EgressDenied(
                "EXTERNAL_EGRESS_DENIED: credential profile does not match endpoint."
            )
        if endpoint.is_read:
            return
        if not pilot_armed or not self._production_write_authorized:
            raise EgressDenied(
                "EXTERNAL_WRITE_EGRESS_DENIED: pilot process is not armed."
            )

    def _credential_matches(
        self,
        endpoint: ApprovedEndpoint,
        authority: EgressAuthority,
        parsed_url: Any,
    ) -> bool:
        access = self._credential_access.get(authority.credential_profile)
        allowed = _CREDENTIAL_ACCESS_BY_MATRIX_CLASS.get(
            (endpoint.system, endpoint.access_class),
            frozenset(),
        )
        expected_target = self._profile_bindings.get(authority.credential_profile)
        if (
            access not in allowed
            or not isinstance(expected_target, str)
            or not expected_target
            or authority.trusted_target != expected_target
        ):
            return False
        if endpoint.system == EgressSystem.METRIKA_BROWSER:
            expected_counter = self._profile_counters.get(authority.credential_profile)
            path_match = re.fullmatch(r"/watch/([^/]+)", parsed_url.path)
            return (
                isinstance(expected_counter, str)
                and bool(expected_counter)
                and authority.counter_id == expected_counter
                and path_match is not None
                and path_match.group(1) == expected_counter
            )
        if endpoint.system != EgressSystem.METRIKA:
            return True
        path_match = re.search(r"/counter/([^/]+)", parsed_url.path)
        if path_match is not None:
            return path_match.group(1) == authority.trusted_target
        query_ids = parse_qs(parsed_url.query).get("ids", [])
        return query_ids == [authority.trusted_target]

    def enforce_adapter(self, adapter: Any, command: Any) -> None:
        """Bind every non-fake adapter to its exact approved matrix operation."""

        if type(adapter) is FakeWriteAdapter:
            try:
                require_test_write_environment(self._environment)
            except EnvironmentWriteDenied as error:
                raise EgressDenied(str(error)) from error
            return
        try:
            spec = ACTION_SPECS[OptimizationAction(command.action)]
            if adapter.trusted_target != command.account:
                raise EgressDenied(
                    "EXTERNAL_WRITE_EGRESS_DENIED: command target is not bound."
                )
            self.authorize(
                adapter.http_method,
                adapter.url,
                version=adapter.version,
                service=spec.service,
                operation=spec.method,
                authority=EgressAuthority(
                    credential_profile=CredentialProfile(adapter.credential_profile),
                    trusted_target=adapter.trusted_target,
                    counter_id=getattr(adapter, "counter_id", None),
                ),
                redirected=adapter.redirected,
                pilot_armed=adapter.pilot_armed,
            )
        except (AttributeError, KeyError, ValueError) as error:
            raise EgressDenied(
                "EXTERNAL_WRITE_EGRESS_DENIED: adapter is not guard-connected."
            ) from error
