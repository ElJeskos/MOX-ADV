"""Installed-wheel proof that production provider editions cannot write."""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tests.e2e.release_test_support import (
    build_release_wheelhouse,
    create_virtual_environment,
    install_offline,
)

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_WRITE_FORBIDDEN = "PRODUCTION_WRITE_FORBIDDEN"
WRITE_CASES = (
    ("direct", "APPLY_OPTIMIZATION"),
    ("direct", "CREATE_CAMPAIGN"),
    ("metrika", "MANAGE_GOAL_CANDIDATE"),
)
SENSITIVE_ENVIRONMENT_MARKERS = (
    "CREDENTIAL",
    "OAUTH",
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "WRITE",
)


def _install_standalone(
    *,
    root: Path,
    wheelhouse: Path,
    edition: str,
) -> Path:
    environment = root / (edition + "-venv")
    create_virtual_environment(environment)
    install_offline(
        environment,
        wheelhouse,
        "mox-adv-" + edition + "==1.0.0",
    )
    return environment


def _install_paired(
    *,
    root: Path,
    wheelhouse: Path,
) -> Path:
    environment = root / "paired-venv"
    create_virtual_environment(environment)
    install_offline(environment, wheelhouse, "mox-adv-paired==1.0.0")
    return environment


def _write_poison_sitecustomize(root: Path) -> Path:
    support = root / "poison-support"
    support.mkdir()
    (support / "sitecustomize.py").write_text(
        """import os
from pathlib import Path
from mox_adv import yandex_credentials, yandex_transport

loaded = Path(os.environ["MOX_ADV_TRAP_LOADED"])
loaded.write_text("loaded\\n", encoding="utf-8")


def trip(kind):
    target = Path(os.environ["MOX_ADV_TRAP_CALLED"])
    with target.open("a", encoding="utf-8") as stream:
        stream.write(kind + "\\n")
    raise AssertionError("release safety trap called: " + kind)


def resolve(self):
    del self
    return trip("credential-resolution")


def perform(self, **kwargs):
    del self, kwargs
    return trip("http-egress")


yandex_credentials.DotenvValue.resolve = resolve
yandex_transport.UrllibHttpClient.perform = perform
""",
        encoding="utf-8",
    )
    return support


def _sanitized_process_environment(
    *,
    poison_support: Path,
    loaded_trap: Path,
    called_trap: Path,
) -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if name != "PYTHONPATH"
        and not any(marker in name.upper() for marker in SENSITIVE_ENVIRONMENT_MARKERS)
    }
    environment.update(
        {
            "PYTHONPATH": os.fspath(poison_support),
            "MOX_ADV_TRAP_LOADED": os.fspath(loaded_trap),
            "MOX_ADV_TRAP_CALLED": os.fspath(called_trap),
        }
    )
    return environment


def _provider_configuration(root: Path, edition: str) -> tuple[Path, Path, tuple[str, ...]]:
    configuration = root / (edition + "-production-read.json")
    environment = root / ("." + edition + "-read")
    secrets: tuple[str, ...]
    if edition == "direct":
        configuration.write_text(
            json.dumps(
                {
                    "connection_id": "customer-direct",
                    "account_id": "account-8",
                    "campaign_id": "campaign-7",
                    "trusted_change_author": "release-safety",
                }
            ),
            encoding="utf-8",
        )
        secrets = (
            "direct-read-token-release-safety-canary",
            "direct-client-login-release-safety-canary",
        )
        environment.write_text(
            "YANDEX_DIRECT_OAUTH_TOKEN="
            + secrets[0]
            + "\nYANDEX_DIRECT_CLIENT_LOGIN="
            + secrets[1]
            + "\n",
            encoding="utf-8",
        )
    elif edition == "metrika":
        configuration.write_text(
            json.dumps(
                {
                    "connection_id": "customer-metrika",
                    "counter_id": "counter-9",
                    "goal_id": "goal-3",
                    "campaign_id": "campaign-7",
                }
            ),
            encoding="utf-8",
        )
        secrets = ("metrika-read-token-release-safety-canary",)
        environment.write_text(
            "YANDEX_METRIKA_OAUTH_TOKEN=" + secrets[0] + "\n",
            encoding="utf-8",
        )
    else:
        raise AssertionError("Unknown provider edition.")
    environment.chmod(0o600)
    return configuration, environment, secrets


