"""Authorized Direct reads and normalized customer-evidence validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional, Protocol, Tuple

from mox_adv.contracts import (
    DirectCampaignStateBlock,
    DirectCampaignStateReadQuery,
    DirectReportBlock,
    DirectReportRow,
    DirectReportsReadQuery,
)
from mox_adv.module_api.v1 import (
    MetricValueV1,
    ModuleProvenanceV1,
    ModuleRequestV1,
)


class DirectReadAuthorizationError(PermissionError):
    """Raised when a stored connection does not authorize the requested scope."""


class DirectProviderUnavailable(RuntimeError):
    """Raised when an authorized provider read cannot be completed."""


class DirectReportReaderV1(Protocol):
    def read_report(self, query: DirectReportsReadQuery) -> DirectReportBlock: ...


class DirectStateReaderV1(Protocol):
    def read_campaign_state(
        self,
        query: DirectCampaignStateReadQuery,
    ) -> DirectCampaignStateBlock: ...


class AuthorizedDirectReadProviderV1(Protocol):
    def read_direct_report(
        self,
        connection_id: str,
        query: DirectReportsReadQuery,
    ) -> DirectReportBlock: ...

    def read_direct_state(
        self,
        connection_id: str,
        query: DirectCampaignStateReadQuery,
    ) -> DirectCampaignStateBlock: ...

    def authorizes_change_author(
        self,
        connection_id: str,
        author: str,
    ) -> bool: ...


class BoundDirectReadProviderV1:
    """Bind typed readers to one stored connection, account, and campaign."""

    def __init__(
        self,
        *,
        connection_id: str,
        account_id: str,
        campaign_id: str,
        trusted_change_author: str,
        report_reader: DirectReportReaderV1,
        state_reader: DirectStateReaderV1,
    ) -> None:
        self._connection_id = connection_id
        self._account_id = account_id
        self._campaign_id = campaign_id
        self._trusted_change_author = trusted_change_author
        self._report_reader = report_reader
        self._state_reader = state_reader

    def read_direct_report(
        self,
        connection_id: str,
        query: DirectReportsReadQuery,
    ) -> DirectReportBlock:
        self._authorize(connection_id, query.account, query.campaign)
        return self._report_reader.read_report(query)

    def read_direct_state(
        self,
        connection_id: str,
        query: DirectCampaignStateReadQuery,
    ) -> DirectCampaignStateBlock:
        self._authorize(connection_id, query.account, query.campaign)
        return self._state_reader.read_campaign_state(query)

    def authorizes_change_author(
        self,
        connection_id: str,
        author: str,
    ) -> bool:
        if connection_id != self._connection_id:
            raise DirectReadAuthorizationError(
                "The stored connection does not authorize this Direct scope."
            )
        return author == self._trusted_change_author

    def _authorize(
        self,
        connection_id: str,
        account_id: str,
        campaign_id: str,
    ) -> None:
        if (
            connection_id != self._connection_id
            or account_id != self._account_id
            or campaign_id != self._campaign_id
        ):
            raise DirectReadAuthorizationError(
                "The stored connection does not authorize this Direct scope."
            )


@dataclass(frozen=True)
class DirectObservationV1:
    impressions: int
    clicks: int
    cost_micros: int
    campaign_state: str
    group_state: str
    ad_state: str
    strategy: str
    current_weekly_budget_micros: int
    budget_period_start: datetime
    budget_period_end: datetime
    current_search_bid_micros: int
    ad_variant: str
    object_config_version: str
    last_change_author: Optional[str]
    last_change_occurred_at: Optional[datetime]
    conversions: Optional[int]
    observed_at: datetime
    provenance: Tuple[ModuleProvenanceV1, ...]


@dataclass(frozen=True)
class DirectStateValuesV1:
    campaign_state: str
    group_state: str
    ad_state: str
    strategy: str
    current_weekly_budget_micros: int
    budget_period_start: datetime
    budget_period_end: datetime
    current_search_bid_micros: int
    ad_variant: str
    object_config_version: str
    last_change_author: str
    last_change_occurred_at: datetime


class DirectObservationReaderV1:
    """Select and validate normalized evidence or two authorized Direct reads."""

    _EXTERNAL_REQUIRED_UNITS = {
        "impressions": "COUNT",
        "clicks": "COUNT",
        "cost_micros": "MICROS_RUB",
        "campaign_state": "CODE",
        "group_state": "CODE",
        "ad_state": "CODE",
        "strategy": "CODE",
        "current_weekly_budget_micros": "MICROS_RUB",
        "current_search_bid_micros": "MICROS_RUB",
        "ad_variant": "CODE",
        "object_config_version": "CODE",
        "budget_period_start": "ISO_8601",
        "budget_period_end": "ISO_8601",
    }
    _EXTERNAL_OPTIONAL_UNITS = {"conversions": "COUNT"}

    def __init__(
        self,
        provider_reader: Optional[AuthorizedDirectReadProviderV1],
    ) -> None:
        self._provider_reader = provider_reader

    def read(
        self,
        request: ModuleRequestV1,
        now: datetime,
    ) -> DirectObservationV1:
        if request.external_evidence is not None:
            return self._read_customer_evidence(request, now)
        return self._read_provider(request, now)

    def _read_customer_evidence(
        self,
        request: ModuleRequestV1,
        now: datetime,
    ) -> DirectObservationV1:
        assert request.external_evidence is not None
        metrics = self._validated_external_metrics(
            request.external_evidence.metrics
        )
        observed_at = self._timestamp(
            request.external_evidence.observed_at,
            "external_evidence.observed_at",
        )
        watermark = self._timestamp(
            request.external_evidence.watermark,
            "external_evidence.watermark",
        )
        self._validate_provenance(observed_at, watermark, now)
        budget_start = self._timestamp(
            self._string(metrics["budget_period_start"], "budget_period_start"),
            "budget_period_start",
        )
        budget_end = self._timestamp(
            self._string(metrics["budget_period_end"], "budget_period_end"),
            "budget_period_end",
        )
        self._validate_budget_period(budget_start, budget_end, now)
        return DirectObservationV1(
            impressions=self._count(metrics["impressions"], "impressions"),
            clicks=self._count(metrics["clicks"], "clicks"),
            cost_micros=self._count(metrics["cost_micros"], "cost_micros"),
            campaign_state=self._string(
                metrics["campaign_state"], "campaign_state"
            ),
            group_state=self._string(metrics["group_state"], "group_state"),
            ad_state=self._string(metrics["ad_state"], "ad_state"),
            strategy=self._string(metrics["strategy"], "strategy"),
            current_weekly_budget_micros=self._positive_count(
                metrics["current_weekly_budget_micros"],
                "current_weekly_budget_micros",
            ),
            budget_period_start=budget_start,
            budget_period_end=budget_end,
            current_search_bid_micros=self._count(
                metrics["current_search_bid_micros"],
                "current_search_bid_micros",
            ),
            ad_variant=self._string(metrics["ad_variant"], "ad_variant"),
            object_config_version=self._string(
                metrics["object_config_version"],
                "object_config_version",
            ),
            last_change_author=None,
            last_change_occurred_at=None,
            conversions=(
                None
                if "conversions" not in metrics
                else self._count(metrics["conversions"], "conversions")
            ),
            observed_at=observed_at,
            provenance=(
                ModuleProvenanceV1(
                    source_type="CUSTOMER_EVIDENCE",
                    source=request.external_evidence.source,
                    retrieved_at=request.external_evidence.observed_at,
                    watermark=request.external_evidence.watermark,
                    evidence_id=request.external_evidence.evidence_id,
                ),
            ),
        )

    def _read_provider(
        self,
        request: ModuleRequestV1,
        now: datetime,
    ) -> DirectObservationV1:
        assert self._provider_reader is not None
        assert request.scope.account_id is not None
        assert request.scope.campaign_id is not None
        report_query = DirectReportsReadQuery(
            account=request.scope.account_id,
            campaign=request.scope.campaign_id,
            period_start=request.period.start_date,
            period_end=request.period.end_date,
            attribution="AUTO",
        )
        state_query = DirectCampaignStateReadQuery(
            account=request.scope.account_id,
            campaign=request.scope.campaign_id,
        )
        try:
            report = self._provider_reader.read_direct_report(
                request.connection_ref.connection_id,
                report_query,
            )
            state = self._provider_reader.read_direct_state(
                request.connection_ref.connection_id,
                state_query,
            )
        except DirectReadAuthorizationError:
            raise
        except Exception as error:
            raise DirectProviderUnavailable from error
        impressions, clicks, cost_micros = self._validated_report(
            report,
            request,
        )
        state_values = self._validated_state(state, request, now)
        try:
            authorized_change = self._provider_reader.authorizes_change_author(
                request.connection_ref.connection_id,
                state_values.last_change_author,
            )
        except DirectReadAuthorizationError:
            raise
        except Exception as error:
            raise DirectProviderUnavailable from error
        if not authorized_change:
            raise DirectReadAuthorizationError(
                "The provider state contains an unknown external change."
            )
        report_retrieved = self._timestamp(
            report.retrieved_at,
            "provider_report.retrieved_at",
        )
        report_watermark = self._timestamp(
            report.watermark,
            "provider_report.watermark",
        )
        state_retrieved = self._timestamp(
            state.retrieved_at,
            "provider_state.retrieved_at",
        )
        state_watermark = self._timestamp(
            state.watermark,
            "provider_state.watermark",
        )
        self._validate_provenance(report_retrieved, report_watermark, now)
        self._validate_provenance(state_retrieved, state_watermark, now)
        return DirectObservationV1(
            impressions=impressions,
            clicks=clicks,
            cost_micros=cost_micros,
            conversions=None,
            observed_at=min(report_retrieved, state_retrieved),
            provenance=(
                ModuleProvenanceV1(
                    source_type="PROVIDER",
                    source=report.source,
                    retrieved_at=report.retrieved_at,
                    watermark=report.watermark,
                ),
                ModuleProvenanceV1(
                    source_type="PROVIDER",
                    source=state.source,
                    retrieved_at=state.retrieved_at,
                    watermark=state.watermark,
                ),
            ),
            campaign_state=state_values.campaign_state,
            group_state=state_values.group_state,
            ad_state=state_values.ad_state,
            strategy=state_values.strategy,
            current_weekly_budget_micros=(
                state_values.current_weekly_budget_micros
            ),
            budget_period_start=state_values.budget_period_start,
            budget_period_end=state_values.budget_period_end,
            current_search_bid_micros=state_values.current_search_bid_micros,
            ad_variant=state_values.ad_variant,
            object_config_version=state_values.object_config_version,
            last_change_author=state_values.last_change_author,
            last_change_occurred_at=state_values.last_change_occurred_at,
        )

    @classmethod
    def _validated_external_metrics(
        cls,
        metrics: Tuple[MetricValueV1, ...],
    ) -> Dict[str, object]:
        by_name: Dict[str, MetricValueV1] = {}
        for metric in metrics:
            if metric.name in by_name:
                raise ValueError("Direct evidence contains a duplicate metric.")
            by_name[metric.name] = metric
        allowed = {
            **cls._EXTERNAL_REQUIRED_UNITS,
            **cls._EXTERNAL_OPTIONAL_UNITS,
        }
        unknown = set(by_name) - set(allowed)
        missing = set(cls._EXTERNAL_REQUIRED_UNITS) - set(by_name)
        if unknown:
            raise ValueError(
                "Direct evidence contains an unsupported metric: "
                + sorted(unknown)[0]
            )
        if missing:
            raise ValueError(
                "Direct evidence is missing metric: " + sorted(missing)[0]
            )
        for name, metric in by_name.items():
            if metric.unit != allowed[name]:
                raise ValueError(
                    name + " must use the " + allowed[name] + " unit."
                )
        values: Dict[str, object] = {
            name: metric.value for name, metric in by_name.items()
        }
        impressions = cls._count(values["impressions"], "impressions")
        clicks = cls._count(values["clicks"], "clicks")
        if clicks > impressions:
            raise ValueError("Direct clicks exceed impressions.")
        if "conversions" in values:
            conversions = cls._count(values["conversions"], "conversions")
            if conversions > clicks:
                raise ValueError("Direct conversions exceed clicks.")
        return values

    @classmethod
    def _validated_report(
        cls,
        report: DirectReportBlock,
        request: ModuleRequestV1,
    ) -> Tuple[int, int, int]:
        if not isinstance(report, DirectReportBlock):
            raise ValueError(
                "The provider response does not match DirectReportBlock."
            )
        if not isinstance(report.rows, tuple) or any(
            not isinstance(row, DirectReportRow) for row in report.rows
        ):
            raise ValueError("The provider response rows are malformed.")
        if report.source != "DIRECT_REPORTS":
            raise ValueError("The provider report source is unsupported.")
        if (
            report.period_start != request.period.start_date
            or report.period_end != request.period.end_date
            or report.timezone != request.period.timezone
            or report.attribution != "AUTO"
            or report.currency != "RUB"
        ):
            raise ValueError(
                "The provider report period, timezone, attribution, or "
                "currency does not match the request."
            )
        start = cls._date(report.period_start, "provider_report.period_start")
        end = cls._date(report.period_end, "provider_report.period_end")
        expected_dates = tuple(
            start + timedelta(days=offset)
            for offset in range((end - start).days + 1)
        )
        actual_dates = tuple(
            cls._date(row.date, "provider_report.rows[].date")
            for row in report.rows
        )
        if tuple(sorted(actual_dates)) != expected_dates or len(
            set(actual_dates)
        ) != len(actual_dates):
            raise ValueError(
                "The provider report must cover the closed daily grain."
            )
        impressions = 0
        clicks = 0
        cost_micros = 0
        for row in report.rows:
            if row.campaign != request.scope.campaign_id:
                raise ValueError(
                    "The provider report is outside the requested scope."
                )
            row_impressions = cls._count(row.impressions, "impressions")
            row_clicks = cls._count(row.clicks, "clicks")
            if row_clicks > row_impressions:
                raise ValueError("Direct clicks exceed impressions.")
            impressions += row_impressions
            clicks += row_clicks
            cost_micros += cls._count(row.cost_micros, "cost_micros")
        return impressions, clicks, cost_micros

    @classmethod
    def _validated_state(
        cls,
        state: DirectCampaignStateBlock,
        request: ModuleRequestV1,
        now: datetime,
    ) -> DirectStateValuesV1:
        if not isinstance(state, DirectCampaignStateBlock):
            raise ValueError(
                "The provider response does not match "
                "DirectCampaignStateBlock."
            )
        if state.source != "DIRECT_CAMPAIGN_STATE":
            raise ValueError("The provider state source is unsupported.")
        if state.campaign != request.scope.campaign_id:
            raise ValueError(
                "The provider state is outside the requested scope."
            )
        budget_start = cls._timestamp(
            state.budget_period_start,
            "provider_state.budget_period_start",
        )
        budget_end = cls._timestamp(
            state.budget_period_end,
            "provider_state.budget_period_end",
        )
        cls._validate_budget_period(budget_start, budget_end, now)
        last_change_occurred_at = cls._timestamp(
            state.last_change_occurred_at,
            "provider_state.last_change_occurred_at",
        )
        return DirectStateValuesV1(
            campaign_state=cls._string(
                state.campaign_state,
                "campaign_state",
            ),
            group_state=cls._string(state.group_state, "group_state"),
            ad_state=cls._string(state.ad_state, "ad_state"),
            strategy=cls._string(state.strategy, "strategy"),
            current_weekly_budget_micros=cls._positive_count(
                state.current_weekly_budget_micros,
                "current_weekly_budget_micros",
            ),
            budget_period_start=budget_start,
            budget_period_end=budget_end,
            current_search_bid_micros=cls._count(
                state.current_search_bid_micros,
                "current_search_bid_micros",
            ),
            ad_variant=cls._string(state.ad_variant, "ad_variant"),
            object_config_version=cls._string(
                state.object_config_version,
                "object_config_version",
            ),
            last_change_author=cls._string(
                state.last_change_author,
                "last_change_author",
            ),
            last_change_occurred_at=last_change_occurred_at,
        )

    @staticmethod
    def _count(value: object, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(name + " must be a non-negative integer.")
        return value

    @classmethod
    def _positive_count(cls, value: object, name: str) -> int:
        parsed = cls._count(value, name)
        if parsed == 0:
            raise ValueError("The current weekly budget must be positive.")
        return parsed

    @staticmethod
    def _string(value: object, name: str) -> str:
        if not isinstance(value, str) or not value or len(value) > 128:
            raise ValueError(name + " must be a non-empty string.")
        return value

    @staticmethod
    def _timestamp(value: str, field: str) -> datetime:
        if not isinstance(value, str):
            raise ValueError(field + " must be an ISO-8601 timestamp.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(field + " must be an ISO-8601 timestamp.") from error
        if parsed.tzinfo is None:
            raise ValueError(field + " must include a UTC offset.")
        if parsed.utcoffset() != timedelta(0):
            raise ValueError(field + " must use UTC.")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _date(value: str, field: str) -> date:
        if not isinstance(value, str):
            raise ValueError(field + " must be an ISO date.")
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise ValueError(field + " must be an ISO date.") from error

    @staticmethod
    def _validate_budget_period(
        start: datetime,
        end: datetime,
        now: datetime,
    ) -> None:
        if end - start != timedelta(days=7):
            raise ValueError("The weekly budget period must span seven days.")
        if start > now:
            raise ValueError("The weekly budget period has not started.")

    @staticmethod
    def _validate_provenance(
        retrieved_at: datetime,
        watermark: datetime,
        now: datetime,
    ) -> None:
        if retrieved_at > now or watermark > retrieved_at:
            raise ValueError(
                "Evidence timestamps must satisfy watermark <= retrieved_at <= now."
            )
