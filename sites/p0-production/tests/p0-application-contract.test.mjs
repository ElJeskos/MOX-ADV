import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  P0_APPLICATION_CONTRACT,
  P0_DOCUMENT_SCHEMA,
  P0Application,
  P0ApplicationError,
} from "../lib/p0-application.ts";
import { collectOfficialWordstatBatch } from "../lib/market-evidence.ts";

class JsonDurableStore {
  constructor(path) {
    this.path = path;
  }

  async data() {
    try {
      return JSON.parse(await readFile(this.path, "utf8"));
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
      return { current: {}, revisions: {} };
    }
  }

  async persist(data) {
    await writeFile(this.path, JSON.stringify(data), "utf8");
  }

  async load(key) {
    return (await this.data()).current[key] ?? null;
  }

  async initialize(key, row) {
    const data = await this.data();
    if (data.current[key]) return false;
    data.current[key] = row;
    data.revisions[key] = [row];
    await this.persist(data);
    return true;
  }

  async compareAndSwap(key, expectedRevision, row) {
    const data = await this.data();
    if (data.current[key]?.revision !== expectedRevision) return false;
    data.current[key] = row;
    data.revisions[key].push(row);
    await this.persist(data);
    return true;
  }

  async history(key) {
    return [...((await this.data()).revisions[key] ?? [])].reverse();
  }

  async seed(key, row) {
    const data = await this.data();
    data.current[key] = row;
    data.revisions[key] = [row];
    await this.persist(data);
  }
}

function canonicalizeForTest(value) {
  if (Array.isArray(value)) return value.map(canonicalizeForTest);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value).sort(([left], [right]) => left.localeCompare(right)).map(([key, item]) => [key, canonicalizeForTest(item)]));
}

async function sha256ForTest(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(canonicalizeForTest(value))));
  return `sha256:${[...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("")}`;
}

async function rehashLandingAdvisoryForTest(run) {
  run.advisory_key = `landing-advisory-key:${await sha256ForTest({
    strategy_revision_id: run.strategy_revision_id,
    final_url: run.final_url ?? run.requested_url,
  })}`;
  run.run_id = `landing-advisory:${await sha256ForTest(Object.fromEntries(Object.entries(run).filter(([key]) => key !== "run_id")))}`;
}

function context() {
  return {
    environment: "PRODUCTION",
    test_scenario: false,
    direct: {
      ready: true,
      inventory_ready: true,
      authority: "VERIFIED",
      access: "YANDEX_DIRECT_API_V501",
      account: "owner-account",
      binding: {
        expected_account: "owner-account",
        api_account: "owner-account",
        matched: true,
      },
      campaigns_total: 1,
      minimum_weekly_budget_rub: 300,
      observed_at: "2026-08-21T10:00:00.000Z",
      read_limitations: {
        inventory_complete: true,
        limited_by: null,
        methods_read: ["Campaigns.get"],
        methods_not_read: ["AdGroups.get", "Keywords.get", "Ads.get", "SEARCH_QUERY_PERFORMANCE_REPORT"],
        statistics_provisional_days: 3,
      },
    },
    metrika: {
      ready: true,
      authority: "VERIFIED",
      access: "YANDEX_METRIKA_MANAGEMENT_AND_REPORTS_API",
      counter_id: "424242",
      goal_id: "1717",
      time_zone: "Europe/Moscow",
      binding: {
        expected_counter_id: "424242",
        api_counter_id: "424242",
        matched: true,
      },
      goal_binding: {
        expected_goal_id: "1717",
        api_goal_id: "1717",
        matched: true,
      },
      observed_at: "2026-08-21T10:00:00.000Z",
    },
    campaign_catalog: { total: 1, active: [] },
    performance: {
      period_start: "2026-08-01",
      period_end: "2026-08-20",
      display_metrics: { visits: "10", goal_visits: "2" },
      provenance: {
        source_kind: "METRIKA_REPORTS_API",
        observed_at: "2026-08-21T10:00:00.000Z",
        attribution: "last_direct_click_order_dimension",
        timezone: "Europe/Moscow",
        dimensions: ["ym:s:date", "ym:s:lastDirectClickOrder"],
        filters: "ym:s:lastDirectClickOrder=='77'",
        sampling: {
          sampled: false,
          contains_sensitive_data: false,
          sample_share: 1,
          sample_size: 10,
          sample_space: 10,
          data_lag: 0,
        },
      },
    },
  };
}

function landingAdvisoryAdapter({ performanceScore = 0.8, ctaLabel = "Оставить заявку" } = {}) {
  return {
    availability: { available: true, reason: null },
    async resolveHostname() {
      return ["93.184.216.34"];
    },
    async versions() {
      return {
        lighthouse: "12.8.2",
        chrome: "136.0.7103.113",
        lighthouse_config: "p0-lighthouse-desktop-1920x1080-v1",
        axe_core: "4.10.3",
      };
    },
    async inspect(input) {
      input.policy.authorizeRequest({ url: input.url, method: "GET", resource_type: "document", headers: {}, body_present: false, resolved_addresses: ["93.184.216.34"] });
      return {
        requested_url: input.url,
        final_url: input.url,
        redirect_chain: [input.url],
        network_requests: [{ url: input.url, method: "GET", resource_type: "document", headers: {}, body_present: false, resolved_addresses: ["93.184.216.34"] }],
        response_bytes: 100,
        page: {
          title: "Промышленная выставка",
          headings: ["Найдите новых покупателей"],
          text_excerpt: "Оставьте заявку на участие в промышленной выставке.",
          ctas: [{ label: ctaLabel, kind: "link" }],
          forms: [{ method: "POST", action_kind: "same_page", fields_count: 4 }],
          metrika_tag_detected: true,
          http_status: 200,
          content_type: "text/html",
        },
        hypotheses: [],
      };
    },
    async runLighthouse() {
      return {
        performance_score: performanceScore,
        metrics: {
          first_contentful_paint_ms: 1000,
          largest_contentful_paint_ms: 2000,
          cumulative_layout_shift: 0.05,
          total_blocking_time_ms: 150,
          speed_index_ms: 2400,
        },
      };
    },
    async runAxe() {
      return {
        violations: { count: 0, items: [] },
        passes: { count: 10, items: [] },
        incomplete: { count: 1, items: [{ id: "manual", impact: null, nodes: 1, help: "manual review" }] },
        inapplicable: { count: 2, items: [] },
      };
    },
  };
}

