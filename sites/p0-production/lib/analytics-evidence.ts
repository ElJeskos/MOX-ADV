export const ANALYTICS_EVIDENCE_SCHEMA = "p0-analytics-evidence-v1";

export type EvidenceSourceStatus = "VERIFIED" | "PARTIAL" | "UNAVAILABLE";

export type EvidenceSource = {
  source_id: string;
  title: string;
  source_kind: string;
  status: EvidenceSourceStatus;
  observed_at: string | null;
  facts: string[];
  limitations: string[];
  evidence_ids: string[];
};

export type ConfidenceVector = {
  source_quality: "PRIMARY_ONLY";
  freshness: "CURRENT" | "MIXED" | "UNKNOWN";
  consistency: "SINGLE_SOURCE" | "CORROBORATED" | "NOT_EVALUATED";
  coverage: "COMPLETE_FOR_SCOPE" | "PARTIAL" | "UNKNOWN";
  uncertainty: string[];
};

export type EvidenceRecord = {
  evidence_id: string;
  claim_links: Array<{ claim_id: string; relation: "supports" }>;
  source_kind: string;
  source_locator: Record<string, string>;
  observed_at: string | null;
  extraction: { method: string; version: string };
  raw: { quote?: string; value?: unknown; sha256: string };
  normalized: Record<string, unknown>;
};

export type EvidenceClaim = {
  claim_id: string;
  subject: string;
  predicate: string;
  value: unknown;
  evidence_ids: string[];
  confidence: {
    source_quality: "A" | "B" | "U";
    freshness: "current" | "unknown";
    consistency: "single" | "corroborated" | "not_evaluated";
    coverage: "complete_for_scope" | "partial" | "unknown";
    tier: "TIER_1_VERIFIED" | "TIER_3_INDICATIVE" | "BLOCKED_UNKNOWN";
  };
};

export type AnalyticsEvidenceBundle = {
  schema_version: typeof ANALYTICS_EVIDENCE_SCHEMA;
  snapshot_id: string;
  as_of: string;
  recommendation_status: "EVIDENCE_READY_WITH_GAPS" | "BLOCKED_UNKNOWN";
  summary: {
    sources_total: number;
    sources_verified: number;
    sources_partial: number;
    sources_unavailable: number;
    claims_supported: number;
    hard_blockers: string[];
  };
  confidence: ConfidenceVector;
  sources: EvidenceSource[];
  claims: EvidenceClaim[];
  evidence: EvidenceRecord[];
  material_uncertainties: string[];
  prelaunch_cost: {
    status: "UNAVAILABLE" | "HISTORICAL_FIRST_PARTY";
    reason: string;
  };
  contract_path: string;
};

type AnalyticsEvidenceInput = {
  site: Record<string, unknown>;
  model: Record<string, unknown>;
  context: Record<string, unknown>;
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function number(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => left.localeCompare(right));
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

async function digest(value: unknown) {
  const bytes = new TextEncoder().encode(canonical(value));
  const hash = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(hash)].map((item) => item.toString(16).padStart(2, "0")).join("");
}

function latestTimestamp(values: Array<string | null>) {
  const valid = values.filter((value): value is string => Boolean(value && !Number.isNaN(Date.parse(value))));
  return valid.sort().at(-1) ?? null;
}

function freshness(observedAt: string | null, asOf: string) {
  if (!observedAt || Number.isNaN(Date.parse(observedAt))) return "UNKNOWN" as const;
  const age = Math.max(0, Date.parse(asOf) - Date.parse(observedAt));
  return age <= 3 * 24 * 60 * 60 * 1_000 ? "CURRENT" as const : "MIXED" as const;
}

async function evidenceId(seed: unknown) {
  return `urn:mox:evidence:${(await digest(seed)).slice(0, 24)}`;
}

async function claimId(seed: unknown) {
  return `urn:mox:claim:${(await digest(seed)).slice(0, 24)}`;
}

