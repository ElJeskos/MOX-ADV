"""Deterministic local analytics for the safe fixture."""

from __future__ import annotations

from decimal import Decimal

from mox_adv.contracts import AnalyticsSummary, NormalizedSnapshot, RunContext


class AnalyticsEngineV1:
    def calculate(
        self,
        context: RunContext,
        snapshot: NormalizedSnapshot,
    ) -> AnalyticsSummary:
        del context
        impressions = sum(record.impressions for record in snapshot.records)
        clicks = sum(record.clicks for record in snapshot.records)
        conversions = sum(record.conversions for record in snapshot.records)
        cost_rub = sum((record.cost_rub for record in snapshot.records), Decimal("0"))
        ctr = Decimal(clicks) / Decimal(impressions) if impressions else Decimal("0")
        return AnalyticsSummary(
            snapshot_id=snapshot.snapshot_id,
            impressions=impressions,
            clicks=clicks,
            conversions=conversions,
            cost_rub=cost_rub,
            ctr=ctr,
        )
