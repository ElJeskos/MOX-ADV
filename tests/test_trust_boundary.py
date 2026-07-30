from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from mox_adv.approval_execution import (
    ApprovalRequiredPolicy,
    ExecutionFacts,
    ExecutionRequest,
)
from mox_adv.audit import (
    AuditAnchorVerificationError,
    AuditIntegrityError,
    AuditWriteBlocked,
    SQLiteAuditJournal,
)
from mox_adv.commands import OptimizationAction, calculate_relative_target
from mox_adv.control_state import PreparedChange, TrustedScope
from mox_adv.egress import (
    CredentialProfile,
    EgressAuthority,
    EgressDenied,
    HttpEgressGuard,
)
from mox_adv.environment import ExecutionEnvironment
from mox_adv.model_provider import DeterministicFakeModelProvider
from mox_adv.proposal_store import ImmutableProposalStore
from mox_adv.recommend_service import RecommendationService
from mox_adv.trust_boundary import (
    AuditGuardedFakeWriteAdapter,
    CapabilityEvidence,
    DurablePreWriteAudit,
    MacOSKeychainAuditAnchorSigner,
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
                self.assertTrue(result.untrusted_text_excluded)
                self.assertTrue(result.authority_unchanged)
                self.assertTrue(result.policy_unchanged)
                self.assertNotIn(
                    result.injection_text,
                    json.dumps(dict(result.projection), sort_keys=True),
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

    def test_each_surface_passes_actual_proposal_and_policy_without_authority_change(
        self,
    ) -> None:
        policy = load_json(POLICY)
        projection_fixture = load_json(PROJECTION)
        paths = sorted(SECURITY_FIXTURES.glob("injection-*.json"))
        with tempfile.TemporaryDirectory() as directory:
            provider = DeterministicFakeModelProvider()
            service = RecommendationService(
                provider,
                ImmutableProposalStore(Path(directory)),
            )
            for path in paths:
                fixture = load_json(path)
                verification = verify_injection_fixture(
                    fixture,
                    projection_fixture,
                    policy,
                )
                outcome = service.recommend(
                    projection=verification.projection,
                    run_id="run-" + str(fixture["surface"]),
                    snapshot_id="sha256:" + "a" * 64,
                    expected_fingerprint="sha256:" + "b" * 64,
                    created_at="2026-07-30T12:00:00+00:00",
                    expires_at="2026-07-30T12:30:00+00:00",
                )
                with self.subTest(fixture=path.name):
                    self.assertEqual("READY", outcome.status)
                    self.assertEqual("NOT_STARTED", outcome.execution_status)
                    self.assertIsNotNone(outcome.proposal)
                    proposal = outcome.proposal
                    assert proposal is not None
                    serialized = json.dumps(proposal.as_dict(), sort_keys=True)
                    for text in fixture["untrusted_payload"].values():
                        if isinstance(text, str):
                            self.assertNotIn(text, serialized)
                    self.assertTrue(
                        {
                            "target",
                            "method",
                            "tool",
                            "credential_profile",
                            "authority",
                            "approval",
                            "mandate",
                        }.isdisjoint(proposal.as_dict()),
                    )
                    prepared = self._prepared_change(proposal.proposal_id)
                    request = self._execution_request(prepared)
                    decision = ApprovalRequiredPolicy(policy).evaluate(
                        prepared,
                        request,
                    )
                    self.assertTrue(decision.allowed, decision.reason_code)
            self.assertEqual(5, provider.invocation_count)

    def test_personal_and_commercial_source_fields_are_removed(self) -> None:
        fixture = load_json(SECURITY_FIXTURES / "sensitive-source-fields.json")

        result = verify_injection_fixture(
            fixture,
            load_json(PROJECTION),
            load_json(POLICY),
        )

        serialized = json.dumps(dict(result.projection), sort_keys=True)
        self.assertNotIn("person@example.invalid", serialized)
        self.assertNotIn("Synthetic Customer", serialized)
        self.assertNotIn("commercial_margin", result.projection)

    @staticmethod
    def _prepared_change(proposal_id: str) -> PreparedChange:
        current = 2_000_000_000
        return PreparedChange(
            proposal_id=proposal_id,
            proposal_hash="sha256:" + "1" * 64,
            scope=TrustedScope(
                organization="sim-organization",
                connection="sim-connection",
                account="sim-direct-account",
                campaign="sim-campaign",
                writer="sim-executor",
            ),
            action=OptimizationAction.INCREASE_WEEKLY_BUDGET,
            current_value=current,
            target_value=calculate_relative_target(current, 10),
            expected_diff={
                "operation": "INCREASE_WEEKLY_BUDGET",
                "relative_step_percent": 10,
            },
            snapshot_id="sha256:" + "a" * 64,
            snapshot_generated_at="2026-07-30T11:55:00+00:00",
            direct_watermark="2026-07-30T11:55:00+00:00",
            metrika_watermark="2026-07-30T11:55:00+00:00",
            policy_version="mox-adv-gate0-2026-07-29",
            expected_fingerprint="sha256:" + "b" * 64,
            risk="WEEKLY_BUDGET_INCREASE",
        )

    @staticmethod
    def _execution_request(prepared: PreparedChange) -> ExecutionRequest:
        return ExecutionRequest(
            proposal_id=prepared.proposal_id,
            execution_key=prepared.execution_key(),
            scope=prepared.scope,
            facts=ExecutionFacts(
                mode="APPROVAL_REQUIRED",
                automation_enabled=True,
                comparability_status="COMPARABLE",
                confidence_status="READY",
                financial_recommendations_allowed=True,
                direct_age_minutes=5,
                metrika_age_minutes=5,
                watermark_skew_minutes=1,
                clicks=100,
                conversions=12,
                impressions=10_000,
                spend_rub=1_900,
                cpa_rub="791.67",
                budget_utilization_percent="95",
                ctr_percent="1",
                campaign_state="ON",
                campaign_strategy="HIGHEST_POSITION",
                current_fingerprint="sha256:" + "b" * 64,
                cooldown_active=False,
                actions_in_last_24h=0,
                cumulative_daily_change_percent=0,
                monetary_exposure_rub=200,
                kill_switch_available=True,
            ),
        )


class ExactEgressBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        policy = load_json(POLICY)
        bindings = policy["bindings"]
        assert isinstance(bindings, dict)
        pilot = bindings["pilot"]
        assert isinstance(pilot, dict)
        pilot["direct_account"] = "pilot-account"
        pilot["test_counter"] = "test-counter"
        pilot["pilot_counter"] = "pilot-counter"
        pilot["test_site_zone"] = "test-site-zone"
        pilot["pilot_site_zone"] = "pilot-site-zone"
        self.guard = HttpEgressGuard(
            policy,
            environment=ExecutionEnvironment.PRODUCTION,
        )

    def test_exact_read_and_write_profiles_are_bound_to_matrix_entries(self) -> None:
        self.guard.authorize(
            "POST",
            "https://api.direct.yandex.com/json/v5/reports",
            version="v5",
            service="Reports",
            operation="get",
            authority=EgressAuthority(
                CredentialProfile.DIRECT_PROD_READ,
                "pilot-account",
            ),
        )
        self.guard.authorize(
            "GET",
            "https://api-metrika.yandex.net/stat/v1/data?ids=test-counter",
            version="v1",
            service="Statistics",
            operation="get",
            authority=EgressAuthority(
                CredentialProfile.METRIKA_TEST_WRITE,
                "test-counter",
            ),
        )

    def test_every_egress_mutation_fails_closed(self) -> None:
        cases = (
            {
                "http_method": "POST",
                "url": "http://api.direct.yandex.com/json/v5/reports",
                "version": "v5",
                "service": "Reports",
                "operation": "get",
                "authority": EgressAuthority(
                    CredentialProfile.DIRECT_PROD_READ,
                    "pilot-account",
                ),
            },
            {
                "http_method": "POST",
                "url": "https://api.direct.yandex.com:444/json/v5/reports",
                "version": "v5",
                "service": "Reports",
                "operation": "get",
                "authority": EgressAuthority(
                    CredentialProfile.DIRECT_PROD_READ,
                    "pilot-account",
                ),
            },
            {
                "http_method": "GET",
                "url": "https://api.direct.yandex.com/json/v5/reports",
                "version": "v5",
                "service": "Reports",
                "operation": "get",
                "authority": EgressAuthority(
                    CredentialProfile.DIRECT_PROD_READ,
                    "pilot-account",
                ),
            },
            {
                "http_method": "POST",
                "url": "https://api.direct.yandex.com/json/v5/reports",
                "version": "v5",
                "service": "Reports",
                "operation": "unknown",
                "authority": EgressAuthority(
                    CredentialProfile.DIRECT_PROD_READ,
                    "pilot-account",
                ),
            },
            {
                "http_method": "POST",
                "url": "https://api.direct.yandex.com/json/v5/reports",
                "version": "v5",
                "service": "Reports",
                "operation": "get",
                "authority": EgressAuthority(
                    CredentialProfile.DIRECT_PILOT_WRITE,
                    "pilot-account",
                ),
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
                authority=EgressAuthority(
                    CredentialProfile.DIRECT_PROD_READ,
                    "pilot-account",
                ),
                redirected=True,
            )

    def test_metrika_profile_and_counter_must_match_exact_binding(self) -> None:
        cases = (
            (
                CredentialProfile.METRIKA_TEST_WRITE,
                "pilot-counter",
                "pilot-counter",
            ),
            (
                CredentialProfile.METRIKA_PILOT_WRITE,
                "test-counter",
                "test-counter",
            ),
            (
                CredentialProfile.METRIKA_TEST_WRITE,
                "test-counter",
                "pilot-counter",
            ),
        )
        for profile, trusted_target, url_counter in cases:
            with self.subTest(profile=profile), self.assertRaises(EgressDenied):
                self.guard.authorize(
                    "GET",
                    "https://api-metrika.yandex.net/stat/v1/data?ids=" + url_counter,
                    version="v1",
                    service="Statistics",
                    operation="get",
                    authority=EgressAuthority(profile, trusted_target),
                )

    def test_browser_profile_site_zone_and_counter_must_match_exact_binding(
        self,
    ) -> None:
        policy = load_json(POLICY)
        record = policy["record"]
        assert isinstance(record, dict)
        record["production_write_authorized"] = True
        bindings = policy["bindings"]
        assert isinstance(bindings, dict)
        pilot = bindings["pilot"]
        assert isinstance(pilot, dict)
        pilot["test_counter"] = "test-counter"
        pilot["pilot_counter"] = "pilot-counter"
        pilot["test_site_zone"] = "test-site-zone"
        pilot["pilot_site_zone"] = "pilot-site-zone"
        guard = HttpEgressGuard(
            policy,
            environment=ExecutionEnvironment.TEST,
        )

        guard.authorize(
            "POST",
            "https://mc.yandex.ru/watch/test-counter",
            version="tag-v1",
            service="BrowserTag",
            operation="reachGoal",
            authority=EgressAuthority(
                CredentialProfile.TEST_SITE_PUBLISH,
                "test-site-zone",
                counter_id="test-counter",
            ),
            pilot_armed=True,
        )

        cases = (
            EgressAuthority(
                CredentialProfile.TEST_SITE_PUBLISH,
                "test-site-zone",
                counter_id="pilot-counter",
            ),
            EgressAuthority(
                CredentialProfile.TEST_SITE_PUBLISH,
                "pilot-site-zone",
                counter_id="test-counter",
            ),
            EgressAuthority(
                CredentialProfile.PILOT_SITE_PUBLISH,
                "pilot-site-zone",
                counter_id="test-counter",
            ),
        )
        for authority in cases:
            with self.subTest(authority=authority), self.assertRaises(EgressDenied):
                guard.authorize(
                    "POST",
                    "https://mc.yandex.ru/watch/test-counter",
                    version="tag-v1",
                    service="BrowserTag",
                    operation="reachGoal",
                    authority=authority,
                    pilot_armed=True,
                )


class SignedAuditGateTests(unittest.TestCase):
    @mock.patch("mox_adv.trust_boundary.subprocess.run")
    def test_persisted_anchor_is_verified_by_new_keychain_signer_instance(
        self,
        run: mock.Mock,
    ) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=["security"],
            returncode=0,
            stdout=b"fake-keychain-audit-key\n",
            stderr=b"",
        )
        with tempfile.TemporaryDirectory() as directory:
            control_state = Path(directory) / "control.sqlite3"
            authorizer = DurablePreWriteAudit(
                control_state,
                "policy-v1",
                MacOSKeychainAuditAnchorSigner(
                    service="MOX_ADV_TEST_AUDIT_KEY",
                    account="test-principal",
                ),
            )
            authorizer.authorize("execution-1", "campaign-1", NOW)

            verifier = DurablePreWriteAudit(
                control_state,
                "policy-v1",
                MacOSKeychainAuditAnchorSigner(
                    service="MOX_ADV_TEST_AUDIT_KEY",
                    account="test-principal",
                ),
            )
            anchor = verifier.verify_persisted(
                "execution-1",
                now=NOW + timedelta(minutes=1),
                maximum_age=timedelta(minutes=15),
            )

            self.assertEqual(
                "macos-keychain:MOX_ADV_TEST_AUDIT_KEY:test-principal",
                anchor.key_id,
            )
            self.assertGreaterEqual(run.call_count, 3)
            for call in run.call_args_list:
                self.assertNotIn(
                    "fake-keychain-audit-key",
                    " ".join(call.args[0]),
                )

    @mock.patch("mox_adv.trust_boundary.subprocess.run")
    def test_persisted_anchor_rejects_execution_and_policy_replay(
        self,
        run: mock.Mock,
    ) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=["security"],
            returncode=0,
            stdout=b"fake-keychain-audit-key\n",
            stderr=b"",
        )
        with tempfile.TemporaryDirectory() as directory:
            control_state = Path(directory) / "control.sqlite3"
            signer = MacOSKeychainAuditAnchorSigner(
                service="MOX_ADV_TEST_AUDIT_KEY",
                account="test-principal",
            )
            authorizer = DurablePreWriteAudit(
                control_state,
                "policy-v1",
                signer,
            )
            authorizer.authorize("execution-1", "campaign-1", NOW)

            source_digest = hashlib.sha256(b"execution-1").hexdigest()
            replay_digest = hashlib.sha256(b"execution-2").hexdigest()
            for suffix in (".sqlite3", ".anchor.json"):
                shutil.copy2(
                    authorizer.root / (source_digest + suffix),
                    authorizer.root / (replay_digest + suffix),
                )

            replay_verifier = DurablePreWriteAudit(
                control_state,
                "policy-v1",
                MacOSKeychainAuditAnchorSigner(
                    service="MOX_ADV_TEST_AUDIT_KEY",
                    account="test-principal",
                ),
            )
            with self.assertRaisesRegex(AuditWriteBlocked, "AUDIT_ANCHOR_INVALID"):
                replay_verifier.verify_persisted(
                    "execution-2",
                    now=NOW + timedelta(minutes=1),
                    maximum_age=timedelta(minutes=15),
                )

            wrong_policy_verifier = DurablePreWriteAudit(
                control_state,
                "policy-v2",
                MacOSKeychainAuditAnchorSigner(
                    service="MOX_ADV_TEST_AUDIT_KEY",
                    account="test-principal",
                ),
            )
            with self.assertRaisesRegex(AuditWriteBlocked, "AUDIT_ANCHOR_INVALID"):
                wrong_policy_verifier.verify_persisted(
                    "execution-1",
                    now=NOW + timedelta(minutes=1),
                    maximum_age=timedelta(minutes=15),
                )

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
                            for source_root in (ROOT / "src", ROOT / "scripts")
                            for path in source_root.rglob("*")
                            if path.is_file()
                        ),
                        "prompt": json.dumps(dict(projection), sort_keys=True),
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

    def test_container_failure_does_not_expose_ephemeral_credential(self) -> None:
        canary = "FAILURE-CANARY-" + uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            fake_keychain = temporary / "fake-security"
            fake_keychain.write_text(
                f"#!/bin/sh\nprintf '%s\\n' '{canary}'\n",
                encoding="utf-8",
            )
            fake_keychain.chmod(0o700)
            fake_docker = temporary / "docker"
            fake_docker.write_text(
                "#!/bin/sh\n"
                "/bin/cat >/dev/null\n"
                "printf '%s\\n' 'Container failed safely.' >&2\n"
                "exit 42\n",
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
                    "safe-failure",
                    "--credential-profile",
                    "DIRECT_PROD_READ",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(42, completed.returncode)
            self.assertNotIn(canary, completed.stdout)
            self.assertNotIn(canary, completed.stderr)


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
                        capability="SAFETY_CORE",
                        status="NOT_PROVEN",
                        evidence_type="SIMULATED",
                        acceptance_cases=("22", "22.1", "23", "23.1"),
                        evidence_paths=(str(evidence_file),),
                        limitations=("Local security fixtures only.",),
                    ),
                    CapabilityEvidence(
                        capability="TOOL_CONTRACT",
                        status="NOT_TESTED",
                        evidence_type="SIMULATED",
                        acceptance_cases=("24", "27"),
                        evidence_paths=(),
                        limitations=("This capability was not exercised.",),
                    ),
                ),
            )

            summary = load_json(destination)

            self.assertEqual("trust-boundary-evidence", summary["run_id"])
            self.assertEqual(
                {"22", "22.1", "23", "23.1", "24", "27"},
                {
                    case
                    for capability in summary["capabilities"]
                    for case in capability["acceptance_cases"]
                },
            )
            self.assertTrue(
                all(
                    capability["status"]
                    in {
                        "PROVEN",
                        "NOT_PROVEN",
                        "INCONCLUSIVE",
                        "NOT_TESTED",
                    }
                    for capability in summary["capabilities"]
                )
            )


if __name__ == "__main__":
    unittest.main()
