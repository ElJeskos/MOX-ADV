import assert from "node:assert/strict";
import test from "node:test";

import {
  ANALYTICS_EVIDENCE_SCHEMA,
  AnalyticsEvidenceError,
  buildAnalyticsEvidence,
  verifyAnalyticsEvidenceSnapshot,
} from "../lib/analytics-evidence.ts";

function fixture({ sampled = false, sensitive = false, lag = 0, missing = [], competitors = [] } = {}) {
  return {
    generatedAt: "2026-08-21T10:05:00.000Z",
    site: {
      fetched_at: "2026-08-21T10:00:00.000Z",
      url: "https://owner.example/",
      pages: [{
        url: "https://owner.example/",
        title: "Owner",
        description: "Международная промышленная выставка",
        headings: ["Стать участником"],
        forms_detected: 1,
        text_excerpt: "Международная промышленная выставка для руководителей компаний.",
      }],
      research: { pages_analyzed: 1, scope: "FIRST_PARTY_PUBLIC_HTTPS" },
    },
    model: {
      product: "Участие в промышленной выставке",
      audience: "Руководители компаний",
      value: "Найти партнёров",
      qualified_result: "Заявка на участие",
      exclusions: "Посетители без заявки",
      missing_questions: missing,
      field_evidence: {
        product: {
          confidence: "MEDIUM",
          source_url: "https://owner.example/",
          quote: "Международная промышленная выставка",
        },
        audience: {
          confidence: "OWNER_CONFIRMED",
          source_url: "",
          quote: "",
          owner_confirmed: true,
          owner_confirmed_at: "2026-08-21T10:04:00.000Z",
        },
      },
    },
    context: {
      direct: {
        ready: true,
        inventory_ready: true,
        authority: "VERIFIED",
        access: "YANDEX_DIRECT_API_V501",
        account: "owner-login",
        client_id: "9007199254740993",
        binding: {
          expected_account: "owner-login",
          api_account: "owner-login",
          matched: true,
        },
        campaigns_total: 7,
        observed_at: "2026-08-21T10:02:00.000Z",
        read_limitations: {
          inventory_complete: true,
          limited_by: null,
          methods_read: ["Campaigns.get"],
          methods_not_read: ["AdGroups.get", "Keywords.get", "Ads.get", "SEARCH_QUERY_PERFORMANCE_REPORT"],
          statistics_provisional_days: 3,
        },
      },
      campaign_catalog: {
        total: 7,
        active: [
          { campaign_id: "1", name: "Campaign A", state: "ON", status: "ACCEPTED" },
          { campaign_id: "2", name: "Campaign B", state: "SUSPENDED", status: "ACCEPTED" },
        ],
      },
      metrika: {
        ready: true,
        authority: "VERIFIED",
        access: "YANDEX_METRIKA_MANAGEMENT_AND_REPORTS_API",
        counter_id: "123",
        goal_id: "456",
        binding: {
          expected_counter_id: "123",
          api_counter_id: "123",
          matched: true,
        },
        goal_binding: {
          expected_goal_id: "456",
          api_goal_id: "456",
          matched: true,
        },
        observed_at: "2026-08-21T10:03:00.000Z",
      },
      performance: {
        period_start: "2026-08-13",
        period_end: "2026-08-20",
        display_metrics: { visits: "42", goal_visits: "3" },
        provenance: {
          source_kind: "METRIKA_REPORTS_API",
          observed_at: "2026-08-21T10:03:00.000Z",
          attribution: "last_direct_click",
          timezone: "Europe/Moscow",
          dimensions: ["ym:s:date", "ym:s:lastDirectClickOrder"],
          filters: "ym:s:lastDirectClickOrder=='77'",
          sampling: {
            sampled,
            contains_sensitive_data: sensitive,
            sample_share: sampled ? 0.5 : 1,
            sample_size: sampled ? 21 : 42,
            sample_space: 42,
            data_lag: lag,
          },
        },
      },
      competitor_observations: competitors,
    },
  };
}

