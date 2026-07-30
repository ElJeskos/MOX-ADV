"""Build the headless Metrika edition from an explicit module allowlist."""

import sys
from pathlib import Path

PACKAGING_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGING_ROOT))

from provider_definition import setup_provider_edition

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_MODULES = {
    "mox_adv": {
        "goal_adapters",
        "goal_contracts",
        "goal_evidence",
        "goal_service",
        "goal_store",
        "metrika_analysis",
        "metrika_cli",
        "metrika_goal_lifecycle",
        "metrika_metrics",
        "metrika_production",
        "metrika_provider",
        "metrika_test_resources",
    },
    "mox_adv.modules": {"metrika"},
}

setup_provider_edition(
    repository_root=REPOSITORY_ROOT,
    distribution="mox-adv-metrika",
    description="Headless standalone Yandex Metrika integration module",
    console_script="mox-adv-metrika=mox_adv.metrika_cli:main",
    package_modules=PACKAGE_MODULES,
)
