import { env } from "cloudflare:workers";
import {
  hasDuplicateCampaignName,
} from "./campaign-draft.ts";
import { fingerprintDirectProjection } from "./campaign-fanout.ts";
import { minimumWeeklyBudgetRub, validateWeeklyBudgetRub } from "./direct-limits.ts";
import {
  createSuspendedCampaign,
  DirectWriteError,
  type DirectProjection,
} from "./direct-write.ts";
import { mustHoldAccountLock } from "./execution-safety.ts";
import {
  P0Application,
  type P0ApplicationStore,
  type P0Command,
  type P0Context,
  type P0Document,
  type P0StoredRow,
  type PageEvidence,
  type SiteAnalysis,
} from "./p0-application.ts";
import { normalizePublicHttpsUrl, requirePublicHttpsUrl } from "./site-url.ts";
import { cleanText } from "./text.ts";

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

type ExecutionRow = {
  execution_id: string;
  campaign_id: string;
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

async function readContext(): Promise<P0Context> {
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
    return { execution_id: executionId, ...result };
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
}

const application = new P0Application({
  store: new D1P0ApplicationStore(),
  adapters: {
    now,
    readContext,
    researchSite,
    readCurrencyLimits,
    externalWriteConfiguration() {
      const config = directWriteConfig();
      const blockers = [
        ...(!config.token ? ["Direct production OAuth token не настроен"] : []),
        ...(!config.account ? ["Direct advertiser account не настроен"] : []),
      ];
      return { ready: blockers.length === 0, blockers, account: config.account };
    },
    createExternalOutcome,
  },
});

export async function overview(key: string) {
  return application.query(key);
}

export async function applyAction(key: string, payload: Record<string, unknown>) {
  return application.command(key, payload as P0Command);
}
