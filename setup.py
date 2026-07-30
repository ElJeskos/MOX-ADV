"""Build the repository as the official paired release artifact."""

import sys
from pathlib import Path

PACKAGING_ROOT = Path(__file__).resolve().parent / "packaging"
sys.path.insert(0, str(PACKAGING_ROOT))

from paired_definition import setup_paired

setup_paired(Path(__file__).resolve().parent)
