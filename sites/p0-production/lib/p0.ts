import { env } from "cloudflare:workers";
import { buildAdTitle } from "./ad-copy";
import {
  buildAnalyticsEvidence,
  type AnalyticsEvidenceBundle,
} from "./analytics-evidence";
import {
  inferDecisionMakers,
  inferOffer,
  isUnprocessedAudience,
  isUnprocessedOffer,
} from "./business-model";
import {
  buildCampaignNames,
  buildPublishProjection,
  hasDuplicateCampaignName,
  isCampaignNameWithGeography,
  isLegacySearchName,
} from "./campaign-draft";
import {
  buildCampaignRecommendationSet,
  campaignDraftPublishBlockers,
  fingerprintDirectProjection,
  type CampaignRecommendationSet,
} from "./campaign-fanout";
import {
  explainScoreDelta,
  scoreCampaignDrafts,
} from "./campaign-viability";
import { minimumWeeklyBudgetRub, validateWeeklyBudgetRub } from "./direct-limits";
import {
  createSuspendedCampaign,
  DirectWriteError,
  type DirectProjection,
} from "./direct-write";
import { mustHoldAccountLock } from "./execution-safety";
import {
  summarizeP0Revision,
  type P0RevisionSummary,
} from "./revision-history";
import { normalizePublicHttpsUrl, requirePublicHttpsUrl } from "./site-url";

const MAX_SITE_BYTES = 5_000_000;
const MAX_SITE_PAGES = 6;
const RESEARCH_TERMS = [
  "about",
  "product",
  "service",
  "solution",
  "particip",
  "partner",
  "price",
  "tariff",
  "registration",
  "become",
  "visitor",
  "client",
  "faq",
  "contact",
  "услов",
  "участ",
  "партнер",
  "регистра",
  "посетител",
  "клиент",
  "контакт",
];

export type P0Document = {
  site_analysis: SiteAnalysis | null;
  business_model: BusinessModel | null;
  strategy: Record<string, unknown> | null;
  recommendation_set: CampaignRecommendationSet | null;
  draft: Record<string, unknown> | null;
  campaign: Record<string, unknown> | null;
};

type StateRow = {
  revision: number;
  updated_at: string;
  value_json: string;
};

type ExecutionRow = {
  execution_id: string;
  campaign_id: string;
  projection_json: string;
  result_json: string;
};

type PageEvidence = {
  url: string;
  title: string;
  description: string;
  headings: string[];
  forms_detected: number;
  text_excerpt: string;
};

type SiteAnalysis = PageEvidence & {
  fetched_at: string;
  pages: PageEvidence[];
  research: {
    pages_analyzed: number;
    links_discovered: number;
    scope: string;
  };
};

type BusinessModel = {
  product: string;
  audience: string;
  value: string;
  qualified_result: string;
  exclusions: string;
  source: string;
  assumptions: string[];
  missing_questions: string[];
  research: {
    agent: string;
    pages_analyzed: number;
    sources: string[];
    completed_fields: string[];
  };
  field_evidence: Record<
    string,
    {
      confidence: string;
      source_url: string;
      quote: string;
      owner_confirmed?: boolean;
      owner_confirmed_at?: string;
    }
  >;
  analysis_evidence?: AnalyticsEvidenceBundle;
};

type Context = {
  environment: "PRODUCTION";
  test_scenario: false;
  direct: Record<string, unknown>;
  metrika: Record<string, unknown>;
  performance: Record<string, unknown> | null;
  campaign_catalog: Record<string, unknown> | null;
};

async function migrateDocument(state: P0Document, revision: number, updatedAt: string) {
  let changed = false;
  let modelChanged = false;
  let previousProduct = "";
  const model = state.business_model;
  const site = state.site_analysis;
  const productEvidence = model?.field_evidence?.product;
  if (model && site && productEvidence) {
    const supportingEvidence = bestOfferEvidence(evidenceRows(site));
    const brand = brandFromSite(site);
    const inferred = inferOffer(
      brand,
      supportingEvidence?.text ?? site.text_excerpt,
      model.qualified_result,
    );
    if (inferred && isUnprocessedOffer(model.product, productEvidence.quote, brand)) {
      previousProduct = model.product;
      model.product = inferred;
      productEvidence.confidence = "MEDIUM";
      productEvidence.quote = supportingEvidence?.text ?? site.description;
      productEvidence.source_url = supportingEvidence?.url ?? site.url;
      delete productEvidence.owner_confirmed;
      delete productEvidence.owner_confirmed_at;
      model.research.agent = "GPT_SITES_EVIDENCE_RESEARCH_V3";
      const correction = "product: агент превратил название бренда в конкретное рекламируемое предложение; проверьте формулировку";
      if (!model.assumptions.includes(correction)) model.assumptions.push(correction);
      model.missing_questions = model.missing_questions.filter((item) => !item.includes("предложение"));
      if (!model.research.completed_fields.includes("product")) model.research.completed_fields.push("product");
      changed = true;
      modelChanged = true;
    }
  }

  const audienceEvidence = model?.field_evidence?.audience;
  if (model && audienceEvidence) {
    const inferred = inferDecisionMakers(audienceEvidence.quote);
    const needsCorrection = isUnprocessedAudience(model.audience, audienceEvidence.quote)
      || (model.research.agent === "GPT_SITES_EVIDENCE_RESEARCH_V2" && inferred !== model.audience);
    if (inferred && needsCorrection) {
      model.audience = inferred;
      audienceEvidence.confidence = "MEDIUM";
      delete audienceEvidence.owner_confirmed;
      delete audienceEvidence.owner_confirmed_at;
      if (model.research.agent !== "GPT_SITES_EVIDENCE_RESEARCH_V3") {
        model.research.agent = "GPT_SITES_EVIDENCE_RESEARCH_V2";
      }
      const correction = "audience: агент выделил роли из evidence; проверьте соответствие реальному решению о покупке";
      if (!model.assumptions.includes(correction)) model.assumptions.push(correction);
      changed = true;
      modelChanged = true;
    }
  }

  if (modelChanged && model) delete model.analysis_evidence;

  const draft = state.draft;
  const strategy = state.strategy;
  if (strategy && model) {
    if (!strategy.strategy_revision_id) {
      strategy.strategy_revision_id = `campaign-strategy-r${Math.max(1, revision)}`;
      strategy.approved_at = updatedAt;
      changed = true;
    }
    if (
      !state.recommendation_set
      || state.recommendation_set.strategy_revision_id !== strategy.strategy_revision_id
      || state.recommendation_set.schema_version !== "campaign-recommendation-set-v2"
    ) {
      state.recommendation_set = await buildCampaignRecommendationSet({
        model: model as unknown as Record<string, unknown>,
        strategy,
        analyticsEvidence: model.analysis_evidence as unknown as Record<string, unknown> | undefined,
        generatedAt: updatedAt,
      });
      changed = true;
    }
  }
  if (draft && strategy && model) {
    let draftChanged = false;
    const baseline = state.recommendation_set?.drafts.find((item) => item.visibility === "VISIBLE");
    if (!draft.draft_id && baseline) {
      draft.draft_id = baseline.draft_id;
      draft.draft_revision_id = `${baseline.draft_id}-r${Math.max(1, revision)}`;
      draft.strategy_revision_id = strategy.strategy_revision_id;
      draft.capability_profile_id = state.recommendation_set?.capability_profile.profile_id;
      changed = true;
      draftChanged = true;
    }
    const names = buildCampaignNames(model.product, strategy.geography, model.qualified_result);
    if (
      isLegacySearchName(draft.campaign_name)
      || isCampaignNameWithGeography(draft.campaign_name, strategy.geography)
      || (previousProduct && String(draft.campaign_name).startsWith(`${previousProduct} ·`))
    ) {
      draft.campaign_name = names.campaignName;
      changed = true;
      draftChanged = true;
    }
    if (isLegacySearchName(draft.group_name)) {
      draft.group_name = names.groupName;
      changed = true;
      draftChanged = true;
    }
    if (previousProduct && draft.ad_title === previousProduct) {
      draft.ad_title = buildAdTitle(model.product);
      changed = true;
      draftChanged = true;
    }
    if ((draft.publish_projection as Record<string, unknown> | undefined)?.schema_version !== "p0-direct-projection-v3" || previousProduct || draftChanged) {
      draft.publish_projection = buildPublishProjection(
        model as unknown as Record<string, unknown>,
        strategy,
        draft,
      );
      changed = true;
    }
    const projection = draft.publish_projection as Record<string, unknown> | undefined;
    const recommendationSet = state.recommendation_set;
    if (projection && recommendationSet) {
      const publishFingerprint = await fingerprintDirectProjection(projection);
      if (draft.publish_fingerprint !== publishFingerprint) {
        draft.publish_fingerprint = publishFingerprint;
        changed = true;
      }
      const generatedIndex = recommendationSet.drafts.findIndex((item) => item.draft_id === draft.draft_id);
      if (generatedIndex >= 0 && recommendationSet.drafts[generatedIndex].draft_revision_id !== draft.draft_revision_id) {
        recommendationSet.drafts[generatedIndex] = {
          ...recommendationSet.drafts[generatedIndex],
          ...draft,
        } as typeof recommendationSet.drafts[number];
        changed = true;
      }
    }
  }
  return changed;
}

