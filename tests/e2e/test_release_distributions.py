"""Clean-wheel release acceptance for the three MOX-ADV editions."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import zipfile
import os
import selectors
import sqlite3
from itertools import combinations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def _build_wheel(setup_path: Path, destination: Path) -> Path:
    egg_base = destination / "egg-info"
    egg_base.mkdir(parents=True)
    completed = subprocess.run(
        [
            sys.executable,
            str(setup_path),
            "egg_info",
            "--egg-base",
            str(egg_base),
            "build",
            "--build-base",
            str(destination / "build"),
            "bdist_wheel",
            "--dist-dir",
            str(destination / "dist"),
            "--bdist-dir",
            str(destination / "wheel"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    wheels = tuple((destination / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise AssertionError(f"Expected one wheel, found {wheels!r}.")
    return wheels[0]


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
            self.assertIn("mox_adv/paired_runtime.py", names)
            self.assertIn("mox_adv/ui/app.js", names)
            self.assertNotIn("mox_adv/modules/direct.py", names)
            self.assertNotIn("mox_adv/modules/metrika.py", names)
            self.assertNotIn("mox_adv/direct_analysis.py", names)
            self.assertNotIn("mox_adv/metrika_analysis.py", names)

    def test_clean_paired_install_starts_existing_dashboard_on_8878(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            for name in ("core", "direct", "metrika", "paired"):
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
                    "mox-adv-paired==1.0.0",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, installed.returncode, installed.stderr)
            process = subprocess.Popen(
                [
                    str(environment / "bin" / "mox-adv-paired"),
                    "ui",
                    "--port",
                    "8878",
                    "--runs-dir",
                    str(root / "runs"),
                    "--no-open",
                ],
                cwd=root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env={
                    name: value
                    for name, value in os.environ.items()
                    if name != "PYTHONPATH"
                },
                text=True,
            )
            try:
                deadline = time.monotonic() + 10
                page = ""
                last_error: Exception | None = None
                while time.monotonic() < deadline and not page:
                    if process.poll() is not None:
                        break
                    try:
                        with urllib.request.urlopen(
                            "http://127.0.0.1:8878/overview",
                            timeout=0.5,
                        ) as response:
                            page = response.read().decode("utf-8")
                    except Exception as error:
                        last_error = error
                        time.sleep(0.05)
                if not page:
                    assert process.stderr is not None
                    stderr = (
                        process.stderr.read()
                        if process.poll() is not None
                        else repr(last_error)
                    )
                    self.fail("paired Dashboard did not start: " + stderr)
                self.assertIn('lang="ru"', page)
                self.assertIn("MOX-ADV", page)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                if process.stderr is not None:
                    process.stderr.close()

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
