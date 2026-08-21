import assert from "node:assert/strict";
import test from "node:test";

import {
  buildCampaignRecommendationSet,
  fingerprintDirectProjection,
} from "../lib/campaign-fanout.ts";
import { sealCuratedPlaybookRelease } from "../lib/campaign-playbook.ts";
import {
  evaluateScoreVisibility,
  explainScoreDelta,
  scoreCampaignDrafts,
  viabilityScorePolicy,
} from "../lib/campaign-viability.ts";

const model = {
  product: "Участие со стендом в выставке ИННОПРОМ",
  audience: "Руководители промышленных компаний",
  value: "Встречи с заказчиками и промышленными партнёрами",
  qualified_result: "Отправленная заявка на участие",
};

const strategy = {
  strategy_revision_id: "campaign-strategy-r7",
  goal: "Получать заявки на участие",
  advertised_offer: model.product,
  target_audience: model.audience,
  qualified_result: model.qualified_result,
  exclusions: "Вакансии и бесплатные билеты",
  geography: "Россия",
  period_start: "2026-09-01",
  period_end: "2026-09-30",
  landing_page: "https://innoprom.com/participant/",
  weekly_budget_rub: "10000",
  target_cpa_rub: "2000",
  message: "Подайте заявку на участие в выставке",
};

const coreCapabilitySnapshot = {
  schema_version: "direct-account-capability-snapshot-v1",
  snapshot_id: "direct-capability:owner-account:core",
  observed_at: "2026-08-21T11:59:00.000Z",
  source: "YANDEX_DIRECT_API_V501",
  account: "owner-account",
  api_version: "v501",
  archived: "NO",
  currency: "RUB",
  edit_campaigns_grant: "YES",
  available_campaign_types: ["UNIFIED_CAMPAIGN"],
  restrictions: [],
  conditional_capabilities: [],
};

function claim(predicate, tier = "TIER_1_VERIFIED") {
  return {
    claim_id: `claim-${predicate}`,
    predicate,
    evidence_ids: [`evidence-${predicate}`],
    confidence: {
      quality: "A",
      freshness: "current",
      consistency: "corroborated",
      coverage: "complete_for_scope",
      uncertainty: [],
      tier,
    },
  };
}

function evidence(overrides = {}) {
  return {
    snapshot_id: "sha256:analytics-v1",
    summary: { hard_blockers: [] },
    sources: [
      { source_id: "direct", status: "PARTIAL", scope: { client_login: "owner-account" }, evidence_ids: ["evidence-direct"] },
      { source_id: "metrika", status: "VERIFIED", scope: { counter_id: "42", goal_id: "7" }, evidence_ids: ["evidence-metrika"] },
    ],
    claims: [
      claim("product"),
      claim("audience"),
      claim("value"),
      claim("qualified_result"),
      claim("campaign_inventory", "TIER_3_INDICATIVE"),
      claim("observed_performance"),
      claim("measurement_goal_mapping"),
      claim("measurement_landing_binding"),
      claim("measurement_attribution_contract"),
      claim("measurement_maturity_contract"),
    ],
    gaps: [],
    material_uncertainties: [],
    market_evidence: {
      contract_version: "demand-cost-packing-v1",
      frequency: {
        status: "AVAILABLE",
        source: "YANDEX_WORDSTAT_V1",
        method: "/v1/topRequests",
        snapshot_batch_id: "wordstat-batch-1",
        declared_window: "rolling_last_30_days",
        observed_unique_count: { value: 67, semantics: "LOWER_BOUND_OBSERVED_TOP_ROWS" },
        scopes: [{ operator_profile: "BROAD_CONTAINING", region_ids: [225], device: "desktop", observed_unique_count: { value: 67 } }],
        has_search_volume: { all_devices: "YES" },
        seasonality: { status: "AVAILABLE", ratio: 1.1 },
        unique_assigned_rows: [{ row_id: "row-1", provenance: { call_ids: ["wordstat-call-1"] } }],
        clusters: [{
          cluster_id: "cluster-primary",
          status: "AVAILABLE",
          assigned_row_ids: ["row-1"],
          semantic_key: { product: "выставка", need: "участие", intent: "commercial", offer: "стенд" },
        }],
        gaps: [],
      },
      cost: {
        status: "AVAILABLE",
        compact_source: "DIRECT_HISTORY_OWN_EMPIRICAL",
        scenario: "day-level P25-P75",
        scope: { account: "owner-account", phrase: "CLUSTER", geography: "SAME", placement: "SAME", strategy: "SAME", season: "SAME" },
        as_of: "2026-08-20T00:00:00.000Z",
        currency: "RUB",
        vat_treatment: "INCLUDED",
        sample_size: { unit: "clicks", value: 42 },
        range: { low: 110, high: 170, kind: "EMPIRICAL_IQR" },
        observations: [{ source: "DIRECT_HISTORY_OWN_EMPIRICAL", evidence_ids: ["cost-observation-1"] }],
      },
    },
    ...overrides,
  };
}

