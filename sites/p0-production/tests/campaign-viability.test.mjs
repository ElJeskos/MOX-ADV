import assert from "node:assert/strict";
import test from "node:test";

import { buildCampaignRecommendationSet } from "../lib/campaign-fanout.ts";
import { bundledCuratedPlaybookReleases } from "../lib/campaign-playbook.ts";
import { explainScoreDelta, scoreCampaignDrafts, viabilityScorePolicy } from "../lib/campaign-viability.ts";

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

function claim(predicate, tier = "TIER_1_VERIFIED") {
  return {
    claim_id: `claim-${predicate}`,
    predicate,
    evidence_ids: [`evidence-${predicate}`],
    confidence: {
      source_quality: "A",
      freshness: "current",
      consistency: "corroborated",
      coverage: "complete_for_scope",
      tier,
    },
  };
}

const evidence = {
  snapshot_id: "sha256:analytics-v1",
  summary: { hard_blockers: [] },
  sources: [
    { source_id: "direct", status: "PARTIAL" },
    { source_id: "metrika", status: "VERIFIED" },
  ],
  claims: [
    claim("product"),
    claim("audience"),
    claim("value"),
    claim("qualified_result"),
    claim("campaign_inventory", "TIER_3_INDICATIVE"),
    claim("observed_performance"),
  ],
  material_uncertainties: ["Wordstat unavailable", "Comparable pre-launch cost unavailable"],
  prelaunch_cost: { status: "UNAVAILABLE" },
};

async function recommendationSet(analyticsEvidence = evidence) {
  return buildCampaignRecommendationSet({
    model,
    strategy,
    analyticsEvidence,
    playbookReleases: await bundledCuratedPlaybookReleases(),
    generatedAt: "2026-08-21T12:00:00.000Z",
  });
}

test("computes one deterministic non-predictive score for each hard-eligible Draft", async () => {
  const first = await recommendationSet();
  const second = await recommendationSet();
  assert.deepEqual(first, second);
  assert.equal(first.schema_version, "campaign-recommendation-set-v3");
  assert.equal(first.score_contract.version, "viability-score/1.0.0");

  for (const draft of first.drafts) {
    const score = draft.viability_score;
    assert.equal(score.eligibility.status, "ELIGIBLE");
    assert.equal(Number.isInteger(score.score), true);
    assert.ok(score.score >= 0 && score.score <= 100);
    assert.ok(score.rank >= 1);
    assert.ok(score.score_lower <= score.score && score.score <= score.score_upper);
    assert.equal(score.explanation.label, "COMPARATIVE_PRELAUNCH_PRIORITY_NOT_A_FORECAST");
    assert.equal(score.explanation.landing_audit_used, false);
    assert.equal(score.policy_status, "UNCALIBRATED_POLICY_V1");
  }
});

test("keeps unavailable demand and cost at an explicit midpoint with sensitivity bounds", async () => {
  const value = await recommendationSet();
  const score = value.drafts[0].viability_score;
  assert.equal(score.dimensions.demand.value, 50);
  assert.equal(score.dimensions.cost.value, 50);
  assert.equal(score.dimensions.cost.features[0].status, "UNKNOWN");
  assert.ok(score.score_upper > score.score_lower);
  assert.ok(score.explanation.missing_dimensions.includes("demand"));
  assert.ok(score.explanation.missing_dimensions.includes("cost"));
  assert.equal(value.drafts[0].visibility, "VISIBLE");
});

test("never lets a hard evidence blocker be averaged into the viability score", async () => {
  const blocked = await recommendationSet({
    ...evidence,
    snapshot_id: "sha256:blocked",
    summary: { hard_blockers: ["Direct account capability is unresolved"] },
  });
  for (const draft of blocked.drafts) {
    assert.equal(draft.viability_score.eligibility.status, "BLOCKED_UNKNOWN");
    assert.equal(draft.viability_score.score, null);
    assert.equal(draft.viability_score.rank, null);
  }
});

test("recomputes field-level score delta after a material manual edit", async () => {
  const value = await recommendationSet();
  const previous = value.drafts[0];
  const edited = {
    ...previous,
    draft_revision_id: `${previous.draft_id}-r2`,
    keyword: "общая нерелевантная фраза",
    ad_title: "Другое объявление",
    ad_text: "Текст без продукта, аудитории и предложения",
  };
  const rescored = await scoreCampaignDrafts({
    drafts: value.drafts.map((draft) => draft.draft_id === edited.draft_id ? edited : draft),
    model,
    strategy,
    analyticsEvidence: evidence,
    scoredAt: "2026-08-21T12:05:00.000Z",
  });
  const current = rescored.find((draft) => draft.draft_id === edited.draft_id);
  assert.ok(current.viability_score.score < previous.viability_score.score);
  assert.ok(
    current.viability_score.dimensions.offer_audience_fit.value
      < previous.viability_score.dimensions.offer_audience_fit.value,
  );
  const delta = explainScoreDelta(
    previous.viability_score,
    current.viability_score,
    ["/draft/keyword", "/draft/ad_title", "/draft/ad_text"],
  );
  assert.ok(delta.score.delta < 0);
  assert.deepEqual(delta.changed_pointers, ["/draft/ad_text", "/draft/ad_title", "/draft/keyword"]);
});

test("landing advisory data cannot affect score, rank, threshold or fingerprints", async () => {
  const baseline = await recommendationSet();
  const withLandingAudit = await recommendationSet({
    ...evidence,
    landing_audit: {
      score: 0,
      blockers: ["arbitrary advisory finding"],
      lighthouse: { performance: 1 },
    },
  });
  assert.deepEqual(
    withLandingAudit.drafts.map((draft) => draft.viability_score),
    baseline.drafts.map((draft) => draft.viability_score),
  );
  assert.equal(viabilityScorePolicy.landing_audit_used, false);
});
