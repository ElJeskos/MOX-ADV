"""Deterministic normalization for bootstrap and integrated analytics."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping, Sequence, Tuple

from mox_adv.contracts import (
    INTEGRATED_SNAPSHOT_SCHEMA_VERSION,
    BusinessGoal,
    CampaignObservation,
    ComparabilityStatus,
    ConfidenceStatus,
    ConnectedAnalytics,
    ConnectedFixture,
    IntegratedGrainRecord,
    IntegratedSnapshotDraft,
    LastChangeObservation,
    NormalizedSnapshot,
    ProvenanceEntry,
    RunContext,
    SnapshotAttribution,
    SnapshotProvenance,
    TargetKPI,
    TrustedAnalyticsScope,
)
from mox_adv.errors import RunRejectedError


class NormalizerV1:
    def normalize(
        self,
        context: RunContext,
        connected: ConnectedFixture,
    ) -> NormalizedSnapshot:
        canonical = {
            "fixture_id": connected.fixture_id,
            "policy_version": context.policy_version,
            "records": [
                {
                    "impressions": record.impressions,
                    "clicks": record.clicks,
                    "conversions": record.conversions,
                    "cost_rub": str(record.cost_rub),
                }
                for record in connected.records
            ],
        }
        digest = hashlib.sha256(
            json.dumps(
                canonical,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return NormalizedSnapshot(
            snapshot_id="sha256:" + digest,
            fixture_id=connected.fixture_id,
            records=connected.records,
        )


def _reject(message: str) -> RunRejectedError:
    return RunRejectedError(
        "INTEGRATED_SNAPSHOT_REJECTED",
        "normalization",
        message,
    )


def _parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise _reject("The " + label + " timestamp is invalid.") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise _reject("The " + label + " timestamp must use UTC.")
    return parsed.astimezone(timezone.utc)


def _parse_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise _reject("The " + label + " date is invalid.") from error


class IntegratedSnapshotNormalizerV1:
    """Validate trusted linkage and create a calculation-ready snapshot draft."""

    def normalize(
        self,
        connected: ConnectedAnalytics,
        policy: Mapping[str, Any],
        trusted_scope: TrustedAnalyticsScope,
    ) -> IntegratedSnapshotDraft:
        generated_at = _parse_utc(connected.generated_at, "generation")
        local_fixture = self._validate_sources(connected)
        self._validate_trusted_scope(connected, policy, trusted_scope)
        gaps, comparability = self._comparability(
            connected,
            policy,
            generated_at,
            local_fixture,
        )
        direct_dates, metrika_dates = self._validate_rows(
            connected,
            local_fixture,
        )
        total_clicks = sum(row.clicks for row in connected.direct_report.rows)
        total_goal_visits = sum(
            row.goal_visits for row in connected.metrika_report.rows
        )
        minimum_sample = policy["mandate"]["minimum_sample"]
        if (
            total_clicks < minimum_sample["clicks"]
            or total_goal_visits < minimum_sample["conversions"]
        ):
            confidence_status: ConfidenceStatus = "INSUFFICIENT_DATA"
            gaps.append("INSUFFICIENT_SAMPLE")
        elif any(gap.endswith("_DATA_STALE") for gap in gaps):
            confidence_status = "STALE_DATA"
        else:
            confidence_status = "READY"
        if comparability == "COMPARABLE" and connected.baseline is None:
            comparability = "PARTIAL"
            gaps.append("BASELINE_UNAVAILABLE")
        records = self._join_rows(connected, direct_dates, metrika_dates)
        financial_allowed = (
            comparability == "COMPARABLE" and confidence_status == "READY"
        )
        state = connected.direct_state
        return IntegratedSnapshotDraft(
            schema_version=INTEGRATED_SNAPSHOT_SCHEMA_VERSION,
            policy_version=str(policy["policy_id"]),
            observation_id=connected.observation_id,
            generated_at=generated_at.isoformat(),
            scope=connected.scope,
            period_start=connected.direct_report.period_start,
            period_end=connected.direct_report.period_end,
            timezone="UTC",
            attribution=SnapshotAttribution(
                direct=connected.direct_report.attribution,
                metrika=connected.metrika_report.attribution,
            ),
            provenance=SnapshotProvenance(
                direct_report=ProvenanceEntry(
                    source=connected.direct_report.source,
                    retrieved_at=connected.direct_report.retrieved_at,
                    watermark=connected.direct_report.watermark,
                ),
                direct_state=ProvenanceEntry(
                    source=state.source,
                    retrieved_at=state.retrieved_at,
                    watermark=state.watermark,
                ),
                metrika_report=ProvenanceEntry(
                    source=connected.metrika_report.source,
                    retrieved_at=connected.metrika_report.retrieved_at,
                    watermark=connected.metrika_report.watermark,
                ),
            ),
            grain_records=records,
            campaign=CampaignObservation(
                state=state.campaign_state,
                group_state=state.group_state,
                ad_state=state.ad_state,
                strategy=state.strategy,
                current_weekly_budget_micros=(state.current_weekly_budget_micros),
                budget_period_start=state.budget_period_start,
                budget_period_end=state.budget_period_end,
                current_search_bid_micros=state.current_search_bid_micros,
                current_ad_variant=state.ad_variant,
                object_config_version=state.object_config_version,
            ),
            last_change=LastChangeObservation(
                author=state.last_change_author,
                occurred_at=state.last_change_occurred_at,
            ),
            business_goal=BusinessGoal(
                event=str(policy["conversion"]["primary"]["event"]),
                meaning=str(policy["conversion"]["primary"]["business_meaning"]),
            ),
            target_kpi=TargetKPI(
                name=str(policy["mandate"]["kpi"]["name"]),
                target_maximum=int(policy["mandate"]["kpi"]["target_maximum"]),
            ),
            baseline=connected.baseline,
            comparability_status=comparability,
            confidence_status=confidence_status,
            data_quality_gaps=tuple(sorted(set(gaps))),
            financial_recommendations_allowed=financial_allowed,
        )

    @staticmethod
    def _validate_sources(connected: ConnectedAnalytics) -> bool:
        sources = (
            connected.direct_report.source,
            connected.direct_state.source,
            connected.metrika_report.source,
        )
        if sources == ("LOCAL_FIXTURE",) * 3:
            return True
        if sources == (
            "DIRECT_REPORTS",
            "DIRECT_CAMPAIGN_STATE",
            "METRIKA_REPORT",
        ):
            return False
        raise _reject("The analytics source combination is unsupported.")

    @staticmethod
    def _validate_trusted_scope(
        connected: ConnectedAnalytics,
        policy: Mapping[str, Any],
        trusted_scope: TrustedAnalyticsScope,
    ) -> None:
        if (
            connected.scope.organization != trusted_scope.organization
            or connected.scope.connection != trusted_scope.connection
            or connected.scope.account != trusted_scope.account
            or connected.scope.campaign != trusted_scope.campaign
            or connected.scope.counter != trusted_scope.counter
            or connected.scope.goal != trusted_scope.goal
        ):
            raise _reject("The analytics input is outside the trusted scope.")
        if (
            connected.baseline is not None
            and connected.baseline.source_campaign != trusted_scope.baseline_campaign
        ):
            raise _reject("The baseline is outside the trusted scope.")
        owner = policy["principals"]["owner"]["identity"]
        if connected.direct_state.last_change_author != owner:
            raise _reject("The campaign contains an unknown external change.")

    @staticmethod
    def _validate_rows(
        connected: ConnectedAnalytics,
        local_fixture: bool,
    ) -> Tuple[Tuple[date, ...], Tuple[date, ...]]:
        direct = connected.direct_report
        metrika = connected.metrika_report
        direct_start = _parse_date(direct.period_start, "Direct period start")
        direct_end = _parse_date(direct.period_end, "Direct period end")
        metrika_start = _parse_date(
            metrika.period_start,
            "Metrika period start",
        )
        metrika_end = _parse_date(metrika.period_end, "Metrika period end")
        if direct_end < direct_start or metrika_end < metrika_start:
            raise _reject("An analytics period is invalid.")
        if local_fixture and (direct_end - direct_start).days != 6:
            raise _reject("A local fixture period must be seven calendar days.")
        direct_dates = tuple(_parse_date(row.date, "Direct row") for row in direct.rows)
        metrika_dates = tuple(
            _parse_date(row.date, "Metrika row") for row in metrika.rows
        )
        expected_direct_dates = (
            tuple(direct_start + timedelta(days=offset) for offset in range(7))
            if local_fixture
            else tuple(
                direct_start + timedelta(days=offset)
                for offset in range((direct_end - direct_start).days + 1)
            )
        )
        expected_metrika_dates = tuple(
            metrika_start + timedelta(days=offset)
            for offset in range((metrika_end - metrika_start).days + 1)
        )
        if tuple(sorted(direct_dates)) != expected_direct_dates or len(
            set(direct_dates)
        ) != len(direct_dates):
            raise _reject("Direct rows do not cover the closed daily grain.")
        if tuple(sorted(metrika_dates)) != expected_metrika_dates or len(
            set(metrika_dates)
        ) != len(metrika_dates):
            raise _reject("Metrika rows do not cover the closed daily grain.")
        return direct_dates, metrika_dates

    @staticmethod
    def _comparability(
        connected: ConnectedAnalytics,
        policy: Mapping[str, Any],
        generated_at: datetime,
        local_fixture: bool,
    ) -> Tuple[list[str], ComparabilityStatus]:
        gaps = []
        direct = connected.direct_report
        metrika = connected.metrika_report
        incompatible = False
        expected_campaign = connected.scope.campaign
        if (
            {row.campaign for row in direct.rows} != {expected_campaign}
            or {row.campaign for row in metrika.rows} != {expected_campaign}
            or {row.goal for row in metrika.rows} != {connected.scope.goal}
            or connected.direct_state.campaign != expected_campaign
        ):
            gaps.append("IDENTIFIER_MISMATCH")
            incompatible = True
        if (
            direct.period_start != metrika.period_start
            or direct.period_end != metrika.period_end
            or direct.period_start != connected.requested_period.period_start
            or direct.period_end != connected.requested_period.period_end
            or metrika.period_start != connected.requested_period.period_start
            or metrika.period_end != connected.requested_period.period_end
        ):
            gaps.append("PERIOD_MISMATCH")
            incompatible = True
        if direct.timezone != "UTC" or metrika.timezone != "UTC":
            gaps.append("TIMEZONE_MISMATCH")
            incompatible = True
        expected_attribution = policy["attribution"]
        if (
            direct.attribution != expected_attribution["direct"]
            or metrika.attribution != expected_attribution["metrika"]
        ):
            gaps.append("ATTRIBUTION_MISMATCH")
            incompatible = True
        if direct.currency != "RUB":
            gaps.append("CURRENCY_MISMATCH")
            incompatible = True
        budget_period_start = _parse_utc(
            connected.direct_state.budget_period_start,
            "budget period start",
        )
        budget_period_end = _parse_utc(
            connected.direct_state.budget_period_end,
            "budget period end",
        )
        if budget_period_end - budget_period_start != timedelta(days=7):
            raise _reject("The weekly budget period must span seven days.")
        if generated_at < budget_period_start:
            gaps.append("BUDGET_PERIOD_MISMATCH")
            incompatible = True

        timestamps = {
            "direct_report": (
                _parse_utc(direct.retrieved_at, "Direct retrieval"),
                _parse_utc(direct.watermark, "Direct watermark"),
            ),
            "direct_state": (
                _parse_utc(
                    connected.direct_state.retrieved_at,
                    "campaign state retrieval",
                ),
                _parse_utc(
                    connected.direct_state.watermark,
                    "campaign state watermark",
                ),
            ),
            "metrika_report": (
                _parse_utc(metrika.retrieved_at, "Metrika retrieval"),
                _parse_utc(metrika.watermark, "Metrika watermark"),
            ),
        }
        for label, (retrieved_at, watermark) in timestamps.items():
            if retrieved_at > generated_at or watermark > retrieved_at:
                raise _reject("Analytics provenance contains a future timestamp.")
            if label.startswith("direct"):
                maximum_age = timedelta(
                    minutes=policy["timing"]["direct_freshness_minutes"]
                )
                stale_gap = "DIRECT_DATA_STALE"
            else:
                maximum_age = timedelta(
                    hours=policy["timing"]["metrika_freshness_hours"]
                )
                stale_gap = "METRIKA_DATA_STALE"
            if generated_at - retrieved_at > maximum_age:
                gaps.append(stale_gap)
                incompatible = True
        watermarks = [item[1] for item in timestamps.values()]
        maximum_skew = timedelta(hours=policy["timing"]["maximum_watermark_skew_hours"])
        if max(watermarks) - min(watermarks) > maximum_skew:
            gaps.append("WATERMARK_SKEW_EXCEEDED")
            incompatible = True
        period_end = _parse_date(direct.period_end, "period end")
        closed_at = datetime.combine(
            period_end + timedelta(days=1),
            time.min,
            tzinfo=timezone.utc,
        )
        if generated_at < closed_at:
            gaps.append("PERIOD_NOT_CLOSED")
            incompatible = True
        if local_fixture and generated_at - closed_at > timedelta(hours=48):
            raise _reject(
                "A local fixture must use a closed period no older than 48 hours."
            )
        cutoff = closed_at + timedelta(
            hours=policy["timing"]["late_conversion_cutoff_hours"]
        )
        metrika_watermark = timestamps["metrika_report"][1]
        if metrika_watermark > cutoff:
            gaps.append("LATE_CONVERSION_CUTOFF_EXCEEDED")
            incompatible = True
        if incompatible:
            return gaps, "INCOMPATIBLE"
        if gaps:
            return gaps, "PARTIAL"
        return gaps, "COMPARABLE"

    @staticmethod
    def _join_rows(
        connected: ConnectedAnalytics,
        direct_dates: Sequence[date],
        metrika_dates: Sequence[date],
    ) -> Tuple[IntegratedGrainRecord, ...]:
        direct_by_date = dict(zip(direct_dates, connected.direct_report.rows))
        metrika_by_date = dict(zip(metrika_dates, connected.metrika_report.rows))
        records = []
        for row_date in sorted(set(direct_by_date) & set(metrika_by_date)):
            direct = direct_by_date[row_date]
            metrika = metrika_by_date[row_date]
            records.append(
                IntegratedGrainRecord(
                    campaign=direct.campaign,
                    goal=metrika.goal,
                    date=row_date.isoformat(),
                    impressions=direct.impressions,
                    clicks=direct.clicks,
                    cost_micros=direct.cost_micros,
                    visits=metrika.visits,
                    goal_visits=metrika.goal_visits,
                    leads=None,
                )
            )
        return tuple(records)

    @staticmethod
    def fingerprint(value: Mapping[str, Any]) -> str:
        canonical = dict(value)
        canonical.pop("snapshot_id", None)
        digest = hashlib.sha256(
            json.dumps(
                canonical,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return "sha256:" + digest

    @classmethod
    def verify_fingerprint(cls, value: Mapping[str, Any]) -> bool:
        snapshot_id = value.get("snapshot_id")
        return isinstance(snapshot_id, str) and snapshot_id == cls.fingerprint(value)