function runtimeEnv() {
  return env as unknown as Record<string, string | undefined> & {
    DB: typeof env.DB;
  };
}

function emptyDocument(): P0Document {
  return {
    site_analysis: null,
    business_model: null,
    strategy: null,
    recommendation_set: null,
    draft: null,
    campaign: null,
  };
}

function now() {
  return new Date().toISOString();
}

function cleanText(value: string, maximum = 1_000) {
  return value
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, maximum);
}

function requiredInput(value: unknown, label: string, maximum: number) {
  const text = cleanText(String(value ?? ""), 10_000);
  if (!text) throw new Error(`${label} не заполнено.`);
  if (text.length > maximum) throw new Error(`${label}: максимум ${maximum} символов.`);
  return text;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Неизвестная ошибка";
}

export function userKey(request: Request) {
  const authenticated = request.headers.get("oai-authenticated-user-id")?.trim();
  if (authenticated) return authenticated;
  const hostname = new URL(request.url).hostname;
  if (hostname === "localhost" || hostname === "127.0.0.1") return "local-preview";
  throw new Error("Для production-модуля требуется вход через GPT Sites.");
}

async function ensureState(key: string) {
  const db = runtimeEnv().DB;
  if (!db) throw new Error("Sites D1 binding DB недоступен.");
  await db
    .prepare(
      "CREATE TABLE IF NOT EXISTS p0_state (user_key TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL, value_json TEXT NOT NULL)",
    )
    .run();
  await db
    .prepare(
      "CREATE TABLE IF NOT EXISTS p0_state_revisions (user_key TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL, value_json TEXT NOT NULL, PRIMARY KEY (user_key, revision))",
    )
    .run();
  await db
    .prepare(
      "CREATE TABLE IF NOT EXISTS p0_executions (execution_id TEXT PRIMARY KEY, user_key TEXT NOT NULL, account_key TEXT NOT NULL, status TEXT NOT NULL, campaign_id TEXT, projection_json TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
    )
    .run();
  await db
    .prepare(
      "CREATE TABLE IF NOT EXISTS p0_account_locks (account_key TEXT PRIMARY KEY, execution_id TEXT NOT NULL, owner_key TEXT NOT NULL, expires_at TEXT NOT NULL)",
    )
    .run();
  const existing = await db
    .prepare("SELECT revision, updated_at, value_json FROM p0_state WHERE user_key = ?")
    .bind(key)
    .first<StateRow>();
  let row = existing;
  if (!row) {
    const updatedAt = now();
    const valueJson = JSON.stringify(emptyDocument());
    await db
      .prepare(
        "INSERT INTO p0_state(user_key, revision, updated_at, value_json) VALUES (?, 0, ?, ?)",
      )
      .bind(key, updatedAt, valueJson)
      .run();
    row = { revision: 0, updated_at: updatedAt, value_json: valueJson };
  }
  await db
    .prepare(
      "INSERT OR IGNORE INTO p0_state_revisions(user_key, revision, updated_at, value_json) VALUES (?, ?, ?, ?)",
    )
    .bind(key, Number(row.revision), String(row.updated_at), String(row.value_json))
    .run();
  return row;
}

async function readRevisionHistory(key: string, currentRevision: number): Promise<P0RevisionSummary[]> {
  const result = await runtimeEnv()
    .DB.prepare(
      "SELECT revision, updated_at, value_json FROM p0_state_revisions WHERE user_key = ? ORDER BY revision DESC LIMIT 50",
    )
    .bind(key)
    .all<StateRow>();
  return result.results.map((row) => summarizeP0Revision(row, currentRevision));
}

