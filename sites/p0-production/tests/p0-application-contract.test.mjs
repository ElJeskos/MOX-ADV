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
import { directExecutionFailureOutcome } from "../lib/campaign-package-execution.ts";
import { sealCuratedPlaybookRelease } from "../lib/campaign-playbook.ts";
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
      client_id: "client-4242",
      binding: {
        expected_account: "owner-account",
        api_account: "owner-account",
        matched: true,
      },
      campaigns_total: 1,
      minimum_weekly_budget_rub: 300,
      observed_at: "2026-08-21T10:00:00.000Z",
      capability_snapshot: {
        schema_version: "direct-account-capability-snapshot-v1",
        snapshot_id: "direct-capability:fixture-owner-account",
        source: "YANDEX_DIRECT_API_V501",
        account: "owner-account",
        observed_at: "2026-08-21T10:00:00.000Z",
        api_version: "v501",
        archived: "NO",
        currency: "RUB",
        edit_campaigns_grant: "YES",
        available_campaign_types: ["UNIFIED_CAMPAIGN"],
        restrictions: [{ element: "CAMPAIGNS_TOTAL_PER_CLIENT", value: 3000 }],
        conditional_capabilities: [],
      },
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
  assert.equal(result.state.context_state.facts.direct.capability_snapshot.source, "YANDEX_DIRECT_API_V501");
  assert.equal(result.state.recommendation_set.direct_capability_snapshot_id, result.state.context_state.facts.direct.capability_snapshot.snapshot_id);
  assert.equal(result.state.recommendation_set.capability_profile.eligibility.eligible, true);
  assert.equal(result.state.recommendation_set.playbook_release.status, "BLOCKED_FAIL_CLOSED");
  assert.equal(result.state.recommendation_set.drafts.length, 1);
  assert.equal(result.state.recommendation_set.drafts[0].variant.control_basis.kind, "STRATEGY_BASELINE_FALLBACK");
  assert.equal(result.state.recommendation_set.drafts[0].publish_eligibility, "BLOCKED_HARD");
  assert.equal(result.state.recommendation_set.candidate_audit.some((candidate) => candidate.reason_code === "HIDDEN:PLAYBOOK_NO_ACTIVE_APPROVED_RELEASE"), true);
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
    shortlist: JSON.stringify(result.state.shortlist),
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
  assert.equal(JSON.stringify(result.state.shortlist), original.shortlist);

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
  assert.equal(result.state.shortlist.schema_version, "p0-shortlist-v2");
  assert.deepEqual(result.state.shortlist.selections, []);
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
  await assert.rejects(
    restarted.command("owner", {
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
        autotargeting_settings: { Exact: "YES" },
      },
    }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_DRAFT_FIELD_UNSUPPORTED",
  );
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
  assert.equal(result.workflow.current_step, 3);
  assert.equal(result.state.draft.strategy_revision_id, result.state.strategy.strategy_revision_id);
  assert.match(result.state.draft.publish_fingerprint, /^sha256:[a-f0-9]{64}$/u);

  await assert.rejects(
    restarted.command("owner", {
      action: "confirm_creation",
      expected_revision: result.revision,
      confirmation: "CREATE_NON_SERVING_CAMPAIGN",
    }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_TRANSITION_INVALID",
  );
  const afterBlockedWrite = await restarted.query("owner");
  assert.equal(afterBlockedWrite.revision, 6);
  assert.equal(afterBlockedWrite.state.shortlist.schema_version, "p0-shortlist-v2");
  assert.deepEqual(afterBlockedWrite.state.shortlist.selections, []);
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
      name: "unverified Direct capability source",
      mutate(value) { value.direct.capability_snapshot.source = "UNTRUSTED_SNAPSHOT"; },
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

test("fresh Direct capability observation identity stays normalization-only across confirm, save and reanalysis", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "mox-p0-capability-refresh-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const store = new JsonDurableStore(join(directory, "state.json"));
  const observedSnapshots = [];
  const application = new P0Application({ store, adapters: adapters({
    async readContext() {
      const value = context();
      const sequence = observedSnapshots.length + 1;
      const observedAt = `2026-08-21T10:00:${String(sequence).padStart(2, "0")}.000Z`;
      value.direct.observed_at = observedAt;
      value.direct.capability_snapshot.observed_at = observedAt;
      value.direct.capability_snapshot.snapshot_id = `direct-capability:fresh-observation-${sequence}`;
      observedSnapshots.push(structuredClone(value.direct.capability_snapshot));
      return value;
    },
  }) });

  let result = await application.command("owner", { action: "analyze_site", expected_revision: 0, url: "https://owner.example/" });
  assert.equal(result.state.context_state.facts.direct.capability_snapshot.snapshot_id, observedSnapshots[0].snapshot_id);
  result = await application.command("owner", {
    action: "confirm_context_goal",
    expected_revision: result.revision,
    confirmation: "CONFIRM_CONTEXT_GOAL",
    goal: result.state.context_state.provisional_business_goal.value,
  });
  const persistedCapabilitySnapshot = structuredClone(result.state.context_state.facts.direct.capability_snapshot);
  assert.equal(observedSnapshots.some((snapshot) => snapshot.snapshot_id === persistedCapabilitySnapshot.snapshot_id), true);
  assert.notEqual(persistedCapabilitySnapshot.snapshot_id, observedSnapshots[0].snapshot_id);

  result = await application.command("owner", {
    action: "save_business_model",
    expected_revision: result.revision,
    value: ownerModel(result.state),
  });
  result = await approveStrategy(application, result);
  const lineage = {
    context_revision_id: result.state.context_state.context_revision_id,
    material_fingerprint: result.state.context_state.material_fingerprint,
    strategy_revision_id: result.state.strategy.strategy_revision_id,
    recommendation_set_id: result.state.recommendation_set.recommendation_set_id,
  };
  assert.equal(result.state.recommendation_set.direct_capability_snapshot_id, persistedCapabilitySnapshot.snapshot_id);

  result = await application.command("owner", {
    action: "analyze_site",
    expected_revision: result.revision,
    url: "owner.example",
  });
  assert.deepEqual(result.state.context_state.facts.direct.capability_snapshot, persistedCapabilitySnapshot);
  assert.equal(result.state.context_state.context_revision_id, lineage.context_revision_id);
  assert.equal(result.state.context_state.material_fingerprint, lineage.material_fingerprint);
  assert.equal(result.state.context_state.last_material_change, null);
  assert.equal(result.state.strategy.strategy_revision_id, lineage.strategy_revision_id);
  assert.equal(result.state.recommendation_set.recommendation_set_id, lineage.recommendation_set_id);
});

