"""Paired production composition over isolated Direct and Metrika readers."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from mox_adv.contracts import BaselineAggregate, TrustedAnalyticsScope
from mox_adv.direct_production import (
    DEFAULT_DIRECT_CONFIGURATION_PATH,
    DEFAULT_DIRECT_ENVIRONMENT_PATH,
    DirectProductionReadCompositionV1,
    DirectProductionReadSettingsV1,
)
from mox_adv.environment import ExecutionEnvironment
from mox_adv.metrika_production import (
    DEFAULT_METRIKA_CONFIGURATION_PATH,
    DEFAULT_METRIKA_ENVIRONMENT_PATH,
    MetrikaProductionReadCompositionV1,
    MetrikaProductionReadSettingsV1,
)
from mox_adv.paired_runtime import PairedConnectionRefsV1, PairedModuleRuntimeV1
from mox_adv.yandex_transport import (
    DIRECT_CAMPAIGN_STATE_READ,
    DIRECT_REPORTS_READ,
    METRIKA_REPORT_READ,
    HttpClient,
)
from mox_adv.yandex_transport import (
    nonnegative_count as _count,
)
from mox_adv.yandex_transport import (
    required_text as _text,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PAIRED_CONFIGURATION_PATH = (
    ROOT / "config" / "paired-production-read.json"
)

@dataclass(frozen=True)
class PairedProductionReadSettingsV1:
    organization_id: str
    paired_connection_id: str
    period_days: int
    baseline: BaselineAggregate

    @classmethod
    def from_path(cls, path: Path) -> PairedProductionReadSettingsV1:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(
                "Paired production read configuration is unavailable."
            ) from error
        if not isinstance(value, dict) or set(value) != {
            "organization_id",
            "paired_connection_id",
            "period_days",
            "baseline",
        }:
            raise ValueError(
                "Paired production read configuration has unexpected fields."
            )
        period_days = value["period_days"]
        if (
            isinstance(period_days, bool)
            or not isinstance(period_days, int)
            or period_days < 1
            or period_days > 90
        ):
            raise ValueError("period_days must be between 1 and 90.")
        baseline = value["baseline"]
        expected_baseline = {
            "source_campaign",
            "impressions",
            "clicks",
            "cost_micros",
            "visits",
            "goal_visits",
        }
        if not isinstance(baseline, dict) or set(baseline) != expected_baseline:
            raise ValueError("baseline has unexpected fields.")
        return cls(
            organization_id=_text(
                value["organization_id"],
                "organization_id",
            ),
            paired_connection_id=_text(
                value["paired_connection_id"],
                "paired_connection_id",
            ),
            period_days=period_days,
            baseline=BaselineAggregate(
                source_campaign=_text(
                    baseline["source_campaign"],
                    "baseline.source_campaign",
                ),
                impressions=_count(
                    baseline["impressions"],
                    "baseline.impressions",
                ),
                clicks=_count(baseline["clicks"], "baseline.clicks"),
                cost_micros=_count(
                    baseline["cost_micros"],
                    "baseline.cost_micros",
                ),
                visits=_count(baseline["visits"], "baseline.visits"),
                goal_visits=_count(
                    baseline["goal_visits"],
                    "baseline.goal_visits",
                ),
            ),
        )


@dataclass(frozen=True)
class LinkedProductionReadContextV1:
    paired: PairedProductionReadSettingsV1
    direct: DirectProductionReadSettingsV1
    metrika: MetrikaProductionReadSettingsV1

    def __post_init__(self) -> None:
        if self.direct.campaign_id != self.metrika.campaign_id:
            raise ValueError(
                "Paired Direct and Metrika configurations must link one campaign."
            )

    @property
    def trusted_scope(self) -> TrustedAnalyticsScope:
        return TrustedAnalyticsScope(
            organization=self.paired.organization_id,
            connection=self.paired.paired_connection_id,
            account=self.direct.account_id,
            campaign=self.direct.campaign_id,
            counter=self.metrika.counter_id,
            goal=self.metrika.goal_id,
            baseline_campaign=self.paired.baseline.source_campaign,
        )

    @property
    def connection_refs(self) -> PairedConnectionRefsV1:
        return PairedConnectionRefsV1(
            direct=self.direct.connection_id,
            metrika=self.metrika.connection_id,
        )


class PairedYandexProductionReaderV1:
    """Compose the two production read modules for the existing Dashboard."""

    def __init__(
        self,
        *,
        paired_configuration_path: Path = DEFAULT_PAIRED_CONFIGURATION_PATH,
        direct_configuration_path: Path = DEFAULT_DIRECT_CONFIGURATION_PATH,
        metrika_configuration_path: Path = DEFAULT_METRIKA_CONFIGURATION_PATH,
        direct_environment_path: Path = DEFAULT_DIRECT_ENVIRONMENT_PATH,
        metrika_environment_path: Path = DEFAULT_METRIKA_ENVIRONMENT_PATH,
        direct_http_client: HttpClient | None = None,
        metrika_http_client: HttpClient | None = None,
        direct: DirectProductionReadCompositionV1 | None = None,
        metrika: MetrikaProductionReadCompositionV1 | None = None,
    ) -> None:
        self.paired_configuration_path = paired_configuration_path
        self._direct = direct or DirectProductionReadCompositionV1(
            configuration_path=direct_configuration_path,
            environment_path=direct_environment_path,
            http_client=direct_http_client,
        )
        self._metrika = metrika or MetrikaProductionReadCompositionV1(
            configuration_path=metrika_configuration_path,
            environment_path=metrika_environment_path,
            http_client=metrika_http_client,
        )
        self.last_records: tuple[Mapping[str, str], ...] = ()

    def readiness(self, policy: Mapping[str, Any]) -> dict[str, Any]:
        del policy
        configuration_ready = self._context_or_none() is not None
        checks = [
            {
                "id": "production_read_configuration",
                "label": "Конфигурация production read-only Яндекса доступна",
                "ready": configuration_ready,
            },
            *self._direct.credential_checks(),
            *self._metrika.credential_checks(),
        ]
        blockers = [item["label"] for item in checks if not item["ready"]]
        return {
            "ready": not blockers,
            "checks": checks,
            "blockers": blockers,
            "access": "READ_ONLY",
            "data_source": "YANDEX_PRODUCTION_API",
            "external_reads_enabled": True,
            "write_requests_allowed": False,
            "write_flow": "DISABLED",
        }

    def collect_snapshot(
        self,
        *,
        policy: Mapping[str, Any],
        observation_id: str,
        generated_at: datetime,
        progress_callback: Callable[[dict[str, str]], None] | None = None,
    ):
        context = self._context()
        self._progress(progress_callback, "direct", "RUNNING")
        runtime = PairedModuleRuntimeV1(
            direct=self._direct.adapter(clock=lambda: generated_at),
            metrika=self._metrika.adapter(clock=lambda: generated_at),
            environment=ExecutionEnvironment.PRODUCTION,
        )
        period_end = (generated_at.date() - timedelta(days=1)).isoformat()
        period_start = (
            generated_at.date() - timedelta(days=context.paired.period_days)
        ).isoformat()
        try:
            snapshot = runtime.collect_snapshot(
                policy=policy,
                observation_id=observation_id,
                generated_at=generated_at.isoformat(),
                period_start=period_start,
                period_end=period_end,
                trusted_scope=context.trusted_scope,
                connection_refs=context.connection_refs,
                baseline=context.paired.baseline,
                progress_callback=lambda step, status: self._progress(
                    progress_callback,
                    step,
                    status,
                ),
            )
        except Exception:
            self.last_records = ()
            raise
        self.last_records = tuple(
            endpoint.audit_record()
            for endpoint in (
                DIRECT_REPORTS_READ,
                DIRECT_CAMPAIGN_STATE_READ,
                METRIKA_REPORT_READ,
            )
        )
        return snapshot

    def _context(self) -> LinkedProductionReadContextV1:
        return LinkedProductionReadContextV1(
            paired=PairedProductionReadSettingsV1.from_path(
                self.paired_configuration_path
            ),
            direct=self._direct.settings(),
            metrika=self._metrika.settings(),
        )

    def _context_or_none(self) -> LinkedProductionReadContextV1 | None:
        try:
            return self._context()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _progress(
        callback: Callable[[dict[str, str]], None] | None,
        step: str,
        status: str,
    ) -> None:
        if callback is not None:
            callback({"step": step, "status": status})
