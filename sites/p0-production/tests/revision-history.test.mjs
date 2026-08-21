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