async function loadState(key: string) {
  const row = await ensureState(key);
  const revision = Number(row.revision);
  const state = JSON.parse(String(row.value_json)) as P0Document;
  if (await migrateDocument(state, revision, String(row.updated_at))) return saveState(key, revision, state);
  return {
    revision,
    updated_at: String(row.updated_at),
    state,
    revision_history: await readRevisionHistory(key, revision),
  };
}

async function saveState(key: string, expectedRevision: number, state: P0Document) {
  const updatedAt = now();
  const nextRevision = expectedRevision + 1;
  const valueJson = JSON.stringify(state);
  const db = runtimeEnv().DB;
  const [result] = await db.batch([
    db.prepare(
      "UPDATE p0_state SET revision = revision + 1, updated_at = ?, value_json = ? WHERE user_key = ? AND revision = ?",
    ).bind(updatedAt, valueJson, key, expectedRevision),
    db.prepare(
      "INSERT OR IGNORE INTO p0_state_revisions(user_key, revision, updated_at, value_json) SELECT user_key, revision, updated_at, value_json FROM p0_state WHERE user_key = ? AND revision = ? AND value_json = ?",
    ).bind(key, nextRevision, valueJson),
  ]);
  if (Number(result.meta.changes) !== 1) {
    throw new Error("P0 изменился в другой вкладке. Обновите страницу.");
  }
  return {
    revision: nextRevision,
    updated_at: updatedAt,
    state,
    revision_history: await readRevisionHistory(key, nextRevision),
  };
}

function directWriteConfig() {
  const runtime = runtimeEnv();
  return {
    token: runtime.YANDEX_DIRECT_OAUTH_TOKEN ?? "",
    account: runtime.YANDEX_DIRECT_CLIENT_LOGIN ?? "",
  };
}

async function beginExecution(
  userKeyValue: string,
  account: string,
  projection: DirectProjection,
) {
  const executionId = crypto.randomUUID();
  const timestamp = now();
  await runtimeEnv()
    .DB.prepare(
      "INSERT INTO p0_executions(execution_id, user_key, account_key, status, projection_json, result_json, created_at, updated_at) VALUES (?, ?, ?, 'STARTED', ?, '{}', ?, ?)",
    )
    .bind(executionId, userKeyValue, account, JSON.stringify(projection), timestamp, timestamp)
    .run();
  return executionId;
}

async function findRecoverableExecution(
  userKeyValue: string,
  account: string,
  projection: DirectProjection,
) {
  const row = await runtimeEnv()
    .DB.prepare(
      "SELECT execution_id, campaign_id, projection_json, result_json FROM p0_executions WHERE user_key = ? AND account_key = ? AND campaign_id IS NOT NULL ORDER BY created_at DESC LIMIT 1",
    )
    .bind(userKeyValue, account)
    .first<ExecutionRow>();
  if (!row) return null;
  const storedProjection = JSON.parse(row.projection_json) as DirectProjection;
  const storedResult = JSON.parse(row.result_json) as Record<string, unknown>;
  const steps = Array.isArray(storedResult.steps) ? storedResult.steps : [];
  const [storedFingerprint, requestedFingerprint] = await Promise.all([
    fingerprintDirectProjection(storedProjection as unknown as Record<string, unknown>),
    fingerprintDirectProjection(projection as unknown as Record<string, unknown>),
  ]);
  if (storedFingerprint !== requestedFingerprint) return null;
  const campaignOnly = steps.length === 1 && steps[0] === "CAMPAIGN_CREATED";
  const graphCreated = steps.includes("OBJECT_GRAPH_CREATED")
    && storedResult.ad_group_id
    && storedResult.keyword_id;
  if (!campaignOnly && !graphCreated) return null;
  return {
    executionId: row.execution_id,
    recovery: {
      campaignId: String(row.campaign_id),
      ...(graphCreated
        ? {
            adGroupId: String(storedResult.ad_group_id),
            keywordId: String(storedResult.keyword_id),
          }
        : {}),
    },
  };
}

async function claimRecoveryLock(account: string, userKeyValue: string, executionId: string) {
  const lock = await runtimeEnv()
    .DB.prepare("SELECT execution_id FROM p0_account_locks WHERE account_key = ?")
    .bind(account)
    .first<{ execution_id: string }>();
  if (lock?.execution_id === executionId) return;
  if (lock) throw new Error("Для аккаунта уже выполняется другая production-запись.");
  await acquireAccountLock(account, userKeyValue, executionId);
}

async function recordExecution(
  executionId: string,
  status: string,
  result: Record<string, unknown>,
) {
  await runtimeEnv()
    .DB.prepare(
      "UPDATE p0_executions SET status = ?, campaign_id = COALESCE(?, campaign_id), result_json = ?, updated_at = ? WHERE execution_id = ?",
    )
    .bind(
      status,
      result.campaign_id ? String(result.campaign_id) : null,
      JSON.stringify(result),
      now(),
      executionId,
    )
    .run();
}

async function acquireAccountLock(account: string, userKeyValue: string, executionId: string) {
  const db = runtimeEnv().DB;
  const timestamp = now();
  await db.prepare("DELETE FROM p0_account_locks WHERE expires_at <= ?").bind(timestamp).run();
  const expiresAt = new Date(Date.now() + 15 * 60_000).toISOString();
  const result = await db
    .prepare(
      "INSERT OR IGNORE INTO p0_account_locks(account_key, execution_id, owner_key, expires_at) VALUES (?, ?, ?, ?)",
    )
    .bind(account, executionId, userKeyValue, expiresAt)
    .run();
  if (Number(result.meta.changes) !== 1) {
    throw new Error("Для аккаунта уже выполняется другая production-запись.");
  }
}

async function releaseAccountLock(account: string, executionId: string) {
  await runtimeEnv()
    .DB.prepare("DELETE FROM p0_account_locks WHERE account_key = ? AND execution_id = ?")
    .bind(account, executionId)
    .run();
}

async function holdAccountLock(account: string, executionId: string) {
  await runtimeEnv()
    .DB.prepare(
      "UPDATE p0_account_locks SET expires_at = '9999-12-31T23:59:59.999Z' WHERE account_key = ? AND execution_id = ?",
    )
    .bind(account, executionId)
    .run();
}