function adapters(overrides = {}) {
  let tick = 0;
  return {
    now() {
      tick += 1;
      return `2026-08-21T10:00:${String(tick).padStart(2, "0")}.000Z`;
    },
    async readContext() {
      return context();
    },
    async researchSite(url) {
      return {
        url,
        fetched_at: "2026-08-21T10:00:00.000Z",
        title: "Промышленная выставка",
        description: "Выставка помогает производителям найти новых покупателей и партнёров.",
        headings: ["Стать участником выставки"],
        forms_detected: 1,
        text_excerpt: "Руководители производственных компаний могут оставить заявку на участие.",
        pages: [{
          url,
          title: "Промышленная выставка",
          description: "Выставка помогает производителям найти новых покупателей и партнёров.",
          headings: ["Стать участником выставки"],
          forms_detected: 1,
          text_excerpt: "Руководители производственных компаний могут оставить заявку на участие.",
        }],
        research: { pages_analyzed: 1, links_discovered: 0, scope: "FIRST_PARTY_PUBLIC_HTTPS" },
      };
    },
    async readCurrencyLimits() {
      return { minimum_weekly_budget_rub: 300 };
    },
    externalWriteConfiguration() {
      return { ready: true, blockers: [], account: "owner-account" };
    },
    async createExternalOutcome({ projection }) {
      return {
        source: "YANDEX_DIRECT_API",
        execution_id: "execution-1",
        campaign_id: "9007199254740993",
        campaign_state: "SUSPENDED",
        moderation_status: "MODERATION",
        spend_started: false,
        status: "MODERATION_PENDING",
        projection_schema_version: projection.schema_version,
      };
    },
    ...overrides,
  };
}

async function fixture() {
  const directory = await mkdtemp(join(tmpdir(), "mox-p0-contract-"));
  const store = new JsonDurableStore(join(directory, "state.json"));
  return {
    directory,
    store,
    application: new P0Application({ store, adapters: adapters() }),
  };
}

function ownerModel(state) {
  return Object.fromEntries(
    ["product", "audience", "value", "qualified_result", "exclusions"]
      .map((field) => [field, state.business_model[field]]),
  );
}

function strategyValue() {
  return {
    goal: "Получать заявки на участие через сайт",
    geography: "Москва",
    period_start: "2026-09-01",
    period_end: "2026-10-01",
    landing_page: "https://owner.example/participate",
    weekly_budget_rub: 50_000,
    target_cpa_rub: 10_000,
    message: "Найдите новых покупателей на выставке",
  };
}

const STRATEGY_FIELD_ORDER = [
  "business_goal",
  "advertised_offer",
  "target_audience",
  "qualified_result",
  "exclusions",
  "geography",
  "period",
  "landing_page",
  "weekly_budget",
  "target_result_cost",
  "core_message",
];

function strategyAnswers(state, overrides = {}) {
  const recommended = Object.fromEntries(
    state.strategy_questionnaire.fields.map((field) => [field.field_id, field.recommended_value]),
  );
  return {
    ...recommended,
    geography: "Москва",
    period: { start_date: "2026-09-01", end_date: "2026-10-01" },
    weekly_budget: 50_000,
    target_result_cost: 10_000,
    ...overrides,
  };
}

async function approveStrategy(application, result, overrides = {}) {
  return application.command("owner", {
    action: "approve_strategy",
    expected_revision: result.revision,
    confirmation: "APPROVE_CAMPAIGN_STRATEGY",
    answers: strategyAnswers(result.state, overrides),
  });
}

async function marketEvidenceInput() {
  const top = JSON.parse(await readFile(new URL("./fixtures/wordstat/top-requests.json", import.meta.url), "utf8"));
  const dynamics = JSON.parse(await readFile(new URL("./fixtures/wordstat/dynamics.json", import.meta.url), "utf8"));
  const regions = JSON.parse(await readFile(new URL("./fixtures/wordstat/regions.json", import.meta.url), "utf8"));
  let tick = 0;
  const wordstatBatch = await collectOfficialWordstatBatch({
    token: "fixture-only",
    clientId: "fixture-client",
    seeds: [{
      seed_id: "seed-participation",
      cluster_id: "cluster-participation",
      phrase: "участие в выставке",
      dynamics_phrase: "+участие +выставке",
      dynamics_period: "monthly",
      dynamics_from_date: "2024-01-01",
      dynamics_to_date: "2026-07-31",
      operator_profile: "BROAD_CONTAINING",
      region_ids: [213],
      region_names: ["Москва"],
      device: "desktop",
    }],
  }, async (input) => {
    const path = new URL(String(input)).pathname;
    return new Response(JSON.stringify(path.endsWith("topRequests") ? top : path.endsWith("dynamics") ? dynamics : regions));
  }, () => `2026-08-21T10:00:${String(tick++).padStart(2, "0")}.000Z`);
  return {
    wordstat_batch: wordstatBatch,
    demand_clusters: [{ cluster_id: "cluster-participation", semantic_key: { product: "выставка", need: "участие", intent: "commercial", offer: "стенд" } }],
    cost_observations: [],
  };
}

test("authoritative application collects market evidence only for a Model revision and persists it for downstream delivery packing", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "mox-p0-market-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const store = new JsonDurableStore(join(directory, "state.json"));
  let marketReads = 0;
  const application = new P0Application({ store, adapters: adapters({
    async readMarketEvidence() {
      marketReads += 1;
      return marketEvidenceInput();
    },
  }) });

  let result = await application.command("owner", { action: "analyze_site", expected_revision: 0, url: "https://owner.example/" });
  result = await application.command("owner", { action: "confirm_context_goal", expected_revision: result.revision, confirmation: "CONFIRM_CONTEXT_GOAL", goal: result.state.context_state.provisional_business_goal.value });
  assert.equal(marketReads, 1);
  assert.equal(result.state.analytics_evidence_snapshot.market_evidence.frequency.status, "AVAILABLE");
  const persistedSnapshot = result.state.analytics_evidence_snapshot.snapshot_id;

  const queried = await application.query("owner");
  assert.equal(marketReads, 1);
  assert.equal(queried.state.analytics_evidence_snapshot.snapshot_id, persistedSnapshot);

  result = await application.command("owner", { action: "save_business_model", expected_revision: queried.revision, value: ownerModel(queried.state) });
  assert.equal(marketReads, 2);
  result = await approveStrategy(application, result);
  assert.equal(result.state.recommendation_set.delivery_packing.delivery_buckets.length, 1);
  assert.equal(result.state.recommendation_set.delivery_packing.delivery_buckets[0].disposition, "PACKED");
  assert.equal(result.state.recommendation_set.drafts.every((draft) => draft.market_evidence.frequency.snapshot_batch_id === result.state.analytics_evidence_snapshot.market_evidence.snapshot_batch_id), true);
});

