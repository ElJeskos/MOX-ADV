"""Build the headless Metrika edition from an explicit module allowlist."""

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


class MetrikaBuildPy(build_py):
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
    name="mox-adv-metrika",
    version=release_version(),
    description="Headless standalone Yandex Metrika integration module",
    python_requires=">=3.9",
    install_requires=[exact_core_requirement()],
    entry_points={
        "console_scripts": ["mox-adv-metrika=mox_adv.metrika_cli:main"],
    },
    packages=list(PACKAGE_MODULES),
    package_dir={"": str(SOURCE_ROOT)},
    cmdclass={"build_py": MetrikaBuildPy},
)
