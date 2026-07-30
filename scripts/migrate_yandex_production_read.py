#!/usr/bin/env python3
"""Split the retired combined Yandex production-read configuration once."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import stat
import sys
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO

LEGACY_CONFIGURATION_FIELDS = {
    "organization_id",
    "paired_connection_id",
    "direct_connection_id",
    "metrika_connection_id",
    "account_id",
    "campaign_id",
    "counter_id",
    "goal_id",
    "trusted_change_author",
    "period_days",
    "baseline",
}
LEGACY_TEXT_FIELDS = (
    "organization_id",
    "paired_connection_id",
    "direct_connection_id",
    "metrika_connection_id",
    "account_id",
    "campaign_id",
    "counter_id",
    "goal_id",
    "trusted_change_author",
)
BASELINE_FIELDS = {
    "source_campaign",
    "impressions",
    "clicks",
    "cost_micros",
    "visits",
    "goal_visits",
}
BASELINE_COUNT_FIELDS = (
    "impressions",
    "clicks",
    "cost_micros",
    "visits",
    "goal_visits",
)
REQUIRED_ENVIRONMENT_NAMES = (
    "YANDEX_DIRECT_OAUTH_TOKEN",
    "YANDEX_DIRECT_CLIENT_LOGIN",
    "YANDEX_METRIKA_OAUTH_TOKEN",
)
TRANSACTION_SCHEMA_VERSION = "yandex-production-read-migration-v1"
TRANSACTION_MARKER_NAME = ".mox-adv-production-read-migration.json"
MIGRATION_LOCK_NAME = ".mox-adv-production-read-migration.lock"


class MigrationError(RuntimeError):
    """Describe a refusal without exposing configuration or credential values."""


def _reject_duplicate_keys(
    pairs: Iterable[tuple[str, Any]],
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise MigrationError(
                "Legacy production read JSON contains a duplicate field."
            )
        value[key] = item
    return value


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise MigrationError(field + " must be a non-empty string.")
    return value


def _nonnegative_count(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MigrationError(field + " must be a non-negative integer.")
    return value


def _load_legacy_configuration(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except MigrationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MigrationError(
            "Legacy production read JSON is unavailable or invalid."
        ) from error
    if not isinstance(value, dict) or set(value) != LEGACY_CONFIGURATION_FIELDS:
        raise MigrationError("Legacy production read JSON has unexpected fields.")
    parsed: dict[str, Any] = {
        field: _required_text(value[field], field) for field in LEGACY_TEXT_FIELDS
    }
    period_days = value["period_days"]
    if (
        isinstance(period_days, bool)
        or not isinstance(period_days, int)
        or period_days < 1
        or period_days > 90
    ):
        raise MigrationError("period_days must be between 1 and 90.")
    baseline = value["baseline"]
    if not isinstance(baseline, dict) or set(baseline) != BASELINE_FIELDS:
        raise MigrationError("baseline has unexpected fields.")
    parsed_baseline: dict[str, Any] = {
        "source_campaign": _required_text(
            baseline["source_campaign"],
            "baseline.source_campaign",
        )
    }
    for field in BASELINE_COUNT_FIELDS:
        parsed_baseline[field] = _nonnegative_count(
            baseline[field],
            "baseline." + field,
        )
    parsed["period_days"] = period_days
    parsed["baseline"] = parsed_baseline
    return parsed


def _load_legacy_environment(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise MigrationError(
            "Legacy environment file is unavailable or invalid."
        ) from error
    values: dict[str, str] = {}
    required_names = set(REQUIRED_ENVIRONMENT_NAMES)
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, raw_value = line.split("=", 1)
        name = name.strip()
        if name not in required_names:
            continue
        if name in values:
            raise MigrationError(
                "Legacy environment file contains a duplicate required name."
            )
        values[name] = raw_value.strip()
    missing = [name for name in REQUIRED_ENVIRONMENT_NAMES if not values.get(name)]
    if missing:
        raise MigrationError(
            "Legacy environment file is missing a required non-empty value: "
            + ", ".join(missing)
            + "."
        )
    return values


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _environment_bytes(
    values: Mapping[str, str],
    names: Iterable[str],
) -> bytes:
    return ("\n".join(name + "=" + values[name] for name in names) + "\n").encode(
        "utf-8"
    )


def _path_exists(path: Path) -> bool:
    return os.path.lexists(path)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _prepare_temporary_file(
    target: Path,
    content: bytes,
    mode: int,
    *,
    prefix: str = ".mox-adv-production-read-",
) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=prefix,
        dir=target.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        temporary_file = os.fdopen(descriptor, "wb")
        descriptor = -1
        with temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        if _path_exists(temporary_path):
            temporary_path.unlink()
        raise
    return temporary_path


def _transaction_digest(
    project_root: Path,
    outputs: Mapping[Path, tuple[bytes, int]],
) -> str:
    entries = [
        {
            "path": path.relative_to(project_root).as_posix(),
            "sha256": hashlib.sha256(content).hexdigest(),
            "mode": mode,
        }
        for path, (content, mode) in sorted(
            outputs.items(),
            key=lambda item: item[0].as_posix(),
        )
    ]
    canonical = json.dumps(
        entries,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _marker_bytes(transaction_digest: str) -> bytes:
    return _json_bytes(
        {
            "schema_version": TRANSACTION_SCHEMA_VERSION,
            "transaction_digest": transaction_digest,
        }
    )


def _read_marker(path: Path) -> str:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except MigrationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MigrationError("The migration transaction marker is invalid.") from error
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "transaction_digest",
    }:
        raise MigrationError("The migration transaction marker is invalid.")
    if value["schema_version"] != TRANSACTION_SCHEMA_VERSION:
        raise MigrationError("The migration transaction marker is unsupported.")
    digest = value["transaction_digest"]
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise MigrationError("The migration transaction marker is invalid.")
    return digest


def _claim_marker(path: Path, transaction_digest: str) -> None:
    temporary_path = _prepare_temporary_file(
        path,
        _marker_bytes(transaction_digest),
        0o600,
        prefix=".mox-adv-production-read-" + transaction_digest + "-",
    )
    try:
        os.link(temporary_path, path)
        _fsync_directory(path.parent)
    except FileExistsError as error:
        raise MigrationError(
            "Another migration transaction has already started."
        ) from error
    except OSError as error:
        raise MigrationError(
            "Migration could not create its transaction marker."
        ) from error
    finally:
        if _path_exists(temporary_path):
            temporary_path.unlink()


def _matches_expected_output(
    path: Path,
    content: bytes,
    mode: int,
) -> bool:
    try:
        return (
            not path.is_symlink()
            and path.is_file()
            and path.read_bytes() == content
            and stat.S_IMODE(path.stat().st_mode) == mode
        )
    except OSError:
        return False


def _verify_existing_transaction_outputs(
    outputs: Mapping[Path, tuple[bytes, int]],
) -> set[Path]:
    existing: set[Path] = set()
    mismatched: list[Path] = []
    for target, (content, mode) in outputs.items():
        if not _path_exists(target):
            continue
        existing.add(target)
        if not _matches_expected_output(target, content, mode):
            mismatched.append(target)
    if mismatched:
        raise MigrationError(
            "Migration recovery refused because an existing output does not "
            "match the recorded transaction: "
            + ", ".join(str(path) for path in mismatched)
            + "."
        )
    return existing


def _install_missing_outputs(
    outputs: Mapping[Path, tuple[bytes, int]],
    existing: set[Path],
    transaction_digest: str,
) -> list[Path]:
    temporary_paths: dict[Path, Path] = {}
    installed_paths: list[Path] = []
    try:
        for target, (content, mode) in outputs.items():
            if target in existing:
                continue
            temporary_paths[target] = _prepare_temporary_file(
                target,
                content,
                mode,
                prefix=(".mox-adv-production-read-" + transaction_digest + "-"),
            )
        for target, temporary_path in temporary_paths.items():
            os.link(temporary_path, target)
            installed_paths.append(target)
            temporary_path.unlink()
            _fsync_directory(target.parent)
    except Exception as error:
        for temporary_path in temporary_paths.values():
            if _path_exists(temporary_path):
                temporary_path.unlink()
        for installed_path in installed_paths:
            if _path_exists(installed_path):
                installed_path.unlink()
                _fsync_directory(installed_path.parent)
        if isinstance(error, MigrationError):
            raise
        raise MigrationError("Migration could not install all outputs.") from error
    return installed_paths


@contextmanager
def _migration_lock(project_root: Path) -> Iterator[BinaryIO]:
    path = project_root / MIGRATION_LOCK_NAME
    try:
        stream = path.open("a+b")
    except OSError as error:
        raise MigrationError("Migration could not acquire its lock.") from error
    acquired = False
    try:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError as error:
            raise MigrationError(
                "Another migration process is already running."
            ) from error
        yield stream
    finally:
        if acquired and _path_exists(path):
            try:
                locked = os.fstat(stream.fileno())
                current = os.lstat(path)
                if locked.st_dev == current.st_dev and locked.st_ino == current.st_ino:
                    path.unlink()
                    _fsync_directory(project_root)
            except OSError:
                pass
        stream.close()


def _validate_split_configurations(
    temporary_paths: Mapping[Path, Path],
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    source_root = str(repository_root / "src")
    inserted = source_root not in sys.path
    if inserted:
        sys.path.insert(0, source_root)
    try:
        from mox_adv.direct_production import DirectProductionReadSettingsV1
        from mox_adv.metrika_production import MetrikaProductionReadSettingsV1
        from mox_adv.paired_production import PairedProductionReadSettingsV1

        validators = {
            "paired-production-read.json": (PairedProductionReadSettingsV1.from_path),
            "direct-production-read.json": (DirectProductionReadSettingsV1.from_path),
            "metrika-production-read.json": (MetrikaProductionReadSettingsV1.from_path),
        }
        for target, temporary_path in temporary_paths.items():
            validator = validators.get(target.name)
            if validator is not None:
                validator(temporary_path)
    except (TypeError, ValueError) as error:
        raise MigrationError(
            "Generated split configuration failed current runtime validation."
        ) from error
    finally:
        if inserted:
            sys.path.remove(source_root)


def _validate_outputs(
    outputs: Mapping[Path, tuple[bytes, int]],
    transaction_digest: str,
) -> None:
    temporary_paths: dict[Path, Path] = {}
    try:
        for target, (content, mode) in outputs.items():
            if target.suffix == ".json":
                temporary_paths[target] = _prepare_temporary_file(
                    target,
                    content,
                    mode,
                    prefix=(".mox-adv-production-read-" + transaction_digest + "-"),
                )
        _validate_split_configurations(temporary_paths)
    finally:
        for temporary_path in temporary_paths.values():
            if _path_exists(temporary_path):
                temporary_path.unlink()


def _cleanup_transaction_temporaries(
    outputs: Mapping[Path, tuple[bytes, int]],
    transaction_digest: str,
) -> None:
    pattern = ".mox-adv-production-read-" + transaction_digest + "-*"
    expected = {(content, mode) for content, mode in outputs.values()}
    expected.add((_marker_bytes(transaction_digest), 0o600))
    for directory in {path.parent for path in outputs}:
        removed = False
        for path in directory.glob(pattern):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                candidate = (
                    path.read_bytes(),
                    stat.S_IMODE(path.stat().st_mode),
                )
                if candidate in expected:
                    path.unlink()
                    removed = True
            except OSError:
                continue
        if removed:
            _fsync_directory(directory)


def _run_transaction(
    project_root: Path,
    outputs: Mapping[Path, tuple[bytes, int]],
) -> None:
    marker_path = project_root / TRANSACTION_MARKER_NAME
    digest = _transaction_digest(project_root, outputs)
    _cleanup_transaction_temporaries(outputs, digest)
    if _path_exists(marker_path):
        if marker_path.is_symlink() or not marker_path.is_file():
            raise MigrationError(
                "The migration transaction marker is not a regular file."
            )
        if _read_marker(marker_path) != digest:
            raise MigrationError(
                "The migration transaction does not match the current legacy inputs."
            )
        existing = _verify_existing_transaction_outputs(outputs)
    else:
        existing_paths = [path for path in outputs if _path_exists(path)]
        if existing_paths:
            raise MigrationError(
                "Migration refused because an output already exists: "
                + ", ".join(str(path) for path in existing_paths)
                + "."
            )
        _claim_marker(marker_path, digest)
        existing = set()

    try:
        installed = _install_missing_outputs(outputs, existing, digest)
    except Exception:
        if not existing and _path_exists(marker_path):
            marker_path.unlink()
            _fsync_directory(project_root)
        raise
    try:
        verified = _verify_existing_transaction_outputs(outputs)
        if verified != set(outputs):
            raise MigrationError(
                "Migration transaction did not produce every expected output."
            )
    except Exception:
        for path in installed:
            if _path_exists(path):
                path.unlink()
                _fsync_directory(path.parent)
        raise
    _cleanup_transaction_temporaries(outputs, digest)
    marker_path.unlink()
    _fsync_directory(project_root)


def migrate(project_root: Path) -> None:
    if not project_root.is_dir():
        raise MigrationError("Project root must be an existing directory.")
    configuration_directory = project_root / "config"
    if not configuration_directory.is_dir():
        raise MigrationError("Project config directory must be an existing directory.")
    with _migration_lock(project_root):
        legacy_configuration_path = (
            configuration_directory / "yandex-production-read.json"
        )
        legacy_environment_path = project_root / ".env"

        configuration = _load_legacy_configuration(legacy_configuration_path)
        environment = _load_legacy_environment(legacy_environment_path)
        try:
            configuration_mode = stat.S_IMODE(legacy_configuration_path.stat().st_mode)
            environment_mode = stat.S_IMODE(legacy_environment_path.stat().st_mode)
        except OSError as error:
            raise MigrationError(
                "Legacy input permissions could not be read."
            ) from error

        paired_configuration = {
            "organization_id": configuration["organization_id"],
            "paired_connection_id": configuration["paired_connection_id"],
            "period_days": configuration["period_days"],
            "baseline": configuration["baseline"],
        }
        direct_configuration = {
            "connection_id": configuration["direct_connection_id"],
            "account_id": configuration["account_id"],
            "campaign_id": configuration["campaign_id"],
            "trusted_change_author": configuration["trusted_change_author"],
        }
        metrika_configuration = {
            "connection_id": configuration["metrika_connection_id"],
            "counter_id": configuration["counter_id"],
            "goal_id": configuration["goal_id"],
            "campaign_id": configuration["campaign_id"],
        }
        outputs = {
            configuration_directory / "paired-production-read.json": (
                _json_bytes(paired_configuration),
                configuration_mode,
            ),
            configuration_directory / "direct-production-read.json": (
                _json_bytes(direct_configuration),
                configuration_mode,
            ),
            configuration_directory / "metrika-production-read.json": (
                _json_bytes(metrika_configuration),
                configuration_mode,
            ),
            project_root / ".env.direct-read": (
                _environment_bytes(
                    environment,
                    (
                        "YANDEX_DIRECT_OAUTH_TOKEN",
                        "YANDEX_DIRECT_CLIENT_LOGIN",
                    ),
                ),
                environment_mode,
            ),
            project_root / ".env.metrika-read": (
                _environment_bytes(
                    environment,
                    ("YANDEX_METRIKA_OAUTH_TOKEN",),
                ),
                environment_mode,
            ),
        }
        transaction_digest = _transaction_digest(project_root, outputs)
        _cleanup_transaction_temporaries(outputs, transaction_digest)
        _validate_outputs(outputs, transaction_digest)
        _run_transaction(project_root, outputs)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Split config/yandex-production-read.json and .env into the "
            "provider-scoped production read files without deleting inputs."
        )
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project root containing config/yandex-production-read.json.",
    )
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        migrate(arguments.project_root.expanduser().resolve())
    except MigrationError as error:
        print("Migration refused: " + str(error), file=sys.stderr)
        return 2
    print("Created split production read configuration and environment files.")
    print("The legacy inputs were kept unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
