import assert from "node:assert/strict";
import test from "node:test";

import { filterAndSortCampaignDrafts } from "../lib/campaign-canvas.ts";

const drafts = [
  { draft_id: "draft-b", visibility: "VISIBLE", variant: { kind: "CONTROL" }, market_evidence_status: "AVAILABLE", viability_score: { rank: 1, score: 75, score_raw: 75 } },
  { draft_id: "draft-a", visibility: "VISIBLE", variant: { kind: "IMPROVEMENT" }, market_evidence_status: "AVAILABLE", viability_score: { rank: 1, score: 75, score_raw: 75 } },
  { draft_id: "draft-c", visibility: "VISIBLE", variant: { kind: "IMPROVEMENT" }, market_evidence_status: "PARTIAL", viability_score: { rank: 3, score: 61, score_raw: 60.8 } },
  { draft_id: "draft-hidden", visibility: "HIDDEN", suppression_reason: "HIDDEN:NO_MATERIAL_DELTA", variant: { kind: "IMPROVEMENT" }, market_evidence_status: "EVIDENCE_GAP", viability_score: { rank: null, score: null, score_raw: null } },
];

test("Campaign Canvas applies deterministic variant and evidence-status filters without erasing semantic ties", () => {
  const result = filterAndSortCampaignDrafts(drafts, {
    variant: "IMPROVEMENT",
    evidence: "AVAILABLE",
    sort: "RANK",
    includeHidden: false,
  });
  assert.deepEqual(result.map((draft) => draft.draft_id), ["draft-a"]);

  const tied = filterAndSortCampaignDrafts(drafts, { variant: "ALL", evidence: "ALL", sort: "RANK", includeHidden: false });
  assert.deepEqual(tied.map((draft) => draft.draft_id), ["draft-a", "draft-b", "draft-c"]);
  assert.equal(tied[0].viability_score.rank, tied[1].viability_score.rank);
});

test("rank and score sorting use stable IDs only for equal display values and hidden Drafts remain discoverable", () => {
  assert.deepEqual(
    filterAndSortCampaignDrafts(drafts, { variant: "ALL", evidence: "ALL", sort: "SCORE", includeHidden: true }).map((draft) => draft.draft_id),
    ["draft-a", "draft-b", "draft-c", "draft-hidden"],
  );
  assert.deepEqual(
    filterAndSortCampaignDrafts(drafts, { variant: "ALL", evidence: "EVIDENCE_GAP", sort: "RANK", includeHidden: true }).map((draft) => draft.draft_id),
    ["draft-hidden"],
  );
  assert.equal(drafts[3].suppression_reason, "HIDDEN:NO_MATERIAL_DELTA");
});