function competitorObservation(overrides = {}) {
  return {
    source_url: "https://competitor.example/offer",
    observed_at: "2026-08-21T09:30:00.000Z",
    collected_via: "PUBLIC_RESEARCH_EGRESS_V1",
    locator: {
      url: "https://competitor.example/offer",
      selector: "main h1",
    },
    policy: {
      policy_id: "public-competitor-pages",
      version: "1.0.0",
      policy_url: "https://competitor.example/robots.txt",
      access: "PUBLIC_NO_AUTH",
      allowed_hosts: ["competitor.example"],
    },
    scope: {
      host: "competitor.example",
      pages_observed: 1,
      observation_scope: "published offer text on one public page",
    },
    claim: {
      subject: "competitor:competitor.example",
      predicate: "published_offer",
      value: "Бесплатная консультация перед заказом",
    },
    raw_quote: "Бесплатная консультация перед заказом",
    limitations: ["Одно публичное наблюдение не доказывает распространённость или эффективность."],
    ...overrides,
  };
}

test("builds a deeply immutable content-addressed snapshot with stable IDs, complete manifests and hashes", async () => {
  const first = await buildAnalyticsEvidence(fixture());
  const second = await buildAnalyticsEvidence(fixture());

  assert.equal(first.schema_version, ANALYTICS_EVIDENCE_SCHEMA);
  assert.equal(first.snapshot_id, second.snapshot_id);
  assert.match(first.snapshot_id, /^sha256:[a-f0-9]{64}$/);
  assert.equal(await verifyAnalyticsEvidenceSnapshot(first), true);
  assert.equal(Object.isFrozen(first), true);
  assert.equal(Object.isFrozen(first.sources), true);
  assert.equal(Object.isFrozen(first.evidence[0].raw), true);
  assert.equal(first.immutability.content_addressed, true);
  assert.equal(first.immutability.revision_required_for_change, true);
  assert.deepEqual(Object.keys(first.hashes).sort(), [
    "claims_sha256",
    "conflicts_sha256",
    "evidence_sha256",
    "gaps_sha256",
    "input_root_sha256",
    "sources_sha256",
  ]);
  assert.ok(first.sources.every((source) => /^sha256:[a-f0-9]{64}$/.test(source.manifest_hash)));
  assert.ok(first.claims.every((claim) => /^sha256:[a-f0-9]{64}$/.test(claim.claim_hash)));
  assert.ok(first.evidence.every((record) => /^sha256:[a-f0-9]{64}$/.test(record.record_hash)));
  assert.ok(first.evidence.every((record) => /^sha256:[a-f0-9]{64}$/.test(record.raw.sha256)));
  assert.ok(first.evidence.every((record) => Array.isArray(record.transforms)));
  assert.ok(first.evidence.every((record) => record.versions.schema && record.versions.extractor));
  assert.ok(first.evidence.every((record) => record.fetched_at && record.observed_at));
  assert.ok(first.evidence.every((record) => record.claim_links.every((link) => first.claims.some((claim) => claim.claim_id === link.claim_id))));
  assert.deepEqual(first.scope, {
    company_host: "owner.example",
    direct_client_login: "owner-login",
    direct_client_id: "9007199254740993",
    metrika_counter_id: "123",
    metrika_goal_id: "456",
  });
});

test("content IDs are insensitive to object key order and sensitive to normalized value, locator and version changes", async () => {
  const base = fixture();
  const reordered = fixture();
  reordered.model = Object.fromEntries(Object.entries(reordered.model).reverse());
  reordered.context.direct = Object.fromEntries(Object.entries(reordered.context.direct).reverse());

  const original = await buildAnalyticsEvidence(base);
  assert.equal((await buildAnalyticsEvidence(reordered)).snapshot_id, original.snapshot_id);

  const changedValue = fixture();
  changedValue.model.product = "Другое предложение";
  assert.notEqual((await buildAnalyticsEvidence(changedValue)).snapshot_id, original.snapshot_id);

  const changedLocator = fixture();
  changedLocator.model.field_evidence.product.source_url = "https://owner.example/products";
  assert.notEqual((await buildAnalyticsEvidence(changedLocator)).snapshot_id, original.snapshot_id);

  const changedVersion = fixture();
  changedVersion.model.research = { agent: "GPT_SITES_EVIDENCE_RESEARCH_V4" };
  assert.notEqual((await buildAnalyticsEvidence(changedVersion)).snapshot_id, original.snapshot_id);
});

