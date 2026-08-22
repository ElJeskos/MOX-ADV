import { env } from "cloudflare:workers";
import {
  hasDuplicateCampaignName,
} from "./campaign-draft.ts";
import {
  campaignDraftPublishBlockers,
  fingerprintDirectProjection,
} from "./campaign-fanout.ts";
import { directExecutionFailureOutcome } from "./campaign-package-execution.ts";
import { strategyAnswerValue } from "./campaign-strategy.ts";
import { minimumWeeklyBudgetRub, validateWeeklyBudgetRub } from "./direct-limits.ts";
import {
  correctSuspendedCampaignAndResubmitModeration,
  DirectWriteError,
  pollSuspendedCampaignModeration,
  type DirectProjection,
} from "./direct-write.ts";
import {
  executeSafeSingleCampaign,
  type DirectExecutionIdentity,
  type DirectExecutionJournal,
  type DirectExecutionRecord,
} from "./execution-safety.ts";
import {
  P0Application,
  type P0ApplicationStore,
  type P0Command,
  type P0Context,
  type P0Document,
  type P0StoredRow,
} from "./p0-application.ts";
import { researchPublicFirstPartySite } from "./site-research.ts";
import { cleanText } from "./text.ts";
import {
  collectCurrentAuctionCostObservation,
  collectOfficialWordstatBatch,
  unavailableWordstatBatch,
  type CostObservation,
  type MarketEvidenceInput,
  type WordstatSeed,
} from "./market-evidence.ts";
import {
  verifyDirectAccountBinding,
  verifyMetrikaCounterBinding,
} from "./yandex-context.ts";

type ExecutionRow = {
  execution_id: string;
  user_key: string;
  account_key: string;
  status: string;
  campaign_id: string | null;
  projection_json: string;
  result_json: string;
};

function runtimeEnv() {
  return env as unknown as Record<string, string | undefined> & {
    DB: typeof env.DB;
  };
}

function now() {
  return new Date().toISOString();
}


function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Неизвестная ошибка";
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

export function userKey(request: Request) {
  const authenticated = request.headers.get("oai-authenticated-user-id")?.trim();
  if (authenticated) return authenticated;
  const hostname = new URL(request.url).hostname;
  if (hostname === "localhost" || hostname === "127.0.0.1") return "local-preview";
  throw new Error("Для production-модуля требуется вход через GPT Sites.");
}

function directWriteConfig() {
  const runtime = runtimeEnv();
  return {
    token: runtime.YANDEX_DIRECT_OAUTH_TOKEN ?? "",
    account: runtime.YANDEX_DIRECT_CLIENT_LOGIN ?? "",
  };
}

async function readDirectBinding() {
  const config = directWriteConfig();
  return verifyDirectAccountBinding(
    { token: config.token, expectedAccount: config.account },
    fetch,
    now,
  );
}

async function readMetrikaBinding() {
  const runtime = runtimeEnv();
  return verifyMetrikaCounterBinding(
    {
      token: runtime.YANDEX_METRICA_OAUTH_TOKEN ?? "",
      expectedCounterId: runtime.YANDEX_METRICA_COUNTER_ID ?? "",
      expectedGoalId: runtime.YANDEX_METRICA_GOAL_ID ?? "",
    },
    fetch,
    now,
  );
}

async function beginExecution(
  userKeyValue: string,
  account: string,
  projection: DirectProjection,
  executionId = crypto.randomUUID(),
) {
  const timestamp = now();
  await runtimeEnv()
    .DB.prepare(
      "INSERT INTO p0_executions(execution_id, user_key, account_key, status, projection_json, result_json, created_at, updated_at) VALUES (?, ?, ?, 'STARTED', ?, '{}', ?, ?)",
    )
    .bind(executionId, userKeyValue, account, JSON.stringify(projection), timestamp, timestamp)
    .run();
  return executionId;
}

async function findExactExecution(
  userKeyValue: string,
  account: string,
  projection: DirectProjection,
) {
  const rows = await runtimeEnv()
    .DB.prepare(
      "SELECT execution_id, user_key, account_key, status, campaign_id, projection_json, result_json FROM p0_executions WHERE user_key = ? AND account_key = ? ORDER BY created_at DESC LIMIT 20",
    )
    .bind(userKeyValue, account)
    .all<ExecutionRow>();
  const requestedFingerprint = await fingerprintDirectProjection(projection as unknown as Record<string, unknown>);
  for (const row of rows.results) {
    const storedProjection = JSON.parse(row.projection_json) as DirectProjection;
    const storedFingerprint = await fingerprintDirectProjection(storedProjection as unknown as Record<string, unknown>);
    if (storedFingerprint === requestedFingerprint) return row.execution_id;
  }
  return null;
}

function accountLockExpiry() {
  return new Date(Date.now() + 15 * 60_000).toISOString();
}

