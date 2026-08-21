import { buildAdText, buildAdTitle } from "./ad-copy.ts";
import { buildPublishProjection } from "./campaign-draft.ts";
import {
  packDemandClusters,
  type PackableDemandCluster,
} from "./market-evidence.ts";
import {
  scoreCampaignDrafts,
  type ViabilityScoreResult,
} from "./campaign-viability.ts";

const FAN_OUT_CONTRACT = "campaign-fanout-v1";
const CAPABILITY_PROFILE = "direct-unified-search-explicit-v1";
const MAX_DRAFTS_PER_DELIVERY_BUCKET = 3;

const text = (value: unknown) => String(value ?? "").normalize("NFKC").replace(/\s+/g, " ").trim();
const keyText = (value: unknown) => text(value).toLocaleLowerCase("ru-RU");

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value
      .map(canonicalize)
      .sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
  }
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonicalize(item)]),
  );
}

async function sha256(value: unknown) {
  const bytes = new TextEncoder().encode(JSON.stringify(canonicalize(value)));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("");
}

function phrase(...values: unknown[]) {
  const words = values
    .flatMap((value) => keyText(value).replace(/[^\p{L}\p{N}-]+/gu, " ").split(" "))
    .filter(Boolean);
  const unique: string[] = [];
  for (const word of words) {
    if (!unique.includes(word)) unique.push(word);
    if (unique.length === 7) break;
  }
  return unique.join(" ");
}

function namedVariant(product: unknown, label: string) {
  const base = text(product) || "Новая кампания";
  const suffix = ` · ${label}`;
  return `${base.slice(0, Math.max(1, 255 - suffix.length)).trim()}${suffix}`;
}

function competitorControlBasis(evidence: Record<string, unknown> | null | undefined) {
  const sources = Array.isArray(evidence?.sources) ? evidence.sources as Array<Record<string, unknown>> : [];
  const records = sources.filter((source) => {
    const identity = `${source.source_kind ?? ""} ${source.title ?? ""}`.toLowerCase();
    return identity.includes("competitor") || identity.includes("конкурент");
  });
  const eligible = records.filter((source) =>
    source.status === "VERIFIED"
    && text(source.pattern_id)
    && Array.isArray(source.facts)
    && source.facts.length > 0
    && Array.isArray(source.evidence_ids)
    && source.evidence_ids.length > 0
  );
  const byPattern = Map.groupBy(eligible, (source) => text(source.pattern_id));
  const corroborated = [...byPattern.entries()]
    .filter(([, sourcesForPattern]) => new Set(sourcesForPattern.map((source) => text(source.source_id))).size >= 2)
    .sort(([left], [right]) => left.localeCompare(right))[0];
  if (!corroborated) {
    return { kind: "STRATEGY_BASELINE_FALLBACK", evidence_ids: [], pattern_id: "approved-strategy-baseline" };
  }
  const [patternId, sourcesForPattern] = corroborated;
  const evidenceIds = [...new Set(sourcesForPattern.flatMap((source) => source.evidence_ids as unknown[]).map(String))].sort();
  return { kind: "COMPETITIVE_NORM_CONTROL", evidence_ids: evidenceIds, pattern_id: patternId };
}

function editableDraft(
  model: Record<string, unknown>,
  strategy: Record<string, unknown>,
  variant: Record<string, unknown>,
) {
  const participation = /участ|participant/iu.test(text(model.qualified_result));
  const variantCode = String(variant.code);
  const adMessage = variantCode === "CONTROL"
    ? strategy.message
    : variantCode === "QUALIFIED_ACTION"
      ? model.qualified_result
      : variantCode === "AUDIENCE_SPECIFICITY"
        ? `${strategy.message}. Для: ${model.audience}`
        : model.value;
  const keyword = variantCode === "CONTROL"
    ? phrase(model.product)
    : variantCode === "QUALIFIED_ACTION"
      ? phrase(model.product, model.qualified_result)
      : variantCode === "AUDIENCE_SPECIFICITY"
        ? phrase(model.product, model.audience)
        : phrase(model.product, model.value);
  return {
    campaign_name: namedVariant(model.product, String(variant.short_label)),
    group_name: text(variant.cluster_label),
    keyword,
    negative_keywords: "бесплатно, вакансии, посетитель, билет",
    ad_title: buildAdTitle(model.product),
    ad_text: buildAdText(adMessage, model.product, participation),
  };
}