def _wait_until_ready(
    process: subprocess.Popen[str],
    *,
    timeout: float = 10,
) -> str:
    assert process.stdout is not None
    assert process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            if selector.select(timeout=0.1):
                line = process.stdout.readline()
                if line:
                    ready = json.loads(line)
                    return str(ready["url"])
    finally:
        selector.close()
    if process.poll() is None:
        process.terminate()
    _, stderr = process.communicate(timeout=5)
    raise AssertionError("Installed host did not become ready: " + stderr)


@contextmanager
def _installed_production_host(
    *,
    root: Path,
    environment: Path,
    edition: str,
    poison_support: Path,
) -> Iterator[tuple[str, Path, Path, tuple[str, ...]]]:
    configuration, environment_file, secret_canaries = _provider_configuration(
        root,
        edition,
    )
    loaded_trap = root / (edition + "-sitecustomize-loaded")
    called_trap = root / (edition + "-poison-called")
    process = subprocess.Popen(
        [
            str(environment / "bin" / ("mox-adv-" + edition)),
            "serve",
            "--environment",
            "PRODUCTION",
            "--state-dir",
            str(root / (edition + "-state")),
            "--configuration",
            str(configuration),
            "--environment-file",
            str(environment_file),
            "--port",
            "0",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_sanitized_process_environment(
            poison_support=poison_support,
            loaded_trap=loaded_trap,
            called_trap=called_trap,
        ),
        text=True,
    )
    try:
        url = _wait_until_ready(process)
        yield url, loaded_trap, called_trap, secret_canaries
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        assert process.stdout is not None
        assert process.stderr is not None
        process.stdout.close()
        process.stderr.close()


def _get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=5) as response:
        payload = json.loads(response.read())
    if not isinstance(payload, dict):
        raise TypeError("Expected one JSON object.")
    return payload


def _post_json(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        response = urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())
    with response:
        return response.status, json.loads(response.read())


