"""Versioned shared runtime for the three MOX-ADV editions."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mox-adv-core")
except PackageNotFoundError:
    __version__ = "1.0.0"
