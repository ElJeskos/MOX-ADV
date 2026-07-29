"""Local-only fixture connector for the bootstrap run."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from mox_adv.contracts import (
    FIXTURE_SCHEMA_VERSION,
    ConnectedFixture,
    FixtureRecord,
    RunContext,
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
