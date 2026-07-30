"""Build the headless Metrika edition from an explicit module allowlist."""

from pathlib import Path
from typing import List, Tuple

from setuptools import setup
from setuptools.command.build_py import build_py

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
PACKAGE_MODULES = {
    "mox_adv": {
        "__init__",
        "commands",
        "contracts",
        "control_state",
        "environment",
        "goal_adapters",
        "goal_contracts",
        "goal_evidence",
        "goal_service",
        "goal_store",
        "interrupt_state",
        "metrika_analysis",
        "metrika_goal_lifecycle",
        "metrika_metrics",
        "metrika_provider",
        "module_analysis",
    },
    "mox_adv.module_api": {"__init__"},
    "mox_adv.module_api.v1": {
        "__init__",
        "adapters",
        "contracts",
        "decision_records",
        "goal_lifecycle_contracts",
    },
    "mox_adv.modules": {"__init__", "_bound", "metrika"},
}


class MetrikaBuildPy(build_py):
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
    name="mox-adv-metrika",
    version="0.1.0",
    description="Headless standalone Yandex Metrika integration module",
    python_requires=">=3.9",
    packages=list(PACKAGE_MODULES),
    package_dir={"": str(SOURCE_ROOT)},
    cmdclass={"build_py": MetrikaBuildPy},
)
