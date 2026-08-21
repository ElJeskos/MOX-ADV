import { buildAdText, buildAdTitle } from "./ad-copy.ts";
import { buildPublishProjection } from "./campaign-draft.ts";
import {
  resolveCuratedPlaybookReleases,
  type CompetitiveSampleRule,
  type CuratedPlaybookRelease,
  type CuratedPlaybookRule,
  type PlaybookAuditRecord,
  type PlaybookChangedFamily,
} from "./campaign-playbook.ts";
import { strategyAnswerValue } from "./campaign-strategy.ts";
import {
  normalizeDeliveryKey,
  packDemandClusters,
  type PackableDemandCluster,
} from "./market-evidence.ts";
import {
  scoreCampaignDrafts,
  type ViabilityScoreResult,
} from "./campaign-viability.ts";

const FAN_OUT_CONTRACT = "campaign-fanout-v1";
const MAX_IMPROVEMENTS_PER_DELIVERY_BUCKET = 2;
const PROVIDER_UNORDERED_ARRAY_PATHS = new Set([
  "/ad_group/RegionIds",
  "/ad_group/NegativeKeywords/Items",
  "/campaign/UnifiedCampaign/CounterIds",
]);

export const CORE_DIRECT_CAPABILITY_PROFILE = Object.freeze({
  profile_id: "direct-v501-unified-search-explicit-text",
  profile_version: "1.0.0",
  api_family: "YANDEX_DIRECT_API",
  endpoint_version: "v501",
  campaign_type: "UNIFIED_CAMPAIGN",
  ad_group_type: "UNIFIED_AD_GROUP",
  search_strategy: "WB_MAXIMUM_CLICKS",
  network_strategy: "SERVING_OFF",
  search_results: "ENABLED",
  product_gallery: "DISABLED",
  dynamic_places: "PLATFORM_LINKED_TO_SEARCH_RESULTS",
  criteria: Object.freeze(["EXPLICIT_KEYWORDS"]),
  ad_type: "TEXT_AD",
  conditional_not_enabled: Object.freeze(["AUTOTARGETING", "SITELINKS", "PRODUCT_GALLERY", "NETWORK"]),
});

export type DirectConditionalCapabilityEvidence = {
  capability: "AUTOTARGETING" | "SITELINKS" | "PRODUCT_GALLERY" | "NETWORK";
  field_paths: string[];
  official_api_check: {
    source: "YANDEX_DIRECT_API_V501";
    endpoint: string;
    method: string;
    evidence_id: string;
    verified: boolean;
  };
  account_eligibility_check: {
    account: string;
    evidence_id: string;
    eligible: boolean;
  };
};

export type DirectCapabilitySnapshot = {
  schema_version: "direct-account-capability-snapshot-v1";
  snapshot_id: string;
  observed_at: string;
  source: "YANDEX_DIRECT_API_V501";
  account: string;
  api_version: "v501";
  currency: string;
  available_campaign_types: string[];
  edit_campaigns_grant: "YES" | "NO" | "UNKNOWN";
  archived: "YES" | "NO" | "UNKNOWN";
  restrictions: Array<{ element: string; value: number }>;
  conditional_capabilities: DirectConditionalCapabilityEvidence[];
};

export type CapabilityBlocker = {
  code: "UNSUPPORTED_SELECTED_FIELD" | "CONDITIONAL_CAPABILITY_EVIDENCE_MISSING" | "CONDITIONAL_CAPABILITY_ACCOUNT_INELIGIBLE";
  field_path: string;
  capability: string | null;
  message: string;
};

const CONDITIONAL_FIELD_CAPABILITY = new Map([
  ["/direct/keyword/AutotargetingSettings", "AUTOTARGETING"],
  ["/direct/campaign/UnifiedCampaign/BiddingStrategy/Search/PlacementTypes/ProductGallery", "PRODUCT_GALLERY"],
  ["/direct/sitelink_sets", "SITELINKS"],
  ["/direct/campaign/UnifiedCampaign/BiddingStrategy/Network", "NETWORK"],
]);

const text = (value: unknown) => String(value ?? "").normalize("NFKC").replace(/\s+/gu, " ").trim();
const keyText = (value: unknown) => text(value).toLocaleLowerCase("ru-RU");

function canonicalizeProviderProjection(value: unknown, path = ""): unknown {
  if (Array.isArray(value)) {
    const normalized = value.map((item, index) => canonicalizeProviderProjection(item, `${path}/${index}`));
    return PROVIDER_UNORDERED_ARRAY_PATHS.has(path)
      ? normalized.sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)))
      : normalized;
  }
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonicalizeProviderProjection(item, `${path}/${key}`)]),
  );
}

