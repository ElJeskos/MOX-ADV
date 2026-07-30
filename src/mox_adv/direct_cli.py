"""Installed command for the headless Direct edition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mox_adv.direct_production import DirectProductionReadCompositionV1
from mox_adv.module_api.v1 import ModuleDecisionRecordStoreV1, ModuleV1
from mox_adv.module_cli import (
    StandaloneRuntimeSettingsV1,
    standalone_main_v1,
)
from mox_adv.modules.direct import DirectModuleV1


def _module(
    settings: StandaloneRuntimeSettingsV1,
    decisions: ModuleDecisionRecordStoreV1,
) -> ModuleV1:
    clock = lambda: datetime.now(timezone.utc)
    if settings.configuration_path is None:
        return DirectModuleV1(
            clock=clock,
            decision_records=decisions,
            environment=settings.environment,
        )
    assert settings.environment_path is not None
    return DirectProductionReadCompositionV1(
        configuration_path=settings.configuration_path,
        environment_path=settings.environment_path,
    ).module(clock=clock, decision_records=decisions)


def _diagnostics(
    settings: StandaloneRuntimeSettingsV1,
) -> Mapping[str, Any]:
    if settings.configuration_path is None:
        return {
            "mode": "CUSTOMER_EVIDENCE",
            "configuration_ready": True,
            "read_credentials": [],
        }
    assert settings.environment_path is not None
    composition = DirectProductionReadCompositionV1(
        configuration_path=settings.configuration_path,
        environment_path=settings.environment_path,
    )
    return {
        "mode": "PROVIDER_READ",
        "configuration_ready": composition.settings_or_none() is not None,
        "read_credentials": list(composition.credential_checks()),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    return standalone_main_v1(
        argv,
        program="mox-adv-direct",
        edition="DIRECT_STANDALONE",
        distribution="mox-adv-direct",
        module_builder=_module,
        diagnostic_builder=_diagnostics,
    )


if __name__ == "__main__":
    raise SystemExit(main())
