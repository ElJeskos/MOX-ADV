import { buildAdTitle } from "./ad-copy.ts";
import {
  buildAnalyticsEvidence,
  redactSensitiveEvidenceText,
  verifyAnalyticsEvidenceSnapshot,
  type AnalyticsEvidenceBundle,
} from "./analytics-evidence.ts";
import {
  inferDecisionMakers,
  inferOffer,
  isUnprocessedAudience,
  isUnprocessedOffer,
} from "./business-model.ts";
import {
  buildCampaignNames,
  buildPublishProjection,
  isCampaignNameWithGeography,
  isLegacySearchName,
} from "./campaign-draft.ts";
import {
  buildCampaignRecommendationSet,
  campaignDraftPublishBlockers,
  fingerprintDirectProjection,
  type CampaignRecommendationSet,
} from "./campaign-fanout.ts";
import {
  explainScoreDelta,
  scoreCampaignDrafts,
} from "./campaign-viability.ts";
import { validateWeeklyBudgetRub } from "./direct-limits.ts";
import type { DirectProjection } from "./direct-write.ts";
import {
  summarizeP0Revision,
  type P0RevisionSummary,
} from "./revision-history.ts";
import { normalizePublicHttpsUrl } from "./site-url.ts";
import { cleanText } from "./text.ts";
import type { MarketEvidenceInput } from "./market-evidence.ts";

export const P0_APPLICATION_CONTRACT = "mox-adv.p0.application";
export const P0_APPLICATION_CONTRACT_VERSION = "1.3.0";
export const P0_DOCUMENT_SCHEMA = "p0-application-document-v2";
const P0_LEGACY_DOCUMENT_SCHEMA = "p0-application-document-v1";
export const P0_CONTEXT_SCHEMA = "p0-context-v1";
export const P0_CONTEXT_PREFLIGHT_MAX_AGE_MS = 5 * 60_000;

export type P0ContextState = {
  schema_version: typeof P0_CONTEXT_SCHEMA;
  status: "GOAL_PROVISIONAL" | "GOAL_CONFIRMED";
  facts: {
    direct: {
      account: string;
      client_id: string;
      campaigns_total: number;
      minimum_weekly_budget_rub: number | null;
      observed_at: string;
      source_kind: "YANDEX_DIRECT_API_V501";
    };
    metrika: {
      counter_id: string;
      goal_id: string;
      observed_at: string;
      source_kind: "YANDEX_METRIKA_MANAGEMENT_AND_REPORTS_API";
    };
    site: {
      url: string;
      title: string;
      pages_analyzed: number;
      fetched_at: string;
      source_kind: "PUBLIC_FIRST_PARTY_HTTPS";
    };
  };
  provisional_business_goal: {
    value: string;
    rationale: string;
    proposed_at: string;
    source_url: string;
  };
  business_goal_decision: {
    value: string;
    provisional_value: string;
    decision: "CONFIRMED" | "CORRECTED";
    decided_at: string;
    owner_confirmed: true;
  } | null;
  material_fingerprint: string;
  last_material_change: {
    affected_steps: ["campaign_strategy", "recommendation_set", "campaign_drafts", "shortlist", "confirmation"];
    invalidated_at: string;
    previous_lineage: {
      strategy_revision_id: string | null;
      recommendation_set_id: string | null;
      draft_revision_id: string | null;
      shortlist_revision_id: string | null;
      publish_fingerprint: string | null;
    };
  } | null;
};

export type P0Document = {
  schema_version: typeof P0_DOCUMENT_SCHEMA;
  context_state: P0ContextState | null;
  site_analysis: SiteAnalysis | null;
  business_model: BusinessModel | null;
  analytics_evidence_snapshot: AnalyticsEvidenceBundle | null;
  strategy: Record<string, unknown> | null;
  recommendation_set: CampaignRecommendationSet | null;
  draft: Record<string, unknown> | null;
  shortlist: {
    schema_version: "p0-shortlist-v1";
    shortlist_revision_id: string;
    strategy_revision_id: string;
    draft_revision_ids: string[];
    updated_at: string;
  } | null;
  external_write_intent: {
    strategy_revision_id: string;
    draft_revision_id: string;
    publish_fingerprint: string;
    confirmed_at: string;
  } | null;
  campaign: Record<string, unknown> | null;
};

export type P0StoredRow = {
  revision: number;
  updated_at: string;
  value_json: string;
};

export interface P0ApplicationStore {
  load(key: string): Promise<P0StoredRow | null>;
  initialize(key: string, row: P0StoredRow): Promise<boolean>;
  compareAndSwap(key: string, expectedRevision: number, row: P0StoredRow): Promise<boolean>;
  history(key: string, limit?: number): Promise<P0StoredRow[]>;
}

export type P0Context = {
  environment: "PRODUCTION";
  test_scenario: false;
  direct: Record<string, unknown>;
  metrika: Record<string, unknown>;
  performance: Record<string, unknown> | null;
  campaign_catalog: Record<string, unknown> | null;
  competitor_observations?: Array<Record<string, unknown>>;
};

export type P0ExternalWriteConfiguration = {
  ready: boolean;
  blockers: string[];
  account: string;
};

export interface P0ApplicationAdapters {
  now(): string;
  readContext(): Promise<P0Context>;
  researchSite(url: string): Promise<SiteAnalysis>;
  readCurrencyLimits(): Promise<{ minimum_weekly_budget_rub: number }>;
  readMarketEvidence?(input: {
    model: BusinessModel;
    context: P0Context;
    generatedAt: string;
  }): Promise<MarketEvidenceInput>;
  externalWriteConfiguration(): P0ExternalWriteConfiguration;
  createExternalOutcome(input: {
    key: string;
    state: P0Document;
    projection: DirectProjection;
  }): Promise<Record<string, unknown>>;
}

export type P0Command = Record<string, unknown> & {
  action: string;
  expected_revision: number;
};

export type PageEvidence = {
  url: string;
  title: string;
  description: string;
  headings: string[];
  forms_detected: number;
  text_excerpt: string;
};

export type SiteAnalysis = PageEvidence & {
  fetched_at: string;
  pages: PageEvidence[];
  research: {
    pages_analyzed: number;
    links_discovered: number;
    scope: string;
  };
};

export type BusinessModel = {
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
};

export class P0ApplicationError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "P0ApplicationError";
    this.code = code;
  }
}

const WORKFLOW_STEPS = [
  { id: "context", label: "Контекст", detail: "Реальные подключения" },
  { id: "business_model", label: "Модель бизнеса", detail: "Агентное исследование" },
  { id: "campaign_strategy", label: "Стратегия кампании", detail: "Критические решения" },
  { id: "campaign_drafts", label: "Рекламные кампании", detail: "Точная проекция" },
  { id: "confirmation", label: "Подтверждение", detail: "Guarded write" },
] as const;

