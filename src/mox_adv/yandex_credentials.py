"""Isolated Yandex credential resolution."""

from __future__ import annotations

from pathlib import Path
from typing import TextIO


class DotenvValue:
    """Resolve exactly one named secret without exposing sibling credentials."""

    def __init__(self, path: Path, name: str) -> None:
        self._path = path
        self._name = name

    def configured(self) -> bool:
        try:
            return bool(self._read())
        except (OSError, ValueError):
            return False

    def resolve(self) -> str:
        value = self._read()
        if not value:
            raise RuntimeError(self._name + " is not configured.")
        return value

    def _read(self) -> str:
        with self._path.open(encoding="utf-8") as stream:
            return self._read_from(stream)

    def _read_from(self, stream: TextIO) -> str:
        for raw_line in stream:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == self._name:
                return value.strip()
        return ""
