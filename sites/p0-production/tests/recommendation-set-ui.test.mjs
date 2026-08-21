import assert from "node:assert/strict";
import { readFile, rm, writeFile } from "node:fs/promises";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

async function loadComponents(t) {
  const sourceUrl = new URL("../app/RecommendationSetDisclosure.tsx", import.meta.url);
  const outputUrl = new URL(`../app/.recommendation-set-ui-test-${process.pid}-${Date.now()}.mjs`, import.meta.url);
  const source = await readFile(sourceUrl, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  await writeFile(outputUrl, compiled, "utf8");
  t.after(() => rm(outputUrl, { force: true }));
  return import(outputUrl.href);
}

const recommendationSet = {
  direct_capability_snapshot_id: "direct-capability:owner-account:core",
  coverage: {
    generated_count: 4,
    visible_count: 3,
    hidden_count: 1,
    reconciliation: { generated_equals_visible_plus_hidden: true },
  },
  capability_profile: {
    profile_id: "direct-v501-unified-search-explicit-text",
    profile_version: "1.0.0",
    campaign_type: "UNIFIED_CAMPAIGN",
    ad_group_type: "UNIFIED_AD_GROUP",
    search_strategy: "WB_MAXIMUM_CLICKS",
    network_strategy: "SERVING_OFF",
    criteria: ["EXPLICIT_KEYWORDS"],
    ad_type: "TEXT_AD",
  },
  playbook_release: {
    status: "ACTIVE_APPROVED",
    release_id: "p0-curated-playbook-2026-08",
    release_version: "1.0.0",
    content_digest: `sha256:${"a".repeat(64)}`,
  },
  candidate_audit: [{
    candidate_id: "playbook-rule:contradicted",
    candidate_type: "PLAYBOOK_RULE",
    playbook_rule_id: "message-offer-contradicted-v1",
    visibility: "HIDDEN",
    reason_code: "HIDDEN:PLAYBOOK_RULE_CONTRADICTED",
    draft_id: null,
  }],
};

test("Recommendation Set UI discloses reconciled audit counts plus exact capability and playbook lineage", async (t) => {
  const { RecommendationSetDisclosure } = await loadComponents(t);
  const html = renderToStaticMarkup(React.createElement(RecommendationSetDisclosure, { recommendationSet }));
  assert.match(html, /4 generated/);
  assert.match(html, /3 visible · 1 hidden · reconciliation OK/);
  assert.match(html, /p0-curated-playbook-2026-08@1.0.0/);
  assert.match(html, /ACTIVE_APPROVED/);
  assert.match(html, /UNIFIED_CAMPAIGN · UNIFIED_AD_GROUP · EXPLICIT_KEYWORDS · TEXT_AD/);
  assert.match(html, /WB_MAXIMUM_CLICKS · Network SERVING_OFF/);
  assert.match(html, /direct-capability:owner-account:core/);
  assert.match(html, /Hidden candidate audit · 1/);
  assert.match(html, /HIDDEN:PLAYBOOK_RULE_CONTRADICTED/);
});

test("Recommendation Set UI distinguishes comparator and one-factor improvement and renders explicit blockers", async (t) => {
  const { DraftPublicationBlockers, DraftTreatmentDelta, DraftVariantLabel } = await loadComponents(t);
  const comparator = { variant: { kind: "CONTROL", control_basis: { kind: "STRATEGY_BASELINE_FALLBACK" } } };
  const improvement = {
    variant: { kind: "IMPROVEMENT" },
    treatment_delta: { changed_family: "QUALIFIED_ACTION", changed_fields: ["/direct/keyword/Keyword", "/direct/ad/TextAd/Text"] },
    publication_blockers: [{
      code: "CONDITIONAL_CAPABILITY_EVIDENCE_MISSING",
      message: "AUTOTARGETING requires persisted official API and exact account eligibility evidence.",
      field_path: "/direct/keyword/AutotargetingSettings",
    }],
  };
  assert.match(renderToStaticMarkup(React.createElement(DraftVariantLabel, { draft: comparator })), /STRATEGY_BASELINE_FALLBACK/);
  assert.match(renderToStaticMarkup(React.createElement(DraftVariantLabel, { draft: improvement })), /IMPROVEMENT · QUALIFIED_ACTION/);
  assert.match(renderToStaticMarkup(React.createElement(DraftTreatmentDelta, { draft: improvement })), /One-factor delta: \/direct\/keyword\/Keyword · \/direct\/ad\/TextAd\/Text/);
  const blockers = renderToStaticMarkup(React.createElement(DraftPublicationBlockers, { draft: improvement }));
  assert.match(blockers, /aria-label="Publication blockers"/);
  assert.match(blockers, /CONDITIONAL_CAPABILITY_EVIDENCE_MISSING/);
  assert.match(blockers, /\/direct\/keyword\/AutotargetingSettings/);
});

function scoreFixture(overrides = {}) {
  const feature = { rule: "known-v1", input_pointers: ["/draft/market_evidence/frequency"], value: 80, status: "KNOWN", midpoint_applied: false, claim_ids: ["claim-demand"], evidence_ids: ["evidence-demand"] };
  const dimension = (value, weight) => ({ state: "KNOWN", value, lower: value, upper: value, weight: weight / 100, weight_percent: weight, weighted_contribution: value * weight / 100, evidence_pointers: [{ input_pointer: "/draft/input", claim_ids: [], evidence_ids: [] }], features: [feature] });
  return {
    contract_version: "viability-score/1.0.0",
    eligibility: { status: "ELIGIBLE", blockers: [] },
    evidence_gaps: { status: "RESOLVED", required: [], optional: [{ code: "PRELAUNCH_COST_UNAVAILABLE" }] },
    score: 72,
    score_raw: 72,
    score_lower: 62,
    score_upper: 82,
    rank: 1,
    tied_draft_ids: ["draft-a", "draft-b"],
    ranking: { status: "RANKED", recommendation_set_id: "recommendation-set-fixed", cohort_id: "capability-cohort:core", comparable_set_id: "comparable-set:core" },
    dimensions: {
      demand: dimension(80, 18),
      cost: { ...dimension(50, 12), state: "UNKNOWN", lower: 0, upper: 100, features: [{ ...feature, rule: "unknown-cost-v1", status: "UNKNOWN", value: 50, midpoint_applied: true }] },
      economics: dimension(70, 20),
      offer_audience_fit: dimension(75, 18),
      direct_feasibility: dimension(100, 12),
      measurement_readiness: dimension(60, 10),
      evidence_quality: dimension(80, 10),
    },
    scopes: {
      frequency: { status: "AVAILABLE", semantics: "LOWER_BOUND_OBSERVED_TOP_ROWS", observed_unique_count: 67, source: "YANDEX_WORDSTAT_V1", method: "/v1/topRequests", snapshot_batch_id: "batch-1", operator_profiles: ["BROAD_CONTAINING"], region_ids: [225], devices: ["desktop"] },
      cost: { status: "UNAVAILABLE", semantics: "ONE_QUALIFIED_PRELAUNCH_SOURCE; SOURCES_NOT_AVERAGED", source: null },
    },
    sensitivity: { unknown_dimensions: ["cost"] },
    visibility: { reason: null, decision: "REVIEW_VISIBLE", gates: { sensitivity_upper: 82, upper_below_threshold: false, evidence_quality: 80, evidence_quality_sufficient: true, unresolved_evidence_gap: false, structural_reason: null } },
    fingerprints: { input: `sha256:${"a".repeat(64)}` },
    ...overrides,
  };
}

test("score disclosure names comparative-not-predictive semantics, contributions, scopes, ties, cohort, sensitivity and threshold", async (t) => {
  const { ViabilityScoreDisclosure } = await loadComponents(t);
  const html = renderToStaticMarkup(React.createElement(ViabilityScoreDisclosure, { score: scoreFixture() }));
  assert.match(html, /COMPARATIVE PRELAUNCH PRIORITY \/ NOT A PREDICTION/);
  assert.match(html, /semantic tie/);
  assert.match(html, /capability-cohort:core/);
  assert.match(html, /comparable-set:core/);
  assert.match(html, /Sensitivity 62–82/);
  assert.match(html, /midpoint 50/);
  assert.match(html, /lower recomputes unknown dimensions at 0/);
  assert.match(html, /Спрос · raw 80 · weight 18% → 14.40 points · KNOWN/);
  assert.match(html, /claim-demand/);
  assert.match(html, /evidence-demand/);
  assert.match(html, /LOWER_BOUND_OBSERVED_TOP_ROWS/);
  assert.match(html, /YANDEX_WORDSTAT_V1/);
  assert.match(html, /SOURCES_NOT_AVERAGED/);
  assert.match(html, /upper 82 &lt; 45: false/);
  assert.match(html, /landing=false · post-launch=false · calibration=false/);
});

test("blocked score disclosure keeps hard blockers and unresolved gaps separate and has no rank", async (t) => {
  const { ViabilityScoreDisclosure } = await loadComponents(t);
  const score = scoreFixture({
    eligibility: { status: "BLOCKED_UNKNOWN", blockers: [{ code: "EVIDENCE_HARD_BLOCKER", remediation: "Resolve Direct evidence", input_pointer: "/analytics_evidence" }] },
    evidence_gaps: { status: "UNRESOLVED", required: [{ code: "DEMAND_EVIDENCE_GAP", description: "Demand unavailable, not zero", input_pointer: "/draft/market_evidence_status" }], optional: [] },
    score: null,
    rank: null,
    dimensions: null,
    ranking: { status: "BLOCKED_EVIDENCE_GAP", cohort_id: "capability-cohort:core" },
  });
  const html = renderToStaticMarkup(React.createElement(ViabilityScoreDisclosure, { score }));
  assert.match(html, /Hard eligibility и required EVIDENCE_GAP оценены до score/);
  assert.match(html, /EVIDENCE_HARD_BLOCKER/);
  assert.match(html, /Unresolved EVIDENCE_GAP/);
  assert.match(html, /DEMAND_EVIDENCE_GAP/);
  assert.match(html, /rank отсутствует/);
  assert.match(html, /Frequency scope/);
  assert.match(html, /Cost scope/);
});