async function playbookFixture() {
  const rule = (rule_id, changed_family, priority) => ({
    rule_id,
    rule_version: "1.0.0",
    contract_version: "1.0.0",
    state: "ACTIVE",
    approval_status: "APPROVED",
    changed_family,
    mechanism: "Deterministic test-only improvement.",
    changed_fields: ["/direct/keyword/Keyword", "/direct/ad/TextAd/Text"],
    required_capabilities: [],
    evidence_quality: 80,
    priority,
    promotion_policy_id: "test-promotion-policy-v1",
    qualified_evidence_refs: [`test-evidence:${rule_id}`],
    applicability: { campaign_fanout_contract: "campaign-fanout-v1" },
  });
  return [await sealCuratedPlaybookRelease({
    schema_version: "p0-curated-playbook-release-v1",
    contract_version: "1.0.0",
    release_id: "test-viability-release",
    release_version: "1.0.0",
    status: "ACTIVE",
    approval_status: "APPROVED",
    promotion_policy: { policy_id: "test-promotion-policy-v1", policy_version: "1.0.0", content_digest: `sha256:${"c".repeat(64)}` },
    approval_attestation: { decision_id: "test-decision", actor_id: "test-steward", actor_role: "KNOWLEDGE_STEWARD", approved_at: "2026-08-21T11:00:00.000Z" },
    superseded_by_release_id: null,
    rules: [rule("qualified-action-v1", "QUALIFIED_ACTION", 10), rule("audience-specificity-v1", "AUDIENCE_SPECIFICITY", 20)],
    competitive_sample_rules: [],
  })];
}

async function recommendationSet(analyticsEvidence = evidence()) {
  return buildCampaignRecommendationSet({
    model,
    strategy,
    analyticsEvidence,
    playbookReleases: await playbookFixture(),
    directCapabilitySnapshot: coreCapabilitySnapshot,
    generatedAt: "2026-08-21T12:00:00.000Z",
  });
}

async function rescore(drafts, analyticsEvidence = evidence(), overrides = {}) {
  return scoreCampaignDrafts({
    recommendationSetId: "recommendation-set:fixed-test-revision",
    drafts,
    model,
    strategy,
    analyticsEvidence,
    scoredAt: "2026-08-21T12:00:00.000Z",
    ...overrides,
  });
}

