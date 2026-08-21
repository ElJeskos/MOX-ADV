import { buildAdTitle } from "./ad-copy.ts";
import {
  buildAnalyticsEvidence,
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

export const P0_APPLICATION_CONTRACT = "mox-adv.p0.application";
export const P0_APPLICATION_CONTRACT_VERSION = "1.0.0";
export const P0_DOCUMENT_SCHEMA = "p0-application-document-v1";

export type P0Document = {
  schema_version: typeof P0_DOCUMENT_SCHEMA;
  site_analysis: SiteAnalysis | null;
  business_model: BusinessModel | null;
  strategy: Record<string, unknown> | null;
  recommendation_set: CampaignRecommendationSet | null;
  draft: Record<string, unknown> | null;
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
  analysis_evidence?: AnalyticsEvidenceBundle;
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
  confirm_creation: (state: P0Document) => Boolean(state.draft?.publish_projection && !state.campaign),
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
    site_analysis: null,
    business_model: null,
    strategy: null,
    recommendation_set: null,
    draft: null,
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
  const text = cleanText(String(value ?? ""), 10_000);
  if (!text) fail("P0_INPUT_REQUIRED", `${label} не заполнено.`);
  if (text.length > maximum) fail("P0_INPUT_TOO_LONG", `${label}: максимум ${maximum} символов.`);
  return text;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Неизвестная ошибка";
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
  model.analysis_evidence = await buildAnalyticsEvidence({
    site: site as unknown as Record<string, unknown>,
    model: model as unknown as Record<string, unknown>,
    context: context as unknown as Record<string, unknown>,
  });
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
  if (version !== undefined && version !== P0_DOCUMENT_SCHEMA) {
    fail("P0_DOCUMENT_SCHEMA_UNSUPPORTED", `Persisted P0 document использует неподдерживаемую схему ${String(version)}.`);
  }
  const state = raw as unknown as P0Document;
  let changed = version !== P0_DOCUMENT_SCHEMA;
  if (changed) state.schema_version = P0_DOCUMENT_SCHEMA;

  if ((state.campaign || state.external_write_intent) && !state.draft) {
    lineageError("external write не связан с Campaign Draft.");
  }
  if (state.draft && (!state.strategy || !state.business_model)) {
    lineageError("Campaign Draft не связан с Campaign Strategy и моделью бизнеса.");
  }
  if (state.recommendation_set && !state.strategy) {
    lineageError("Recommendation Set не связан с Campaign Strategy.");
  }
  if (state.strategy && !state.business_model) {
    lineageError("Campaign Strategy не связана с моделью бизнеса.");
  }

  for (const key of ["site_analysis", "business_model", "strategy", "recommendation_set", "draft", "external_write_intent", "campaign"] as const) {
    if (!(key in state)) {
      state[key] = null as never;
      changed = true;
    }
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
  if (modelChanged && model) delete model.analysis_evidence;

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
  if (state.site_analysis) return 1;
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

  private writeReadiness(state: P0Document, context: P0Context) {
    const configuration = this.adapters.externalWriteConfiguration();
    const blockers = [...configuration.blockers];
    if (!configuration.ready && blockers.length === 0) blockers.push("Direct production credentials не настроены");
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

  async query(key: string) {
    const [stored, context] = await Promise.all([this.load(key), this.adapters.readContext()]);
    const analysisEvidence = stored.state.business_model?.analysis_evidence ?? null;
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
      analysis_evidence: analysisEvidence,
      revision_history: await this.history(key, stored.revision),
      write_readiness: this.writeReadiness(viewState, context),
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
      const site = await this.adapters.researchSite(String(payload.url ?? ""));
      const context = await this.adapters.readContext();
      state.site_analysis = site;
      state.business_model = await inferModel(site, context);
      state.strategy = null;
      state.recommendation_set = null;
      state.draft = null;
    } else if (action === "save_business_model") {
      if (!state.business_model) fail("P0_PREREQUISITE_MISSING", "Сначала исследуйте сайт.");
      const value = record(payload.value);
      const ownerConfirmedAt = this.adapters.now();
      for (const field of ["product", "audience", "value", "qualified_result", "exclusions"]) {
        const text = cleanText(String(value[field] ?? ""), 1_000);
        if (!text) fail("P0_INPUT_REQUIRED", `Поле ${field} требует подтверждённого значения.`);
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
      if (!state.site_analysis) fail("P0_EVIDENCE_LINEAGE_INVALID", "Evidence snapshot потерял first-party site analysis.");
      const context = await this.adapters.readContext();
      state.business_model.analysis_evidence = await buildAnalyticsEvidence({
        site: state.site_analysis as unknown as Record<string, unknown>,
        model: state.business_model as unknown as Record<string, unknown>,
        context: context as unknown as Record<string, unknown>,
      });
      state.strategy = null;
      state.recommendation_set = null;
      state.draft = null;
    } else if (action === "save_strategy") {
      if (!state.business_model) fail("P0_PREREQUISITE_MISSING", "Сначала подтвердите модель бизнеса.");
      const value = record(payload.value);
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
        analyticsEvidence: state.business_model.analysis_evidence as unknown as Record<string, unknown> | undefined,
        generatedAt: approvedAt,
      });
      state.draft = null;
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
      let scoreEvidence = state.business_model.analysis_evidence;
      if (!scoreEvidence) {
        if (!state.site_analysis) fail("P0_EVIDENCE_LINEAGE_INVALID", "Scoring требует first-party Analytics Evidence Snapshot.");
        const scoringContext = await this.adapters.readContext();
        scoreEvidence = await buildAnalyticsEvidence({
          site: state.site_analysis as unknown as Record<string, unknown>,
          model: state.business_model as unknown as Record<string, unknown>,
          context: scoringContext as unknown as Record<string, unknown>,
        });
        state.business_model.analysis_evidence = scoreEvidence;
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
    } else if (action === "confirm_creation") {
      if (payload.confirmation !== "CREATE_NON_SERVING_CAMPAIGN") {
        fail("P0_CONFIRMATION_REQUIRED", "Нужно точное подтверждение создания реальной кампании с выключенными показами.");
      }
      if (state.campaign) fail("P0_EXTERNAL_OUTCOME_EXISTS", "Кампания по этой ревизии уже создана.");
      const projection = state.draft?.publish_projection as DirectProjection | undefined;
      if (!projection) fail("P0_DRAFT_MISSING", "Campaign Draft не готов к созданию.");
      const publishBlockers = campaignDraftPublishBlockers(state.draft);
      if (publishBlockers.length) fail("P0_PUBLISH_BLOCKED", publishBlockers[0]);
      const configuration = this.adapters.externalWriteConfiguration();
      if (!configuration.ready) {
        fail("P0_WRITE_NOT_READY", configuration.blockers[0] ?? "Direct production credentials не настроены.");
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
    const context = await this.adapters.readContext();
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
      analysis_evidence: state.business_model?.analysis_evidence ?? null,
      revision_history: await this.history(key, next.revision),
      write_readiness: this.writeReadiness(state, context),
    };
  }
}
