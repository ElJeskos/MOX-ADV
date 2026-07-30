"""Shared command-line lifecycle for the two headless provider editions."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.resources
import json
import os
import platform
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from mox_adv.environment import ExecutionEnvironment
from mox_adv.module_api.v1 import (
    DirectoryDecisionRecordStoreV1,
    HttpJsonModuleAdapterV1,
    ModuleDecisionRecordStoreV1,
    ModuleV1,
    inspect_analysis_replay_store_v1,
)
from mox_adv.module_host import build_module_server_v1

API_VERSION = "1.0.0"
LOOPBACK_BINDS = frozenset({"127.0.0.1", "localhost"})


@dataclass(frozen=True)
class StandaloneRuntimeSettingsV1:
    environment: ExecutionEnvironment
    state_dir: Path
    configuration_path: Path | None
    environment_path: Path | None
    test_resources_path: Path | None = None

    @property
    def provider_read_enabled(self) -> bool:
        return self.configuration_path is not None

    @property
    def test_adapter_enabled(self) -> bool:
        return self.test_resources_path is not None


ModuleBuilderV1 = Callable[
    [StandaloneRuntimeSettingsV1, ModuleDecisionRecordStoreV1],
    ModuleV1,
]
DiagnosticBuilderV1 = Callable[
    [StandaloneRuntimeSettingsV1],
    Mapping[str, Any],
]


class ProductionCompositionV1(Protocol):
    def settings_or_none(self) -> object | None: ...

    def credential_checks(self) -> tuple[dict[str, object], ...]: ...

    def module(
        self,
        *,
        clock: Callable[[], datetime],
        decision_records: ModuleDecisionRecordStoreV1 | None = None,
    ) -> ModuleV1: ...


@dataclass(frozen=True)
class ProviderEditionV1:
    program: str
    edition: str
    distribution: str
    analysis_builder: ModuleBuilderV1
    production_builder: Callable[[Path, Path], ProductionCompositionV1]
    test_builder: ModuleBuilderV1
    test_diagnostic_builder: DiagnosticBuilderV1


def provider_edition_main_v1(
    argv: Sequence[str] | None,
    edition: ProviderEditionV1,
) -> int:
    """Run one provider descriptor through the shared release lifecycle."""

    def production(
        settings: StandaloneRuntimeSettingsV1,
    ) -> ProductionCompositionV1:
        assert settings.configuration_path is not None
        assert settings.environment_path is not None
        return edition.production_builder(
            settings.configuration_path,
            settings.environment_path,
        )

    def module(
        settings: StandaloneRuntimeSettingsV1,
        decisions: ModuleDecisionRecordStoreV1,
    ) -> ModuleV1:
        if settings.test_resources_path is not None:
            return edition.test_builder(settings, decisions)
        if settings.configuration_path is None:
            return edition.analysis_builder(settings, decisions)
        return production(settings).module(
            clock=_utc_now,
            decision_records=decisions,
        )

    def diagnostics(
        settings: StandaloneRuntimeSettingsV1,
    ) -> Mapping[str, Any]:
        if settings.test_resources_path is not None:
            return edition.test_diagnostic_builder(settings)
        if settings.configuration_path is None:
            return {
                "mode": "CUSTOMER_EVIDENCE",
                "configuration_ready": True,
                "read_credentials": [],
            }
        composition = production(settings)
        return {
            "mode": "PROVIDER_READ",
            "configuration_ready": composition.settings_or_none() is not None,
            "read_credentials": list(composition.credential_checks()),
        }

    return standalone_main_v1(
        argv,
        program=edition.program,
        edition=edition.edition,
        distribution=edition.distribution,
        module_builder=module,
        diagnostic_builder=diagnostics,
    )


def standalone_main_v1(
    argv: Sequence[str] | None,
    *,
    program: str,
    edition: str,
    distribution: str,
    module_builder: ModuleBuilderV1,
    diagnostic_builder: DiagnosticBuilderV1,
) -> int:
    """Run one provider-specific CLI over the common release host."""

    parser = _parser(program)
    arguments = parser.parse_args(argv)
    settings = _settings(parser, arguments)
    if arguments.command == "diagnostics":
        diagnostics, _ = _diagnostics(
            edition=edition,
            distribution=distribution,
            settings=settings,
            provider=diagnostic_builder(settings),
        )
        print(json.dumps(diagnostics, ensure_ascii=True, sort_keys=True))
        return 0

    if arguments.bind not in LOOPBACK_BINDS:
        parser.error("standalone hosts bind only to an explicit loopback address")
    if not 0 <= arguments.port <= 65535:
        parser.error("port must be between 0 and 65535")
    prepare_state_directory_v1(settings.state_dir)
    decisions = DirectoryDecisionRecordStoreV1(
        settings.state_dir / "decision-records"
    )
    module = module_builder(settings, decisions)
    adapter = HttpJsonModuleAdapterV1.for_durable_host(
        module,
        environment=settings.environment,
        replay_path=settings.state_dir / "analysis-replays.sqlite3",
        decision_records=decisions,
    )
    diagnostics, openapi = _diagnostics(
        edition=edition,
        distribution=distribution,
        settings=settings,
        provider=diagnostic_builder(settings),
    )
    server = build_module_server_v1(
        bind=arguments.bind,
        port=arguments.port,
        adapter=adapter,
        diagnostics=diagnostics,
        openapi_document=openapi,
    )
    address = server.server_address
    url = "http://" + str(address[0]) + ":" + str(address[1])
    print(
        json.dumps(
            {
                "edition": edition,
                "event": "ready",
                "url": url,
            },
            ensure_ascii=True,
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def _parser(program: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=program)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("serve", "diagnostics"):
        child = subparsers.add_parser(command)
        child.add_argument(
            "--environment",
            required=True,
            choices=[item.value for item in ExecutionEnvironment],
        )
        child.add_argument("--state-dir", required=True, type=Path)
        child.add_argument("--configuration", type=Path)
        child.add_argument("--environment-file", type=Path)
        child.add_argument("--test-resources", type=Path)
        if command == "serve":
            child.add_argument("--bind", default="127.0.0.1")
            child.add_argument("--port", default=0, type=int)
    return parser


def _settings(
    parser: argparse.ArgumentParser,
    arguments: argparse.Namespace,
) -> StandaloneRuntimeSettingsV1:
    configuration = arguments.configuration
    environment_file = arguments.environment_file
    test_resources = arguments.test_resources
    if (configuration is None) != (environment_file is None):
        parser.error(
            "--configuration and --environment-file must be provided together"
        )
    environment = ExecutionEnvironment(arguments.environment)
    if configuration is not None and environment is not ExecutionEnvironment.PRODUCTION:
        parser.error("provider-owned reads are available only in PRODUCTION")
    if test_resources is not None and environment is not ExecutionEnvironment.TEST:
        parser.error("write-capable test resources are available only in TEST")
    if test_resources is not None and configuration is not None:
        parser.error("provider reads and test resources are mutually exclusive")
    return StandaloneRuntimeSettingsV1(
        environment=environment,
        state_dir=arguments.state_dir,
        configuration_path=configuration,
        environment_path=environment_file,
        test_resources_path=test_resources,
    )


def prepare_state_directory_v1(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        mode = path.stat().st_mode & 0o777
    except OSError as error:
        raise RuntimeError("The durable state directory is unavailable.") from error
    if mode & 0o077:
        raise RuntimeError(
            "The durable state directory must not be accessible by group or others."
        )


def _diagnostics(
    *,
    edition: str,
    distribution: str,
    settings: StandaloneRuntimeSettingsV1,
    provider: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    openapi_bytes = (
        importlib.resources.files("mox_adv")
        .joinpath("openapi/module-api-v1.openapi.json")
        .read_bytes()
    )
    openapi = json.loads(openapi_bytes)
    if not isinstance(openapi, dict):
        raise TypeError("The packaged OpenAPI document must be an object.")
    return (
        {
            "schema_version": "support-diagnostics-v1",
            "edition": edition,
            "distribution": distribution,
            "distribution_version": importlib.metadata.version(distribution),
            "core_version": importlib.metadata.version("mox-adv-core"),
            "api_version": API_VERSION,
            "python_supported": ">=3.9",
            "python_version": platform.python_version(),
            "openapi_sha256": hashlib.sha256(openapi_bytes).hexdigest(),
            "trusted_environment": settings.environment.value,
            "provider_read_enabled": settings.provider_read_enabled,
            "test_adapter_enabled": settings.test_adapter_enabled,
            "write_credentials": [],
            "production_write_policy": "BLOCKED_BEFORE_CREDENTIAL_AND_HTTP",
            "durable_state": _durable_state_diagnostics(settings.state_dir),
            "provider": dict(provider),
        },
        openapi,
    )


def _durable_state_diagnostics(state_dir: Path) -> dict[str, Any]:
    replay_path = state_dir / "analysis-replays.sqlite3"
    result: dict[str, Any] = {
        "schema_version": "analysis-replay-v1",
        "directory": os.fspath(state_dir),
        "replay_store": replay_path.name,
        "path_exists": state_dir.exists(),
        "status": "NOT_INITIALIZED",
        "integrity": "NOT_CHECKED",
    }
    if not state_dir.is_dir():
        return result
    try:
        mode = state_dir.stat().st_mode & 0o777
    except OSError:
        result.update(status="ERROR", integrity="ERROR")
        return result
    if mode & 0o077:
        result.update(status="ERROR", integrity="ERROR")
        return result
    if not replay_path.exists():
        result.update(status="READY", integrity="NOT_INITIALIZED")
        return result
    if not inspect_analysis_replay_store_v1(replay_path):
        result.update(status="ERROR", integrity="ERROR")
        return result
    result.update(status="READY", integrity="OK")
    return result


__all__ = [
    "ProviderEditionV1",
    "StandaloneRuntimeSettingsV1",
    "prepare_state_directory_v1",
    "provider_edition_main_v1",
    "standalone_main_v1",
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