async function readCurrencyLimits() {
  const runtime = runtimeEnv();
  const token = runtime.YANDEX_DIRECT_OAUTH_TOKEN;
  const account = runtime.YANDEX_DIRECT_CLIENT_LOGIN;
  if (!token || !account) throw new Error("Direct read credentials не настроены в Sites.");
  const response = await fetch("https://api.direct.yandex.com/json/v501/dictionaries", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Client-Login": account,
      Accept: "application/json",
      "Accept-Language": "ru",
      "Content-Type": "application/json; charset=utf-8",
    },
    body: JSON.stringify({ method: "get", params: { DictionaryNames: ["Currencies"] } }),
  });
  if (!response.ok) throw new Error(`Яндекс Директ вернул HTTP ${response.status} для Currencies.`);
  const payload = (await response.json()) as {
    error?: unknown;
    result?: { Currencies?: Array<{ Currency?: unknown; Properties?: Array<{ Name?: unknown; Value?: unknown }> }> };
  };
  if (payload.error || !Array.isArray(payload.result?.Currencies)) {
    throw new Error("Ответ Direct Currencies не соответствует контракту.");
  }
  return { minimum_weekly_budget_rub: minimumWeeklyBudgetRub(payload.result.Currencies) };
}

async function readCampaignCatalog() {
  const runtime = runtimeEnv();
  const token = runtime.YANDEX_DIRECT_OAUTH_TOKEN;
  const account = runtime.YANDEX_DIRECT_CLIENT_LOGIN;
  if (!token || !account) throw new Error("Direct read credentials не настроены в Sites.");
  const response = await fetch("https://api.direct.yandex.com/json/v501/campaigns", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Client-Login": account,
      Accept: "application/json",
      "Accept-Language": "ru",
      "Content-Type": "application/json; charset=utf-8",
    },
    body: JSON.stringify({
      method: "get",
      params: {
        SelectionCriteria: {},
        FieldNames: ["Id", "Name", "Type", "Status", "State", "StartDate", "EndDate"],
        Page: { Limit: 1000, Offset: 0 },
      },
    }),
  });
  if (!response.ok) throw new Error(`Яндекс Директ вернул HTTP ${response.status}.`);
  const payload = (await response.json()) as {
    error?: unknown;
    result?: { Campaigns?: Array<Record<string, unknown>>; LimitedBy?: number };
  };
  if (payload.error || !Array.isArray(payload.result?.Campaigns)) {
    throw new Error("Ответ Яндекс Директа не соответствует read-only контракту.");
  }
  const campaigns = payload.result.Campaigns;
  return {
    account,
    observed_at: now(),
    total: campaigns.length,
    names: campaigns
      .filter((item) => item.State !== "ARCHIVED")
      .map((item) => cleanText(String(item.Name ?? ""), 255)),
    active: campaigns
      .filter((item) => item.State !== "ARCHIVED")
      .slice(0, 20)
      .map((item) => ({
        campaign_id: String(item.Id ?? ""),
        name: cleanText(String(item.Name ?? ""), 255),
        state: String(item.State ?? "UNKNOWN"),
        status: String(item.Status ?? "UNKNOWN"),
      })),
  };
}

function isoDateDaysAgo(days: number) {
  const value = new Date();
  value.setUTCDate(value.getUTCDate() - days);
  return value.toISOString().slice(0, 10);
}

async function readMetrika() {
  const runtime = runtimeEnv();
  const token = runtime.YANDEX_METRICA_OAUTH_TOKEN;
  const counter = runtime.YANDEX_METRICA_COUNTER_ID;
  const goal = runtime.YANDEX_METRICA_GOAL_ID;
  const campaign = runtime.YANDEX_DIRECT_CAMPAIGN_ID;
  if (!token || !counter || !goal || !campaign) {
    throw new Error("Metrika production bindings не настроены в Sites.");
  }
  const dimension = "ym:s:lastDirectClickOrder";
  const start = isoDateDaysAgo(8);
  const end = isoDateDaysAgo(1);
  const query = new URLSearchParams({
    ids: counter,
    date1: start,
    date2: end,
    dimensions: `ym:s:date,${dimension}`,
    metrics: `ym:s:visits,ym:s:goal${goal}visits`,
    filters: `${dimension}=='${campaign}'`,
    accuracy: "full",
    limit: "100000",
  });
  const response = await fetch(`https://api-metrika.yandex.net/stat/v1/data?${query}`, {
    headers: { Authorization: `OAuth ${token}`, Accept: "application/json" },
  });
  if (!response.ok) throw new Error(`Яндекс Метрика вернула HTTP ${response.status}.`);
  const payload = (await response.json()) as {
    data?: Array<{ metrics?: number[] }>;
    sampled?: boolean;
    contains_sensitive_data?: boolean;
    sample_share?: number;
    sample_size?: number;
    sample_space?: number;
    data_lag?: number;
  };
  if (!Array.isArray(payload.data)) throw new Error("Ответ Метрики некорректен.");
  const visits = payload.data.reduce((sum, row) => sum + Number(row.metrics?.[0] ?? 0), 0);
  const goals = payload.data.reduce((sum, row) => sum + Number(row.metrics?.[1] ?? 0), 0);
  return {
    counter,
    goal,
    period_start: start,
    period_end: end,
    visits,
    goals,
    observed_at: now(),
    sampling: {
      sampled: payload.sampled === true,
      contains_sensitive_data: payload.contains_sensitive_data === true,
      sample_share: Number(payload.sample_share ?? 1),
      sample_size: Number(payload.sample_size ?? payload.data.length),
      sample_space: Number(payload.sample_space ?? payload.data.length),
      data_lag: Number(payload.data_lag ?? 0),
    },
  };
}

