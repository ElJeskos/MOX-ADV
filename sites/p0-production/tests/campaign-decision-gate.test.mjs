import assert from "node:assert/strict";
import test from "node:test";

import {
  emptyShortlist,
  restoredInsertionIndex,
  selectionForDraft,
  shortlistSelectionBlockReason,
  stableRemovedIndex,
  verifyShortlist,
} from "../lib/campaign-decision-gate.ts";

function eligibleDraft(overrides = {}) {
  return {
    draft_id: "draft-eligible",
    draft_revision_id: "draft-eligible-r1",
    publish_fingerprint: `sha256:${"a".repeat(64)}`,
    strategy_revision_id: "strategy-r1",
    capability_profile_id: "direct-v501-unified-search-explicit-text",
    capability_profile_version: "1.0.0",
    visibility: "VISIBLE",
    suppression_reason: null,
    shortlist_eligible: true,
    publish_eligibility: "ELIGIBLE",
    publication_blockers: [],
    viability_score: {
      eligibility: { status: "ELIGIBLE", blockers: [] },
      evidence_gaps: { status: "RESOLVED", required: [] },
    },
    ...overrides,
  };
}

function recommendationSet(drafts = [eligibleDraft()]) {
  return {
    recommendation_set_id: "recommendation-set-r1",
    drafts,
    capability_profile: {
      profile_id: "direct-v501-unified-search-explicit-text",
      profile_version: "1.0.0",
    },
  };
}

test("shortlist eligibility rejects hidden, hard-blocked and unresolved evidence-gap Drafts with exact reasons", () => {
  const hidden = eligibleDraft({ visibility: "HIDDEN", suppression_reason: "HIDDEN:DUPLICATE_OR_OVERLAP", shortlist_eligible: false, publish_eligibility: "BLOCKED_HARD" });
  assert.equal(shortlistSelectionBlockReason(hidden), "Draft скрыт: HIDDEN:DUPLICATE_OR_OVERLAP.");
  assert.throws(() => selectionForDraft(hidden, recommendationSet([hidden])), /Draft скрыт/u);

  const hardBlocked = eligibleDraft({ shortlist_eligible: false, publish_eligibility: "BLOCKED_HARD", publication_blockers: [{ code: "PLAYBOOK_NO_ACTIVE_APPROVED_RELEASE", message: "Active approved playbook release отсутствует." }] });
  assert.equal(shortlistSelectionBlockReason(hardBlocked), "Active approved playbook release отсутствует.");
  assert.throws(() => selectionForDraft(hardBlocked, recommendationSet([hardBlocked])), /playbook release/u);

  const evidenceGap = eligibleDraft({
    shortlist_eligible: false,
    publish_eligibility: "BLOCKED_EVIDENCE_GAP",
    market_evidence_status: "EVIDENCE_GAP",
    publication_blockers: [{ code: "DEMAND_EVIDENCE_GAP", message: "Demand evidence gap remains unresolved." }],
    viability_score: { eligibility: { status: "ELIGIBLE", blockers: [] }, evidence_gaps: { status: "UNRESOLVED", required: ["wordstat"] } },
  });
  assert.equal(shortlistSelectionBlockReason(evidenceGap), "Demand evidence gap remains unresolved.");
  assert.throws(() => selectionForDraft(evidenceGap, recommendationSet([evidenceGap])), /evidence gap/u);

  const scoreBlocked = eligibleDraft({
    viability_score: {
      eligibility: {
        status: "BLOCKED_UNKNOWN",
        blockers: [{ code: "DIRECT_CAPABILITY_MISSING", remediation: "Persist exact capability.", input_pointer: "/draft/capability_selection" }],
      },
      evidence_gaps: { status: "RESOLVED", required: [] },
    },
  });
  assert.equal(
    shortlistSelectionBlockReason(scoreBlocked),
    "DIRECT_CAPABILITY_MISSING: Persist exact capability.: /draft/capability_selection",
  );

  const scoreGap = eligibleDraft({
    viability_score: {
      eligibility: { status: "ELIGIBLE", blockers: [] },
      evidence_gaps: {
        status: "UNRESOLVED",
        required: [{ code: "DEMAND_SCOPE_MISSING", description: "Official demand scope unavailable.", input_pointer: "/evidence/frequency" }],
      },
    },
  });
  assert.equal(
    shortlistSelectionBlockReason(scoreGap),
    "DEMAND_SCOPE_MISSING: Official demand scope unavailable.: /evidence/frequency",
  );
});

test("positional restore keeps insertion order when multiple Drafts are removed and restored in any order", () => {
  const removed = [];
  const first = { draft_id: "a", removed_index: stableRemovedIndex(0, removed) };
  removed.push(first);
  const second = { draft_id: "b", removed_index: stableRemovedIndex(0, removed) };
  removed.push(second);
  assert.deepEqual(removed.map((item) => item.removed_index), [0, 1]);
  assert.equal(restoredInsertionIndex(second, removed, 1), 0);
  const afterSecond = removed.filter((item) => item.draft_id !== second.draft_id);
  assert.equal(restoredInsertionIndex(first, afterSecond, 2), 0);
});

test("versioned empty shortlist is valid but exact selected lineage tampering fails closed", async () => {
  const set = recommendationSet();
  const shortlist = await emptyShortlist({
    shortlistRevisionId: "p0-shortlist-r1",
    strategyRevisionId: "strategy-r1",
    recommendationSetId: set.recommendation_set_id,
    updatedAt: "2026-08-21T10:00:00.000Z",
  });
  assert.equal(await verifyShortlist(shortlist, set, "strategy-r1"), true);
  const corrupted = structuredClone(shortlist);
  corrupted.content_hash = `sha256:${"0".repeat(64)}`;
  assert.equal(await verifyShortlist(corrupted, set, "strategy-r1"), false);
});