async function sha256(value: unknown, canonicalize = canonicalizeProviderProjection) {
  const bytes = new TextEncoder().encode(JSON.stringify(canonicalize(value)));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return `sha256:${[...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("")}`;
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

function namedVariant(product: unknown, label: string, bucketOrdinal: number) {
  const base = text(product) || "Новая кампания";
  const bucket = bucketOrdinal > 1 ? ` · Пакет ${bucketOrdinal}` : "";
  const suffix = ` · ${label}${bucket}`;
  return `${base.slice(0, Math.max(1, 255 - suffix.length)).trim()}${suffix}`;
}

function competitiveControlBasis(
  evidence: Record<string, unknown> | null | undefined,
  sampleRules: CompetitiveSampleRule[],
) {
  const sampleRule = sampleRules[0];
  if (!sampleRule) {
    return {
      kind: "STRATEGY_BASELINE_FALLBACK",
      evidence_ids: [] as string[],
      pattern_id: "approved-strategy-baseline",
      sample_rule_id: null,
      sample_rule_version: null,
      fallback_reason: "ACTIVE_VERSIONED_SAMPLE_RULE_UNAVAILABLE",
    };
  }
  const sources = Array.isArray(evidence?.sources) ? evidence.sources as Array<Record<string, unknown>> : [];
  const competitors = sources.filter((source) => {
    const identity = `${source.source_kind ?? ""} ${source.title ?? ""}`.toLowerCase();
    return identity.includes("competitor") || identity.includes("конкурент");
  });
  const eligible = competitors.filter((source) =>
    source.status === sampleRule.required_source_status
    && text(source.pattern_id)
    && Array.isArray(source.facts)
    && source.facts.length > 0
    && Array.isArray(source.evidence_ids)
    && source.evidence_ids.length > 0
    && text(source.source_id)
  );
  const byPattern = Map.groupBy(eligible, (source) => text(source.pattern_id));
  const corroborated = [...byPattern.entries()]
    .filter(([, sourcesForPattern]) => new Set(sourcesForPattern.map((source) => text(source.source_id))).size >= sampleRule.minimum_independent_sources)
    .sort(([left], [right]) => left.localeCompare(right))[0];
  if (!corroborated) {
    return {
      kind: "STRATEGY_BASELINE_FALLBACK",
      evidence_ids: [] as string[],
      pattern_id: "approved-strategy-baseline",
      sample_rule_id: sampleRule.sample_rule_id,
      sample_rule_version: sampleRule.sample_rule_version,
      fallback_reason: "COMPETITIVE_SAMPLE_RULE_NOT_SATISFIED",
    };
  }
  const [patternId, sourcesForPattern] = corroborated;
  const evidenceIds = [...new Set(sourcesForPattern.flatMap((source) => source.evidence_ids as unknown[]).map(String))].sort();
  return {
    kind: "COMPETITIVE_NORM_CONTROL",
    evidence_ids: evidenceIds,
    pattern_id: patternId,
    sample_rule_id: sampleRule.sample_rule_id,
    sample_rule_version: sampleRule.sample_rule_version,
    fallback_reason: null,
  };
}

function variantLabel(family: PlaybookChangedFamily | null, controlKind: string) {
  if (!family) return controlKind === "COMPETITIVE_NORM_CONTROL" ? "Контроль" : "STRATEGY_BASELINE_FALLBACK";
  const labels: Record<PlaybookChangedFamily, string> = {
    QUALIFIED_ACTION: "Целевое действие",
    AUDIENCE_SPECIFICITY: "Аудитория",
    MESSAGE_OFFER: "Ценность",
    CRITERIA_AUTOTARGETING: "Автотаргетинг",
    PLACEMENT: "Плейсмент",
    EXTENSION: "Расширение",
  };
  return labels[family];
}

function editableDraft(
  model: Record<string, unknown>,
  strategy: Record<string, unknown>,
  family: PlaybookChangedFamily | null,
  shortLabel: string,
  clusterLabel: string,
  bucketOrdinal: number,
) {
  const advertisedOffer = strategyAnswerValue(strategy, "advertised_offer") || model.product;
  const targetAudience = strategyAnswerValue(strategy, "target_audience") || model.audience;
  const qualifiedResult = strategyAnswerValue(strategy, "qualified_result") || model.qualified_result;
  const coreMessage = strategyAnswerValue(strategy, "core_message") || model.value;
  const participation = /участ|participant/iu.test(text(qualifiedResult));
  const adMessage = family === "QUALIFIED_ACTION"
    ? qualifiedResult
    : family === "AUDIENCE_SPECIFICITY"
      ? `${coreMessage}. Для: ${targetAudience}`
      : family === "MESSAGE_OFFER"
        ? `${coreMessage}. ${advertisedOffer}`
        : coreMessage;
  const keyword = family === "QUALIFIED_ACTION"
    ? phrase(advertisedOffer, qualifiedResult)
    : family === "AUDIENCE_SPECIFICITY"
      ? phrase(advertisedOffer, targetAudience)
      : family === "MESSAGE_OFFER"
        ? phrase(advertisedOffer, coreMessage)
        : phrase(advertisedOffer);
  return {
    campaign_name: namedVariant(advertisedOffer, shortLabel, bucketOrdinal),
    group_name: clusterLabel,
    keyword,
    negative_keywords: "бесплатно, вакансии, посетитель, билет",
    ad_title: buildAdTitle(advertisedOffer),
    ad_text: buildAdText(adMessage, advertisedOffer, participation),
  };
}

function applyConditionalProjection(
  projection: Record<string, unknown>,
  family: PlaybookChangedFamily | null,
) {
  const direct = projection.direct as Record<string, unknown>;
  if (family === "CRITERIA_AUTOTARGETING") {
    (direct.keyword as Record<string, unknown>).AutotargetingSettings = {
      Categories: {
        Exact: "YES",
        Narrow: "YES",
        Alternative: "NO",
        Accessory: "NO",
        Broader: "NO",
      },
    };
  }
  if (family === "PLACEMENT") {
    const campaign = direct.campaign as Record<string, unknown>;
    const unified = campaign.UnifiedCampaign as Record<string, unknown>;
    const bidding = unified.BiddingStrategy as Record<string, unknown>;
    const search = bidding.Search as Record<string, unknown>;
    search.PlacementTypes = { SearchResults: "NO", ProductGallery: "YES" };
  }
}

function treatmentProjection(projection: Record<string, unknown>) {
  const direct = structuredClone(projection.direct as Record<string, unknown>);
  if (direct.campaign && typeof direct.campaign === "object") delete (direct.campaign as Record<string, unknown>).Name;
  if (direct.ad_group && typeof direct.ad_group === "object") delete (direct.ad_group as Record<string, unknown>).Name;
  return direct;
}

function changedPointers(left: unknown, right: unknown, path = "/direct"): string[] {
  const leftCanonical = canonicalizeProviderProjection(left);
  const rightCanonical = canonicalizeProviderProjection(right);
  if (JSON.stringify(leftCanonical) === JSON.stringify(rightCanonical)) return [];
  if (!leftCanonical || !rightCanonical || typeof leftCanonical !== "object" || typeof rightCanonical !== "object"
    || Array.isArray(leftCanonical) || Array.isArray(rightCanonical)) return [path];
  const keys = [...new Set([...Object.keys(leftCanonical as Record<string, unknown>), ...Object.keys(rightCanonical as Record<string, unknown>)])].sort();
  return keys.flatMap((key) => changedPointers(
    (leftCanonical as Record<string, unknown>)[key],
    (rightCanonical as Record<string, unknown>)[key],
    `${path}/${key}`,
  ));
}

export async function fingerprintDirectProjection(projection: Record<string, unknown>) {
  return sha256(projection.direct);
}

export function evaluateCoreDirectCapability(snapshot?: DirectCapabilitySnapshot | null) {
  const blockers: Array<Record<string, unknown>> = [];
  if (!snapshot) blockers.push(publicationBlocker(
    "DIRECT_CORE_CAPABILITY_SNAPSHOT_MISSING",
    "Core Direct v501 capability profile requires a persisted exact account snapshot.",
  ));
  else {
    if (snapshot.schema_version !== "direct-account-capability-snapshot-v1"
      || snapshot.source !== "YANDEX_DIRECT_API_V501" || snapshot.api_version !== "v501"
      || !text(snapshot.snapshot_id) || !text(snapshot.account) || !text(snapshot.observed_at)) {
      blockers.push(publicationBlocker("DIRECT_CORE_CAPABILITY_SNAPSHOT_INVALID", "Direct capability snapshot lineage or official source is invalid."));
    }
    if (!snapshot.available_campaign_types.includes("UNIFIED_CAMPAIGN")) {
      blockers.push(publicationBlocker("DIRECT_UNIFIED_CAMPAIGN_UNAVAILABLE", "Exact Direct account does not report UNIFIED_CAMPAIGN eligibility."));
    }
    if (snapshot.edit_campaigns_grant !== "YES" || snapshot.archived !== "NO") {
      blockers.push(publicationBlocker("DIRECT_ACCOUNT_NOT_EDIT_ELIGIBLE", "Exact Direct account grant or archived state blocks publication."));
    }
  }
  return { eligible: blockers.length === 0, blockers, snapshot_id: snapshot?.snapshot_id ?? null };
}

export function evaluateDirectCapabilitySelection({
  selectedFields,
  requiredCapabilities = [],
  snapshot,
}: {
  selectedFields: string[];
  requiredCapabilities?: string[];
  snapshot?: DirectCapabilitySnapshot | null;
}) {
  const blockers: CapabilityBlocker[] = [];
  const unsupportedFields: string[] = [];
  const normalizedSelectedFields = [...new Set(selectedFields.map(text).filter(Boolean))].sort();
  const selectedCapabilities = new Set(requiredCapabilities.map(text).filter(Boolean));
  for (const fieldPath of normalizedSelectedFields) {
    const capability = CONDITIONAL_FIELD_CAPABILITY.get(fieldPath);
    if (!capability) {
      blockers.push({
        code: "UNSUPPORTED_SELECTED_FIELD",
        field_path: fieldPath,
        capability: null,
        message: `Selected Direct field ${fieldPath} is not supported by the accepted capability profile.`,
      });
      unsupportedFields.push(fieldPath);
      continue;
    }
    selectedCapabilities.add(capability);
  }
  for (const capability of [...selectedCapabilities].sort()) {
    const evidence = snapshot?.conditional_capabilities.find((item) => item.capability === capability);
    const fields = [...new Set([
      ...selectedFields.filter((field) => CONDITIONAL_FIELD_CAPABILITY.get(field) === capability),
      ...(evidence?.field_paths ?? []),
    ])].sort();
    if (!evidence || evidence.official_api_check.source !== "YANDEX_DIRECT_API_V501"
      || !text(evidence.official_api_check.endpoint) || !text(evidence.official_api_check.method)
      || !text(evidence.official_api_check.evidence_id) || evidence.official_api_check.verified !== true
      || !text(evidence.account_eligibility_check.account) || !text(evidence.account_eligibility_check.evidence_id)) {
      for (const fieldPath of fields.length ? fields : [`capability:${capability}`]) {
        blockers.push({
          code: "CONDITIONAL_CAPABILITY_EVIDENCE_MISSING",
          field_path: fieldPath,
          capability,
          message: `${capability} requires persisted official API and exact account eligibility evidence.`,
        });
        if (fieldPath.startsWith("/")) unsupportedFields.push(fieldPath);
      }
    } else if (evidence.account_eligibility_check.eligible !== true || snapshot?.account !== evidence.account_eligibility_check.account) {
      for (const fieldPath of fields.length ? fields : [`capability:${capability}`]) {
        blockers.push({
          code: "CONDITIONAL_CAPABILITY_ACCOUNT_INELIGIBLE",
          field_path: fieldPath,
          capability,
          message: `${capability} is not eligible for the exact Direct account.`,
        });
        if (fieldPath.startsWith("/")) unsupportedFields.push(fieldPath);
      }
    }
  }
  return {
    eligible: blockers.length === 0,
    selected_capabilities: [...selectedCapabilities].sort(),
    selected_fields: normalizedSelectedFields,
    unsupported_fields: [...new Set(unsupportedFields)].sort(),
    blockers,
    capability_snapshot_id: snapshot?.snapshot_id ?? null,
  };
}

export function preserveSelectedConditionalProjection({
  generatedDraft,
  editedProjection,
  snapshot,
}: {
  generatedDraft: Record<string, unknown>;
  editedProjection: Record<string, unknown>;
  snapshot?: DirectCapabilitySnapshot | null;
}) {
  const projection = structuredClone(editedProjection);
  const sourceDirect = (generatedDraft.publish_projection as Record<string, unknown> | undefined)?.direct as Record<string, unknown> | undefined;
  const targetDirect = projection.direct as Record<string, unknown>;
  const previousSelection = generatedDraft.capability_selection as Record<string, unknown> | undefined;
  const selectedCapabilities = Array.isArray(previousSelection?.selected_capabilities)
    ? previousSelection.selected_capabilities.map(text).filter(Boolean) : [];
  const selectedFields = Array.isArray(previousSelection?.selected_fields)
    ? previousSelection.selected_fields.map(text).filter(Boolean) : [];
  if (selectedCapabilities.includes("AUTOTARGETING") && sourceDirect?.keyword && targetDirect.keyword) {
    const sourceKeyword = sourceDirect.keyword as Record<string, unknown>;
    if (Object.hasOwn(sourceKeyword, "AutotargetingSettings")) {
      (targetDirect.keyword as Record<string, unknown>).AutotargetingSettings = structuredClone(sourceKeyword.AutotargetingSettings);
    }
  }
  if (selectedCapabilities.includes("PRODUCT_GALLERY") && sourceDirect?.campaign && targetDirect.campaign) {
    const sourceSearch = (((sourceDirect.campaign as Record<string, unknown>).UnifiedCampaign as Record<string, unknown>)?.BiddingStrategy as Record<string, unknown>)?.Search as Record<string, unknown>;
    const targetSearch = (((targetDirect.campaign as Record<string, unknown>).UnifiedCampaign as Record<string, unknown>)?.BiddingStrategy as Record<string, unknown>)?.Search as Record<string, unknown>;
    if (sourceSearch?.PlacementTypes && targetSearch) targetSearch.PlacementTypes = structuredClone(sourceSearch.PlacementTypes);
  }
  if (selectedCapabilities.includes("NETWORK") && sourceDirect?.campaign && targetDirect.campaign) {
    const sourceBidding = ((sourceDirect.campaign as Record<string, unknown>).UnifiedCampaign as Record<string, unknown>)?.BiddingStrategy as Record<string, unknown>;
    const targetBidding = ((targetDirect.campaign as Record<string, unknown>).UnifiedCampaign as Record<string, unknown>)?.BiddingStrategy as Record<string, unknown>;
    if (sourceBidding?.Network && targetBidding) targetBidding.Network = structuredClone(sourceBidding.Network);
  }
  if (selectedCapabilities.includes("SITELINKS") && sourceDirect?.sitelink_sets) {
    targetDirect.sitelink_sets = structuredClone(sourceDirect.sitelink_sets);
  }
  const capabilitySelection = evaluateDirectCapabilitySelection({
    selectedFields,
    requiredCapabilities: selectedCapabilities,
    snapshot,
  });
  return { projection, capability_selection: capabilitySelection };
}

export function campaignDraftPublishBlockers(draft: Record<string, unknown> | null | undefined) {
  const persisted = Array.isArray(draft?.publication_blockers)
    ? (draft.publication_blockers as Array<Record<string, unknown>>).map((item) => text(item.message)).filter(Boolean)
    : [];
  if (persisted.length) return persisted;
  if (draft?.market_evidence_status === "EVIDENCE_GAP" || draft?.publish_eligibility === "BLOCKED_EVIDENCE_GAP") {
    return ["Campaign Draft не имеет допустимого demand evidence и доступен только для review."];
  }
  return [];
}

export type CampaignDraftCandidate = Record<string, unknown> & {
  draft_id: string;
  draft_revision_id: string;
  strategy_revision_id: string;
  capability_profile_id: string;
  capability_profile_version: string;
  playbook_release_id: string | null;
  playbook_rule_id: string | null;
  publish_projection: Record<string, unknown>;
  publish_fingerprint: string;
  treatment_fingerprint: string;
  visibility: "VISIBLE" | "HIDDEN";
  viability_score?: ViabilityScoreResult;
};

export type CandidateAuditRecord = {
  candidate_id: string;
  candidate_type: "DRAFT" | "PLAYBOOK_RELEASE" | "PLAYBOOK_RULE" | "COMPETITIVE_SAMPLE_RULE";
  delivery_bucket_id: string | null;
  draft_id: string | null;
  visibility: "VISIBLE" | "HIDDEN";
  reason_code: string;
  playbook_release_id: string | null;
  playbook_rule_id: string | null;
};

export type CampaignRecommendationSet = {
  schema_version: "campaign-recommendation-set-v3";
  recommendation_set_id: string;
  strategy_revision_id: string;
  analytics_evidence_snapshot_id: string | null;
  generated_at: string;
  capability_profile: Record<string, unknown>;
  direct_capability_snapshot_id: string | null;
  playbook_release: Record<string, unknown>;
  coverage: Record<string, unknown>;
  candidate_audit: CandidateAuditRecord[];
  axis_ledger: Record<string, unknown>;
  termination: Record<string, unknown>;
  score_contract: Record<string, unknown>;
  delivery_packing: Awaited<ReturnType<typeof packDemandClusters>>;
  drafts: CampaignDraftCandidate[];
};

function playbookCandidateAudit(audit: PlaybookAuditRecord): CandidateAuditRecord {
  return {
    candidate_id: audit.audit_id,
    candidate_type: audit.subject_type === "RELEASE" ? "PLAYBOOK_RELEASE"
      : audit.subject_type === "COMPETITIVE_SAMPLE_RULE" ? "COMPETITIVE_SAMPLE_RULE" : "PLAYBOOK_RULE",
    delivery_bucket_id: null,
    draft_id: null,
    visibility: "HIDDEN",
    reason_code: `HIDDEN:${audit.reason_code}`,
    playbook_release_id: audit.release_id,
    playbook_rule_id: audit.rule_id,
  };
}

function axisMember(axis: string, value: unknown) {
  const label = text(value);
  return { member_id: `${axis}:${keyText(label).replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-|-$/gu, "") || "unknown"}`, label };
}

function publicationBlocker(code: string, message: string, fieldPath: string | null = null) {
  return { code, message, field_path: fieldPath };
}

function ruleSelectedFields(rule: CuratedPlaybookRule) {
  return rule.changed_fields.filter((pointer) => CONDITIONAL_FIELD_CAPABILITY.has(pointer));
}

function expectedChangedFields(rule: CuratedPlaybookRule) {
  return [...new Set(rule.changed_fields.map(text).filter(Boolean))].sort();
}

export async function buildCampaignRecommendationSet({
  model,
  strategy,
  analyticsEvidence,
  generatedAt,
  playbookReleases = [],
  directCapabilitySnapshot = null,
}: {
  model: Record<string, unknown>;
  strategy: Record<string, unknown>;
  analyticsEvidence?: Record<string, unknown> | null;
  generatedAt: string;
  playbookReleases?: CuratedPlaybookRelease[];
  directCapabilitySnapshot?: DirectCapabilitySnapshot | null;
}): Promise<CampaignRecommendationSet> {
  const strategyRevisionId = text(strategy.strategy_revision_id);
  if (!strategyRevisionId) throw new Error("Campaign Strategy должна иметь immutable revision ID.");
  const businessGoal = strategyAnswerValue(strategy, "business_goal");
  const advertisedOffer = strategyAnswerValue(strategy, "advertised_offer") || model.product;
  const targetAudience = strategyAnswerValue(strategy, "target_audience") || model.audience;
  const qualifiedResult = strategyAnswerValue(strategy, "qualified_result") || model.qualified_result;
  const geography = strategyAnswerValue(strategy, "geography");
  const landingPage = strategyAnswerValue(strategy, "landing_page");
  const weeklyBudget = strategyAnswerValue(strategy, "weekly_budget");
  const targetResultCost = strategyAnswerValue(strategy, "target_result_cost");
  const coreMessage = strategyAnswerValue(strategy, "core_message") || model.value;
  const playbook = await resolveCuratedPlaybookReleases(playbookReleases);
  const coreCapability = evaluateCoreDirectCapability(directCapabilitySnapshot);
  const controlBasis = competitiveControlBasis(analyticsEvidence, playbook.competitiveSampleRules);
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
  const provisionalMonthlyBudget = Number(weeklyBudget) * 52 / 12;
  const strategyDeliveryKey = {
    goal: businessGoal,
    economics: { weekly_budget_rub: weeklyBudget, target_cpa_rub: targetResultCost },
    geography,
    landing: landingPage,
    message: coreMessage,
    management: `${CORE_DIRECT_CAPABILITY_PROFILE.profile_id}@${CORE_DIRECT_CAPABILITY_PROFILE.profile_version}`,
  };
  const packableClusters: PackableDemandCluster[] = demandClusters.map((cluster, index) => ({
    cluster_id: text(cluster.cluster_id),
    primary: index === 0,
    demand_status: ["AVAILABLE", "PARTIAL"].includes(text(cluster.status)) && Array.isArray(cluster.assigned_row_ids) && cluster.assigned_row_ids.length > 0
      ? text(cluster.status) as "AVAILABLE" | "PARTIAL"
      : "UNAVAILABLE",
    unique_publish_row_ids: Array.isArray(cluster.assigned_row_ids) ? cluster.assigned_row_ids.map(text).filter(Boolean) : [],
    delivery_key: cluster.delivery_key && typeof cluster.delivery_key === "object"
      ? cluster.delivery_key as PackableDemandCluster["delivery_key"]
      : strategyDeliveryKey,
    provisional_monthly_budget: Number.isFinite(Number(cluster.provisional_monthly_budget))
      ? Number(cluster.provisional_monthly_budget) : provisionalMonthlyBudget,
    relationship_state: text(cluster.relationship_state) as PackableDemandCluster["relationship_state"],
    capacity: cluster.capacity && typeof cluster.capacity === "object"
      ? cluster.capacity as PackableDemandCluster["capacity"] : capacity,
  }));
  const deliveryPacking = await packDemandClusters(packableClusters);
  const packedClusterIds = new Set(deliveryPacking.delivery_buckets.flatMap((bucket) => bucket.demand_cluster_ids as string[]));
  const demandReady = frequency.status === "AVAILABLE" && packedClusterIds.size > 0;
  const demandPartial = frequency.status === "PARTIAL" && packedClusterIds.size > 0;
  const normalizedStrategyDeliveryKey = normalizeDeliveryKey(strategyDeliveryKey);
  const syntheticFingerprint = await sha256(normalizedStrategyDeliveryKey);
  const usesSyntheticEvidenceGapBucket = deliveryPacking.delivery_buckets.length === 0;
  const buckets = !usesSyntheticEvidenceGapBucket
    ? deliveryPacking.delivery_buckets
    : [{
        delivery_bucket_id: `delivery-bucket:${syntheticFingerprint.slice("sha256:".length, "sha256:".length + 20)}`,
        delivery_key: normalizedStrategyDeliveryKey,
        delivery_key_fingerprint: syntheticFingerprint,
        demand_cluster_ids: demandClusterIds,
        disposition: "EVIDENCE_GAP",
        reason_codes: ["DEMAND_EVIDENCE_UNAVAILABLE"],
      }];

  const productAxes = [axisMember("product", advertisedOffer)];
  const audienceAxes = [axisMember("audience", targetAudience)];
  const offerAxes = [axisMember("offer", coreMessage)];
  const keywordAxes = demandClusters.length
    ? demandClusters.map((cluster) => ({ ...axisMember("keyword-cluster", cluster.cluster_id), semantic_key: cluster.semantic_key ?? null }))
    : [{ ...axisMember("keyword-cluster", "evidence-gap"), semantic_key: null }];
  const leafLedger = keywordAxes.map((cluster) => {
    const clusterId = text(cluster.label);
    const disposition = (deliveryPacking.cluster_dispositions as Record<string, Record<string, unknown>>)[clusterId];
    return {
      leaf_id: `leaf:${productAxes[0].member_id}:${audienceAxes[0].member_id}:${offerAxes[0].member_id}:${cluster.member_id}`,
      product_id: productAxes[0].member_id,
      audience_id: audienceAxes[0].member_id,
      offer_id: offerAxes[0].member_id,
      keyword_cluster_id: cluster.member_id,
      demand_cluster_id: demandClusters.length ? clusterId : null,
      terminal_disposition: disposition?.disposition ?? "EVIDENCE_GAP",
      reason_codes: disposition?.reason_codes ?? ["DEMAND_EVIDENCE_UNAVAILABLE"],
      delivery_bucket_id: disposition?.delivery_bucket_id ?? (usesSyntheticEvidenceGapBucket ? text(buckets[0].delivery_bucket_id) : null),
    };
  });

  const candidateAudit: CandidateAuditRecord[] = playbook.audits.map(playbookCandidateAudit);
  const compiled: CampaignDraftCandidate[] = [];
  const seenTreatments = new Map<string, string>();
  const activeRules = playbook.rules.slice(0, MAX_IMPROVEMENTS_PER_DELIVERY_BUCKET);
  const overflowRules = playbook.rules.slice(MAX_IMPROVEMENTS_PER_DELIVERY_BUCKET);
  for (const [bucketIndex, bucket] of buckets.entries()) {
    const bucketId = text(bucket.delivery_bucket_id);
    for (const rule of overflowRules) {
      candidateAudit.push({
        candidate_id: `playbook-rule:${playbook.release?.release_id ?? "none"}:${rule.rule_id}:${bucketId}:limit`,
        candidate_type: "PLAYBOOK_RULE",
        delivery_bucket_id: bucketId,
        draft_id: null,
        visibility: "HIDDEN",
        reason_code: "HIDDEN:PLAYBOOK_RULE_BUCKET_IMPROVEMENT_LIMIT",
        playbook_release_id: playbook.release?.release_id ?? null,
        playbook_rule_id: rule.rule_id,
      });
    }
    const specifications: Array<{ rule: CuratedPlaybookRule | null; family: PlaybookChangedFamily | null }> = [
      { rule: null, family: null },
      ...activeRules.map((rule) => ({ rule, family: rule.changed_family })),
    ];
    let comparator: CampaignDraftCandidate | null = null;
    for (const specification of specifications) {
      const rule = specification.rule;
      const family = specification.family;
      const clusterIds = (bucket.demand_cluster_ids as string[]).map(text).sort();
      const clusterLabel = clusterIds.length ? `Demand pack: ${clusterIds.join(", ")}` : "Demand evidence gap";
      const shortLabel = variantLabel(family, controlBasis.kind);
      const editable = editableDraft(model, strategy, family, shortLabel, clusterLabel, bucketIndex + 1);
      const identityInput = {
        strategy_revision_id: strategyRevisionId,
        delivery_key_fingerprint: bucket.delivery_key_fingerprint,
        demand_cluster_ids: clusterIds,
        variant: rule ? `${rule.rule_id}@${rule.rule_version}` : controlBasis.kind,
        capability_profile: `${CORE_DIRECT_CAPABILITY_PROFILE.profile_id}@${CORE_DIRECT_CAPABILITY_PROFILE.profile_version}`,
        playbook_release_digest: playbook.release?.content_digest ?? null,
      };
      const draftIdentity = await sha256(identityInput);
      const draftId = `draft-${draftIdentity.slice("sha256:".length, "sha256:".length + 20)}`;
      const draftRevisionId = `${draftId}-r1`;
      const projection = buildPublishProjection(model, strategy, {
        ...editable,
        draft_id: draftId,
        draft_revision_id: draftRevisionId,
        strategy_revision_id: strategyRevisionId,
        capability_profile_id: CORE_DIRECT_CAPABILITY_PROFILE.profile_id,
        capability_profile_version: CORE_DIRECT_CAPABILITY_PROFILE.profile_version,
        playbook_release_id: playbook.release?.release_id ?? null,
        playbook_release_version: playbook.release?.release_version ?? null,
        playbook_rule_id: rule?.rule_id ?? null,
        playbook_rule_version: rule?.rule_version ?? null,
      }) as unknown as Record<string, unknown>;
      applyConditionalProjection(projection, family);
      const actualChangedFields = comparator
        ? changedPointers(treatmentProjection(comparator.publish_projection), treatmentProjection(projection))
        : [];
      const selectedFields = rule ? ruleSelectedFields(rule) : [];
      const capability = evaluateDirectCapabilitySelection({
        selectedFields,
        requiredCapabilities: rule?.required_capabilities ?? [],
        snapshot: directCapabilitySnapshot,
      });
      const publicationBlockers: Array<Record<string, unknown>> = [...coreCapability.blockers];
      if (!playbook.release) publicationBlockers.push(publicationBlocker(
        "PLAYBOOK_RELEASE_UNAVAILABLE",
        "Campaign Draft publication requires exactly one ACTIVE and APPROVED curated playbook release.",
      ));
      if (!demandReady) publicationBlockers.push(publicationBlocker(
        "DEMAND_EVIDENCE_GAP",
        "Campaign Draft не имеет допустимого demand evidence и доступен только для review.",
      ));
      publicationBlockers.push(...capability.blockers.map((blocker) => publicationBlocker(blocker.code, blocker.message, blocker.field_path)));
      const expectedFields = rule ? expectedChangedFields(rule) : [];
      const undeclaredChanges = actualChangedFields.filter((pointer) => !expectedFields.includes(pointer));
      const missingDeclaredChanges = expectedFields.filter((pointer) => !actualChangedFields.includes(pointer));
      let suppressionReason: string | null = null;
      if (rule && actualChangedFields.length === 0) suppressionReason = "HIDDEN:NO_MATERIAL_DELTA";
      else if (rule && (undeclaredChanges.length > 0 || missingDeclaredChanges.length > 0)) {
        suppressionReason = "HIDDEN:POLICY_REJECTED:ONE_FACTOR_DELTA_MISMATCH";
        publicationBlockers.push(publicationBlocker(
          "ONE_FACTOR_DELTA_MISMATCH",
          "Improvement projection does not match the one-factor changed_fields contract.",
        ));
      } else if (!capability.eligible) suppressionReason = "HIDDEN:HARD_INELIGIBLE:UNSUPPORTED_CAPABILITY";
      const publishFingerprint = await fingerprintDirectProjection(projection);
      const treatmentFingerprint = await sha256(treatmentProjection(projection));
      const duplicateOf = seenTreatments.get(treatmentFingerprint) ?? null;
      if (!suppressionReason && duplicateOf) suppressionReason = "HIDDEN:DUPLICATE_OR_OVERLAP";
      const visibility = suppressionReason ? "HIDDEN" as const : "VISIBLE" as const;
      if (visibility === "VISIBLE") seenTreatments.set(treatmentFingerprint, draftId);
      const publishEligibility = publicationBlockers.length === 0 && visibility === "VISIBLE" ? "ELIGIBLE" : publicationBlockers.some((item) => item.code === "DEMAND_EVIDENCE_GAP")
        ? "BLOCKED_EVIDENCE_GAP" : "BLOCKED_HARD";
      const draft = {
        ...editable,
        draft_id: draftId,
        draft_revision_id: draftRevisionId,
        strategy_revision_id: strategyRevisionId,
        capability_profile_id: CORE_DIRECT_CAPABILITY_PROFILE.profile_id,
        capability_profile_version: CORE_DIRECT_CAPABILITY_PROFILE.profile_version,
        direct_capability_snapshot_id: directCapabilitySnapshot?.snapshot_id ?? null,
        playbook_release_id: playbook.release?.release_id ?? null,
        playbook_release_version: playbook.release?.release_version ?? null,
        playbook_release_digest: playbook.release?.content_digest ?? null,
        playbook_rule_id: rule?.rule_id ?? null,
        playbook_rule_version: rule?.rule_version ?? null,
        source: FAN_OUT_CONTRACT,
        generation_order: compiled.length + 1,
        delivery_bucket_id: bucketId,
        delivery_key_fingerprint: bucket.delivery_key_fingerprint,
        demand_cluster_ids: clusterIds,
        covered_leaf_ids: leafLedger.filter((leaf) => leaf.delivery_bucket_id === bucketId).map((leaf) => leaf.leaf_id),
        variant: {
          kind: rule ? "IMPROVEMENT" : "CONTROL",
          code: rule?.changed_family ?? "CONTROL",
          control_basis: rule ? null : controlBasis,
          hypothesis: rule ? {
            hypothesis_id: `${rule.rule_id}@${rule.rule_version}`,
            source: "ACTIVE_PLAYBOOK",
            mechanism: rule.mechanism,
            changed_family: rule.changed_family,
            changed_fields: actualChangedFields,
            held_constant_fields: ["/direct/campaign/UnifiedCampaign/BiddingStrategy/Network", "/direct/ad/TextAd/Href"],
            comparator_draft_id: comparator?.draft_id ?? null,
            playbook_release_id: playbook.release?.release_id ?? null,
            playbook_rule_id: rule.rule_id,
          } : null,
          comparator_draft_id: rule ? comparator?.draft_id ?? null : null,
        },
        treatment_delta: rule ? {
          comparator_draft_id: comparator?.draft_id ?? null,
          changed_family: rule.changed_family,
          changed_fields: actualChangedFields,
          expected_changed_fields: expectedFields,
          material: actualChangedFields.length > 0,
          exactly_one_hypothesis_family: undeclaredChanges.length === 0 && missingDeclaredChanges.length === 0,
        } : null,
        dimensions: {
          product: text(advertisedOffer),
          audience: text(targetAudience),
          offer: family === "QUALIFIED_ACTION" ? text(qualifiedResult)
            : family === "AUDIENCE_SPECIFICITY" ? `${text(coreMessage)}. Для: ${text(targetAudience)}` : text(coreMessage),
          keyword_cluster: clusterLabel,
        },
        delivery_key: bucket.delivery_key,
        market_evidence: {
          contract_version: marketEvidence.contract_version ?? "demand-cost-packing-v1",
          frequency,
          cost,
          packing: deliveryPacking,
        },
        market_evidence_status: demandReady ? "AVAILABLE" : demandPartial ? "PARTIAL" : "EVIDENCE_GAP",
        shortlist_eligible: publishEligibility === "ELIGIBLE",
        publish_eligibility: publishEligibility,
        publication_blockers: publicationBlockers,
        unsupported_fields: capability.unsupported_fields,
        capability_selection: capability,
        visibility,
        suppression_reason: suppressionReason,
        duplicate_of: duplicateOf,
        publish_projection: projection,
        publish_fingerprint: publishFingerprint,
        treatment_fingerprint: treatmentFingerprint,
      } as CampaignDraftCandidate;
      compiled.push(draft);
      if (!rule) comparator = draft;
    }
  }

  const scored = await scoreCampaignDrafts({
    drafts: compiled,
    model,
    strategy,
    analyticsEvidence,
    scoredAt: generatedAt,
  });
  for (const draft of scored) {
    candidateAudit.push({
      candidate_id: `draft-candidate:${draft.draft_id}`,
      candidate_type: "DRAFT",
      delivery_bucket_id: text(draft.delivery_bucket_id) || null,
      draft_id: draft.draft_id,
      visibility: draft.visibility,
      reason_code: draft.visibility === "VISIBLE" ? "VISIBLE:GENERATED_DRAFT" : text(draft.suppression_reason) || "HIDDEN:STRUCTURAL",
      playbook_release_id: draft.playbook_release_id,
      playbook_rule_id: draft.playbook_rule_id,
    });
  }
  candidateAudit.sort((left, right) => left.candidate_id.localeCompare(right.candidate_id));
  const visibleCount = candidateAudit.filter((item) => item.visibility === "VISIBLE").length;
  const hiddenCount = candidateAudit.length - visibleCount;
  const auditedDraftCount = candidateAudit.filter((item) => item.candidate_type === "DRAFT").length;
  const auditedNonDraftCount = candidateAudit.length - auditedDraftCount;
  const generatedCount = scored.length + auditedNonDraftCount;
  const representedLeafIds = new Set(scored.flatMap((draft) => Array.isArray(draft.covered_leaf_ids) ? draft.covered_leaf_ids.map(String) : []));
  const suppressedLeafIds = leafLedger.filter((leaf) => !representedLeafIds.has(leaf.leaf_id)).map((leaf) => leaf.leaf_id);
  const uncoveredLeafIds = leafLedger.filter((leaf) => !text(leaf.terminal_disposition)).map((leaf) => leaf.leaf_id);
  const generatedReconciles = generatedCount === candidateAudit.length && auditedDraftCount === scored.length;
  const recommendationSetId = `recommendation-set-${(await sha256({
    strategy_revision_id: strategyRevisionId,
    evidence_snapshot_id: analyticsEvidence?.snapshot_id ?? null,
    capability_profile: `${CORE_DIRECT_CAPABILITY_PROFILE.profile_id}@${CORE_DIRECT_CAPABILITY_PROFILE.profile_version}`,
    capability_snapshot_id: directCapabilitySnapshot?.snapshot_id ?? null,
    playbook_release_digest: playbook.release?.content_digest ?? null,
    publish_fingerprints: scored.map((draft) => draft.publish_fingerprint),
    candidate_audit: candidateAudit,
  })).slice("sha256:".length, "sha256:".length + 20)}`;
  return {
    schema_version: "campaign-recommendation-set-v3",
    recommendation_set_id: recommendationSetId,
    strategy_revision_id: strategyRevisionId,
    analytics_evidence_snapshot_id: analyticsEvidence?.snapshot_id ? String(analyticsEvidence.snapshot_id) : null,
    generated_at: generatedAt,
    capability_profile: {
      ...CORE_DIRECT_CAPABILITY_PROFILE,
      eligibility: coreCapability,
    },
    direct_capability_snapshot_id: directCapabilitySnapshot?.snapshot_id ?? null,
    playbook_release: {
      status: playbook.release ? "ACTIVE_APPROVED" : "BLOCKED_FAIL_CLOSED",
      release_id: playbook.release?.release_id ?? null,
      release_version: playbook.release?.release_version ?? null,
      content_digest: playbook.release?.content_digest ?? null,
      applied_rule_ids: activeRules.map((rule) => rule.rule_id),
      excluded_audit_ids: playbook.audits.map((audit) => audit.audit_id),
      mutable_default_read_at_query_time: false,
    },
    coverage: {
      status: uncoveredLeafIds.length === 0 && generatedReconciles ? "COMPLETE" : "INCOMPLETE",
      generated_count: generatedCount,
      visible_count: visibleCount,
      hidden_count: hiddenCount,
      candidates_total: candidateAudit.length,
      visible_drafts: scored.filter((draft) => draft.visibility === "VISIBLE").length,
      hidden_drafts: scored.filter((draft) => draft.visibility === "HIDDEN").length,
      audited_non_draft_candidates: auditedNonDraftCount,
      publishable_drafts: scored.filter((draft) => draft.publish_eligibility === "ELIGIBLE").length,
      evidence_gap_drafts: scored.filter((draft) => draft.market_evidence_status === "EVIDENCE_GAP").length,
      reconciliation: {
        generated_equals_visible_plus_hidden: generatedCount === visibleCount + hiddenCount,
        generated_equals_audited: generatedReconciles,
        unaudited_candidate_ids: generatedReconciles ? [] : candidateAudit.filter((candidate) => candidate.candidate_type === "DRAFT" && !scored.some((draft) => draft.draft_id === candidate.draft_id)).map((candidate) => candidate.candidate_id),
      },
      represented_leaf_ids: [...representedLeafIds].sort(),
      suppressed_leaf_ids: suppressedLeafIds.sort(),
      uncovered_leaf_ids: uncoveredLeafIds.sort(),
      uncovered_axis_members: leafLedger.length ? [] : [...productAxes, ...audienceAxes, ...offerAxes].map((member) => member.member_id),
    },
    candidate_audit: candidateAudit,
    axis_ledger: {
      products: productAxes,
      audiences: audienceAxes,
      offers: offerAxes,
      keyword_clusters: keywordAxes,
      leafs: leafLedger,
      finite_cartesian_upper_bound: productAxes.length * audienceAxes.length * offerAxes.length * keywordAxes.length,
      every_leaf_terminal: leafLedger.every((leaf) => text(leaf.terminal_disposition).length > 0),
    },
    termination: {
      contract: "FINITE_NON_RECURSIVE_ONE_PASS",
      recursion_allowed: false,
      delivery_buckets: buckets.length,
      comparators_per_bucket: 1,
      maximum_improvements_per_bucket: MAX_IMPROVEMENTS_PER_DELIVERY_BUCKET,
      maximum_drafts_per_bucket: 1 + MAX_IMPROVEMENTS_PER_DELIVERY_BUCKET,
      generated_draft_count: scored.length,
      all_candidates_terminal: candidateAudit.every((candidate) => ["VISIBLE", "HIDDEN"].includes(candidate.visibility)),
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