async function readContext(): Promise<Context> {
  const [directResult, limitsResult, metrikaResult] = await Promise.allSettled([
    readCampaignCatalog(),
    readCurrencyLimits(),
    readMetrika(),
  ]);
  const direct =
    directResult.status === "fulfilled" && limitsResult.status === "fulfilled"
      ? {
          ready: true,
          inventory_ready: true,
          access: "REAL_API_READ",
          account: directResult.value.account,
          campaigns_total: directResult.value.total,
          observed_at: directResult.value.observed_at,
          minimum_weekly_budget_rub: limitsResult.value.minimum_weekly_budget_rub,
        }
      : {
          ready: false,
          inventory_ready: directResult.status === "fulfilled",
          access: "REAL_API_READ",
          ...(directResult.status === "fulfilled"
            ? {
                account: directResult.value.account,
                campaigns_total: directResult.value.total,
                observed_at: directResult.value.observed_at,
              }
            : {}),
          blockers: [
            ...(directResult.status === "rejected" ? [errorMessage(directResult.reason)] : []),
            ...(limitsResult.status === "rejected" ? [errorMessage(limitsResult.reason)] : []),
          ],
        };
  const metrika =
    metrikaResult.status === "fulfilled"
      ? {
          ready: true,
          access: "REAL_API_READ",
          counter_connected: true,
          goal_connected: true,
          counter_id: metrikaResult.value.counter,
          goal_id: metrikaResult.value.goal,
          observed_at: metrikaResult.value.observed_at,
        }
      : { ready: false, access: "REAL_API_READ", blockers: [errorMessage(metrikaResult.reason)] };
  return {
    environment: "PRODUCTION",
    test_scenario: false,
    direct,
    metrika,
    campaign_catalog:
      directResult.status === "fulfilled"
        ? { total: directResult.value.total, active: directResult.value.active }
        : null,
    performance:
      metrikaResult.status === "fulfilled"
        ? {
            period_start: metrikaResult.value.period_start,
            period_end: metrikaResult.value.period_end,
            display_metrics: {
              visits: String(metrikaResult.value.visits),
              goal_visits: String(metrikaResult.value.goals),
            },
            provenance: {
              source_kind: "METRIKA_REPORTS_API",
              observed_at: metrikaResult.value.observed_at,
              sampling: metrikaResult.value.sampling,
            },
          }
        : null,
  };
}

function normalizeHost(hostname: string) {
  return hostname.toLowerCase().replace(/^www\./, "");
}

function firstParty(base: string, candidate: string) {
  return candidate === base || candidate.endsWith(`.${base}`);
}

function extractMatches(source: string, pattern: RegExp, maximum: number) {
  const values: string[] = [];
  for (const match of source.matchAll(pattern)) {
    const value = cleanText(match[1] ?? "", 1_000);
    if (value && !values.includes(value)) values.push(value);
    if (values.length >= maximum) break;
  }
  return values;
}