function treatmentProjection(projection: Record<string, unknown>) {
  const direct = structuredClone(projection.direct as Record<string, unknown>);
  if (direct.campaign && typeof direct.campaign === "object") delete (direct.campaign as Record<string, unknown>).Name;
  if (direct.ad_group && typeof direct.ad_group === "object") delete (direct.ad_group as Record<string, unknown>).Name;
  return direct;
}

export async function fingerprintDirectProjection(projection: Record<string, unknown>) {
  return sha256(projection.direct);
}

export function campaignDraftPublishBlockers(draft: Record<string, unknown> | null | undefined) {
  if (draft?.market_evidence_status === "EVIDENCE_GAP" || draft?.publish_eligibility === "BLOCKED_EVIDENCE_GAP") {
    return ["Campaign Draft не имеет допустимого demand evidence и доступен только для review."];
  }
  return [];
}

export type CampaignDraftCandidate = Record<string, unknown> & {
  draft_id: string;
  draft_revision_id: string;
  strategy_revision_id: string;
  publish_projection: Record<string, unknown>;
  publish_fingerprint: string;
  treatment_fingerprint: string;
  visibility: "VISIBLE" | "HIDDEN";
  viability_score?: ViabilityScoreResult;
};

export type CampaignRecommendationSet = {
  schema_version: string;
  recommendation_set_id: string;
  strategy_revision_id: string;
  analytics_evidence_snapshot_id: string | null;
  generated_at: string;
  capability_profile: Record<string, unknown>;
  coverage: Record<string, unknown>;
  termination: Record<string, unknown>;
  score_contract: Record<string, unknown>;
  delivery_packing: Awaited<ReturnType<typeof packDemandClusters>>;
  drafts: CampaignDraftCandidate[];
};

