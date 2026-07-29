from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mox_adv.audit import (
    AuditAnchorVerificationError,
    AuditIntegrityError,
    AuditWriteBlocked,
    SQLiteAuditJournal,
)
from mox_adv.egress import EgressDenied, HttpEgressGuard
from mox_adv.trust_boundary import (
    AuditGuardedFakeWriteAdapter,
    CapabilityEvidence,
    SecretCanaryScanner,
    verify_injection_fixture,
    write_capability_evidence_summary,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "gate0-policy.json"
PROJECTION = ROOT / "fixtures" / "llm" / "LLM_EFFECTIVE_BUDGET_PRESSURE.json"
SECURITY_FIXTURES = ROOT / "fixtures" / "security"
LAUNCHER = ROOT / "scripts" / "mox-adv-host"
NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


class FakeAnchorSigner:
    key_id = "fake-audit-key"

    def __init__(self) -> None:
        self._key = b"local-test-key-with-no-external-authority"

    def sign(self, payload: bytes) -> str:
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def verify(self, payload: bytes, signature: str) -> bool:
        expected = self.sign(payload)
        return hmac.compare_digest(expected, signature)


class RecordingFakeWriteAdapter:
    is_fake = True

    def __init__(self) -> None:
        self.write_calls = 0

    def apply(self, _target_key: str, _command: object) -> None:
        self.write_calls += 1


class InjectionBoundaryTests(unittest.TestCase):
    def test_each_untrusted_surface_is_independently_removed_from_projection(
        self,
    ) -> None:
        policy = load_json(POLICY)
        projection = load_json(PROJECTION)
        paths = sorted(SECURITY_FIXTURES.glob("injection-*.json"))

        self.assertEqual(
            {
                "ad_content",
                "campaign_name",
                "dom",
                "report_error",
                "utm",
            },
            {str(load_json(path)["surface"]) for path in paths},
        )
        for path in paths:
            with self.subTest(fixture=path.name):
                result = verify_injection_fixture(
                    load_json(path),
                    projection,
                    policy,
                )
                self.assertTrue(result.instruction_remained_data)
                self.assertTrue(result.authority_unchanged)
                self.assertTrue(result.policy_unchanged)
                self.assertNotIn(
                    result.injection_text,
                    json.dumps(result.projection, sort_keys=True),
                )
                self.assertTrue(
                    {
                        "target",
                        "method",
                        "tool",
                        "credential_profile",
                        "authority",
                        "scope",
                        "approval",
                        "mandate",
                    }.isdisjoint(result.projection),
                )


class ExactEgressBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = HttpEgressGuard(load_json(POLICY))

    def test_exact_read_and_write_profiles_are_bound_to_matrix_entries(self) -> None:
        self.guard.authorize(
            "POST",
            "https://api.direct.yandex.com/json/v5/reports",
            version="v5",
            service="Reports",
            operation="get",
            credential_profile="DIRECT_PROD_READ",
        )
        self.guard.authorize(
            "GET",
            "https://api-metrika.yandex.net/stat/v1/data?ids=1",
            version="v1",
            service="Statistics",
            operation="get",
            credential_profile="METRIKA_TEST_WRITE",
        )

    def test_every_egress_mutation_fails_closed(self) -> None:
        cases = (
            {
                "http_method": "POST",
                "url": "http://api.direct.yandex.com/json/v5/reports",
                "version": "v5",
                "service": "Reports",
                "operation": "get",
                "credential_profile": "DIRECT_PROD_READ",
            },
            {
                "http_method": "POST",
                "url": "https://api.direct.yandex.com:444/json/v5/reports",
                "version": "v5",
                "service": "Reports",
                "operation": "get",
                "credential_profile": "DIRECT_PROD_READ",
            },
            {
                "http_method": "GET",
                "url": "https://api.direct.yandex.com/json/v5/reports",
                "version": "v5",
                "service": "Reports",
                "operation": "get",
                "credential_profile": "DIRECT_PROD_READ",
            },
            {
                "http_method": "POST",
                "url": "https://api.direct.yandex.com/json/v5/reports",
                "version": "v5",
                "service": "Reports",
                "operation": "unknown",
                "credential_profile": "DIRECT_PROD_READ",
            },
            {
                "http_method": "POST",
                "url": "https://api.direct.yandex.com/json/v5/reports",
                "version": "v5",
                "service": "Reports",
                "operation": "get",
                "credential_profile": "DIRECT_PILOT_WRITE",
            },
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(EgressDenied):
                self.guard.authorize(**case)

        with self.assertRaises(EgressDenied):
            self.guard.authorize(
                "POST",
                "https://api.direct.yandex.com/json/v5/reports",
                version="v5",
                service="Reports",
                operation="get",
                credential_profile="DIRECT_PROD_READ",
                redirected=True,
            )


class SignedAuditGateTests(unittest.TestCase):
    def test_signed_current_pre_write_anchor_allows_one_fake_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            journal = SQLiteAuditJournal(
                Path(temporary_directory) / "audit.sqlite3",
                "audit-write",
                "run-artifacts-v1",
                "policy-v1",
            )
            event = journal.append(
                "write.intent.recorded",
                {"execution_key": "execution-1", "target": "campaign-1"},
            )
            signer = FakeAnchorSigner()
            anchor = journal.create_signed_anchor(signer, NOW)
            delegate = RecordingFakeWriteAdapter()
            adapter = AuditGuardedFakeWriteAdapter(
                delegate,
                journal,
                signer,
                anchor,
                event.event_hash,
                maximum_anchor_age=timedelta(minutes=15),
                clock=lambda: NOW + timedelta(minutes=1),
            )

            adapter.apply("campaign-1", object())

            self.assertEqual(1, delegate.write_calls)
            journal.close()

    def test_missing_or_overdue_pre_write_anchor_blocks_fake_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            journal = SQLiteAuditJournal(
                Path(temporary_directory) / "audit.sqlite3",
                "audit-write",
                "run-artifacts-v1",
                "policy-v1",
            )
            event = journal.append(
                "write.intent.recorded",
                {"execution_key": "execution-1", "target": "campaign-1"},
            )
            signer = FakeAnchorSigner()
            anchor = journal.create_signed_anchor(signer, NOW)
            for expected_hash, clock in (
                (None, lambda: NOW),
                (event.event_hash, lambda: NOW + timedelta(minutes=16)),
            ):
                delegate = RecordingFakeWriteAdapter()
                adapter = AuditGuardedFakeWriteAdapter(
                    delegate,
                    journal,
                    signer,
                    anchor,
                    expected_hash,
                    maximum_anchor_age=timedelta(minutes=15),
                    clock=clock,
                )
                with self.subTest(expected_hash=expected_hash):
                    with self.assertRaises(AuditWriteBlocked):
                        adapter.apply("campaign-1", object())
                    self.assertEqual(0, delegate.write_calls)
            journal.close()

    def test_mutation_deletion_and_anchor_corruption_are_detected(self) -> None:
        for statement in (
            "UPDATE events SET payload_json = '{\"changed\":true}' WHERE sequence = 1",
            "DELETE FROM events WHERE sequence = 1",
        ):
            with (
                self.subTest(statement=statement),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = Path(directory) / "audit.sqlite3"
                journal = SQLiteAuditJournal(
                    path,
                    "audit-corruption",
                    "run-artifacts-v1",
                    "policy-v1",
                )
                journal.append("write.intent.recorded", {"target": "campaign-1"})
                signer = FakeAnchorSigner()
                anchor = journal.create_signed_anchor(signer, NOW)
                journal.close()
                with sqlite3.connect(path) as connection:
                    connection.execute(statement)
                reopened = SQLiteAuditJournal.open(path)
                with self.assertRaises(AuditIntegrityError):
                    reopened.verify_signed_anchor(
                        anchor,
                        signer,
                        now=NOW,
                        maximum_age=timedelta(minutes=15),
                    )
                reopened.close()

        with tempfile.TemporaryDirectory() as directory:
            journal = SQLiteAuditJournal(
                Path(directory) / "audit.sqlite3",
                "audit-signature",
                "run-artifacts-v1",
                "policy-v1",
            )
            journal.append("write.intent.recorded", {"target": "campaign-1"})
            signer = FakeAnchorSigner()
            anchor = journal.create_signed_anchor(signer, NOW)
            corrupted = anchor.with_signature("0" * 64)
            with self.assertRaises(AuditAnchorVerificationError):
                journal.verify_signed_anchor(
                    corrupted,
                    signer,
                    now=NOW,
                    maximum_age=timedelta(minutes=15),
                )
            journal.close()


class HostLauncherAndCanaryTests(unittest.TestCase):
    def test_fake_keychain_host_run_leaks_no_canary_and_emits_artifacts(self) -> None:
        canary = "CANARY-" + uuid.uuid4().hex
        run_id = "host-boundary-" + uuid.uuid4().hex[:12]
        run_directory = ROOT / "runs" / run_id
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            canary_file = temporary / "credential"
            canary_file.write_text(canary + "\n", encoding="utf-8")
            keychain_args = temporary / "keychain-args"
            docker_args = temporary / "docker-args"
            fake_keychain = temporary / "fake-security"
            fake_keychain.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$*\" > '{keychain_args}'\n"
                f"exec /bin/cat '{canary_file}'\n",
                encoding="utf-8",
            )
            fake_keychain.chmod(0o700)
            fake_docker = temporary / "docker"
            fake_docker.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$*\" > '{docker_args}'\n"
                "run_id=''\n"
                "profile=''\n"
                "credential='false'\n"
                'while [ "$#" -gt 0 ]; do\n'
                "  if [ \"$1\" = '--run-id' ]; then run_id=$2; shift 2; continue; fi\n"
                "  if [ \"$1\" = '--credential-profile' ]; then\n"
                "    profile=$2; shift 2; continue\n"
                "  fi\n"
                "  if [ \"$1\" = '--credential-stdin' ]; then credential='true'; fi\n"
                "  shift\n"
                "done\n"
                f"cd '{ROOT}'\n"
                "if [ \"$credential\" = 'true' ]; then\n"
                "  exec env PYTHONPATH=src python3 -m mox_adv run-fixture "
                '--runs-dir runs --run-id "$run_id" '
                '--credential-profile "$profile" --credential-stdin\n'
                "fi\n"
                "exec env PYTHONPATH=src python3 -m mox_adv run-fixture "
                '--runs-dir runs --run-id "$run_id"\n',
                encoding="utf-8",
            )
            fake_docker.chmod(0o700)
            environment = dict(os.environ)
            environment["PATH"] = str(temporary) + os.pathsep + environment["PATH"]
            environment["MOX_ADV_KEYCHAIN_COMMAND"] = str(fake_keychain)

            completed = subprocess.run(
                [
                    str(LAUNCHER),
                    "run-fixture",
                    "--run-id",
                    run_id,
                    "--credential-profile",
                    "DIRECT_PROD_READ",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            try:
                self.assertEqual(0, completed.returncode, completed.stderr)
                self.assertEqual(
                    "find-generic-password -w -s MOX_ADV_DIRECT_PROD_READ",
                    keychain_args.read_text(encoding="utf-8").strip(),
                )
                artifacts = tuple(run_directory.iterdir())
                self.assertTrue(
                    {
                        "result.json",
                        "report.md",
                        "events.jsonl",
                    }.issubset({path.name for path in artifacts}),
                )
                projection = verify_injection_fixture(
                    load_json(SECURITY_FIXTURES / "injection-report-error.json"),
                    load_json(PROJECTION),
                    load_json(POLICY),
                ).projection
                scanner = SecretCanaryScanner(canary)
                violations = scanner.scan(
                    channels={
                        "source": "\n".join(
                            path.read_text(encoding="utf-8", errors="ignore")
                            for path in (ROOT / "src").rglob("*.py")
                        ),
                        "prompt": json.dumps(projection, sort_keys=True),
                        "environment_variables": json.dumps(
                            environment, sort_keys=True
                        ),
                        "argv": json.dumps(
                            [
                                str(LAUNCHER),
                                "run-fixture",
                                "--run-id",
                                run_id,
                                "--credential-profile",
                                "DIRECT_PROD_READ",
                            ]
                        ),
                        "docker_metadata": docker_args.read_text(encoding="utf-8"),
                        "logs": completed.stdout + completed.stderr,
                        "stdout": completed.stdout,
                        "exceptions": completed.stderr,
                    },
                    artifact_paths=artifacts,
                )
                self.assertEqual((), violations)
            finally:
                if run_directory.exists():
                    for path in run_directory.iterdir():
                        path.unlink()
                    run_directory.rmdir()

    def test_unknown_or_write_profile_never_reaches_fake_keychain(self) -> None:
        for profile in ("UNKNOWN_PROFILE", "DIRECT_PILOT_WRITE"):
            with (
                self.subTest(profile=profile),
                tempfile.TemporaryDirectory() as directory,
            ):
                marker = Path(directory) / "called"
                fake_keychain = Path(directory) / "fake-security"
                fake_keychain.write_text(
                    f"#!/bin/sh\n/usr/bin/touch '{marker}'\nexit 1\n",
                    encoding="utf-8",
                )
                fake_keychain.chmod(0o700)
                environment = dict(os.environ)
                environment["MOX_ADV_KEYCHAIN_COMMAND"] = str(fake_keychain)
                completed = subprocess.run(
                    [
                        str(LAUNCHER),
                        "run-fixture",
                        "--run-id",
                        "reject-profile",
                        "--credential-profile",
                        profile,
                    ],
                    cwd=ROOT,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(2, completed.returncode)
                self.assertFalse(marker.exists())


class CapabilityEvidenceTests(unittest.TestCase):
    def test_summary_is_case_aligned_and_uses_honest_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence_file = root / "events.jsonl"
            evidence_file.write_text("{}\n", encoding="utf-8")
            destination = root / "capability-evidence.json"
            write_capability_evidence_summary(
                destination,
                run_id="trust-boundary-evidence",
                policy_version="mox-adv-gate0-2026-07-29",
                capabilities=(
                    CapabilityEvidence(
                        capability="PROMPT_INJECTION_RESISTANCE",
                        status="PROVEN",
                        evidence_type="SIMULATED",
                        acceptance_cases=("22", "22.1"),
                        evidence_paths=(str(evidence_file),),
                        limitations=("Local fixtures only.",),
                    ),
                    CapabilityEvidence(
                        capability="SECRET_ISOLATION",
                        status="PROVEN",
                        evidence_type="SIMULATED",
                        acceptance_cases=("23",),
                        evidence_paths=(str(evidence_file),),
                        limitations=("Fake Keychain only.",),
                    ),
                    CapabilityEvidence(
                        capability="TAMPER_EVIDENT_AUDIT",
                        status="PROVEN",
                        evidence_type="SIMULATED",
                        acceptance_cases=("23.1",),
                        evidence_paths=(str(evidence_file),),
                        limitations=("Fake signer only.",),
                    ),
                    CapabilityEvidence(
                        capability="HOST_DOCKER_BOUNDARY",
                        status="PARTIAL",
                        evidence_type="SIMULATED",
                        acceptance_cases=("24",),
                        evidence_paths=(str(evidence_file),),
                        limitations=("Real Docker smoke is reported separately.",),
                    ),
                ),
            )

            summary = load_json(destination)

            self.assertEqual("trust-boundary-evidence", summary["run_id"])
            self.assertEqual(
                {"22", "22.1", "23", "23.1", "24"},
                {
                    case
                    for capability in summary["capabilities"]
                    for case in capability["acceptance_cases"]
                },
            )
            self.assertTrue(
                all(
                    capability["status"]
                    in {"PROVEN", "PARTIAL", "NOT_PROVEN", "INCONCLUSIVE"}
                    for capability in summary["capabilities"]
                )
            )


if __name__ == "__main__":
    unittest.main()