test("uses the exact versioned weights and discloses deterministic contributions", async () => {
  assert.deepEqual(viabilityScorePolicy.weights_percent, {
    demand: 18,
    cost: 12,
    economics: 20,
    offer_audience_fit: 18,
    direct_feasibility: 12,
    measurement_readiness: 10,
    evidence_quality: 10,
  });
  assert.equal(viabilityScorePolicy.weight_sum_percent, 100);

  const first = await recommendationSet();
  const second = await recommendationSet();
  assert.deepEqual(first, second);
  for (const draft of first.drafts) {
    const result = draft.viability_score;
    assert.equal(result.eligibility.status, "ELIGIBLE");
    assert.equal(result.evidence_gaps.status, "RESOLVED");
    assert.equal(result.explanation.label, "COMPARATIVE PRELAUNCH PRIORITY / NOT A PREDICTION");
    assert.equal(result.explanation.calibration_used, false);
    assert.equal(result.ranking.recommendation_set_id, first.recommendation_set_id);
    assert.equal(result.ranking.status, "RANKED");
    assert.ok(result.ranking.cohort_id);
    assert.ok(result.ranking.comparable_set_id);
    assert.equal(
      Number(Object.values(result.dimensions).reduce((sum, dimension) => sum + dimension.weighted_contribution, 0).toFixed(4)),
      result.score_raw,
    );
    for (const dimension of Object.values(result.dimensions)) {
      assert.ok(["KNOWN", "UNKNOWN"].includes(dimension.state));
      assert.ok(Array.isArray(dimension.evidence_pointers));
      assert.equal(dimension.weighted_contribution, dimension.weighted_points);
    }
  }
});

test("evaluates hard eligibility and required EVIDENCE_GAP before score or rank", async () => {
  const hardBlocked = await recommendationSet(evidence({
    summary: { hard_blockers: ["Direct account capability is unresolved"] },
  }));
  for (const draft of hardBlocked.drafts) {
    assert.equal(draft.viability_score.eligibility.status, "BLOCKED_UNKNOWN");
    assert.equal(draft.viability_score.score, null);
    assert.equal(draft.viability_score.rank, null);
    assert.equal(draft.shortlist_eligible, false);
    assert.equal(draft.publish_eligibility, "ELIGIBLE", "score must not rewrite the existing structural publication decision");
  }

  const unavailableDemand = evidence();
  unavailableDemand.market_evidence.frequency = {
    status: "UNAVAILABLE",
    source: "YANDEX_WORDSTAT_V1",
    method: "/v1/topRequests",
    snapshot_batch_id: "wordstat-batch-gap",
    observed_unique_count: { value: null, semantics: "UNAVAILABLE_NOT_ZERO" },
    clusters: [],
    gaps: [{ code: "WORDSTAT_PROVIDER_UNAVAILABLE", detail: "Provider unavailable" }],
  };
  const gapBlocked = await recommendationSet(unavailableDemand);
  for (const draft of gapBlocked.drafts) {
    assert.equal(draft.viability_score.evidence_gaps.status, "UNRESOLVED");
    assert.ok(draft.viability_score.evidence_gaps.required.some((gap) => gap.code === "DEMAND_EVIDENCE_GAP"));
    assert.equal(draft.viability_score.score, null);
    assert.equal(draft.viability_score.rank, null);
    assert.equal(draft.visibility, "VISIBLE", "required missing evidence stays review-visible");
    assert.equal(draft.shortlist_eligible, false);
  }
});

test("uses disclosed midpoint 50 and dimension-level 0/100 sensitivity for optional unknowns", async () => {
  const optional = evidence();
  optional.market_evidence.cost = {
    status: "UNAVAILABLE",
    compact_source: null,
    scenario: null,
    scope: null,
    as_of: null,
    currency: null,
    vat_treatment: null,
    sample_size: null,
    range: null,
    observations: [],
  };
  optional.gaps = [{ gap_id: "gap-cost", code: "PRELAUNCH_COST_UNAVAILABLE", source_id: "direct", description: "No comparable cost source", material: false }];
  const value = await recommendationSet(optional);
  const result = value.drafts[0].viability_score;
  assert.equal(result.score === null, false);
  assert.equal(result.dimensions.cost.state, "UNKNOWN");
  assert.equal(result.dimensions.cost.value, 50);
  assert.equal(result.dimensions.cost.lower, 0);
  assert.equal(result.dimensions.cost.upper, 100);
  assert.equal(result.dimensions.cost.midpoint.applied, true);
  assert.ok(result.sensitivity.unknown_dimensions.includes("cost"));
  assert.equal(result.sensitivity.lower.unknown_dimensions_value, 0);
  assert.equal(result.sensitivity.upper.unknown_dimensions_value, 100);
  assert.ok(result.score_lower < result.score && result.score < result.score_upper);
  assert.ok(result.evidence_gaps.optional.some((gap) => gap.code === "PRELAUNCH_COST_UNAVAILABLE"));
});

