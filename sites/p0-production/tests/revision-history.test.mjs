import assert from "node:assert/strict";
import test from "node:test";

import { summarizeP0Revision } from "../lib/revision-history.ts";

const state = {
  strategy: { strategy_revision_id: "campaign-strategy-r7" },
  recommendation_set: { recommendation_set_id: "recommendation-set-7" },
  draft: {
    draft_id: "draft-7",
    draft_revision_id: "draft-7-r2",
    publish_fingerprint: "abcdef0123456789",
  },
  shortlist: { shortlist_revision_id: "p0-shortlist-r7" },
  package_review: { package_review_id: "package-review-7", package_id: "package-7" },
  human_decision_gate: { gate_id: "gate-7", package_id: "package-7", confirmed_at: "2026-08-21T12:01:00.000Z" },
  campaign: { campaign_id: "123", campaign_state: "SUSPENDED" },
};

test("keeps superseded Strategy and Draft lineage audit-visible", () => {
  assert.deepEqual(
    summarizeP0Revision(
      { revision: 7, updated_at: "2026-08-21T12:00:00.000Z", value_json: JSON.stringify(state) },
      8,
    ),
    {
      revision: 7,
      updated_at: "2026-08-21T12:00:00.000Z",
      status: "SUPERSEDED",
      strategy_revision_id: "campaign-strategy-r7",
      recommendation_set_id: "recommendation-set-7",
      draft_id: "draft-7",
      draft_revision_id: "draft-7-r2",
      publish_fingerprint: "abcdef0123456789",
      shortlist_revision_id: "p0-shortlist-r7",
      package_review_id: "package-review-7",
      package_id: "package-7",
      human_decision_gate_id: "gate-7",
      package_confirmed_at: "2026-08-21T12:01:00.000Z",
      campaign_id: "123",
      campaign_state: "SUSPENDED",
    },
  );
});

test("marks only the latest persisted document revision current", () => {
  const summary = summarizeP0Revision(
    { revision: 8, updated_at: "2026-08-21T12:05:00.000Z", value_json: JSON.stringify(state) },
    8,
  );
  assert.equal(summary.status, "CURRENT");
  assert.equal(summary.draft_revision_id, "draft-7-r2");
});
