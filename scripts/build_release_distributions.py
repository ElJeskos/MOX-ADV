#!/usr/bin/env python3
"""Build and validate one isolated, atomic MOX-ADV release wheelhouse."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from email.message import Message
from email.parser import BytesParser
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGING_ROOT = ROOT / "packaging"
sys.path.insert(0, str(PACKAGING_ROOT))

from release import release_version

ARTIFACTS = ("core", "direct", "metrika", "paired")
_AT_FDCWD = -100
_LINUX_RENAME_NOREPLACE = 1
_MACOS_RENAME_EXCL = 0x00000004


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the four artifacts behind three MOX-ADV editions."
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--work-root", type=Path)
    return parser


def _build(
    artifact: str,
    *,
    version: str,
    work: Path,
    destination: Path,
) -> Path:
    artifact_work = work / artifact
    egg_base = artifact_work / "egg-info"
    egg_base.mkdir(parents=True)
    environment = dict(os.environ)
    environment["MOX_ADV_RELEASE_VERSION"] = version
    completed = subprocess.run(
        [
            sys.executable,
            str(PACKAGING_ROOT / artifact / "setup.py"),
            "egg_info",
            "--egg-base",
            str(egg_base),
            "build",
            "--build-base",
            str(artifact_work / "build"),
            "bdist_wheel",
            "--dist-dir",
            str(destination),
            "--bdist-dir",
            str(artifact_work / "bdist"),
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            artifact + " wheel build failed:\n" + completed.stderr
        )
    normalized = artifact.replace("-", "_")
    matches = tuple(
        destination.glob(
            "mox_adv_" + normalized + "-" + version + "-*.whl"
        )
    )
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one {artifact} {version} wheel, found {matches!r}."
        )
    return matches[0]


def _wheel_details(wheel: Path) -> tuple[set[str], Message]:
    with zipfile.ZipFile(wheel) as archive:
        names = {
            name
            for name in archive.namelist()
            if ".dist-info/" not in name and not name.endswith("/")
        }
        metadata_name = next(
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        )
        metadata = BytesParser().parsebytes(archive.read(metadata_name))
    return names, metadata


def _normalized_requirement(value: str) -> str:
    return value.replace(" ", "").replace("(", "").replace(")", "")


def _validate(
    wheels: Mapping[str, Path],
    *,
    version: str,
) -> dict[str, Any]:
    details = {
        name: _wheel_details(wheel)
        for name, wheel in wheels.items()
    }
    for left, right in combinations(ARTIFACTS, 2):
        overlap = sorted(details[left][0] & details[right][0])
        if overlap:
            raise RuntimeError(
                f"{left} and {right} own the same installed paths: {overlap!r}"
            )
    requirements = {
        name: {
            _normalized_requirement(item)
            for item in metadata.get_all("Requires-Dist", [])
        }
        for name, (_, metadata) in details.items()
    }
    core = "mox-adv-core==" + version
    if requirements["core"]:
        raise RuntimeError("The internal core must have no runtime dependency.")
    if requirements["direct"] != {core}:
        raise RuntimeError("Direct must depend on the exact release core.")
    if requirements["metrika"] != {core}:
        raise RuntimeError("Metrika must depend on the exact release core.")
    expected_paired = {
        "mox-adv-direct==" + version,
        "mox-adv-metrika==" + version,
        "playwright==1.59.0",
    }
    if requirements["paired"] != expected_paired:
        raise RuntimeError(
            "Paired must depend on exact providers and its Dashboard runtime."
        )
    return {
        "schema_version": "mox-adv-release-manifest-v1",
        "release_version": version,
        "artifacts": [
            {
                "artifact": name,
                "distribution": "mox-adv-" + name,
                "filename": wheels[name].name,
                "sha256": hashlib.sha256(wheels[name].read_bytes()).hexdigest(),
                "user_facing": name != "core",
            }
            for name in ARTIFACTS
        ],
    }


def _publish_release(staging: Path, output: Path) -> None:
    """Atomically publish one directory without replacing any existing name."""

    library = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(staging)
    destination = os.fsencode(output)
    if sys.platform == "darwin":
        rename = library.renamex_np
        rename.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(source, destination, _MACOS_RENAME_EXCL)
    elif sys.platform.startswith("linux"):
        try:
            rename = library.renameat2
        except AttributeError as error:
            raise RuntimeError(
                "Atomic no-replace release publication requires renameat2."
            ) from error
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(
            _AT_FDCWD,
            source,
            _AT_FDCWD,
            destination,
            _LINUX_RENAME_NOREPLACE,
        )
    else:
        raise RuntimeError(
            "Atomic no-replace release publication supports macOS and Linux."
        )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise RuntimeError(
            "The release output directory must not already exist."
        )
    if error_number in {errno.ENOSYS, errno.ENOTSUP}:
        raise RuntimeError(
            "The filesystem does not support atomic no-replace publication."
        )
    raise OSError(
        error_number,
        os.strerror(error_number),
        os.fspath(output),
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    os.environ["MOX_ADV_RELEASE_VERSION"] = arguments.version
    version = release_version()
    output = arguments.output_dir.resolve()
    if output.exists():
        raise RuntimeError("The release output directory must not already exist.")
    output.parent.mkdir(parents=True, exist_ok=True)
    work_root = (
        output.parent
        if arguments.work_root is None
        else arguments.work_root.resolve()
    )
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".mox-adv-release-work-",
        dir=work_root,
    ) as work_name, tempfile.TemporaryDirectory(
        prefix=".mox-adv-release-output-",
        dir=output.parent,
    ) as staging_name:
        work = Path(work_name)
        staging = Path(staging_name)
        wheels = {
            artifact: _build(
                artifact,
                version=version,
                work=work,
                destination=staging,
            )
            for artifact in ARTIFACTS
        }
        manifest = _validate(wheels, version=version)
        manifest_path = staging / "release-manifest.json"
        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        _publish_release(staging, output)
    print(json.dumps(manifest, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
