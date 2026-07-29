"""Deterministic fixture normalization."""

from __future__ import annotations

import hashlib
import json

from mox_adv.contracts import ConnectedFixture, NormalizedSnapshot, RunContext


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