async function fetchPage(rawUrl: string): Promise<{ page: PageEvidence; links: string[] }> {
  const requested = normalizePublicHttpsUrl(rawUrl);
  const response = await fetch(requested, {
    headers: {
      "User-Agent": "MOX-ADV-GPT-Sites/1.0",
      Accept: "text/html,application/xhtml+xml",
    },
    redirect: "follow",
  });
  if (!response.ok) throw new Error(`Сайт вернул HTTP ${response.status}.`);
  const finalUrl = requirePublicHttpsUrl(response.url);
  const contentType = response.headers.get("content-type") ?? "";
  if (!/text\/html|application\/xhtml\+xml/i.test(contentType)) {
    throw new Error("Страница не вернула HTML.");
  }
  const html = await response.text();
  if (new TextEncoder().encode(html).byteLength > MAX_SITE_BYTES) {
    throw new Error("HTML страницы превышает безопасный размер.");
  }
  const title = extractMatches(html, /<title[^>]*>([\s\S]*?)<\/title>/gi, 1)[0] ?? "";
  const descriptions = extractMatches(
    html,
    /<meta[^>]+(?:name|property)=["'](?:description|og:description)["'][^>]+content=["']([^"']*)["'][^>]*>/gi,
    2,
  );
  const headings = extractMatches(html, /<h[12][^>]*>([\s\S]*?)<\/h[12]>/gi, 20);
  const links = extractMatches(html, /<a[^>]+href=["']([^"']+)["'][^>]*>/gi, 500);
  const body = cleanText(
    html
      .replace(/<script[\s\S]*?<\/script>/gi, " ")
      .replace(/<style[\s\S]*?<\/style>/gi, " ")
      .replace(/<noscript[\s\S]*?<\/noscript>/gi, " "),
    8_000,
  );
  return {
    page: {
      url: finalUrl.toString(),
      title,
      description: descriptions[0] ?? "",
      headings: headings.slice(0, 10),
      forms_detected: (html.match(/<form\b/gi) ?? []).length,
      text_excerpt: body,
    },
    links,
  };
}

function rankedLinks(baseUrl: string, links: string[]) {
  const base = new URL(baseUrl);
  const baseHost = normalizeHost(base.hostname);
  const scores = new Map<string, number>();
  for (const href of links) {
    if (/^(mailto:|tel:|javascript:)/i.test(href) || /privacy|cookie|login|logout|\.pdf|\.zip/i.test(href)) {
      continue;
    }
    let candidate: URL;
    try {
      candidate = new URL(href, base);
    } catch {
      continue;
    }
    const candidateHost = normalizeHost(candidate.hostname);
    if (candidate.protocol !== "https:" || !firstParty(baseHost, candidateHost)) continue;
    candidate.search = "";
    candidate.hash = "";
    if (candidate.toString().replace(/\/$/, "") === base.toString().replace(/\/$/, "")) continue;
    const haystack = `${candidate.pathname} ${candidate.search}`.toLowerCase();
    let score = RESEARCH_TERMS.reduce((total, term) => total + (haystack.includes(term) ? 3 : 0), 0);
    if (candidateHost !== baseHost) score += 6;
    if (/terms.*particip|услов.*участ/.test(haystack)) score += 10;
    if (/become|стать-участ/.test(haystack)) score += 8;
    if (/participants|partner-country|list/.test(haystack)) score -= 4;
    if (score > 0) scores.set(candidate.toString(), Math.max(score, scores.get(candidate.toString()) ?? -100));
  }
  return [...scores.entries()].sort((a, b) => b[1] - a[1]).map(([url]) => url);
}

async function researchSite(rawUrl: string): Promise<SiteAnalysis> {
  const entry = await fetchPage(rawUrl);
  const entryHost = normalizeHost(new URL(entry.page.url).hostname);
  const pages = [entry.page];
  const attempted = new Set<string>();
  let candidates = rankedLinks(entry.page.url, entry.links);
  while (candidates.length && pages.length < MAX_SITE_PAGES) {
    const candidate = candidates.shift()!;
    if (attempted.has(candidate)) continue;
    attempted.add(candidate);
    try {
      const result = await fetchPage(candidate);
      const pageHost = normalizeHost(new URL(result.page.url).hostname);
      if (!firstParty(entryHost, pageHost) || pages.some((item) => item.url === result.page.url)) continue;
      pages.push(result.page);
      candidates = [
        ...rankedLinks(result.page.url, result.links).filter((item) => !attempted.has(item)),
        ...candidates,
      ];
    } catch {
      // Secondary pages are best-effort; the entry page remains authoritative.
    }
  }
  return {
    ...entry.page,
    fetched_at: now(),
    forms_detected: pages.reduce((sum, page) => sum + page.forms_detected, 0),
    text_excerpt: cleanText(pages.map((page) => page.text_excerpt).join(" "), 8_000),
    pages,
    research: {
      pages_analyzed: pages.length,
      links_discovered: entry.links.length,
      scope: "FIRST_PARTY_PUBLIC_HTTPS",
    },
  };
}

function evidenceRows(site: SiteAnalysis) {
  const rows: Array<{ text: string; url: string }> = [];
  const seen = new Set<string>();
  for (const page of site.pages) {
    const values = [page.description, ...page.headings, ...page.text_excerpt.split(/(?<=[.!?])\s+|\s*[|•]\s*/g)];
    for (const value of values) {
      const text = cleanText(value, 1_000);
      const key = text.toLowerCase();
      if (text.length < 12 || seen.has(key)) continue;
      seen.add(key);
      rows.push({ text, url: page.url });
    }
  }
  return rows;
}

function bestEvidence(rows: Array<{ text: string; url: string }>, terms: string[]) {
  return rows
    .map((row) => ({ row, score: terms.reduce((sum, term) => sum + (row.text.toLowerCase().includes(term) ? 1 : 0), 0) }))
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score || a.row.text.length - b.row.text.length)[0]?.row;
}

function brandFromSite(site: SiteAnalysis) {
  return cleanText(site.title.split(/\s[|—–-]\s/)[0] || "", 200);
}

function bestOfferEvidence(rows: Array<{ text: string; url: string }>) {
  return bestEvidence(rows, [
    "участ",
    "выстав",
    "стенд",
    "экспонент",
    "participant",
    "exhibitor",
    "exhibition",
    "booth",
  ]);
}

async function inferModel(site: SiteAnalysis, context: Context): Promise<BusinessModel> {
  const rows = evidenceRows(site);
  const productEvidence = bestOfferEvidence(rows);
  const brand = brandFromSite(site);
  const audienceEvidence = bestEvidence(rows, [
    "руководител",
    "заказчик",
    "инвестор",
    "покупател",
    "байер",
    "производител",
    "decision-maker",
    "buyer",
    "manufacturer",
  ]);
  const valueEvidence = bestEvidence(rows, [
    "найдите",
    "получите",
    "возможност",
    "привлеч",
    "инвестиц",
    "партнер",
    "find new",
    "opportunit",
    "connect",
  ]);
  const resultEvidence = bestEvidence(rows, [
    "заполните короткую форму",
    "менеджер свяж",
    "оставьте заявку",
    "стать участник",
    "become a participant",
    "submit an application",
    "register",
  ]);
  const visitorEvidence = bestEvidence(rows, ["посетител", "visitor", "билет", "free ticket"]);
  const audience = inferDecisionMakers(audienceEvidence?.text ?? "");
  const value = cleanText(valueEvidence?.text ?? site.description, 1_000);
  const qualified = resultEvidence
    ? /участ|participant/i.test(resultEvidence.text)
      ? "Отправленная заявка на участие через форму сайта"
      : /регистра|register/i.test(resultEvidence.text)
        ? "Завершённая регистрация на сайте"
        : "Отправленная квалифицированная заявка через сайт"
    : site.forms_detected
      ? "Отправленная форма с контактными данными"
      : "";
  const exclusions = visitorEvidence
    ? "Посетители без намерения оставить коммерческую заявку"
    : qualified
      ? "Информационные обращения без намерения выполнить целевое действие"
      : "";
  const product = inferOffer(
    brand,
    productEvidence?.text ?? site.text_excerpt,
    qualified,
  );
  const facts: Record<string, { value: string; evidence?: { text: string; url: string }; confidence: string }> = {
    product: { value: product, evidence: productEvidence, confidence: product ? "MEDIUM" : "LOW" },
    audience: { value: audience, evidence: audienceEvidence, confidence: audience ? "MEDIUM" : "LOW" },
    value: { value, evidence: valueEvidence, confidence: value ? "MEDIUM" : "LOW" },
    qualified_result: { value: qualified, evidence: resultEvidence, confidence: qualified ? "HIGH" : "LOW" },
    exclusions: { value: exclusions, evidence: visitorEvidence, confidence: exclusions ? "MEDIUM" : "LOW" },
  };
  const questions: Record<string, string> = {
    product: "Какое предложение нужно рекламировать?",
    audience: "Кто фактически принимает решение о покупке?",
    value: "Какая подтверждённая ценность важнее всего?",
    qualified_result: "Какой результат считается квалифицированным?",
    exclusions: "Какие обращения нужно исключить?",
  };
  const sources = ["PUBLIC_FIRST_PARTY_SITE"];
  if (context.direct.ready === true) sources.push("DIRECT_REAL_ACCOUNT");
  if (context.metrika.ready === true) sources.push("METRIKA_REAL_COUNTER");
  const model: BusinessModel = {
    product: facts.product.value,
    audience: facts.audience.value,
    value: facts.value.value,
    qualified_result: facts.qualified_result.value,
    exclusions: facts.exclusions.value,
    source: "REAL_SITE_AND_CONNECTED_DATA_RESEARCH",
    assumptions: Object.entries(facts)
      .filter(([, fact]) => fact.value && fact.confidence === "MEDIUM")
      .map(([name]) => `${name}: вывод агента требует подтверждения владельца`),
    missing_questions: Object.entries(facts)
      .filter(([, fact]) => !fact.value)
      .map(([name]) => questions[name]),
    research: {
      agent: "GPT_SITES_EVIDENCE_RESEARCH_V3",
      pages_analyzed: site.pages.length,
      sources,
      completed_fields: Object.entries(facts).filter(([, fact]) => fact.value).map(([name]) => name),
    },
    field_evidence: Object.fromEntries(
      Object.entries(facts).map(([name, fact]) => [
        name,
        {
          confidence: fact.confidence,
          source_url: fact.evidence?.url ?? "",
          quote: fact.evidence?.text ?? "",
        },
      ]),
    ),
  };
  model.analysis_evidence = await buildAnalyticsEvidence({
    site: site as unknown as Record<string, unknown>,
    model: model as unknown as Record<string, unknown>,
    context: context as unknown as Record<string, unknown>,
  });
  return model;
}

function writeReadiness(state: P0Document, context: Context) {
  const config = directWriteConfig();
  const blockers: string[] = [];
  if (!config.token || !config.account) blockers.push("Direct production credentials не настроены");
  if (context.direct.ready !== true) blockers.push("Текущий аккаунт Директа не прошёл production preflight");
  const minimumBudget = Number(context.direct.minimum_weekly_budget_rub);
  if (Number.isFinite(minimumBudget) && state.strategy) {
    try {
      validateWeeklyBudgetRub(state.strategy.weekly_budget_rub, minimumBudget);
    } catch (error) {
      blockers.push(errorMessage(error));
    }
  }
  if (!state.draft?.publish_projection) blockers.push("Campaign Draft ещё не зафиксирован");
  blockers.push(...campaignDraftPublishBlockers(state.draft));
  if (state.campaign) blockers.push("Кампания по этой ревизии уже создана");
  return { ready: blockers.length === 0, blockers };
}

export async function overview(key: string) {
  const [stored, context] = await Promise.all([loadState(key), readContext()]);
  const analysisEvidence = stored.state.site_analysis && stored.state.business_model
    ? await buildAnalyticsEvidence({
        site: stored.state.site_analysis as unknown as Record<string, unknown>,
        model: stored.state.business_model as unknown as Record<string, unknown>,
        context: context as unknown as Record<string, unknown>,
      })
    : null;
  const viewState = structuredClone(stored.state);
  if (analysisEvidence && viewState.business_model && viewState.strategy && viewState.recommendation_set) {
    const scored = await scoreCampaignDrafts({
      drafts: viewState.recommendation_set.drafts,
      model: viewState.business_model as unknown as Record<string, unknown>,
      strategy: viewState.strategy,
      analyticsEvidence: analysisEvidence as unknown as Record<string, unknown>,
      scoredAt: analysisEvidence.as_of,
    });
    viewState.recommendation_set.drafts = scored;
    viewState.recommendation_set.analytics_evidence_snapshot_id = analysisEvidence.snapshot_id;
    viewState.recommendation_set.coverage = {
      ...viewState.recommendation_set.coverage,
      visible_drafts: scored.filter((draft) => draft.visibility === "VISIBLE").length,
      hidden_drafts: scored.filter((draft) => draft.visibility === "HIDDEN").length,
    };
    if (viewState.draft) {
      const selected = scored.find((draft) => draft.draft_id === viewState.draft?.draft_id);
      if (selected) viewState.draft = { ...viewState.draft, ...selected };
    }
  }
  return {
    module: "P0_PRODUCTION",
    environment: "PRODUCTION",
    test_scenario: false,
    ...stored,
    state: viewState,
    context,
    analysis_evidence: analysisEvidence,
    write_readiness: writeReadiness(viewState, context),
  };
}

export async function applyAction(key: string, payload: Record<string, unknown>) {
  const expectedRevision = Number(payload.expected_revision);
  if (!Number.isInteger(expectedRevision) || expectedRevision < 0) {
    throw new Error("Для изменения нужна текущая ревизия.");
  }
  const current = await loadState(key);
  if (current.revision !== expectedRevision) throw new Error("P0 изменился в другой вкладке.");
  const state = structuredClone(current.state);
  const action = String(payload.action ?? "");
  if (action === "analyze_site") {
    const site = await researchSite(String(payload.url ?? ""));
    const context = await readContext();
    state.site_analysis = site;
    state.business_model = await inferModel(site, context);
    state.strategy = null;
    state.recommendation_set = null;
    state.draft = null;
  } else if (action === "save_business_model") {
    if (!state.business_model) throw new Error("Сначала исследуйте сайт.");
    const value = payload.value as Record<string, unknown>;
    const ownerConfirmedAt = now();
    for (const field of ["product", "audience", "value", "qualified_result", "exclusions"]) {
      const text = cleanText(String(value?.[field] ?? ""), 1_000);
      if (!text) throw new Error(`Поле ${field} требует подтверждённого значения.`);
      (state.business_model as unknown as Record<string, unknown>)[field] = text;
      state.business_model.field_evidence[field] = {
        ...state.business_model.field_evidence[field],
        confidence: "OWNER_CONFIRMED",
        owner_confirmed: true,
        owner_confirmed_at: ownerConfirmedAt,
      };
    }
    state.business_model.source = "REAL_SITE_RESEARCH_PLUS_OWNER_CONFIRMATION";
    state.business_model.assumptions = [];
    state.business_model.missing_questions = [];
    if (!state.site_analysis) throw new Error("Evidence snapshot потерял first-party site analysis.");
    const context = await readContext();
    state.business_model.analysis_evidence = await buildAnalyticsEvidence({
      site: state.site_analysis as unknown as Record<string, unknown>,
      model: state.business_model as unknown as Record<string, unknown>,
      context: context as unknown as Record<string, unknown>,
    });
    state.strategy = null;
    state.recommendation_set = null;
    state.draft = null;
  } else if (action === "save_strategy") {
    if (!state.business_model) throw new Error("Сначала подтвердите модель бизнеса.");
    const value = payload.value as Record<string, unknown>;
    const required = ["goal", "geography", "period_start", "period_end", "landing_page", "weekly_budget_rub", "target_cpa_rub", "message"];
    if (required.some((field) => String(value?.[field] ?? "").trim() === "")) {
      throw new Error("Критические решения Campaign Strategy заполнены не полностью.");
    }
    const landing = normalizePublicHttpsUrl(String(value.landing_page));
    const limits = await readCurrencyLimits();
    validateWeeklyBudgetRub(value.weekly_budget_rub, limits.minimum_weekly_budget_rub);
    const approvedAt = now();
    state.strategy = {
      ...value,
      landing_page: landing.toString(),
      source: "OWNER_APPROVED_REAL_BUSINESS_INPUT",
      strategy_revision_id: `campaign-strategy-r${expectedRevision + 1}`,
      approved_at: approvedAt,
    };
    state.recommendation_set = await buildCampaignRecommendationSet({
      model: state.business_model as unknown as Record<string, unknown>,
      strategy: state.strategy,
      analyticsEvidence: state.business_model?.analysis_evidence as unknown as Record<string, unknown> | undefined,
      generatedAt: approvedAt,
    });
    state.draft = null;
  } else if (action === "save_draft") {
    const value = payload.value as Record<string, unknown>;
    if (!state.strategy || !state.business_model) throw new Error("Сначала подтвердите модель и Strategy.");
    const draftId = requiredInput(value?.draft_id, "Campaign Draft", 255);
    const recommendationSet = state.recommendation_set;
    const generated = recommendationSet?.drafts.find((item) => item.draft_id === draftId);
    if (!recommendationSet || !generated || generated.visibility !== "VISIBLE") {
      throw new Error("Выбранный Campaign Draft не принадлежит текущей Strategy revision.");
    }
    const normalized: Record<string, unknown> = {
      campaign_name: requiredInput(value?.campaign_name, "Название кампании", 255),
      group_name: requiredInput(value?.group_name, "Название группы", 255),
      keyword: requiredInput(value?.keyword, "Ключевая фраза", 4_096),
      negative_keywords: requiredInput(value?.negative_keywords, "Минус-фразы", 1_000),
      ad_title: requiredInput(value?.ad_title, "Заголовок объявления", 56),
      ad_text: requiredInput(value?.ad_text, "Текст объявления", 81),
      draft_id: draftId,
      draft_revision_id: `${draftId}-r${expectedRevision + 1}`,
      strategy_revision_id: state.strategy.strategy_revision_id,
      capability_profile_id: recommendationSet.capability_profile.profile_id,
    };
    const projection = buildPublishProjection(
      state.business_model as unknown as Record<string, unknown>,
      state.strategy,
      normalized,
    ) as unknown as Record<string, unknown>;
    const editableFields = [
      "campaign_name",
      "group_name",
      "keyword",
      "negative_keywords",
      "ad_title",
      "ad_text",
    ] as const;
    const changedPointers = editableFields
      .filter((field) => String(generated[field] ?? "") !== String(normalized[field] ?? ""))
      .map((field) => `/draft/${field}`);
    let scoreEvidence = state.business_model.analysis_evidence;
    if (!scoreEvidence) {
      if (!state.site_analysis) throw new Error("Scoring требует first-party Analytics Evidence Snapshot.");
      const scoringContext = await readContext();
      scoreEvidence = await buildAnalyticsEvidence({
        site: state.site_analysis as unknown as Record<string, unknown>,
        model: state.business_model as unknown as Record<string, unknown>,
        context: scoringContext as unknown as Record<string, unknown>,
      });
      state.business_model.analysis_evidence = scoreEvidence;
    }
    const editedAt = now();
    const editedDraft = {
      ...generated,
      ...normalized,
      source: "OWNER_REVIEWED_PUBLISH_PROJECTION",
      edited_at: editedAt,
      publish_projection: projection,
      publish_fingerprint: await fingerprintDirectProjection(projection),
    } as typeof generated;
    const rescored = await scoreCampaignDrafts({
      drafts: recommendationSet.drafts.map((item) => item.draft_id === draftId ? editedDraft : item),
      model: state.business_model as unknown as Record<string, unknown>,
      strategy: state.strategy,
      analyticsEvidence: scoreEvidence as unknown as Record<string, unknown>,
      scoredAt: editedAt,
    });
    const currentDraft = rescored.find((item) => item.draft_id === draftId);
    if (!currentDraft) throw new Error("Пересчёт Campaign Draft не вернул выбранную ревизию.");
    state.draft = {
      ...currentDraft,
      score_delta: explainScoreDelta(
        generated.viability_score,
        currentDraft.viability_score,
        changedPointers,
      ),
    };
    recommendationSet.drafts = rescored.map((item) =>
      item.draft_id === draftId ? state.draft as typeof item : item
    );
  } else if (action === "confirm_creation") {
    if (payload.confirmation !== "CREATE_NON_SERVING_CAMPAIGN") {
      throw new Error("Нужно точное подтверждение создания реальной кампании с выключенными показами.");
    }
    if (state.campaign) throw new Error("Кампания по этой ревизии уже создана.");
    const projection = state.draft?.publish_projection as DirectProjection | undefined;
    if (!projection) throw new Error("Campaign Draft не готов к созданию.");
    const publishBlockers = campaignDraftPublishBlockers(state.draft);
    if (publishBlockers.length) throw new Error(publishBlockers[0]);
    const config = directWriteConfig();
    if (!config.token || !config.account) throw new Error("Direct production credentials не настроены.");
    const [catalog, limits] = await Promise.all([readCampaignCatalog(), readCurrencyLimits()]);
    if (!state.strategy) throw new Error("Campaign Strategy отсутствует.");
    validateWeeklyBudgetRub(state.strategy.weekly_budget_rub, limits.minimum_weekly_budget_rub);
    const campaignName = String(projection.direct.campaign.Name ?? "");
    const recovery = await findRecoverableExecution(key, config.account, projection);
    let executionId: string;
    let directRecovery: { campaignId: string; adGroupId?: string; keywordId?: string } | null = null;
    if (recovery) {
      executionId = recovery.executionId;
      directRecovery = recovery.recovery;
      await claimRecoveryLock(config.account, key, executionId);
    } else {
      if (hasDuplicateCampaignName(catalog.names, campaignName)) {
        throw new Error("В аккаунте уже существует активная кампания с таким названием.");
      }
      executionId = await beginExecution(key, config.account, projection);
      try {
        await acquireAccountLock(config.account, key, executionId);
      } catch (error) {
        await recordExecution(executionId, "ACCOUNT_WRITE_LOCKED", {});
        throw error;
      }
    }
    let releaseLock = true;
    try {
      const result = await createSuspendedCampaign(
        config,
        projection,
        fetch,
        (status, progress) => recordExecution(executionId, status, progress),
        directRecovery,
      );
      state.campaign = {
        source: "YANDEX_DIRECT_API",
        created_at: now(),
        execution_id: executionId,
        ...result,
      };
    } catch (error) {
      const partial = error instanceof DirectWriteError ? error.partial : {};
      await recordExecution(
        executionId,
        error instanceof DirectWriteError ? error.code : "P0_DIRECT_WRITE_FAILED",
        partial,
      );
      if (mustHoldAccountLock(partial)) {
        releaseLock = false;
        await holdAccountLock(config.account, executionId);
      }
      throw error;
    } finally {
      if (releaseLock) await releaseAccountLock(config.account, executionId);
    }
  } else if (action === "reset") {
    Object.assign(state, emptyDocument());
  } else {
    throw new Error("Действие не поддерживается production-модулем.");
  }
  return saveState(key, expectedRevision, state);
}
