"""Build the paired edition from its authoritative shared definition."""

import sys
from pathlib import Path

PACKAGING_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGING_ROOT))

from paired_definition import setup_paired

setup_paired(Path(__file__).resolve().parents[2])
