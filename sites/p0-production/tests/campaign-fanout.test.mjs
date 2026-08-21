import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  buildCampaignRecommendationSet,
  campaignDraftPublishBlockers,
  evaluateDirectCapabilitySelection,
  fingerprintDirectProjection,
  preserveSelectedConditionalProjection,
} from "../lib/campaign-fanout.ts";
import { sealCuratedPlaybookRelease } from "../lib/campaign-playbook.ts";

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

async function recommendationSet(analyticsEvidence = null, overrides = {}) {
  return buildCampaignRecommendationSet({
    model,
    strategy,
    analyticsEvidence,
    playbookReleases: await defaultPlaybookFixtureReleases(),
    directCapabilitySnapshot: coreCapabilitySnapshot,
    generatedAt: "2026-08-21T12:00:00.000Z",
    ...overrides,
  });
}

test("deterministically fans one approved Strategy revision out into multiple complete Drafts", async () => {
  const first = await recommendationSet();
  const second = await recommendationSet();
  assert.deepEqual(first, second);

  const visible = first.drafts.filter((draft) => draft.visibility === "VISIBLE");
  assert.equal(visible.length, 3);
  assert.equal(first.schema_version, "campaign-recommendation-set-v3");
  assert.equal(first.termination.contract, "FINITE_NON_RECURSIVE_ONE_PASS");
  assert.equal(first.termination.recursion_allowed, false);
  assert.equal(first.coverage.generated_count, first.coverage.visible_count + first.coverage.hidden_count);
  assert.equal(first.coverage.generated_count, first.candidate_audit.length);
  assert.equal(first.candidate_audit.every((candidate) => ["VISIBLE", "HIDDEN"].includes(candidate.visibility)), true);
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
  assert.equal(value.coverage.evidence_gap_drafts, 3);
});