test("authoritative application persists LandingAdvisoryRun while every publish decision surface remains byte-identical", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "mox-p0-landing-isolation-"));
  t.after(() => rm(directory, { recursive: true, force: true }));

  async function approvedApplication(name, landingAdvisory) {
    const store = new JsonDurableStore(join(directory, `${name}.json`));
    const application = new P0Application({ store, adapters: adapters({ landingAdvisory }) });
    let result = await application.command("owner", { action: "analyze_site", expected_revision: 0, url: "https://owner.example/participate" });
    result = await application.command("owner", { action: "confirm_context_goal", expected_revision: result.revision, confirmation: "CONFIRM_CONTEXT_GOAL", goal: result.state.context_state.provisional_business_goal.value });
    result = await application.command("owner", { action: "save_business_model", expected_revision: result.revision, value: ownerModel(result.state) });
    result = await approveStrategy(application, result, { landing_page: "https://owner.example/participate" });
    return { application, result };
  }

  const left = await approvedApplication("left", landingAdvisoryAdapter({ performanceScore: 0.2, ctaLabel: "Подробнее" }));
  const right = await approvedApplication("right", landingAdvisoryAdapter({ performanceScore: 0.98, ctaLabel: "Оставить заявку" }));
  assert.notEqual(JSON.stringify(left.result.state.landing_advisory_run.findings), JSON.stringify(right.result.state.landing_advisory_run.findings));
  assert.equal(left.result.state.landing_advisory_run.strategy_revision_id, left.result.state.strategy.strategy_revision_id);
  assert.equal(left.result.state.landing_advisory_run.final_url, "https://owner.example/participate");

  function decisionSurface(result) {
    return JSON.stringify({
      recommendation_set: result.state.recommendation_set,
      write_readiness: result.write_readiness,
      shortlist: result.state.shortlist,
      external_write_intent: result.state.external_write_intent,
    });
  }
  assert.equal(decisionSurface(left.result), decisionSurface(right.result));

  for (const item of [left, right]) {
    const visible = item.result.state.recommendation_set.drafts.find((candidate) => candidate.visibility === "VISIBLE");
    item.result = await item.application.command("owner", {
      action: "save_draft",
      expected_revision: item.result.revision,
      value: {
        draft_id: visible.draft_id,
        campaign_name: visible.campaign_name,
        group_name: visible.group_name,
        keyword: visible.keyword,
        negative_keywords: visible.negative_keywords,
        ad_title: visible.ad_title,
        ad_text: visible.ad_text,
      },
    });
  }
  const publishDecision = (result) => JSON.stringify({
    hard_eligibility: result.state.draft.viability_score.eligibility,
    publish_readiness: result.state.draft.publish_eligibility,
    score: result.state.draft.viability_score.score,
    rank: result.state.draft.viability_score.rank,
    threshold: result.state.draft.viability_score.visibility,
    calibration: {
      status: result.state.draft.viability_score.policy_status,
      contract_version: result.state.draft.viability_score.contract_version,
      policy_fingerprint: result.state.draft.viability_score.fingerprints.policy,
      cohort_fingerprint: result.state.draft.viability_score.fingerprints.cohort,
    },
    publish_fingerprint: result.state.draft.publish_fingerprint,
    canonical_projection: result.state.draft.publish_projection,
    write_readiness: result.write_readiness,
  });
  assert.equal(publishDecision(left.result), publishDecision(right.result));

  const beforeRerun = publishDecision(left.result);
  left.result = await left.application.command("owner", { action: "run_landing_advisory", expected_revision: left.result.revision });
  assert.equal(publishDecision(left.result), beforeRerun);
});

test("rejects a content-rehashed cross-party LandingAdvisoryRun before query or downstream use", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "mox-p0-landing-corrupt-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const store = new JsonDurableStore(join(directory, "state.json"));
  const application = new P0Application({ store, adapters: adapters({ landingAdvisory: landingAdvisoryAdapter() }) });
  let result = await application.command("owner", { action: "analyze_site", expected_revision: 0, url: "https://owner.example/participate" });
  result = await application.command("owner", { action: "confirm_context_goal", expected_revision: result.revision, confirmation: "CONFIRM_CONTEXT_GOAL", goal: result.state.context_state.provisional_business_goal.value });
  result = await application.command("owner", { action: "save_business_model", expected_revision: result.revision, value: ownerModel(result.state) });
  await approveStrategy(application, result, { landing_page: "https://owner.example/participate" });
  const row = await store.load("owner");
  const corrupted = JSON.parse(row.value_json);
  corrupted.landing_advisory_run.final_url = "https://unrelated.example/participate";
  corrupted.landing_advisory_run.browser_safety.allowed_hosts = ["owner.example", "unrelated.example"];
  await rehashLandingAdvisoryForTest(corrupted.landing_advisory_run);
  await store.seed("owner", { ...row, value_json: JSON.stringify(corrupted) });

  await assert.rejects(
    application.query("owner"),
    (error) => error instanceof P0ApplicationError && error.code === "P0_MIGRATION_LINEAGE_INVALID" && /LandingAdvisoryRun/u.test(error.message),
  );
  assert.equal((await store.load("owner")).revision, row.revision);
});