def _probe_installed_paired_production_guard(
    *,
    root: Path,
    environment: Path,
    poison_support: Path,
) -> dict[str, Any]:
    loaded_trap = root / "paired-sitecustomize-loaded"
    called_trap = root / "paired-poison-called"
    script = r"""
import json
import os
import sys
from pathlib import Path

from mox_adv.campaign_lifecycle import CampaignDraftSafetyBindings
from mox_adv.environment import PRODUCTION_WRITE_FORBIDDEN
from mox_adv.ui_dashboard import DashboardApplication
from mox_adv.ui_service import UiRunService
from mox_adv.ui_workflows import DashboardWorkflowFacade, DashboardWorkflowRejected

runs_root = Path(sys.argv[1])
safety = CampaignDraftSafetyBindings(
    allowed_landing_hosts=("allowlisted.example",),
    prohibited_phrases=("guaranteed results",),
    prepared_media_references=("prepared-media-1", "prepared-media-2"),
)
service = UiRunService(runs_root)
dashboard = DashboardApplication(runs_root, service)
blocked = []


def require_blocked(name, invoke):
    try:
        invoke()
    except DashboardWorkflowRejected as error:
        if str(error) != PRODUCTION_WRITE_FORBIDDEN:
            raise
        blocked.append(name)
        return
    raise AssertionError(name + " did not reject production write")


require_blocked(
    "constructor_capability_injection",
    lambda: DashboardWorkflowFacade(
        runs_root=runs_root,
        policy_path=dashboard.workflows.policy_path,
        campaign_safety=safety,
        production_campaign_executor=object(),
    ),
)
require_blocked(
    "preview_campaign",
    lambda: dashboard.workflows.preview_campaign(
        run_id="paired-release-campaign-preview",
        proposal_id="paired-release-campaign-proposal",
        draft_payload={},
        execution_mode="PRODUCTION",
    ),
)
require_blocked(
    "run_campaign",
    lambda: dashboard.workflows.run_campaign(
        run_id="paired-release-campaign-run",
        proposal_id="paired-release-campaign-proposal",
        draft_payload={},
        execution_mode="PRODUCTION",
        requested_at="2026-07-30T00:00:00+00:00",
    ),
)
require_blocked(
    "preview_goal",
    lambda: dashboard.workflows.preview_goal(
        run_id="paired-release-goal-preview",
        proposal_id="paired-release-goal-proposal",
        candidate_payload={},
        expected_site_version="test-page-v1",
        execution_mode="PRODUCTION",
    ),
)
require_blocked(
    "run_goal",
    lambda: dashboard.workflows.run_goal(
        run_id="paired-release-goal-run",
        proposal_id="paired-release-goal-proposal",
        candidate_payload={},
        expected_site_version="test-page-v1",
        execution_mode="PRODUCTION",
        requested_at="2026-07-30T00:00:00+00:00",
        semantic_decision="APPROVE",
        reviewer="release-security-reviewer",
    ),
)
status = service.status()["production_mode"]
print(
    json.dumps(
        {
            "blocked_paths": sorted(blocked),
            "dashboard_status": status,
            "write_credentials": sorted(
                name for name in os.environ if "WRITE" in name.upper()
            ),
        },
        sort_keys=True,
    )
)
"""
    completed = subprocess.run(
        [
            str(environment / "bin" / "python"),
            "-c",
            script,
            str(root / "paired-runs"),
        ],
        env=_sanitized_process_environment(
            poison_support=poison_support,
            loaded_trap=loaded_trap,
            called_trap=called_trap,
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    evidence = json.loads(completed.stdout)
    if not isinstance(evidence, dict):
        raise TypeError("Paired production guard evidence must be an object.")
    evidence["poison_loaded"] = loaded_trap.is_file()
    evidence["poison_called"] = called_trap.exists()
    return evidence


def _base_execute_request(edition: str, operation_type: str) -> dict[str, Any]:
    connection = "customer-" + edition
    scope: dict[str, str] = {
        "organization_id": "customer-42",
        "account_id": "account-8",
        "campaign_id": "campaign-7",
    }
    if edition == "metrika":
        scope = {
            "organization_id": "customer-42",
            "counter_id": "counter-9",
            "goal_id": "goal-3",
        }
    return {
        "schema_version": "module-request-v1",
        "connection_ref": {"connection_id": connection},
        "environment": "PRODUCTION",
        "scope": scope,
        "period": {
            "start_date": "2026-07-01",
            "end_date": "2026-07-29",
            "timezone": "Europe/Moscow",
        },
        "objective": {
            "code": "SAFE_CHANGE",
            "description": "Prove the installed production guard.",
        },
        "external_evidence": {
            "schema_version": "normalized-metrics-evidence-v1",
            "evidence_id": "release-safety-evidence",
            "source": "CUSTOMER_ECOSYSTEM",
            "observed_at": "2026-07-30T09:00:00+00:00",
            "watermark": "2026-07-30T08:55:00+00:00",
            "metrics": [
                {
                    "name": "conversions",
                    "value": 21,
                    "unit": "COUNT",
                }
            ],
        },
        "operation": {
            "kind": "EXECUTE",
            "operation_type": operation_type,
        },
        "idempotency_key": "release-safety-" + operation_type.lower(),
    }


def _execute_request(edition: str, operation_type: str) -> dict[str, Any]:
    payload = _base_execute_request(edition, operation_type)
    if operation_type == "APPLY_OPTIMIZATION":
        payload["direct_action_command"] = {
            "schema_version": "direct-action-command-v1",
            "command": "EXECUTE_PROPOSAL",
            "proposal_id": "release-safety-proposal",
        }
    elif operation_type == "CREATE_CAMPAIGN":
        payload.pop("external_evidence")
        payload["scope"] = {
            "organization_id": "customer-42",
            "account_id": "account-8",
        }
        payload["campaign_creation_command"] = {
            "schema_version": "campaign-creation-command-v1",
            "command": "CREATE_CAMPAIGN",
            "run_id": "release-safety-run",
            "execution_key": payload["idempotency_key"],
            "proposal_id": "release-safety-proposal",
            "approval_id": "release-safety-approval",
            "reservation_id": "release-safety-reservation",
            "draft": {
                "schema_version": "campaign-draft-v1",
                "draft_id": "release-safety-draft",
                "business_goal": {
                    "event": "lead_submitted",
                    "meaning": "A visitor submitted the lead form.",
                },
                "primary_conversion": {"event": "lead_submitted"},
                "campaign_type": "UNIFIED_CAMPAIGN",
                "strategy": {
                    "placement": "SEARCH",
                    "search": "HIGHEST_POSITION",
                    "network": "SERVING_OFF",
                },
                "geography": ["RU"],
                "schedule": {
                    "timezone": "Europe/Moscow",
                    "days": ["MONDAY"],
                    "start": "09:00",
                    "end": "18:00",
                },
                "budget": {
                    "currency": "RUB",
                    "weekly_micros": 500_000_000,
                },
                "limits": {
                    "maximum_weekly_micros": 500_000_000,
                    "maximum_bid_micros": 100_000_000,
                },
                "groups": [
                    {
                        "name": "Lead service",
                        "keywords": ["lead service"],
                        "negative_keywords": ["free"],
                        "audiences": [],
                        "ads": [
                            {
                                "variant_id": "A",
                                "title": "Lead service",
                                "text": "Submit a request",
                                "landing_page": (
                                    "https://allowlisted.example/lead"
                                ),
                                "utm": "utm_source=yandex&utm_content=a",
                                "media_reference": "prepared-media-1",
                            },
                            {
                                "variant_id": "B",
                                "title": "Lead service alternative",
                                "text": "Request a consultation",
                                "landing_page": (
                                    "https://allowlisted.example/lead"
                                ),
                                "utm": "utm_source=yandex&utm_content=b",
                                "media_reference": "prepared-media-2",
                            },
                        ],
                    }
                ],
                "landing_page": "https://allowlisted.example/lead",
                "media_references": [
                    "prepared-media-1",
                    "prepared-media-2",
                ],
            },
        }
    elif operation_type == "MANAGE_GOAL_CANDIDATE":
        payload.pop("external_evidence")
        payload["goal_lifecycle_command"] = {
            "schema_version": "goal-lifecycle-command-v1",
            "action": "CREATE_CANDIDATE",
            "run_id": "release-safety-goal-run",
            "proposal_id": "release-safety-goal-proposal",
            "reservation_id": "release-safety-goal-reservation",
            "authority_id": "release-safety-goal-authority",
            "candidate": {
                "schema_version": "goal-candidate-input-v1",
                "name": "Release safety candidate",
                "event": "lead_submitted",
                "site_location": "#lead-form",
                "type": "ACTION",
                "business_meaning": "Prove the production guard.",
                "priority": 1,
                "duplicate_signals": [],
            },
        }
    else:
        raise AssertionError("Unexpected write operation.")
    return payload


class ProductionReleaseSafetyTests(unittest.TestCase):
    _temporary: tempfile.TemporaryDirectory[str]
    root: Path
    wheelhouse: Path
    environments: dict[str, Path]
    poison_support: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._temporary.cleanup)
        cls.root = Path(cls._temporary.name)
        cls.wheelhouse, _ = build_release_wheelhouse(
            cls.root,
            version="1.0.0",
            include_paired_dependencies=True,
        )
        cls.environments = {
            edition: _install_standalone(
                root=cls.root,
                wheelhouse=cls.wheelhouse,
                edition=edition,
            )
            for edition in ("direct", "metrika")
        }
        cls.environments["paired"] = _install_paired(
            root=cls.root,
            wheelhouse=cls.wheelhouse,
        )
        cls.poison_support = _write_poison_sitecustomize(cls.root)

    def test_installed_production_editions_expose_no_write_credentials_or_secrets(
        self,
    ) -> None:
        for edition in ("direct", "metrika"):
            with self.subTest(edition=edition), _installed_production_host(
                root=self.root,
                environment=self.environments[edition],
                edition=edition,
                poison_support=self.poison_support,
            ) as (url, loaded_trap, called_trap, secret_canaries):
                diagnostics = _get_json(url + "/diagnostics")
                serialized = json.dumps(diagnostics, sort_keys=True)

                self.assertEqual("PRODUCTION", diagnostics["trusted_environment"])
                self.assertTrue(diagnostics["provider_read_enabled"])
                self.assertEqual([], diagnostics["write_credentials"])
                self.assertEqual(
                    "BLOCKED_BEFORE_CREDENTIAL_AND_HTTP",
                    diagnostics["production_write_policy"],
                )
                self.assertTrue(
                    all(
                        check["ready"]
                        for check in diagnostics["provider"]["read_credentials"]
                    )
                )
                for canary in secret_canaries:
                    self.assertNotIn(canary, serialized)
                self.assertTrue(loaded_trap.is_file())
                self.assertFalse(called_trap.exists())

    def test_every_installed_production_write_is_blocked_before_credentials_and_http(
        self,
    ) -> None:
        for edition in ("direct", "metrika"):
            edition_cases = tuple(
                operation_type
                for case_edition, operation_type in WRITE_CASES
                if case_edition == edition
            )
            with _installed_production_host(
                root=self.root,
                environment=self.environments[edition],
                edition=edition,
                poison_support=self.poison_support,
            ) as (url, loaded_trap, called_trap, _):
                self.assertTrue(loaded_trap.is_file())
                operation_schema = _get_json(url + "/openapi.json")["components"][
                    "schemas"
                ]["ModuleOperationV1"]
                execute_types = next(
                    branch["properties"]["operation_type"]["enum"]
                    for branch in operation_schema["oneOf"]
                    if branch["properties"]["kind"]["const"] == "EXECUTE"
                )
                self.assertEqual(
                    set(execute_types),
                    {
                        operation_type
                        for _, operation_type in WRITE_CASES
                    },
                )
                for operation_type in edition_cases:
                    with self.subTest(
                        edition=edition,
                        operation_type=operation_type,
                    ):
                        status, result = _post_json(
                            url + "/v1/runs",
                            _execute_request(edition, operation_type),
                        )

                        self.assertEqual(422, status)
                        self.assertEqual("BLOCKED", result["status"])
                        self.assertEqual(
                            PRODUCTION_WRITE_FORBIDDEN,
                            result["errors"][0]["code"],
                        )
                        if operation_type == "APPLY_OPTIMIZATION":
                            self.assertIsNone(result["execution_result"])
                            self.assertEqual(
                                {
                                    "operation_type": "APPLY_OPTIMIZATION",
                                    "proposal_id": "release-safety-proposal",
                                    "status": "DRY_RUN",
                                },
                                result["proposal"],
                            )
                        else:
                            self.assertEqual(
                                operation_type,
                                result["execution_result"]["operation_type"],
                            )
                            self.assertEqual(
                                "BLOCKED",
                                result["execution_result"]["status"],
                            )
                            self.assertFalse(
                                result["execution_result"]["applied"]
                            )
                        self.assertFalse(called_trap.exists())

    def test_installed_paired_production_write_paths_fail_before_credentials_and_http(
        self,
    ) -> None:
        evidence = _probe_installed_paired_production_guard(
            root=self.root,
            environment=self.environments["paired"],
            poison_support=self.poison_support,
        )

        self.assertEqual(
            {
                "constructor_capability_injection",
                "preview_campaign",
                "preview_goal",
                "run_campaign",
                "run_goal",
            },
            set(evidence["blocked_paths"]),
        )
        self.assertEqual([], evidence["write_credentials"])
        self.assertEqual("READ_ONLY", evidence["dashboard_status"]["access"])
        self.assertFalse(evidence["dashboard_status"]["write_requests_allowed"])
        self.assertEqual("DISABLED", evidence["dashboard_status"]["write_flow"])
        self.assertTrue(evidence["poison_loaded"])
        self.assertFalse(evidence["poison_called"])


if __name__ == "__main__":
    unittest.main()
