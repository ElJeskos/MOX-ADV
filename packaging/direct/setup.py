"""Build the headless Direct edition from an explicit module allowlist."""

import sys
from pathlib import Path

PACKAGING_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGING_ROOT))

from provider_definition import setup_provider_edition

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_MODULES = {
    "mox_adv": {
        "approval_execution",
        "audit",
        "autonomy_contracts",
        "autonomy_execution",
        "autonomy_policy",
        "canonical",
        "campaign_lifecycle",
        "direct_action",
        "direct_action_common",
        "direct_action_execution",
        "direct_action_planning",
        "direct_action_runtime",
        "direct_analysis",
        "direct_campaign_creation",
        "direct_cli",
        "direct_conclusions",
        "direct_impact",
        "direct_metrics",
        "direct_management",
        "direct_production",
        "direct_provider",
        "direct_test_resources",
        "egress",
        "errors",
        "fake_write_adapter",
        "mandate_signing",
        "mandate_store",
        "monitoring",
        "normalization",
        "proposal_store",
        "recommend_projection",
        "trust_boundary",
        "write_window",
    },
    "mox_adv.modules": {"direct"},
}

setup_provider_edition(
    repository_root=REPOSITORY_ROOT,
    distribution="mox-adv-direct",
    description="Headless standalone Yandex Direct integration module",
    console_script="mox-adv-direct=mox_adv.direct_cli:main",
    package_modules=PACKAGE_MODULES,
)