export const P0_COMMAND_TRUTH_TABLE = {
  analyze_site: (state: P0Document) => !state.campaign && !state.external_write_intent,
  confirm_context_goal: (state: P0Document) => Boolean(
    state.context_state && state.site_analysis && !state.campaign && !state.external_write_intent,
  ),
  save_business_model: (state: P0Document) => Boolean(
    state.site_analysis && state.business_model && !state.campaign && !state.external_write_intent,
  ),
  save_strategy: (state: P0Document) => (
    state.business_model?.source === "REAL_SITE_RESEARCH_PLUS_OWNER_CONFIRMATION"
    && !state.campaign
    && !state.external_write_intent
  ),
  save_draft: (state: P0Document) => Boolean(
    state.strategy && state.recommendation_set && !state.campaign && !state.external_write_intent,
  ),
  confirm_creation: (state: P0Document) => Boolean(
    state.draft?.publish_projection
    && state.shortlist?.draft_revision_ids.includes(String(state.draft.draft_revision_id ?? ""))
    && (!state.context_state || state.context_state.status === "GOAL_CONFIRMED")
    && !state.campaign,
  ),
  reset: (state: P0Document) => !state.campaign && !state.external_write_intent,
} as const;

type CommandName = keyof typeof P0_COMMAND_TRUTH_TABLE;

type LoadedDocument = {
  revision: number;
  updated_at: string;
  state: P0Document;
};

function fail(code: string, message: string): never {
  throw new P0ApplicationError(code, message);
}

