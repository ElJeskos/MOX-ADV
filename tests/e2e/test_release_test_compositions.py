"""Clean-wheel proof for explicit write-capable TEST compositions."""

from __future__ import annotations

import json
import os
import platform
import pwd
import selectors
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

from tests.e2e.test_release_distributions import _build_wheel
from tests.e2e.test_standalone_direct_module import (
    campaign_creation_module_request,
    campaign_draft_payload,
    direct_action_plan_request,
)
from tests.e2e.test_standalone_metrika_goal_lifecycle import (
    goal_candidate,
    goal_request,
)

ROOT = Path(__file__).resolve().parents[2]


class InstalledTestHost:
    def __init__(
        self,
        *,
        root: Path,
        provider: str,
        resources: Path,
    ) -> None:
        self.root = root
        self.provider = provider
        self.resources = resources
        self.environment = root / ("venv-" + provider)
        self.state = root / ("state-" + provider)
        self.state.mkdir(mode=0o700)
        wheels = [
            _build_wheel(
                ROOT / "packaging" / name / "setup.py",
                root / ("build-" + provider + "-" + name),
            )
            for name in ("core", provider)
        ]
        subprocess.run(
            [sys.executable, "-m", "venv", str(self.environment)],
            check=True,
            capture_output=True,
            text=True,
        )
        installed = subprocess.run(
            [
                str(self.environment / "bin" / "python"),
                "-m",
                "pip",
                "install",
                "--quiet",
                "--no-deps",
                "--no-index",
                *(str(wheel) for wheel in wheels),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if installed.returncode:
            raise AssertionError(installed.stderr)
        self.command = self.environment / "bin" / ("mox-adv-" + provider)
        self.process: subprocess.Popen[str] | None = None
        self.url = ""

    def start(self) -> InstalledTestHost:
        self.process = subprocess.Popen(
            [
                str(self.command),
                "serve",
                "--environment",
                "TEST",
                "--state-dir",
                str(self.state),
                "--test-resources",
                str(self.resources),
                "--port",
                "0",
            ],
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                name: value
                for name, value in os.environ.items()
                if name != "PYTHONPATH"
            },
            text=True,
        )
        assert self.process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(self.process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + 10
        try:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    break
                if not selector.select(timeout=0.1):
                    continue
                line = self.process.stdout.readline()
                if not line:
                    continue
                event = json.loads(line)
                if event.get("event") == "ready":
                    self.url = str(event["url"])
                    return self
        finally:
            selector.close()
        _stdout, stderr = self.stop()
        raise AssertionError("Installed TEST host did not start: " + stderr)

    def post(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            self.url + "/v1/runs",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def cli(
        self,
        *arguments: str,
        environment_overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = {
            name: value
            for name, value in os.environ.items()
            if name != "PYTHONPATH"
        }
        environment.update(environment_overrides or {})
        return subprocess.run(
            [str(self.command), *arguments],
            cwd=self.root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

    def stop(self) -> tuple[str, str]:
        if self.process is None:
            return "", ""
        if self.process.poll() is None:
            self.process.terminate()
        try:
            return self.process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            return self.process.communicate(timeout=5)


@contextmanager
def _running(host: InstalledTestHost) -> Iterator[InstalledTestHost]:
    try:
        yield host.start()
        assert host.process is not None
        if host.process.poll() is not None:
            raise AssertionError("Installed TEST host exited unexpectedly.")
    except BaseException as error:
        stdout, stderr = host.stop()
        raise AssertionError(
            f"{error}\nTEST host stdout:\n{stdout}\nTEST host stderr:\n{stderr}"
        ) from error
    else:
        host.stop()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _customer_policy(root: Path) -> tuple[Path, dict[str, Any]]:
    policy = json.loads(
        (ROOT / "config" / "gate0-policy.json").read_text(encoding="utf-8")
    )
    authentication = {
        "Darwin": "authenticated_macos_user",
        "Linux": "authenticated_linux_user",
    }[platform.system()]
    for principal in policy["principals"].values():
        principal["identity"] = pwd.getpwuid(os.getuid()).pw_name
        principal["authentication"] = authentication
    path = root / "gate0-policy.json"
    _write_json(path, policy)
    return path, policy


def _fresh_direct_plan() -> dict[str, Any]:
    request = direct_action_plan_request()
    now = datetime.now(timezone.utc)
    period_end = now.date() - timedelta(days=1)
    request["period"]["start_date"] = (period_end - timedelta(days=6)).isoformat()
    request["period"]["end_date"] = period_end.isoformat()
    evidence = request["external_evidence"]
    evidence["observed_at"] = (now - timedelta(minutes=5)).isoformat()
    evidence["watermark"] = (now - timedelta(minutes=10)).isoformat()
    for metric in evidence["metrics"]:
        if metric["name"] == "budget_period_start":
            metric["value"] = (now - timedelta(days=6)).isoformat()
        elif metric["name"] == "budget_period_end":
            metric["value"] = (now + timedelta(days=1)).isoformat()
    return cast(dict[str, Any], request)


class ReleaseTestCompositionTests(unittest.TestCase):
    def test_installed_direct_test_actions_require_explicit_authority(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            resources = root / "direct-test-resources.json"
            policy_path, _policy = _customer_policy(root)
            draft = campaign_draft_payload()
            direct_resources = {
                "schema_version": "direct-test-resources-v1",
                "policy_path": policy_path.name,
                "connection_id": "sim-connection",
                "organization_id": "sim-organization",
                "account_id": "sim-direct-account",
                "campaign_id": "campaign-7",
                "trusted_change_author": "sim-executor",
                "initial_weekly_budget_micros": 2_000_000_000,
                "campaign_safety": {
                    "allowed_landing_hosts": ["allowlisted.example"],
                    "prohibited_phrases": ["guaranteed results"],
                    "prepared_media_references": [
                        "prepared-media-1",
                        "prepared-media-2",
                    ],
                },
                "campaign_authorizations": [
                    {
                        "run_id": "run-headless-create-1",
                        "execution_key": "execution-headless-create-1",
                        "proposal_id": "proposal-headless-create-1",
                        "approval_id": "approval-headless-create-1",
                        "reservation_id": "reservation-headless-create-1",
                        "expires_at": "2099-01-01T00:00:00+00:00",
                        "draft": draft,
                    }
                ],
            }
            _write_json(resources, direct_resources)
            host = InstalledTestHost(
                root=root,
                provider="direct",
                resources=resources,
            )
            with _running(host):
                plan = _fresh_direct_plan()
                status, planned = host.post(plan)
                self.assertEqual(200, status, planned)
                self.assertEqual("PROPOSED", planned["proposal"]["status"])
                proposal_id = planned["proposal"]["proposal_id"]

                execute = dict(plan)
                execute["operation"] = {
                    "kind": "EXECUTE",
                    "operation_type": "APPLY_OPTIMIZATION",
                }
                execute["direct_action_command"] = {
                    "schema_version": "direct-action-command-v1",
                    "command": "EXECUTE_PROPOSAL",
                    "proposal_id": proposal_id,
                }
                execute["idempotency_key"] = "release-direct-execute-test-1"
                blocked_status, blocked = host.post(execute)
                self.assertEqual(422, blocked_status)
                self.assertEqual("APPROVAL_NOT_FOUND", blocked["errors"][0]["code"])

                spoof_policy = json.loads(
                    policy_path.read_text(encoding="utf-8")
                )
                spoof_policy["principals"]["approver"]["identity"] = (
                    "unauthorized-release-user"
                )
                spoof_policy_path = root / "spoof-direct-policy.json"
                _write_json(spoof_policy_path, spoof_policy)
                spoof_resources = dict(direct_resources)
                spoof_resources["policy_path"] = spoof_policy_path.name
                spoof_resources_path = root / "spoof-direct-resources.json"
                _write_json(spoof_resources_path, spoof_resources)
                rejected_caller = host.cli(
                    "approve-test",
                    "--environment",
                    "TEST",
                    "--state-dir",
                    str(host.state),
                    "--test-resources",
                    str(spoof_resources_path),
                    "--proposal-id",
                    proposal_id,
                    "--reason",
                    "A different local user must not grant authority.",
                    environment_overrides={
                        "LOGNAME": "unauthorized-release-user",
                        "USER": "unauthorized-release-user",
                        "LNAME": "unauthorized-release-user",
                        "USERNAME": "unauthorized-release-user",
                    },
                )
                self.assertEqual(2, rejected_caller.returncode)
                self.assertIn(
                    "UNAUTHENTICATED_PRINCIPAL",
                    rejected_caller.stderr,
                )

                approved = host.cli(
                    "approve-test",
                    "--environment",
                    "TEST",
                    "--state-dir",
                    str(host.state),
                    "--test-resources",
                    str(resources),
                    "--proposal-id",
                    proposal_id,
                    "--reason",
                    "Approve the exact clean-wheel TEST proposal.",
                )
                self.assertEqual(0, approved.returncode, approved.stderr)
                execute["idempotency_key"] = "release-direct-execute-test-2"
                applied_status, applied = host.post(execute)
                duplicate_status, duplicate = host.post(execute)
                self.assertEqual(200, applied_status)
                self.assertEqual(200, duplicate_status)
                self.assertEqual("APPLIED", applied["execution_result"]["status"])
                self.assertEqual(
                    "ALREADY_PROCESSED",
                    duplicate["execution_result"]["status"],
                )

                create_request = campaign_creation_module_request()
                create_request["connection_ref"] = {
                    "connection_id": "sim-connection"
                }
                create_status, created = host.post(create_request)
                self.assertEqual(200, create_status, created)
                self.assertEqual("APPLIED", created["execution_result"]["status"])

                wrong_scope = campaign_creation_module_request(
                    execution_key="execution-wrong-scope-1"
                )
                wrong_scope["connection_ref"] = {
                    "connection_id": "sim-connection"
                }
                wrong_scope["scope"]["account_id"] = "production-account"
                wrong_status, wrong = host.post(wrong_scope)
                self.assertEqual(422, wrong_status)
                self.assertEqual(
                    "DIRECT_CAMPAIGN_SCOPE_REJECTED",
                    wrong["errors"][0]["code"],
                )

                production = campaign_creation_module_request(
                    environment="PRODUCTION",
                    execution_key="execution-production-1",
                )
                production_status, production_result = host.post(production)
                self.assertEqual(422, production_status)
                self.assertEqual(
                    "PRODUCTION_WRITE_FORBIDDEN",
                    production_result["errors"][0]["code"],
                )

            with sqlite3.connect(
                host.state / "direct-test" / "control.sqlite3"
            ) as connection:
                applied_count = connection.execute(
                    "SELECT COUNT(*) FROM executions WHERE status = 'APPLIED'"
                ).fetchone()
            self.assertEqual((1,), applied_count)

    def test_installed_metrika_goal_and_site_actions_use_bound_test_resources(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            resources = root / "metrika-test-resources.json"
            policy_path, policy = _customer_policy(root)
            candidate = goal_candidate()
            metrika_resources = {
                "schema_version": "metrika-test-resources-v1",
                "policy_path": policy_path.name,
                "connection_id": "stored-test-metrika",
                "counter_id": "sim-test-counter",
                "site_zone": "sim-test-site-zone",
                "site_version": "test-page-v1",
                "site_publish_credential_profile": "TEST_SITE_PUBLISH",
                "principals": {
                    role: dict(policy["principals"][role])
                    for role in (
                        "mandate_issuer",
                        "approver",
                        "product_signoff",
                    )
                },
                "goal_authorizations": [
                    {
                        "run_id": "release-goal-run-1",
                        "proposal_id": "release-goal-proposal-1",
                        "reservation_id": "release-goal-reservation-1",
                        "authority_id": "release-goal-authority-1",
                        "expires_at": "2099-01-01T00:00:00+00:00",
                        "candidate": candidate,
                    }
                ],
            }
            _write_json(resources, metrika_resources)
            host = InstalledTestHost(
                root=root,
                provider="metrika",
                resources=resources,
            )
            with _running(host):
                create = goal_request(
                    {
                        "schema_version": "goal-lifecycle-command-v1",
                        "action": "CREATE_CANDIDATE",
                        "run_id": "release-goal-run-1",
                        "proposal_id": "release-goal-proposal-1",
                        "reservation_id": "release-goal-reservation-1",
                        "authority_id": "release-goal-authority-1",
                        "candidate": candidate,
                    }
                )
                create["idempotency_key"] = "release-goal-create-1"
                status, created = host.post(create)
                self.assertEqual(200, status)
                candidate_id = created["lifecycle_outcome"]["candidate_id"]

                spoof_policy = json.loads(
                    policy_path.read_text(encoding="utf-8")
                )
                for role in (
                    "mandate_issuer",
                    "approver",
                    "product_signoff",
                ):
                    spoof_policy["principals"][role]["identity"] = (
                        "unauthorized-release-user"
                    )
                spoof_policy_path = root / "spoof-metrika-policy.json"
                _write_json(spoof_policy_path, spoof_policy)
                spoof_resources = dict(metrika_resources)
                spoof_resources["policy_path"] = spoof_policy_path.name
                spoof_resources["principals"] = {
                    role: dict(spoof_policy["principals"][role])
                    for role in (
                        "mandate_issuer",
                        "approver",
                        "product_signoff",
                    )
                }
                spoof_resources_path = root / "spoof-metrika-resources.json"
                _write_json(spoof_resources_path, spoof_resources)
                rejected_caller = host.cli(
                    "authorize-site-test",
                    "--environment",
                    "TEST",
                    "--state-dir",
                    str(host.state),
                    "--test-resources",
                    str(spoof_resources_path),
                    "--candidate-id",
                    candidate_id,
                    "--authority-id",
                    "unauthorized-site-authority",
                    environment_overrides={
                        "LOGNAME": "unauthorized-release-user",
                        "USER": "unauthorized-release-user",
                        "LNAME": "unauthorized-release-user",
                        "USERNAME": "unauthorized-release-user",
                    },
                )
                self.assertEqual(2, rejected_caller.returncode)
                self.assertIn(
                    "UNAUTHENTICATED_PRINCIPAL",
                    rejected_caller.stderr,
                )

                authorized = host.cli(
                    "authorize-site-test",
                    "--environment",
                    "TEST",
                    "--state-dir",
                    str(host.state),
                    "--test-resources",
                    str(resources),
                    "--candidate-id",
                    candidate_id,
                    "--authority-id",
                    "release-site-authority-1",
                )
                self.assertEqual(0, authorized.returncode, authorized.stderr)
                publish = goal_request(
                    {
                        "schema_version": "goal-lifecycle-command-v1",
                        "action": "PUBLISH_EVENT",
                        "candidate_id": candidate_id,
                        "authority_id": "release-site-authority-1",
                        "site_zone": "sim-test-site-zone",
                        "expected_version": "test-page-v1",
                    }
                )
                publish["idempotency_key"] = "release-goal-publish-1"
                publish_status, published = host.post(publish)
                self.assertEqual(200, publish_status)
                self.assertEqual(
                    "EVENT_PUBLISHED",
                    published["lifecycle_outcome"]["lifecycle_status"],
                )

                wrong = dict(publish)
                wrong["idempotency_key"] = "release-goal-wrong-counter-1"
                wrong["scope"] = dict(publish["scope"])
                wrong["scope"]["counter_id"] = "production-counter"
                wrong_status, wrong_result = host.post(wrong)
                self.assertEqual(422, wrong_status)
                self.assertEqual(
                    "METRIKA_GOAL_SCOPE_REJECTED",
                    wrong_result["errors"][0]["code"],
                )

    def test_invalid_test_resources_are_not_ready_and_never_echo_secrets(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            invalid = root / "invalid.json"
            sentinel = "secret-value-must-not-be-echoed"
            invalid.write_text(
                '{"schema_version":"wrong","token":"' + sentinel + '"}',
                encoding="utf-8",
            )
            metrika_host: InstalledTestHost | None = None
            for provider in ("direct", "metrika"):
                with self.subTest(provider=provider):
                    host = InstalledTestHost(
                        root=root,
                        provider=provider,
                        resources=invalid,
                    )
                    diagnostics = host.cli(
                        "diagnostics",
                        "--environment",
                        "TEST",
                        "--state-dir",
                        str(host.state),
                        "--test-resources",
                        str(invalid),
                    )
                    self.assertEqual(
                        0,
                        diagnostics.returncode,
                        diagnostics.stderr,
                    )
                    result = json.loads(diagnostics.stdout)
                    self.assertFalse(
                        result["provider"]["configuration_ready"]
                    )
                    self.assertEqual([], result["write_credentials"])
                    self.assertNotIn(sentinel, diagnostics.stdout)
                    if provider == "metrika":
                        metrika_host = host

            assert metrika_host is not None
            policy_path, policy = _customer_policy(root)
            wrong_role = root / "wrong-role-metrika.json"
            principals = {
                role: dict(policy["principals"][role])
                for role in (
                    "mandate_issuer",
                    "approver",
                    "product_signoff",
                )
            }
            principals["approver"]["identity"] = "different-approver"
            _write_json(
                wrong_role,
                {
                    "schema_version": "metrika-test-resources-v1",
                    "policy_path": policy_path.name,
                    "connection_id": "stored-test-metrika",
                    "counter_id": "sim-test-counter",
                    "site_zone": "sim-test-site-zone",
                    "site_version": "test-page-v1",
                    "site_publish_credential_profile": "TEST_SITE_PUBLISH",
                    "principals": principals,
                    "goal_authorizations": [],
                },
            )
            role_diagnostics = metrika_host.cli(
                "diagnostics",
                "--environment",
                "TEST",
                "--state-dir",
                str(metrika_host.state),
                "--test-resources",
                str(wrong_role),
            )
            self.assertEqual(0, role_diagnostics.returncode)
            role_result = json.loads(role_diagnostics.stdout)
            self.assertFalse(role_result["provider"]["configuration_ready"])

            wrong_profile = json.loads(wrong_role.read_text(encoding="utf-8"))
            wrong_profile["principals"] = {
                role: dict(policy["principals"][role])
                for role in (
                    "mandate_issuer",
                    "approver",
                    "product_signoff",
                )
            }
            wrong_profile["site_publish_credential_profile"] = (
                "METRIKA_TEST_WRITE"
            )
            wrong_profile_path = root / "wrong-site-profile-metrika.json"
            _write_json(wrong_profile_path, wrong_profile)
            profile_diagnostics = metrika_host.cli(
                "diagnostics",
                "--environment",
                "TEST",
                "--state-dir",
                str(metrika_host.state),
                "--test-resources",
                str(wrong_profile_path),
            )
            self.assertEqual(0, profile_diagnostics.returncode)
            profile_result = json.loads(profile_diagnostics.stdout)
            self.assertFalse(
                profile_result["provider"]["configuration_ready"]
            )


if __name__ == "__main__":
    unittest.main()
