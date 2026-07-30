"""Clean-wheel release acceptance for the three MOX-ADV editions."""

from __future__ import annotations

import fcntl
import os
import selectors
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path
from typing import Any
from unittest import mock

from playwright.sync_api import sync_playwright

from scripts import build_release_distributions
from tests.e2e.release_test_support import (
    RELEASE_DEPENDENCY_WHEELHOUSE_ENV,
    build_release_wheelhouse,
    copy_paired_dependency_wheels,
    create_virtual_environment,
    install_offline,
)
from tests.e2e.release_test_support import (
    build_wheel as _build_wheel,
)
from tests.e2e.test_paired_dashboard_regression import (
    EXISTING_ROUTES,
    PRE_MIGRATION_SCREENSHOT_DIGESTS,
    _stable_screenshot,
    _visual_digest,
)

ROOT = Path(__file__).resolve().parents[2]
EXACT_DASHBOARD_PORT = 8878


@contextmanager
def _exclusive_dashboard_port(
    port: int = EXACT_DASHBOARD_PORT,
) -> Iterator[None]:
    """Serialize exact-port acceptance and prove the port has no owner."""

    lock_path = (
        Path(tempfile.gettempdir()) / f"mox-adv-dashboard-{port}.lock"
    )
    descriptor = os.open(
        lock_path,
        os.O_CREAT
        | os.O_RDWR
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
                probe.listen(1)
            except OSError as error:
                raise AssertionError(
                    f"Dashboard port {port} is already owned by another process."
                ) from error
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _assert_child_running(process: subprocess.Popen[str]) -> None:
    return_code = process.poll()
    if return_code is not None:
        raise AssertionError(
            f"Installed paired Dashboard exited unexpectedly with {return_code}."
        )


def _wait_for_dashboard_ready(
    process: subprocess.Popen[str],
    *,
    timeout: float = 10,
) -> str:
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            _assert_child_running(process)
            if not selector.select(timeout=0.1):
                continue
            line = process.stdout.readline()
            if not line.startswith("MOX-ADV UI: "):
                continue
            url = line.removeprefix("MOX-ADV UI: ").strip()
            expected = f"http://127.0.0.1:{EXACT_DASHBOARD_PORT}"
            if url != expected:
                raise AssertionError(
                    f"Installed paired Dashboard announced {url}, not {expected}."
                )
            _assert_child_running(process)
            return url
    finally:
        selector.close()
    raise AssertionError("Installed paired Dashboard did not announce readiness.")


def _read_dashboard_overview(
    process: subprocess.Popen[str],
    origin: str,
    *,
    timeout: float = 10,
) -> str:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        _assert_child_running(process)
        try:
            with urllib.request.urlopen(
                origin + "/overview",
                timeout=0.5,
            ) as response:
                page = response.read().decode("utf-8")
            _assert_child_running(process)
            return page
        except (TimeoutError, urllib.error.URLError) as error:
            last_error = error
            time.sleep(0.05)
    raise AssertionError(
        "Installed paired Dashboard did not serve its overview: "
        + repr(last_error)
    )


def _terminate_and_capture(
    process: subprocess.Popen[str],
) -> tuple[str, str]:
    if process.poll() is None:
        process.terminate()
    try:
        return process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate(timeout=5)


@contextmanager
def _captured_dashboard_process(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> Iterator[subprocess.Popen[str]]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        text=True,
    )
    try:
        yield process
        _assert_child_running(process)
    except BaseException as error:
        stdout, stderr = _terminate_and_capture(process)
        raise AssertionError(
            f"{error}\n"
            f"Installed paired Dashboard stdout:\n{stdout}\n"
            f"Installed paired Dashboard stderr:\n{stderr}"
        ) from error
    else:
        _terminate_and_capture(process)


def _installed_paths(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as archive:
        return {
            name
            for name in archive.namelist()
            if ".dist-info/" not in name and not name.endswith("/")
        }


def _direct_request() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    period_end = now.date() - timedelta(days=1)
    period_start = period_end - timedelta(days=6)
    return {
        "schema_version": "module-request-v1",
        "connection_ref": {"connection_id": "customer-direct-primary"},
        "environment": "PRODUCTION",
        "scope": {
            "organization_id": "customer-42",
            "account_id": "account-8",
            "campaign_id": "campaign-7",
        },
        "period": {
            "start_date": period_start.isoformat(),
            "end_date": period_end.isoformat(),
            "timezone": "UTC",
        },
        "objective": {
            "code": "REDUCE_CPA",
            "description": "Reduce CPA without losing qualified conversions.",
        },
        "external_evidence": {
            "schema_version": "normalized-metrics-evidence-v1",
            "evidence_id": "release-direct-evidence-1",
            "source": "CUSTOMER_ECOSYSTEM",
            "observed_at": now.isoformat(),
            "watermark": (now - timedelta(minutes=5)).isoformat(),
            "metrics": [
                {"name": "impressions", "value": 10_000, "unit": "COUNT"},
                {"name": "clicks", "value": 200, "unit": "COUNT"},
                {
                    "name": "cost_micros",
                    "value": 4_000_000_000,
                    "unit": "MICROS_RUB",
                },
                {"name": "conversions", "value": 20, "unit": "COUNT"},
                {"name": "campaign_state", "value": "ON", "unit": "CODE"},
                {"name": "group_state", "value": "ON", "unit": "CODE"},
                {"name": "ad_state", "value": "ON", "unit": "CODE"},
                {
                    "name": "strategy",
                    "value": "HIGHEST_POSITION",
                    "unit": "CODE",
                },
                {
                    "name": "current_weekly_budget_micros",
                    "value": 2_000_000_000,
                    "unit": "MICROS_RUB",
                },
                {
                    "name": "current_search_bid_micros",
                    "value": 100_000_000,
                    "unit": "MICROS_RUB",
                },
                {"name": "ad_variant", "value": "A", "unit": "CODE"},
                {
                    "name": "object_config_version",
                    "value": "campaign-config-v1",
                    "unit": "CODE",
                },
                {
                    "name": "budget_period_start",
                    "value": (now - timedelta(days=6)).isoformat(),
                    "unit": "ISO_8601",
                },
                {
                    "name": "budget_period_end",
                    "value": (now + timedelta(days=1)).isoformat(),
                    "unit": "ISO_8601",
                },
            ],
        },
        "operation": {
            "kind": "ANALYZE",
            "operation_type": "ANALYZE_PERFORMANCE",
        },
        "idempotency_key": "release-direct-request-1",
    }


def _metrika_request() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    period_end = now.date() - timedelta(days=1)
    period_start = period_end - timedelta(days=6)
    return {
        "schema_version": "module-request-v1",
        "connection_ref": {"connection_id": "customer-metrika-primary"},
        "environment": "PRODUCTION",
        "scope": {
            "organization_id": "customer-42",
            "campaign_id": "campaign-7",
            "counter_id": "counter-9",
            "goal_id": "goal-3",
        },
        "period": {
            "start_date": period_start.isoformat(),
            "end_date": period_end.isoformat(),
            "timezone": "UTC",
        },
        "objective": {
            "code": "REDUCE_CPA",
            "description": "Reduce CPA without losing qualified conversions.",
        },
        "external_evidence": {
            "schema_version": "normalized-metrics-evidence-v1",
            "evidence_id": "release-metrika-evidence-1",
            "source": "CUSTOMER_ECOSYSTEM",
            "observed_at": now.isoformat(),
            "watermark": (now - timedelta(minutes=5)).isoformat(),
            "metrics": [
                {"name": "visits", "value": 140, "unit": "COUNT"},
                {"name": "goal_visits", "value": 7, "unit": "COUNT"},
            ],
        },
        "operation": {
            "kind": "ANALYZE",
            "operation_type": "ANALYZE_PERFORMANCE",
        },
        "idempotency_key": "release-metrika-request-1",
    }


class ReleaseDistributionTests(unittest.TestCase):
    def test_standalone_wheels_have_no_overlapping_installed_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            direct = _build_wheel(
                ROOT / "packaging" / "direct" / "setup.py",
                root / "direct",
            )
            metrika = _build_wheel(
                ROOT / "packaging" / "metrika" / "setup.py",
                root / "metrika",
            )

            overlap = sorted(_installed_paths(direct) & _installed_paths(metrika))

            self.assertEqual([], overlap)

    def test_every_release_wheel_has_disjoint_record_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheels = {
                name: _build_wheel(
                    ROOT / "packaging" / name / "setup.py",
                    root / name,
                )
                for name in ("core", "direct", "metrika", "paired")
            }

            for (left_name, left), (right_name, right) in combinations(
                wheels.items(),
                2,
            ):
                overlap = sorted(
                    _installed_paths(left) & _installed_paths(right)
                )
                self.assertEqual(
                    [],
                    overlap,
                    f"{left_name} and {right_name} both own files",
                )

    def test_repository_root_builds_the_official_paired_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paired = _build_wheel(
                ROOT / "packaging" / "paired" / "setup.py",
                root / "paired",
            )
            built = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    "--quiet",
                    "--no-deps",
                    "--no-build-isolation",
                    "--wheel-dir",
                    str(root / "root-dist"),
                    str(ROOT),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, built.returncode, built.stderr)
            root_wheels = tuple((root / "root-dist").glob("*.whl"))
            self.assertEqual(1, len(root_wheels))
            self.assertEqual(
                paired.name,
                root_wheels[0].name,
            )
            self.assertEqual(
                _installed_paths(paired),
                _installed_paths(root_wheels[0]),
            )

    def test_official_release_builder_isolates_stale_build_trees(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work_root = root / "work"
            poison = (
                work_root
                / "stale"
                / "build"
                / "lib"
                / "mox_adv"
                / "metrika_poison.py"
            )
            poison.parent.mkdir(parents=True)
            poison.write_text("raise AssertionError('stale build leaked')\n")
            output = root / "wheelhouse"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_release_distributions.py"),
                    "--version",
                    "1.0.0",
                    "--output-dir",
                    str(output),
                    "--work-root",
                    str(work_root),
                ],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            wheels = tuple(sorted(output.glob("*.whl")))
            self.assertEqual(4, len(wheels))
            self.assertTrue((output / "release-manifest.json").is_file())
            self.assertFalse(
                any(
                    "mox_adv/metrika_poison.py" in _installed_paths(wheel)
                    for wheel in wheels
                )
            )
            for left, right in combinations(wheels, 2):
                self.assertEqual(
                    set(),
                    _installed_paths(left) & _installed_paths(right),
                )

    def test_release_publish_never_replaces_concurrently_created_output(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "wheelhouse"
            staging.mkdir()
            (staging / "release-manifest.json").write_text(
                '{"release":"candidate"}\n',
                encoding="utf-8",
            )
            output.mkdir()

            with self.assertRaisesRegex(
                RuntimeError,
                "must not already exist",
            ):
                build_release_distributions._publish_release(
                    staging,
                    output,
                )

            self.assertEqual([], list(output.iterdir()))
            self.assertTrue((staging / "release-manifest.json").is_file())

    def test_dashboard_port_preflight_rejects_an_existing_owner(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as owner:
            owner.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            owner.bind(("127.0.0.1", 0))
            owner.listen(1)
            port = int(owner.getsockname()[1])

            with self.assertRaisesRegex(
                AssertionError,
                "already owned",
            ), _exclusive_dashboard_port(port):
                self.fail("The occupied port must not be yielded.")

    def test_dashboard_port_lock_serializes_across_processes(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        lock_path = (
            Path(tempfile.gettempdir()) / f"mox-adv-dashboard-{port}.lock"
        )
        contender = """
import fcntl
import os
import sys

descriptor = os.open(sys.argv[1], os.O_RDWR)
try:
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print("blocked")
    raise SystemExit(0)
raise SystemExit("lock unexpectedly acquired")
"""

        with _exclusive_dashboard_port(port):
            completed = subprocess.run(
                [sys.executable, "-c", contender, str(lock_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("blocked\n", completed.stdout)

    def test_dashboard_child_failure_captures_stderr_after_termination(
        self,
    ) -> None:
        child = (
            "import sys,time;"
            f"print('MOX-ADV UI: http://127.0.0.1:{EXACT_DASHBOARD_PORT}',"
            "flush=True);"
            "print('dashboard-stderr-marker',file=sys.stderr,flush=True);"
            "time.sleep(30)"
        )

        with self.assertRaisesRegex(
            AssertionError,
            "dashboard-stderr-marker",
        ), _captured_dashboard_process(
            [sys.executable, "-c", child],
            cwd=ROOT,
            environment=dict(os.environ),
        ) as process:
            _wait_for_dashboard_ready(process)
            raise AssertionError("forced acceptance failure")

    def test_clean_direct_install_starts_http_host_and_returns_module_result(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            _build_wheel(
                ROOT / "packaging" / "core" / "setup.py",
                root / "core",
            ).replace(wheelhouse / "mox_adv_core-1.0.0-py3-none-any.whl")
            _build_wheel(
                ROOT / "packaging" / "direct" / "setup.py",
                root / "direct",
            ).replace(wheelhouse / "mox_adv_direct-1.0.0-py3-none-any.whl")
            environment = root / "venv"
            created = subprocess.run(
                [sys.executable, "-m", "venv", str(environment)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, created.returncode, created.stderr)
            installed = subprocess.run(
                [
                    str(environment / "bin" / "python"),
                    "-m",
                    "pip",
                    "install",
                    "--quiet",
                    "--no-index",
                    "--find-links",
                    str(wheelhouse),
                    "mox-adv-direct==1.0.0",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, installed.returncode, installed.stderr)

            process = subprocess.Popen(
                [
                    str(environment / "bin" / "mox-adv-direct"),
                    "serve",
                    "--environment",
                    "PRODUCTION",
                    "--state-dir",
                    str(root / "state"),
                    "--port",
                    "0",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={
                    name: value
                    for name, value in os.environ.items()
                    if name != "PYTHONPATH"
                },
                text=True,
            )
            try:
                assert process.stdout is not None
                assert process.stderr is not None
                deadline = time.monotonic() + 10
                ready_line = ""
                selector = selectors.DefaultSelector()
                selector.register(process.stdout, selectors.EVENT_READ)
                while time.monotonic() < deadline and not ready_line:
                    if process.poll() is not None:
                        break
                    events = selector.select(timeout=0.1)
                    if events:
                        ready_line = process.stdout.readline()
                selector.close()
                if not ready_line:
                    process.terminate()
                    _, stderr = process.communicate(timeout=5)
                    self.fail("host did not become ready: " + stderr)
                ready = __import__("json").loads(ready_line)
                request = urllib.request.Request(
                    ready["url"] + "/v1/runs",
                    data=__import__("json").dumps(_direct_request()).encode(
                        "utf-8"
                    ),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    result = __import__("json").loads(response.read())
                self.assertEqual("module-result-v1", result["schema_version"])
                self.assertEqual("YANDEX_DIRECT", result["module"]["module_id"])
                self.assertIn(result["status"], {"SUCCEEDED", "PARTIAL"})
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                process.stdout.close()
                process.stderr.close()

    def test_clean_metrika_install_starts_http_host_and_returns_module_result(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            _build_wheel(
                ROOT / "packaging" / "core" / "setup.py",
                root / "core",
            ).replace(wheelhouse / "mox_adv_core-1.0.0-py3-none-any.whl")
            _build_wheel(
                ROOT / "packaging" / "metrika" / "setup.py",
                root / "metrika",
            ).replace(wheelhouse / "mox_adv_metrika-1.0.0-py3-none-any.whl")
            environment = root / "venv"
            subprocess.run(
                [sys.executable, "-m", "venv", str(environment)],
                check=True,
                capture_output=True,
                text=True,
            )
            installed = subprocess.run(
                [
                    str(environment / "bin" / "python"),
                    "-m",
                    "pip",
                    "install",
                    "--quiet",
                    "--no-index",
                    "--find-links",
                    str(wheelhouse),
                    "mox-adv-metrika==1.0.0",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, installed.returncode, installed.stderr)
            process = subprocess.Popen(
                [
                    str(environment / "bin" / "mox-adv-metrika"),
                    "serve",
                    "--environment",
                    "PRODUCTION",
                    "--state-dir",
                    str(root / "state"),
                    "--port",
                    "0",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={
                    name: value
                    for name, value in os.environ.items()
                    if name != "PYTHONPATH"
                },
                text=True,
            )
            try:
                assert process.stdout is not None
                assert process.stderr is not None
                selector = selectors.DefaultSelector()
                selector.register(process.stdout, selectors.EVENT_READ)
                events = selector.select(timeout=10)
                selector.close()
                if not events:
                    process.terminate()
                    _, stderr = process.communicate(timeout=5)
                    self.fail("host did not become ready: " + stderr)
                ready = __import__("json").loads(process.stdout.readline())
                request = urllib.request.Request(
                    ready["url"] + "/v1/runs",
                    data=__import__("json").dumps(_metrika_request()).encode(
                        "utf-8"
                    ),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    result = __import__("json").loads(response.read())
                self.assertEqual("module-result-v1", result["schema_version"])
                self.assertEqual("YANDEX_METRIKA", result["module"]["module_id"])
                self.assertIn(result["status"], {"SUCCEEDED", "PARTIAL"})
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                process.stdout.close()
                process.stderr.close()

    def test_paired_wheel_depends_on_exact_standalones_without_provider_code(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheel = _build_wheel(
                ROOT / "packaging" / "paired" / "setup.py",
                Path(temporary) / "paired",
            )
            with zipfile.ZipFile(wheel) as archive:
                names = set(archive.namelist())
                metadata_name = next(
                    name
                    for name in names
                    if name.endswith(".dist-info/METADATA")
                )
                metadata = archive.read(metadata_name).decode("utf-8")

            self.assertIn("Requires-Dist: mox-adv-direct (==1.0.0)", metadata)
            self.assertIn("Requires-Dist: mox-adv-metrika (==1.0.0)", metadata)
            self.assertIn(
                "Requires-Dist: playwright (==1.59.0)",
                metadata,
            )
            self.assertIn("mox_adv/paired_runtime.py", names)
            self.assertIn("mox_adv/ui/app.js", names)
            self.assertNotIn("mox_adv/modules/direct.py", names)
            self.assertNotIn("mox_adv/modules/metrika.py", names)
            self.assertNotIn("mox_adv/direct_analysis.py", names)
            self.assertNotIn("mox_adv/metrika_analysis.py", names)

    def test_installed_paired_mandate_cli_loads_packaged_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheelhouse, _wheels = build_release_wheelhouse(
                root,
                version="1.0.0",
                include_paired_dependencies=True,
            )
            environment = root / "venv"
            create_virtual_environment(environment)
            install_offline(
                environment,
                wheelhouse,
                "mox-adv-paired==1.0.0",
            )
            probe = """
import contextlib
import io
import tempfile
from pathlib import Path

from mox_adv.cli import main
from mox_adv.control_state import AuthenticatedPrincipal, DurableControlState


class FixedAuthenticator:
    def authenticate(self):
        return AuthenticatedPrincipal(
            identity="installed-release-test",
            authentication="authenticated_macos_user",
        )

    def elevated_reauthenticate(self):
        return self.authenticate()


with tempfile.TemporaryDirectory() as temporary:
    error = io.StringIO()
    with contextlib.redirect_stderr(error):
        status = main(
            ["mandate", "activate", "--mandate-id", "missing-mandate"],
            control_state=DurableControlState(Path(temporary) / "control.sqlite3"),
            authenticator=FixedAuthenticator(),
        )
    detail = error.getvalue()
    if status != 2 or "MANDATE_NOT_FOUND" not in detail:
        raise AssertionError(detail)
"""
            completed = subprocess.run(
                [str(environment / "bin" / "python"), "-c", probe],
                cwd=root,
                env={
                    name: value
                    for name, value in os.environ.items()
                    if name != "PYTHONPATH"
                },
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)

    def test_paired_dependency_wheelhouse_rejects_incomplete_or_extra_graph(
        self,
    ) -> None:
        configured = os.environ.get(RELEASE_DEPENDENCY_WHEELHOUSE_ENV)
        self.assertIsNotNone(configured)
        assert configured is not None
        source_wheels = tuple(sorted(Path(configured).glob("*.whl")))
        self.assertGreater(len(source_wheels), 1)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            incomplete = root / "incomplete"
            incomplete.mkdir()
            for wheel in source_wheels[:-1]:
                shutil.copy2(wheel, incomplete / wheel.name)
            with mock.patch.dict(
                os.environ,
                {RELEASE_DEPENDENCY_WHEELHOUSE_ENV: str(incomplete)},
            ), self.assertRaisesRegex(
                AssertionError,
                "exactly match requirements-release.txt",
            ):
                copy_paired_dependency_wheels(root / "incomplete-target")

            extra = root / "extra"
            extra.mkdir()
            for wheel in source_wheels:
                shutil.copy2(wheel, extra / wheel.name)
            shutil.copy2(source_wheels[0], extra / ("extra-" + source_wheels[0].name))
            with mock.patch.dict(
                os.environ,
                {RELEASE_DEPENDENCY_WHEELHOUSE_ENV: str(extra)},
            ), self.assertRaisesRegex(
                AssertionError,
                "exactly match requirements-release.txt",
            ):
                copy_paired_dependency_wheels(root / "extra-target")

    def test_clean_paired_install_starts_existing_dashboard_on_8878(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheelhouse, _wheels = build_release_wheelhouse(
                root,
                version="1.0.0",
                include_paired_dependencies=True,
            )
            environment = root / "venv"
            create_virtual_environment(environment)
            install_offline(
                environment,
                wheelhouse,
                "mox-adv-paired==1.0.0",
            )
            runtime_environment = {
                name: value
                for name, value in os.environ.items()
                if name != "PYTHONPATH"
            }
            runtime_environment["PYTHONUNBUFFERED"] = "1"
            with _exclusive_dashboard_port(), _captured_dashboard_process(
                [
                    str(environment / "bin" / "mox-adv-paired"),
                    "ui",
                    "--port",
                    str(EXACT_DASHBOARD_PORT),
                    "--runs-dir",
                    str(root / "runs"),
                    "--no-open",
                ],
                cwd=root,
                environment=runtime_environment,
            ) as process:
                origin = _wait_for_dashboard_ready(process)
                page = _read_dashboard_overview(process, origin)
                self.assertIn('lang="ru"', page)
                self.assertIn("MOX-ADV", page)
                page_errors: list[str] = []
                console_errors: list[str] = []
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    dashboard = browser.new_page(
                        viewport={"width": 1440, "height": 1000},
                        device_scale_factor=1,
                    )
                    dashboard.on(
                        "pageerror",
                        lambda error: page_errors.append(str(error)),
                    )
                    dashboard.on(
                        "console",
                        lambda message: (
                            console_errors.append(message.text)
                            if message.type == "error"
                            else None
                        ),
                    )
                    try:
                        for route in EXISTING_ROUTES:
                            _assert_child_running(process)
                            response = dashboard.goto(
                                origin + route,
                                wait_until="networkidle",
                            )
                            _assert_child_running(process)
                            if response is None:
                                self.fail(
                                    "Dashboard navigation returned no response."
                                )
                            self.assertTrue(response.ok)
                        _assert_child_running(process)
                        dashboard.goto(
                            origin + "/cycle",
                            wait_until="networkidle",
                        )
                        _assert_child_running(process)
                        visual_digests = {
                            "test_initial": _visual_digest(
                                _stable_screenshot(dashboard)
                            )
                        }
                        dashboard.get_by_role("tab", name="Основной").click()
                        dashboard.locator("#mode-name").get_by_text(
                            "Реальные данные",
                            exact=True,
                        ).wait_for()
                        _assert_child_running(process)
                        visual_digests["production_initial"] = _visual_digest(
                            _stable_screenshot(dashboard)
                        )
                        dashboard.get_by_role("tab", name="Тестовый").click()
                        dashboard.locator("#mode-name").get_by_text(
                            "Тестовые данные",
                            exact=True,
                        ).wait_for()
                        dashboard.get_by_role(
                            "button",
                            name="Получить предложение",
                        ).click()
                        dashboard.get_by_text(
                            "Предложение готово и ещё не применено",
                            exact=True,
                        ).wait_for()
                        _assert_child_running(process)
                        dashboard.locator("#report-run-id").evaluate(
                            "(element) => {"
                            " element.textContent = 'ui-reference-run';"
                            " }"
                        )
                        visual_digests["test_result"] = _visual_digest(
                            _stable_screenshot(dashboard)
                        )
                    finally:
                        browser.close()
                self.assertEqual([], page_errors)
                application_console_errors = [
                    message
                    for message in console_errors
                    if not (
                        message.startswith("Applying inline style violates")
                        and "style-src 'self'" in message
                    )
                ]
                self.assertEqual([], application_console_errors)
                self.assertEqual(
                    PRE_MIGRATION_SCREENSHOT_DIGESTS,
                    visual_digests,
                )
                _assert_child_running(process)

    def test_installed_host_replays_same_result_after_process_restart(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            for name in ("core", "metrika"):
                wheel = _build_wheel(
                    ROOT / "packaging" / name / "setup.py",
                    root / name,
                )
                wheel.replace(wheelhouse / wheel.name)
            environment = root / "venv"
            subprocess.run(
                [sys.executable, "-m", "venv", str(environment)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    str(environment / "bin" / "python"),
                    "-m",
                    "pip",
                    "install",
                    "--quiet",
                    "--no-index",
                    "--find-links",
                    str(wheelhouse),
                    "mox-adv-metrika==1.0.0",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            state = root / "state"
            responses = []
            payload = _metrika_request()
            for _ in range(2):
                process = subprocess.Popen(
                    [
                        str(environment / "bin" / "mox-adv-metrika"),
                        "serve",
                        "--environment",
                        "PRODUCTION",
                        "--state-dir",
                        str(state),
                        "--port",
                        "0",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env={
                        name: value
                        for name, value in os.environ.items()
                        if name != "PYTHONPATH"
                    },
                    text=True,
                )
                try:
                    assert process.stdout is not None
                    assert process.stderr is not None
                    selector = selectors.DefaultSelector()
                    selector.register(process.stdout, selectors.EVENT_READ)
                    events = selector.select(timeout=10)
                    selector.close()
                    if not events:
                        process.terminate()
                        _, stderr = process.communicate(timeout=5)
                        self.fail("host did not become ready: " + stderr)
                    ready = __import__("json").loads(process.stdout.readline())
                    request = urllib.request.Request(
                        ready["url"] + "/v1/runs",
                        data=__import__("json").dumps(payload).encode(
                            "utf-8"
                        ),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request, timeout=5) as response:
                        responses.append(
                            __import__("json").loads(response.read())
                        )
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=5)
                    process.stdout.close()
                    process.stderr.close()

            with sqlite3.connect(state / "analysis-replays.sqlite3") as database:
                rows = database.execute(
                    """
                    SELECT request_fingerprint, status_code, owner_token
                    FROM module_analysis_replays
                    """
                ).fetchall()
            self.assertEqual(responses[0], responses[1])
            self.assertEqual(1, len(rows))
            self.assertEqual(200, rows[0][1])
            self.assertIsNone(rows[0][2])


if __name__ == "__main__":
    unittest.main()
