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
      account: "owner-account",
      campaigns_total: 1,
      minimum_weekly_budget_rub: 300,
      observed_at: "2026-08-21T10:00:00.000Z",
    },
    metrika: {
      ready: true,
      observed_at: "2026-08-21T10:00:00.000Z",
    },
    campaign_catalog: { total: 1, active: [] },
    performance: {
      period_start: "2026-08-01",
      period_end: "2026-08-20",
      display_metrics: { visits: "10", goal_visits: "2" },
      provenance: { observed_at: "2026-08-21T10:00:00.000Z" },
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
    goal: "Получать заявки на участие",
    geography: "Москва",
    period_start: "2026-09-01",
    period_end: "2026-10-01",
    landing_page: "https://owner.example/participate",
    weekly_budget_rub: 50_000,
    target_cpa_rub: 10_000,
    message: "Найдите новых покупателей на выставке",
  };
}

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
  assert.equal(result.workflow.current_step, 1);
  assert.match(result.state.business_model.analysis_evidence.snapshot_id, /^sha256:[a-f0-9]{64}$/);

  const persistedSnapshotId = result.state.business_model.analysis_evidence.snapshot_id;
  const changedContext = context();
  changedContext.direct.observed_at = "2026-08-22T10:00:00.000Z";
  changedContext.direct.campaigns_total = 99;
  const restarted = new P0Application({
    store,
    adapters: adapters({ readContext: async () => changedContext }),
  });
  result = await restarted.query("owner");
  assert.equal(result.revision, 1);
  assert.equal(result.workflow.current_step, 1);
  assert.equal(result.analysis_evidence.snapshot_id, persistedSnapshotId);

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
  assert.equal(result.revision, 4);
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
  assert.equal(afterBlockedWrite.revision, 4);
  assert.equal(afterBlockedWrite.state.campaign, null);
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
