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
