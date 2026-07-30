"""Lossless normalized provider observations carried by module results."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Tuple, Union, cast

from mox_adv.contracts import (
    DirectCampaignStateBlock,
    DirectReportBlock,
    DirectReportRow,
    MetrikaReportBlock,
    MetrikaReportRow,
)
from mox_adv.module_api.v1.contract_validation import (
    ContractValidationError,
)
from mox_adv.module_api.v1.contract_validation import (
    array_value as _array,
)
from mox_adv.module_api.v1.contract_validation import (
    exact_fields as _exact_fields,
)
from mox_adv.module_api.v1.contract_validation import (
    iso_date as _iso_date,
)
from mox_adv.module_api.v1.contract_validation import (
    object_value as _object,
)
from mox_adv.module_api.v1.contract_validation import (
    one_of as _one_of,
)
from mox_adv.module_api.v1.contract_validation import (
    text as _text,
)
from mox_adv.module_api.v1.contract_validation import (
    timestamp as _timestamp,
)
from mox_adv.module_api.v1.contract_validation import (
    timezone_name as _timezone,
)


def _count(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractValidationError(f"{field} must be a non-negative integer")
    return value


def _rows(value: object, field: str) -> Tuple[object, ...]:
    rows = tuple(_array(value, field))
    if not rows or len(rows) > 1_000:
        raise ContractValidationError(f"{field} must contain 1 to 1000 rows")
    return rows


def _report_as_dict(
    value: Union[DirectReportBlock, MetrikaReportBlock],
) -> Dict[str, Any]:
    result = asdict(value)
    result["rows"] = [asdict(row) for row in value.rows]
    return result


def _direct_report_from_dict(
    value: Mapping[str, Any],
) -> DirectReportBlock:
    _exact_fields(
        value,
        field="provider_observation.report",
        required=(
            "source",
            "retrieved_at",
            "watermark",
            "period_start",
            "period_end",
            "timezone",
            "attribution",
            "currency",
            "rows",
        ),
    )
    rows = []
    for index, item in enumerate(
        _rows(value["rows"], "provider_observation.report.rows")
    ):
        field = f"provider_observation.report.rows[{index}]"
        row = _object(item, field)
        _exact_fields(
            row,
            field=field,
            required=(
                "campaign",
                "date",
                "impressions",
                "clicks",
                "cost_micros",
            ),
        )
        impressions = _count(row["impressions"], field + ".impressions")
        clicks = _count(row["clicks"], field + ".clicks")
        if clicks > impressions:
            raise ContractValidationError(
                f"{field}.clicks must not exceed impressions"
            )
        rows.append(
            DirectReportRow(
                campaign=_text(row["campaign"], field + ".campaign", maximum=128),
                date=_iso_date(row["date"], field + ".date"),
                impressions=impressions,
                clicks=clicks,
                cost_micros=_count(
                    row["cost_micros"],
                    field + ".cost_micros",
                ),
            )
        )
    return DirectReportBlock(
        source=_text(value["source"], "provider_observation.report.source", maximum=64),
        retrieved_at=_timestamp(
            value["retrieved_at"],
            "provider_observation.report.retrieved_at",
        ),
        watermark=_timestamp(
            value["watermark"],
            "provider_observation.report.watermark",
        ),
        period_start=_iso_date(
            value["period_start"],
            "provider_observation.report.period_start",
        ),
        period_end=_iso_date(
            value["period_end"],
            "provider_observation.report.period_end",
        ),
        timezone=_timezone(
            value["timezone"],
            "provider_observation.report.timezone",
        ),
        attribution=_text(
            value["attribution"],
            "provider_observation.report.attribution",
            maximum=64,
        ),
        currency=_text(
            value["currency"],
            "provider_observation.report.currency",
            maximum=16,
        ),
        rows=tuple(rows),
    )


def _direct_state_from_dict(
    value: Mapping[str, Any],
) -> DirectCampaignStateBlock:
    fields = (
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
        "last_change_author",
        "last_change_occurred_at",
    )
    _exact_fields(
        value,
        field="provider_observation.state",
        required=fields,
    )
    text_fields = {
        name: _text(
            value[name],
            "provider_observation.state." + name,
            maximum=128,
        )
        for name in fields
        if name
        not in {
            "current_weekly_budget_micros",
            "current_search_bid_micros",
        }
    }
    for name in (
        "retrieved_at",
        "watermark",
        "budget_period_start",
        "budget_period_end",
        "last_change_occurred_at",
    ):
        text_fields[name] = _timestamp(
            value[name],
            "provider_observation.state." + name,
        )
    weekly_budget = _count(
        value["current_weekly_budget_micros"],
        "provider_observation.state.current_weekly_budget_micros",
    )
    if weekly_budget == 0:
        raise ContractValidationError(
            "provider_observation.state.current_weekly_budget_micros "
            "must be positive"
        )
    return DirectCampaignStateBlock(
        current_weekly_budget_micros=weekly_budget,
        current_search_bid_micros=_count(
            value["current_search_bid_micros"],
            "provider_observation.state.current_search_bid_micros",
        ),
        **text_fields,
    )


def _metrika_report_from_dict(
    value: Mapping[str, Any],
) -> MetrikaReportBlock:
    _exact_fields(
        value,
        field="provider_observation.report",
        required=(
            "source",
            "retrieved_at",
            "watermark",
            "period_start",
            "period_end",
            "timezone",
            "attribution",
            "rows",
        ),
    )
    rows = []
    for index, item in enumerate(
        _rows(value["rows"], "provider_observation.report.rows")
    ):
        field = f"provider_observation.report.rows[{index}]"
        row = _object(item, field)
        _exact_fields(
            row,
            field=field,
            required=("campaign", "goal", "date", "visits", "goal_visits"),
        )
        visits = _count(row["visits"], field + ".visits")
        goal_visits = _count(row["goal_visits"], field + ".goal_visits")
        if goal_visits > visits:
            raise ContractValidationError(
                f"{field}.goal_visits must not exceed visits"
            )
        rows.append(
            MetrikaReportRow(
                campaign=_text(row["campaign"], field + ".campaign", maximum=128),
                goal=_text(row["goal"], field + ".goal", maximum=128),
                date=_iso_date(row["date"], field + ".date"),
                visits=visits,
                goal_visits=goal_visits,
            )
        )
    return MetrikaReportBlock(
        source=_text(value["source"], "provider_observation.report.source", maximum=64),
        retrieved_at=_timestamp(
            value["retrieved_at"],
            "provider_observation.report.retrieved_at",
        ),
        watermark=_timestamp(
            value["watermark"],
            "provider_observation.report.watermark",
        ),
        period_start=_iso_date(
            value["period_start"],
            "provider_observation.report.period_start",
        ),
        period_end=_iso_date(
            value["period_end"],
            "provider_observation.report.period_end",
        ),
        timezone=_timezone(
            value["timezone"],
            "provider_observation.report.timezone",
        ),
        attribution=_text(
            value["attribution"],
            "provider_observation.report.attribution",
            maximum=64,
        ),
        rows=tuple(rows),
    )


@dataclass(frozen=True)
class DirectProviderObservationV1:
    """The validated Direct report and state needed by paired analytics."""

    report: DirectReportBlock
    state: DirectCampaignStateBlock
    kind: str = "DIRECT"

    def __post_init__(self) -> None:
        _one_of(self.kind, "provider_observation.kind", ("DIRECT",))
        if not isinstance(self.report, DirectReportBlock):
            raise ContractValidationError(
                "provider_observation.report must be a DirectReportBlock"
            )
        if not isinstance(self.state, DirectCampaignStateBlock):
            raise ContractValidationError(
                "provider_observation.state must be a DirectCampaignStateBlock"
            )

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "DirectProviderObservationV1":
        _exact_fields(
            value,
            field="provider_observation",
            required=("kind", "report", "state"),
        )
        _one_of(value["kind"], "provider_observation.kind", ("DIRECT",))
        return cls(
            report=_direct_report_from_dict(
                _object(value["report"], "provider_observation.report")
            ),
            state=_direct_state_from_dict(
                _object(value["state"], "provider_observation.state")
            ),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "report": _report_as_dict(self.report),
            "state": asdict(self.state),
        }


@dataclass(frozen=True)
class MetrikaProviderObservationV1:
    """The validated Metrika report needed by paired analytics."""

    report: MetrikaReportBlock
    kind: str = "METRIKA"

    def __post_init__(self) -> None:
        _one_of(self.kind, "provider_observation.kind", ("METRIKA",))
        if not isinstance(self.report, MetrikaReportBlock):
            raise ContractValidationError(
                "provider_observation.report must be a MetrikaReportBlock"
            )

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "MetrikaProviderObservationV1":
        _exact_fields(
            value,
            field="provider_observation",
            required=("kind", "report"),
        )
        _one_of(value["kind"], "provider_observation.kind", ("METRIKA",))
        return cls(
            report=_metrika_report_from_dict(
                _object(value["report"], "provider_observation.report")
            )
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "report": _report_as_dict(self.report),
        }


ProviderObservationV1 = Union[
    DirectProviderObservationV1,
    MetrikaProviderObservationV1,
]


def provider_observation_from_dict(
    value: Mapping[str, Any],
) -> ProviderObservationV1:
    kind = _text(value.get("kind"), "provider_observation.kind", maximum=32)
    if kind == "DIRECT":
        return DirectProviderObservationV1.from_dict(value)
    if kind == "METRIKA":
        return MetrikaProviderObservationV1.from_dict(value)
    raise ContractValidationError(
        "provider_observation.kind must be one of: DIRECT, METRIKA"
    )


def provider_observation_as_dict(
    value: ProviderObservationV1,
) -> Dict[str, Any]:
    if isinstance(value, DirectProviderObservationV1):
        return value.as_dict()
    return cast(MetrikaProviderObservationV1, value).as_dict()