test("keeps first-party public and owner-confirmed provenance in separate source manifests and Evidence Records", async () => {
  const input = fixture();
  input.model.field_evidence.product.owner_confirmed = true;
  input.model.field_evidence.product.owner_confirmed_at = "2026-08-21T10:04:00.000Z";
  input.model.field_evidence.product.confidence = "OWNER_CONFIRMED";

  const result = await buildAnalyticsEvidence(input);
  const claim = result.claims.find((item) => item.predicate === "product");
  const records = result.evidence.filter((item) => claim?.evidence_ids.includes(item.evidence_id));

  assert.equal(claim?.confidence.consistency, "corroborated");
  assert.deepEqual(records.map((item) => item.source_kind).sort(), [
    "first_party_web",
    "owner_confirmation",
  ]);
  assert.equal(records.find((item) => item.source_kind === "first_party_web")?.source_id, "first-party-web");
  assert.equal(records.find((item) => item.source_kind === "owner_confirmation")?.source_id, "owner-confirmed");
  assert.equal(result.sources.find((item) => item.source_id === "first-party-web")?.status, "VERIFIED");
  assert.equal(result.sources.find((item) => item.source_id === "owner-confirmed")?.status, "VERIFIED");
});

test("attaches exact Direct read scope and treats unavailable current inventory as a material blocker, never zero activity", async () => {
  const available = await buildAnalyticsEvidence(fixture());
  const directRecord = available.evidence.find((item) => item.source_kind === "direct_management_api");
  assert.deepEqual(directRecord?.scope, {
    access: "owner_authorized",
    client_login: "owner-login",
    client_id: "9007199254740993",
  });
  assert.deepEqual(directRecord?.provider_metadata.direct_read.methods_not_read, [
    "AdGroups.get",
    "Keywords.get",
    "Ads.get",
    "SEARCH_QUERY_PERFORMANCE_REPORT",
  ]);
  assert.equal(available.sources.find((item) => item.source_id === "direct")?.status, "PARTIAL");

  const input = fixture();
  input.context.direct = {
    ready: false,
    inventory_ready: false,
    authority: "VERIFIED",
    access: "YANDEX_DIRECT_API_V501",
    account: "owner-login",
    client_id: "9007199254740993",
    binding: { expected_account: "owner-login", api_account: "owner-login", matched: true },
    blockers: ["Direct API timeout"],
  };
  input.context.campaign_catalog = null;
  const unavailable = await buildAnalyticsEvidence(input);

  assert.equal(unavailable.recommendation_status, "BLOCKED_UNKNOWN");
  assert.ok(unavailable.summary.hard_blockers.some((item) => item.includes("Direct inventory")));
  assert.equal(unavailable.sources.find((item) => item.source_id === "direct")?.status, "UNAVAILABLE");
  assert.equal(unavailable.claims.some((item) => item.predicate === "campaigns_total" && item.value === 0), false);
  assert.ok(unavailable.gaps.some((item) => item.code === "CURRENT_DIRECT_INVENTORY_UNAVAILABLE" && item.material));
});

test("preserves Metrika sampling, privacy, lag, attribution and exact counter/goal binding as partial metadata", async () => {
  const result = await buildAnalyticsEvidence(fixture({ sampled: true, sensitive: true, lag: 7200 }));
  const source = result.sources.find((item) => item.source_id === "metrika");
  const claim = result.claims.find((item) => item.predicate === "observed_performance");
  const record = result.evidence.find((item) => item.source_kind === "metrica_reports_api");

  assert.equal(source?.status, "PARTIAL");
  assert.equal(claim?.confidence.coverage, "partial");
  assert.equal(claim?.confidence.tier, "TIER_3_INDICATIVE");
  assert.deepEqual(record?.scope, {
    access: "owner_authorized",
    counter_id: "123",
    goal_id: "456",
  });
  assert.deepEqual(record?.provider_metadata.metrika_report, {
    sampled: true,
    contains_sensitive_data: true,
    sample_share: 0.5,
    sample_size: 21,
    sample_space: 42,
    data_lag: 7200,
    attribution: "last_direct_click",
    timezone: "Europe/Moscow",
    dimensions: ["ym:s:date", "ym:s:lastDirectClickOrder"],
    filters: "ym:s:lastDirectClickOrder=='77'",
    period_start: "2026-08-13",
    period_end: "2026-08-20",
  });
  assert.ok(claim?.confidence.uncertainty.some((item) => item.includes("sampling")));
  assert.ok(claim?.confidence.uncertainty.some((item) => item.includes("privacy")));
  assert.ok(claim?.confidence.uncertainty.some((item) => item.includes("lag")));
});