function emptyDocument(): P0Document {
  return {
    schema_version: P0_DOCUMENT_SCHEMA,
    context_state: null,
    site_analysis: null,
    business_model: null,
    analytics_evidence_snapshot: null,
    strategy: null,
    recommendation_set: null,
    draft: null,
    shortlist: null,
    external_write_intent: null,
    campaign: null,
  };
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function requiredInput(value: unknown, label: string, maximum: number) {
  const normalized = cleanText(String(value ?? ""), 10_000);
  if (!normalized) fail("P0_INPUT_REQUIRED", `${label} не заполнено.`);
  if (normalized.length > maximum) fail("P0_INPUT_TOO_LONG", `${label}: максимум ${maximum} символов.`);
  return artifactText(normalized, maximum);
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Неизвестная ошибка";
}

function artifactText(value: unknown, maximum: number) {
  return cleanText(redactSensitiveEvidenceText(value, maximum), maximum + 20);
}

function stringList(value: unknown) {
  return Array.isArray(value)
    ? value.map((item) => artifactText(item, 500)).filter(Boolean).slice(0, 20)
    : [];
}

function sanitizeSiteAnalysis(input: SiteAnalysis): SiteAnalysis {
  const sanitizePage = (page: PageEvidence): PageEvidence => ({
    url: normalizePublicHttpsUrl(page.url).toString(),
    title: artifactText(page.title, 500),
    description: artifactText(page.description, 1_000),
    headings: page.headings.slice(0, 20).map((item) => artifactText(item, 1_000)),
    forms_detected: Math.max(0, Number(page.forms_detected ?? 0)),
    text_excerpt: artifactText(page.text_excerpt, 8_000),
  });
  const pages = input.pages.slice(0, 6).map(sanitizePage);
  const entry = sanitizePage(input);
  return {
    ...entry,
    fetched_at: cleanText(String(input.fetched_at ?? ""), 100),
    pages,
    research: {
      pages_analyzed: pages.length,
      links_discovered: Math.max(0, Number(input.research.links_discovered ?? 0)),
      scope: cleanText(String(input.research.scope ?? ""), 100),
    },
  };
}

function sanitizeContext(input: P0Context): P0Context {
  const direct = record(input.direct);
  const directBinding = record(direct.binding);
  const directReadLimitations = record(direct.read_limitations);
  const metrika = record(input.metrika);
  const metrikaBinding = record(metrika.binding);
  const goalBinding = record(metrika.goal_binding);
  const catalog = record(input.campaign_catalog);
  const performance = record(input.performance);
  const metrics = record(performance.display_metrics);
  const provenance = record(performance.provenance);
  const sampling = record(provenance.sampling);
  const samplingMetadataComplete = [
    "sampled",
    "contains_sensitive_data",
    "sample_share",
    "sample_size",
    "sample_space",
    "data_lag",
  ].every((key) => Object.hasOwn(sampling, key));
  return {
    environment: "PRODUCTION",
    test_scenario: false,
    direct: {
      ready: direct.ready === true,
      inventory_ready: direct.inventory_ready === true,
      authority: cleanText(String(direct.authority ?? ""), 50),
      access: cleanText(String(direct.access ?? ""), 100),
      account: cleanText(String(direct.account ?? ""), 255),
      client_id: cleanText(String(direct.client_id ?? ""), 100),
      binding: {
        expected_account: cleanText(String(directBinding.expected_account ?? ""), 255),
        api_account: cleanText(String(directBinding.api_account ?? ""), 255),
        matched: directBinding.matched === true,
      },
      campaigns_total: Number(direct.campaigns_total ?? 0),
      minimum_weekly_budget_rub: Number(direct.minimum_weekly_budget_rub),
      observed_at: cleanText(String(direct.observed_at ?? ""), 100),
      read_limitations: {
        inventory_complete: directReadLimitations.inventory_complete === true,
        limited_by: directReadLimitations.limited_by === null || directReadLimitations.limited_by === undefined
          ? null
          : Number(directReadLimitations.limited_by),
        methods_read: stringList(directReadLimitations.methods_read),
        methods_not_read: stringList(directReadLimitations.methods_not_read),
        statistics_provisional_days: Number(directReadLimitations.statistics_provisional_days ?? 3),
      },
      blockers: stringList(direct.blockers),
    },
    metrika: {
      ready: metrika.ready === true,
      authority: cleanText(String(metrika.authority ?? ""), 50),
      access: cleanText(String(metrika.access ?? ""), 100),
      counter_id: cleanText(String(metrika.counter_id ?? ""), 100),
      goal_id: cleanText(String(metrika.goal_id ?? ""), 100),
      time_zone: cleanText(String(metrika.time_zone ?? ""), 100),
      binding: {
        expected_counter_id: cleanText(String(metrikaBinding.expected_counter_id ?? ""), 100),
        api_counter_id: cleanText(String(metrikaBinding.api_counter_id ?? ""), 100),
        matched: metrikaBinding.matched === true,
      },
      goal_binding: {
        expected_goal_id: cleanText(String(goalBinding.expected_goal_id ?? ""), 100),
        api_goal_id: cleanText(String(goalBinding.api_goal_id ?? ""), 100),
        matched: goalBinding.matched === true,
      },
      observed_at: cleanText(String(metrika.observed_at ?? ""), 100),
      blockers: stringList(metrika.blockers),
    },
    campaign_catalog: input.campaign_catalog
      ? {
          total: Number(catalog.total ?? 0),
          active: Array.isArray(catalog.active)
            ? catalog.active.slice(0, 20).map((item) => {
                const campaign = record(item);
                return {
                  campaign_id: cleanText(String(campaign.campaign_id ?? ""), 100),
                  name: cleanText(String(campaign.name ?? ""), 255),
                  state: cleanText(String(campaign.state ?? ""), 50),
                  status: cleanText(String(campaign.status ?? ""), 50),
                };
              })
            : [],
        }
      : null,
    performance: input.performance
      ? {
          period_start: cleanText(String(performance.period_start ?? ""), 20),
          period_end: cleanText(String(performance.period_end ?? ""), 20),
          display_metrics: {
            visits: cleanText(String(metrics.visits ?? ""), 100),
            goal_visits: cleanText(String(metrics.goal_visits ?? ""), 100),
          },
          provenance: {
            source_kind: cleanText(String(provenance.source_kind ?? ""), 100),
            observed_at: cleanText(String(provenance.observed_at ?? ""), 100),
            attribution: cleanText(String(provenance.attribution ?? ""), 100),
            timezone: cleanText(String(provenance.timezone ?? ""), 100),
            dimensions: stringList(provenance.dimensions),
            filters: cleanText(String(provenance.filters ?? ""), 1_000),
            sampling: {
              metadata_complete: samplingMetadataComplete,
              sampled: sampling.sampled === true,
              contains_sensitive_data: sampling.contains_sensitive_data === true,
              sample_share: Number(sampling.sample_share ?? 1),
              sample_size: Number(sampling.sample_size ?? 0),
              sample_space: Number(sampling.sample_space ?? 0),
              data_lag: Number(sampling.data_lag ?? 0),
            },
          },
        }
      : null,
    competitor_observations: (Array.isArray(input.competitor_observations) ? input.competitor_observations : []).slice(0, 20).map((rawObservation) => {
      const observation = record(rawObservation);
      const locator = record(observation.locator);
      const policy = record(observation.policy);
      const scope = record(observation.scope);
      const claim = record(observation.claim);
      return {
        source_url: cleanText(String(observation.source_url ?? ""), 2_000),
        observed_at: cleanText(String(observation.observed_at ?? ""), 100),
        collected_via: cleanText(String(observation.collected_via ?? ""), 100),
        locator: {
          url: cleanText(String(locator.url ?? ""), 2_000),
          selector: cleanText(String(locator.selector ?? ""), 500),
        },
        policy: {
          policy_id: cleanText(String(policy.policy_id ?? ""), 100),
          version: cleanText(String(policy.version ?? ""), 100),
          policy_url: cleanText(String(policy.policy_url ?? ""), 2_000),
          access: cleanText(String(policy.access ?? ""), 100),
          allowed_hosts: stringList(policy.allowed_hosts),
        },
        scope: {
          host: cleanText(String(scope.host ?? ""), 255),
          pages_observed: Number(scope.pages_observed ?? 0),
          observation_scope: cleanText(String(scope.observation_scope ?? ""), 500),
        },
        claim: {
          subject: cleanText(String(claim.subject ?? ""), 500),
          predicate: cleanText(String(claim.predicate ?? ""), 200),
          value: artifactText(claim.value, 1_000),
        },
        raw_quote: artifactText(observation.raw_quote, 1_000),
        limitations: stringList(observation.limitations).map((item) => artifactText(item, 500)),
      };
    }),
  };
}

function observationIsFresh(value: unknown, nowValue: string) {
  const observed = Date.parse(String(value ?? ""));
  const current = Date.parse(nowValue);
  if (!Number.isFinite(observed) || !Number.isFinite(current)) return false;
  const age = current - observed;
  return age >= -60_000 && age <= P0_CONTEXT_PREFLIGHT_MAX_AGE_MS;
}

export function contextPreflightBlockers(context: P0Context, nowValue: string) {
  const direct = record(context.direct);
  const directBinding = record(direct.binding);
  const metrika = record(context.metrika);
  const metrikaBinding = record(metrika.binding);
  const goalBinding = record(metrika.goal_binding);
  const blockers: string[] = [];
  if (
    direct.ready !== true
    || direct.inventory_ready !== true
    || !Number.isFinite(Number(direct.campaigns_total))
    || !Number.isFinite(Number(direct.minimum_weekly_budget_rub))
  ) blockers.push("Direct API preflight недоступен или частичен");
  if (direct.authority !== "VERIFIED" || direct.access !== "YANDEX_DIRECT_API_V501") {
    blockers.push("Direct read authority не подтверждена официальным API");
  }
  if (
    !String(directBinding.expected_account ?? "")
    || directBinding.expected_account !== directBinding.api_account
    || directBinding.matched !== true
    || direct.account !== directBinding.api_account
  ) {
    blockers.push("Direct advertiser account binding не совпадает");
  }
  if (!observationIsFresh(direct.observed_at, nowValue)) blockers.push("Direct API preflight устарел");
  if (metrika.ready !== true) blockers.push("Metrika API preflight недоступен или частичен");
  if (metrika.authority !== "VERIFIED" || metrika.access !== "YANDEX_METRIKA_MANAGEMENT_AND_REPORTS_API") {
    blockers.push("Metrika read authority не подтверждена официальным API");
  }
  if (
    !String(metrikaBinding.expected_counter_id ?? "")
    || metrikaBinding.expected_counter_id !== metrikaBinding.api_counter_id
    || metrikaBinding.matched !== true
    || metrika.counter_id !== metrikaBinding.api_counter_id
  ) {
    blockers.push("Metrika counter binding не совпадает");
  }
  if (
    !String(goalBinding.expected_goal_id ?? "")
    || goalBinding.expected_goal_id !== goalBinding.api_goal_id
    || goalBinding.matched !== true
    || metrika.goal_id !== goalBinding.api_goal_id
  ) {
    blockers.push("Metrika goal binding не совпадает");
  }
  if (!observationIsFresh(metrika.observed_at, nowValue)) blockers.push("Metrika API preflight устарел");
  return [...new Set(blockers)];
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

function bestOfferEvidence(rows: Array<{ text: string; url: string }>) {
  return bestEvidence(rows, ["участ", "выстав", "стенд", "экспонент", "participant", "exhibitor", "exhibition", "booth"]);
}

function brandFromSite(site: SiteAnalysis) {
  return cleanText(site.title.split(/\s[|—–-]\s/)[0] || "", 200);
}

async function sha256(value: unknown) {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("");
}

function persistedContextFacts(site: SiteAnalysis, context: P0Context): P0ContextState["facts"] {
  const direct = record(context.direct);
  const metrika = record(context.metrika);
  const minimum = Number(direct.minimum_weekly_budget_rub);
  return {
    direct: {
      account: cleanText(String(direct.account ?? ""), 255),
      client_id: cleanText(String(direct.client_id ?? ""), 100),
      campaigns_total: Number(direct.campaigns_total ?? 0),
      minimum_weekly_budget_rub: Number.isFinite(minimum) ? minimum : null,
      observed_at: cleanText(String(direct.observed_at ?? ""), 100),
      source_kind: "YANDEX_DIRECT_API_V501",
    },
    metrika: {
      counter_id: cleanText(String(metrika.counter_id ?? ""), 100),
      goal_id: cleanText(String(metrika.goal_id ?? ""), 100),
      observed_at: cleanText(String(metrika.observed_at ?? ""), 100),
      source_kind: "YANDEX_METRIKA_MANAGEMENT_AND_REPORTS_API",
    },
    site: {
      url: site.url,
      title: cleanText(site.title, 500),
      pages_analyzed: site.pages.length,
      fetched_at: site.fetched_at,
      source_kind: "PUBLIC_FIRST_PARTY_HTTPS",
    },
  };
}

function providerMaterialFacts(context: P0Context) {
  const direct = record(context.direct);
  const metrika = record(context.metrika);
  return {
    direct: {
      account: String(direct.account ?? ""),
      client_id: String(direct.client_id ?? ""),
      campaigns_total: Number(direct.campaigns_total ?? 0),
      minimum_weekly_budget_rub: Number(direct.minimum_weekly_budget_rub),
    },
    metrika: {
      counter_id: String(metrika.counter_id ?? ""),
      goal_id: String(metrika.goal_id ?? ""),
    },
  };
}

function persistedProviderMaterialFacts(facts: P0ContextState["facts"]) {
  return {
    direct: {
      account: facts.direct.account,
      client_id: facts.direct.client_id,
      campaigns_total: facts.direct.campaigns_total,
      minimum_weekly_budget_rub: facts.direct.minimum_weekly_budget_rub,
    },
    metrika: {
      counter_id: facts.metrika.counter_id,
      goal_id: facts.metrika.goal_id,
    },
  };
}

async function contextMaterialFingerprint(site: SiteAnalysis, context: P0Context) {
  return sha256({
    providers: providerMaterialFacts(context),
    site: {
      url: site.url,
      title: cleanText(site.title, 500),
      description: cleanText(site.description, 1_000),
      headings: site.headings.map((item) => cleanText(item, 1_000)),
      forms_detected: site.forms_detected,
      pages: site.pages.map((page) => ({
        url: page.url,
        title: cleanText(page.title, 500),
        description: cleanText(page.description, 1_000),
        headings: page.headings.map((item) => cleanText(item, 1_000)),
        forms_detected: page.forms_detected,
        text_excerpt: cleanText(page.text_excerpt, 8_000),
      })),
    },
  });
}

function provisionalBusinessGoal(site: SiteAnalysis, proposedAt: string) {
  const rows = evidenceRows(site);
  const resultEvidence = bestEvidence(rows, [
    "оставьте заявку", "заявк", "стать участник", "particip", "submit", "register", "регистра", "купить", "заказать",
  ]);
  const quote = cleanText(resultEvidence?.text ?? site.description ?? site.text_excerpt, 240);
  let value = "Получать квалифицированные обращения через сайт";
  if (/участ|particip/iu.test(quote)) value = "Получать заявки на участие через сайт";
  else if (/регистра|register/iu.test(quote)) value = "Получать завершённые регистрации через сайт";
  else if (/купить|заказ|purchase|order/iu.test(quote)) value = "Получать заказы через сайт";
  return {
    value,
    rationale: quote ? `Основание: на сайте указано «${quote}».` : "Основание: на first-party сайте найдено целевое контактное действие.",
    proposed_at: proposedAt,
    source_url: resultEvidence?.url ?? site.url,
  };
}

function previousLineage(state: P0Document) {
  return {
    strategy_revision_id: state.strategy ? String(state.strategy.strategy_revision_id ?? "") || null : null,
    recommendation_set_id: state.recommendation_set?.recommendation_set_id ?? null,
    draft_revision_id: state.draft ? String(state.draft.draft_revision_id ?? "") || null : null,
    shortlist_revision_id: state.shortlist?.shortlist_revision_id ?? null,
    publish_fingerprint: state.draft ? String(state.draft.publish_fingerprint ?? "") || null : null,
  };
}

function invalidationRecord(state: P0Document, invalidatedAt: string): P0ContextState["last_material_change"] {
  return {
    affected_steps: ["campaign_strategy", "recommendation_set", "campaign_drafts", "shortlist", "confirmation"],
    invalidated_at: invalidatedAt,
    previous_lineage: previousLineage(state),
  };
}

function invalidateContextDownstream(state: P0Document) {
  state.strategy = null;
  state.recommendation_set = null;
  state.draft = null;
  state.shortlist = null;
  state.external_write_intent = null;
}

async function inferModel(site: SiteAnalysis, context: P0Context): Promise<BusinessModel> {
  const rows = evidenceRows(site);
  const productEvidence = bestOfferEvidence(rows);
  const brand = brandFromSite(site);
  const audienceEvidence = bestEvidence(rows, [
    "руководител", "заказчик", "инвестор", "покупател", "байер", "производител",
    "decision-maker", "buyer", "manufacturer",
  ]);
  const valueEvidence = bestEvidence(rows, [
    "найдите", "получите", "возможност", "привлеч", "инвестиц", "партнер",
    "find new", "opportunit", "connect",
  ]);
  const resultEvidence = bestEvidence(rows, [
    "заполните короткую форму", "менеджер свяж", "оставьте заявку", "стать участник",
    "become a participant", "submit an application", "register",
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
  const product = inferOffer(brand, productEvidence?.text ?? site.text_excerpt, qualified);
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
  return model;
}

function decodeDocument(row: P0StoredRow): Record<string, unknown> {
  let decoded: unknown;
  try {
    decoded = JSON.parse(row.value_json);
  } catch {
    fail("P0_STATE_INVALID", "Persisted P0 document содержит некорректный JSON.");
  }
  if (!decoded || typeof decoded !== "object" || Array.isArray(decoded)) {
    fail("P0_STATE_INVALID", "Persisted P0 document должен быть объектом.");
  }
  return decoded as Record<string, unknown>;
}

function lineageError(message: string): never {
  fail("P0_MIGRATION_LINEAGE_INVALID", `Persisted P0 document отклонён: ${message}`);
}

async function migrateDocument(raw: Record<string, unknown>, revision: number, updatedAt: string) {
  const version = raw.schema_version;
  if (version !== undefined && version !== P0_DOCUMENT_SCHEMA && version !== P0_LEGACY_DOCUMENT_SCHEMA) {
    fail("P0_DOCUMENT_SCHEMA_UNSUPPORTED", `Persisted P0 document использует неподдерживаемую схему ${String(version)}.`);
  }
  const state = raw as unknown as P0Document;
  let changed = version !== P0_DOCUMENT_SCHEMA;
  if (changed) state.schema_version = P0_DOCUMENT_SCHEMA;
  const legacyModel = record(state.business_model);
  if (!state.analytics_evidence_snapshot && legacyModel.analysis_evidence) {
    state.analytics_evidence_snapshot = legacyModel.analysis_evidence as AnalyticsEvidenceBundle;
    delete legacyModel.analysis_evidence;
    changed = true;
  }

  if (state.context_state) {
    if (state.context_state.schema_version !== P0_CONTEXT_SCHEMA) {
      fail("P0_CONTEXT_SCHEMA_UNSUPPORTED", "Persisted Context использует неподдерживаемую схему.");
    }
    if (!state.site_analysis || state.context_state.facts.site.url !== state.site_analysis.url) {
      lineageError("Context facts не связаны с first-party site analysis.");
    }
    if (state.context_state.status === "GOAL_CONFIRMED" && !state.context_state.business_goal_decision?.value) {
      lineageError("Context помечен подтверждённым без решения владельца по бизнес-цели.");
    }
  }
  if ((state.campaign || state.external_write_intent) && !state.draft) {
    lineageError("external write не связан с Campaign Draft.");
  }
  if (state.draft && (!state.strategy || !state.business_model)) {
    lineageError("Campaign Draft не связан с Campaign Strategy и моделью бизнеса.");
  }
  if (state.shortlist && !state.draft) {
    lineageError("shortlist не связан с Campaign Draft.");
  }
  if (state.recommendation_set && !state.strategy) {
    lineageError("Recommendation Set не связан с Campaign Strategy.");
  }
  if (state.strategy && !state.business_model) {
    lineageError("Campaign Strategy не связана с моделью бизнеса.");
  }

  for (const key of ["context_state", "site_analysis", "business_model", "analytics_evidence_snapshot", "strategy", "recommendation_set", "draft", "shortlist", "external_write_intent", "campaign"] as const) {
    if (!(key in state)) {
      state[key] = null as never;
      changed = true;
    }
  }
  if (state.analytics_evidence_snapshot && !await verifyAnalyticsEvidenceSnapshot(state.analytics_evidence_snapshot)) {
    lineageError("Analytics Evidence Snapshot hash verification failed.");
  }

  let modelChanged = false;
  let previousProduct = "";
  const model = state.business_model;
  const site = state.site_analysis;
  const productEvidence = model?.field_evidence?.product;
  if (model && site && productEvidence) {
    const supportingEvidence = bestOfferEvidence(evidenceRows(site));
    const brand = brandFromSite(site);
    const inferred = inferOffer(brand, supportingEvidence?.text ?? site.text_excerpt, model.qualified_result);
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
  if (modelChanged && model) state.analytics_evidence_snapshot = null;

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
        analyticsEvidence: state.analytics_evidence_snapshot as unknown as Record<string, unknown> | undefined,
        generatedAt: updatedAt,
      });
      changed = true;
    }
  }

  const draft = state.draft;
  if (draft && strategy && model) {
    let draftChanged = false;
    const baseline = state.recommendation_set?.drafts.find((item) => item.visibility === "VISIBLE");
    if (!baseline) lineageError("Campaign Draft не может быть восстановлен в Recommendation Set.");
    if (!draft.draft_id) {
      draft.draft_id = baseline.draft_id;
      draft.draft_revision_id = `${baseline.draft_id}-r${Math.max(1, revision)}`;
      draft.strategy_revision_id = strategy.strategy_revision_id;
      draft.capability_profile_id = state.recommendation_set?.capability_profile.profile_id;
      changed = true;
      draftChanged = true;
    }
    if (draft.strategy_revision_id !== strategy.strategy_revision_id) {
      lineageError("Campaign Draft ссылается на другую Campaign Strategy revision.");
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
    if (record(draft.publish_projection).schema_version !== "p0-direct-projection-v3" || previousProduct || draftChanged) {
      draft.publish_projection = buildPublishProjection(model as unknown as Record<string, unknown>, strategy, draft);
      changed = true;
    }
    const projection = draft.publish_projection as Record<string, unknown> | undefined;
    if (!projection) lineageError("Campaign Draft не содержит publish projection.");
    const publishFingerprint = await fingerprintDirectProjection(projection);
    if (draft.publish_fingerprint !== publishFingerprint) {
      draft.publish_fingerprint = publishFingerprint;
      changed = true;
    }
    const recommendationSet = state.recommendation_set;
    if (!recommendationSet) lineageError("Campaign Draft отсутствует в Recommendation Set.");
    const generatedIndex = recommendationSet.drafts.findIndex((item) => item.draft_id === draft.draft_id);
    if (generatedIndex < 0) lineageError("Campaign Draft отсутствует в текущем Recommendation Set.");
    if (recommendationSet.drafts[generatedIndex].draft_revision_id !== draft.draft_revision_id) {
      recommendationSet.drafts[generatedIndex] = {
        ...recommendationSet.drafts[generatedIndex],
        ...draft,
      } as typeof recommendationSet.drafts[number];
      changed = true;
    }
    if (!state.shortlist) {
      state.shortlist = {
        schema_version: "p0-shortlist-v1",
        shortlist_revision_id: `p0-shortlist-r${Math.max(1, revision)}`,
        strategy_revision_id: String(strategy.strategy_revision_id ?? ""),
        draft_revision_ids: [String(draft.draft_revision_id ?? "")],
        updated_at: updatedAt,
      };
      changed = true;
    }
    if (
      state.shortlist.strategy_revision_id !== strategy.strategy_revision_id
      || !state.shortlist.draft_revision_ids.includes(String(draft.draft_revision_id ?? ""))
    ) {
      lineageError("shortlist ссылается на другую Strategy или Draft revision.");
    }
  }

  if (state.external_write_intent && state.draft && strategy) {
    if (
      state.external_write_intent.strategy_revision_id !== strategy.strategy_revision_id
      || state.external_write_intent.draft_revision_id !== state.draft.draft_revision_id
      || state.external_write_intent.publish_fingerprint !== state.draft.publish_fingerprint
    ) {
      lineageError("external write intent ссылается на другую Strategy или Draft revision.");
    }
  }
  if (state.campaign) {
    if (!String(state.campaign.campaign_id ?? "").trim()) lineageError("external outcome не содержит Campaign ID.");
    if (!state.draft?.publish_fingerprint) lineageError("external outcome потерял publish fingerprint Campaign Draft.");
    if (!state.external_write_intent) {
      state.external_write_intent = {
        strategy_revision_id: String(state.strategy?.strategy_revision_id ?? ""),
        draft_revision_id: String(state.draft.draft_revision_id ?? ""),
        publish_fingerprint: String(state.draft.publish_fingerprint),
        confirmed_at: String(state.campaign.created_at ?? updatedAt),
      };
      if (!state.external_write_intent.strategy_revision_id || !state.external_write_intent.draft_revision_id) {
        lineageError("external outcome потерял Strategy или Draft revision.");
      }
      changed = true;
    }
  }
  return { state, changed };
}

function currentStep(state: P0Document) {
  if (state.draft?.publish_projection) return 4;
  if (state.strategy) return 3;
  if (state.business_model?.source === "REAL_SITE_RESEARCH_PLUS_OWNER_CONFIRMATION") return 2;
  if (state.business_model) return 1;
  return 0;
}

function allowedCommands(state: P0Document): CommandName[] {
  return (Object.keys(P0_COMMAND_TRUTH_TABLE) as CommandName[])
    .filter((command) => P0_COMMAND_TRUTH_TABLE[command](state));
}

function workflow(state: P0Document) {
  return {
    steps: WORKFLOW_STEPS,
    current_step: currentStep(state),
    maximum_reachable_step: currentStep(state),
    allowed_commands: allowedCommands(state),
    transition_contract: P0_APPLICATION_CONTRACT_VERSION,
  };
}

function contextChangePolicy() {
  return {
    affected_steps: [
      { id: "campaign_strategy", label: "Стратегия кампании" },
      { id: "recommendation_set", label: "Recommendation Set" },
      { id: "campaign_drafts", label: "Campaign Drafts" },
      { id: "shortlist", label: "shortlist" },
      { id: "confirmation", label: "Подтверждение" },
    ],
    normalization_only_changes_invalidate: false,
    confirmation_requires_recomputation: true,
  };
}

function contractMetadata(operation: "query" | "command") {
  return {
    name: P0_APPLICATION_CONTRACT,
    version: P0_APPLICATION_CONTRACT_VERSION,
    operation,
    document_schema: P0_DOCUMENT_SCHEMA,
  };
}

export class P0Application {
  private readonly store: P0ApplicationStore;
  private readonly adapters: P0ApplicationAdapters;

  constructor({ store, adapters }: { store: P0ApplicationStore; adapters: P0ApplicationAdapters }) {
    this.store = store;
    this.adapters = adapters;
  }

  private async load(key: string): Promise<LoadedDocument> {
    for (let attempt = 0; attempt < 4; attempt += 1) {
      let row = await this.store.load(key);
      if (!row) {
        const timestamp = this.adapters.now();
        const initial: P0StoredRow = {
          revision: 0,
          updated_at: timestamp,
          value_json: JSON.stringify(emptyDocument()),
        };
        await this.store.initialize(key, initial);
        row = await this.store.load(key);
      }
      if (!row) fail("P0_STATE_MISSING", "Persisted P0 document не инициализирован.");
      if (!Number.isSafeInteger(row.revision) || row.revision < 0) {
        fail("P0_STATE_INVALID", "Persisted P0 document содержит некорректную revision.");
      }
      const migrated = await migrateDocument(structuredClone(decodeDocument(row)), row.revision, row.updated_at);
      if (!migrated.changed) {
        return { revision: row.revision, updated_at: row.updated_at, state: migrated.state };
      }
      const timestamp = this.adapters.now();
      const next: P0StoredRow = {
        revision: row.revision + 1,
        updated_at: timestamp,
        value_json: JSON.stringify(migrated.state),
      };
      if (await this.store.compareAndSwap(key, row.revision, next)) {
        return { revision: next.revision, updated_at: next.updated_at, state: migrated.state };
      }
    }
    fail("P0_REVISION_CONFLICT", "P0 изменился в другой вкладке. Обновите страницу.");
  }

  private async history(key: string, currentRevision: number): Promise<P0RevisionSummary[]> {
    const rows = await this.store.history(key, 50);
    return rows.slice(0, 50).map((row) => summarizeP0Revision(row, currentRevision));
  }

  private async buildModelEvidence(site: SiteAnalysis, model: BusinessModel, context: P0Context, generatedAt: string) {
    const marketEvidenceInput: MarketEvidenceInput | undefined = await this.adapters.readMarketEvidence?.({
      model,
      context,
      generatedAt,
    });
    return buildAnalyticsEvidence({
      site: site as unknown as Record<string, unknown>,
      model: model as unknown as Record<string, unknown>,
      context: {
        ...context as unknown as Record<string, unknown>,
        ...(marketEvidenceInput ? { market_evidence_input: marketEvidenceInput } : {}),
      },
      generatedAt,
    });
  }

  private assertContextPreflight(context: P0Context, timestamp: string) {
    const blockers = contextPreflightBlockers(context, timestamp);
    if (blockers.length) fail("P0_CONTEXT_PREFLIGHT_BLOCKED", blockers[0]);
  }

  private assertPersistedBindings(state: P0Document, context: P0Context) {
    if (!state.context_state) return;
    if (JSON.stringify(persistedProviderMaterialFacts(state.context_state.facts)) !== JSON.stringify(providerMaterialFacts(context))) {
      fail("P0_CONTEXT_PREFLIGHT_CHANGED", "Подключения или исходные Context facts изменились. Повторите шаг «Контекст».");
    }
  }

  private writeReadiness(state: P0Document, context: P0Context, timestamp: string) {
    const configuration = this.adapters.externalWriteConfiguration();
    const blockers = [...configuration.blockers, ...contextPreflightBlockers(context, timestamp)];
    if (!configuration.ready && blockers.length === 0) blockers.push("Direct production credentials не настроены");
    if (context.direct.ready !== true) blockers.push("Текущий аккаунт Директа не прошёл production preflight");
    if (state.context_state?.status !== "GOAL_CONFIRMED") blockers.push("Provisional бизнес-цель ещё не подтверждена владельцем");
    if (
      state.context_state
      && String(context.direct.account ?? "") !== state.context_state.facts.direct.account
    ) blockers.push("Текущий Direct account не совпадает с сохранённым Context binding");
    if (configuration.account && state.context_state && configuration.account !== state.context_state.facts.direct.account) {
      blockers.push("Direct write account не совпадает с подтверждённым Context binding");
    }
    const minimumBudget = Number(context.direct.minimum_weekly_budget_rub);
    if (Number.isFinite(minimumBudget) && state.strategy) {
      try {
        validateWeeklyBudgetRub(state.strategy.weekly_budget_rub, minimumBudget);
      } catch (error) {
        blockers.push(errorMessage(error));
      }
    }
    if (!state.draft?.publish_projection) blockers.push("Campaign Draft ещё не зафиксирован");
    if (!state.shortlist?.draft_revision_ids.includes(String(state.draft?.draft_revision_id ?? ""))) {
      blockers.push("shortlist требует пересчёта после Context change");
    }
    blockers.push(...campaignDraftPublishBlockers(state.draft));
    if (state.campaign) blockers.push("Кампания по этой ревизии уже создана");
    return { ready: blockers.length === 0, blockers };
  }

  async query(key: string) {
    const [stored, rawContext] = await Promise.all([this.load(key), this.adapters.readContext()]);
    const context = sanitizeContext(rawContext);
    const timestamp = this.adapters.now();
    const viewState = structuredClone(stored.state);
    return {
      contract: contractMetadata("query"),
      module: "P0_PRODUCTION",
      environment: "PRODUCTION",
      test_scenario: false,
      ...stored,
      state: viewState,
      workflow: workflow(viewState),
      context,
      context_preflight: {
        ready: contextPreflightBlockers(context, timestamp).length === 0,
        blockers: contextPreflightBlockers(context, timestamp),
        maximum_age_ms: P0_CONTEXT_PREFLIGHT_MAX_AGE_MS,
      },
      context_change_policy: contextChangePolicy(),
      revision_history: await this.history(key, stored.revision),
      write_readiness: this.writeReadiness(viewState, context, timestamp),
    };
  }

  async command(key: string, payload: P0Command) {
    if (
      typeof payload.expected_revision !== "number"
      || !Number.isSafeInteger(payload.expected_revision)
      || payload.expected_revision < 0
    ) {
      fail("P0_REVISION_REQUIRED", "Для изменения нужна текущая ревизия.");
    }
    const action = String(payload.action ?? "") as CommandName;
    if (!(action in P0_COMMAND_TRUTH_TABLE)) {
      fail("P0_ACTION_INVALID", "Действие не поддерживается production-модулем.");
    }
    const current = await this.load(key);
    if (current.revision !== payload.expected_revision) {
      fail("P0_REVISION_CONFLICT", "P0 изменился в другой вкладке. Обновите страницу.");
    }
    if (!allowedCommands(current.state).includes(action)) {
      fail("P0_TRANSITION_INVALID", "Действие недоступно для текущего состояния P0.");
    }
    const state = structuredClone(current.state);
    let persistedRevision = current.revision;

    if (action === "analyze_site") {
      const timestamp = this.adapters.now();
      const context = sanitizeContext(await this.adapters.readContext());
      this.assertContextPreflight(context, timestamp);
      const requestedUrl = normalizePublicHttpsUrl(String(payload.url ?? "")).toString();
      const site = sanitizeSiteAnalysis(await this.adapters.researchSite(requestedUrl));
      const fingerprint = await contextMaterialFingerprint(site, context);
      const previousContext = state.context_state;
      const normalizationOnly = previousContext?.material_fingerprint === fingerprint;
      if (normalizationOnly && previousContext) {
        // Keep the exact persisted evidence/provenance; a technical re-entry only advances document revision.
      } else {
        state.site_analysis = site;
        const hasPreviousContext = Boolean(previousContext || state.business_model || state.strategy || state.draft || state.shortlist);
        const lastMaterialChange = hasPreviousContext ? invalidationRecord(state, timestamp) : null;
        state.context_state = {
          schema_version: P0_CONTEXT_SCHEMA,
          status: "GOAL_PROVISIONAL",
          facts: persistedContextFacts(site, context),
          provisional_business_goal: provisionalBusinessGoal(site, timestamp),
          business_goal_decision: null,
          material_fingerprint: fingerprint,
          last_material_change: lastMaterialChange,
        };
        state.business_model = null;
        state.analytics_evidence_snapshot = null;
        invalidateContextDownstream(state);
      }
    } else if (action === "confirm_context_goal") {
      if (payload.confirmation !== "CONFIRM_CONTEXT_GOAL") {
        fail("P0_CONTEXT_GOAL_CONFIRMATION_REQUIRED", "Нужно явно подтвердить или исправить provisional бизнес-цель.");
      }
      if (!state.context_state || !state.site_analysis) {
        fail("P0_PREREQUISITE_MISSING", "Сначала проверьте Context и исследуйте first-party сайт.");
      }
      const timestamp = this.adapters.now();
      const context = sanitizeContext(await this.adapters.readContext());
      this.assertContextPreflight(context, timestamp);
      this.assertPersistedBindings(state, context);
      const goal = requiredInput(payload.goal, "Бизнес-цель", 500);
      const previousDecision = state.context_state.business_goal_decision;
      const changedConfirmedGoal = Boolean(previousDecision && previousDecision.value !== goal);
      if (changedConfirmedGoal) {
        state.context_state.last_material_change = invalidationRecord(state, timestamp);
        invalidateContextDownstream(state);
      }
      const provisionalValue = state.context_state.provisional_business_goal.value;
      state.context_state = {
        ...state.context_state,
        status: "GOAL_CONFIRMED",
        facts: persistedContextFacts(state.site_analysis, context),
        business_goal_decision: {
          value: goal,
          provisional_value: provisionalValue,
          decision: goal === provisionalValue ? "CONFIRMED" : "CORRECTED",
          decided_at: timestamp,
          owner_confirmed: true,
        },
      };
      if (!state.business_model) {
        state.business_model = await inferModel(state.site_analysis, context);
        state.analytics_evidence_snapshot = await this.buildModelEvidence(
          state.site_analysis,
          state.business_model,
          context,
          timestamp,
        );
      }
    } else if (action === "save_business_model") {
      if (!state.business_model) fail("P0_PREREQUISITE_MISSING", "Сначала исследуйте сайт.");
      const value = record(payload.value);
      const ownerConfirmedAt = this.adapters.now();
      for (const field of ["product", "audience", "value", "qualified_result", "exclusions"]) {
        const confirmedValue = artifactText(value[field], 1_000);
        if (!confirmedValue) fail("P0_INPUT_REQUIRED", `Поле ${field} требует подтверждённого значения.`);
        (state.business_model as unknown as Record<string, unknown>)[field] = confirmedValue;
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
      if (!state.site_analysis) fail("P0_EVIDENCE_LINEAGE_INVALID", "Evidence snapshot потерял first-party site analysis.");
      const context = sanitizeContext(await this.adapters.readContext());
      this.assertContextPreflight(context, ownerConfirmedAt);
      this.assertPersistedBindings(state, context);
      state.analytics_evidence_snapshot = await this.buildModelEvidence(
        state.site_analysis,
        state.business_model,
        context,
        ownerConfirmedAt,
      );
      state.strategy = null;
      state.recommendation_set = null;
      state.draft = null;
      state.shortlist = null;
    } else if (action === "save_strategy") {
      if (!state.business_model) fail("P0_PREREQUISITE_MISSING", "Сначала подтвердите модель бизнеса.");
      const value = record(payload.value);
      const confirmedContextGoal = state.context_state?.business_goal_decision?.value;
      if (confirmedContextGoal && cleanText(String(value.goal ?? ""), 500) !== confirmedContextGoal) {
        fail("P0_CONTEXT_GOAL_CHANGED", "Измените бизнес-цель на шаге «Контекст», чтобы показать и применить каскад invalidation.");
      }
      const required = ["goal", "geography", "period_start", "period_end", "landing_page", "weekly_budget_rub", "target_cpa_rub", "message"];
      if (required.some((field) => String(value[field] ?? "").trim() === "")) {
        fail("P0_STRATEGY_INVALID", "Критические решения Campaign Strategy заполнены не полностью.");
      }
      const landing = normalizePublicHttpsUrl(String(value.landing_page));
      const limits = await this.adapters.readCurrencyLimits();
      validateWeeklyBudgetRub(value.weekly_budget_rub, limits.minimum_weekly_budget_rub);
      const approvedAt = this.adapters.now();
      state.strategy = {
        ...value,
        landing_page: landing.toString(),
        source: "OWNER_APPROVED_REAL_BUSINESS_INPUT",
        strategy_revision_id: `campaign-strategy-r${current.revision + 1}`,
        approved_at: approvedAt,
      };
      state.recommendation_set = await buildCampaignRecommendationSet({
        model: state.business_model as unknown as Record<string, unknown>,
        strategy: state.strategy,
        analyticsEvidence: state.analytics_evidence_snapshot as unknown as Record<string, unknown> | undefined,
        generatedAt: approvedAt,
      });
      state.draft = null;
      state.shortlist = null;
    } else if (action === "save_draft") {
      const value = record(payload.value);
      if (!state.strategy || !state.business_model) {
        fail("P0_PREREQUISITE_MISSING", "Сначала подтвердите модель и Strategy.");
      }
      const draftId = requiredInput(value.draft_id, "Campaign Draft", 255);
      const recommendationSet = state.recommendation_set;
      const generated = recommendationSet?.drafts.find((item) => item.draft_id === draftId);
      if (!recommendationSet || !generated || generated.visibility !== "VISIBLE") {
        fail("P0_DRAFT_INVALID", "Выбранный Campaign Draft не принадлежит текущей Strategy revision.");
      }
      const normalized: Record<string, unknown> = {
        campaign_name: requiredInput(value.campaign_name, "Название кампании", 255),
        group_name: requiredInput(value.group_name, "Название группы", 255),
        keyword: requiredInput(value.keyword, "Ключевая фраза", 4_096),
        negative_keywords: requiredInput(value.negative_keywords, "Минус-фразы", 1_000),
        ad_title: requiredInput(value.ad_title, "Заголовок объявления", 56),
        ad_text: requiredInput(value.ad_text, "Текст объявления", 81),
        draft_id: draftId,
        draft_revision_id: `${draftId}-r${current.revision + 1}`,
        strategy_revision_id: state.strategy.strategy_revision_id,
        capability_profile_id: recommendationSet.capability_profile.profile_id,
      };
      const projection = buildPublishProjection(
        state.business_model as unknown as Record<string, unknown>,
        state.strategy,
        normalized,
      ) as unknown as Record<string, unknown>;
      const editableFields = ["campaign_name", "group_name", "keyword", "negative_keywords", "ad_title", "ad_text"] as const;
      const changedPointers = editableFields
        .filter((field) => String(generated[field] ?? "") !== String(normalized[field] ?? ""))
        .map((field) => `/draft/${field}`);
      const scoreEvidence = state.analytics_evidence_snapshot;
      if (!scoreEvidence) {
        fail("P0_EVIDENCE_LINEAGE_INVALID", "Scoring требует persisted Analytics Evidence Snapshot из Model revision.");
      }
      const editedAt = this.adapters.now();
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
      if (!currentDraft) fail("P0_DRAFT_INVALID", "Пересчёт Campaign Draft не вернул выбранную ревизию.");
      state.draft = {
        ...currentDraft,
        score_delta: explainScoreDelta(generated.viability_score, currentDraft.viability_score, changedPointers),
      };
      recommendationSet.drafts = rescored.map((item) => item.draft_id === draftId ? state.draft as typeof item : item);
      state.shortlist = {
        schema_version: "p0-shortlist-v1",
        shortlist_revision_id: `p0-shortlist-r${current.revision + 1}`,
        strategy_revision_id: String(state.strategy.strategy_revision_id ?? ""),
        draft_revision_ids: [String(state.draft.draft_revision_id ?? "")],
        updated_at: editedAt,
      };
    } else if (action === "confirm_creation") {
      if (payload.confirmation !== "CREATE_NON_SERVING_CAMPAIGN") {
        fail("P0_CONFIRMATION_REQUIRED", "Нужно точное подтверждение создания реальной кампании с выключенными показами.");
      }
      const preflightAt = this.adapters.now();
      const preflightContext = sanitizeContext(await this.adapters.readContext());
      this.assertContextPreflight(preflightContext, preflightAt);
      this.assertPersistedBindings(state, preflightContext);
      if (state.campaign) fail("P0_EXTERNAL_OUTCOME_EXISTS", "Кампания по этой ревизии уже создана.");
      const projection = state.draft?.publish_projection as DirectProjection | undefined;
      if (!projection) fail("P0_DRAFT_MISSING", "Campaign Draft не готов к созданию.");
      const publishBlockers = campaignDraftPublishBlockers(state.draft);
      if (publishBlockers.length) fail("P0_PUBLISH_BLOCKED", publishBlockers[0]);
      const configuration = this.adapters.externalWriteConfiguration();
      if (!configuration.ready) {
        fail("P0_WRITE_NOT_READY", configuration.blockers[0] ?? "Direct production credentials не настроены.");
      }
      if (state.context_state && configuration.account !== state.context_state.facts.direct.account) {
        fail("P0_CONTEXT_ACCOUNT_MISMATCH", "Direct write account не совпадает с подтверждённым Context binding.");
      }
      if (!state.external_write_intent) {
        const strategyRevisionId = String(state.strategy?.strategy_revision_id ?? "");
        const draftRevisionId = String(state.draft?.draft_revision_id ?? "");
        const publishFingerprint = String(state.draft?.publish_fingerprint ?? "");
        if (!strategyRevisionId || !draftRevisionId || !publishFingerprint) {
          fail("P0_EXTERNAL_LINEAGE_INVALID", "External write требует Strategy, Draft revision и publish fingerprint.");
        }
        state.external_write_intent = {
          strategy_revision_id: strategyRevisionId,
          draft_revision_id: draftRevisionId,
          publish_fingerprint: publishFingerprint,
          confirmed_at: this.adapters.now(),
        };
        const intentRow: P0StoredRow = {
          revision: persistedRevision + 1,
          updated_at: state.external_write_intent.confirmed_at,
          value_json: JSON.stringify(state),
        };
        if (!await this.store.compareAndSwap(key, persistedRevision, intentRow)) {
          fail("P0_REVISION_CONFLICT", "P0 изменился в другой вкладке. Обновите страницу.");
        }
        persistedRevision = intentRow.revision;
      }
      state.campaign = {
        source: "YANDEX_DIRECT_API",
        created_at: this.adapters.now(),
        ...await this.adapters.createExternalOutcome({ key, state, projection }),
      };
    } else if (action === "reset") {
      Object.assign(state, emptyDocument());
    }

    const timestamp = this.adapters.now();
    const next: P0StoredRow = {
      revision: persistedRevision + 1,
      updated_at: timestamp,
      value_json: JSON.stringify(state),
    };
    if (!await this.store.compareAndSwap(key, persistedRevision, next)) {
      fail("P0_REVISION_CONFLICT", "P0 изменился в другой вкладке. Обновите страницу.");
    }
    const context = sanitizeContext(await this.adapters.readContext());
    const responseAt = this.adapters.now();
    return {
      contract: contractMetadata("command"),
      module: "P0_PRODUCTION",
      environment: "PRODUCTION",
      test_scenario: false,
      revision: next.revision,
      updated_at: next.updated_at,
      state,
      workflow: workflow(state),
      context,
      context_preflight: {
        ready: contextPreflightBlockers(context, responseAt).length === 0,
        blockers: contextPreflightBlockers(context, responseAt),
        maximum_age_ms: P0_CONTEXT_PREFLIGHT_MAX_AGE_MS,
      },
      context_change_policy: contextChangePolicy(),
      revision_history: await this.history(key, next.revision),
      write_readiness: this.writeReadiness(state, context, responseAt),
    };
  }
}
