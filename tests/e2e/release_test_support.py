"""Shared offline clean-wheel preparation for release acceptance."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE_PACKAGES = ("core", "direct", "metrika", "paired")
RELEASE_DEPENDENCY_WHEELHOUSE_ENV = (
    "MOX_ADV_RELEASE_DEPENDENCY_WHEELHOUSE"
)
RELEASE_DEPENDENCY_REQUIREMENTS = ROOT / "requirements-release.txt"


def release_environment(**extra: str) -> dict[str, str]:
    environment = {
        name: value for name, value in os.environ.items() if name != "PYTHONPATH"
    }
    environment.update(extra)
    return environment


def build_wheel(
    setup_path: Path,
    destination: Path,
    *,
    version: str = "1.0.0",
) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    egg_base = destination / "egg-info"
    egg_base.mkdir()
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
        env=release_environment(MOX_ADV_RELEASE_VERSION=version),
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


def build_release_wheelhouse(
    root: Path,
    *,
    version: str,
    include_paired_dependencies: bool,
) -> tuple[Path, dict[str, Path]]:
    wheelhouse = root / "wheelhouse"
    wheelhouse.mkdir(exist_ok=True)
    wheels: dict[str, Path] = {}
    for package in RELEASE_PACKAGES:
        built = build_wheel(
            ROOT / "packaging" / package / "setup.py",
            root / "release-build" / version / package,
            version=version,
        )
        destination = wheelhouse / built.name
        built.replace(destination)
        wheels[package] = destination
    if include_paired_dependencies:
        copy_paired_dependency_wheels(wheelhouse)
    return wheelhouse, wheels


def copy_paired_dependency_wheels(wheelhouse: Path) -> None:
    source_value = os.environ.get(RELEASE_DEPENDENCY_WHEELHOUSE_ENV)
    if source_value is None:
        raise AssertionError(
            RELEASE_DEPENDENCY_WHEELHOUSE_ENV
            + " must point to the pre-downloaded exact release dependency wheelhouse."
        )
    source = Path(source_value)
    wheels = tuple(sorted(source.glob("*.whl")))
    if not source.is_dir() or not wheels:
        raise AssertionError("The offline release dependency wheelhouse is empty.")
    distributions = {_wheel_identity(wheel) for wheel in wheels}
    expected = _release_dependency_identities()
    if distributions != expected or len(distributions) != len(wheels):
        raise AssertionError(
            "The offline wheelhouse must exactly match requirements-release.txt; "
            f"expected {sorted(expected)!r}, found {sorted(distributions)!r}."
        )
    wheelhouse.mkdir(parents=True, exist_ok=True)
    for wheel in wheels:
        destination = wheelhouse / wheel.name
        if destination.exists():
            if destination.read_bytes() != wheel.read_bytes():
                raise AssertionError(
                    "Offline dependency wheel name collision: " + wheel.name
                )
            continue
        shutil.copy2(wheel, destination)


def create_virtual_environment(path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "venv", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)


def install_offline(
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
        env=release_environment(),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    assert_pip_check(environment)


def assert_pip_check(environment: Path) -> None:
    completed = subprocess.run(
        [str(environment / "bin" / "python"), "-m", "pip", "check"],
        env=release_environment(),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stdout + completed.stderr)


def _wheel_identity(wheel: Path) -> tuple[str, str]:
    with zipfile.ZipFile(wheel) as archive:
        metadata_path = next(
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        )
        metadata = BytesParser().parsebytes(archive.read(metadata_path))
    name = str(metadata["Name"]).lower().replace("_", "-").replace(".", "-")
    return name, str(metadata["Version"])


def _release_dependency_identities() -> set[tuple[str, str]]:
    identities: set[tuple[str, str]] = set()
    for line in RELEASE_DEPENDENCY_REQUIREMENTS.read_text(
        encoding="utf-8"
    ).splitlines():
        name, separator, version = line.partition("==")
        if (
            not separator
            or not name
            or not version
            or name != name.lower()
        ):
            raise AssertionError(
                "requirements-release.txt must contain exact normalized pins."
            )
        identity = (name, version)
        if identity in identities:
            raise AssertionError(
                "requirements-release.txt must not contain duplicate pins."
            )
        identities.add(identity)
    if not identities:
        raise AssertionError("requirements-release.txt must not be empty.")
    return identities


__all__ = [
    "RELEASE_DEPENDENCY_WHEELHOUSE_ENV",
    "RELEASE_PACKAGES",
    "assert_pip_check",
    "build_release_wheelhouse",
    "build_wheel",
    "copy_paired_dependency_wheels",
    "create_virtual_environment",
    "install_offline",
    "release_environment",
]