test("preserves exact semantic ties only inside the fixed Recommendation Set capability cohort", async () => {
  const generated = await recommendationSet();
  const source = generated.drafts[0];
  const clone = (id, selectedCapabilities = []) => ({
    ...structuredClone(source),
    draft_id: id,
    draft_revision_id: `${id}-r1`,
    capability_selection: {
      ...structuredClone(source.capability_selection),
      eligible: true,
      selected_capabilities: selectedCapabilities,
      selected_fields: selectedCapabilities.map((item) => `/conditional/${item}`),
      blockers: [],
    },
    viability_score: undefined,
  });
  const scored = await rescore([
    clone("draft-a1"),
    clone("draft-a2"),
    clone("draft-b1", ["SITELINKS"]),
    clone("draft-b2", ["SITELINKS"]),
  ]);
  const [a1, a2, b1, b2] = scored.map((draft) => draft.viability_score);
  assert.equal(a1.rank, 1);
  assert.equal(a2.rank, 1);
  assert.deepEqual(a1.tied_draft_ids, ["draft-a1", "draft-a2"]);
  assert.equal(b1.rank, 1);
  assert.equal(b2.rank, 1);
  assert.deepEqual(b1.tied_draft_ids, ["draft-b1", "draft-b2"]);
  assert.equal(a1.ranking.cohort_id, a2.ranking.cohort_id);
  assert.notEqual(a1.ranking.cohort_id, b1.ranking.cohort_id);
  assert.notEqual(a1.ranking.comparable_set_id, b1.ranking.comparable_set_id);
});

test("applies strict score hiding gates and gives structural reasons precedence", () => {
  const hidden = evaluateScoreVisibility({
    structuralReason: null,
    sensitivityUpper: 44.9999,
    evidenceQuality: 60,
    unresolvedEvidenceGap: false,
  });
  assert.equal(hidden.status, "HIDDEN");
  assert.equal(hidden.reason, "HIDDEN:VIABILITY_SENSITIVITY_UPPER_BELOW_45_V1");
  assert.equal(hidden.gates.applied_by_score, true);

  for (const input of [
    { sensitivityUpper: 45, evidenceQuality: 100, unresolvedEvidenceGap: false },
    { sensitivityUpper: 20, evidenceQuality: 59.9999, unresolvedEvidenceGap: false },
    { sensitivityUpper: 20, evidenceQuality: 100, unresolvedEvidenceGap: true },
  ]) {
    assert.equal(evaluateScoreVisibility({ structuralReason: null, ...input }).status, "VISIBLE");
  }

  const structural = evaluateScoreVisibility({
    structuralReason: "HIDDEN:DUPLICATE_OR_OVERLAP",
    sensitivityUpper: 20,
    evidenceQuality: 100,
    unresolvedEvidenceGap: false,
  });
  assert.equal(structural.status, "HIDDEN");
  assert.equal(structural.reason, "HIDDEN:DUPLICATE_OR_OVERLAP");
  assert.equal(structural.decision, "STRUCTURAL_REASON_PRECEDENCE");
  assert.equal(structural.gates.applied_by_score, false);
});