test("the authoritative contract persists the fixed Strategy questionnaire and freezes one linked immutable revision", async (t) => {
  const { directory, store, application } = await fixture();
  t.after(() => rm(directory, { recursive: true, force: true }));

  let result = await application.command("owner", { action: "analyze_site", expected_revision: 0, url: "https://owner.example/" });
  result = await application.command("owner", {
    action: "confirm_context_goal",
    expected_revision: result.revision,
    confirmation: "CONFIRM_CONTEXT_GOAL",
    goal: result.state.context_state.provisional_business_goal.value,
  });
  result = await application.command("owner", {
    action: "save_business_model",
    expected_revision: result.revision,
    value: ownerModel(result.state),
  });

  const questionnaire = result.state.strategy_questionnaire;
  assert.equal(questionnaire.schema_version, "p0-strategy-questionnaire-v1");
  assert.deepEqual(questionnaire.fields.map((field) => field.field_id), STRATEGY_FIELD_ORDER);
  assert.equal(questionnaire.context_revision_id, result.state.context_state.context_revision_id);
  assert.equal(questionnaire.context_material_fingerprint, result.state.context_state.material_fingerprint);
  assert.equal(questionnaire.analytics_evidence_snapshot_id, result.state.analytics_evidence_snapshot.snapshot_id);
  for (const field of questionnaire.fields) {
    assert.equal(Object.hasOwn(field, "recommended_value"), true);
    assert.equal(typeof field.explanation, "string");
    assert.equal(["сайт", "Директ", "Метрика", "аналитика агента", "решение владельца"].includes(field.source_category), true);
    assert.equal(["уверенно", "нужно проверить", "нет данных"].includes(field.status), true);
  }
  for (const fieldId of ["geography", "period", "weekly_budget", "target_result_cost"]) {
    const field = questionnaire.fields.find((item) => item.field_id === fieldId);
    assert.equal(field.recommended_value, null);
    assert.equal(field.status, "нет данных");
    assert.equal(field.source_category, "решение владельца");
    assert.equal(field.prepared_decision.required, true);
    assert.equal(field.prepared_decision.consequences.length > 0, true);
  }
  assert.doesNotMatch((await store.load("owner")).value_json, /50000|10000/u);

  await assert.rejects(
    application.command("owner", {
      action: "approve_strategy",
      expected_revision: result.revision,
      confirmation: "APPROVE_CAMPAIGN_STRATEGY",
      answers: { ...strategyAnswers(result.state), weekly_budget: null },
    }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_STRATEGY_DECISION_REQUIRED",
  );
  assert.equal((await store.load("owner")).revision, result.revision);
  await assert.rejects(
    application.command("owner", {
      action: "approve_strategy",
      expected_revision: result.revision,
      confirmation: "APPROVE_CAMPAIGN_STRATEGY",
      answers: strategyAnswers(result.state, { period: { start_date: "2026-99-01", end_date: "2026-10-01" } }),
    }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_STRATEGY_PERIOD_INVALID",
  );
  assert.equal((await store.load("owner")).revision, result.revision);

  result = await approveStrategy(application, result);
  assert.equal(result.state.strategy.schema_version, "p0-campaign-strategy-v1");
  assert.deepEqual(result.state.strategy.answers.map((answer) => answer.field_id), STRATEGY_FIELD_ORDER);
  assert.equal(result.state.strategy.questionnaire_id, questionnaire.questionnaire_id);
  assert.equal(result.state.strategy.questionnaire_contract_version, questionnaire.contract_version);
  assert.equal(result.state.strategy.context_revision_id, result.state.context_state.context_revision_id);
  assert.equal(result.state.strategy.context_material_fingerprint, result.state.context_state.material_fingerprint);
  assert.equal(result.state.strategy.analytics_evidence_snapshot_id, result.state.analytics_evidence_snapshot.snapshot_id);
  assert.equal(result.state.strategy.lineage.previous_strategy_revision_id, null);
  assert.equal(result.state.recommendation_set.strategy_revision_id, result.state.strategy.strategy_revision_id);
  assert.equal(result.state.recommendation_set.analytics_evidence_snapshot_id, result.state.analytics_evidence_snapshot.snapshot_id);
});

test("rejects a corrupted persisted Strategy questionnaire before it can change field order or approval metadata", async (t) => {
  const { directory, store, application } = await fixture();
  t.after(() => rm(directory, { recursive: true, force: true }));
  let result = await application.command("owner", { action: "analyze_site", expected_revision: 0, url: "https://owner.example/" });
  result = await application.command("owner", {
    action: "confirm_context_goal",
    expected_revision: result.revision,
    confirmation: "CONFIRM_CONTEXT_GOAL",
    goal: result.state.context_state.provisional_business_goal.value,
  });
  result = await application.command("owner", { action: "save_business_model", expected_revision: result.revision, value: ownerModel(result.state) });
  const row = await store.load("owner");
  assert.equal(row.revision, result.revision);
  const corrupted = JSON.parse(row.value_json);
  corrupted.strategy_questionnaire.fields.reverse();
  corrupted.strategy_questionnaire.fields[0].source_category = "скрытый источник";
  await store.seed("owner", { ...row, value_json: JSON.stringify(corrupted) });

  await assert.rejects(
    application.query("owner"),
    (error) => error instanceof P0ApplicationError
      && error.code === "P0_MIGRATION_LINEAGE_INVALID"
      && /questionnaire/u.test(error.message),
  );
  assert.equal((await store.load("owner")).value_json, JSON.stringify(corrupted));
});

test("Strategy and Model material changes cascade while technical normalization preserves downstream lineage", async (t) => {
  const { directory, store, application } = await fixture();
  t.after(() => rm(directory, { recursive: true, force: true }));

  let result = await application.command("owner", { action: "analyze_site", expected_revision: 0, url: "owner.example" });
  result = await application.command("owner", {
    action: "confirm_context_goal",
    expected_revision: result.revision,
    confirmation: "CONFIRM_CONTEXT_GOAL",
    goal: result.state.context_state.provisional_business_goal.value,
  });
  result = await application.command("owner", { action: "save_business_model", expected_revision: result.revision, value: ownerModel(result.state) });
  result = await approveStrategy(application, result);
  const visible = result.state.recommendation_set.drafts.find((candidate) => candidate.visibility === "VISIBLE");
  result = await application.command("owner", {
    action: "save_draft",
    expected_revision: result.revision,
    value: {
      draft_id: visible.draft_id,
      campaign_name: visible.campaign_name,
      group_name: visible.group_name,
      keyword: visible.keyword,
      negative_keywords: visible.negative_keywords,
      ad_title: visible.ad_title,
      ad_text: visible.ad_text,
    },
  });
  const original = {
    strategy: result.state.strategy.strategy_revision_id,
    recommendation: result.state.recommendation_set.recommendation_set_id,
    draft: result.state.draft.draft_revision_id,
    shortlist: result.state.shortlist.shortlist_revision_id,
    snapshot: result.state.analytics_evidence_snapshot.snapshot_id,
  };

  const approvedCoreMessage = result.state.strategy.answers.find((answer) => answer.field_id === "core_message").value;
  result = await application.command("owner", {
    action: "approve_strategy",
    expected_revision: result.revision,
    confirmation: "APPROVE_CAMPAIGN_STRATEGY",
    answers: strategyAnswers(result.state, {
      core_message: `  ${String(approvedCoreMessage).replaceAll(" ", "   ")}  `,
      landing_page: "owner.example/",
    }),
  });
  assert.equal(result.state.strategy.strategy_revision_id, original.strategy);
  assert.equal(result.state.recommendation_set.recommendation_set_id, original.recommendation);
  assert.equal(result.state.draft.draft_revision_id, original.draft);
  assert.equal(result.state.shortlist.shortlist_revision_id, original.shortlist);

  const tabA = await application.query("owner");
  const tabB = await application.query("owner");
  const compareAndSwap = store.compareAndSwap.bind(store);
  let releaseRecomputation;
  const recomputationMayFinish = new Promise((resolve) => { releaseRecomputation = resolve; });
  let pendingPersisted;
  const pendingWasPersisted = new Promise((resolve) => { pendingPersisted = resolve; });
  let pendingObserved = false;
  store.compareAndSwap = async (key, expectedRevision, row) => {
    const saved = await compareAndSwap(key, expectedRevision, row);
    const nextState = JSON.parse(row.value_json);
    if (saved && !pendingObserved && nextState.last_cascade?.recomputation_status === "PENDING") {
      pendingObserved = true;
      pendingPersisted();
      await recomputationMayFinish;
    }
    return saved;
  };
  const approval = approveStrategy(application, tabA, { core_message: "Новый доказуемый message" });
  await pendingWasPersisted;
  const duringRecomputation = await application.query("owner");
  assert.equal(duringRecomputation.state.last_cascade.recomputation_status, "PENDING");
  assert.deepEqual(duringRecomputation.workflow.allowed_commands, []);
  assert.equal(duringRecomputation.write_readiness.ready, false);
  await assert.rejects(
    application.command("owner", {
      action: "confirm_creation",
      expected_revision: duringRecomputation.revision,
      confirmation: "CREATE_NON_SERVING_CAMPAIGN",
    }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_TRANSITION_INVALID",
  );
  assert.equal((await store.load("owner")).revision, duringRecomputation.revision);
  releaseRecomputation();
  result = await approval;
  assert.notEqual(result.state.strategy.strategy_revision_id, original.strategy);
  assert.equal(result.state.strategy.lineage.previous_strategy_revision_id, original.strategy);
  assert.notEqual(result.state.recommendation_set.recommendation_set_id, original.recommendation);
  assert.equal(result.state.draft, null);
  assert.equal(result.state.shortlist, null);
  assert.equal(result.state.last_cascade.trigger, "STRATEGY");
  assert.deepEqual(result.state.last_cascade.affected_steps, ["recommendation_set", "campaign_drafts", "shortlist", "confirmation"]);
  assert.equal(result.state.last_cascade.recomputation_status, "COMPLETE");
  assert.equal(result.workflow.allowed_commands.includes("confirm_creation"), false);
  assert.equal(result.revision_history.some((item) => item.status === "SUPERSEDED" && item.strategy_revision_id === original.strategy), true);

  await assert.rejects(
    approveStrategy(application, tabB, { core_message: "Несовместимый ответ stale tab" }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_REVISION_CONFLICT",
  );
  const afterConflict = await application.query("owner");
  assert.equal(afterConflict.revision, result.revision);
  assert.equal(afterConflict.state.strategy.answers.find((answer) => answer.field_id === "core_message").value, "Новый доказуемый message");

  const normalizedModel = Object.fromEntries(Object.entries(ownerModel(afterConflict.state)).map(([key, value]) => [key, `  ${String(value).replaceAll(" ", "   ")}  `]));
  result = await application.command("owner", {
    action: "save_business_model",
    expected_revision: afterConflict.revision,
    value: normalizedModel,
  });
  const strategyAfterNormalization = result.state.strategy.strategy_revision_id;
  assert.equal(result.state.analytics_evidence_snapshot.snapshot_id, original.snapshot);
  assert.equal(strategyAfterNormalization, afterConflict.state.strategy.strategy_revision_id);
  assert.equal(result.state.recommendation_set.recommendation_set_id, afterConflict.state.recommendation_set.recommendation_set_id);

  const changedModel = ownerModel(result.state);
  changedModel.product = "Другое рекламируемое предложение";
  result = await application.command("owner", {
    action: "save_business_model",
    expected_revision: result.revision,
    value: changedModel,
  });
  assert.equal(result.state.strategy, null);
  assert.equal(result.state.recommendation_set, null);
  assert.equal(result.state.draft, null);
  assert.equal(result.state.shortlist, null);
  assert.equal(result.state.last_cascade.trigger, "MODEL");
  assert.equal(result.state.last_cascade.recomputation_status, "REQUIRED");
  assert.equal(result.write_readiness.ready, false);
  assert.notEqual(result.state.analytics_evidence_snapshot.snapshot_id, original.snapshot);
  assert.equal(result.state.strategy_questionnaire.analytics_evidence_snapshot_id, result.state.analytics_evidence_snapshot.snapshot_id);
  assert.equal(result.state.strategy_questionnaire.fields.find((field) => field.field_id === "advertised_offer").source_category, "решение владельца");
  assert.equal((await store.load("owner")).revision, result.revision);
});

test("one query/command contract drives and persists the current five-step path", async (t) => {
  const { directory, store, application } = await fixture();
  t.after(() => rm(directory, { recursive: true, force: true }));

  let result = await application.query("owner");
  assert.equal(result.contract.name, P0_APPLICATION_CONTRACT);
  assert.equal(result.revision, 0);
  assert.equal(result.state.schema_version, P0_DOCUMENT_SCHEMA);
  assert.deepEqual(result.workflow.steps.map((step) => step.label), [
    "Контекст",
    "Модель бизнеса",
    "Стратегия кампании",
    "Рекламные кампании",
    "Подтверждение",
  ]);
  assert.equal(result.workflow.current_step, 0);

  result = await application.command("owner", {
    action: "analyze_site",
    expected_revision: result.revision,
    url: "https://owner.example/",
  });
  assert.equal(result.revision, 1);
  assert.equal(result.workflow.current_step, 0);
  assert.equal(result.state.business_model, null);
  assert.equal(result.state.context_state.status, "GOAL_PROVISIONAL");
  assert.equal(result.state.context_state.facts.direct.account, "owner-account");
  assert.equal(result.state.context_state.facts.metrika.counter_id, "424242");
  assert.equal(result.state.context_state.provisional_business_goal.value, "Получать заявки на участие через сайт");
  assert.match(result.state.context_state.provisional_business_goal.rationale, /заявк|участ/u);
  assert.equal(result.workflow.allowed_commands.includes("confirm_context_goal"), true);

  let restarted = new P0Application({ store, adapters: adapters() });
  result = await restarted.query("owner");
  assert.equal(result.revision, 1);
  assert.equal(result.state.context_state.status, "GOAL_PROVISIONAL");

  result = await restarted.command("owner", {
    action: "confirm_context_goal",
    expected_revision: result.revision,
    confirmation: "CONFIRM_CONTEXT_GOAL",
    goal: result.state.context_state.provisional_business_goal.value,
  });
  assert.equal(result.revision, 2);
  assert.equal(result.workflow.current_step, 1);
  assert.equal(result.state.context_state.status, "GOAL_CONFIRMED");
  assert.equal(result.state.context_state.business_goal_decision.decision, "CONFIRMED");
  assert.match(result.state.analytics_evidence_snapshot.snapshot_id, /^sha256:[a-f0-9]{64}$/);
  assert.equal(result.state.business_model.analysis_evidence, undefined);

  const persistedSnapshotId = result.state.analytics_evidence_snapshot.snapshot_id;
  const persistedAfterModel = JSON.parse((await store.load("owner")).value_json);
  assert.equal(persistedAfterModel.analytics_evidence_snapshot.snapshot_id, persistedSnapshotId);
  assert.equal(persistedAfterModel.business_model.analysis_evidence, undefined);

  const changedContext = context();
  changedContext.performance.display_metrics.visits = "999999";
  changedContext.performance.provenance.observed_at = "2026-08-21T10:04:00.000Z";
  restarted = new P0Application({ store, adapters: adapters({ readContext: async () => changedContext }) });
  result = await restarted.query("owner");
  assert.equal(result.revision, 2);
  assert.equal(result.state.context_state.business_goal_decision.value, "Получать заявки на участие через сайт");
  assert.equal(result.state.analytics_evidence_snapshot.snapshot_id, persistedSnapshotId);
  assert.equal(result.analytics_evidence_snapshot, undefined);
  assert.doesNotMatch(JSON.stringify(result.state.analytics_evidence_snapshot), /999999/u);

  result = await restarted.command("owner", {
    action: "save_business_model",
    expected_revision: result.revision,
    value: ownerModel(result.state),
  });
  assert.equal(result.workflow.current_step, 2);

  result = await approveStrategy(restarted, result);
  assert.equal(result.workflow.current_step, 3);
  assert.equal(result.state.recommendation_set.strategy_revision_id, result.state.strategy.strategy_revision_id);

  const draft = result.state.recommendation_set.drafts.find((candidate) => candidate.visibility === "VISIBLE");
  result = await restarted.command("owner", {
    action: "save_draft",
    expected_revision: result.revision,
    value: {
      draft_id: draft.draft_id,
      campaign_name: draft.campaign_name,
      group_name: draft.group_name,
      keyword: draft.keyword,
      negative_keywords: draft.negative_keywords,
      ad_title: draft.ad_title,
      ad_text: draft.ad_text,
    },
  });
  assert.equal(result.revision, 6);
  assert.equal(result.workflow.current_step, 4);
  assert.equal(result.state.draft.strategy_revision_id, result.state.strategy.strategy_revision_id);
  assert.equal(result.state.draft.publish_fingerprint.length, 64);

  await assert.rejects(
    restarted.command("owner", {
      action: "confirm_creation",
      expected_revision: result.revision,
      confirmation: "CREATE_NON_SERVING_CAMPAIGN",
    }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_PUBLISH_BLOCKED",
  );
  const afterBlockedWrite = await restarted.query("owner");
  assert.equal(afterBlockedWrite.revision, 6);
  assert.equal(afterBlockedWrite.state.campaign, null);
});

test("Context preflight fails closed for stale, partial or mismatched exact API binding", async (t) => {
  const cases = [
    {
      name: "mismatched Direct account",
      mutate(value) { value.direct.binding.api_account = "other-account"; value.direct.binding.matched = false; },
      code: "P0_CONTEXT_PREFLIGHT_BLOCKED",
    },
    {
      name: "partial Metrika binding",
      mutate(value) { value.metrika.goal_binding = null; },
      code: "P0_CONTEXT_PREFLIGHT_BLOCKED",
    },
    {
      name: "stale preflight",
      mutate(value) { value.direct.observed_at = "2026-08-21T09:00:00.000Z"; },
      code: "P0_CONTEXT_PREFLIGHT_BLOCKED",
    },
  ];
  for (const item of cases) {
    await t.test(item.name, async () => {
      const { directory, store } = await fixture();
      t.after(() => rm(directory, { recursive: true, force: true }));
      const value = context();
      item.mutate(value);
      const application = new P0Application({ store, adapters: adapters({ readContext: async () => value }) });
      await assert.rejects(
        application.command("owner", { action: "analyze_site", expected_revision: 0, url: "https://owner.example/" }),
        (error) => error instanceof P0ApplicationError && error.code === item.code,
      );
      assert.equal((await store.load("owner")).revision, 0);
    });
  }
});

test("migrates the baseline v1 nested evidence bundle into one authoritative top-level persisted snapshot", async (t) => {
  const { directory, store, application } = await fixture();
  t.after(() => rm(directory, { recursive: true, force: true }));
  let result = await application.query("owner");
  result = await application.command("owner", {
    action: "analyze_site",
    expected_revision: result.revision,
    url: "https://owner.example/",
  });
  await application.command("owner", {
    action: "confirm_context_goal",
    expected_revision: result.revision,
    confirmation: "CONFIRM_CONTEXT_GOAL",
    goal: result.state.context_state.provisional_business_goal.value,
  });
  const current = JSON.parse((await store.load("owner")).value_json);
  const snapshotId = current.analytics_evidence_snapshot.snapshot_id;
  current.schema_version = "p0-application-document-v1";
  current.business_model.analysis_evidence = current.analytics_evidence_snapshot;
  delete current.analytics_evidence_snapshot;
  await store.seed("owner", {
    revision: 12,
    updated_at: "2026-08-21T10:00:12.000Z",
    value_json: JSON.stringify(current),
  });

  const migrated = await new P0Application({ store, adapters: adapters() }).query("owner");
  assert.equal(migrated.revision, 13);
  assert.equal(migrated.state.schema_version, P0_DOCUMENT_SCHEMA);
  assert.equal(migrated.state.analytics_evidence_snapshot.snapshot_id, snapshotId);
  assert.equal(migrated.state.business_model.analysis_evidence, undefined);
  const persisted = JSON.parse((await store.load("owner")).value_json);
  assert.equal(persisted.analytics_evidence_snapshot.snapshot_id, snapshotId);
  assert.equal(persisted.business_model.analysis_evidence, undefined);
});

test("rejects a corrupted persisted evidence snapshot before query reuse or downstream recommendations", async (t) => {
  const { directory, store, application } = await fixture();
  t.after(() => rm(directory, { recursive: true, force: true }));
  let result = await application.query("owner");
  result = await application.command("owner", {
    action: "analyze_site",
    expected_revision: result.revision,
    url: "https://owner.example/",
  });
  await application.command("owner", {
    action: "confirm_context_goal",
    expected_revision: result.revision,
    confirmation: "CONFIRM_CONTEXT_GOAL",
    goal: result.state.context_state.provisional_business_goal.value,
  });
  const row = await store.load("owner");
  const corrupted = JSON.parse(row.value_json);
  corrupted.analytics_evidence_snapshot.claims[0].value = "forged without rehash";
  await store.seed("owner", { ...row, value_json: JSON.stringify(corrupted) });

  await assert.rejects(
    new P0Application({ store, adapters: adapters() }).query("owner"),
    (error) => error instanceof P0ApplicationError
      && error.code === "P0_MIGRATION_LINEAGE_INVALID"
      && /snapshot hash/i.test(error.message),
  );
  assert.equal((await store.load("owner")).revision, row.revision);
  assert.equal(JSON.parse((await store.load("owner")).value_json).analytics_evidence_snapshot.claims[0].value, "forged without rehash");
});

test("client context and persisted Context facts exclude injected credentials", async (t) => {
  const { directory, store } = await fixture();
  t.after(() => rm(directory, { recursive: true, force: true }));
  const value = context();
  value.direct.oauth_token = "direct-secret";
  value.metrika.token = "metrika-secret";
  value.research_prompt = "Bearer prompt-secret";
  value.competitor_observations = [{
    source_url: "https://competitor.example/offer",
    observed_at: "2026-08-21T10:00:00.000Z",
    collected_via: "PUBLIC_RESEARCH_EGRESS_V1",
    locator: { url: "https://competitor.example/offer", selector: "main" },
    policy: {
      policy_id: "public-competitor-pages",
      version: "1.0.0",
      policy_url: "https://competitor.example/robots.txt",
      access: "PUBLIC_NO_AUTH",
      allowed_hosts: ["competitor.example"],
    },
    scope: { host: "competitor.example", pages_observed: 1, observation_scope: "one public page" },
    claim: { subject: "competitor:competitor.example", predicate: "published_offer", value: "Published offer" },
    raw_quote: "Authorization: Bearer competitor-secret owner@example.com",
    limitations: [],
    credential: "hidden-context-secret",
  }];
  const application = new P0Application({ store, adapters: adapters({ readContext: async () => value }) });
  let result = await application.query("owner");
  assert.doesNotMatch(JSON.stringify(result), /direct-secret|metrika-secret|prompt-secret|competitor-secret|owner@example\.com|hidden-context-secret/u);
  result = await application.command("owner", {
    action: "analyze_site",
    expected_revision: result.revision,
    url: "https://owner.example/",
  });
  assert.doesNotMatch((await store.load("owner")).value_json, /direct-secret|metrika-secret|prompt-secret|competitor-secret|owner@example\.com|hidden-context-secret/u);
});

test("redacts sensitive public-page and owner-entered artifacts before the revision is persisted", async (t) => {
  const { directory, store } = await fixture();
  t.after(() => rm(directory, { recursive: true, force: true }));
  const baseAdapters = adapters();
  const application = new P0Application({
    store,
    adapters: adapters({
      async researchSite(url) {
        const site = await baseAdapters.researchSite(url);
        site.description = "Authorization: Bearer page-secret owner@example.com";
        site.text_excerpt = `${site.text_excerpt} +7 999 123-45-67`;
        site.pages[0].description = site.description;
        site.pages[0].text_excerpt = site.text_excerpt;
        return site;
      },
    }),
  });
  let result = await application.query("owner");
  result = await application.command("owner", {
    action: "analyze_site",
    expected_revision: result.revision,
    url: "https://owner.example/",
  });
  result = await application.command("owner", {
    action: "confirm_context_goal",
    expected_revision: result.revision,
    confirmation: "CONFIRM_CONTEXT_GOAL",
    goal: result.state.context_state.provisional_business_goal.value,
  });
  const edited = ownerModel(result.state);
  edited.product = "Authorization: Bearer owner-secret sales@example.com";
  result = await application.command("owner", {
    action: "save_business_model",
    expected_revision: result.revision,
    value: edited,
  });

  const persisted = (await store.load("owner")).value_json;
  assert.doesNotMatch(persisted, /page-secret|owner-secret|owner@example\.com|sales@example\.com|999 123-45-67/u);
  assert.match(persisted, /\[REDACTED_(?:CREDENTIAL|PII)\]/u);
  assert.doesNotMatch(JSON.stringify(result), /page-secret|owner-secret|owner@example\.com|sales@example\.com|999 123-45-67/u);
});

test("the owner explicitly corrects the one provisional goal and the decision survives restart", async (t) => {
  const { directory, store, application } = await fixture();
  t.after(() => rm(directory, { recursive: true, force: true }));
  let result = await application.query("owner");
  result = await application.command("owner", {
    action: "analyze_site",
    expected_revision: result.revision,
    url: "https://owner.example/",
  });
  assert.equal(result.state.business_model, null);
  await assert.rejects(
    application.command("owner", {
      action: "confirm_context_goal",
      expected_revision: result.revision,
      goal: "Увеличивать квалифицированные обращения",
    }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_CONTEXT_GOAL_CONFIRMATION_REQUIRED",
  );
  assert.equal((await store.load("owner")).revision, result.revision);
  result = await application.command("owner", {
    action: "confirm_context_goal",
    expected_revision: result.revision,
    confirmation: "CONFIRM_CONTEXT_GOAL",
    goal: "  Увеличивать   квалифицированные обращения  ",
  });
  assert.equal(result.state.context_state.business_goal_decision.value, "Увеличивать квалифицированные обращения");
  assert.equal(result.state.context_state.business_goal_decision.decision, "CORRECTED");
  const restarted = new P0Application({ store, adapters: adapters() });
  result = await restarted.query("owner");
  assert.equal(result.state.context_state.business_goal_decision.value, "Увеличивать квалифицированные обращения");
  assert.equal(result.workflow.current_step, 1);
});

test("a material Context change names and invalidates downstream lineage while normalization-only input does not", async (t) => {
  const { directory, store, application } = await fixture();
  t.after(() => rm(directory, { recursive: true, force: true }));
  let result = await application.query("owner");
  result = await application.command("owner", { action: "analyze_site", expected_revision: result.revision, url: "owner.example" });
  result = await application.command("owner", {
    action: "confirm_context_goal",
    expected_revision: result.revision,
    confirmation: "CONFIRM_CONTEXT_GOAL",
    goal: "Получать заявки на участие через сайт",
  });
  result = await application.command("owner", { action: "save_business_model", expected_revision: result.revision, value: ownerModel(result.state) });
  result = await approveStrategy(application, result);
  const draft = result.state.recommendation_set.drafts.find((candidate) => candidate.visibility === "VISIBLE");
  result = await application.command("owner", {
    action: "save_draft",
    expected_revision: result.revision,
    value: {
      draft_id: draft.draft_id,
      campaign_name: draft.campaign_name,
      group_name: draft.group_name,
      keyword: draft.keyword,
      negative_keywords: draft.negative_keywords,
      ad_title: draft.ad_title,
      ad_text: draft.ad_text,
    },
  });
  const lineage = {
    strategy: result.state.strategy.strategy_revision_id,
    draft: result.state.draft.draft_revision_id,
    shortlist: result.state.shortlist.shortlist_revision_id,
  };
  const staleContext = context();
  staleContext.metrika.observed_at = "2026-08-21T09:00:00.000Z";
  const staleApplication = new P0Application({ store, adapters: adapters({ readContext: async () => staleContext }) });
  await assert.rejects(
    staleApplication.command("owner", {
      action: "confirm_creation",
      expected_revision: result.revision,
      confirmation: "CREATE_NON_SERVING_CAMPAIGN",
    }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_CONTEXT_PREFLIGHT_BLOCKED",
  );
  assert.equal((await store.load("owner")).revision, result.revision);

  result = await application.command("owner", {
    action: "analyze_site",
    expected_revision: result.revision,
    url: "https://owner.example/",
  });
  assert.equal(result.state.strategy.strategy_revision_id, lineage.strategy);
  assert.equal(result.state.draft.draft_revision_id, lineage.draft);
  assert.equal(result.state.shortlist.shortlist_revision_id, lineage.shortlist);
  assert.equal(result.state.context_state.last_material_change, null);

  const changedResearch = adapters({
    async researchSite(url) {
      const site = await adapters().researchSite(url);
      site.description = "Новая услуга для другого результата.";
      site.pages[0].description = site.description;
      return site;
    },
  });
  const changedApplication = new P0Application({ store, adapters: changedResearch });
  result = await changedApplication.command("owner", {
    action: "analyze_site",
    expected_revision: result.revision,
    url: "https://owner.example/",
  });
  assert.equal(result.workflow.current_step, 0);
  assert.equal(result.state.strategy, null);
  assert.equal(result.state.recommendation_set, null);
  assert.equal(result.state.draft, null);
  assert.equal(result.state.shortlist, null);
  assert.equal(result.workflow.allowed_commands.includes("confirm_creation"), false);
  assert.deepEqual(result.state.context_state.last_material_change.affected_steps, [
    "campaign_strategy",
    "recommendation_set",
    "campaign_drafts",
    "shortlist",
    "confirmation",
  ]);
  assert.equal(result.state.context_state.last_material_change.previous_lineage.strategy_revision_id, lineage.strategy);
  assert.equal(result.state.context_state.last_material_change.previous_lineage.draft_revision_id, lineage.draft);
  assert.equal(result.state.context_state.last_material_change.previous_lineage.shortlist_revision_id, lineage.shortlist);
  assert.equal(result.state.last_cascade.trigger, "CONTEXT");
  assert.equal(result.state.last_cascade.recomputation_status, "REQUIRED");
  assert.equal(result.write_readiness.ready, false);
});

test("compare-and-swap rejects a stale tab without changing the persisted document", async (t) => {
  const { directory, application } = await fixture();
  t.after(() => rm(directory, { recursive: true, force: true }));

  const tabA = await application.query("owner");
  const tabB = await application.query("owner");
  const saved = await application.command("owner", {
    action: "analyze_site",
    expected_revision: tabA.revision,
    url: "https://owner.example/",
  });

  await assert.rejects(
    application.command("owner", {
      action: "reset",
      expected_revision: tabB.revision,
    }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_REVISION_CONFLICT",
  );
  const current = await application.query("owner");
  assert.equal(current.revision, saved.revision);
  assert.equal(current.state.site_analysis.url, "https://owner.example/");
});

test("legacy Sites state migrates with lineage before an external outcome survives restart", async (t) => {
  const { directory, store } = await fixture();
  t.after(() => rm(directory, { recursive: true, force: true }));
  const legacy = {
    site_analysis: {
      url: "https://owner.example/",
      fetched_at: "2026-08-20T10:00:00.000Z",
      title: "Owner",
      description: "Owner product",
      headings: [],
      forms_detected: 1,
      text_excerpt: "Owner product for business",
      pages: [],
      research: { pages_analyzed: 1, links_discovered: 0, scope: "FIRST_PARTY_PUBLIC_HTTPS" },
    },
    business_model: {
      product: "Owner product",
      audience: "Business owners",
      value: "Save time",
      qualified_result: "Qualified request",
      exclusions: "Job seekers",
      source: "REAL_SITE_RESEARCH_PLUS_OWNER_CONFIRMATION",
      assumptions: [],
      missing_questions: [],
      research: { agent: "LEGACY", pages_analyzed: 1, sources: [], completed_fields: [] },
      field_evidence: {},
    },
    strategy: { ...strategyValue(), source: "OWNER_APPROVED_REAL_BUSINESS_INPUT" },
    recommendation_set: null,
    draft: {
      campaign_name: "Owner product · Search",
      group_name: "Owner group",
      keyword: "owner product",
      negative_keywords: "free, jobs",
      ad_title: "Owner product",
      ad_text: "Submit a qualified request",
      publish_projection: {
        schema_version: "p0-direct-projection-v3",
        direct: { campaign: { Name: "Owner product · Search" } },
        safety: { must_end_suspended: true, resume_allowed: false },
      },
    },
    campaign: null,
  };
  await store.seed("owner", {
    revision: 7,
    updated_at: "2026-08-20T10:00:00.000Z",
    value_json: JSON.stringify(legacy),
  });

  let dispatchRevision = null;
  let application = new P0Application({
    store,
    adapters: adapters({
      async createExternalOutcome({ projection }) {
        const persisted = await store.load("owner");
        const document = JSON.parse(persisted.value_json);
        assert.equal(persisted.revision, 9);
        assert.equal(document.external_write_intent.publish_fingerprint, document.draft.publish_fingerprint);
        assert.equal(document.campaign, null);
        dispatchRevision = persisted.revision;
        return {
          execution_id: "execution-1",
          campaign_id: "9007199254740993",
          campaign_state: "SUSPENDED",
          moderation_status: "MODERATION",
          spend_started: false,
          status: "MODERATION_PENDING",
          projection_schema_version: projection.schema_version,
        };
      },
    }),
  });
  let result = await application.query("owner");
  assert.equal(result.revision, 8);
  assert.equal(result.state.schema_version, P0_DOCUMENT_SCHEMA);
  assert.equal(result.state.strategy.strategy_revision_id, "campaign-strategy-r7");
  assert.match(result.state.draft.draft_id, /^draft-/);
  assert.equal(result.state.draft.strategy_revision_id, "campaign-strategy-r7");
  assert.equal(result.state.draft.publish_fingerprint.length, 64);
  assert.equal(result.revision_history.at(-1).revision, 7);

  result = await application.command("owner", {
    action: "confirm_creation",
    expected_revision: result.revision,
    confirmation: "CREATE_NON_SERVING_CAMPAIGN",
  });
  assert.equal(dispatchRevision, 9);
  assert.equal(result.revision, 10);
  assert.equal(result.state.campaign.campaign_state, "SUSPENDED");
  assert.equal(result.state.campaign.spend_started, false);

  application = new P0Application({ store, adapters: adapters() });
  result = await application.query("owner");
  assert.equal(result.revision, 10);
  assert.equal(result.state.campaign.execution_id, "execution-1");
  assert.equal(result.state.draft.strategy_revision_id, result.state.strategy.strategy_revision_id);
  assert.deepEqual(result.workflow.allowed_commands, []);

  for (const action of ["analyze_site", "reset"]) {
    await assert.rejects(
      application.command("owner", {
        action,
        expected_revision: result.revision,
        ...(action === "analyze_site" ? { url: "https://changed.example/" } : {}),
      }),
      (error) => error instanceof P0ApplicationError && error.code === "P0_TRANSITION_INVALID",
    );
  }
  assert.equal((await application.query("owner")).revision, 10);
});

test("legacy state with an outcome but no Draft lineage is rejected explicitly", async (t) => {
  const { directory, store, application } = await fixture();
  t.after(() => rm(directory, { recursive: true, force: true }));
  await store.seed("owner", {
    revision: 3,
    updated_at: "2026-08-20T10:00:00.000Z",
    value_json: JSON.stringify({
      site_analysis: null,
      business_model: null,
      strategy: null,
      recommendation_set: null,
      draft: null,
      campaign: { campaign_id: "123", campaign_state: "SUSPENDED" },
    }),
  });

  await assert.rejects(
    application.query("owner"),
    (error) => error instanceof P0ApplicationError && error.code === "P0_MIGRATION_LINEAGE_INVALID",
  );
  assert.equal((await store.load("owner")).revision, 3);
});
