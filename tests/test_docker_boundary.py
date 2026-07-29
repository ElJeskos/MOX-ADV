from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "mox-adv-host"


class DockerBoundaryTests(unittest.TestCase):
    def test_printed_docker_command_denies_network_and_escalation(self) -> None:
        completed = subprocess.run(
            [
                str(LAUNCHER),
                "print-run-command",
                "--run-id",
                "docker-safe",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("--network=none", completed.stdout)
        self.assertIn("--read-only", completed.stdout)
        self.assertIn("--cap-drop=ALL", completed.stdout)
        self.assertIn("no-new-privileges", completed.stdout)
        self.assertNotIn("Keychain", completed.stdout)
        self.assertNotIn("security find-generic-password", completed.stdout)

    @unittest.skipUnless(
        os.environ.get("MOX_ADV_RUN_DOCKER_TESTS") == "1",
        "set MOX_ADV_RUN_DOCKER_TESTS=1 for the real Docker smoke test",
    )
    def test_real_hardened_docker_run_uses_fake_keychain_stdin(self) -> None:
        if shutil.which("docker") is None:
            self.skipTest("Docker is unavailable")
        run_id = "docker-integration-" + uuid.uuid4().hex[:12]
        run_directory = ROOT / "runs" / run_id
        canary = "DOCKER-EPHEMERAL-SECRET-CANARY"
        with tempfile.TemporaryDirectory() as temporary_directory:
            fake_security = Path(temporary_directory) / "fake-security"
            fake_security.write_text(
                "#!/bin/sh\nprintf '%s\\n' '" + canary + "'\n",
                encoding="utf-8",
            )
            fake_security.chmod(0o700)
            environment = dict(os.environ)
            environment["MOX_ADV_KEYCHAIN_COMMAND"] = str(fake_security)

            printed = subprocess.run(
                [
                    str(LAUNCHER),
                    "print-run-command",
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
            self.assertEqual(0, printed.returncode, printed.stderr)
            self.assertIn("--network=none", printed.stdout)
            self.assertIn("--read-only", printed.stdout)
            self.assertIn("--cap-drop=ALL", printed.stdout)
            self.assertIn("no-new-privileges", printed.stdout)
            self.assertIn("--credential-stdin", printed.stdout)
            self.assertNotIn(canary, printed.stdout)

            started = time.monotonic()
            built = subprocess.run(
                [str(LAUNCHER), "build"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            self.assertEqual(0, built.returncode, built.stderr)
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
                timeout=300,
                check=False,
            )
            elapsed = time.monotonic() - started

        try:
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertLess(elapsed, 300)
            artifacts = [
                run_directory / "result.json",
                run_directory / "report.md",
                run_directory / "events.jsonl",
            ]
            self.assertTrue(all(path.is_file() for path in artifacts))
            result = json.loads(artifacts[0].read_text(encoding="utf-8"))
            self.assertEqual("SUCCEEDED", result["status"])
            self.assertFalse(result["external_write_sent"])
            combined = (
                completed.stdout
                + completed.stderr
                + "\n".join(path.read_text(encoding="utf-8") for path in artifacts)
            )
            self.assertNotIn(canary, combined)
        finally:
            if run_directory.exists():
                shutil.rmtree(run_directory)


if __name__ == "__main__":
    unittest.main()
