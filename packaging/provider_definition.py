"""Shared build definition for independently installable provider editions."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from release import exact_core_requirement, release_version
from setuptools import setup
from setuptools.command.build_py import build_py


def setup_provider_edition(
    *,
    repository_root: Path,
    distribution: str,
    description: str,
    console_script: str,
    package_modules: Mapping[str, set[str]],
) -> None:
    """Build one provider wheel from an explicit module ownership map."""

    class ProviderBuildPy(build_py):
        """Copy only files owned by this provider edition."""

        def find_package_modules(
            self,
            package: str,
            package_dir: str,
        ) -> list[tuple[str, str, str]]:
            modules = super().find_package_modules(  # type: ignore[no-untyped-call]
                package,
                package_dir,
            )
            allowed = package_modules[package]
            return [module for module in modules if module[1] in allowed]

    setup(
        name=distribution,
        version=release_version(),
        description=description,
        python_requires=">=3.9",
        install_requires=[exact_core_requirement()],
        entry_points={"console_scripts": [console_script]},
        packages=list(package_modules),
        package_dir={"": str(repository_root / "src")},
        cmdclass={"build_py": ProviderBuildPy},
    )


__all__ = ["setup_provider_edition"]
