"""Resolve paired immutable runtime data in source and installed layouts."""

from __future__ import annotations

from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2]
PACKAGED_ROOT = Path(__file__).with_name("runtime_data")


def runtime_resource(*parts: str) -> Path:
    """Prefer immutable packaged data and fall back to the source checkout."""

    packaged = PACKAGED_ROOT.joinpath(*parts)
    if packaged.exists():
        return packaged
    return SOURCE_ROOT.joinpath(*parts)
