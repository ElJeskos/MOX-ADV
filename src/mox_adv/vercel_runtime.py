"""Vercel runtime composition for the public MOX-ADV demonstration."""

from __future__ import annotations

import json
import os
import shutil
import threading
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from mox_adv.control_state import AuthenticatedPrincipal
from mox_adv.ui_dashboard import DashboardApplication
from mox_adv.ui_service import UiRunService
from mox_adv.yandex_read import YandexProductionReader

PRODUCTION_READ_JSON_VARIABLE = "MOX_ADV_PRODUCTION_READ_JSON"
YANDEX_ENVIRONMENT_VARIABLES = (
    "YANDEX_DIRECT_OAUTH_TOKEN",
    "YANDEX_DIRECT_CLIENT_LOGIN",
    "YANDEX_METRICA_OAUTH_TOKEN",
    "YANDEX_METRICA_COUNTER_IDS",
)
MAX_RUNTIME_BINDING_BYTES = 64 * 1024
MAX_STATE_ARCHIVE_BYTES = 64 * 1024 * 1024
STATE_BLOB_PATH = "runtime/dashboard-state-v1.zip"


class VercelPublicDemoAuthenticator:
    """Represent the explicitly unauthenticated public demo operator."""

    @staticmethod
    def authenticate() -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            identity="sviridov",
            authentication="vercel_public_demo",
        )

    @classmethod
    def elevated_reauthenticate(cls) -> AuthenticatedPrincipal:
        return cls.authenticate()


@dataclass
class VercelDashboardRuntime:
    """Keep one warm-function Dashboard composition and opportunistic scheduler."""

    service: UiRunService
    dashboard: DashboardApplication
    _tick_lock: threading.Lock

    def tick(self) -> bool:
        if not self._tick_lock.acquire(blocking=False):
            return False
        try:
            return self.service.run_due_automation() is not None
        except (OSError, RuntimeError, TypeError, ValueError):
            return False
        finally:
            self._tick_lock.release()


class VercelStateStore:
    """Share the Dashboard's file-backed state between function instances."""

    def __init__(
        self,
        *,
        token: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.token = token or ""
        self.client = client
        if self.client is None and self.token:
            from vercel.blob import BlobClient

            self.client = BlobClient(token=self.token)

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> VercelStateStore:
        values = os.environ if environment is None else environment
        return cls(token=str(values.get("BLOB_READ_WRITE_TOKEN", "")).strip())

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def restore(self, scratch_root: Path) -> bool:
        """Replace the local runs directory with the latest private snapshot."""

        runs_root = Path(scratch_root) / "runs"
        if runs_root.exists():
            shutil.rmtree(runs_root)
        runs_root.mkdir(parents=True, exist_ok=True)
        if not self.enabled:
            return False
        try:
            result = self.client.get(
                STATE_BLOB_PATH,
                access="private",
                use_cache=False,
                token=self.token or None,
            )
        except Exception as error:
            if isinstance(error, FileNotFoundError) or (
                type(error).__name__ == "BlobNotFoundError"
            ):
                return False
            raise
        content = bytes(result)
        if len(content) > MAX_STATE_ARCHIVE_BYTES:
            raise RuntimeError("Vercel state archive exceeds the size limit.")
        _restore_runs_archive(content, runs_root)
        return True

    def persist(self, scratch_root: Path) -> None:
        """Upload one private snapshot after a state-changing request."""

        if not self.enabled:
            return
        content = _runs_archive(Path(scratch_root) / "runs")
        if len(content) > MAX_STATE_ARCHIVE_BYTES:
            raise RuntimeError("Vercel state archive exceeds the size limit.")
        self.client.put(
            STATE_BLOB_PATH,
            content,
            access="private",
            content_type="application/zip",
            overwrite=True,
            token=self.token or None,
        )


def build_vercel_runtime(
    *,
    environment: Mapping[str, str] | None = None,
    scratch_root: Path = Path("/tmp/mox-adv-vercel"),
    http_client: Any | None = None,
) -> VercelDashboardRuntime:
    """Build the Dashboard against Vercel's writable ephemeral directory."""

    values = os.environ if environment is None else environment
    runtime_root = Path(scratch_root)
    binding_root = runtime_root / "bindings"
    runs_root = runtime_root / "runs"
    binding_root.mkdir(parents=True, exist_ok=True)
    runs_root.mkdir(parents=True, exist_ok=True)

    environment_path = binding_root / ".env"
    configuration_path = binding_root / "production-read.json"
    _write_restricted_text(
        environment_path,
        _dotenv_content(values),
    )
    _write_restricted_text(
        configuration_path,
        _production_read_content(values),
    )

    production_reader = YandexProductionReader(
        configuration_path=configuration_path,
        environment_path=environment_path,
        http_client=http_client,
    )
    production_reader._credential_root = binding_root
    service = UiRunService(
        runs_root,
        production_reader=production_reader,
    )
    dashboard = DashboardApplication(
        runs_root,
        service,
        authenticator=VercelPublicDemoAuthenticator(),
    )
    return VercelDashboardRuntime(
        service=service,
        dashboard=dashboard,
        _tick_lock=threading.Lock(),
    )


def _dotenv_content(environment: Mapping[str, str]) -> str:
    lines: list[str] = []
    for name in YANDEX_ENVIRONMENT_VARIABLES:
        value = str(environment.get(name, ""))
        if "\n" in value or "\r" in value:
            raise RuntimeError(f"{name} contains an invalid line break.")
        lines.append(f"{name}={value}")
    content = "\n".join(lines) + "\n"
    if len(content.encode("utf-8")) > MAX_RUNTIME_BINDING_BYTES:
        raise RuntimeError("Yandex runtime bindings exceed the size limit.")
    return content


def _production_read_content(environment: Mapping[str, str]) -> str:
    raw = str(environment.get(PRODUCTION_READ_JSON_VARIABLE, "")).strip()
    if not raw:
        return "{}\n"
    if len(raw.encode("utf-8")) > MAX_RUNTIME_BINDING_BYTES:
        raise RuntimeError("Production-read configuration exceeds the size limit.")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"{PRODUCTION_READ_JSON_VARIABLE} must contain valid JSON."
        ) from error
    if not isinstance(value, dict):
        raise RuntimeError(
            f"{PRODUCTION_READ_JSON_VARIABLE} must contain a JSON object."
        )
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"


def _write_restricted_text(path: Path, content: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=True) as stream:
            descriptor = -1
            stream.write(content)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _runs_archive(runs_root: Path) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        if runs_root.exists():
            for path in sorted(runs_root.rglob("*")):
                if path.is_symlink() or not path.is_file():
                    continue
                archive.write(path, path.relative_to(runs_root).as_posix())
    return output.getvalue()


def _restore_runs_archive(content: bytes, runs_root: Path) -> None:
    with zipfile.ZipFile(BytesIO(content), mode="r") as archive:
        expanded_bytes = sum(item.file_size for item in archive.infolist())
        if expanded_bytes > MAX_STATE_ARCHIVE_BYTES:
            raise RuntimeError("Expanded Vercel state exceeds the size limit.")
        for item in archive.infolist():
            relative = Path(item.filename)
            if item.is_dir():
                continue
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError("Vercel state archive contains an unsafe path.")
            target = runs_root.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(item))
