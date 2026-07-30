"""Installed command for the headless Metrika edition."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from mox_adv.control_state import ControlRejected
from mox_adv.metrika_production import MetrikaProductionReadCompositionV1
from mox_adv.metrika_test_resources import (
    authorize_metrika_site_publish_v1,
    build_metrika_test_module_v1,
    metrika_test_diagnostics_v1,
)
from mox_adv.module_cli import (
    ProviderEditionV1,
    prepare_state_directory_v1,
    provider_edition_main_v1,
)
from mox_adv.modules.metrika import MetrikaModuleV1

METRIKA_EDITION_V1 = ProviderEditionV1(
    program="mox-adv-metrika",
    edition="METRIKA_STANDALONE",
    distribution="mox-adv-metrika",
    analysis_builder=lambda _settings, decisions: MetrikaModuleV1(
        clock=lambda: datetime.now(timezone.utc),
        decision_records=decisions,
    ),
    production_builder=lambda configuration, environment: (
        MetrikaProductionReadCompositionV1(
            configuration_path=configuration,
            environment_path=environment,
        )
    ),
    test_builder=build_metrika_test_module_v1,
    test_diagnostic_builder=metrika_test_diagnostics_v1,
)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "authorize-site-test":
        try:
            return _authorize_site_test(arguments[1:])
        except ControlRejected as error:
            print(str(error), file=sys.stderr)
            return 2
    return provider_edition_main_v1(arguments, METRIKA_EDITION_V1)


def _authorize_site_test(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="mox-adv-metrika authorize-site-test"
    )
    parser.add_argument(
        "--environment",
        required=True,
        choices=["TEST"],
    )
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--test-resources", required=True, type=Path)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--authority-id", required=True)
    arguments = parser.parse_args(argv)
    prepare_state_directory_v1(arguments.state_dir)
    authority_id = authorize_metrika_site_publish_v1(
        state_dir=arguments.state_dir,
        resources_path=arguments.test_resources,
        candidate_id=arguments.candidate_id,
        authority_id=arguments.authority_id,
        now=datetime.now(timezone.utc),
    )
    print(authority_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