test("discloses bounded evidence pointers and exact frequency/cost scopes", async () => {
  const value = await recommendationSet();
  const result = value.drafts[0].viability_score;
  assert.equal(result.scopes.frequency.semantics, "LOWER_BOUND_OBSERVED_TOP_ROWS");
  assert.equal(result.scopes.frequency.source, "YANDEX_WORDSTAT_V1");
  assert.equal(result.scopes.frequency.method, "/v1/topRequests");
  assert.equal(result.scopes.frequency.snapshot_batch_id, "wordstat-batch-1");
  assert.deepEqual(result.scopes.frequency.operator_profiles, ["BROAD_CONTAINING"]);
  assert.deepEqual(result.scopes.frequency.region_ids, [225]);
  assert.deepEqual(result.scopes.frequency.devices, ["desktop"]);
  assert.equal(result.scopes.cost.source, "DIRECT_HISTORY_OWN_EMPIRICAL");
  assert.equal(result.scopes.cost.scenario, "day-level P25-P75");
  assert.equal(result.scopes.cost.currency, "RUB");
  assert.equal(result.scopes.cost.vat_treatment, "INCLUDED");
  assert.deepEqual(result.scopes.cost.sample_size, { unit: "clicks", value: 42 });
  assert.ok(Object.values(result.dimensions).every((dimension) => dimension.evidence_pointers.length <= 32));
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
  const rescored = await rescore(value.drafts.map((draft) => draft.draft_id === edited.draft_id ? edited : draft));
  const current = rescored.find((draft) => draft.draft_id === edited.draft_id);
  assert.ok(current.viability_score.score < previous.viability_score.score);
  const delta = explainScoreDelta(previous.viability_score, current.viability_score, ["/draft/keyword", "/draft/ad_title", "/draft/ad_text"]);
  assert.ok(delta.score.delta < 0);
  assert.deepEqual(delta.changed_pointers, ["/draft/ad_text", "/draft/ad_title", "/draft/keyword"]);
});

test("LandingAdvisoryRun and post-launch outcomes cannot affect decisions or fingerprints", async () => {
  const baselineSet = await recommendationSet();
  const contaminatedEvidence = evidence({
    landing_advisory_run: { score: 0, blockers: ["advisory only"] },
    post_launch_outcomes: { cpa: 1, conversions: 999 },
    outcome_learning: { calibrated_probability: 0.99 },
  });
  const contaminatedStrategy = {
    ...strategy,
    landing_advisory_run: { status: "ISSUE_OBSERVED" },
    post_launch_outcomes: [{ status: "ACCEPTED" }],
  };
  const contaminatedModel = {
    ...model,
    landing_advisory: { performance_score: 0 },
    campaign_outcome: { cpa: 1 },
  };
  const contaminatedDrafts = baselineSet.drafts.map((draft) => {
    const contaminated = structuredClone(draft);
    contaminated.landing_advisory_run = { status: "COMPLETE" };
    contaminated.moderation_outcome = { status: "ACCEPTED" };
    contaminated.post_launch_metrics = { conversions: 1000 };
    contaminated.market_evidence.frequency.post_launch_outcome = { visits: 999 };
    contaminated.market_evidence.cost.scope.post_launch_cpa = 1;
    contaminated.market_evidence.cost.post_launch_calibration = { probability: 0.99 };
    contaminated.viability_score = undefined;
    return contaminated;
  });
  const baseline = await rescore(baselineSet.drafts);
  const contaminated = await rescore(contaminatedDrafts, contaminatedEvidence, {
    strategy: contaminatedStrategy,
    model: contaminatedModel,
  });
  assert.deepEqual(contaminated.map((draft) => draft.viability_score), baseline.map((draft) => draft.viability_score));

  const projection = baselineSet.drafts[0].publish_projection;
  const contaminatedProjection = structuredClone(projection);
  contaminatedProjection.direct.post_launch_outcome = { cpa: 1 };
  contaminatedProjection.direct.moderation_outcome = { status: "ACCEPTED" };
  contaminatedProjection.direct.landing_advisory_run = { score: 100 };
  assert.equal(await fingerprintDirectProjection(contaminatedProjection), await fingerprintDirectProjection(projection));

  const regenerated = await recommendationSet(contaminatedEvidence);
  assert.deepEqual(regenerated, baselineSet);
  assert.equal(viabilityScorePolicy.forbidden_inputs.includes("LandingAdvisoryRun"), true);
  assert.equal(viabilityScorePolicy.post_launch_inputs_used, false);
});
