from __future__ import annotations

import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from mox_adv.audit import AuditIntegrityError, AuditSealedError, SQLiteAuditJournal
from mox_adv.internal_api.v1 import (
    AnalyticsAPI,
    AuditAPI,
    ConnectorsAPI,
    DecisionAPI,
    ExecutionAPI,
    NormalizationAPI,
    PolicyAPI,
)
from mox_adv.pipeline import run_fixture

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
POLICY = ROOT / "config" / "gate0-policy.json"
FIXTURE = ROOT / "fixtures" / "safe-bootstrap.json"


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class InternalAPITests(unittest.TestCase):
    def test_all_required_module_boundaries_are_versioned(self) -> None:
        boundaries = (
            ConnectorsAPI,
            NormalizationAPI,
            AnalyticsAPI,
            DecisionAPI,
            PolicyAPI,
            ExecutionAPI,
            AuditAPI,
        )

        self.assertTrue(
            all(item.__module__ == "mox_adv.internal_api.v1" for item in boundaries)
        )


class AuditJournalTests(unittest.TestCase):
    def test_transactional_chain_verifies_and_sealed_run_rejects_append(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "audit.sqlite3"
            journal = SQLiteAuditJournal(
                path=path,
                run_id="audit-run",
                schema_version="run-artifacts-v1",
                policy_version="policy-v1",
            )
            journal.append("run.started", {"mode": "SIMULATION"})
            final_event = journal.append("run.completed", {"status": "SUCCEEDED"})
            journal.seal()

            verification = journal.verify()

            self.assertEqual(2, verification.final_sequence)
            self.assertEqual(final_event.event_hash, verification.final_hash)
            with self.assertRaises(AuditSealedError):
                journal.append("run.changed", {})
            journal.close()

    def test_deleted_event_is_detected_after_seal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "audit.sqlite3"
            journal = SQLiteAuditJournal(
                path=path,
                run_id="audit-run",
                schema_version="run-artifacts-v1",
                policy_version="policy-v1",
            )
            journal.append("run.started", {})
            journal.append("run.completed", {})
            journal.seal()
            journal.close()

            import sqlite3

            with sqlite3.connect(path) as connection:
                connection.execute("DELETE FROM events WHERE sequence = 2")

            reopened = SQLiteAuditJournal.open(path)
            with self.assertRaises(AuditIntegrityError):
                reopened.verify()
            reopened.close()

    def test_deleted_unsealed_tail_cannot_be_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "audit.sqlite3"
            journal = SQLiteAuditJournal(
                path=path,
                run_id="audit-run",
                schema_version="run-artifacts-v1",
                policy_version="policy-v1",
            )
            journal.append("run.started", {})
            journal.append("stage.completed", {})

            import sqlite3

            with sqlite3.connect(path) as connection:
                connection.execute("DELETE FROM events WHERE sequence = 2")

            with self.assertRaises(AuditIntegrityError):
                journal.append("replacement.event", {})
            journal.close()

    def test_deleted_unsealed_tail_prevents_sealing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "audit.sqlite3"
            journal = SQLiteAuditJournal(
                path=path,
                run_id="audit-run",
                schema_version="run-artifacts-v1",
                policy_version="policy-v1",
            )
            journal.append("run.started", {})
            journal.append("stage.completed", {})

            import sqlite3

            with sqlite3.connect(path) as connection:
                connection.execute("DELETE FROM events WHERE sequence = 2")

            with self.assertRaises(AuditIntegrityError):
                journal.seal()
            journal.close()


class FixtureRunTests(unittest.TestCase):
    def test_success_creates_required_versioned_artifacts_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            runs_root = Path(temporary_directory) / "runs"
            started = time.monotonic()
            with (
                mock.patch.object(
                    socket,
                    "create_connection",
                    side_effect=AssertionError("network access is forbidden"),
                ),
                mock.patch.object(
                    socket,
                    "socket",
                    side_effect=AssertionError("network access is forbidden"),
                ),
            ):
                outcome = run_fixture(
                    run_id="safe-success",
                    runs_root=runs_root,
                    fixture_path=FIXTURE,
                    policy_path=POLICY,
                )
            elapsed = time.monotonic() - started

            self.assertEqual(0, outcome.exit_code)
            self.assertLess(elapsed, 300)
            run_directory = runs_root / "safe-success"
            self.assertEqual(
                {
                    "capability-evidence.json",
                    "events.jsonl",
                    "report.md",
                    "result.json",
                },
                {
                    path.name
                    for path in run_directory.iterdir()
                    if not path.name.startswith(".")
                },
            )
            result = json.loads(
                (run_directory / "result.json").read_text(encoding="utf-8")
            )
            self.assertEqual("run-artifacts-v1", result["schema_version"])
            self.assertEqual("mox-adv-gate0-2026-07-29", result["policy_version"])
            self.assertEqual("SUCCEEDED", result["status"])
            self.assertEqual("NO_CHANGE", result["execution_status"])
            self.assertFalse(result["external_write_sent"])
            self.assertEqual("SIMULATED", result["evidence_type"])
            self.assertEqual(
                "capability-evidence.json",
                result["capability_evidence_path"],
            )
            capability_evidence = json.loads(
                (run_directory / "capability-evidence.json").read_text(encoding="utf-8")
            )
            self.assertEqual(14, len(capability_evidence["capabilities"]))
            safety = next(
                item
                for item in capability_evidence["capabilities"]
                if item["capability"] == "SAFETY_CORE"
            )
            self.assertEqual("NOT_PROVEN", safety["status"])
            self.assertIn("23.1", safety["acceptance_cases"])
            self.assertIn("27", safety["acceptance_cases"])
            report = (run_directory / "report.md").read_text(encoding="utf-8")
            self.assertIn("SAFETY_CORE: status=NOT_PROVEN", report)
            self.assertIn("CLOSED_LOOP_CONTROL: status=NOT_TESTED", report)
            events = [
                json.loads(line)
                for line in (run_directory / "events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(
                list(range(1, len(events) + 1)), [event["sequence"] for event in events]
            )
            self.assertEqual(result["audit"]["final_hash"], events[-1]["event_hash"])

    def test_rejected_input_still_creates_safe_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            fixture = temporary_root / "rejected.json"
            canary = "SHOULD-NOT-LEAK-SECRET-CANARY"
            fixture.write_text(
                json.dumps({"schema_version": "wrong", "secret": canary}),
                encoding="utf-8",
            )

            outcome = run_fixture(
                run_id="safe-rejection",
                runs_root=temporary_root / "runs",
                fixture_path=fixture,
                policy_path=POLICY,
            )

            self.assertEqual(2, outcome.exit_code)
            run_directory = temporary_root / "runs" / "safe-rejection"
            artifacts = [
                run_directory / "result.json",
                run_directory / "report.md",
                run_directory / "events.jsonl",
            ]
            self.assertTrue(all(path.is_file() for path in artifacts))
            combined = "\n".join(path.read_text(encoding="utf-8") for path in artifacts)
            self.assertNotIn(canary, combined)
            self.assertNotIn("Traceback", combined)
            result = json.loads(artifacts[0].read_text(encoding="utf-8"))
            self.assertEqual("REJECTED", result["status"])
            self.assertEqual("BLOCKED", result["execution_status"])
            self.assertFalse(result["external_write_sent"])

    def test_invalid_run_id_creates_redacted_rejection_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            canary = "INVALID/SHOULD-NOT-LEAK-SECRET-CANARY"
            outcome = run_fixture(
                run_id=canary,
                runs_root=Path(temporary_directory) / "runs",
                fixture_path=FIXTURE,
                policy_path=POLICY,
            )

            self.assertEqual(2, outcome.exit_code)
            self.assertEqual("INVALID_RUN_ID", outcome.error_code)
            self.assertTrue(outcome.run_id.startswith("rejected-"))
            run_directory = Path(outcome.run_directory)
            artifacts = [
                run_directory / "result.json",
                run_directory / "report.md",
                run_directory / "events.jsonl",
            ]
            self.assertTrue(all(path.is_file() for path in artifacts))
            combined = "\n".join(path.read_text(encoding="utf-8") for path in artifacts)
            self.assertNotIn(canary, combined)
            self.assertNotIn("Traceback", combined)

    def test_ephemeral_credential_is_consumed_without_artifact_leak(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            canary = b"EPHEMERAL-SECRET-CANARY"
            outcome = run_fixture(
                run_id="credential-ingress",
                runs_root=Path(temporary_directory) / "runs",
                fixture_path=FIXTURE,
                policy_path=POLICY,
                credential_stream=io.BytesIO(canary + b"\n"),
                credential_profile="DIRECT_PROD_READ",
            )

            self.assertEqual(0, outcome.exit_code)
            run_directory = Path(outcome.run_directory)
            combined = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (
                    run_directory / "result.json",
                    run_directory / "report.md",
                    run_directory / "events.jsonl",
                )
            )
            self.assertNotIn(canary.decode("ascii"), combined)
            self.assertIn("EPHEMERAL_STDIN", combined)

    def test_repeated_run_id_does_not_change_completed_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            runs_root = Path(temporary_directory) / "runs"
            first = run_fixture(
                run_id="immutable-run",
                runs_root=runs_root,
                fixture_path=FIXTURE,
                policy_path=POLICY,
            )
            run_directory = runs_root / "immutable-run"
            before = {path.name: file_digest(path) for path in run_directory.iterdir()}

            second = run_fixture(
                run_id="immutable-run",
                runs_root=runs_root,
                fixture_path=FIXTURE,
                policy_path=POLICY,
            )
            after = {path.name: file_digest(path) for path in run_directory.iterdir()}

            self.assertEqual(0, first.exit_code)
            self.assertEqual(2, second.exit_code)
            self.assertEqual("RUN_ALREADY_EXISTS", second.error_code)
            self.assertEqual(before, after)

    def test_cli_returns_safe_error_without_traceback(self) -> None:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(SRC)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "mox_adv",
                "run-fixture",
                "--run-id",
                "cli-success",
                "--runs-dir",
                tempfile.mkdtemp(),
                "--fixture",
                str(FIXTURE),
                "--policy",
                str(POLICY),
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertNotIn("Traceback", completed.stdout + completed.stderr)
        self.assertIn("SUCCEEDED", completed.stdout)


if __name__ == "__main__":
    unittest.main()
