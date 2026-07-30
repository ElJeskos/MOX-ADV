"""Build the internal shared runtime without provider or Dashboard code."""

import shutil
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

PACKAGING_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGING_ROOT))

from release import release_version

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
PACKAGE_MODULES = {
    "mox_adv": {
        "__init__",
        "campaign_vocabulary",
        "commands",
        "contracts",
        "control_state",
        "environment",
        "impact",
        "interrupt_state",
        "module_analysis",
        "module_cli",
        "module_host",
        "recommend_contracts",
        "test_resource_validation",
        "yandex_credentials",
        "yandex_transport",
        "yandex_values",
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
        "replay_store",
    },
    "mox_adv.modules": {"__init__", "_bound"},
}


class CoreBuildPy(build_py):
    """Copy only files with one unambiguous internal owner."""

    def find_package_modules(
        self,
        package: str,
        package_dir: str,
    ) -> list[tuple[str, str, str]]:
        modules = super().find_package_modules(package, package_dir)
        allowed = PACKAGE_MODULES[package]
        return [module for module in modules if module[1] in allowed]

    def run(self) -> None:
        super().run()
        destination = Path(self.build_lib) / "mox_adv" / "openapi"
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            REPOSITORY_ROOT / "openapi" / "module-api-v1.openapi.json",
            destination / "module-api-v1.openapi.json",
        )


setup(
    name="mox-adv-core",
    version=release_version(),
    description="Internal versioned runtime for MOX-ADV provider editions",
    python_requires=">=3.9",
    packages=list(PACKAGE_MODULES),
    package_dir={"": str(SOURCE_ROOT)},
    cmdclass={"build_py": CoreBuildPy},
    package_data={"mox_adv": ["openapi/*.json"]},
)