test("canonicalizes only provider-declared unordered arrays before fingerprinting", async () => {
  const value = await recommendationSet();
  const projection = value.drafts[0].publish_projection;
  const reordered = structuredClone(projection);
  reordered.direct.ad_group.NegativeKeywords.Items.reverse();
  assert.equal(
    await fingerprintDirectProjection(projection),
    await fingerprintDirectProjection(reordered),
  );
  assert.match(await fingerprintDirectProjection(projection), /^sha256:[a-f0-9]{64}$/u);

  const ordered = structuredClone(projection);
  ordered.direct.campaign.UnifiedCampaign.Settings = [{ Option: "A" }, { Option: "B" }];
  const reversedOrdered = structuredClone(ordered);
  reversedOrdered.direct.campaign.UnifiedCampaign.Settings.reverse();
  assert.notEqual(
    await fingerprintDirectProjection(ordered),
    await fingerprintDirectProjection(reversedOrdered),
  );

  const material = structuredClone(projection);
  material.direct.ad.TextAd.Text = `${material.direct.ad.TextAd.Text} Материальное изменение`;
  assert.notEqual(
    await fingerprintDirectProjection(projection),
    await fingerprintDirectProjection(material),
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
  assert.equal(value.capability_profile.profile_id, "direct-v501-unified-search-explicit-text");
  assert.equal(value.capability_profile.profile_version, "1.0.0");
  assert.equal(value.capability_profile.campaign_type, "UNIFIED_CAMPAIGN");
  assert.equal(value.capability_profile.ad_group_type, "UNIFIED_AD_GROUP");
  assert.deepEqual(value.capability_profile.criteria, ["EXPLICIT_KEYWORDS"]);
  assert.equal(value.capability_profile.ad_type, "TEXT_AD");
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
  assert.equal(corroborated.drafts[0].variant.control_basis.sample_rule_id, "competitive-pattern-independent-sources");
  assert.equal(corroborated.drafts[0].variant.control_basis.sample_rule_version, "1.0.0");
  assert.deepEqual(corroborated.drafts[0].variant.control_basis.evidence_ids, ["evidence-a", "evidence-b"]);
});

test("terminates at one control plus at most two improvements and audits excluded playbook rules", async () => {
  const value = await recommendationSet();
  assert.equal(value.termination.contract, "FINITE_NON_RECURSIVE_ONE_PASS");
  assert.equal(value.termination.all_candidates_terminal, true);
  assert.equal(value.termination.comparators_per_bucket, 1);
  assert.equal(value.termination.maximum_improvements_per_bucket, 2);
  assert.equal(value.drafts.filter((draft) => draft.variant.kind === "CONTROL").length, 1);
  assert.equal(value.drafts.filter((draft) => draft.variant.kind === "IMPROVEMENT").length, 2);
  assert.equal(value.coverage.candidates_total, 4);
  assert.equal(value.coverage.visible_drafts, 3);
  assert.equal(value.coverage.hidden_drafts, 0);
  assert.equal(value.candidate_audit.some((candidate) => candidate.reason_code === "HIDDEN:PLAYBOOK_RULE_CONTRADICTED"), true);
  assert.equal("score" in value.drafts[0], false);
});

function playbookRule(rule_id, overrides = {}) {
  return {
    rule_id,
    rule_version: "1.0.0",
    contract_version: "1.0.0",
    state: "ACTIVE",
    approval_status: "APPROVED",
    changed_family: "QUALIFIED_ACTION",
    mechanism: "Одна проверяемая treatment-гипотеза.",
    changed_fields: ["/direct/keyword/Keyword", "/direct/ad/TextAd/Text"],
    required_capabilities: [],
    evidence_quality: 80,
    priority: 10,
    promotion_policy_id: "test-promotion-policy-v1",
    qualified_evidence_refs: [`test-qualified-evidence:${rule_id}`],
    applicability: { campaign_fanout_contract: "campaign-fanout-v1" },
    ...overrides,
  };
}

async function playbookRelease(rules, overrides = {}) {
  return sealCuratedPlaybookRelease({
    schema_version: "p0-curated-playbook-release-v1",
    contract_version: "1.0.0",
    release_id: "test-curated-release",
    release_version: "1.0.0",
    status: "ACTIVE",
    approval_status: "APPROVED",
    promotion_policy: {
      policy_id: "test-promotion-policy-v1",
      policy_version: "1.0.0",
      content_digest: `sha256:${"b".repeat(64)}`,
    },
    approval_attestation: {
      decision_id: "test-playbook-approval-1",
      actor_id: "test-knowledge-steward",
      actor_role: "KNOWLEDGE_STEWARD",
      approved_at: "2026-08-21T11:00:00.000Z",
    },
    superseded_by_release_id: null,
    rules,
    competitive_sample_rules: [],
    ...overrides,
  });
}

async function defaultPlaybookFixtureReleases() {
  return [await playbookRelease([
    playbookRule("qualified-action-v1", { changed_family: "QUALIFIED_ACTION", priority: 10, evidence_quality: 82 }),
    playbookRule("audience-specificity-v1", { changed_family: "AUDIENCE_SPECIFICITY", priority: 20, evidence_quality: 76 }),
    playbookRule("message-offer-contradicted-v1", { changed_family: "MESSAGE_OFFER", state: "CONTRADICTED", priority: 30, evidence_quality: 70 }),
  ], {
    release_id: "test-curated-release-default",
    competitive_sample_rules: [{
      sample_rule_id: "competitive-pattern-independent-sources",
      sample_rule_version: "1.0.0",
      state: "ACTIVE",
      approval_status: "APPROVED",
      minimum_independent_sources: 2,
      required_source_status: "VERIFIED",
      require_pattern_id: true,
      require_evidence_ids: true,
    }],
  })];
}

const availableDemandEvidence = {
  snapshot_id: "analytics-evidence:packed-demand",
  market_evidence: {
    contract_version: "demand-cost-packing-v1",
    frequency: {
      status: "AVAILABLE",
      snapshot_batch_id: "wordstat-batch-1",
      clusters: [
        { cluster_id: "cluster-primary", status: "AVAILABLE", assigned_row_ids: ["row-1"], semantic_key: { product: "выставка", need: "участие", intent: "commercial", offer: "стенд" } },
        { cluster_id: "cluster-long-tail", status: "AVAILABLE", assigned_row_ids: ["row-2"], semantic_key: { product: "выставка", need: "стенд", intent: "commercial", offer: "участие" } },
      ],
    },
    cost: { status: "UNAVAILABLE", compact_source: null, observations: [] },
  },
};

test("matches the checked-in Recommendation Set identity and disposition golden", async () => {
  const value = await recommendationSet(availableDemandEvidence);
  const actual = {
    schema_version: value.schema_version,
    recommendation_set_id: value.recommendation_set_id,
    capability_profile: `${value.capability_profile.profile_id}@${value.capability_profile.profile_version}`,
    playbook_release: `${value.playbook_release.release_id}@${value.playbook_release.release_version}`,
    coverage: value.coverage,
    termination: value.termination,
    draft_identities: value.drafts.map((draft) => ({
      draft_id: draft.draft_id,
      draft_revision_id: draft.draft_revision_id,
      variant: draft.variant.code,
      playbook_rule_id: draft.playbook_rule_id,
      visibility: draft.visibility,
      suppression_reason: draft.suppression_reason,
      publish_fingerprint: draft.publish_fingerprint,
      changed_fields: draft.treatment_delta?.changed_fields ?? [],
    })),
    candidate_dispositions: value.candidate_audit.map((candidate) => ({
      candidate_id: candidate.candidate_id,
      visibility: candidate.visibility,
      reason_code: candidate.reason_code,
    })),
  };
  const expected = JSON.parse(await readFile(new URL("./fixtures/recommendation-set-golden.json", import.meta.url), "utf8"));
  assert.deepEqual(actual, expected);
});

test("packs compatible keyword clusters before a finite product-audience-offer fan-out", async () => {
  const value = await recommendationSet(availableDemandEvidence);
  assert.equal(value.delivery_packing.delivery_buckets.length, 1);
  assert.deepEqual(value.delivery_packing.delivery_buckets[0].demand_cluster_ids, ["cluster-long-tail", "cluster-primary"]);
  assert.equal(value.axis_ledger.products.length, 1);
  assert.equal(value.axis_ledger.audiences.length, 1);
  assert.equal(value.axis_ledger.offers.length, 1);
  assert.equal(value.axis_ledger.keyword_clusters.length, 2);
  assert.equal(value.axis_ledger.leafs.length, 2);
  assert.equal(value.axis_ledger.every_leaf_terminal, true);
  assert.equal(value.coverage.status, "COMPLETE");
  assert.equal(value.coverage.represented_leaf_ids.length, 2);
  assert.deepEqual(value.coverage.uncovered_leaf_ids, []);
  assert.equal(value.drafts.length, 3);
  assert.equal(value.drafts.every((draft) => draft.demand_cluster_ids.length === 2), true);
});

test("reconciles canonical leaf coverage for cluster IDs that require normalization", async () => {
  const evidence = structuredClone(availableDemandEvidence);
  evidence.market_evidence.frequency.clusters = [{
    cluster_id: "Cluster Mixed Case",
    status: "AVAILABLE",
    assigned_row_ids: ["row-mixed"],
    semantic_key: { product: "выставка", need: "участие", intent: "commercial", offer: "стенд" },
  }];
  const value = await recommendationSet(evidence);
  assert.equal(value.axis_ledger.leafs[0].keyword_cluster_id, "keyword-cluster:cluster-mixed-case");
  assert.equal(value.drafts.every((draft) => draft.covered_leaf_ids.includes(value.axis_ledger.leafs[0].leaf_id)), true);
  assert.deepEqual(value.coverage.uncovered_leaf_ids, []);
  assert.equal(value.coverage.status, "COMPLETE");
});

test("emits exactly one comparator and at most two improvements for every evidence-backed delivery bucket", async () => {
  const evidence = structuredClone(availableDemandEvidence);
  const secondary = evidence.market_evidence.frequency.clusters[1];
  secondary.delivery_key = {
    goal: "Получать заявки на участие",
    economics: { weekly_budget_rub: 10_000, target_cpa_rub: 2_000 },
    geography: "Россия",
    landing: "https://innoprom.com/participant/",
    message: "Отдельный подтверждённый message regime",
    management: "direct-v501-unified-search-explicit-text@1.0.0",
  };
  secondary.provisional_monthly_budget = 3_000;
  secondary.capacity = {
    status: "AVAILABLE",
    source: "LEGACY_LIVE4_SCENARIO",
    scope: "DEDUPLICATED_DELIVERY_PACK",
    demand_cluster_ids: ["cluster-long-tail"],
    forecast_clicks: 20,
    forecast_total_spend: 3_500,
  };
  const value = await recommendationSet(evidence);
  assert.equal(value.termination.delivery_buckets, 2);
  assert.equal(value.drafts.length, 6);
  for (const bucket of value.delivery_packing.delivery_buckets) {
    const bucketDrafts = value.drafts.filter((draft) => draft.delivery_bucket_id === bucket.delivery_bucket_id);
    assert.equal(bucketDrafts.filter((draft) => draft.variant.kind === "CONTROL").length, 1);
    assert.ok(bucketDrafts.filter((draft) => draft.variant.kind === "IMPROVEMENT").length <= 2);
  }
});

test("records a material one-family delta from each improvement to its bucket comparator", async () => {
  const value = await recommendationSet(availableDemandEvidence);
  const comparator = value.drafts.find((draft) => draft.variant.kind === "CONTROL");
  const improvements = value.drafts.filter((draft) => draft.variant.kind === "IMPROVEMENT");
  assert.equal(improvements.length, 2);
  for (const improvement of improvements) {
    assert.equal(improvement.variant.comparator_draft_id, comparator.draft_id);
    assert.equal(improvement.treatment_delta.comparator_draft_id, comparator.draft_id);
    assert.equal(improvement.treatment_delta.material, true);
    assert.equal(improvement.treatment_delta.exactly_one_hypothesis_family, true);
    assert.equal(improvement.treatment_delta.changed_family, improvement.variant.hypothesis.changed_family);
    assert.deepEqual(improvement.treatment_delta.changed_fields, improvement.treatment_delta.expected_changed_fields);
  }
});

test("deduplicates identical treatment projections without losing the audited candidate", async () => {
  const release = await playbookRelease([
    playbookRule("qualified-action-a", { priority: 1 }),
    playbookRule("qualified-action-b", { priority: 2 }),
  ]);
  const value = await recommendationSet(availableDemandEvidence, { playbookReleases: [release] });
  const duplicates = value.drafts.filter((draft) => draft.suppression_reason === "HIDDEN:DUPLICATE_OR_OVERLAP");
  assert.equal(duplicates.length, 1);
  assert.ok(duplicates[0].duplicate_of);
  assert.equal(value.candidate_audit.some((candidate) => candidate.draft_id === duplicates[0].draft_id && candidate.visibility === "HIDDEN"), true);
  assert.equal(value.coverage.generated_count, value.coverage.visible_count + value.coverage.hidden_count);
});

test("filters curated releases and rule states fail closed while pinning exact active lineage", async () => {
  const release = await playbookRelease([
    playbookRule("active-rule"),
    playbookRule("quarantined-rule", { state: "QUARANTINED", priority: 20 }),
    playbookRule("contradicted-rule", { state: "CONTRADICTED", priority: 30 }),
    playbookRule("deactivated-rule", { state: "DEACTIVATED", priority: 40 }),
    playbookRule("unapproved-rule", { approval_status: "UNAPPROVED", priority: 50 }),
    playbookRule("unknown-version-rule", { contract_version: "99.0.0", priority: 60 }),
  ]);
  const value = await recommendationSet(availableDemandEvidence, { playbookReleases: [release] });
  assert.equal(value.playbook_release.status, "ACTIVE_APPROVED");
  assert.equal(value.playbook_release.release_id, "test-curated-release");
  assert.match(value.playbook_release.content_digest, /^sha256:[a-f0-9]{64}$/u);
  assert.deepEqual(value.playbook_release.applied_rule_ids, ["active-rule"]);
  assert.deepEqual(value.drafts.map((draft) => draft.playbook_rule_id).filter(Boolean), ["active-rule"]);
  for (const reason of [
    "HIDDEN:PLAYBOOK_RULE_QUARANTINED",
    "HIDDEN:PLAYBOOK_RULE_CONTRADICTED",
    "HIDDEN:PLAYBOOK_RULE_DEACTIVATED",
    "HIDDEN:PLAYBOOK_RULE_UNAPPROVED",
    "HIDDEN:PLAYBOOK_RULE_UNKNOWN_VERSION",
  ]) assert.equal(value.candidate_audit.some((candidate) => candidate.reason_code === reason), true);
});

test("excludes unavailable, superseded, malformed, unapproved and unknown-version releases fail closed", async () => {
  const quarantined = await playbookRelease([], { release_id: "release-quarantined", status: "QUARANTINED" });
  const superseded = await playbookRelease([], { release_id: "release-superseded", superseded_by_release_id: "release-next" });
  const unapproved = await playbookRelease([], { release_id: "release-unapproved", approval_status: "UNAPPROVED", approval_attestation: null });
  const unknown = await playbookRelease([], { release_id: "release-unknown", contract_version: "99.0.0" });
  const malformed = { ...await playbookRelease([], { release_id: "release-malformed" }), content_digest: "sha256:invalid" };
  const value = await recommendationSet(availableDemandEvidence, {
    playbookReleases: [quarantined, superseded, unapproved, unknown, malformed],
  });
  assert.equal(value.playbook_release.status, "BLOCKED_FAIL_CLOSED");
  assert.equal(value.drafts.length, 1);
  assert.equal(value.drafts[0].publish_eligibility, "BLOCKED_HARD");
  for (const reason of [
    "HIDDEN:PLAYBOOK_RELEASE_QUARANTINED",
    "HIDDEN:PLAYBOOK_RELEASE_SUPERSEDED",
    "HIDDEN:PLAYBOOK_RELEASE_UNAPPROVED",
    "HIDDEN:PLAYBOOK_RELEASE_UNKNOWN_VERSION",
    "HIDDEN:PLAYBOOK_RELEASE_MALFORMED",
    "HIDDEN:PLAYBOOK_NO_ACTIVE_APPROVED_RELEASE",
  ]) assert.equal(value.candidate_audit.some((candidate) => candidate.reason_code === reason), true);
});

test("blocks conditional or unknown selected fields without silently dropping them", async () => {
  const missingCore = await recommendationSet(availableDemandEvidence, { directCapabilitySnapshot: null });
  assert.equal(missingCore.drafts.every((draft) => draft.publish_eligibility === "BLOCKED_HARD"), true);
  assert.equal(missingCore.drafts.every((draft) => campaignDraftPublishBlockers(draft).some((message) => message.includes("persisted exact account snapshot"))), true);

  const conditionalField = "/direct/keyword/AutotargetingSettings";
  const unavailable = evaluateDirectCapabilitySelection({
    selectedFields: [conditionalField],
    requiredCapabilities: ["AUTOTARGETING"],
    snapshot: null,
  });
  assert.equal(unavailable.eligible, false);
  assert.deepEqual(unavailable.unsupported_fields, [conditionalField]);
  assert.equal(unavailable.blockers[0].code, "CONDITIONAL_CAPABILITY_EVIDENCE_MISSING");

  const unknown = evaluateDirectCapabilitySelection({ selectedFields: ["/direct/ad/TextAd/UnsupportedFutureField"] });
  assert.equal(unknown.eligible, false);
  assert.equal(unknown.blockers[0].code, "UNSUPPORTED_SELECTED_FIELD");

  const snapshot = {
    ...coreCapabilitySnapshot,
    snapshot_id: "direct-capability:owner-account:1",
    conditional_capabilities: [{
      capability: "AUTOTARGETING",
      field_paths: [conditionalField],
      official_api_check: { source: "YANDEX_DIRECT_API_V501", endpoint: "Keywords.add/get", method: "ACCOUNT_PREFLIGHT", evidence_id: "api-evidence-1", verified: true },
      account_eligibility_check: { account: "owner-account", evidence_id: "account-evidence-1", eligible: true },
    }],
  };
  assert.equal(evaluateDirectCapabilitySelection({ selectedFields: [conditionalField], snapshot }).eligible, true);

  const conditionalRelease = await playbookRelease([playbookRule("autotargeting-rule", {
    changed_family: "CRITERIA_AUTOTARGETING",
    changed_fields: [conditionalField],
    required_capabilities: ["AUTOTARGETING"],
  })]);
  const blocked = await recommendationSet(availableDemandEvidence, { playbookReleases: [conditionalRelease] });
  const blockedDraft = blocked.drafts.find((draft) => draft.playbook_rule_id === "autotargeting-rule");
  assert.ok(blockedDraft.publish_projection.direct.keyword.AutotargetingSettings);
  assert.deepEqual(blockedDraft.unsupported_fields, [conditionalField]);
  assert.equal(blockedDraft.visibility, "HIDDEN");
  assert.equal(blockedDraft.publish_eligibility, "BLOCKED_HARD");
  assert.equal(blocked.candidate_audit.some((candidate) => candidate.draft_id === blockedDraft.draft_id && candidate.reason_code === "HIDDEN:HARD_INELIGIBLE:UNSUPPORTED_CAPABILITY"), true);

  const eligible = await recommendationSet(availableDemandEvidence, { playbookReleases: [conditionalRelease], directCapabilitySnapshot: snapshot });
  const eligibleDraft = eligible.drafts.find((draft) => draft.playbook_rule_id === "autotargeting-rule");
  assert.equal(eligibleDraft.visibility, "VISIBLE");
  assert.equal(eligibleDraft.publish_eligibility, "ELIGIBLE");
  assert.equal(eligibleDraft.direct_capability_snapshot_id, snapshot.snapshot_id);

  const ownerEditedProjection = structuredClone(eligibleDraft.publish_projection);
  delete ownerEditedProjection.direct.keyword.AutotargetingSettings;
  ownerEditedProjection.direct.ad.TextAd.Text = "Owner-edited text";
  const preserved = preserveSelectedConditionalProjection({
    generatedDraft: eligibleDraft,
    editedProjection: ownerEditedProjection,
    snapshot,
  });
  assert.deepEqual(
    preserved.projection.direct.keyword.AutotargetingSettings,
    eligibleDraft.publish_projection.direct.keyword.AutotargetingSettings,
  );
  assert.equal(preserved.projection.direct.ad.TextAd.Text, "Owner-edited text");
  assert.equal(preserved.capability_selection.eligible, true);
});

test("pins Strategy, Draft, capability profile and playbook IDs in immutable Draft identity", async () => {
  const value = await recommendationSet(availableDemandEvidence);
  for (const draft of value.drafts) {
    assert.equal(draft.strategy_revision_id, strategy.strategy_revision_id);
    assert.match(draft.draft_revision_id, new RegExp(`^${draft.draft_id}-r1$`, "u"));
    assert.equal(draft.capability_profile_id, value.capability_profile.profile_id);
    assert.equal(draft.capability_profile_version, value.capability_profile.profile_version);
    assert.equal(draft.playbook_release_id, value.playbook_release.release_id);
    assert.match(draft.publish_fingerprint, /^sha256:[a-f0-9]{64}$/u);
    assert.equal(draft.publish_projection.lineage.draft_revision_id, draft.draft_revision_id);
    assert.equal(draft.publish_projection.lineage.capability_profile_version, draft.capability_profile_version);
  }
  const nextStrategy = { ...strategy, strategy_revision_id: "campaign-strategy-r8" };
  const next = await buildCampaignRecommendationSet({
    model,
    strategy: nextStrategy,
    analyticsEvidence: availableDemandEvidence,
    playbookReleases: await defaultPlaybookFixtureReleases(),
    directCapabilitySnapshot: coreCapabilitySnapshot,
    generatedAt: "2026-08-21T12:00:00.000Z",
  });
  assert.notEqual(next.drafts[0].draft_id, value.drafts[0].draft_id);
});
