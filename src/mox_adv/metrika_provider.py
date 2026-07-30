"""Authorized reads and normalized evidence for standalone Metrika."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional, Protocol, Tuple

from mox_adv.contracts import MetrikaReportBlock, MetrikaReportReadQuery
from mox_adv.module_api.v1 import (
    MetricValueV1,
    ModuleProvenanceV1,
    ModuleRequestV1,
)


class AuthorizedMetrikaReadProviderV1(Protocol):
    """Resolve one stored connection and perform an authorized typed read."""

    def read_metrika_report(
        self,
        connection_id: str,
        query: MetrikaReportReadQuery,
    ) -> MetrikaReportBlock: ...


class MetrikaReportReaderV1(Protocol):
    """Read a typed report after connection authorization is complete."""

    def read_metrika_report(
        self,
        query: MetrikaReportReadQuery,
    ) -> MetrikaReportBlock: ...


class MetrikaReadAuthorizationError(ValueError):
    """The stored connection does not authorize the requested Metrika scope."""


class MetrikaProviderUnavailable(RuntimeError):
    """The authorized provider read failed without a usable typed response."""


class BoundMetrikaReadProviderV1:
    """Bind one stored connection to its allowlisted Metrika resources."""

    def __init__(
        self,
        *,
        connection_id: str,
        counter_id: str,
        goal_id: str,
        campaign_id: str,
        reader: MetrikaReportReaderV1,
    ) -> None:
        self._connection_id = connection_id
        self._counter_id = counter_id
        self._goal_id = goal_id
        self._campaign_id = campaign_id
        self._reader = reader

    def read_metrika_report(
        self,
        connection_id: str,
        query: MetrikaReportReadQuery,
    ) -> MetrikaReportBlock:
        if (
            connection_id != self._connection_id
            or query.counter != self._counter_id
            or query.goal != self._goal_id
            or query.campaign != self._campaign_id
        ):
            raise MetrikaReadAuthorizationError(
                "The stored connection does not authorize this Metrika scope."
            )
        return self._reader.read_metrika_report(query)


@dataclass(frozen=True)
class MetrikaObservationV1:
    visits: int
    goal_visits: int
    observed_at: datetime
    provenance: ModuleProvenanceV1


class MetrikaObservationReaderV1:
    """Select and validate customer evidence or an authorized provider read."""

    def __init__(
        self,
        provider_reader: Optional[AuthorizedMetrikaReadProviderV1],
    ) -> None:
        self._provider_reader = provider_reader

    def read(
        self,
        request: ModuleRequestV1,
        now: datetime,
    ) -> MetrikaObservationV1:
        if request.external_evidence is not None:
            return self._read_customer_evidence(request, now)
        return self._read_provider(request, now)

    def _read_customer_evidence(
        self,
        request: ModuleRequestV1,
        now: datetime,
    ) -> MetrikaObservationV1:
        assert request.external_evidence is not None
        visits, goal_visits = self._validated_metrics(request.external_evidence.metrics)
        observed_at = self._timestamp(
            request.external_evidence.observed_at,
            "external_evidence.observed_at",
        )
        watermark = self._timestamp(
            request.external_evidence.watermark,
            "external_evidence.watermark",
        )
        self._validate_provenance(observed_at, watermark, now)
        return MetrikaObservationV1(
            visits=visits,
            goal_visits=goal_visits,
            observed_at=observed_at,
            provenance=ModuleProvenanceV1(
                source_type="CUSTOMER_EVIDENCE",
                source=request.external_evidence.source,
                retrieved_at=request.external_evidence.observed_at,
                watermark=request.external_evidence.watermark,
                evidence_id=request.external_evidence.evidence_id,
            ),
        )

    def _read_provider(
        self,
        request: ModuleRequestV1,
        now: datetime,
    ) -> MetrikaObservationV1:
        assert self._provider_reader is not None
        campaign_id = request.scope.campaign_id
        if campaign_id is None:
            raise ValueError(
                "Provider-owned Metrika reads require a campaign identifier."
            )
        assert request.scope.counter_id is not None
        assert request.scope.goal_id is not None
        query = MetrikaReportReadQuery(
            counter=request.scope.counter_id,
            campaign=campaign_id,
            goal=request.scope.goal_id,
            period_start=request.period.start_date,
            period_end=request.period.end_date,
            attribution="automatic",
        )
        try:
            report = self._provider_reader.read_metrika_report(
                request.connection_ref.connection_id,
                query,
            )
        except MetrikaReadAuthorizationError:
            raise
        except Exception as error:
            raise MetrikaProviderUnavailable from error
        visits, goal_visits = self._validated_provider_report(report, request)
        retrieved_at = self._timestamp(
            report.retrieved_at,
            "provider_report.retrieved_at",
        )
        watermark = self._timestamp(
            report.watermark,
            "provider_report.watermark",
        )
        self._validate_provenance(retrieved_at, watermark, now)
        return MetrikaObservationV1(
            visits=visits,
            goal_visits=goal_visits,
            observed_at=retrieved_at,
            provenance=ModuleProvenanceV1(
                source_type="PROVIDER",
                source=report.source,
                retrieved_at=report.retrieved_at,
                watermark=report.watermark,
            ),
        )

    @classmethod
    def _validated_provider_report(
        cls,
        report: MetrikaReportBlock,
        request: ModuleRequestV1,
    ) -> Tuple[int, int]:
        if not isinstance(report, MetrikaReportBlock):
            raise ValueError("The provider response does not match MetrikaReportBlock.")
        if report.source != "METRIKA_REPORT":
            raise ValueError("The provider response source is unsupported.")
        if (
            report.period_start != request.period.start_date
            or report.period_end != request.period.end_date
            or report.timezone != request.period.timezone
            or report.attribution != "automatic"
        ):
            raise ValueError(
                "The provider response period, timezone, or attribution "
                "does not match the request."
            )
        start = cls._date(report.period_start, "provider_report.period_start")
        end = cls._date(report.period_end, "provider_report.period_end")
        expected_dates = tuple(
            start + timedelta(days=offset) for offset in range((end - start).days + 1)
        )
        actual_dates = tuple(
            cls._date(row.date, "provider_report.rows[].date") for row in report.rows
        )
        if tuple(sorted(actual_dates)) != expected_dates or len(
            set(actual_dates)
        ) != len(actual_dates):
            raise ValueError("The provider response must cover the closed daily grain.")
        visits = 0
        goal_visits = 0
        for row in report.rows:
            if (
                row.goal != request.scope.goal_id
                or row.campaign != request.scope.campaign_id
            ):
                raise ValueError(
                    "The provider response is outside the requested scope."
                )
            cls._validate_count(row.visits, "visits")
            cls._validate_count(row.goal_visits, "goal_visits")
            if row.goal_visits > row.visits:
                raise ValueError("Metrika goal visits exceed visits.")
            visits += row.visits
            goal_visits += row.goal_visits
        return visits, goal_visits

    @classmethod
    def _validated_metrics(
        cls,
        metrics: Tuple[MetricValueV1, ...],
    ) -> Tuple[int, int]:
        by_name: Dict[str, MetricValueV1] = {}
        for metric in metrics:
            if metric.name in by_name:
                raise ValueError("Metrika evidence contains a duplicate metric.")
            by_name[metric.name] = metric
        if set(by_name) != {"visits", "goal_visits"}:
            raise ValueError(
                "Metrika evidence must contain only visits and goal_visits."
            )
        values: Dict[str, int] = {}
        for name in ("visits", "goal_visits"):
            metric = by_name[name]
            if metric.unit != "COUNT":
                raise ValueError(name + " must use the COUNT unit.")
            values[name] = cls._validate_count(metric.value, name)
        if values["goal_visits"] > values["visits"]:
            raise ValueError("Metrika goal visits exceed visits.")
        return values["visits"], values["goal_visits"]

    @staticmethod
    def _validate_count(value: object, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(name + " must be a non-negative integer COUNT.")
        return value

    @staticmethod
    def _timestamp(value: str, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(field + " must be an ISO-8601 timestamp.") from error
        if parsed.tzinfo is None:
            raise ValueError(field + " must include a UTC offset.")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _date(value: str, field: str) -> date:
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise ValueError(field + " must be an ISO date.") from error

    @staticmethod
    def _validate_provenance(
        observed_at: datetime,
        watermark: datetime,
        now: datetime,
    ) -> None:
        if observed_at > now or watermark > observed_at:
            raise ValueError(
                "Evidence timestamps must satisfy watermark <= observed_at <= now."
            )
