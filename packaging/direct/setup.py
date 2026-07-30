"""Build the headless Direct edition from an explicit module allowlist."""

import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

PACKAGING_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGING_ROOT))

from release import exact_core_requirement, release_version

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
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


class DirectBuildPy(build_py):
    """Copy only modules needed by the independently installable edition."""

    def find_package_modules(
        self,
        package: str,
        package_dir: str,
    ) -> list[tuple[str, str, str]]:
        modules = super().find_package_modules(package, package_dir)
        allowed = PACKAGE_MODULES[package]
        return [module for module in modules if module[1] in allowed]


setup(
    name="mox-adv-direct",
    version=release_version(),
    description="Headless standalone Yandex Direct integration module",
    python_requires=">=3.9",
    install_requires=[exact_core_requirement()],
    entry_points={
        "console_scripts": ["mox-adv-direct=mox_adv.direct_cli:main"],
    },
    packages=list(PACKAGE_MODULES),
    package_dir={"": str(SOURCE_ROOT)},
    cmdclass={"build_py": DirectBuildPy},
)
