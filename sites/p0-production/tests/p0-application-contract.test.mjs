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
      dynamics_from_date: "2025-01-01",
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
  result = await application.command("owner", { action: "save_strategy", expected_revision: result.revision, value: strategyValue() });
  assert.equal(result.state.recommendation_set.delivery_packing.delivery_buckets.length, 1);
  assert.equal(result.state.recommendation_set.delivery_packing.delivery_buckets[0].disposition, "PACKED");
  assert.equal(result.state.recommendation_set.drafts.every((draft) => draft.market_evidence.frequency.snapshot_batch_id === result.state.analytics_evidence_snapshot.market_evidence.snapshot_batch_id), true);
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

  result = await restarted.command("owner", {
    action: "save_strategy",
    expected_revision: result.revision,
    value: strategyValue(),
  });
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
  assert.equal(result.revision, 5);
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
  assert.equal(afterBlockedWrite.revision, 5);
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
  result = await application.command("owner", { action: "save_strategy", expected_revision: result.revision, value: strategyValue() });
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
