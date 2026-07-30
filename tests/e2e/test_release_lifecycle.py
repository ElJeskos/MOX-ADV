"""Clean-venv compatibility, upgrade, rollback, and uninstall acceptance."""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import stat
import subprocess
import sys
import tempfile
import unittest
import urllib.request
import zipfile
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from email.message import Message
from email.parser import BytesParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RELEASE_PACKAGES = ("core", "direct", "metrika", "paired")
BASE_VERSION = "1.0.0"
PATCH_VERSION = "1.0.1"


def _release_environment(**extra: str) -> dict[str, str]:
    environment = {
        name: value for name, value in os.environ.items() if name != "PYTHONPATH"
    }
    environment.update(extra)
    return environment


def _build_wheel(
    package: str,
    version: str,
    destination: Path,
) -> Path:
    build_root = destination / package / version
    (build_root / "egg-info").mkdir(parents=True)
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "packaging" / package / "setup.py"),
            "egg_info",
            "--egg-base",
            str(build_root / "egg-info"),
            "build",
            "--build-base",
            str(build_root / "build"),
            "bdist_wheel",
            "--dist-dir",
            str(destination),
            "--bdist-dir",
            str(build_root / "wheel"),
        ],
        cwd=ROOT,
        env=_release_environment(MOX_ADV_RELEASE_VERSION=version),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    matches = tuple(destination.glob(f"*{version}-py3-none-any.whl"))
    package_prefix = package.replace("-", "_")
    wheel = tuple(
        candidate
        for candidate in matches
        if candidate.name.startswith("mox_adv_" + package_prefix + "-")
    )
    if len(wheel) != 1:
        raise AssertionError(
            f"Expected one {package} {version} wheel, found {wheel!r}."
        )
    return wheel[0]


def _wheel_metadata(wheel: Path) -> Message:
    with zipfile.ZipFile(wheel) as archive:
        metadata_path = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        return BytesParser().parsebytes(archive.read(metadata_path))


def _create_venv(path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "venv", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)


def _install(
    environment: Path,
    wheelhouse: Path,
    requirement: str,
    *,
    force: bool = False,
) -> None:
    command = [
        str(environment / "bin" / "python"),
        "-m",
        "pip",
        "install",
        "--quiet",
        "--no-index",
        "--find-links",
        str(wheelhouse),
    ]
    if force:
        command.extend(("--upgrade", "--force-reinstall"))
    command.append(requirement)
    completed = subprocess.run(
        command,
        env=_release_environment(),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)


def _install_internal_release_set(
    environment: Path,
    wheelhouse: Path,
    version: str,
) -> None:
    requirements = [f"mox-adv-{package}=={version}" for package in RELEASE_PACKAGES]
    completed = subprocess.run(
        [
            str(environment / "bin" / "python"),
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-index",
            "--find-links",
            str(wheelhouse),
            "--no-deps",
            "--upgrade",
            "--force-reinstall",
            *requirements,
        ],
        env=_release_environment(),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)


def _uninstall(environment: Path, *distributions: str) -> None:
    completed = subprocess.run(
        [
            str(environment / "bin" / "python"),
            "-m",
            "pip",
            "uninstall",
            "--yes",
            *distributions,
        ],
        env=_release_environment(),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)


