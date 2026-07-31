"""Versioned read connectors and local fixture adapters."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Sequence, Set

from mox_adv.contracts import (
    ANALYTICS_FIXTURE_SCHEMA_VERSION,
    FIXTURE_SCHEMA_VERSION,
    AnalyticsPeriod,
    AnalyticsScope,
    BaselineAggregate,
    ConnectedAnalytics,
    ConnectedFixture,
    DirectCampaignStateBlock,
    DirectCampaignStateReadQuery,
    DirectReportBlock,
    DirectReportRow,
    DirectReportsReadQuery,
    FixtureRecord,
    MetrikaReportBlock,
    MetrikaReportReadQuery,
    MetrikaReportRow,
    ReadOnlyTransport,
    RunContext,
    VersionedReadRequest,
)
from mox_adv.errors import RunRejectedError


class FixtureConnectorV1:
    """Parse a closed-schema local fixture without using the network."""

    def read_fixture(
        self,
        context: RunContext,
        raw_fixture: Mapping[str, Any],
    ) -> ConnectedFixture:
        del context
        if set(raw_fixture) != {"schema_version", "fixture_id", "records"}:
            raise RunRejectedError(
                "FIXTURE_SCHEMA_REJECTED",
                "connectors",
                "The fixture does not match the approved closed schema.",
            )
        if raw_fixture.get("schema_version") != FIXTURE_SCHEMA_VERSION:
            raise RunRejectedError(
                "FIXTURE_SCHEMA_REJECTED",
                "connectors",
                "The fixture schema version is not supported.",
            )
        fixture_id = raw_fixture.get("fixture_id")
        records = raw_fixture.get("records")
        if not isinstance(fixture_id, str) or not fixture_id or len(fixture_id) > 128:
            raise RunRejectedError(
                "FIXTURE_SCHEMA_REJECTED",
                "connectors",
                "The fixture identifier is invalid.",
            )
        if not isinstance(records, list) or not 1 <= len(records) <= 1000:
            raise RunRejectedError(
                "FIXTURE_SCHEMA_REJECTED",
                "connectors",
                "The fixture record count is invalid.",
            )
        parsed = tuple(self._parse_record(record) for record in records)
        return ConnectedFixture(fixture_id=fixture_id, records=parsed)

    @staticmethod
    def _parse_record(value: Any) -> FixtureRecord:
        if not isinstance(value, dict) or set(value) != {
            "impressions",
            "clicks",
            "conversions",
            "cost_rub",
        }:
            raise RunRejectedError(
                "FIXTURE_SCHEMA_REJECTED",
                "connectors",
                "A fixture record does not match the approved schema.",
            )
        integer_fields = {}
        for field_name in ("impressions", "clicks", "conversions"):
            field_value = value[field_name]
            if (
                isinstance(field_value, bool)
                or not isinstance(field_value, int)
                or field_value < 0
            ):
                raise RunRejectedError(
                    "FIXTURE_SCHEMA_REJECTED",
                    "connectors",
                    "A fixture metric is invalid.",
                )
            integer_fields[field_name] = field_value
        if integer_fields["clicks"] > integer_fields["impressions"]:
            raise RunRejectedError(
                "FIXTURE_SCHEMA_REJECTED",
                "connectors",
                "Fixture clicks exceed impressions.",
            )
        if integer_fields["conversions"] > integer_fields["clicks"]:
            raise RunRejectedError(
                "FIXTURE_SCHEMA_REJECTED",
                "connectors",
                "Fixture conversions exceed clicks.",
            )
        try:
            cost = Decimal(str(value["cost_rub"]))
        except (InvalidOperation, ValueError):
            raise RunRejectedError(
                "FIXTURE_SCHEMA_REJECTED",
                "connectors",
                "The fixture cost is invalid.",
            )
        if not cost.is_finite() or cost < 0:
            raise RunRejectedError(
                "FIXTURE_SCHEMA_REJECTED",
                "connectors",
                "The fixture cost is invalid.",
            )
        return FixtureRecord(cost_rub=cost, **integer_fields)


class DirectReportsReadConnectorV1:
    """Read Direct report data through the read-only transport boundary."""

    def __init__(self, transport: ReadOnlyTransport) -> None:
        self._transport = transport

    def read_report(self, query: DirectReportsReadQuery) -> DirectReportBlock:
        raw = self._transport.read(
            VersionedReadRequest(
                system="DIRECT_REPORTS",
                host="api.direct.yandex.com",
                path="/json/v501/reports",
                version="v501",
                service="Reports",
                method="get",
                http_verb="POST",
                payload=asdict(query),
            )
        )
        if not isinstance(raw, DirectReportBlock) or raw.source != "DIRECT_REPORTS":
            raise _reject_read_response("Direct Reports")
        return raw


class DirectCampaignStateReadConnectorV1:
    """Read Direct campaign state without exposing management operations."""

    def __init__(self, transport: ReadOnlyTransport) -> None:
        self._transport = transport

    def read_campaign_state(
        self,
        query: DirectCampaignStateReadQuery,
    ) -> DirectCampaignStateBlock:
        raw = self._transport.read(
            VersionedReadRequest(
                system="DIRECT",
                host="api.direct.yandex.com",
                path="/json/v501/campaigns",
                version="v501",
                service="Campaigns",
                method="get",
                http_verb="POST",
                payload=asdict(query),
            )
        )
        if (
            not isinstance(raw, DirectCampaignStateBlock)
            or raw.source != "DIRECT_CAMPAIGN_STATE"
        ):
            raise _reject_read_response("Direct campaign state")
        return raw


class MetrikaReportReadConnectorV1:
    """Read Metrika report data through the read-only transport boundary."""

    def __init__(self, transport: ReadOnlyTransport) -> None:
        self._transport = transport

    def read_metrika_report(
        self,
        query: MetrikaReportReadQuery,
    ) -> MetrikaReportBlock:
        raw = self._transport.read(
            VersionedReadRequest(
                system="METRIKA",
                host="api-metrika.yandex.net",
                path="/stat/v1/data",
                version="v1",
                service="Statistics",
                method="get",
                http_verb="GET",
                payload=asdict(query),
            )
        )
        if not isinstance(raw, MetrikaReportBlock) or raw.source != "METRIKA_REPORT":
            raise _reject_read_response("Metrika report")
        return raw


def _reject_read_response(connector: str) -> RunRejectedError:
    return RunRejectedError(
        "READ_CONNECTOR_RESPONSE_REJECTED",
        "connectors",
        "The " + connector + " response does not match its typed contract.",
    )


def _reject_fixture(message: str) -> RunRejectedError:
    return RunRejectedError(
        "INVALID_INPUT",
        "connectors",
        message,
    )


def _require_object(
    value: Any,
    expected_keys: Set[str],
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise _reject_fixture(
            "The " + label + " does not match the approved closed schema."
        )
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise _reject_fixture("The " + label + " is invalid.")
    return value


def _require_nonnegative_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _reject_fixture("The " + label + " is invalid.")
    return value


def _require_positive_integer(value: Any, label: str) -> int:
    parsed = _require_nonnegative_integer(value, label)
    if parsed == 0:
        raise _reject_fixture("The " + label + " must be positive.")
    return parsed


def _require_rows(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, list) or not 1 <= len(value) <= 1000:
        raise _reject_fixture("The " + label + " row count is invalid.")
    return value


class FixtureAnalyticsConnectorV1:
    """Parse a linked fixture through the same three read contracts."""

    def read_report(self, raw: Mapping[str, Any]) -> DirectReportBlock:
        value = _require_object(
            raw,
            {
                "source",
                "retrieved_at",
                "watermark",
                "period_start",
                "period_end",
                "timezone",
                "attribution",
                "currency",
                "rows",
            },
            "Direct report block",
        )
        rows = []
        for raw_row in _require_rows(value["rows"], "Direct report"):
            row = _require_object(
                raw_row,
                {"campaign", "date", "impressions", "clicks", "cost_micros"},
                "Direct report row",
            )
            impressions = _require_nonnegative_integer(
                row["impressions"],
                "Direct impressions",
            )
            clicks = _require_nonnegative_integer(row["clicks"], "Direct clicks")
            if clicks > impressions:
                raise _reject_fixture("Direct clicks exceed impressions.")
            rows.append(
                DirectReportRow(
                    campaign=_require_string(row["campaign"], "Direct campaign"),
                    date=_require_string(row["date"], "Direct date"),
                    impressions=impressions,
                    clicks=clicks,
                    cost_micros=_require_nonnegative_integer(
                        row["cost_micros"],
                        "Direct cost",
                    ),
                )
            )
        return DirectReportBlock(
            source=_require_string(value["source"], "Direct source"),
            retrieved_at=_require_string(
                value["retrieved_at"],
                "Direct retrieval time",
            ),
            watermark=_require_string(value["watermark"], "Direct watermark"),
            period_start=_require_string(
                value["period_start"],
                "Direct period start",
            ),
            period_end=_require_string(value["period_end"], "Direct period end"),
            timezone=_require_string(value["timezone"], "Direct timezone"),
            attribution=_require_string(
                value["attribution"],
                "Direct attribution",
            ),
            currency=_require_string(value["currency"], "Direct currency"),
            rows=tuple(rows),
        )

    def read_campaign_state(
        self,
        raw: Mapping[str, Any],
    ) -> DirectCampaignStateBlock:
        value = _require_object(
            raw,
            {
                "source",
                "retrieved_at",
                "watermark",
                "campaign",
                "campaign_state",
                "group_state",
                "ad_state",
                "strategy",
                "current_weekly_budget_micros",
                "budget_period_start",
                "budget_period_end",
                "current_search_bid_micros",
                "ad_variant",
                "object_config_version",
                "last_change",
            },
            "Direct campaign state block",
        )
        last_change = _require_object(
            value["last_change"],
            {"author", "occurred_at"},
            "last change",
        )
        return DirectCampaignStateBlock(
            source=_require_string(value["source"], "campaign state source"),
            retrieved_at=_require_string(
                value["retrieved_at"],
                "campaign state retrieval time",
            ),
            watermark=_require_string(
                value["watermark"],
                "campaign state watermark",
            ),
            campaign=_require_string(value["campaign"], "campaign"),
            campaign_state=_require_string(
                value["campaign_state"],
                "campaign state",
            ),
            group_state=_require_string(value["group_state"], "group state"),
            ad_state=_require_string(value["ad_state"], "ad state"),
            strategy=_require_string(value["strategy"], "strategy"),
            current_weekly_budget_micros=_require_positive_integer(
                value["current_weekly_budget_micros"],
                "weekly budget",
            ),
            budget_period_start=_require_string(
                value["budget_period_start"],
                "budget period start",
            ),
            budget_period_end=_require_string(
                value["budget_period_end"],
                "budget period end",
            ),
            current_search_bid_micros=_require_nonnegative_integer(
                value["current_search_bid_micros"],
                "search bid",
            ),
            ad_variant=_require_string(value["ad_variant"], "ad variant"),
            object_config_version=_require_string(
                value["object_config_version"],
                "object configuration version",
            ),
            last_change_author=_require_string(
                last_change["author"],
                "last change author",
            ),
            last_change_occurred_at=_require_string(
                last_change["occurred_at"],
                "last change time",
            ),
        )

    def read_metrika_report(
        self,
        raw: Mapping[str, Any],
    ) -> MetrikaReportBlock:
        value = _require_object(
            raw,
            {
                "source",
                "retrieved_at",
                "watermark",
                "period_start",
                "period_end",
                "timezone",
                "attribution",
                "rows",
            },
            "Metrika report block",
        )
        rows = []
        for raw_row in _require_rows(value["rows"], "Metrika report"):
            row = _require_object(
                raw_row,
                {"campaign", "goal", "date", "visits", "goal_visits"},
                "Metrika report row",
            )
            visits = _require_nonnegative_integer(
                row["visits"],
                "Metrika visits",
            )
            goal_visits = _require_nonnegative_integer(
                row["goal_visits"],
                "Metrika goal visits",
            )
            if goal_visits > visits:
                raise _reject_fixture("Metrika goal visits exceed visits.")
            rows.append(
                MetrikaReportRow(
                    campaign=_require_string(row["campaign"], "Metrika campaign"),
                    goal=_require_string(row["goal"], "Metrika goal"),
                    date=_require_string(row["date"], "Metrika date"),
                    visits=visits,
                    goal_visits=goal_visits,
                )
            )
        return MetrikaReportBlock(
            source=_require_string(value["source"], "Metrika source"),
            retrieved_at=_require_string(
                value["retrieved_at"],
                "Metrika retrieval time",
            ),
            watermark=_require_string(value["watermark"], "Metrika watermark"),
            period_start=_require_string(
                value["period_start"],
                "Metrika period start",
            ),
            period_end=_require_string(
                value["period_end"],
                "Metrika period end",
            ),
            timezone=_require_string(value["timezone"], "Metrika timezone"),
            attribution=_require_string(
                value["attribution"],
                "Metrika attribution",
            ),
            rows=tuple(rows),
        )

    def read_linked(self, raw_fixture: Mapping[str, Any]) -> ConnectedAnalytics:
        value = _require_object(
            raw_fixture,
            {
                "schema_version",
                "fixture_id",
                "generated_at",
                "scope",
                "direct_report",
                "direct_state",
                "metrika_report",
                "baseline",
            },
            "linked analytics fixture",
        )
        if value["schema_version"] != ANALYTICS_FIXTURE_SCHEMA_VERSION:
            raise _reject_fixture("The analytics fixture version is unsupported.")
        scope_value = _require_object(
            value["scope"],
            {
                "organization",
                "connection",
                "account",
                "campaign",
                "counter",
                "goal",
            },
            "analytics scope",
        )
        scope = AnalyticsScope(
            organization=_require_string(
                scope_value["organization"],
                "scope organization",
            ),
            connection=_require_string(
                scope_value["connection"],
                "scope connection",
            ),
            account=_require_string(scope_value["account"], "scope account"),
            campaign=_require_string(scope_value["campaign"], "scope campaign"),
            counter=_require_string(scope_value["counter"], "scope counter"),
            goal=_require_string(scope_value["goal"], "scope goal"),
        )
        baseline = self._read_baseline(value["baseline"])
        direct_report = self.read_report(value["direct_report"])
        direct_state = self.read_campaign_state(value["direct_state"])
        metrika_report = self.read_metrika_report(value["metrika_report"])
        return ConnectedAnalytics(
            observation_id=_require_string(
                value["fixture_id"],
                "fixture identifier",
            ),
            generated_at=_require_string(value["generated_at"], "generation time"),
            scope=scope,
            requested_period=AnalyticsPeriod(
                period_start=direct_report.period_start,
                period_end=direct_report.period_end,
            ),
            direct_report=direct_report,
            direct_state=direct_state,
            metrika_report=metrika_report,
            baseline=baseline,
        )

    @staticmethod
    def _read_baseline(value: Any) -> Optional[BaselineAggregate]:
        if value is None:
            return None
        baseline = _require_object(
            value,
            {
                "campaign",
                "impressions",
                "clicks",
                "cost_micros",
                "visits",
                "goal_visits",
            },
            "baseline",
        )
        _require_string(baseline["campaign"], "baseline campaign")
        impressions = _require_nonnegative_integer(
            baseline["impressions"],
            "baseline impressions",
        )
        clicks = _require_nonnegative_integer(
            baseline["clicks"],
            "baseline clicks",
        )
        visits = _require_nonnegative_integer(
            baseline["visits"],
            "baseline visits",
        )
        goal_visits = _require_nonnegative_integer(
            baseline["goal_visits"],
            "baseline goal visits",
        )
        if clicks > impressions or goal_visits > visits:
            raise _reject_fixture("The baseline metrics are inconsistent.")
        return BaselineAggregate(
            source_campaign=_require_string(
                baseline["campaign"],
                "baseline campaign",
            ),
            impressions=impressions,
            clicks=clicks,
            cost_micros=_require_nonnegative_integer(
                baseline["cost_micros"],
                "baseline cost",
            ),
            visits=visits,
            goal_visits=goal_visits,
        )


class FixtureAnalyticsReadConnectorsV1:
    """Serve a parsed fixture through the production read interfaces."""

    def __init__(self, connected: ConnectedAnalytics) -> None:
        self.connected = connected

    def read_report(self, query: DirectReportsReadQuery) -> DirectReportBlock:
        scope = self.connected.scope
        if query.account != scope.account or query.campaign != scope.campaign:
            raise _reject_fixture_read_query()
        return self.connected.direct_report

    def read_campaign_state(
        self,
        query: DirectCampaignStateReadQuery,
    ) -> DirectCampaignStateBlock:
        scope = self.connected.scope
        if query.account != scope.account or query.campaign != scope.campaign:
            raise _reject_fixture_read_query()
        return self.connected.direct_state

    def read_metrika_report(
        self,
        query: MetrikaReportReadQuery,
    ) -> MetrikaReportBlock:
        scope = self.connected.scope
        if (
            query.counter != scope.counter
            or query.campaign != scope.campaign
            or query.goal != scope.goal
        ):
            raise _reject_fixture_read_query()
        return self.connected.metrika_report


def _reject_fixture_read_query() -> RunRejectedError:
    return RunRejectedError(
        "FIXTURE_READ_QUERY_REJECTED",
        "connectors",
        "The fixture read query is outside the trusted scope.",
    )
