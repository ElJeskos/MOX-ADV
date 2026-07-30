"""Installed command for the headless Direct edition."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from mox_adv.control_state import ControlRejected
from mox_adv.direct_production import DirectProductionReadCompositionV1
from mox_adv.direct_test_resources import (
    approve_direct_test_proposal_v1,
    build_direct_test_module_v1,
    direct_test_diagnostics_v1,
)
from mox_adv.module_cli import (
    ProviderEditionV1,
    prepare_state_directory_v1,
    provider_edition_main_v1,
)
from mox_adv.modules.direct import DirectModuleV1

DIRECT_EDITION_V1 = ProviderEditionV1(
    program="mox-adv-direct",
    edition="DIRECT_STANDALONE",
    distribution="mox-adv-direct",
    analysis_builder=lambda settings, decisions: DirectModuleV1(
        clock=lambda: datetime.now(timezone.utc),
        decision_records=decisions,
        environment=settings.environment,
    ),
    production_builder=lambda configuration, environment: (
        DirectProductionReadCompositionV1(
            configuration_path=configuration,
            environment_path=environment,
        )
    ),
    test_builder=build_direct_test_module_v1,
    test_diagnostic_builder=direct_test_diagnostics_v1,
)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "approve-test":
        try:
            return _approve_test(arguments[1:])
        except ControlRejected as error:
            print(str(error), file=sys.stderr)
            return 2
    return provider_edition_main_v1(arguments, DIRECT_EDITION_V1)


def _approve_test(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="mox-adv-direct approve-test")
    parser.add_argument(
        "--environment",
        required=True,
        choices=["TEST"],
    )
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--test-resources", required=True, type=Path)
    parser.add_argument("--proposal-id", required=True)
    parser.add_argument("--reason", required=True)
    arguments = parser.parse_args(argv)
    prepare_state_directory_v1(arguments.state_dir)
    approval_id = approve_direct_test_proposal_v1(
        state_dir=arguments.state_dir,
        resources_path=arguments.test_resources,
        proposal_id=arguments.proposal_id,
        reason=arguments.reason,
        now=datetime.now(timezone.utc),
    )
    print(approval_id)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