def _installed_release_versions(environment: Path) -> dict[str, str]:
    script = (
        "import importlib.metadata, json;"
        "names=('mox-adv-core','mox-adv-direct','mox-adv-metrika','mox-adv-paired');"
        "print(json.dumps({name: importlib.metadata.version(name) for name in names}))"
    )
    completed = subprocess.run(
        [str(environment / "bin" / "python"), "-c", script],
        env=_release_environment(),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    versions = json.loads(completed.stdout)
    if not isinstance(versions, dict):
        raise TypeError("Installed versions must be one JSON object.")
    return versions


def _diagnostics(
    environment: Path,
    program: str,
    state_dir: Path,
    *,
    secret_canary: str | None = None,
) -> dict[str, Any]:
    runtime_environment = _release_environment()
    if secret_canary is not None:
        runtime_environment.update(
            {
                "YANDEX_DIRECT_OAUTH_TOKEN": secret_canary,
                "YANDEX_DIRECT_CLIENT_LOGIN": secret_canary,
                "YANDEX_METRIKA_OAUTH_TOKEN": secret_canary,
            }
        )
    completed = subprocess.run(
        [
            str(environment / "bin" / program),
            "diagnostics",
            "--environment",
            "PRODUCTION",
            "--state-dir",
            str(state_dir),
        ],
        env=runtime_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    if secret_canary is not None:
        assert secret_canary not in completed.stdout
        assert secret_canary not in completed.stderr
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise TypeError("Diagnostics must be one JSON object.")
    return payload


def _metrika_request() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    period_end = now.date() - timedelta(days=1)
    return {
        "schema_version": "module-request-v1",
        "connection_ref": {"connection_id": "release-lifecycle-metrika"},
        "environment": "PRODUCTION",
        "scope": {
            "organization_id": "customer-42",
            "campaign_id": "campaign-7",
            "counter_id": "counter-9",
            "goal_id": "goal-3",
        },
        "period": {
            "start_date": (period_end - timedelta(days=6)).isoformat(),
            "end_date": period_end.isoformat(),
            "timezone": "UTC",
        },
        "objective": {
            "code": "REDUCE_CPA",
            "description": "Keep the release replay stable.",
        },
        "external_evidence": {
            "schema_version": "normalized-metrics-evidence-v1",
            "evidence_id": "release-lifecycle-evidence-1",
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
        "idempotency_key": "release-lifecycle-request-1",
    }


def _run_metrika_request(
    environment: Path,
    state_dir: Path,
    payload: Mapping[str, Any],
) -> tuple[bytes, dict[str, Any]]:
    process = subprocess.Popen(
        [
            str(environment / "bin" / "mox-adv-metrika"),
            "serve",
            "--environment",
            "PRODUCTION",
            "--state-dir",
            str(state_dir),
            "--port",
            "0",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_release_environment(),
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stderr is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        events = selector.select(timeout=15)
        selector.close()
        if not events:
            process.terminate()
            _, stderr = process.communicate(timeout=5)
            raise AssertionError("Metrika host did not become ready: " + stderr)
        ready_line = process.stdout.readline()
        if not ready_line:
            _, stderr = process.communicate(timeout=5)
            raise AssertionError("Metrika host stopped before readiness: " + stderr)
        ready = json.loads(ready_line)
        request = urllib.request.Request(
            ready["url"] + "/v1/runs",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            response_body = response.read()
            result = json.loads(response_body)
        if not isinstance(result, dict):
            raise TypeError("ModuleResult must be one JSON object.")
        return response_body, result
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


class ReleaseLifecycleTests(unittest.TestCase):
    wheelhouse_temporary: tempfile.TemporaryDirectory[str]
    wheelhouse: Path
    wheels: dict[tuple[str, str], Path]

    @classmethod
    def setUpClass(cls) -> None:
        cls.wheelhouse_temporary = tempfile.TemporaryDirectory()
        cls.wheelhouse = Path(cls.wheelhouse_temporary.name)
        cls.wheels = {}
        for package in RELEASE_PACKAGES:
            cls.wheels[(package, BASE_VERSION)] = _build_wheel(
                package,
                BASE_VERSION,
                cls.wheelhouse,
            )
        for package in RELEASE_PACKAGES:
            cls.wheels[(package, PATCH_VERSION)] = _build_wheel(
                package,
                PATCH_VERSION,
                cls.wheelhouse,
            )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.wheelhouse_temporary.cleanup()

    def test_release_metadata_and_diagnostics_publish_compatibility(self) -> None:
        direct = _wheel_metadata(self.wheels[("direct", BASE_VERSION)])
        metrika = _wheel_metadata(self.wheels[("metrika", BASE_VERSION)])
        paired = _wheel_metadata(self.wheels[("paired", BASE_VERSION)])
        with zipfile.ZipFile(self.wheels[("core", BASE_VERSION)]) as archive:
            openapi_bytes = archive.read("mox_adv/openapi/module-api-v1.openapi.json")
        openapi = json.loads(openapi_bytes)

        self.assertEqual(">=3.9", direct["Requires-Python"])
        self.assertEqual(">=3.9", metrika["Requires-Python"])
        self.assertEqual(">=3.9", paired["Requires-Python"])
        self.assertGreaterEqual(sys.version_info, (3, 9))
        self.assertEqual("1.0.0", openapi["info"]["version"])
        self.assertIn(
            "mox-adv-core (==1.0.0)",
            direct.get_all("Requires-Dist", []),
        )
        self.assertIn(
            "mox-adv-core (==1.0.0)",
            metrika.get_all("Requires-Dist", []),
        )
        paired_requirements = set(paired.get_all("Requires-Dist", []))
        self.assertTrue(
            {
                "mox-adv-direct (==1.0.0)",
                "mox-adv-metrika (==1.0.0)",
            }.issubset(paired_requirements),
        )
        self.assertIn("playwright (<2,>=1.48)", paired_requirements)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = root / "venv"
            state = root / "external-state"
            state.mkdir(mode=0o700)
            _create_venv(environment)
            _install(
                environment,
                self.wheelhouse,
                "mox-adv-metrika==1.0.0",
            )

            diagnostics = _diagnostics(
                environment,
                "mox-adv-metrika",
                state,
                secret_canary="release-diagnostics-secret-canary",
            )

        self.assertEqual("support-diagnostics-v1", diagnostics["schema_version"])
        self.assertEqual("1.0.0", diagnostics["distribution_version"])
        self.assertEqual("1.0.0", diagnostics["core_version"])
        self.assertEqual("1.0.0", diagnostics["api_version"])
        self.assertEqual(
            hashlib.sha256(openapi_bytes).hexdigest(),
            diagnostics["openapi_sha256"],
        )
        self.assertEqual(">=3.9", diagnostics["python_supported"])
        self.assertRegex(diagnostics["python_version"], r"^[0-9]+\.[0-9]+\.[0-9]+$")
        self.assertEqual([], diagnostics["write_credentials"])
        self.assertEqual(
            "BLOCKED_BEFORE_CREDENTIAL_AND_HTTP",
            diagnostics["production_write_policy"],
        )
        self.assertEqual(
            "analysis-replay-v1",
            diagnostics["durable_state"]["schema_version"],
        )
        self.assertEqual("READY", diagnostics["durable_state"]["status"])
        self.assertEqual(
            "NOT_INITIALIZED",
            diagnostics["durable_state"]["integrity"],
        )

    def test_patch_upgrade_and_rollback_replay_the_same_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = root / "venv"
            external = root / "customer-owned"
            state = external / "state ? #"
            configuration = external / "configuration.json"
            state.mkdir(parents=True, mode=0o700)
            configuration.write_text(
                '{"owner":"customer","version":1}\n',
                encoding="utf-8",
            )
            configuration.chmod(stat.S_IRUSR | stat.S_IWUSR)
            state_canary = state / "customer-owned.txt"
            state_canary.write_text("preserve-me\n", encoding="utf-8")
            request = _metrika_request()
            _create_venv(environment)

            _install(
                environment,
                self.wheelhouse,
                "mox-adv-metrika==1.0.0",
            )
            original_body, original = _run_metrika_request(
                environment,
                state,
                request,
            )
            self.assertEqual("module-result-v1", original["schema_version"])
            self.assertTrue((state / "analysis-replays.sqlite3").is_file())
            initialized_diagnostics = _diagnostics(
                environment,
                "mox-adv-metrika",
                state,
            )
            self.assertEqual(
                "OK",
                initialized_diagnostics["durable_state"]["integrity"],
            )

            _install(
                environment,
                self.wheelhouse,
                "mox-adv-metrika==1.0.1",
                force=True,
            )
            upgraded_diagnostics = _diagnostics(
                environment,
                "mox-adv-metrika",
                state,
            )
            upgraded_body, upgraded = _run_metrika_request(
                environment,
                state,
                request,
            )
            self.assertEqual("1.0.1", upgraded_diagnostics["distribution_version"])
            self.assertEqual("1.0.1", upgraded_diagnostics["core_version"])
            self.assertEqual("1.0.0", upgraded_diagnostics["api_version"])
            self.assertEqual(
                "analysis-replay-v1",
                upgraded_diagnostics["durable_state"]["schema_version"],
            )
            self.assertEqual(original, upgraded)
            self.assertEqual(original_body, upgraded_body)

            _install(
                environment,
                self.wheelhouse,
                "mox-adv-metrika==1.0.0",
                force=True,
            )
            rolled_back_diagnostics = _diagnostics(
                environment,
                "mox-adv-metrika",
                state,
            )
            rolled_back_body, rolled_back = _run_metrika_request(
                environment,
                state,
                request,
            )
            self.assertEqual(
                "1.0.0",
                rolled_back_diagnostics["distribution_version"],
            )
            self.assertEqual("1.0.0", rolled_back_diagnostics["core_version"])
            self.assertEqual(original, rolled_back)
            self.assertEqual(original_body, rolled_back_body)
            self.assertEqual(
                '{"owner":"customer","version":1}\n',
                configuration.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "preserve-me\n",
                state_canary.read_text(encoding="utf-8"),
            )

    def test_paired_patch_upgrade_and_rollback_keep_one_exact_release_set(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = root / "venv"
            external_runs = root / "customer-owned" / "paired-runs"
            external_runs.mkdir(parents=True)
            state_canary = external_runs / "customer-owned.txt"
            state_canary.write_text("preserve-me\n", encoding="utf-8")
            _create_venv(environment)

            _install_internal_release_set(
                environment,
                self.wheelhouse,
                "1.0.0",
            )
            self.assertEqual(
                {
                    "mox-adv-core": "1.0.0",
                    "mox-adv-direct": "1.0.0",
                    "mox-adv-metrika": "1.0.0",
                    "mox-adv-paired": "1.0.0",
                },
                _installed_release_versions(environment),
            )

            _install_internal_release_set(
                environment,
                self.wheelhouse,
                "1.0.1",
            )
            self.assertEqual(
                {
                    "mox-adv-core": "1.0.1",
                    "mox-adv-direct": "1.0.1",
                    "mox-adv-metrika": "1.0.1",
                    "mox-adv-paired": "1.0.1",
                },
                _installed_release_versions(environment),
            )

            _install_internal_release_set(
                environment,
                self.wheelhouse,
                "1.0.0",
            )
            self.assertEqual(
                {
                    "mox-adv-core": "1.0.0",
                    "mox-adv-direct": "1.0.0",
                    "mox-adv-metrika": "1.0.0",
                    "mox-adv-paired": "1.0.0",
                },
                _installed_release_versions(environment),
            )
            self.assertEqual(
                "preserve-me\n",
                state_canary.read_text(encoding="utf-8"),
            )

    def test_uninstall_isolated_editions_preserves_other_modules_and_data(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = root / "venv"
            external = root / "customer-owned"
            state = external / "state"
            configuration = external / "configuration.json"
            state.mkdir(parents=True, mode=0o700)
            configuration.write_text("customer-owned\n", encoding="utf-8")
            state_canary = state / "customer-owned.txt"
            state_canary.write_text("preserve-me\n", encoding="utf-8")
            _create_venv(environment)
            _install_internal_release_set(
                environment,
                self.wheelhouse,
                "1.0.0",
            )

            _uninstall(environment, "mox-adv-paired")
            self.assertFalse((environment / "bin" / "mox-adv-paired").exists())
            direct = _diagnostics(
                environment,
                "mox-adv-direct",
                state,
            )
            metrika = _diagnostics(
                environment,
                "mox-adv-metrika",
                state,
            )
            self.assertEqual("mox-adv-direct", direct["distribution"])
            self.assertEqual("mox-adv-metrika", metrika["distribution"])

            _uninstall(environment, "mox-adv-direct")
            self.assertFalse((environment / "bin" / "mox-adv-direct").exists())
            metrika_after_direct = _diagnostics(
                environment,
                "mox-adv-metrika",
                state,
            )
            self.assertEqual(
                "mox-adv-metrika",
                metrika_after_direct["distribution"],
            )

            _uninstall(environment, "mox-adv-metrika", "mox-adv-core")
            self.assertEqual(
                "customer-owned\n",
                configuration.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "preserve-me\n",
                state_canary.read_text(encoding="utf-8"),
            )
            self.assertFalse((environment / "bin" / "mox-adv-metrika").exists())


if __name__ == "__main__":
    unittest.main()