export async function buildAnalyticsEvidence({
  site,
  model,
  context,
}: AnalyticsEvidenceInput): Promise<AnalyticsEvidenceBundle> {
  const siteResearch = record(site.research);
  const direct = record(context.direct);
  const metrika = record(context.metrika);
  const performance = record(context.performance);
  const campaignCatalog = record(context.campaign_catalog);
  const fieldEvidence = record(model.field_evidence);
  const missingQuestions = list(model.missing_questions).map(text).filter(Boolean);
  const pages = list(site.pages);
  const directObservedAt = text(direct.observed_at) || null;
  const performanceProvenance = record(performance.provenance);
  const metrikaObservedAt = text(performanceProvenance.observed_at) || text(metrika.observed_at) || null;
  const siteObservedAt = text(site.fetched_at) || null;
  const ownerObservedAts = Object.values(fieldEvidence)
    .map((item) => text(record(item).owner_confirmed_at) || null);
  const firstPartyObservedAt = latestTimestamp([siteObservedAt, ...ownerObservedAts]);
  const asOf = latestTimestamp([
    firstPartyObservedAt,
    directObservedAt,
    metrikaObservedAt,
  ]) ?? new Date(0).toISOString();

  const evidence: EvidenceRecord[] = [];
  const claims: EvidenceClaim[] = [];
  const firstPartyEvidenceIds: string[] = [];

  for (const [field, rawItem] of Object.entries(fieldEvidence).sort(([left], [right]) => left.localeCompare(right))) {
    const item = record(rawItem);
    const quote = text(item.quote);
    const sourceUrl = text(item.source_url);
    const ownerConfirmed = item.owner_confirmed === true || text(item.confidence) === "OWNER_CONFIRMED";
    const ownerConfirmedAt = text(item.owner_confirmed_at) || null;
    const modelValue = model[field] ?? "";
    const webEvidenceId = quote && sourceUrl
      ? await evidenceId({ source: "first_party_web", field, quote, sourceUrl, observed_at: siteObservedAt })
      : null;
    const ownerEvidenceId = ownerConfirmed
      ? await evidenceId({ source: "owner_confirmation", field, modelValue, observed_at: ownerConfirmedAt })
      : null;
    const evidenceIds = [webEvidenceId, ownerEvidenceId].filter((value): value is string => Boolean(value));
    if (evidenceIds.length === 0) continue;

    const cid = await claimId({ field, modelValue, evidence_ids: evidenceIds });
    if (webEvidenceId) {
      evidence.push({
        evidence_id: webEvidenceId,
        claim_links: [{ claim_id: cid, relation: "supports" }],
        source_kind: "first_party_web",
        source_locator: { url: sourceUrl, field },
        observed_at: siteObservedAt,
        extraction: { method: "evidence_span", version: "p0-site-research-v3" },
        raw: { quote, sha256: `sha256:${await digest(quote)}` },
        normalized: { value: modelValue, datatype: "string", language: "ru" },
      });
    }
    if (ownerEvidenceId) {
      evidence.push({
        evidence_id: ownerEvidenceId,
        claim_links: [{ claim_id: cid, relation: "supports" }],
        source_kind: "owner_confirmation",
        source_locator: { state_path: `business_model.${field}`, field },
        observed_at: ownerConfirmedAt,
        extraction: { method: "owner_confirmation", version: "p0-owner-confirmation-v1" },
        raw: { value: modelValue, sha256: `sha256:${await digest(modelValue)}` },
        normalized: { value: modelValue, datatype: "string", language: "ru" },
      });
    }
    firstPartyEvidenceIds.push(...evidenceIds);
    claims.push({
      claim_id: cid,
      subject: "business_model",
      predicate: field,
      value: modelValue,
      evidence_ids: evidenceIds,
      confidence: {
        source_quality: ownerConfirmed ? "A" : "B",
        freshness: freshness(ownerConfirmed ? ownerConfirmedAt : siteObservedAt, asOf) === "CURRENT"
          ? "current"
          : "unknown",
        consistency: evidenceIds.length > 1 ? "corroborated" : "single",
        coverage: "complete_for_scope",
        tier: ownerConfirmed ? "TIER_1_VERIFIED" : "TIER_3_INDICATIVE",
      },
    });
  }

  const directInventoryReady = direct.inventory_ready === true || direct.ready === true;
  const directActive = list(campaignCatalog.active);
  const directEvidenceIds: string[] = [];
  if (directInventoryReady) {
    const normalized = {
      account: text(direct.account),
      campaigns_total: number(direct.campaigns_total),
      campaign_summaries: directActive.length,
    };
    const id = await evidenceId({ source: "direct_campaigns_get", normalized, observed_at: directObservedAt });
    const cid = await claimId({ predicate: "current_direct_inventory", evidence_id: id });
    directEvidenceIds.push(id);
    evidence.push({
      evidence_id: id,
      claim_links: [{ claim_id: cid, relation: "supports" }],
      source_kind: "direct_management_api",
      source_locator: { service: "Campaigns", method: "get", client_login: text(direct.account) },
      observed_at: directObservedAt,
      extraction: { method: "api_parser", version: "direct-v501-campaign-inventory-v1" },
      raw: { sha256: `sha256:${await digest(normalized)}` },
      normalized,
    });
    claims.push({
      claim_id: cid,
      subject: "current_direct_account",
      predicate: "campaign_inventory",
      value: normalized,
      evidence_ids: [id],
      confidence: {
        source_quality: "A",
        freshness: freshness(directObservedAt, asOf) === "CURRENT" ? "current" : "unknown",
        consistency: "single",
        coverage: "partial",
        tier: "TIER_3_INDICATIVE",
      },
    });
  }

  const sampling = record(performanceProvenance.sampling);
  const metrikaReady = metrika.ready === true && Boolean(performance.period_start);
  const metrikaPartial = sampling.sampled === true || sampling.contains_sensitive_data === true;
  const metrikaEvidenceIds: string[] = [];
  if (metrikaReady) {
    const displayMetrics = record(performance.display_metrics);
    const normalized = {
      counter_id: text(metrika.counter_id),
      goal_id: text(metrika.goal_id),
      period_start: text(performance.period_start),
      period_end: text(performance.period_end),
      visits: text(displayMetrics.visits),
      goal_visits: text(displayMetrics.goal_visits),
      sampling,
    };
    const id = await evidenceId({ source: "metrika_reports_api", normalized, observed_at: metrikaObservedAt });
    const cid = await claimId({ predicate: "metrika_goal_observation", evidence_id: id });
    metrikaEvidenceIds.push(id);
    evidence.push({
      evidence_id: id,
      claim_links: [{ claim_id: cid, relation: "supports" }],
      source_kind: "metrika_reports_api",
      source_locator: {
        service: "Statistics",
        method: "get",
        counter_id: text(metrika.counter_id),
        goal_id: text(metrika.goal_id),
      },
      observed_at: metrikaObservedAt,
      extraction: { method: "api_parser", version: "metrika-stat-v1" },
      raw: { sha256: `sha256:${await digest(normalized)}` },
      normalized,
    });
    claims.push({
      claim_id: cid,
      subject: "metrika_goal",
      predicate: "observed_performance",
      value: normalized,
      evidence_ids: [id],
      confidence: {
        source_quality: "A",
        freshness: freshness(metrikaObservedAt, asOf) === "CURRENT" ? "current" : "unknown",
        consistency: "single",
        coverage: metrikaPartial ? "partial" : "complete_for_scope",
        tier: metrikaPartial ? "TIER_3_INDICATIVE" : "TIER_1_VERIFIED",
      },
    });
  }

  const firstPartyStatus: EvidenceSourceStatus = firstPartyEvidenceIds.length > 0
    ? "VERIFIED"
    : pages.length > 0
      ? "PARTIAL"
      : "UNAVAILABLE";
  const sources: EvidenceSource[] = [
    {
      source_id: "first-party",
      title: "Компания и продукты",
      source_kind: "first_party_web_and_owner",
      status: firstPartyStatus,
      observed_at: firstPartyObservedAt,
      facts: [
        `${number(siteResearch.pages_analyzed) || pages.length} first-party страниц`,
        `${claims.filter((claim) => claim.subject === "business_model").length} claims с раскрываемым evidence`,
      ],
      limitations: firstPartyEvidenceIds.length
        ? []
        : ["Нет восстановимого first-party span или отдельного подтверждения владельца."],
      evidence_ids: firstPartyEvidenceIds,
    },
    {
      source_id: "direct",
      title: "Текущий Яндекс Директ",
      source_kind: "direct_management_api",
      status: directInventoryReady ? "PARTIAL" : "UNAVAILABLE",
      observed_at: directObservedAt,
      facts: directInventoryReady
        ? [`${number(direct.campaigns_total)} кампаний прочитано`, `${directActive.length} object summaries в раскрытии`]
        : [],
      limitations: directInventoryReady
        ? [
            "Ad groups, keywords, ads и Search Query report ещё не входят в этот минимальный read-срез.",
            ...list(direct.blockers).map(text).filter(Boolean),
          ]
        : list(direct.blockers).map(text).filter(Boolean),
      evidence_ids: directEvidenceIds,
    },
    {
      source_id: "metrika",
      title: "Яндекс Метрика",
      source_kind: "metrika_reports_api",
      status: metrikaReady ? (metrikaPartial ? "PARTIAL" : "VERIFIED") : "UNAVAILABLE",
      observed_at: metrikaObservedAt,
      facts: metrikaReady
        ? [
            `${text(record(performance.display_metrics).visits)} визитов`,
            `${text(record(performance.display_metrics).goal_visits)} достижений цели`,
            `${text(performance.period_start)} — ${text(performance.period_end)}`,
          ]
        : [],
      limitations: metrikaReady
        ? [
            ...(sampling.sampled === true ? ["Ответ Метрики sampled; coverage не считается полным."] : []),
            ...(sampling.contains_sensitive_data === true ? ["Часть данных ограничена privacy threshold."] : []),
          ]
        : list(metrika.blockers).map(text).filter(Boolean),
      evidence_ids: metrikaEvidenceIds,
    },
    {
      source_id: "competitors",
      title: "Публичные конкуренты",
      source_kind: "competitor_public_web",
      status: "UNAVAILABLE",
      observed_at: null,
      facts: [],
      limitations: [
        "Разрешённая выборка конкурентов не задана; агент не подменяет наблюдение догадкой.",
        "Официальный специализированный competitor-ad feed не подтверждён.",
      ],
      evidence_ids: [],
    },
    {
      source_id: "wordstat",
      title: "Спрос и Wordstat",
      source_kind: "wordstat_api",
      status: "UNAVAILABLE",
      observed_at: null,
      facts: ["prelaunch_cost = unavailable"],
      limitations: [
        "Wordstat API v1 ещё не подключён к этому production-срезу.",
        "Wordstat frequency не является CPC или budget forecast.",
      ],
      evidence_ids: [],
    },
  ];

  const materialUncertainties = [
    ...missingQuestions.map((question) => `Material Uncertainty: ${question}`),
    "Конкурентная выборка отсутствует: control по распространённой практике не сформирован.",
    "Wordstat не подключён: частотность не наблюдалась, стоимость до запуска недоступна.",
    "Direct object graph и search-query coverage пока частичны; каннибализация не доказана.",
    ...(metrikaPartial ? ["Metrica response sampled или ограничен privacy threshold."] : []),
  ];
  const statuses = sources.map((source) => source.status);
  const sourceFreshness = sources
    .filter((source) => source.status !== "UNAVAILABLE")
    .map((source) => freshness(source.observed_at, asOf));
  const hardBlockers = [
    ...missingQuestions.map((question) => `Не разрешено: ${question}`),
    ...(firstPartyEvidenceIds.length === 0
      ? ["First-party модель не имеет восстановимого evidence или подтверждения владельца."]
      : []),
    ...(!directInventoryReady
      ? ["Текущий Direct inventory недоступен: дубли и уже покрытый спрос неизвестны."]
      : []),
  ];
  const confidence: ConfidenceVector = {
    source_quality: "PRIMARY_ONLY",
    freshness: sourceFreshness.length === 0
      ? "UNKNOWN"
      : sourceFreshness.every((value) => value === "CURRENT")
        ? "CURRENT"
        : "MIXED",
    consistency: "NOT_EVALUATED",
    coverage: statuses.every((status) => status === "VERIFIED") ? "COMPLETE_FOR_SCOPE" : "PARTIAL",
    uncertainty: materialUncertainties,
  };
  const recommendationStatus: AnalyticsEvidenceBundle["recommendation_status"] = hardBlockers.length
    ? "BLOCKED_UNKNOWN"
    : "EVIDENCE_READY_WITH_GAPS";
  const unsigned: Omit<AnalyticsEvidenceBundle, "snapshot_id"> = {
    schema_version: ANALYTICS_EVIDENCE_SCHEMA,
    as_of: asOf,
    recommendation_status: recommendationStatus,
    summary: {
      sources_total: sources.length,
      sources_verified: statuses.filter((status) => status === "VERIFIED").length,
      sources_partial: statuses.filter((status) => status === "PARTIAL").length,
      sources_unavailable: statuses.filter((status) => status === "UNAVAILABLE").length,
      claims_supported: claims.length,
      hard_blockers: hardBlockers,
    },
    confidence,
    sources,
    claims,
    evidence,
    material_uncertainties: materialUncertainties,
    prelaunch_cost: {
      status: "UNAVAILABLE" as const,
      reason: "Wordstat API v1 не является CPC/budget forecast; сопоставимого first-party history нет.",
    },
    contract_path: "docs/research/analytics-evidence-contract.md",
  };
  return {
    ...unsigned,
    snapshot_id: `sha256:${await digest(unsigned)}`,
  };
}