export async function buildCampaignRecommendationSet({
  model,
  strategy,
  analyticsEvidence,
  generatedAt,
}: {
  model: Record<string, unknown>;
  strategy: Record<string, unknown>;
  analyticsEvidence?: Record<string, unknown> | null;
  generatedAt: string;
}): Promise<CampaignRecommendationSet> {
  const strategyRevisionId = text(strategy.strategy_revision_id);
  if (!strategyRevisionId) throw new Error("Campaign Strategy должна иметь immutable revision ID.");
  const controlBasis = competitorControlBasis(analyticsEvidence);
  const marketEvidence = analyticsEvidence?.market_evidence && typeof analyticsEvidence.market_evidence === "object"
    ? analyticsEvidence.market_evidence as Record<string, unknown>
    : {};
  const frequency = marketEvidence.frequency && typeof marketEvidence.frequency === "object"
    ? marketEvidence.frequency as Record<string, unknown>
    : {};
  const cost = marketEvidence.cost && typeof marketEvidence.cost === "object"
    ? marketEvidence.cost as Record<string, unknown>
    : {};
  const demandClusters = Array.isArray(frequency.clusters) ? frequency.clusters as Array<Record<string, unknown>> : [];
  const demandClusterIds = demandClusters.map((cluster) => text(cluster.cluster_id)).filter(Boolean).sort();
  const selectedCost = Array.isArray(cost.observations)
    ? (cost.observations as Array<Record<string, unknown>>).find((item) => item.source === cost.compact_source)
    : undefined;
  const capacity = selectedCost?.source === "LEGACY_LIVE4_SCENARIO" && selectedCost.capacity && typeof selectedCost.capacity === "object"
    ? {
        status: "AVAILABLE" as const,
        source: "LEGACY_LIVE4_SCENARIO" as const,
        scope: "DEDUPLICATED_DELIVERY_PACK" as const,
        demand_cluster_ids: demandClusterIds,
        forecast_clicks: Number((selectedCost.capacity as Record<string, unknown>).forecast_clicks),
        forecast_total_spend: Number((selectedCost.capacity as Record<string, unknown>).forecast_total_spend),
      }
    : { status: "UNAVAILABLE" as const, source: null };
  const provisionalMonthlyBudget = Number(strategy.weekly_budget_rub) * 52 / 12;
  const packableClusters: PackableDemandCluster[] = demandClusters.map((cluster, index) => ({
    cluster_id: text(cluster.cluster_id),
    primary: index === 0,
    demand_status: ["AVAILABLE", "PARTIAL"].includes(text(cluster.status)) && Array.isArray(cluster.assigned_row_ids) && cluster.assigned_row_ids.length > 0
      ? text(cluster.status) as "AVAILABLE" | "PARTIAL"
      : "UNAVAILABLE",
    unique_publish_row_ids: Array.isArray(cluster.assigned_row_ids) ? cluster.assigned_row_ids.map(text).filter(Boolean) : [],
    delivery_key: {
      goal: strategy.goal,
      economics: { weekly_budget_rub: strategy.weekly_budget_rub, target_cpa_rub: strategy.target_cpa_rub },
      geography: strategy.geography,
      landing: strategy.landing_page,
      message: strategy.message,
      management: CAPABILITY_PROFILE,
    },
    provisional_monthly_budget: provisionalMonthlyBudget,
    capacity,
  }));
  const deliveryPacking = await packDemandClusters(packableClusters);
  const packedClusterIds = new Set(deliveryPacking.delivery_buckets.flatMap((bucket) => bucket.demand_cluster_ids as string[]));
  const demandReady = frequency.status === "AVAILABLE" && packedClusterIds.size > 0;
  const demandPartial = frequency.status === "PARTIAL" && packedClusterIds.size > 0;
  const variantSpecs = [
    {
      code: "CONTROL",
      kind: "CONTROL",
      short_label: controlBasis.kind === "COMPETITIVE_NORM_CONTROL" ? "Контроль" : "Базовый",
      cluster_label: "Базовый коммерческий спрос",
      offer: strategy.message,
      hypothesis: null,
    },
    {
      code: "QUALIFIED_ACTION",
      kind: "IMPROVEMENT",
      short_label: "Целевое действие",
      cluster_label: "Квалифицированное действие",
      offer: model.qualified_result,
      hypothesis: {
        hypothesis_id: "qualified-action-v1",
        changed_family: "QUALIFIED_ACTION",
        mechanism: "Явное квалифицированное действие может точнее отделить коммерческий спрос.",
        changed_fields: ["/direct/keyword/Keyword", "/direct/ad/TextAd/Text"],
      },
    },
    {
      code: "AUDIENCE_SPECIFICITY",
      kind: "IMPROVEMENT",
      short_label: "Аудитория",
      cluster_label: "Ролевой коммерческий спрос",
      offer: `${strategy.message}. Для: ${model.audience}`,
      hypothesis: {
        hypothesis_id: "audience-specificity-v1",
        changed_family: "AUDIENCE_SPECIFICITY",
        mechanism: "Явное обращение к принимающей решение роли может повысить релевантность сообщения.",
        changed_fields: ["/direct/keyword/Keyword", "/direct/ad/TextAd/Text"],
      },
    },
    {
      code: "MESSAGE_OFFER",
      kind: "IMPROVEMENT",
      short_label: "Ценность",
      cluster_label: "Ценностный коммерческий спрос",
      offer: model.value,
      hypothesis: {
        hypothesis_id: "message-offer-v1",
        changed_family: "MESSAGE_OFFER",
        mechanism: "First-party ценность может дать более конкретное предложение без новых неподтверждённых claims.",
        changed_fields: ["/direct/keyword/Keyword", "/direct/ad/TextAd/Text"],
      },
    },
  ];

  const compiled: CampaignDraftCandidate[] = [];
  const seenTreatments = new Map<string, string>();
  for (const [index, variant] of variantSpecs.entries()) {
    const editable = editableDraft(model, strategy, variant);
    const provisionalKey = `${strategyRevisionId}:${String(variant.code).toLowerCase()}`;
    const provisionalId = `draft-${(await sha256(provisionalKey)).slice(0, 16)}`;
    const projection = buildPublishProjection(model, strategy, {
      ...editable,
      draft_id: provisionalId,
      strategy_revision_id: strategyRevisionId,
      capability_profile_id: CAPABILITY_PROFILE,
    }) as unknown as Record<string, unknown>;
    const publishFingerprint = await fingerprintDirectProjection(projection);
    const treatmentFingerprint = await sha256(treatmentProjection(projection));
    const duplicateOf = seenTreatments.get(treatmentFingerprint) ?? null;
    const visibleCount = compiled.filter((item) => item.visibility === "VISIBLE").length;
    const capacityHidden = visibleCount >= MAX_DRAFTS_PER_DELIVERY_BUCKET;
    const visibility = duplicateOf || capacityHidden ? "HIDDEN" : "VISIBLE";
    if (visibility === "VISIBLE") seenTreatments.set(treatmentFingerprint, provisionalId);
    compiled.push({
      ...editable,
      draft_id: provisionalId,
      draft_revision_id: `${provisionalId}-r1`,
      strategy_revision_id: strategyRevisionId,
      source: FAN_OUT_CONTRACT,
      generation_order: index + 1,
      variant: {
        kind: variant.kind,
        code: variant.code,
        control_basis: variant.kind === "CONTROL" ? controlBasis : null,
        hypothesis: variant.hypothesis,
        comparator_draft_id: variant.kind === "CONTROL" ? null : compiled[0]?.draft_id ?? null,
      },
      dimensions: {
        product: text(model.product),
        audience: text(model.audience),
        offer: text(variant.offer),
        keyword_cluster: text(variant.cluster_label),
      },
      delivery_key: {
        goal: text(strategy.goal),
        economics: `${strategy.weekly_budget_rub}:${strategy.target_cpa_rub}`,
        geography: text(strategy.geography),
        landing_page: text(strategy.landing_page),
        core_message: text(strategy.message),
        management_profile: CAPABILITY_PROFILE,
      },
      market_evidence: {
        contract_version: marketEvidence.contract_version ?? "demand-cost-packing-v1",
        frequency,
        cost,
        packing: deliveryPacking,
      },
      market_evidence_status: demandReady ? "AVAILABLE" : demandPartial ? "PARTIAL" : "EVIDENCE_GAP",
      shortlist_eligible: demandReady,
      publish_eligibility: demandReady ? "ELIGIBLE" : "BLOCKED_EVIDENCE_GAP",
      visibility,
      suppression_reason: duplicateOf
        ? "HIDDEN:NO_MATERIAL_DELTA"
        : capacityHidden
          ? "HIDDEN:CAPACITY_LIMIT"
          : null,
      duplicate_of: duplicateOf,
      publish_projection: projection,
      publish_fingerprint: publishFingerprint,
      treatment_fingerprint: treatmentFingerprint,
    } as CampaignDraftCandidate);
  }

  const recommendationSetId = `recommendation-set-${(await sha256({
    strategyRevisionId,
    evidence: analyticsEvidence?.snapshot_id ?? null,
    fingerprints: compiled.map((draft) => draft.publish_fingerprint),
  })).slice(0, 20)}`;
  const scored = await scoreCampaignDrafts({
    drafts: compiled,
    model,
    strategy,
    analyticsEvidence,
    scoredAt: generatedAt,
  });
  const visible = scored.filter((draft) => draft.visibility === "VISIBLE");
  return {
    schema_version: "campaign-recommendation-set-v2",
    recommendation_set_id: recommendationSetId,
    strategy_revision_id: strategyRevisionId,
    analytics_evidence_snapshot_id: analyticsEvidence?.snapshot_id ? String(analyticsEvidence.snapshot_id) : null,
    generated_at: generatedAt,
    capability_profile: {
      profile_id: CAPABILITY_PROFILE,
      api: "DIRECT_V501",
      campaign_type: "UNIFIED_CAMPAIGN",
      ad_group_type: "UNIFIED_AD_GROUP",
      search_strategy: "WB_MAXIMUM_CLICKS",
      network_strategy: "SERVING_OFF",
      placements: ["SEARCH_RESULTS", "DYNAMIC_PLACES_PLATFORM_LINKED"],
      criteria: ["EXPLICIT_KEYWORDS"],
      ad_type: "TEXT_AD",
      extensions: [],
      conditional_not_enabled: ["AUTOTARGETING", "SITELINKS", "PRODUCT_GALLERY", "NETWORK"],
    },
    coverage: {
      status: "COMPLETE",
      products: [text(model.product)],
      audiences: [text(model.audience)],
      offers_considered: variantSpecs.map((variant) => text(variant.offer)),
      keyword_clusters_considered: variantSpecs.map((variant) => text(variant.cluster_label)),
      candidates_total: scored.length,
      visible_drafts: visible.length,
      hidden_drafts: scored.length - visible.length,
      publishable_drafts: scored.filter((draft) => draft.publish_eligibility === "ELIGIBLE").length,
      evidence_gap_drafts: scored.filter((draft) => draft.market_evidence_status === "EVIDENCE_GAP").length,
      uncovered_axis_members: [],
    },
    termination: {
      contract: "FINITE_NON_RECURSIVE",
      delivery_buckets: deliveryPacking.delivery_buckets.length,
      maximum_drafts_per_bucket: MAX_DRAFTS_PER_DELIVERY_BUCKET,
      all_candidates_terminal: true,
    },
    delivery_packing: deliveryPacking,
    score_contract: {
      version: "viability-score/1.0.0",
      status: "UNCALIBRATED_POLICY_V1",
      semantics: "COMPARATIVE_PRELAUNCH_PRIORITY_NOT_A_FORECAST",
      landing_audit_used: false,
    },
    drafts: scored,
  };
}
