"""Authoritative paired build metadata used by both release entry points."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from release import exact_provider_requirements, release_version
from setuptools import setup
from setuptools.command.build_py import build_py

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


def setup_paired(repository_root: Path) -> None:
    """Invoke setuptools once from the shared paired release definition."""

    source_root = repository_root / "src"

    class PairedBuildPy(build_py):
        """Copy paired composition, UI, and its non-secret local fixtures."""

        def find_package_modules(
            self,
            package: str,
            package_dir: str,
        ) -> list[tuple[str, str, str]]:
            modules = super().find_package_modules(  # type: ignore[no-untyped-call]
                package,
                package_dir,
            )
            allowed = PACKAGE_MODULES[package]
            return [module for module in modules if module[1] in allowed]

        def run(self) -> None:
            super().run()
            runtime_data = Path(self.build_lib) / "mox_adv" / "runtime_data"
            shutil.copytree(
                repository_root / "config",
                runtime_data / "config",
            )
            shutil.copytree(
                repository_root / "fixtures",
                runtime_data / "fixtures",
            )

    setup(
        name="mox-adv-paired",
        version=release_version(),
        description="Paired Yandex Direct and Metrika edition with Dashboard",
        python_requires=">=3.9",
        install_requires=[
            *exact_provider_requirements(),
            "playwright==1.59.0",
        ],
        packages=list(PACKAGE_MODULES),
        package_dir={"": os.path.relpath(source_root, Path.cwd())},
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