test("substantive Direct capability changes fail closed and reanalysis invalidates downstream lineage", async (t) => {
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
  result = await approveStrategy(application, result);
  const original = {
    revision: result.revision,
    strategy_revision_id: result.state.strategy.strategy_revision_id,
    recommendation_set_id: result.state.recommendation_set.recommendation_set_id,
  };
  const changedContext = context();
  changedContext.direct.capability_snapshot.snapshot_id = "direct-capability:changed-restriction";
  changedContext.direct.capability_snapshot.observed_at = "2026-08-21T10:00:10.000Z";
  changedContext.direct.capability_snapshot.restrictions[0].value = 2_999;
  const changedApplication = new P0Application({ store, adapters: adapters({ readContext: async () => changedContext }) });

  await assert.rejects(
    changedApplication.command("owner", {
      action: "save_business_model",
      expected_revision: result.revision,
      value: ownerModel(result.state),
    }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_CONTEXT_PREFLIGHT_CHANGED",
  );
  assert.equal((await store.load("owner")).revision, original.revision);

  result = await changedApplication.command("owner", {
    action: "analyze_site",
    expected_revision: original.revision,
    url: "https://owner.example/",
  });
  assert.equal(result.workflow.current_step, 0);
  assert.equal(result.state.strategy, null);
  assert.equal(result.state.recommendation_set, null);
  assert.equal(result.state.context_state.facts.direct.capability_snapshot.snapshot_id, "direct-capability:changed-restriction");
  assert.equal(result.state.context_state.facts.direct.capability_snapshot.restrictions[0].value, 2_999);
  assert.equal(result.state.context_state.last_material_change.previous_lineage.strategy_revision_id, original.strategy_revision_id);
  assert.equal(result.state.context_state.last_material_change.previous_lineage.recommendation_set_id, original.recommendation_set_id);
  assert.equal(result.state.last_decision_invalidation.reason_code, "ACCOUNT_OR_CAPABILITY_LINEAGE_CHANGED");
  assert.equal(result.state.last_cascade.trigger, "CONTEXT");
  assert.equal(result.state.last_cascade.recomputation_status, "REQUIRED");
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
    shortlist: JSON.stringify(result.state.shortlist),
    shortlist_revision_id: result.state.shortlist.shortlist_revision_id,
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
    (error) => error instanceof P0ApplicationError && error.code === "P0_TRANSITION_INVALID",
  );
  assert.equal((await store.load("owner")).revision, result.revision);

  result = await application.command("owner", {
    action: "analyze_site",
    expected_revision: result.revision,
    url: "https://owner.example/",
  });
  assert.equal(result.state.strategy.strategy_revision_id, lineage.strategy);
  assert.equal(result.state.draft.draft_revision_id, lineage.draft);
  assert.equal(JSON.stringify(result.state.shortlist), lineage.shortlist);
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
  assert.equal(result.state.context_state.last_material_change.previous_lineage.shortlist_revision_id, lineage.shortlist_revision_id);
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

test("legacy Sites state migrates with lineage but cannot bypass current eligibility into an external write", async (t) => {
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

  let application = new P0Application({ store, adapters: adapters() });
  let result = await application.query("owner");
  assert.equal(result.revision, 8);
  assert.equal(result.state.schema_version, P0_DOCUMENT_SCHEMA);
  assert.equal(result.state.strategy.strategy_revision_id, "campaign-strategy-r7");
  assert.match(result.state.draft.draft_id, /^draft-/);
  assert.equal(result.state.draft.strategy_revision_id, "campaign-strategy-r7");
  assert.match(result.state.draft.publish_fingerprint, /^sha256:[a-f0-9]{64}$/u);
  assert.equal(result.revision_history.at(-1).revision, 7);

  assert.equal(result.state.shortlist.schema_version, "p0-shortlist-v2");
  assert.deepEqual(result.state.shortlist.selections, []);
  assert.equal(result.workflow.allowed_commands.includes("confirm_creation"), false);
  await assert.rejects(
    application.command("owner", {
      action: "confirm_creation",
      expected_revision: result.revision,
      confirmation: "CREATE_NON_SERVING_CAMPAIGN",
    }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_TRANSITION_INVALID",
  );
  application = new P0Application({ store, adapters: adapters() });
  result = await application.query("owner");
  assert.equal(result.revision, 8);
  assert.equal(result.state.campaign, null);
  assert.equal(result.state.draft.strategy_revision_id, result.state.strategy.strategy_revision_id);
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

function editableDraftValue(draft, overrides = {}) {
  return {
    draft_id: draft.draft_id,
    campaign_name: draft.campaign_name,
    group_name: draft.group_name,
    negative_keywords: draft.negative_keywords,
    keyword: draft.keyword,
    ad_title: draft.ad_title,
    ad_text: draft.ad_text,
    ...overrides,
  };
}

async function approvedDraftFixture(t) {
  const value = await fixture();
  t.after(() => rm(value.directory, { recursive: true, force: true }));
  let result = await value.application.command("owner", { action: "analyze_site", expected_revision: 0, url: "https://owner.example/" });
  result = await value.application.command("owner", {
    action: "confirm_context_goal",
    expected_revision: result.revision,
    confirmation: "CONFIRM_CONTEXT_GOAL",
    goal: result.state.context_state.provisional_business_goal.value,
  });
  result = await value.application.command("owner", { action: "save_business_model", expected_revision: result.revision, value: ownerModel(result.state) });
  result = await approveStrategy(value.application, result);
  return { ...value, result };
}

test("restart rejects every same-schema persisted field registry mutation before query or UI use", async (t) => {
  const { store, result } = await approvedDraftFixture(t);
  const row = await store.load("owner");
  const cases = [
    ["editable", (registry) => { registry.fields[1].editable = true; }],
    ["classification", (registry) => { registry.fields[1].classification = "EDITABLE"; }],
    ["input_name", (registry) => { registry.fields[0].input_name = "same_schema_rogue_field"; }],
    ["pointer", (registry) => { registry.fields[0].pointer = "/direct/campaign/Unsupported"; }],
  ];
  for (const [name, mutate] of cases) {
    const corrupted = JSON.parse(row.value_json);
    assert.equal(corrupted.recommendation_set.field_registry.schema_version, result.state.recommendation_set.field_registry.schema_version);
    mutate(corrupted.recommendation_set.field_registry);
    await store.seed("owner", { ...row, value_json: JSON.stringify(corrupted) });
    const restarted = new P0Application({ store, adapters: adapters() });
    await assert.rejects(
      restarted.query("owner"),
      (error) => error instanceof P0ApplicationError
        && error.code === "P0_MIGRATION_LINEAGE_INVALID"
        && /field registry/u.test(error.message),
      name,
    );
    assert.equal((await store.load("owner")).value_json, JSON.stringify(corrupted));
  }
  const explicitNull = JSON.parse(row.value_json);
  explicitNull.recommendation_set.field_registry = null;
  await store.seed("owner", { ...row, value_json: JSON.stringify(explicitNull) });
  await assert.rejects(
    new P0Application({ store, adapters: adapters() }).query("owner"),
    (error) => error instanceof P0ApplicationError
      && error.code === "P0_MIGRATION_LINEAGE_INVALID"
      && /field registry/u.test(error.message),
  );

  const genuinelyMissing = JSON.parse(row.value_json);
  delete genuinelyMissing.recommendation_set.field_registry;
  await store.seed("owner", { ...row, value_json: JSON.stringify(genuinelyMissing) });
  const migrated = await new P0Application({ store, adapters: adapters() }).query("owner");
  assert.deepEqual(migrated.state.recommendation_set.field_registry, result.state.recommendation_set.field_registry);
  assert.equal(migrated.revision, row.revision + 1);
});

test("normalization-only Draft save reports a no-op without inventing a Draft or Recommendation Set revision", async (t) => {
  const { application, result: approved } = await approvedDraftFixture(t);
  const generated = approved.state.recommendation_set.drafts.find((draft) => draft.visibility === "VISIBLE");
  const before = {
    draft_revision_id: generated.draft_revision_id,
    publish_fingerprint: generated.publish_fingerprint,
    recommendation_set_id: approved.state.recommendation_set.recommendation_set_id,
    score: generated.viability_score,
  };
  const reversedNegatives = generated.negative_keywords.split(",").map((item) => item.trim()).reverse().join(", ");
  const result = await application.command("owner", {
    action: "save_draft",
    expected_revision: approved.revision,
    value: editableDraftValue(generated, {
      campaign_name: `  ${generated.campaign_name.replaceAll(" ", "   ")}  `,
      negative_keywords: reversedNegatives,
    }),
  });
  assert.equal(result.state.draft.draft_revision_id, before.draft_revision_id);
  assert.equal(result.state.draft.publish_fingerprint, before.publish_fingerprint);
  assert.equal(result.state.recommendation_set.recommendation_set_id, before.recommendation_set_id);
  assert.deepEqual(result.state.draft.viability_score, before.score);
  const shortlistBeforeNormalization = JSON.stringify(approved.state.shortlist);
  assert.deepEqual(result.state.draft.draft_save_result, {
    schema_version: "p0-draft-save-result-v1",
    material_change: false,
    message: "Нет material changes: нормализация не создала Draft revision.",
    previous_draft_revision_id: before.draft_revision_id,
    current_draft_revision_id: before.draft_revision_id,
    previous_publish_fingerprint: before.publish_fingerprint,
    current_publish_fingerprint: before.publish_fingerprint,
    changed_fields: [],
  });
  assert.equal(JSON.stringify(result.state.shortlist), shortlistBeforeNormalization);
});

async function governedPlaybookRelease({ releaseId, releaseVersion, family, decisionId }) {
  const changedFields = ["/direct/keyword/Keyword", "/direct/ad/TextAd/Text"];
  return sealCuratedPlaybookRelease({
    schema_version: "p0-curated-playbook-release-v1",
    contract_version: "1.0.0",
    release_id: releaseId,
    release_version: releaseVersion,
    status: "ACTIVE",
    approval_status: "APPROVED",
    promotion_policy: { policy_id: "fixture-promotion-policy", policy_version: "1.0.0", content_digest: `sha256:${"b".repeat(64)}` },
    approval_attestation: { decision_id: decisionId, actor_id: "fixture-steward", actor_role: "KNOWLEDGE_STEWARD", approved_at: "2026-08-21T09:00:00.000Z" },
    superseded_by_release_id: null,
    competitive_sample_rules: [],
    rules: [{
      rule_id: `fixture-${family.toLowerCase()}`,
      rule_version: "1.0.0",
      contract_version: "1.0.0",
      state: "ACTIVE",
      approval_status: "APPROVED",
      changed_family: family,
      mechanism: "Deterministic governed fixture treatment.",
      changed_fields: changedFields,
      required_capabilities: [],
      evidence_quality: 80,
      priority: 10,
      promotion_policy_id: "fixture-promotion-policy",
      qualified_evidence_refs: [`fixture-evidence:${family}`],
      applicability: { campaign_fanout_contract: "campaign-fanout-v1" },
    }],
  });
}

async function packageFixture(t, { release } = {}) {
  const directory = await mkdtemp(join(tmpdir(), "mox-p0-package-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const store = new JsonDurableStore(join(directory, "state.json"));
  let releases = [release ?? await governedPlaybookRelease({
    releaseId: "fixture-release-package",
    releaseVersion: "1.0.0",
    family: "QUALIFIED_ACTION",
    decisionId: "decision-package",
  })];
  let externalWrites = 0;
  let contextReads = 0;
  const adapter = adapters({
    async readContext() { contextReads += 1; return context(); },
    async readMarketEvidence() { return marketEvidenceInput(); },
    async readPlaybookReleases() { return releases; },
    async createExternalOutcome() {
      externalWrites += 1;
      throw new Error("Package review and confirmation must never call the external adapter.");
    },
  });
  const application = new P0Application({ store, adapters: adapter });
  let result = await application.command("owner", { action: "analyze_site", expected_revision: 0, url: "https://owner.example/" });
  result = await application.command("owner", { action: "confirm_context_goal", expected_revision: result.revision, confirmation: "CONFIRM_CONTEXT_GOAL", goal: result.state.context_state.provisional_business_goal.value });
  result = await application.command("owner", { action: "save_business_model", expected_revision: result.revision, value: ownerModel(result.state) });
  result = await approveStrategy(application, result);
  return {
    directory,
    store,
    application,
    adapter,
    result,
    externalWrites: () => externalWrites,
    contextReads: () => contextReads,
    setReleases(value) { releases = value; },
  };
}

async function reviewAndConfirm(application, result, draftIds) {
  for (const draftId of draftIds) {
    result = await application.command("owner", { action: "add_to_shortlist", expected_revision: result.revision, draft_id: draftId });
  }
  result = await application.command("owner", { action: "review_package", expected_revision: result.revision });
  return application.command("owner", {
    action: "confirm_package",
    expected_revision: result.revision,
    confirmation: "CONFIRM_EXACT_SHORTLIST_PACKAGE",
    package_review_id: result.state.package_review.package_review_id,
    package_id: result.state.package_review.package_id,
  });
}

test("ordered multi-Draft shortlist supports add/remove/positional restore, exact review and a durable no-write Gate", async (t) => {
  const value = await packageFixture(t);
  let result = value.result;
  const eligible = result.state.recommendation_set.drafts.filter((draft) => draft.shortlist_eligible === true && draft.visibility === "VISIBLE");
  assert.equal(eligible.length >= 2, true);
  const [first, second] = eligible;
  const recommendationBefore = JSON.stringify(result.state.recommendation_set);
  const evidenceBefore = JSON.stringify(result.state.analytics_evidence_snapshot);
  assert.equal(result.state.shortlist.schema_version, "p0-shortlist-v2");
  assert.deepEqual(result.state.shortlist.selections, []);

  const staleBeforeAdd = await value.application.query("owner");
  result = await value.application.command("owner", { action: "add_to_shortlist", expected_revision: result.revision, draft_id: first.draft_id });
  await assert.rejects(
    value.application.command("owner", { action: "add_to_shortlist", expected_revision: staleBeforeAdd.revision, draft_id: second.draft_id }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_REVISION_CONFLICT",
  );
  await assert.rejects(
    value.application.command("owner", { action: "add_to_shortlist", expected_revision: result.revision, draft_id: first.draft_id }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_SHORTLIST_DUPLICATE",
  );
  result = await value.application.command("owner", { action: "add_to_shortlist", expected_revision: result.revision, draft_id: second.draft_id });
  assert.deepEqual(result.state.shortlist.selections.map((item) => item.draft_id), [first.draft_id, second.draft_id]);
  assert.equal(result.state.shortlist.selections.every((item) => item.recommendation_set_id === result.state.recommendation_set.recommendation_set_id), true);

  const removeTab = await value.application.query("owner");
  const staleRemoveTab = await value.application.query("owner");
  result = await value.application.command("owner", { action: "remove_from_shortlist", expected_revision: removeTab.revision, draft_id: first.draft_id });
  assert.deepEqual(result.state.shortlist.selections.map((item) => item.draft_id), [second.draft_id]);
  assert.equal(result.state.shortlist.removed_selections[0].removed_index, 0);
  await assert.rejects(
    value.application.command("owner", { action: "remove_from_shortlist", expected_revision: staleRemoveTab.revision, draft_id: second.draft_id }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_REVISION_CONFLICT",
  );
  result = await value.application.command("owner", { action: "remove_from_shortlist", expected_revision: result.revision, draft_id: second.draft_id });
  assert.deepEqual(result.state.shortlist.selections, []);
  assert.deepEqual(result.state.shortlist.removed_selections.map((item) => item.removed_index).sort((left, right) => left - right), [0, 1]);
  result = await value.application.command("owner", { action: "restore_to_shortlist", expected_revision: result.revision, draft_id: second.draft_id });
  assert.deepEqual(result.state.shortlist.selections.map((item) => item.draft_id), [second.draft_id]);
  result = await value.application.command("owner", { action: "restore_to_shortlist", expected_revision: result.revision, draft_id: first.draft_id });
  assert.deepEqual(result.state.shortlist.selections.map((item) => item.draft_id), [first.draft_id, second.draft_id]);
  assert.deepEqual(result.state.shortlist.removed_selections, []);
  assert.equal(JSON.stringify(result.state.recommendation_set), recommendationBefore);
  assert.equal(JSON.stringify(result.state.analytics_evidence_snapshot), evidenceBefore);

  const restarted = new P0Application({ store: value.store, adapters: value.adapter });
  result = await restarted.query("owner");
  assert.deepEqual(result.state.shortlist.selections.map((item) => item.draft_id), [first.draft_id, second.draft_id]);
  const reviewTab = await restarted.query("owner");
  const staleReviewTab = await restarted.query("owner");
  const readsBeforeReview = value.contextReads();
  result = await restarted.command("owner", { action: "review_package", expected_revision: reviewTab.revision });
  assert.equal(value.contextReads(), readsBeforeReview, "package review must use persisted authoritative state without provider adapter reads");
  await assert.rejects(
    restarted.command("owner", { action: "review_package", expected_revision: staleReviewTab.revision }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_REVISION_CONFLICT",
  );
  const review = result.state.package_review;
  assert.deepEqual(review.authority.ordered_selections, result.state.shortlist.selections);
  assert.equal(review.authority.strategy_revision_id, result.state.strategy.strategy_revision_id);
  assert.equal(review.authority.recommendation_set_id, result.state.recommendation_set.recommendation_set_id);
  assert.equal(review.authority.direct_account_binding.account, "owner-account");
  assert.equal(review.authority.direct_capability_snapshot.snapshot_id, result.state.context_state.facts.direct.capability_snapshot.snapshot_id);
  assert.equal(review.authority.capability_profile.profile_id, result.state.recommendation_set.capability_profile.profile_id);
  assert.equal(review.authority.analytics_evidence_snapshot_id, result.state.analytics_evidence_snapshot.snapshot_id);
  assert.match(review.package_id, /^sha256:[a-f0-9]{64}$/u);
  assert.match(review.package_review_id, /^sha256:[a-f0-9]{64}$/u);
  assert.equal(review.authority.orchestration.selected_campaigns_execute_independently, true);
  assert.match(review.authority.orchestration.disclosure, /независимо/u);

  await assert.rejects(
    restarted.command("owner", { action: "confirm_package", expected_revision: result.revision, confirmation: "CONFIRM_PACKAGE", package_review_id: review.package_review_id, package_id: review.package_id }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_PACKAGE_CONFIRMATION_REQUIRED",
  );
  await assert.rejects(
    restarted.command("owner", { action: "confirm_package", expected_revision: result.revision, confirmation: "CONFIRM_EXACT_SHORTLIST_PACKAGE", package_review_id: "stale-review", package_id: review.package_id }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_PACKAGE_IDENTITY_STALE",
  );
  const confirmTab = await restarted.query("owner");
  const staleConfirmTab = await restarted.query("owner");
  const readsBeforeConfirmation = value.contextReads();
  result = await restarted.command("owner", { action: "confirm_package", expected_revision: confirmTab.revision, confirmation: "CONFIRM_EXACT_SHORTLIST_PACKAGE", package_review_id: review.package_review_id, package_id: review.package_id });
  assert.equal(value.contextReads(), readsBeforeConfirmation, "Gate confirmation must not call provider adapters");
  await assert.rejects(
    restarted.command("owner", { action: "confirm_package", expected_revision: staleConfirmTab.revision, confirmation: "CONFIRM_EXACT_SHORTLIST_PACKAGE", package_review_id: review.package_review_id, package_id: review.package_id }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_REVISION_CONFLICT",
  );
  assert.match(result.state.human_decision_gate.gate_id, /^sha256:[a-f0-9]{64}$/u);
  assert.equal(result.state.human_decision_gate.confirmed_at.includes("2026-08-21T10:00:"), true);
  assert.deepEqual(result.state.human_decision_gate.authority, review.authority);
  assert.equal(result.state.human_decision_gate.external_transactionality_promised, false);
  assert.equal(result.state.human_decision_gate.external_writes_performed, false);
  assert.equal(result.write_readiness.ready, true);
  assert.equal(result.workflow.allowed_commands.includes("dispatch_package"), true);
  const confirmedGate = JSON.stringify(result.state.human_decision_gate);
  const confirmedReview = JSON.stringify(result.state.package_review);
  const readsBeforeReopen = value.contextReads();
  result = await restarted.command("owner", { action: "review_package", expected_revision: result.revision });
  assert.equal(value.contextReads(), readsBeforeReopen, "reopening a current review must remain adapter-free");
  assert.equal(JSON.stringify(result.state.package_review), confirmedReview);
  assert.equal(JSON.stringify(result.state.human_decision_gate), confirmedGate);
  await assert.rejects(
    restarted.command("owner", { action: "confirm_package", expected_revision: result.revision, confirmation: "CONFIRM_EXACT_SHORTLIST_PACKAGE", package_review_id: review.package_review_id, package_id: review.package_id }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_TRANSITION_INVALID",
  );
  assert.equal(value.externalWrites(), 0);
  const afterRestart = await new P0Application({ store: value.store, adapters: value.adapter }).query("owner");
  assert.equal(afterRestart.state.human_decision_gate.gate_id, result.state.human_decision_gate.gate_id);
});

test("confirmed package dispatches every selected Draft independently and preserves mixed item outcomes", async (t) => {
  const value = await packageFixture(t);
  const eligible = value.result.state.recommendation_set.drafts.filter((draft) => draft.shortlist_eligible && draft.visibility === "VISIBLE");
  const selected = eligible.slice(0, 2);
  assert.equal(selected.length, 2);
  let result = await reviewAndConfirm(value.application, value.result, selected.map((draft) => draft.draft_id));
  const calls = [];
  value.adapter.createPackageItemOutcome = async ({ item_execution_id, selection, projection }) => {
    calls.push({ item_execution_id, selection, projection });
    if (selection.draft_id === selected[0].draft_id) {
      return {
        execution_id: item_execution_id,
        status: "MODERATION_PENDING",
        campaign_id: "90071992547409931",
        ad_group_id: "90071992547409932",
        keyword_id: "90071992547409933",
        ad_id: "90071992547409934",
        campaign_state: "SUSPENDED",
        moderation_status: "MODERATION",
        semantic_graph: { campaign: { State: "SUSPENDED" } },
        steps: ["CAMPAIGN_CREATED", "NON_SERVING_CONFIRMED", "AD_GROUP_CREATED", "KEYWORD_CREATED", "AD_CREATED", "OBJECT_GRAPH_VERIFIED", "MODERATION_SUBMITTED"],
        provider_issues: [],
        spend_started: false,
      };
    }
    return {
      execution_id: item_execution_id,
      status: "PROVIDER_REJECTED",
      error_code: "P0_DIRECT_ITEM_FAILED",
      error_message: "Direct rejected this exact item.",
      rejected: true,
      provider_issues: [{ operation: "Campaigns.add", severity: "ERROR", code: 5001, message: "Rejected", details: "Provider detail" }],
      containment: "NOT_CREATED",
      account_lock: "RELEASED",
    };
  };

  const confirmedGate = JSON.stringify(result.state.human_decision_gate);
  result = await value.application.command("owner", {
    action: "dispatch_package",
    expected_revision: result.revision,
    package_id: result.state.human_decision_gate.package_id,
    gate_id: result.state.human_decision_gate.gate_id,
  });

  assert.equal(calls.length, 2);
  assert.deepEqual(calls.map((call) => call.selection.draft_id), selected.map((draft) => draft.draft_id));
  assert.equal(calls.every((call) => call.projection.lineage.draft_revision_id === call.selection.draft_revision_id), true);
  assert.equal(new Set(calls.map((call) => call.item_execution_id)).size, 2);
  assert.equal(JSON.stringify(result.state.human_decision_gate), confirmedGate);
  assert.equal(result.state.package_execution.package_id, result.state.human_decision_gate.package_id);
  assert.equal(result.state.package_execution.gate_id, result.state.human_decision_gate.gate_id);
  assert.equal(result.state.package_execution.atomic_transaction, false);
  assert.equal(result.state.package_execution.status, "PENDING");
  assert.deepEqual(result.state.package_execution.items.map((item) => item.selection.draft_id), selected.map((draft) => draft.draft_id));
  assert.equal(result.state.package_execution.items[0].status, "MODERATION_PENDING");
  assert.equal(result.state.package_execution.items[0].ownership, "PENDING_PROVIDER_OUTCOME");
  assert.equal(result.state.package_execution.items[0].progress.suspension, "CONFIRMED_SUSPENDED");
  assert.equal(result.state.package_execution.items[0].progress.child_graph, "CREATED");
  assert.equal(result.state.package_execution.items[0].progress.readback, "VERIFIED");
  assert.equal(result.state.package_execution.items[0].progress.moderation, "PENDING");
  assert.equal(result.state.package_execution.items[0].provider_ids.campaign_id, "90071992547409931");
  assert.equal(result.state.package_execution.items[1].status, "PROVIDER_REJECTED");
  assert.equal(result.state.package_execution.items[1].ownership, "PROVIDER");
  assert.equal(result.state.package_execution.items[1].provider_issues[0].details, "Provider detail");
  assert.equal(result.state.package_execution.items[1].containment, "NOT_CREATED");
  assert.equal(result.state.package_execution.items[1].progress.creation, "REJECTED");
  assert.equal(result.decision_readiness.external_writes_performed, true);
  assert.equal(result.write_readiness.ready, false);

  const restarted = await new P0Application({ store: value.store, adapters: value.adapter }).query("owner");
  assert.deepEqual(restarted.state.package_execution, result.state.package_execution);
  assert.equal(restarted.workflow.allowed_commands.includes("dispatch_package"), false);
});

test("package dispatch continues after contained system failure but stops unsafe remaining items behind reconciliation", async (t) => {
  await t.test("definite pre-dispatch validation failure is NOT_CREATED and does not stop the next safe item", async (t) => {
    const value = await packageFixture(t);
    const selected = value.result.state.recommendation_set.drafts.filter((draft) => draft.shortlist_eligible && draft.visibility === "VISIBLE").slice(0, 2);
    let result = await reviewAndConfirm(value.application, value.result, selected.map((draft) => draft.draft_id));
    const calls = [];
    value.adapter.createPackageItemOutcome = async ({ item_execution_id, selection }) => {
      calls.push(selection.draft_id);
      if (selection.draft_id === selected[0].draft_id) {
        return {
          execution_id: item_execution_id,
          status: "SYSTEM_FAILED",
          error_code: "P0_CAPABILITY_OR_ACCOUNT_MISMATCH",
          error_message: "Exact item validation failed before dispatch.",
          validation_failed: true,
          dispatch_not_attempted: true,
          containment: "NOT_CREATED",
          account_lock: "RELEASED",
        };
      }
      return {
        execution_id: item_execution_id,
        status: "MODERATION_PENDING",
        campaign_id: "91",
        ad_group_id: "92",
        keyword_id: "93",
        ad_id: "94",
        campaign_state: "SUSPENDED",
        moderation_status: "MODERATION",
        semantic_graph: { campaign: { State: "SUSPENDED" } },
        steps: ["CAMPAIGN_CREATED", "NON_SERVING_CONFIRMED", "AD_GROUP_CREATED", "KEYWORD_CREATED", "AD_CREATED", "OBJECT_GRAPH_VERIFIED", "MODERATION_SUBMITTED"],
        account_lock: "RELEASED",
      };
    };

    result = await value.application.command("owner", {
      action: "dispatch_package",
      expected_revision: result.revision,
      package_id: result.state.human_decision_gate.package_id,
      gate_id: result.state.human_decision_gate.gate_id,
    });

    assert.deepEqual(calls, selected.map((draft) => draft.draft_id));
    assert.equal(result.state.package_execution.items[0].ownership, "SYSTEM");
    assert.equal(result.state.package_execution.items[0].progress.validation, "FAILED");
    assert.equal(result.state.package_execution.items[0].progress.creation, "NOT_ATTEMPTED");
    assert.equal(result.state.package_execution.items[0].containment, "NOT_CREATED");
    assert.equal(result.state.package_execution.items[1].status, "MODERATION_PENDING");
  });

  await t.test("contained system failure does not hide or stop the next independent item", async (t) => {
    const value = await packageFixture(t);
    const selected = value.result.state.recommendation_set.drafts.filter((draft) => draft.shortlist_eligible && draft.visibility === "VISIBLE").slice(0, 2);
    let result = await reviewAndConfirm(value.application, value.result, selected.map((draft) => draft.draft_id));
    const calls = [];
    value.adapter.createPackageItemOutcome = async ({ item_execution_id, selection }) => {
      calls.push(selection.draft_id);
      if (selection.draft_id === selected[0].draft_id) {
        return {
          execution_id: item_execution_id,
          status: "SYSTEM_FAILED",
          error_code: "P0_DIRECT_GRAPH_MISMATCH",
          error_message: "Provider silently altered a selected field.",
          campaign_id: "101",
          campaign_state: "SUSPENDED",
          steps: ["CAMPAIGN_CREATED", "NON_SERVING_CONFIRMED"],
          containment: "NON_SERVING_CONFIRMED",
          account_lock: "RELEASED",
        };
      }
      return {
        execution_id: item_execution_id,
        status: "MODERATION_PENDING",
        campaign_id: "201",
        ad_group_id: "202",
        keyword_id: "203",
        ad_id: "204",
        campaign_state: "SUSPENDED",
        moderation_status: "PREACCEPTED",
        semantic_graph: { campaign: { State: "SUSPENDED" } },
        steps: ["CAMPAIGN_CREATED", "NON_SERVING_CONFIRMED", "AD_GROUP_CREATED", "KEYWORD_CREATED", "AD_CREATED", "OBJECT_GRAPH_VERIFIED", "MODERATION_SUBMITTED"],
        account_lock: "RELEASED",
      };
    };

    result = await value.application.command("owner", {
      action: "dispatch_package",
      expected_revision: result.revision,
      package_id: result.state.human_decision_gate.package_id,
      gate_id: result.state.human_decision_gate.gate_id,
    });

    assert.deepEqual(calls, selected.map((draft) => draft.draft_id));
    assert.equal(result.state.package_execution.items[0].ownership, "SYSTEM");
    assert.equal(result.state.package_execution.items[0].containment, "CONFIRMED_SUSPENDED");
    assert.equal(result.state.package_execution.items[0].failure.code, "P0_DIRECT_GRAPH_MISMATCH");
    assert.equal(result.state.package_execution.items[1].ownership, "PENDING_PROVIDER_OUTCOME");
    assert.equal(result.state.package_execution.items[1].progress.moderation, "PENDING");
  });

  await t.test("created item without exact SUSPENDED proof leaves the package fail closed", async (t) => {
    const value = await packageFixture(t);
    const selected = value.result.state.recommendation_set.drafts.filter((draft) => draft.shortlist_eligible && draft.visibility === "VISIBLE").slice(0, 2);
    let result = await reviewAndConfirm(value.application, value.result, selected.map((draft) => draft.draft_id));
    const calls = [];
    value.adapter.createPackageItemOutcome = async ({ item_execution_id, selection }) => {
      calls.push(selection.draft_id);
      return {
        execution_id: item_execution_id,
        status: "PROVIDER_REJECTED",
        rejected: true,
        campaign_id: "301",
        containment: "NON_SERVING_CONFIRMED",
        account_lock: "RELEASED",
        provider_issues: [{ operation: "AdGroups.add", severity: "ERROR", code: 5002, message: "Child rejected", details: "" }],
      };
    };

    result = await value.application.command("owner", {
      action: "dispatch_package",
      expected_revision: result.revision,
      package_id: result.state.human_decision_gate.package_id,
      gate_id: result.state.human_decision_gate.gate_id,
    });

    assert.equal(result.state.package_execution.items[0].provider_ids.campaign_id, "301");
    assert.equal(result.state.package_execution.items[0].progress.suspension, "FAILED");
    assert.equal(result.state.package_execution.status, "FAIL_CLOSED");
    assert.deepEqual(calls, [selected[0].draft_id]);
    assert.equal(result.state.package_execution.items[1].status, "QUEUED");
  });

  await t.test("mismatched durable item execution identity is unknown and blocks later dispatch", async (t) => {
    const value = await packageFixture(t);
    const selected = value.result.state.recommendation_set.drafts.filter((draft) => draft.shortlist_eligible && draft.visibility === "VISIBLE").slice(0, 2);
    let result = await reviewAndConfirm(value.application, value.result, selected.map((draft) => draft.draft_id));
    const calls = [];
    value.adapter.createPackageItemOutcome = async ({ selection }) => {
      calls.push(selection.draft_id);
      return {
        execution_id: "forged-execution-id",
        status: "MODERATION_PENDING",
        campaign_id: "501",
        campaign_state: "SUSPENDED",
        moderation_status: "MODERATION",
        account_lock: "RELEASED",
      };
    };

    result = await value.application.command("owner", {
      action: "dispatch_package",
      expected_revision: result.revision,
      package_id: result.state.human_decision_gate.package_id,
      gate_id: result.state.human_decision_gate.gate_id,
    });

    assert.deepEqual(calls, [selected[0].draft_id]);
    assert.equal(result.state.package_execution.status, "RECONCILIATION_REQUIRED");
    assert.equal(result.state.package_execution.items[0].ownership, "UNKNOWN");
    assert.equal(result.state.package_execution.items[0].failure.code, "P0_PACKAGE_ITEM_IDENTITY_MISMATCH");
    assert.equal(result.state.package_execution.items[1].status, "QUEUED");
  });

  await t.test("ambiguous item holds the account boundary and leaves later items undispatched", async (t) => {
    const value = await packageFixture(t);
    const selected = value.result.state.recommendation_set.drafts.filter((draft) => draft.shortlist_eligible && draft.visibility === "VISIBLE").slice(0, 2);
    let result = await reviewAndConfirm(value.application, value.result, selected.map((draft) => draft.draft_id));
    const calls = [];
    value.adapter.createPackageItemOutcome = async ({ item_execution_id, selection }) => {
      calls.push(selection.draft_id);
      return {
        execution_id: item_execution_id,
        status: "RECONCILIATION_REQUIRED",
        error_code: "P0_DIRECT_OUTCOME_AMBIGUOUS",
        error_message: "Campaigns.add outcome is unknown.",
        requires_reconciliation: true,
        containment: "RECONCILIATION_REQUIRED",
        account_lock: "HELD_FOR_RECONCILIATION",
      };
    };

    result = await value.application.command("owner", {
      action: "dispatch_package",
      expected_revision: result.revision,
      package_id: result.state.human_decision_gate.package_id,
      gate_id: result.state.human_decision_gate.gate_id,
    });

    assert.deepEqual(calls, [selected[0].draft_id]);
    assert.equal(result.state.package_execution.status, "RECONCILIATION_REQUIRED");
    assert.equal(result.state.package_execution.items[0].ownership, "UNKNOWN");
    assert.equal(result.state.package_execution.items[0].account_lock, "HELD_FOR_RECONCILIATION");
    assert.equal(result.state.package_execution.items[1].status, "QUEUED");
    assert.equal(result.state.package_execution.items[1].progress.creation, "PENDING");
  });
});

test("package dispatch blocks the whole set before durable intent when current account binding changed", async (t) => {
  const value = await packageFixture(t);
  const selected = value.result.state.recommendation_set.drafts.filter((draft) => draft.shortlist_eligible && draft.visibility === "VISIBLE").slice(0, 2);
  const confirmed = await reviewAndConfirm(value.application, value.result, selected.map((draft) => draft.draft_id));
  const changedContext = structuredClone(context());
  changedContext.direct.account = "other-account";
  changedContext.direct.client_id = "client-other";
  changedContext.direct.binding.expected_account = "other-account";
  changedContext.direct.binding.api_account = "other-account";
  changedContext.direct.capability_snapshot.account = "other-account";
  let externalCalls = 0;
  const changedAdapter = adapters({
    async readContext() { return changedContext; },
    async createPackageItemOutcome() { externalCalls += 1; throw new Error("must not dispatch"); },
  });
  const changedApplication = new P0Application({ store: value.store, adapters: changedAdapter });

  await assert.rejects(
    changedApplication.command("owner", {
      action: "dispatch_package",
      expected_revision: confirmed.revision,
      package_id: confirmed.state.human_decision_gate.package_id,
      gate_id: confirmed.state.human_decision_gate.gate_id,
    }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_CONTEXT_PREFLIGHT_CHANGED",
  );
  assert.equal(externalCalls, 0);
  const unchanged = await value.store.load("owner");
  assert.equal(JSON.parse(unchanged.value_json).package_execution, null);
});

test("restart resumes a durable DISPATCHING item with the same deterministic execution identity", async (t) => {
  const value = await packageFixture(t);
  const selected = value.result.state.recommendation_set.drafts.filter((draft) => draft.shortlist_eligible && draft.visibility === "VISIBLE").slice(0, 1);
  const confirmed = await reviewAndConfirm(value.application, value.result, selected.map((draft) => draft.draft_id));
  const originalCompareAndSwap = value.store.compareAndSwap.bind(value.store);
  let rejectOutcomeCheckpoint = false;
  value.store.compareAndSwap = async (...args) => {
    if (rejectOutcomeCheckpoint) {
      rejectOutcomeCheckpoint = false;
      return false;
    }
    return originalCompareAndSwap(...args);
  };
  const calls = [];
  value.adapter.createPackageItemOutcome = async ({ item_execution_id }) => {
    calls.push(item_execution_id);
    if (calls.length === 1) rejectOutcomeCheckpoint = true;
    return {
      execution_id: item_execution_id,
      status: "MODERATION_PENDING",
      campaign_id: "401",
      ad_group_id: "402",
      keyword_id: "403",
      ad_id: "404",
      campaign_state: "SUSPENDED",
      moderation_status: "MODERATION",
      semantic_graph: { campaign: { State: "SUSPENDED" } },
      steps: ["CAMPAIGN_CREATED", "NON_SERVING_CONFIRMED", "AD_GROUP_CREATED", "KEYWORD_CREATED", "AD_CREATED", "OBJECT_GRAPH_VERIFIED", "MODERATION_SUBMITTED"],
      account_lock: "RELEASED",
    };
  };

  await assert.rejects(
    value.application.command("owner", {
      action: "dispatch_package",
      expected_revision: confirmed.revision,
      package_id: confirmed.state.human_decision_gate.package_id,
      gate_id: confirmed.state.human_decision_gate.gate_id,
    }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_REVISION_CONFLICT",
  );
  value.store.compareAndSwap = originalCompareAndSwap;
  const interrupted = await new P0Application({ store: value.store, adapters: value.adapter }).query("owner");
  assert.equal(interrupted.state.package_execution.items[0].status, "DISPATCHING");
  assert.equal(interrupted.workflow.allowed_commands.includes("dispatch_package"), true);

  const recovered = await new P0Application({ store: value.store, adapters: value.adapter }).command("owner", {
    action: "dispatch_package",
    expected_revision: interrupted.revision,
    package_id: interrupted.state.human_decision_gate.package_id,
    gate_id: interrupted.state.human_decision_gate.gate_id,
  });
  assert.equal(calls.length, 2);
  assert.equal(calls[0], calls[1]);
  assert.equal(recovered.state.package_execution.items[0].item_execution_id, calls[0]);
  assert.equal(recovered.state.package_execution.items[0].provider_ids.campaign_id, "401");
  assert.equal(recovered.state.package_execution.items[0].status, "MODERATION_PENDING");
});

test("restart preserves a terminal provider rejection after the package outcome checkpoint was interrupted", async (t) => {
  const value = await packageFixture(t);
  const draft = value.result.state.recommendation_set.drafts.find((item) => item.shortlist_eligible && item.visibility === "VISIBLE");
  const confirmed = await reviewAndConfirm(value.application, value.result, [draft.draft_id]);
  const originalCompareAndSwap = value.store.compareAndSwap.bind(value.store);
  let rejectOutcomeCheckpoint = false;
  value.store.compareAndSwap = async (...args) => {
    if (rejectOutcomeCheckpoint) {
      rejectOutcomeCheckpoint = false;
      return false;
    }
    return originalCompareAndSwap(...args);
  };
  const calls = [];
  const providerOutcome = {
    status: "PROVIDER_REJECTED",
    rejected: true,
    error_code: "P0_DIRECT_ITEM_FAILED",
    error_message: "Direct rejected the campaign.",
    provider_issues: [{ operation: "Campaigns.add", severity: "ERROR", code: 5001, message: "Rejected", details: "Original provider detail" }],
    containment: "NOT_CREATED",
    account_lock: "RELEASED",
  };
  value.adapter.createPackageItemOutcome = async ({ item_execution_id }) => {
    calls.push(item_execution_id);
    if (calls.length === 1) {
      rejectOutcomeCheckpoint = true;
      return { execution_id: item_execution_id, ...providerOutcome };
    }
    return directExecutionFailureOutcome(item_execution_id, Object.assign(new Error("Execution already terminal."), {
      code: "P0_EXECUTION_ALREADY_TERMINAL",
      partial: { previous_status: "PROVIDER_REJECTED", previous_result: providerOutcome },
    }));
  };

  await assert.rejects(
    value.application.command("owner", {
      action: "dispatch_package",
      expected_revision: confirmed.revision,
      package_id: confirmed.state.human_decision_gate.package_id,
      gate_id: confirmed.state.human_decision_gate.gate_id,
    }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_REVISION_CONFLICT",
  );
  value.store.compareAndSwap = originalCompareAndSwap;
  const interrupted = await new P0Application({ store: value.store, adapters: value.adapter }).query("owner");
  const recovered = await new P0Application({ store: value.store, adapters: value.adapter }).command("owner", {
    action: "dispatch_package",
    expected_revision: interrupted.revision,
    package_id: interrupted.state.human_decision_gate.package_id,
    gate_id: interrupted.state.human_decision_gate.gate_id,
  });

  assert.equal(calls.length, 2);
  assert.equal(calls[0], calls[1]);
  assert.equal(recovered.state.package_execution.items[0].status, "PROVIDER_REJECTED");
  assert.equal(recovered.state.package_execution.items[0].ownership, "PROVIDER");
  assert.equal(recovered.state.package_execution.items[0].containment, "NOT_CREATED");
  assert.equal(recovered.state.package_execution.items[0].provider_issues[0].details, "Original provider detail");
});

test("same-schema package item outcome tampering fails closed before UI reuse", async (t) => {
  const value = await packageFixture(t);
  const draft = value.result.state.recommendation_set.drafts.find((item) => item.shortlist_eligible && item.visibility === "VISIBLE");
  const result = await reviewAndConfirm(value.application, value.result, [draft.draft_id]);
  value.adapter.createPackageItemOutcome = async ({ item_execution_id }) => ({
    execution_id: item_execution_id,
    status: "MODERATION_PENDING",
    campaign_id: "601",
    ad_group_id: "602",
    keyword_id: "603",
    ad_id: "604",
    campaign_state: "SUSPENDED",
    moderation_status: "MODERATION",
    semantic_graph: { campaign: { State: "SUSPENDED" } },
    steps: ["CAMPAIGN_CREATED", "NON_SERVING_CONFIRMED", "AD_GROUP_CREATED", "KEYWORD_CREATED", "AD_CREATED", "OBJECT_GRAPH_VERIFIED", "MODERATION_SUBMITTED"],
    account_lock: "RELEASED",
  });
  await value.application.command("owner", {
    action: "dispatch_package",
    expected_revision: result.revision,
    package_id: result.state.human_decision_gate.package_id,
    gate_id: result.state.human_decision_gate.gate_id,
  });
  const row = await value.store.load("owner");
  const corrupted = JSON.parse(row.value_json);
  corrupted.package_execution.items[0].provider_ids.campaign_id = "forged-provider-id";
  await value.store.seed("owner", { ...row, value_json: JSON.stringify(corrupted) });

  await assert.rejects(
    new P0Application({ store: value.store, adapters: value.adapter }).query("owner"),
    (error) => error instanceof P0ApplicationError
      && error.code === "P0_MIGRATION_LINEAGE_INVALID"
      && /package execution/iu.test(error.message),
  );
});

test("authoritative shortlist command rejects blocked and evidence-gap Drafts without rewriting candidate or evidence audit", async (t) => {
  const { application, result: approved } = await approvedDraftFixture(t);
  const blocked = approved.state.recommendation_set.drafts[0];
  const recommendationBefore = JSON.stringify(approved.state.recommendation_set);
  const evidenceBefore = JSON.stringify(approved.state.analytics_evidence_snapshot);
  await assert.rejects(
    application.command("owner", { action: "add_to_shortlist", expected_revision: approved.revision, draft_id: blocked.draft_id }),
    (error) => error instanceof P0ApplicationError && error.code === "P0_SHORTLIST_BLOCKED" && /playbook|evidence|Draft/iu.test(error.message),
  );
  const after = await application.query("owner");
  assert.equal(after.revision, approved.revision);
  assert.equal(JSON.stringify(after.state.recommendation_set), recommendationBefore);
  assert.equal(JSON.stringify(after.state.analytics_evidence_snapshot), evidenceBefore);
  assert.deepEqual(after.state.shortlist.selections, []);
  assert.equal(after.shortlist_controls.find((item) => item.draft_id === blocked.draft_id).status, "BLOCKED");
  assert.equal(typeof after.shortlist_controls.find((item) => item.draft_id === blocked.draft_id).disabled_reason, "string");
});

test("v5 package authority migrates to v6 without discarding the exact confirmed Gate", async (t) => {
  const value = await packageFixture(t);
  const draft = value.result.state.recommendation_set.drafts.find((item) => item.shortlist_eligible && item.visibility === "VISIBLE");
  const confirmed = await reviewAndConfirm(value.application, value.result, [draft.draft_id]);
  const row = await value.store.load("owner");
  const legacy = JSON.parse(row.value_json);
  legacy.schema_version = "p0-application-document-v5";
  delete legacy.package_execution;
  await value.store.seed("owner", { ...row, value_json: JSON.stringify(legacy) });

  const migrated = await new P0Application({ store: value.store, adapters: value.adapter }).query("owner");
  assert.equal(migrated.state.schema_version, P0_DOCUMENT_SCHEMA);
  assert.equal(migrated.state.package_execution, null);
  assert.deepEqual(migrated.state.package_review, confirmed.state.package_review);
  assert.deepEqual(migrated.state.human_decision_gate, confirmed.state.human_decision_gate);
  assert.equal(migrated.workflow.allowed_commands.includes("dispatch_package"), true);
});

test("same-schema shortlist, package and confirmation tampering all fail closed on restart", async (t) => {
  const value = await packageFixture(t);
  const eligible = value.result.state.recommendation_set.drafts.filter((draft) => draft.shortlist_eligible && draft.visibility === "VISIBLE");
  const confirmed = await reviewAndConfirm(value.application, value.result, eligible.slice(0, 2).map((draft) => draft.draft_id));
  const row = await value.store.load("owner");
  const cases = [
    ["selected Draft ID", (state) => { state.shortlist.selections[0].draft_id = "draft-forged"; }],
    ["selected Draft revision", (state) => { state.shortlist.selections[0].draft_revision_id = "draft-forged-r9"; }],
    ["selected publish fingerprint", (state) => { state.shortlist.selections[0].publish_fingerprint = `sha256:${"0".repeat(64)}`; }],
    ["package contents", (state) => { state.package_review.authority.direct_account_binding.account = "other-account"; }],
    ["confirmation token", (state) => { state.human_decision_gate.confirmation_token = "FORGED"; }],
    ["confirmation timestamp", (state) => { state.human_decision_gate.confirmed_at = "2030-01-01T00:00:00.000Z"; }],
  ];
  for (const [name, mutate] of cases) {
    const corrupted = JSON.parse(row.value_json);
    assert.equal(corrupted.schema_version, P0_DOCUMENT_SCHEMA);
    mutate(corrupted);
    await value.store.seed("owner", { ...row, value_json: JSON.stringify(corrupted) });
    await assert.rejects(
      new P0Application({ store: value.store, adapters: value.adapter }).query("owner"),
      (error) => error instanceof P0ApplicationError && error.code === "P0_MIGRATION_LINEAGE_INVALID",
      name,
    );
    assert.equal((await value.store.load("owner")).value_json, JSON.stringify(corrupted));
  }
  await value.store.seed("owner", row);
  const restarted = await new P0Application({ store: value.store, adapters: value.adapter }).query("owner");
  assert.equal(restarted.state.human_decision_gate.gate_id, confirmed.state.human_decision_gate.gate_id);
});

test("normalization preserves exact package Gate while a material Draft edit invalidates and rebases shortlist lineage", async (t) => {
  const value = await packageFixture(t);
  const draft = value.result.state.recommendation_set.drafts.find((item) => item.shortlist_eligible && item.visibility === "VISIBLE");
  let result = await reviewAndConfirm(value.application, value.result, [draft.draft_id]);
  const reviewBefore = JSON.stringify(result.state.package_review);
  const gateBefore = JSON.stringify(result.state.human_decision_gate);
  result = await value.application.command("owner", {
    action: "save_draft",
    expected_revision: result.revision,
    value: editableDraftValue(draft, { campaign_name: `  ${draft.campaign_name.replaceAll(" ", "   ")}  ` }),
  });
  assert.equal(result.state.draft.draft_save_result.material_change, false);
  assert.equal(JSON.stringify(result.state.package_review), reviewBefore);
  assert.equal(JSON.stringify(result.state.human_decision_gate), gateBefore);

  result = await value.application.command("owner", {
    action: "save_draft",
    expected_revision: result.revision,
    value: editableDraftValue(result.state.draft, { campaign_name: `${draft.campaign_name} · material owner edit` }),
  });
  assert.equal(result.state.draft.draft_save_result.material_change, true);
  assert.equal(result.state.package_review, null);
  assert.equal(result.state.human_decision_gate, null);
  assert.equal(result.state.last_decision_invalidation.reason_code, "DRAFT_MATERIAL_CHANGE");
  assert.equal(result.state.shortlist.selections[0].draft_id, draft.draft_id);
  assert.equal(result.state.shortlist.selections[0].draft_revision_id, result.state.draft.draft_revision_id);
  assert.equal(result.state.shortlist.selections[0].publish_fingerprint, result.state.draft.publish_fingerprint);
  assert.equal(result.state.shortlist.selections[0].recommendation_set_id, result.state.recommendation_set.recommendation_set_id);
});

test("Strategy, Model, Context and playbook material paths invalidate current Gate with an audit-visible reason", async (t) => {
  await t.test("Strategy", async (t) => {
    const value = await packageFixture(t);
    const draft = value.result.state.recommendation_set.drafts.find((item) => item.shortlist_eligible && item.visibility === "VISIBLE");
    let result = await reviewAndConfirm(value.application, value.result, [draft.draft_id]);
    result = await approveStrategy(value.application, result, { core_message: "Материально новое сообщение владельца" });
    assert.equal(result.state.package_review, null);
    assert.equal(result.state.human_decision_gate, null);
    assert.equal(result.state.last_decision_invalidation.reason_code, "STRATEGY_MATERIAL_CHANGE");
    assert.deepEqual(result.state.shortlist.selections, []);
  });

  await t.test("Model evidence lineage", async (t) => {
    const value = await packageFixture(t);
    const draft = value.result.state.recommendation_set.drafts.find((item) => item.shortlist_eligible && item.visibility === "VISIBLE");
    let result = await reviewAndConfirm(value.application, value.result, [draft.draft_id]);
    const changed = ownerModel(result.state);
    changed.product = "Материально другое предложение";
    result = await value.application.command("owner", { action: "save_business_model", expected_revision: result.revision, value: changed });
    assert.equal(result.state.package_review, null);
    assert.equal(result.state.human_decision_gate, null);
    assert.equal(result.state.last_decision_invalidation.reason_code, "MODEL_MATERIAL_CHANGE");
    assert.equal(result.state.analytics_evidence_snapshot.snapshot_id === value.result.state.analytics_evidence_snapshot.snapshot_id, false);
  });

  await t.test("Context", async (t) => {
    const value = await packageFixture(t);
    const draft = value.result.state.recommendation_set.drafts.find((item) => item.shortlist_eligible && item.visibility === "VISIBLE");
    let result = await reviewAndConfirm(value.application, value.result, [draft.draft_id]);
    const baseResearch = value.adapter.researchSite.bind(value.adapter);
    const changedAdapter = {
      ...value.adapter,
      async researchSite(url) {
        const site = await baseResearch(url);
        site.description = "Материально новая first-party услуга.";
        site.pages[0].description = site.description;
        return site;
      },
    };
    result = await new P0Application({ store: value.store, adapters: changedAdapter }).command("owner", { action: "analyze_site", expected_revision: result.revision, url: "https://owner.example/" });
    assert.equal(result.state.package_review, null);
    assert.equal(result.state.human_decision_gate, null);
    assert.equal(result.state.last_decision_invalidation.reason_code, "CONTEXT_MATERIAL_CHANGE");
  });

  await t.test("playbook regeneration", async (t) => {
    const value = await packageFixture(t);
    const draft = value.result.state.recommendation_set.drafts.find((item) => item.shortlist_eligible && item.visibility === "VISIBLE");
    let result = await reviewAndConfirm(value.application, value.result, [draft.draft_id]);
    value.setReleases([await governedPlaybookRelease({ releaseId: "fixture-release-replacement", releaseVersion: "2.0.0", family: "MESSAGE_OFFER", decisionId: "decision-replacement" })]);
    result = await value.application.command("owner", { action: "recalculate_recommendations", expected_revision: result.revision });
    assert.equal(result.state.package_review, null);
    assert.equal(result.state.human_decision_gate, null);
    assert.equal(result.state.last_decision_invalidation.reason_code, "PLAYBOOK_REGENERATION");
    assert.deepEqual(result.state.shortlist.selections, []);
  });
});

test("same exact active playbook release preserves a material owner Draft revision and every downstream decision", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "mox-p0-playbook-no-change-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const store = new JsonDurableStore(join(directory, "state.json"));
  const releases = [await governedPlaybookRelease({ releaseId: "fixture-release-stable", releaseVersion: "2.0.0", family: "QUALIFIED_ACTION", decisionId: "decision-stable" })];
  const application = new P0Application({ store, adapters: adapters({ async readPlaybookReleases() { return releases; } }) });
  let result = await application.command("owner", { action: "analyze_site", expected_revision: 0, url: "https://owner.example/" });
  result = await application.command("owner", { action: "confirm_context_goal", expected_revision: result.revision, confirmation: "CONFIRM_CONTEXT_GOAL", goal: result.state.context_state.provisional_business_goal.value });
  result = await application.command("owner", { action: "save_business_model", expected_revision: result.revision, value: ownerModel(result.state) });
  result = await approveStrategy(application, result);
  const improvement = result.state.recommendation_set.drafts.find((draft) => draft.variant.kind === "IMPROVEMENT" && draft.visibility === "VISIBLE");
  assert.ok(improvement);
  result = await application.command("owner", {
    action: "save_draft",
    expected_revision: result.revision,
    value: editableDraftValue(improvement, { campaign_name: `${improvement.campaign_name} · owner material edit` }),
  });
  assert.equal(result.state.draft.draft_save_result.material_change, true);
  const preserved = {
    recommendation_set: JSON.stringify(result.state.recommendation_set),
    draft: JSON.stringify(result.state.draft),
    shortlist: JSON.stringify(result.state.shortlist),
    external_write_intent: JSON.stringify(result.state.external_write_intent),
    candidate_audit: JSON.stringify(result.state.recommendation_set.candidate_audit),
    recommendation_set_id: result.state.recommendation_set.recommendation_set_id,
    draft_revision_id: result.state.draft.draft_revision_id,
    publish_fingerprint: result.state.draft.publish_fingerprint,
    score: result.state.draft.viability_score.score,
    rank: result.state.draft.viability_score.rank,
  };

  result = await application.command("owner", { action: "recalculate_recommendations", expected_revision: result.revision });

  assert.equal(JSON.stringify(result.state.recommendation_set), preserved.recommendation_set);
  assert.equal(JSON.stringify(result.state.draft), preserved.draft);
  assert.equal(JSON.stringify(result.state.shortlist), preserved.shortlist);
  assert.equal(JSON.stringify(result.state.external_write_intent), preserved.external_write_intent);
  assert.equal(JSON.stringify(result.state.recommendation_set.candidate_audit), preserved.candidate_audit);
  assert.equal(result.state.recommendation_set.recommendation_set_id, preserved.recommendation_set_id);
  assert.equal(result.state.draft.draft_revision_id, preserved.draft_revision_id);
  assert.equal(result.state.draft.publish_fingerprint, preserved.publish_fingerprint);
  assert.equal(result.state.draft.viability_score.score, preserved.score);
  assert.equal(result.state.draft.viability_score.rank, preserved.rank);
  assert.deepEqual(result.state.recommendation_recalculation, {
    schema_version: "p0-recommendation-recalculation-v1",
    material_change: false,
    message: "Active playbook check завершён без material изменения active release lineage.",
    reason_code: "NO_ACTIVE_PLAYBOOK_MATERIAL_CHANGE",
    recalculated_at: result.state.recommendation_recalculation.recalculated_at,
    previous_recommendation_set_id: preserved.recommendation_set_id,
    current_recommendation_set_id: preserved.recommendation_set_id,
    previous_playbook_release_id: "fixture-release-stable",
    current_playbook_release_id: "fixture-release-stable",
    changes: [],
    evaluator_traces_exposed: false,
  });
});

test("active playbook rollback persists a visible exact-lineage notice with truthful bounded candidate changes", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "mox-p0-playbook-recalculation-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const store = new JsonDurableStore(join(directory, "state.json"));
  let releases = [await governedPlaybookRelease({ releaseId: "fixture-release-new", releaseVersion: "2.0.0", family: "QUALIFIED_ACTION", decisionId: "decision-new" })];
  const application = new P0Application({ store, adapters: adapters({ async readPlaybookReleases() { return releases; } }) });
  let result = await application.command("owner", { action: "analyze_site", expected_revision: 0, url: "https://owner.example/" });
  result = await application.command("owner", { action: "confirm_context_goal", expected_revision: result.revision, confirmation: "CONFIRM_CONTEXT_GOAL", goal: result.state.context_state.provisional_business_goal.value });
  result = await application.command("owner", { action: "save_business_model", expected_revision: result.revision, value: ownerModel(result.state) });
  result = await approveStrategy(application, result);
  const improvement = result.state.recommendation_set.drafts.find((draft) => draft.variant.kind === "IMPROVEMENT" && draft.visibility === "VISIBLE");
  assert.ok(improvement);
  result = await application.command("owner", { action: "save_draft", expected_revision: result.revision, value: editableDraftValue(improvement) });
  const previous = { draft_id: result.state.draft.draft_id };
  const previousDraftIds = result.state.recommendation_set.drafts.map((draft) => draft.draft_id);

  releases = [await governedPlaybookRelease({ releaseId: "fixture-release-rollback", releaseVersion: "1.0.0", family: "MESSAGE_OFFER", decisionId: "decision-rollback" })];
  result = await application.command("owner", { action: "recalculate_recommendations", expected_revision: result.revision });
  const notice = result.state.recommendation_recalculation;
  assert.equal(notice.material_change, true);
  assert.equal(notice.reason_code, "ACTIVE_PLAYBOOK_RELEASE_CHANGED_OR_ROLLED_BACK");
  assert.match(notice.message, /изменился или был откачен/u);
  assert.equal(notice.previous_playbook_release_id, "fixture-release-new");
  assert.equal(notice.current_playbook_release_id, "fixture-release-rollback");
  assert.equal(notice.evaluator_traces_exposed, false);
  assert.equal(Object.hasOwn(notice, "evaluator_trace"), false);
  assert.equal(notice.changes.length > 0, true);
  assert.equal(notice.changes.every((change) => ["REPLACED", "REMOVED", "ADDED"].includes(change.change_type)), true);
  assert.equal(notice.changes.some((change) => change.change_type === "REMOVED" && change.previous_draft_id === previous.draft_id && change.current_draft_id === null), true);
  const added = notice.changes.find((change) => change.change_type === "ADDED");
  assert.ok(added);
  assert.equal(added.previous_draft_id, null);
  assert.equal(result.state.recommendation_set.drafts.some((draft) => draft.draft_id === added.current_draft_id && draft.variant.hypothesis?.changed_family === "MESSAGE_OFFER"), true);
  assert.equal(notice.changes.every((change) => !Object.hasOwn(change, "evaluator_trace") && !Object.hasOwn(change, "publish_projection")), true);
  assert.equal(previousDraftIds.every((draftId) => notice.changes.some((change) => change.previous_draft_id === draftId)), true);
  assert.equal(result.state.recommendation_set.drafts.every((draft) => notice.changes.some((change) => change.current_draft_id === draft.draft_id)), true);
  assert.equal(result.state.draft, null);
  assert.equal(result.state.shortlist.schema_version, "p0-shortlist-v2");
  assert.deepEqual(result.state.shortlist.selections, []);
  assert.equal(result.state.recommendation_set.playbook_release.release_id, "fixture-release-rollback");
});

test("every editable Direct field round-trips into a material immutable Draft revision with full fixed-membership rescore", async (t) => {
  const { application, result: approved } = await approvedDraftFixture(t);
  let result = approved;
  let current = result.state.recommendation_set.drafts.find((draft) => draft.visibility === "VISIBLE");
  const cases = [
    ["campaign_name", `${current.campaign_name} · owner`, "/direct/campaign/Name"],
    ["group_name", `${current.group_name} · owner`, "/direct/ad_group/Name"],
    ["negative_keywords", `${current.negative_keywords}, реферат`, "/direct/ad_group/NegativeKeywords/Items"],
    ["keyword", `${current.keyword} цена`, "/direct/keyword/Keyword"],
    ["ad_title", "Заявка на выставку", "/direct/ad/TextAd/Title"],
    ["ad_text", "Оставьте заявку на участие в выставке прямо сейчас", "/direct/ad/TextAd/Text"],
  ];
  let expectedRevision = 1;
  for (const [inputName, nextValue, expectedPointer] of cases) {
    const previousRecommendationSetId = result.state.recommendation_set.recommendation_set_id;
    const previousFingerprint = current.publish_fingerprint;
    const previousScores = Object.fromEntries(result.state.recommendation_set.drafts.map((draft) => [draft.draft_id, draft.viability_score.fingerprints.input]));
    result = await application.command("owner", {
      action: "save_draft",
      expected_revision: result.revision,
      value: editableDraftValue(current, { [inputName]: nextValue }),
    });
    current = result.state.draft;
    expectedRevision += 1;
    assert.equal(current.draft_revision_id, `${current.draft_id}-r${expectedRevision}`);
    assert.notEqual(current.publish_fingerprint, previousFingerprint);
    assert.notEqual(result.state.recommendation_set.recommendation_set_id, previousRecommendationSetId);
    assert.deepEqual(current.material_delta.fields.map((field) => field.pointer), [expectedPointer]);
    assert.equal(current.material_delta.fields[0].reason_code, "SUPPORTED_PUBLISHABLE_FIELD_CHANGED");
    assert.equal(current.draft_save_result.material_change, true);
    assert.equal(current.score_delta.changed_pointers.includes(expectedPointer), true);
    assert.equal(typeof current.score_delta.comparative_priority_reason.message, "string");
    assert.equal(current.score_delta.comparative_priority_reason.message.length > 0, true);
    assert.equal(result.state.recommendation_set.drafts.length, Object.keys(previousScores).length);
    for (const draft of result.state.recommendation_set.drafts) {
      assert.notEqual(draft.viability_score.fingerprints.input, previousScores[draft.draft_id]);
      assert.equal(draft.viability_score.ranking.recommendation_set_id, result.state.recommendation_set.recommendation_set_id);
    }
    assert.equal(result.state.recommendation_set.coverage.generated_count, result.state.recommendation_set.coverage.visible_count + result.state.recommendation_set.coverage.hidden_count);
    assert.equal(result.state.recommendation_set.coverage.generated_count, result.state.recommendation_set.candidate_audit.length);
    assert.equal(result.state.shortlist.schema_version, "p0-shortlist-v2");
    assert.deepEqual(result.state.shortlist.selections, []);
  }
});