async function acquireAccountLock(account: string, userKeyValue: string, executionId: string) {
  const db = runtimeEnv().DB;
  const timestamp = now();
  await db.prepare("DELETE FROM p0_account_locks WHERE expires_at <= ?").bind(timestamp).run();
  const expiresAt = accountLockExpiry();
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

async function renewAccountLock(account: string, executionId: string) {
  const result = await runtimeEnv()
    .DB.prepare("UPDATE p0_account_locks SET expires_at = ? WHERE account_key = ? AND execution_id = ?")
    .bind(accountLockExpiry(), account, executionId)
    .run();
  if (Number(result.meta.changes) !== 1) throw new Error("Direct account single-writer lease потеряна.");
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

async function claimAccountLock(account: string, userKeyValue: string, executionId: string) {
  const db = runtimeEnv().DB;
  await db.prepare("DELETE FROM p0_account_locks WHERE expires_at <= ?").bind(now()).run();
  const lock = await db
    .prepare("SELECT execution_id FROM p0_account_locks WHERE account_key = ?")
    .bind(account)
    .first<{ execution_id: string }>();
  if (lock?.execution_id === executionId) return;
  if (lock) throw new Error("Для аккаунта уже выполняется другая production-запись.");
  await acquireAccountLock(account, userKeyValue, executionId);
}

class D1DirectExecutionJournal implements DirectExecutionJournal {
  constructor(
    private readonly ownerKey: string,
    private readonly projection: DirectProjection,
  ) {}

  async acquire(identity: DirectExecutionIdentity) {
    const row = await runtimeEnv()
      .DB.prepare(
        "SELECT execution_id, user_key, account_key, status, campaign_id, projection_json, result_json FROM p0_executions WHERE execution_id = ? AND user_key = ? AND account_key = ?",
      )
      .bind(identity.execution_id, this.ownerKey, identity.account)
      .first<ExecutionRow>();
    if (!row) throw new Error("Durable Direct execution record отсутствует.");
    const storedProjection = JSON.parse(row.projection_json) as DirectProjection;
    const [storedFingerprint, requestedFingerprint] = await Promise.all([
      fingerprintDirectProjection(storedProjection as unknown as Record<string, unknown>),
      fingerprintDirectProjection(this.projection as unknown as Record<string, unknown>),
    ]);
    if (storedFingerprint !== identity.publish_fingerprint || requestedFingerprint !== identity.publish_fingerprint) {
      throw new Error("Durable Direct execution fingerprint не совпадает.");
    }
    await claimAccountLock(identity.account, this.ownerKey, identity.execution_id);
    const value = JSON.parse(row.result_json) as Record<string, unknown>;
    if (!Object.keys(value).length) return null;
    if (value.schema_version !== "p0-direct-single-campaign-execution-v1") {
      await holdAccountLock(identity.account, identity.execution_id);
      throw new Error("Legacy Direct execution requires manual reconciliation.");
    }
    return value as DirectExecutionRecord;
  }

  async save(record: DirectExecutionRecord) {
    await renewAccountLock(record.account, record.execution_id);
    const result = await runtimeEnv()
      .DB.prepare(
        "UPDATE p0_executions SET status = ?, campaign_id = COALESCE(?, campaign_id), result_json = ?, updated_at = ? WHERE execution_id = ? AND user_key = ? AND account_key = ?",
      )
      .bind(
        record.status,
        record.provider_ids.campaign_id,
        JSON.stringify(record),
        record.updated_at,
        record.execution_id,
        this.ownerKey,
        record.account,
      )
      .run();
    if (Number(result.meta.changes) !== 1) throw new Error("Durable Direct execution checkpoint не сохранён.");
  }

  async release(identity: DirectExecutionIdentity) {
    await releaseAccountLock(identity.account, identity.execution_id);
  }

  async hold(identity: DirectExecutionIdentity) {
    await holdAccountLock(identity.account, identity.execution_id);
  }
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
  if (payload.result.LimitedBy !== undefined) {
    throw new Error("Direct campaign inventory preflight частичен: API ограничил результат.");
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

async function readMarketEvidence({
  model,
  generatedAt,
}: {
  model: Record<string, unknown>;
  context: P0Context;
  generatedAt: string;
}): Promise<MarketEvidenceInput> {
  const runtime = runtimeEnv();
  const phrase = cleanText(String(model.product ?? ""), 500);
  const regionIds = String(runtime.YANDEX_WORDSTAT_REGION_IDS ?? "")
    .split(",")
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isSafeInteger(item) && item > 0);
  const regionNames = String(runtime.YANDEX_WORDSTAT_REGION_NAMES ?? "")
    .split(",")
    .map((item) => cleanText(item, 100))
    .filter(Boolean);
  const configuredDevice = String(runtime.YANDEX_WORDSTAT_DEVICE ?? "all") as WordstatSeed["device"];
  const clusterId = "demand-cluster-primary";
  const demandClusters = [{
    cluster_id: clusterId,
    semantic_key: {
      product: phrase,
      need: cleanText(String(model.audience ?? ""), 500),
      intent: cleanText(String(model.qualified_result ?? ""), 500),
      offer: cleanText(String(model.value ?? ""), 500),
    },
  }];
  const configurationMissing = !phrase
    || !runtime.YANDEX_WORDSTAT_OAUTH_TOKEN
    || !runtime.YANDEX_WORDSTAT_CLIENT_ID
    || regionIds.length === 0
    || regionNames.length !== regionIds.length
    || !["all", "desktop", "phone", "tablet"].includes(configuredDevice);
  let wordstatBatch;
  if (configurationMissing) {
    wordstatBatch = await unavailableWordstatBatch(
      "Scoped Wordstat authority, phrase, explicit regions or device is unavailable for this Model revision.",
      generatedAt,
    );
  } else {
    const dynamicsPhrase = phrase
      .replace(/[!"[\]()|+]/gu, " ")
      .split(/\s+/u)
      .map((item) => item.replace(/[^\p{L}\p{N}-]/gu, ""))
      .filter(Boolean)
      .map((item) => `+${item}`)
      .join(" ");
    const observedDate = new Date(generatedAt);
    const dynamicsTo = new Date(Date.UTC(observedDate.getUTCFullYear(), observedDate.getUTCMonth(), 0));
    const dynamicsFrom = new Date(Date.UTC(dynamicsTo.getUTCFullYear() - 3, dynamicsTo.getUTCMonth(), 1));
    wordstatBatch = await collectOfficialWordstatBatch({
      token: runtime.YANDEX_WORDSTAT_OAUTH_TOKEN ?? "",
      clientId: runtime.YANDEX_WORDSTAT_CLIENT_ID ?? "",
      seeds: [{
        seed_id: "primary-product-demand",
        cluster_id: clusterId,
        phrase,
        dynamics_phrase: dynamicsPhrase,
        dynamics_period: "monthly",
        dynamics_from_date: dynamicsFrom.toISOString().slice(0, 10),
        dynamics_to_date: dynamicsTo.toISOString().slice(0, 10),
        operator_profile: "BROAD_CONTAINING",
        region_ids: regionIds,
        region_names: regionNames,
        device: configuredDevice,
      }],
    }, fetch, now);
  }
  const costObservations: CostObservation[] = [{
    observation_id: `live4-preflight:${generatedAt}`,
    source: "LEGACY_LIVE4_SCENARIO",
    status: "UNAVAILABLE",
    scenario: "account-specific documented Live 4 capability preflight",
    scope: { account: cleanText(String(runtime.YANDEX_DIRECT_CLIENT_LOGIN ?? ""), 255) },
    as_of: generatedAt,
    currency: cleanText(String(runtime.YANDEX_DIRECT_CURRENCY ?? "RUB"), 10),
    vat_treatment: "UNKNOWN",
    sample_size: { unit: "forecast_phrases", value: 0 },
    range: null,
    qualification: { account_specific: true, capability_status: "UNAVAILABLE", exact_scope: false },
    unavailable_reason: "LIVE4_CAPABILITY_PREFLIGHT_NOT_CONFIGURED",
  }];
  const comparableKeywordId = cleanText(String(runtime.P0_COMPARABLE_DIRECT_KEYWORD_ID ?? ""), 100);
  if (comparableKeywordId) {
    costObservations.push(await collectCurrentAuctionCostObservation({
      token: runtime.YANDEX_DIRECT_OAUTH_TOKEN ?? "",
      account: runtime.YANDEX_DIRECT_CLIENT_LOGIN ?? "",
      keyword_id: comparableKeywordId,
      expected_phrase: phrase,
      currency: cleanText(String(runtime.YANDEX_DIRECT_CURRENCY ?? "RUB"), 10),
      vat_treatment: runtime.YANDEX_DIRECT_INCLUDE_VAT === "true" ? "INCLUDED" : "EXCLUDED",
      traffic_volumes: String(runtime.P0_COMPARABLE_TRAFFIC_VOLUMES ?? "")
        .split(",")
        .map(Number)
        .filter((value) => Number.isFinite(value) && value > 0),
      comparability: {
        geography: runtime.P0_COMPARABLE_GEOGRAPHY === "MAPPED" ? "MAPPED" : runtime.P0_COMPARABLE_GEOGRAPHY === "SAME" ? "SAME" : "UNKNOWN",
        placement: runtime.P0_COMPARABLE_PLACEMENT === "SAME" ? "SAME" : "UNKNOWN",
        strategy: runtime.P0_COMPARABLE_STRATEGY === "SAME" ? "SAME" : "UNKNOWN",
        season: runtime.P0_COMPARABLE_SEASON === "SAME" ? "SAME" : "UNKNOWN",
      },
    }, fetch, now));
  }
  costObservations.push({
    observation_id: `direct-history:${generatedAt}`,
    source: "DIRECT_HISTORY_OWN_EMPIRICAL",
    status: "UNAVAILABLE",
    scenario: "comparable first-party day-level CPC P25-P75",
    scope: { account: cleanText(String(runtime.YANDEX_DIRECT_CLIENT_LOGIN ?? ""), 255), phrase: "UNKNOWN", geography: "UNKNOWN", placement: "UNKNOWN", strategy: "UNKNOWN", season: "UNKNOWN" },
    as_of: generatedAt,
    currency: cleanText(String(runtime.YANDEX_DIRECT_CURRENCY ?? "RUB"), 10),
    vat_treatment: "UNKNOWN",
    sample_size: { unit: "clicks", value: 0 },
    range: null,
    qualification: { first_party: true, clicks: 0 },
    unavailable_reason: "DIRECT_HISTORY_COMPARABLE_REPORT_NOT_CONFIGURED",
  });
  return {
    wordstat_batch: wordstatBatch,
    demand_clusters: demandClusters,
    cost_observations: costObservations,
  };
}

async function readContext(): Promise<P0Context> {
  const [directBindingResult, directResult, limitsResult, metrikaBindingResult, metrikaResult] = await Promise.allSettled([
    readDirectBinding(),
    readCampaignCatalog(),
    readCurrencyLimits(),
    readMetrikaBinding(),
    readMetrika(),
  ]);
  const directReady = directBindingResult.status === "fulfilled"
    && directResult.status === "fulfilled"
    && limitsResult.status === "fulfilled"
    && directBindingResult.value.account === directResult.value.account;
  const direct = directReady
    ? {
        ready: true,
        inventory_ready: true,
        ...directBindingResult.value,
        campaigns_total: directResult.value.total,
        minimum_weekly_budget_rub: limitsResult.value.minimum_weekly_budget_rub,
        read_limitations: {
          inventory_complete: true,
          limited_by: null,
          methods_read: ["Campaigns.get"],
          methods_not_read: ["AdGroups.get", "Keywords.get", "Ads.get", "SEARCH_QUERY_PERFORMANCE_REPORT"],
          statistics_provisional_days: 3,
        },
      }
    : {
        ready: false,
        inventory_ready: directResult.status === "fulfilled",
        authority: directBindingResult.status === "fulfilled" ? directBindingResult.value.authority : "UNVERIFIED",
        access: "YANDEX_DIRECT_API_V501",
        ...(directBindingResult.status === "fulfilled" ? directBindingResult.value : {}),
        ...(directResult.status === "fulfilled" ? {
          campaigns_total: directResult.value.total,
          read_limitations: {
            inventory_complete: true,
            limited_by: null,
            methods_read: ["Campaigns.get"],
            methods_not_read: ["AdGroups.get", "Keywords.get", "Ads.get", "SEARCH_QUERY_PERFORMANCE_REPORT"],
            statistics_provisional_days: 3,
          },
        } : {}),
        blockers: [
          ...(directBindingResult.status === "rejected" ? [errorMessage(directBindingResult.reason)] : []),
          ...(directResult.status === "rejected" ? [errorMessage(directResult.reason)] : []),
          ...(limitsResult.status === "rejected" ? [errorMessage(limitsResult.reason)] : []),
          ...(directBindingResult.status === "fulfilled" && directResult.status === "fulfilled"
            && directBindingResult.value.account !== directResult.value.account
            ? ["Direct advertiser account binding не совпадает с campaign inventory"]
            : []),
        ],
      };
  const metrikaReady = metrikaBindingResult.status === "fulfilled" && metrikaResult.status === "fulfilled";
  const metrika = metrikaReady
    ? { ready: true, ...metrikaBindingResult.value }
    : {
        ready: false,
        authority: metrikaBindingResult.status === "fulfilled" ? metrikaBindingResult.value.authority : "UNVERIFIED",
        access: "YANDEX_METRIKA_MANAGEMENT_AND_REPORTS_API",
        ...(metrikaBindingResult.status === "fulfilled" ? metrikaBindingResult.value : {}),
        blockers: [
          ...(metrikaBindingResult.status === "rejected" ? [errorMessage(metrikaBindingResult.reason)] : []),
          ...(metrikaResult.status === "rejected" ? [errorMessage(metrikaResult.reason)] : []),
        ],
      };
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
              attribution: "last_direct_click_order_dimension",
              timezone: metrikaBindingResult.status === "fulfilled" ? metrikaBindingResult.value.time_zone : "",
              dimensions: ["ym:s:date", "ym:s:lastDirectClickOrder"],
              filters: `ym:s:lastDirectClickOrder=='${runtimeEnv().YANDEX_DIRECT_CAMPAIGN_ID ?? ""}'`,
              sampling: metrikaResult.value.sampling,
            },
          }
        : null,
  };
}

async function resolveHostname(hostname: string) {
  const responses = await Promise.all(["A", "AAAA"].map(async (type) => {
    const query = new URLSearchParams({ name: hostname, type });
    const response = await fetch(`https://cloudflare-dns.com/dns-query?${query}`, {
      headers: { Accept: "application/dns-json" },
      redirect: "error",
    });
    if (!response.ok) throw new Error("DNS safety preflight недоступен.");
    const payload = await response.json() as {
      Status?: number;
      Answer?: Array<{ type?: number; data?: string }>;
    };
    if (payload.Status !== 0 && payload.Status !== 3) throw new Error("DNS safety preflight вернул ошибку.");
    const expectedType = type === "A" ? 1 : 28;
    return (payload.Answer ?? [])
      .filter((item) => item.type === expectedType)
      .map((item) => String(item.data ?? ""))
      .filter(Boolean);
  }));
  return responses.flat();
}

async function researchSite(rawUrl: string) {
  return researchPublicFirstPartySite(rawUrl, {
    fetch,
    resolveHostname,
    now,
  });
}

async function ensureTables() {
  const db = runtimeEnv().DB;
  if (!db) throw new Error("Sites D1 binding DB недоступен.");
  await db.prepare(
    "CREATE TABLE IF NOT EXISTS p0_state (user_key TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL, value_json TEXT NOT NULL)",
  ).run();
  await db.prepare(
    "CREATE TABLE IF NOT EXISTS p0_state_revisions (user_key TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL, value_json TEXT NOT NULL, PRIMARY KEY (user_key, revision))",
  ).run();
  await db.prepare(
    "CREATE TABLE IF NOT EXISTS p0_executions (execution_id TEXT PRIMARY KEY, user_key TEXT NOT NULL, account_key TEXT NOT NULL, status TEXT NOT NULL, campaign_id TEXT, projection_json TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
  ).run();
  await db.prepare(
    "CREATE TABLE IF NOT EXISTS p0_account_locks (account_key TEXT PRIMARY KEY, execution_id TEXT NOT NULL, owner_key TEXT NOT NULL, expires_at TEXT NOT NULL)",
  ).run();
}

class D1P0ApplicationStore implements P0ApplicationStore {
  async load(key: string): Promise<P0StoredRow | null> {
    await ensureTables();
    const row = await runtimeEnv().DB
      .prepare("SELECT revision, updated_at, value_json FROM p0_state WHERE user_key = ?")
      .bind(key)
      .first<P0StoredRow>();
    if (row) {
      await runtimeEnv().DB
        .prepare("INSERT OR IGNORE INTO p0_state_revisions(user_key, revision, updated_at, value_json) VALUES (?, ?, ?, ?)")
        .bind(key, row.revision, row.updated_at, row.value_json)
        .run();
    }
    return row;
  }

  async initialize(key: string, row: P0StoredRow) {
    await ensureTables();
    const result = await runtimeEnv().DB
      .prepare("INSERT OR IGNORE INTO p0_state(user_key, revision, updated_at, value_json) VALUES (?, ?, ?, ?)")
      .bind(key, row.revision, row.updated_at, row.value_json)
      .run();
    if (Number(result.meta.changes) !== 1) return false;
    await runtimeEnv().DB
      .prepare("INSERT OR IGNORE INTO p0_state_revisions(user_key, revision, updated_at, value_json) VALUES (?, ?, ?, ?)")
      .bind(key, row.revision, row.updated_at, row.value_json)
      .run();
    return true;
  }

  async compareAndSwap(key: string, expectedRevision: number, row: P0StoredRow) {
    const db = runtimeEnv().DB;
    const [result] = await db.batch([
      db.prepare(
        "UPDATE p0_state SET revision = ?, updated_at = ?, value_json = ? WHERE user_key = ? AND revision = ?",
      ).bind(row.revision, row.updated_at, row.value_json, key, expectedRevision),
      db.prepare(
        "INSERT OR IGNORE INTO p0_state_revisions(user_key, revision, updated_at, value_json) SELECT user_key, revision, updated_at, value_json FROM p0_state WHERE user_key = ? AND revision = ? AND value_json = ?",
      ).bind(key, row.revision, row.value_json),
    ]);
    return Number(result.meta.changes) === 1;
  }

  async history(key: string, limit = 50) {
    await ensureTables();
    const result = await runtimeEnv().DB
      .prepare(
        "SELECT revision, updated_at, value_json FROM p0_state_revisions WHERE user_key = ? ORDER BY revision DESC LIMIT ?",
      )
      .bind(key, limit)
      .all<P0StoredRow>();
    return result.results;
  }
}

async function createPackageItemOutcome({
  key,
  state,
  item_execution_id: itemExecutionId,
  selection,
  projection,
  draft,
  gate,
}: {
  key: string;
  state: P0Document;
  package_execution_id: string;
  item_execution_id: string;
  selection: NonNullable<P0Document["shortlist"]>["selections"][number];
  projection: DirectProjection;
  draft: NonNullable<P0Document["recommendation_set"]>["drafts"][number];
  gate: NonNullable<P0Document["human_decision_gate"]>;
}) {
  const config = directWriteConfig();
  if (!config.token || !config.account) throw new Error("Direct production credentials не настроены.");
  if (!state.strategy || !state.context_state || !state.recommendation_set) {
    throw new Error("Exact package execution lineage отсутствует.");
  }
  const [binding, catalog, limits] = await Promise.all([
    readDirectBinding(),
    readCampaignCatalog(),
    readCurrencyLimits(),
  ]);
  if (binding.account !== config.account || catalog.account !== binding.account) {
    throw new Error("Direct write account не прошёл точный API binding preflight.");
  }
  validateWeeklyBudgetRub(strategyAnswerValue(state.strategy, "weekly_budget"), limits.minimum_weekly_budget_rub);
  const existing = await runtimeEnv()
    .DB.prepare("SELECT execution_id FROM p0_executions WHERE execution_id = ? AND user_key = ? AND account_key = ?")
    .bind(itemExecutionId, key, config.account)
    .first<{ execution_id: string }>();
  if (!existing) {
    if (hasDuplicateCampaignName(catalog.names, String(projection.direct.campaign.Name ?? ""))) {
      return {
        execution_id: itemExecutionId,
        status: "SYSTEM_FAILED",
        error_code: "P0_DUPLICATE_CAMPAIGN_NAME",
        error_message: "MOX-ADV preflight обнаружил существующую активную кампанию с таким названием.",
        validation_failed: true,
        dispatch_not_attempted: true,
        containment: "NOT_CREATED",
        account_lock: "RELEASED",
      };
    }
    await beginExecution(key, config.account, projection, itemExecutionId);
  }
  const packageAuthority = gate.authority;
  try {
    const result = await executeSafeSingleCampaign({
      execution_id: itemExecutionId,
      config,
      projection,
      authority: {
        direct_account_binding: packageAuthority.direct_account_binding,
        direct_capability_snapshot: packageAuthority.direct_capability_snapshot,
        capability_profile: packageAuthority.capability_profile,
        publish_fingerprint: selection.publish_fingerprint,
        publication_blockers: campaignDraftPublishBlockers(draft),
      },
      journal: new D1DirectExecutionJournal(key, projection),
      fetcher: fetch,
      now,
    });
    return { execution_id: itemExecutionId, ...result };
  } catch (error) {
    if (!(error instanceof DirectWriteError)) throw error;
    return directExecutionFailureOutcome(itemExecutionId, error);
  }
}

async function resubmitCorrectedPackageItemOutcome({
  key,
  state,
  item_execution_id: itemExecutionId,
  selection,
  projection,
  draft,
  gate,
  source_item: sourceItem,
}: {
  key: string;
  state: P0Document;
  package_execution_id: string;
  item_execution_id: string;
  selection: NonNullable<P0Document["shortlist"]>["selections"][number];
  projection: DirectProjection;
  draft: NonNullable<P0Document["recommendation_set"]>["drafts"][number];
  gate: NonNullable<P0Document["human_decision_gate"]>;
  source_item: NonNullable<P0Document["package_execution"]>["items"][number];
}) {
  const config = directWriteConfig();
  if (!config.token || !config.account) throw new Error("Direct production credentials не настроены.");
  if (!state.strategy || !state.context_state || gate.authority.direct_account_binding.account !== config.account) {
    throw new Error("Corrected package Gate не совпадает с persisted Strategy, Context или Direct account.");
  }
  const campaignId = sourceItem.provider_ids.campaign_id;
  const adGroupId = sourceItem.provider_ids.ad_group_id;
  const keywordId = sourceItem.provider_ids.keyword_id;
  const adId = sourceItem.provider_ids.ad_ids[0];
  if (!campaignId || !adGroupId || !keywordId || !adId
    || sourceItem.provider_ids.ad_group_ids.length !== 1
    || sourceItem.provider_ids.keyword_ids.length !== 1
    || sourceItem.provider_ids.ad_ids.length !== 1
    || sourceItem.status !== "REJECTED_NEEDS_EDIT"
    || sourceItem.account_lock !== "RELEASED") {
    throw new Error("Correction resubmission requires one fully-accounted rejected core Direct graph.");
  }
  const changedPointers = (Array.isArray(record(draft.material_delta).fields) ? record(draft.material_delta).fields as unknown[] : [])
    .map((field) => String(record(field).pointer ?? ""))
    .filter(Boolean);
  const requestedFingerprint = await fingerprintDirectProjection(projection as unknown as Record<string, unknown>);
  if (requestedFingerprint !== selection.publish_fingerprint) {
    throw new Error("Corrected projection fingerprint не совпадает с exact Gate.");
  }
  const existing = await runtimeEnv()
    .DB.prepare("SELECT execution_id FROM p0_executions WHERE execution_id = ? AND user_key = ? AND account_key = ?")
    .bind(itemExecutionId, key, config.account)
    .first<{ execution_id: string }>();
  if (!existing) await beginExecution(key, config.account, projection, itemExecutionId);
  await claimAccountLock(config.account, key, itemExecutionId);
  const row = await runtimeEnv()
    .DB.prepare("SELECT execution_id, user_key, account_key, status, campaign_id, projection_json, result_json FROM p0_executions WHERE execution_id = ? AND user_key = ? AND account_key = ?")
    .bind(itemExecutionId, key, config.account)
    .first<ExecutionRow>();
  if (!row) {
    await holdAccountLock(config.account, itemExecutionId);
    throw new DirectWriteError("P0_CORRECTION_JOURNAL_MISSING", "Durable corrected Direct execution record отсутствует.", {
      requires_reconciliation: true,
      containment: "RECONCILIATION_REQUIRED",
      account_lock: "HELD_FOR_RECONCILIATION",
    });
  }
  const storedProjection = JSON.parse(row.projection_json) as DirectProjection;
  if (await fingerprintDirectProjection(storedProjection as unknown as Record<string, unknown>) !== requestedFingerprint) {
    await holdAccountLock(config.account, itemExecutionId);
    throw new DirectWriteError("P0_CORRECTION_FINGERPRINT_MISMATCH", "Durable corrected Direct execution fingerprint не совпадает.", {
      requires_reconciliation: true,
      containment: "RECONCILIATION_REQUIRED",
      account_lock: "HELD_FOR_RECONCILIATION",
    });
  }
  const stored = JSON.parse(row.result_json) as Record<string, unknown>;
  if (Object.keys(stored).length && stored.schema_version !== "p0-direct-correction-execution-v1") {
    await holdAccountLock(config.account, itemExecutionId);
    throw new DirectWriteError("P0_CORRECTION_JOURNAL_SCHEMA_INVALID", "Corrected Direct execution journal schema requires manual reconciliation.", {
      requires_reconciliation: true,
      containment: "RECONCILIATION_REQUIRED",
      account_lock: "HELD_FOR_RECONCILIATION",
    });
  }
  const storedSourceIds = record(stored.source_provider_ids);
  const sourceProviderIds = { campaign_id: campaignId, ad_group_id: adGroupId, keyword_id: keywordId, ad_id: adId };
  if (Object.keys(storedSourceIds).length && JSON.stringify(storedSourceIds) !== JSON.stringify(sourceProviderIds)) {
    await holdAccountLock(config.account, itemExecutionId);
    throw new DirectWriteError("P0_CORRECTION_PROVIDER_LINEAGE_CHANGED", "Corrected Direct source provider lineage changed.", {
      requires_reconciliation: true,
      containment: "RECONCILIATION_REQUIRED",
      account_lock: "HELD_FOR_RECONCILIATION",
    });
  }
  const terminalResult = record(stored.terminal_result);
  if (Object.keys(terminalResult).length) {
    await releaseAccountLock(config.account, itemExecutionId);
    return { execution_id: itemExecutionId, ...terminalResult };
  }
  let journal: Record<string, unknown> = Object.keys(stored).length ? stored : {
    schema_version: "p0-direct-correction-execution-v1",
    execution_id: itemExecutionId,
    publish_fingerprint: requestedFingerprint,
    source_provider_ids: sourceProviderIds,
    status: "CORRECTION_DISPATCH_INTENT_PERSISTED",
    completed_updates: [],
    moderation_intent_persisted: false,
    progress: {},
    terminal_result: null,
  };
  const saveJournal = async (status: string, progress: Record<string, unknown>) => {
    journal = {
      ...journal,
      status,
      completed_updates: Array.isArray(progress.completed_updates) ? structuredClone(progress.completed_updates) : journal.completed_updates,
      moderation_intent_persisted: progress.moderation_intent_persisted === true || journal.moderation_intent_persisted === true,
      progress: structuredClone(progress),
      updated_at: now(),
    };
    await renewAccountLock(config.account, itemExecutionId);
    const saved = await runtimeEnv().DB
      .prepare("UPDATE p0_executions SET status = ?, campaign_id = ?, result_json = ?, updated_at = ? WHERE execution_id = ? AND user_key = ? AND account_key = ?")
      .bind(status, campaignId, JSON.stringify(journal), journal.updated_at, itemExecutionId, key, config.account)
      .run();
    if (Number(saved.meta.changes) !== 1) throw new Error("Durable corrected Direct checkpoint не сохранён.");
  };
  await saveJournal(String(journal.status), record(journal.progress));
  try {
    const result = await correctSuspendedCampaignAndResubmitModeration(
      config,
      projection,
      { campaignId, adGroupId, keywordId, adId },
      changedPointers,
      fetch,
      saveJournal,
      {
        completedUpdates: Array.isArray(journal.completed_updates) ? journal.completed_updates.map(String) : [],
        moderationIntentPersisted: journal.moderation_intent_persisted === true,
      },
    );
    journal = { ...journal, status: String(result.status), terminal_result: structuredClone(result), updated_at: now() };
    await saveJournal(String(result.status), result);
    await releaseAccountLock(config.account, itemExecutionId);
    return { execution_id: itemExecutionId, ...result };
  } catch (error) {
    if (!(error instanceof DirectWriteError)) {
      await holdAccountLock(config.account, itemExecutionId);
      throw new DirectWriteError("P0_CORRECTION_JOURNAL_FAILED", "Corrected Direct execution journal interrupted; reconciliation retains the account boundary.", {
        requires_reconciliation: true,
        containment: "RECONCILIATION_REQUIRED",
        account_lock: "HELD_FOR_RECONCILIATION",
      }, { cause: error });
    }
    const requiresReconciliation = error.partial.requires_reconciliation === true
      || error.partial.account_lock === "HELD_FOR_RECONCILIATION"
      || ["RECONCILIATION_REQUIRED", "MANUAL_RECONCILIATION_REQUIRED"].includes(String(error.partial.containment ?? ""));
    const outcome = directExecutionFailureOutcome(itemExecutionId, Object.assign(error, {
      partial: {
        ...error.partial,
        campaign_id: campaignId,
        provider_ids: {
          campaign_id: campaignId,
          ad_group_id: adGroupId,
          keyword_id: keywordId,
          ad_group_ids: [adGroupId],
          keyword_ids: [keywordId],
          ad_ids: [adId],
        },
        account_lock: requiresReconciliation ? "HELD_FOR_RECONCILIATION" : "RELEASED",
      },
    }));
    journal = { ...journal, status: String(outcome.status), terminal_result: requiresReconciliation ? null : structuredClone(outcome), updated_at: now() };
    await saveJournal(String(outcome.status), outcome);
    if (requiresReconciliation) await holdAccountLock(config.account, itemExecutionId);
    else await releaseAccountLock(config.account, itemExecutionId);
    return outcome;
  }
}

async function pollPackageItemOutcome({
  key,
  item_execution_id: itemExecutionId,
  projection,
  item,
  gate,
}: {
  key: string;
  state: P0Document;
  package_execution_id: string;
  item_execution_id: string;
  selection: NonNullable<P0Document["shortlist"]>["selections"][number];
  projection: DirectProjection;
  draft: NonNullable<P0Document["recommendation_set"]>["drafts"][number];
  item: NonNullable<P0Document["package_execution"]>["items"][number];
  gate: NonNullable<P0Document["human_decision_gate"]>;
}) {
  const config = directWriteConfig();
  if (!config.token || !config.account) throw new Error("Direct production credentials не настроены.");
  if (gate.authority.direct_account_binding.account !== config.account) {
    throw new Error("Exact package Gate не совпадает с Direct moderation account.");
  }
  const row = await runtimeEnv()
    .DB.prepare("SELECT execution_id, user_key, account_key, status, campaign_id, projection_json, result_json FROM p0_executions WHERE execution_id = ? AND user_key = ? AND account_key = ?")
    .bind(itemExecutionId, key, config.account)
    .first<ExecutionRow>();
  if (!row) throw new Error("Durable Direct execution record отсутствует для moderation poll.");
  const storedProjection = JSON.parse(row.projection_json) as DirectProjection;
  const [storedFingerprint, requestedFingerprint] = await Promise.all([
    fingerprintDirectProjection(storedProjection as unknown as Record<string, unknown>),
    fingerprintDirectProjection(projection as unknown as Record<string, unknown>),
  ]);
  if (storedFingerprint !== requestedFingerprint || requestedFingerprint !== item.selection.publish_fingerprint) {
    throw new Error("Moderation poll projection fingerprint не совпадает с durable item execution.");
  }
  const campaignId = item.provider_ids.campaign_id;
  const adGroupId = item.provider_ids.ad_group_id;
  const keywordId = item.provider_ids.keyword_id;
  if (!campaignId || !adGroupId || !keywordId || item.provider_ids.ad_ids.length !== 1) {
    throw new Error("Moderation poll требует полный набор exact core provider IDs.");
  }
  try {
    return {
      execution_id: itemExecutionId,
      ...await pollSuspendedCampaignModeration(
        config,
        projection,
        { campaignId, adGroupId, keywordId, adIds: item.provider_ids.ad_ids },
        fetch,
      ),
    };
  } catch (error) {
    if (!(error instanceof DirectWriteError)) throw error;
    if (error.partial.requires_reconciliation === true) {
      return {
        execution_id: itemExecutionId,
        status: "OUTCOME_UNKNOWN",
        campaign_id: campaignId,
        provider_ids: structuredClone(item.provider_ids),
        campaign_state: item.campaign_state,
        containment: item.containment,
        account_lock: "RELEASED",
        error_code: error.code,
        error_message: error.message,
      };
    }
    return directExecutionFailureOutcome(itemExecutionId, Object.assign(error, {
      partial: {
        ...error.partial,
        campaign_id: campaignId,
        provider_ids: structuredClone(item.provider_ids),
        campaign_state: item.campaign_state,
        containment: item.containment,
        account_lock: "RELEASED",
      },
    }));
  }
}

async function createExternalOutcome({
  key,
  state,
  projection,
}: {
  key: string;
  state: P0Document;
  projection: DirectProjection;
}) {
  const config = directWriteConfig();
  if (!config.token || !config.account) throw new Error("Direct production credentials не настроены.");
  const [binding, catalog, limits] = await Promise.all([
    readDirectBinding(),
    readCampaignCatalog(),
    readCurrencyLimits(),
  ]);
  if (binding.account !== config.account || catalog.account !== binding.account) {
    throw new Error("Direct write account не прошёл точный API binding preflight.");
  }
  if (!state.strategy) throw new Error("Campaign Strategy отсутствует.");
  validateWeeklyBudgetRub(strategyAnswerValue(state.strategy, "weekly_budget"), limits.minimum_weekly_budget_rub);
  if (!state.context_state || !state.recommendation_set || !state.draft) {
    throw new Error("Exact Context, Recommendation Set и Campaign Draft отсутствуют.");
  }
  const campaignName = String(projection.direct.campaign.Name ?? "");
  let executionId = await findExactExecution(key, config.account, projection);
  if (!executionId) {
    if (hasDuplicateCampaignName(catalog.names, campaignName)) {
      throw new Error("В аккаунте уже существует активная кампания с таким названием.");
    }
    executionId = await beginExecution(key, config.account, projection);
  }
  const directFacts = state.context_state.facts.direct;
  const publishFingerprint = String(state.draft.publish_fingerprint ?? "");
  const result = await executeSafeSingleCampaign({
    execution_id: executionId,
    config,
    projection,
    authority: {
      direct_account_binding: {
        source_kind: "YANDEX_DIRECT_API_V501",
        account: directFacts.account,
        client_id: directFacts.client_id,
        verified: true,
      },
      direct_capability_snapshot: directFacts.capability_snapshot as unknown as Record<string, unknown>,
      capability_profile: state.recommendation_set.capability_profile as unknown as Record<string, unknown>,
      publish_fingerprint: publishFingerprint,
      publication_blockers: campaignDraftPublishBlockers(state.draft),
    },
    journal: new D1DirectExecutionJournal(key, projection),
    fetcher: fetch,
    now,
  });
  return { execution_id: executionId, ...result };
}

const application = new P0Application({
  store: new D1P0ApplicationStore(),
  adapters: {
    now,
    readContext,
    researchSite,
    readCurrencyLimits,
    readMarketEvidence,
    externalWriteConfiguration() {
      const config = directWriteConfig();
      const blockers = [
        ...(!config.token ? ["Direct production OAuth token не настроен"] : []),
        ...(!config.account ? ["Direct advertiser account не настроен"] : []),
      ];
      return { ready: blockers.length === 0, blockers, account: config.account };
    },
    createExternalOutcome,
    createPackageItemOutcome,
    resubmitCorrectedPackageItemOutcome,
    pollPackageItemOutcome,
  },
});

export async function overview(key: string) {
  return application.query(key);
}

export async function applyAction(key: string, payload: Record<string, unknown>) {
  return application.command(key, payload as P0Command);
}
