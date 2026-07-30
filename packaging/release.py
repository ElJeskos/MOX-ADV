"""One validated version for every artifact in a MOX-ADV release set."""

from __future__ import annotations

import os
import re

DEFAULT_RELEASE_VERSION = "1.0.0"
_RELEASE_VERSION = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
)


def release_version() -> str:
    """Return the build version shared by all exact release dependencies."""

    value = os.environ.get("MOX_ADV_RELEASE_VERSION", DEFAULT_RELEASE_VERSION)
    if _RELEASE_VERSION.fullmatch(value) is None:
        raise RuntimeError(
            "MOX_ADV_RELEASE_VERSION must be an exact major.minor.patch version."
        )
    return value


def exact_core_requirement() -> str:
    return "mox-adv-core==" + release_version()


def exact_provider_requirements() -> list[str]:
    version = release_version()
    return [
        "mox-adv-direct==" + version,
        "mox-adv-metrika==" + version,
    ]
