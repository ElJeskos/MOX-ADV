"""Build the headless Direct edition from an explicit module allowlist."""

from pathlib import Path
from typing import List, Tuple

from setuptools import setup
from setuptools.command.build_py import build_py

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
PACKAGE_MODULES = {
    "mox_adv": {
        "__init__",
        "approval_execution",
        "audit",
        "autonomy_contracts",
        "autonomy_execution",
        "autonomy_policy",
        "canonical",
        "campaign_lifecycle",
        "campaign_vocabulary",
        "commands",
        "control_state",
        "contracts",
        "direct_action",
        "direct_action_common",
        "direct_action_execution",
        "direct_action_planning",
        "direct_action_runtime",
        "direct_analysis",
        "direct_campaign_creation",
        "direct_conclusions",
        "direct_impact",
        "direct_metrics",
        "direct_management",
        "direct_provider",
        "egress",
        "environment",
        "errors",
        "fake_write_adapter",
        "interrupt_state",
        "mandate_signing",
        "mandate_store",
        "impact",
        "module_analysis",
        "monitoring",
        "normalization",
        "proposal_store",
        "recommend_contracts",
        "recommend_projection",
        "trust_boundary",
        "write_window",
    },
    "mox_adv.module_api": {"__init__"},
    "mox_adv.module_api.v1": {
        "__init__",
        "adapters",
        "campaign_creation_contracts",
        "contract_validation",
        "contracts",
        "decision_records",
        "direct_action_contracts",
        "goal_lifecycle_contracts",
        "impact_contracts",
        "provider_observations",
    },
    "mox_adv.modules": {"__init__", "_bound", "direct"},
}


class DirectBuildPy(build_py):
    """Copy only modules needed by the independently installable edition."""

    def find_package_modules(
        self,
        package: str,
        package_dir: str,
    ) -> List[Tuple[str, str, str]]:
        modules = super().find_package_modules(package, package_dir)
        allowed = PACKAGE_MODULES[package]
        return [module for module in modules if module[1] in allowed]


setup(
    name="mox-adv-direct",
    version="0.1.0",
    description="Headless standalone Yandex Direct integration module",
    python_requires=">=3.9",
    packages=list(PACKAGE_MODULES),
    package_dir={"": str(SOURCE_ROOT)},
    cmdclass={"build_py": DirectBuildPy},
)
