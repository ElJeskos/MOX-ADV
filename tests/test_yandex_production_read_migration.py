from __future__ import annotations

import json
import os
import runpy
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_COMMAND = ROOT / "scripts" / "migrate_yandex_production_read.py"
MIGRATION_NAMESPACE = runpy.run_path(str(MIGRATION_COMMAND))

LEGACY_CONFIGURATION = {
    "organization_id": "production-organization",
    "paired_connection_id": "production-paired",
    "direct_connection_id": "production-direct",
    "metrika_connection_id": "production-metrika",
    "account_id": "production-account",
    "campaign_id": "production-campaign",
    "counter_id": "production-counter",
    "goal_id": "production-goal",
    "trusted_change_author": "trusted-operator",
    "period_days": 7,
    "baseline": {
        "source_campaign": "production-baseline",
        "impressions": 8_000,
        "clicks": 180,
        "cost_micros": 4_000_000_000,
        "visits": 260,
        "goal_visits": 4,
    },
}

DIRECT_TOKEN = "direct-test-token-never-persist"
DIRECT_LOGIN = "direct-client-login"
METRIKA_TOKEN = "metrika-test-token-never-persist"


def prepare_legacy_inputs(project_root: Path) -> tuple[Path, Path]:
    configuration_directory = project_root / "config"
    configuration_directory.mkdir()
    configuration_path = configuration_directory / "yandex-production-read.json"
    configuration_path.write_text(
        json.dumps(
            LEGACY_CONFIGURATION,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    environment_path = project_root / ".env"
    environment_path.write_text(
        "\n".join(
            (
                "# Unrelated legacy settings remain in the source file.",
                "UNRELATED_SETTING=keep-in-legacy-only",
                "YANDEX_DIRECT_OAUTH_TOKEN=" + DIRECT_TOKEN,
                "YANDEX_DIRECT_CLIENT_LOGIN=" + DIRECT_LOGIN,
                "YANDEX_METRIKA_OAUTH_TOKEN=" + METRIKA_TOKEN,
            )
        )
        + "\n",
        encoding="utf-8",
    )
    environment_path.chmod(0o640)
    return configuration_path, environment_path


def run_migration(project_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(MIGRATION_COMMAND),
            "--project-root",
            str(project_root),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def assert_no_split_outputs(
    testcase: unittest.TestCase,
    project_root: Path,
) -> None:
    testcase.assertFalse(
        (project_root / "config" / "paired-production-read.json").exists()
    )
    testcase.assertFalse(
        (project_root / "config" / "direct-production-read.json").exists()
    )
    testcase.assertFalse(
        (project_root / "config" / "metrika-production-read.json").exists()
    )
    testcase.assertFalse((project_root / ".env.direct-read").exists())
    testcase.assertFalse((project_root / ".env.metrika-read").exists())


def split_output_paths(project_root: Path) -> tuple[Path, ...]:
    return (
        project_root / "config" / "paired-production-read.json",
        project_root / "config" / "direct-production-read.json",
        project_root / "config" / "metrika-production-read.json",
        project_root / ".env.direct-read",
        project_root / ".env.metrika-read",
    )


def interrupt_migration_after_first_output(project_root: Path) -> None:
    migrate = MIGRATION_NAMESPACE["migrate"]
    real_link = os.link
    link_count = 0

    def interrupt_after_first_output(
        source: Path,
        target: Path,
    ) -> None:
        nonlocal link_count
        link_count += 1
        if link_count == 3:
            raise KeyboardInterrupt
        real_link(source, target)

    with mock.patch.object(
        MIGRATION_NAMESPACE["os"],
        "link",
        side_effect=interrupt_after_first_output,
    ):
        migrate(project_root)


class YandexProductionReadMigrationTests(unittest.TestCase):
    def test_command_splits_legacy_inputs_losslessly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary)
            legacy_configuration, legacy_environment = prepare_legacy_inputs(
                project_root
            )
            legacy_configuration_bytes = legacy_configuration.read_bytes()
            legacy_environment_bytes = legacy_environment.read_bytes()

            completed = run_migration(project_root)

            self.assertEqual(0, completed.returncode, completed.stderr)
            paired = json.loads(
                (project_root / "config" / "paired-production-read.json").read_text(
                    encoding="utf-8"
                )
            )
            direct = json.loads(
                (project_root / "config" / "direct-production-read.json").read_text(
                    encoding="utf-8"
                )
            )
            metrika = json.loads(
                (project_root / "config" / "metrika-production-read.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                {
                    "organization_id": LEGACY_CONFIGURATION["organization_id"],
                    "paired_connection_id": LEGACY_CONFIGURATION[
                        "paired_connection_id"
                    ],
                    "period_days": LEGACY_CONFIGURATION["period_days"],
                    "baseline": LEGACY_CONFIGURATION["baseline"],
                },
                paired,
            )
            self.assertEqual(
                {
                    "connection_id": LEGACY_CONFIGURATION["direct_connection_id"],
                    "account_id": LEGACY_CONFIGURATION["account_id"],
                    "campaign_id": LEGACY_CONFIGURATION["campaign_id"],
                    "trusted_change_author": LEGACY_CONFIGURATION[
                        "trusted_change_author"
                    ],
                },
                direct,
            )
            self.assertEqual(
                {
                    "connection_id": LEGACY_CONFIGURATION["metrika_connection_id"],
                    "counter_id": LEGACY_CONFIGURATION["counter_id"],
                    "goal_id": LEGACY_CONFIGURATION["goal_id"],
                    "campaign_id": LEGACY_CONFIGURATION["campaign_id"],
                },
                metrika,
            )
            direct_environment = project_root / ".env.direct-read"
            metrika_environment = project_root / ".env.metrika-read"
            self.assertEqual(
                "\n".join(
                    (
                        "YANDEX_DIRECT_OAUTH_TOKEN=" + DIRECT_TOKEN,
                        "YANDEX_DIRECT_CLIENT_LOGIN=" + DIRECT_LOGIN,
                    )
                )
                + "\n",
                direct_environment.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "YANDEX_METRIKA_OAUTH_TOKEN=" + METRIKA_TOKEN + "\n",
                metrika_environment.read_text(encoding="utf-8"),
            )
            expected_mode = stat.S_IMODE(legacy_environment.stat().st_mode)
            self.assertEqual(
                expected_mode,
                stat.S_IMODE(direct_environment.stat().st_mode),
            )
            self.assertEqual(
                expected_mode,
                stat.S_IMODE(metrika_environment.stat().st_mode),
            )
            self.assertTrue(legacy_configuration.exists())
            self.assertTrue(legacy_environment.exists())
            self.assertEqual(
                legacy_configuration_bytes,
                legacy_configuration.read_bytes(),
            )
            self.assertEqual(
                legacy_environment_bytes,
                legacy_environment.read_bytes(),
            )
            marker = project_root / MIGRATION_NAMESPACE["TRANSACTION_MARKER_NAME"]
            self.assertTrue(marker.is_file())

            repeated = run_migration(project_root)

            self.assertEqual(0, repeated.returncode, repeated.stderr)
            self.assertTrue(marker.is_file())

    def test_command_refuses_any_existing_output_without_partial_writes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary)
            prepare_legacy_inputs(project_root)
            existing_output = project_root / ".env.metrika-read"
            existing_output.write_text("sentinel\n", encoding="utf-8")

            completed = run_migration(project_root)

            self.assertNotEqual(0, completed.returncode)
            self.assertEqual(
                "sentinel\n",
                existing_output.read_text(encoding="utf-8"),
            )
            existing_output.unlink()
            assert_no_split_outputs(self, project_root)

    def test_command_requires_every_nonempty_provider_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary)
            _, legacy_environment = prepare_legacy_inputs(project_root)
            legacy_environment.write_text(
                "\n".join(
                    (
                        "YANDEX_DIRECT_OAUTH_TOKEN=" + DIRECT_TOKEN,
                        "YANDEX_DIRECT_CLIENT_LOGIN=" + DIRECT_LOGIN,
                        "YANDEX_METRIKA_OAUTH_TOKEN=",
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            completed = run_migration(project_root)

            self.assertNotEqual(0, completed.returncode)
            self.assertNotIn(DIRECT_TOKEN, completed.stderr)
            self.assertNotIn(METRIKA_TOKEN, completed.stderr)
            assert_no_split_outputs(self, project_root)

    def test_command_rejects_duplicate_required_environment_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary)
            _, legacy_environment = prepare_legacy_inputs(project_root)
            with legacy_environment.open("a", encoding="utf-8") as environment:
                environment.write("YANDEX_DIRECT_CLIENT_LOGIN=ambiguous-login\n")

            completed = run_migration(project_root)

            self.assertNotEqual(0, completed.returncode)
            self.assertNotIn(DIRECT_TOKEN, completed.stderr)
            assert_no_split_outputs(self, project_root)

    def test_command_rejects_non_exact_legacy_schema_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary)
            legacy_configuration, _ = prepare_legacy_inputs(project_root)
            invalid_configuration = {
                **LEGACY_CONFIGURATION,
                "unexpected_runtime_fallback": True,
            }
            legacy_configuration.write_text(
                json.dumps(invalid_configuration),
                encoding="utf-8",
            )

            completed = run_migration(project_root)

            self.assertNotEqual(0, completed.returncode)
            assert_no_split_outputs(self, project_root)

    def test_command_rejects_duplicate_legacy_json_field(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary)
            legacy_configuration, _ = prepare_legacy_inputs(project_root)
            legacy_configuration.write_text(
                json.dumps(LEGACY_CONFIGURATION)[:-1] + ',"period_days":14}',
                encoding="utf-8",
            )

            completed = run_migration(project_root)

            self.assertNotEqual(0, completed.returncode)
            assert_no_split_outputs(self, project_root)

    def test_partial_install_failure_leaves_a_recoverable_transaction(
        self,
    ) -> None:
        run_transaction = MIGRATION_NAMESPACE["_run_transaction"]
        migration_error = MIGRATION_NAMESPACE["MigrationError"]
        marker_name = MIGRATION_NAMESPACE["TRANSACTION_MARKER_NAME"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outputs = {
                root / "first.json": (b"first\n", 0o600),
                root / "second.json": (b"second\n", 0o600),
                root / "third.json": (b"third\n", 0o600),
            }
            real_link = os.link
            link_count = 0

            def fail_second_link(source: Path, target: Path) -> None:
                nonlocal link_count
                link_count += 1
                if link_count == 3:
                    raise OSError("simulated install failure")
                real_link(source, target)

            with mock.patch.object(  # noqa: SIM117
                MIGRATION_NAMESPACE["os"],
                "link",
                side_effect=fail_second_link,
            ):
                with self.assertRaises(migration_error):
                    run_transaction(root, outputs)

            self.assertTrue((root / "first.json").is_file())
            self.assertFalse((root / "second.json").exists())
            self.assertFalse((root / "third.json").exists())
            self.assertTrue((root / marker_name).is_file())
            self.assertEqual(
                {marker_name},
                {path.name for path in root.glob(".mox-adv-production-read-*")},
            )

            run_transaction(root, outputs)

            self.assertTrue(all(path.is_file() for path in outputs))
            self.assertTrue((root / marker_name).is_file())

    def test_install_failure_preserves_concurrently_replaced_output(
        self,
    ) -> None:
        run_transaction = MIGRATION_NAMESPACE["_run_transaction"]
        migration_error = MIGRATION_NAMESPACE["MigrationError"]
        marker_name = MIGRATION_NAMESPACE["TRANSACTION_MARKER_NAME"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            replacement = root / "first.json"
            outputs = {
                replacement: (b"first\n", 0o600),
                root / "second.json": (b"second\n", 0o600),
                root / "third.json": (b"third\n", 0o600),
            }
            real_link = os.link
            link_count = 0

            def replace_first_then_fail_second(
                source: Path,
                target: Path,
            ) -> None:
                nonlocal link_count
                link_count += 1
                if link_count == 3:
                    replacement.unlink()
                    replacement.write_text(
                        "external-replacement\n",
                        encoding="utf-8",
                    )
                    raise OSError("simulated later install failure")
                real_link(source, target)

            with (
                mock.patch.object(
                    MIGRATION_NAMESPACE["os"],
                    "link",
                    side_effect=replace_first_then_fail_second,
                ),
                self.assertRaises(migration_error),
            ):
                run_transaction(root, outputs)

            self.assertEqual(
                "external-replacement\n",
                replacement.read_text(encoding="utf-8"),
            )
            self.assertTrue((root / marker_name).is_file())

    def test_verification_failure_preserves_concurrently_replaced_output(
        self,
    ) -> None:
        run_transaction = MIGRATION_NAMESPACE["_run_transaction"]
        migration_error = MIGRATION_NAMESPACE["MigrationError"]
        marker_name = MIGRATION_NAMESPACE["TRANSACTION_MARKER_NAME"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            replacement = root / "first.json"
            outputs = {
                replacement: (b"first\n", 0o600),
                root / "second.json": (b"second\n", 0o600),
            }

            def replace_before_verification(
                values: object,
            ) -> set[Path]:
                del values
                replacement.unlink()
                replacement.write_text(
                    "external-replacement\n",
                    encoding="utf-8",
                )
                raise migration_error("simulated verification failure")

            with (
                mock.patch.dict(
                    run_transaction.__globals__,
                    {
                        "_verify_existing_transaction_outputs": (
                            replace_before_verification
                        )
                    },
                ),
                self.assertRaises(migration_error),
            ):
                run_transaction(root, outputs)

            self.assertEqual(
                "external-replacement\n",
                replacement.read_text(encoding="utf-8"),
            )
            self.assertTrue((root / "second.json").is_file())
            self.assertTrue((root / marker_name).is_file())

    def test_interrupted_transaction_resumes_exactly_without_overwrite(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary)
            prepare_legacy_inputs(project_root)

            with self.assertRaises(KeyboardInterrupt):
                interrupt_migration_after_first_output(project_root)

            marker = project_root / MIGRATION_NAMESPACE["TRANSACTION_MARKER_NAME"]
            self.assertTrue(marker.is_file())
            self.assertEqual(
                1,
                sum(path.exists() for path in split_output_paths(project_root)),
            )

            completed = run_migration(project_root)

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue(
                all(path.is_file() for path in split_output_paths(project_root))
            )
            self.assertTrue(marker.is_file())
            self.assertEqual(
                {
                    MIGRATION_NAMESPACE["MIGRATION_LOCK_NAME"],
                    MIGRATION_NAMESPACE["TRANSACTION_MARKER_NAME"],
                },
                {path.name for path in project_root.glob(".mox-adv-production-read-*")},
            )
            self.assertEqual(
                [],
                list((project_root / "config").glob(".mox-adv-production-read-*")),
            )

    def test_recovery_refuses_mismatched_output_without_deleting_it(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary)
            prepare_legacy_inputs(project_root)

            with self.assertRaises(KeyboardInterrupt):
                interrupt_migration_after_first_output(project_root)

            existing = next(
                path for path in split_output_paths(project_root) if path.exists()
            )
            existing.write_text("unrelated-owner-content\n", encoding="utf-8")

            completed = run_migration(project_root)

            self.assertNotEqual(0, completed.returncode)
            self.assertEqual(
                "unrelated-owner-content\n",
                existing.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                [existing],
                [path for path in split_output_paths(project_root) if path.exists()],
            )

    def test_concurrent_migration_refuses_without_writes(self) -> None:
        migration_lock = MIGRATION_NAMESPACE["_migration_lock"]
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary)
            prepare_legacy_inputs(project_root)

            with migration_lock(project_root):
                completed = run_migration(project_root)

            self.assertNotEqual(0, completed.returncode)
            self.assertIn(
                "already running",
                completed.stderr,
            )
            assert_no_split_outputs(self, project_root)

    def test_temporary_write_failure_does_not_double_close_descriptor(
        self,
    ) -> None:
        prepare_temporary_file = MIGRATION_NAMESPACE["_prepare_temporary_file"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            with mock.patch.object(  # noqa: SIM117
                MIGRATION_NAMESPACE["os"],
                "fsync",
                side_effect=OSError("simulated fsync failure"),
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "simulated fsync failure",
                ):
                    prepare_temporary_file(
                        root / "output.json",
                        b"content\n",
                        0o600,
                    )

            self.assertEqual(
                [],
                list(root.glob(".mox-adv-production-read-*")),
            )


if __name__ == "__main__":
    unittest.main()
