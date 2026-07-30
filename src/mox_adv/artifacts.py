"""Atomic immutable run workspace and required artifact writers."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

from mox_adv.contracts import RunResult
from mox_adv.errors import RunAlreadyExistsError

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class RunWorkspace:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def create(cls, runs_root: Path, run_id: str) -> "RunWorkspace":
        if not RUN_ID_PATTERN.fullmatch(run_id) or run_id in {".", ".."}:
            raise ValueError("The run identifier is invalid.")
        runs_root.mkdir(parents=True, exist_ok=True)
        path = runs_root / run_id
        try:
            path.mkdir()
        except FileExistsError as error:
            raise RunAlreadyExistsError(
                "The requested run identifier already exists."
            ) from error
        return cls(path)

    def write_json(self, name: str, value: Mapping[str, Any]) -> None:
        text = (
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        self._atomic_write(name, text)

    def write_text(self, name: str, text: str) -> None:
        self._atomic_write(name, text)

    def write_result(self, result: RunResult) -> None:
        self.write_json("result.json", result.as_dict())

    def _atomic_write(self, name: str, text: str) -> None:
        destination = self.path / name
        if destination.exists():
            raise FileExistsError("A run artifact is immutable once written.")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="." + name + ".",
            dir=str(self.path),
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, destination)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
