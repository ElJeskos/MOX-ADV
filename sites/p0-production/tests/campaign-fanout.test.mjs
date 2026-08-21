import assert from "node:assert/strict";
import test from "node:test";

import {
  buildCampaignRecommendationSet,
  campaignDraftPublishBlockers,
  fingerprintDirectProjection,
} from "../lib/campaign-fanout.ts";

const model = {
  product: "Участие со стендом в выставке ИННОПРОМ",
  audience: "Руководители промышленных компаний",
  value: "Встречи с заказчиками и промышленными партнёрами",
  qualified_result: "Отправленная заявка на участие",
};

const strategy = {
  strategy_revision_id: "campaign-strategy-r7",
  goal: "Получать заявки на участие",
  geography: "Россия",
  period_start: "2026-09-01",
  period_end: "2026-09-30",
  landing_page: "https://innoprom.com/participant/",
  weekly_budget_rub: "10000",
  target_cpa_rub: "2000",
  message: "Подайте заявку на участие в выставке",
};

async function recommendationSet(analyticsEvidence = null) {
  return buildCampaignRecommendationSet({
    model,
    strategy,
    analyticsEvidence,
    generatedAt: "2026-08-21T12:00:00.000Z",
  });
}

test("deterministically fans one approved Strategy revision out into multiple complete Drafts", async () => {
  const first = await recommendationSet();
  const second = await recommendationSet();
  assert.deepEqual(first, second);

  const visible = first.drafts.filter((draft) => draft.visibility === "VISIBLE");
  assert.equal(visible.length, 3);
  assert.equal(new Set(visible.map((draft) => draft.draft_id)).size, visible.length);
  assert.equal(new Set(visible.map((draft) => draft.publish_fingerprint)).size, visible.length);
  assert.equal(visible.every((draft) => draft.strategy_revision_id === strategy.strategy_revision_id), true);
  assert.equal(visible.every((draft) => draft.publish_projection.direct.campaign), true);
  assert.equal(visible.every((draft) => draft.publish_projection.direct.ad_group), true);
  assert.equal(visible.every((draft) => draft.publish_projection.direct.keyword), true);
  assert.equal(visible.every((draft) => draft.publish_projection.direct.ad), true);
});

test("keeps evidence-gap Drafts reviewable but outside shortlist and publish", async () => {
  const value = await recommendationSet();
  for (const draft of value.drafts) {
    assert.equal(draft.market_evidence_status, "EVIDENCE_GAP");
    assert.equal(draft.shortlist_eligible, false);
    assert.equal(draft.publish_eligibility, "BLOCKED_EVIDENCE_GAP");
    assert.deepEqual(campaignDraftPublishBlockers(draft), [
      "Campaign Draft не имеет допустимого demand evidence и доступен только для review.",
    ]);
  }
  assert.equal(value.coverage.publishable_drafts, 0);
  assert.equal(value.coverage.evidence_gap_drafts, 4);
});

test("canonicalizes unordered Direct arrays before fingerprinting", async () => {
  const value = await recommendationSet();
  const projection = value.drafts[0].publish_projection;
  const reordered = structuredClone(projection);
  reordered.direct.ad_group.NegativeKeywords.Items.reverse();
  assert.equal(
    await fingerprintDirectProjection(projection),
    await fingerprintDirectProjection(reordered),
  );
});

test("keeps the Direct comparison profile constant across business hypotheses", async () => {
  const value = await recommendationSet();
  for (const draft of value.drafts.filter((item) => item.visibility === "VISIBLE")) {
    const strategyProjection = draft.publish_projection.direct.campaign.UnifiedCampaign.BiddingStrategy;
    assert.equal(strategyProjection.Search.BiddingStrategyType, "WB_MAXIMUM_CLICKS");
    assert.deepEqual(strategyProjection.Search.PlacementTypes, {
      SearchResults: "YES",
      ProductGallery: "NO",
    });
    assert.equal(strategyProjection.Network.BiddingStrategyType, "SERVING_OFF");
    assert.equal(draft.publish_projection.safety.must_end_non_serving, true);
    assert.equal(draft.publish_projection.safety.resume_allowed, false);
    assert.equal(draft.publish_projection.safety.network_serving, false);
    assert.ok(draft.keyword.split(/\s+/u).length <= 7);
  }
  assert.deepEqual(value.capability_profile.conditional_not_enabled, [
    "AUTOTARGETING",
    "SITELINKS",
    "PRODUCT_GALLERY",
    "NETWORK",
  ]);
});

test("requires two independent records of the same pattern before calling a control competitive", async () => {
  const unavailable = await recommendationSet({
    snapshot_id: "snapshot-no-competitors",
    sources: [{ source_kind: "PUBLIC_COMPETITOR", status: "UNAVAILABLE", facts: [] }],
  });
  assert.equal(unavailable.drafts[0].variant.control_basis.kind, "STRATEGY_BASELINE_FALLBACK");

  const singleSource = await recommendationSet({
    snapshot_id: "snapshot-one-competitor",
    sources: [{
      source_id: "competitor-a",
      source_kind: "PUBLIC_COMPETITOR",
      status: "VERIFIED",
      pattern_id: "qualified-action-pattern",
      facts: ["Наблюдение A", "Наблюдение B"],
      evidence_ids: ["evidence-a"],
    }],
  });
  assert.equal(singleSource.drafts[0].variant.control_basis.kind, "STRATEGY_BASELINE_FALLBACK");

  const corroborated = await recommendationSet({
    snapshot_id: "snapshot-with-competitors",
    sources: [
      {
        source_id: "competitor-a",
        source_kind: "PUBLIC_COMPETITOR",
        status: "VERIFIED",
        pattern_id: "qualified-action-pattern",
        facts: ["Наблюдение A"],
        evidence_ids: ["evidence-a"],
      },
      {
        source_id: "competitor-b",
        source_kind: "PUBLIC_COMPETITOR",
        status: "VERIFIED",
        pattern_id: "qualified-action-pattern",
        facts: ["Наблюдение B"],
        evidence_ids: ["evidence-b"],
      },
    ],
  });
  assert.equal(corroborated.drafts[0].variant.control_basis.kind, "COMPETITIVE_NORM_CONTROL");
  assert.equal(corroborated.drafts[0].variant.control_basis.pattern_id, "qualified-action-pattern");
  assert.deepEqual(corroborated.drafts[0].variant.control_basis.evidence_ids, ["evidence-a", "evidence-b"]);
});

test("terminates at one control plus at most two improvements and audits the hidden remainder", async () => {
  const value = await recommendationSet();
  assert.equal(value.termination.contract, "FINITE_NON_RECURSIVE");
  assert.equal(value.termination.all_candidates_terminal, true);
  assert.equal(value.coverage.candidates_total, 4);
  assert.equal(value.coverage.visible_drafts, 3);
  assert.equal(value.coverage.hidden_drafts, 1);
  assert.equal(value.drafts[3].visibility, "HIDDEN");
  assert.equal(value.drafts[3].suppression_reason, "HIDDEN:CAPACITY_LIMIT");
  assert.equal("score" in value.drafts[0], false);
});
