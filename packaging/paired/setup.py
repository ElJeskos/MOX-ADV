"""Build the paired edition from composition and Dashboard code only."""

from pathlib import Path
import shutil
import sys

from setuptools import setup
from setuptools.command.build_py import build_py

PACKAGING_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGING_ROOT))

from release import exact_provider_requirements, release_version  # noqa: E402


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
PACKAGE_MODULES = {
    "mox_adv": {
        "__main__",
        "analytics",
        "artifacts",
        "autonomy",
        "cli",
        "connectors",
        "decision",
        "e2e_browser",
        "e2e_evidence",
        "e2e_runner",
        "execution",
        "goal_lifecycle",
        "host_launcher",
        "model_provider",
        "observe",
        "paired_cycle",
        "paired_production",
        "paired_runtime",
        "pipeline",
        "policy",
        "recommend",
        "recommend_service",
        "runtime_resources",
        "ui_automation",
        "ui_control_plane",
        "ui_dashboard",
        "ui_evidence",
        "ui_server",
        "ui_service",
        "ui_workflows",
    },
    "mox_adv.internal_api": {"__init__"},
    "mox_adv.internal_api.v1": {"__init__"},
    "mox_adv.ui": {"__init__"},
}


class PairedBuildPy(build_py):
    """Copy paired composition, UI, and its non-secret local fixtures."""

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
        runtime_data = Path(self.build_lib) / "mox_adv" / "runtime_data"
        shutil.copytree(
            REPOSITORY_ROOT / "config",
            runtime_data / "config",
        )
        shutil.copytree(
            REPOSITORY_ROOT / "fixtures",
            runtime_data / "fixtures",
        )


setup(
    name="mox-adv-paired",
    version=release_version(),
    description="Paired Yandex Direct and Metrika edition with Dashboard",
    python_requires=">=3.9",
    install_requires=exact_provider_requirements(),
    packages=list(PACKAGE_MODULES),
    package_dir={"": str(SOURCE_ROOT)},
    cmdclass={"build_py": PairedBuildPy},
    package_data={
        "mox_adv": ["runtime_data/**/*"],
        "mox_adv.ui": ["*.css", "*.html", "*.js"],
    },
    entry_points={
        "console_scripts": [
            "mox-adv=mox_adv.cli:main",
            "mox-adv-paired=mox_adv.cli:main",
        ],
    },
)