test("accepts only policy-bound allowlisted public competitor observations and persists scope without hidden performance claims", async () => {
  const result = await buildAnalyticsEvidence(fixture({ competitors: [competitorObservation()] }));
  const source = result.sources.find((item) => item.source_id === "competitors");
  const claim = result.claims.find((item) => item.predicate === "published_offer");
  const record = result.evidence.find((item) => item.source_kind === "competitor_public_web");

  assert.equal(source?.status, "PARTIAL");
  assert.equal(claim?.confidence.quality, "C");
  assert.equal(record?.source_locator.url, "https://competitor.example/offer");
  assert.equal(record?.collection_policy.policy_url, "https://competitor.example/robots.txt");
  assert.equal(record?.collection_policy.access, "PUBLIC_NO_AUTH");
  assert.equal(record?.scope.observation_scope, "published offer text on one public page");
  assert.ok(record?.limitations.some((item) => item.includes("не доказывает")));
  assert.ok(result.gaps.some((item) => item.code === "COMPETITOR_INTERNAL_PERFORMANCE_UNAVAILABLE"));
  assert.doesNotMatch(JSON.stringify(result.claims), /competitor_(?:budget|cpc|conversions|internal_strategy)/iu);
});

test("fails closed for a non-allowlisted competitor host or a hidden competitor performance claim", async (t) => {
  await t.test("host", async () => {
    const observation = competitorObservation();
    observation.policy.allowed_hosts = ["another.example"];
    await assert.rejects(
      buildAnalyticsEvidence(fixture({ competitors: [observation] })),
      (error) => error instanceof AnalyticsEvidenceError && error.code === "PUBLIC_HOST_NOT_ALLOWLISTED",
    );
  });
  await t.test("hidden claim", async () => {
    const observation = competitorObservation({
      claim: {
        subject: "competitor:competitor.example",
        predicate: "competitor_cpc",
        value: "120 RUB",
      },
    });
    await assert.rejects(
      buildAnalyticsEvidence(fixture({ competitors: [observation] })),
      (error) => error instanceof AnalyticsEvidenceError && error.code === "COMPETITOR_HIDDEN_CLAIM_FORBIDDEN",
    );
  });
});

test("keeps conflicts, source status, confidence dimensions and missing evidence separate from one opaque score", async () => {
  const input = fixture({ missing: ["Какое предложение нужно рекламировать?"] });
  input.model.conflicts = [{
    predicate: "product",
    left_value: "Участие",
    right_value: "Посещение",
    relation: "contradicts",
    material: true,
    resolution: "UNRESOLVED_OWNER_DECISION",
  }];
  const result = await buildAnalyticsEvidence(input);

  assert.equal(result.recommendation_status, "BLOCKED_UNKNOWN");
  assert.ok(result.conflicts.some((item) => item.material && item.resolution === "UNRESOLVED_OWNER_DECISION"));
  assert.ok(result.gaps.some((item) => item.code === "BUSINESS_MODEL_EVIDENCE_MISSING" && item.material));
  assert.deepEqual(Object.keys(result.confidence).sort(), [
    "consistency",
    "coverage",
    "freshness",
    "quality",
    "uncertainty",
  ]);
  assert.equal("score" in result.confidence, false);
  assert.ok(result.summary.hard_blockers.some((item) => item.includes("Какое предложение")));
  assert.equal(await verifyAnalyticsEvidenceSnapshot(result), true);
});

test("redacts credential and PII patterns and bounds raw values before client or persistence serialization", async () => {
  const input = fixture({ competitors: [competitorObservation()] });
  input.model.product = "Authorization: Bearer should-never-leak owner@example.com +7 999 123-45-67 ".repeat(60);
  input.model.field_evidence.product.quote = input.model.product;
  input.context.direct.oauth_token = "direct-secret";
  input.context.metrika.token = "metrika-secret";
  input.context.research_prompt = "OAuth prompt-secret";
  const result = await buildAnalyticsEvidence(input);
  const serialized = JSON.stringify(result);

  assert.doesNotMatch(serialized, /should-never-leak|owner@example\.com|999 123-45-67|direct-secret|metrika-secret|prompt-secret/u);
  assert.match(serialized, /\[REDACTED_(?:CREDENTIAL|PII)\]/u);
  const record = result.evidence.find((item) => item.source_kind === "first_party_web");
  assert.equal(record.raw.bounded.truncated, true);
  assert.ok(JSON.stringify(record.raw.value).length <= 1_300);
});
