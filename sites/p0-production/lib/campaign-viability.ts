import { strategyAnswerValue } from "./campaign-strategy.ts";

const SCORE_CONTRACT_VERSION = "viability-score/1.0.0";
const SCORE_SCHEMA_VERSION = "viability-score-result-v1";
const HIDDEN_THRESHOLD = 45;

const WEIGHTS = {
  demand: 0.18,
  cost: 0.12,
  economics: 0.2,
  offer_audience_fit: 0.18,
  direct_feasibility: 0.12,
  measurement: 0.1,
  evidence_quality: 0.1,
} as const;

type DimensionName = keyof typeof WEIGHTS;
type FeatureStatus = "KNOWN" | "UNKNOWN" | "CONFLICTING";

type ScoreFeature = {
  rule: string;
  input_pointers: string[];
  value: number;
  status: FeatureStatus;
  claim_ids: string[];
  evidence_ids: string[];
  uncertainty_group_id?: string;
};

type ScoreDimension = {
  value: number;
  lower: number;
  upper: number;
  weight: number;
  weighted_points: number;
  features: ScoreFeature[];
};

type EligibilityBlocker = {
  code: string;
  rule_id: string;
  rule_version: string;
  input_pointer: string;
  claim_ids: string[];
  evidence_ids: string[];
  remediation: string;
};

export type ViabilityScoreResult = {
  schema_version: typeof SCORE_SCHEMA_VERSION;
  contract_version: typeof SCORE_CONTRACT_VERSION;
  policy_status: "UNCALIBRATED_POLICY_V1";
  eligibility: {
    status: "ELIGIBLE" | "INELIGIBLE" | "BLOCKED_UNKNOWN";
    blockers: EligibilityBlocker[];
  };
  score: number | null;
  score_raw: number | null;
  score_lower: number | null;
  score_upper: number | null;
  uncertainty_width: number | null;
  rank: number | null;
  tied_draft_ids: string[];
  dimensions: Record<DimensionName, ScoreDimension> | null;
  visibility: {
    status: "VISIBLE" | "HIDDEN";
    reason: string | null;
    threshold_version: "score-hidden-v1";
  };
  explanation: {
    label: "COMPARATIVE_PRELAUNCH_PRIORITY_NOT_A_FORECAST";
    landing_audit_used: false;
    missing_dimensions: DimensionName[];
  };
  fingerprints: {
    input: string;
    cohort: string;
    policy: string;
    implementation_build: string;
  };
  scored_at: string;
};

type DraftCandidate = Record<string, unknown> & {
  draft_id: string;
  draft_revision_id: string;
  visibility: "VISIBLE" | "HIDDEN";
  suppression_reason?: string | null;
  viability_score?: ViabilityScoreResult;
};

type ScoreDraftsInput<T extends DraftCandidate> = {
  drafts: T[];
  model: Record<string, unknown>;
  strategy: Record<string, unknown>;
  analyticsEvidence?: Record<string, unknown> | null;
  scoredAt: string;
};

type PreparedDraft<T extends DraftCandidate> = {
  draft: T;
  eligibility: ReturnType<typeof evaluateEligibility>;
  dimensions: Record<DimensionName, ScoreDimension> | null;
  scoreRaw: number | null;
  scoreLower: number | null;
  scoreUpper: number | null;
  evidenceQuality: number;
  inputFingerprint: string;
};

const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};

const list = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
const text = (value: unknown) => String(value ?? "").normalize("NFKC").replace(/\s+/g, " ").trim();
const numberOrNull = (value: unknown) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};
const clamp = (value: number) => Math.min(100, Math.max(0, value));
const rounded = (value: number, precision = 0) => {
  const factor = 10 ** precision;
  return Math.round((value + Number.EPSILON) * factor) / factor;
};

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value
      .map(canonicalize)
      .sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
  }
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonicalize(item)]),
  );
}

async function sha256(value: unknown) {
  const bytes = new TextEncoder().encode(JSON.stringify(canonicalize(value)));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("");
}

function sourceById(evidence: Record<string, unknown> | null | undefined, sourceId: string) {
  return list(evidence?.sources).map(record).find((source) => text(source.source_id) === sourceId) ?? {};
}

function claimsFor(evidence: Record<string, unknown> | null | undefined, predicates: string[]) {
  const allowed = new Set(predicates);
  return list(evidence?.claims).map(record).filter((claim) => allowed.has(text(claim.predicate)));
}

function tierScore(claims: Record<string, unknown>[]) {
  const values = claims.map((claim) => {
    const confidence = record(claim.confidence);
    if (confidence.tier === "TIER_1_VERIFIED") return 100;
    if (confidence.tier === "TIER_3_INDICATIVE") return 75;
    if (confidence.tier === "BLOCKED_UNKNOWN") return 0;
    return 50;
  });
  return values.length ? Math.max(...values) : 50;
}

function evidenceLinks(claims: Record<string, unknown>[]) {
  return {
    claimIds: claims.map((claim) => text(claim.claim_id)).filter(Boolean).sort(),
    evidenceIds: [...new Set(claims.flatMap((claim) => list(claim.evidence_ids).map(text)).filter(Boolean))].sort(),
  };
}

function feature({
  rule,
  pointers,
  value,
  status = "KNOWN",
  claims = [],
  uncertaintyGroup,
}: {
  rule: string;
  pointers: string[];
  value: number;
  status?: FeatureStatus;
  claims?: Record<string, unknown>[];
  uncertaintyGroup?: string;
}): ScoreFeature {
  const links = evidenceLinks(claims);
  return {
    rule,
    input_pointers: pointers,
    value: clamp(value),
    status,
    claim_ids: links.claimIds,
    evidence_ids: links.evidenceIds,
    ...(uncertaintyGroup ? { uncertainty_group_id: uncertaintyGroup } : {}),
  };
}

function unknownFeature(rule: string, pointers: string[], uncertaintyGroup: string) {
  return feature({ rule, pointers, value: 50, status: "UNKNOWN", uncertaintyGroup });
}

function dimension(name: DimensionName, features: ScoreFeature[]): ScoreDimension {
  const value = features.reduce((sum, item) => sum + item.value, 0) / features.length;
  const lower = features.reduce((sum, item) => sum + (item.status === "KNOWN" ? item.value : 0), 0) / features.length;
  const upper = features.reduce((sum, item) => sum + (item.status === "KNOWN" ? item.value : 100), 0) / features.length;
  return {
    value: rounded(value, 4),
    lower: rounded(lower, 4),
    upper: rounded(upper, 4),
    weight: WEIGHTS[name],
    weighted_points: rounded(value * WEIGHTS[name], 4),
    features,
  };
}

function strategyBlockers(strategy: Record<string, unknown>) {
  const required = [
    "strategy_revision_id",
    "goal",
    "geography",
    "period_start",
    "period_end",
    "landing_page",
    "weekly_budget_rub",
    "target_cpa_rub",
    "message",
  ];
  return required.filter((field) => !text(strategy[field]));
}

function blocker(code: string, pointer: string, remediation: string): EligibilityBlocker {
  return {
    code,
    rule_id: `score-eligibility-${code.toLowerCase().replace(/_/g, "-")}`,
    rule_version: "1",
    input_pointer: pointer,
    claim_ids: [],
    evidence_ids: [],
    remediation,
  };
}

function evaluateEligibility(
  draft: DraftCandidate,
  model: Record<string, unknown>,
  strategy: Record<string, unknown>,
  evidence: Record<string, unknown> | null | undefined,
) {
  const blockers: EligibilityBlocker[] = [];
  const missingStrategy = strategyBlockers(strategy);
  if (!text(model.product) || !text(model.audience) || !text(model.qualified_result)) {
    blockers.push(blocker(
      "BUSINESS_MODEL_INCOMPLETE",
      "/business_model",
      "Подтвердить product, audience и qualified outcome в модели бизнеса.",
    ));
  }
  if (missingStrategy.length) {
    blockers.push(blocker(
      "STRATEGY_INCOMPLETE",
      `/strategy/${missingStrategy[0]}`,
      "Принять полную Campaign Strategy revision.",
    ));
  }
  if (!text(draft.draft_revision_id) || !record(draft.publish_projection).direct) {
    blockers.push(blocker(
      "PUBLISH_PROJECTION_INCOMPLETE",
      "/draft/publish_projection",
      "Скомпилировать и провалидировать exact Direct projection.",
    ));
  }
  if (text(draft.duplicate_of)) {
    blockers.push(blocker(
      "EXACT_DUPLICATE",
      "/draft/duplicate_of",
      "Использовать канонический Draft или создать material treatment delta.",
    ));
  }
  const evidenceBlockers = list(record(evidence?.summary).hard_blockers).map(text).filter(Boolean);
  for (const [index, item] of evidenceBlockers.entries()) {
    blockers.push(blocker(
      "EVIDENCE_HARD_BLOCKER",
      `/analytics_evidence/summary/hard_blockers/${index}`,
      item,
    ));
  }
  const structuralReason = text(draft.suppression_reason);
  if (/NO_DEMAND|INSUFFICIENT_STANDALONE_CAPACITY|HARD_INELIGIBLE|DUPLICATE_OR_OVERLAP/.test(structuralReason)) {
    blockers.push(blocker(
      "STRUCTURAL_INELIGIBILITY",
      "/draft/suppression_reason",
      structuralReason,
    ));
  }
  if (!evidence?.snapshot_id) {
    blockers.push(blocker(
      "EVIDENCE_SNAPSHOT_MISSING",
      "/analytics_evidence/snapshot_id",
      "Зафиксировать immutable Analytics Evidence Snapshot до scoring.",
    ));
  }
  return {
    status: blockers.length
      ? blockers.some((item) => item.code.includes("MISSING") || item.code === "EVIDENCE_HARD_BLOCKER")
        ? "BLOCKED_UNKNOWN" as const
        : "INELIGIBLE" as const
      : "ELIGIBLE" as const,
    blockers,
  };
}

function demandScope(frequency: Record<string, unknown>) {
  const explicit = text(frequency.scope_fingerprint) || text(frequency.request_fingerprint);
  if (explicit) return explicit;
  const parts = [
    frequency.source,
    frequency.method,
    frequency.operator_profile,
    JSON.stringify(frequency.region_ids ?? []),
    JSON.stringify(frequency.devices ?? []),
    frequency.declared_window,
  ].map(text);
  return parts.some(Boolean) ? parts.join("|") : "";
}

function demandObservation(draft: DraftCandidate) {
  const frequency = record(record(draft.market_evidence).frequency);
  const count = numberOrNull(record(frequency.observed_unique_count).value);
  const usable = ["AVAILABLE", "PARTIAL", "VERIFIED"].includes(text(frequency.status));
  return {
    frequency,
    count: usable && count !== null && count >= 0 ? count : null,
    scope: usable ? demandScope(frequency) : "",
  };
}

function costObservation(draft: DraftCandidate) {
  const cost = record(record(draft.market_evidence).cost);
  const range = record(cost.range);
  const low = numberOrNull(range.low);
  const high = numberOrNull(range.high);
  const weightedMean = numberOrNull(cost.weighted_historical_mean);
  const reference = low !== null && high !== null
    ? (low + high) / 2
    : weightedMean;
  const source = text(cost.compact_source);
  const comparability = record(cost.comparability);
  const usable = ["AVAILABLE", "VERIFIED"].includes(text(cost.status));
  const scope = usable && source
    ? `${source}|${JSON.stringify(canonicalize(comparability))}|${text(cost.currency)}|${text(cost.vat_mode)}`
    : "";
  return { cost, reference: usable && reference !== null && reference >= 0 ? reference : null, scope };
}

function midrankPercentiles(rows: Array<{ id: string; value: number; scope: string }>) {
  const result = new Map<string, number>();
  const grouped = Map.groupBy(rows, (row) => row.scope);
  for (const scopedRows of grouped.values()) {
    const sorted = [...scopedRows].sort((left, right) => left.value - right.value || left.id.localeCompare(right.id));
    if (sorted.length === 1) {
      result.set(sorted[0].id, 50);
      continue;
    }
    for (const row of sorted) {
      const equalIndexes = sorted
        .map((candidate, index) => candidate.value === row.value ? index : -1)
        .filter((index) => index >= 0);
      const averageIndex = equalIndexes.reduce((sum, index) => sum + index, 0) / equalIndexes.length;
      result.set(row.id, 100 * averageIndex / (sorted.length - 1));
    }
  }
  return result;
}

function seasonalityScore(frequency: Record<string, unknown>) {
  const seasonality = record(frequency.seasonality);
  const ratio = numberOrNull(seasonality.ratio);
  if (ratio === null || !["AVAILABLE", "VERIFIED"].includes(text(seasonality.status))) return null;
  if (ratio >= 1) return 100;
  if (ratio >= 0.75) return 75;
  if (ratio >= 0.5) return 50;
  return 25;
}

function hasVolumeScore(frequency: Record<string, unknown>) {
  const value = text(record(frequency.has_search_volume).all_devices);
  if (value === "YES") return 100;
  if (value === "NO") return 0;
  return null;
}

function economicsDimension(strategy: Record<string, unknown>, draft: DraftCandidate) {
  const weeklyBudget = numberOrNull(strategyAnswerValue(strategy, "weekly_budget"));
  const targetCost = numberOrNull(strategyAnswerValue(strategy, "target_result_cost"));
  const plannedUnits = weeklyBudget !== null && targetCost !== null && weeklyBudget > 0 && targetCost > 0
    ? weeklyBudget * (52 / 12) / targetCost
    : null;
  const capacityValue = plannedUnits === null
    ? null
    : plannedUnits < 3
      ? 0
      : plannedUnits < 5
        ? 25
        : plannedUnits < 10
          ? 50
          : plannedUnits < 20
            ? 75
            : 100;
  const { cost } = costObservation(draft);
  const high = numberOrNull(record(cost.range).high);
  const ratio = high !== null && targetCost !== null && targetCost > 0 ? high / targetCost : null;
  const ratioValue = ratio === null
    ? null
    : ratio <= 0.05
      ? 100
      : ratio <= 0.1
        ? 80
        : ratio <= 0.2
          ? 50
          : ratio <= 0.33
            ? 20
            : 0;
  const consistencyKnown = weeklyBudget !== null && weeklyBudget > 0 && targetCost !== null && targetCost > 0;
  return dimension("economics", [
    capacityValue === null
      ? unknownFeature("planned-result-units-v1", ["/strategy/weekly_budget_rub", "/strategy/target_cpa_rub"], "economics-inputs")
      : feature({ rule: "planned-result-units-v1", pointers: ["/strategy/weekly_budget_rub", "/strategy/target_cpa_rub"], value: capacityValue }),
    ratioValue === null
      ? unknownFeature("cost-to-target-ratio-v1", ["/draft/market_evidence/cost/range/high", "/strategy/target_cpa_rub"], "prelaunch-cost")
      : feature({ rule: "cost-to-target-ratio-v1", pointers: ["/draft/market_evidence/cost/range/high", "/strategy/target_cpa_rub"], value: ratioValue }),
    feature({
      rule: "economics-consistency-v1",
      pointers: ["/strategy/weekly_budget_rub", "/strategy/target_cpa_rub"],
      value: consistencyKnown ? 100 : 0,
    }),
  ]);
}

function semanticTokens(value: unknown) {
  return [...new Set(
    text(value)
      .toLocaleLowerCase("ru-RU")
      .replace(/[^\p{L}\p{N}]+/gu, " ")
      .split(" ")
      .filter((token) => token.length >= 4)
      .map((token) => token.length >= 7 ? token.slice(0, 6) : token),
  )];
}

function tokenCoverage(haystack: unknown, needle: unknown) {
  const wanted = semanticTokens(needle);
  if (!wanted.length) return null;
  const actual = new Set(semanticTokens(haystack));
  return wanted.filter((token) => actual.has(token)).length / wanted.length;
}

function messageAlignment(draft: DraftCandidate, model: Record<string, unknown>, strategy: Record<string, unknown>) {
  const variant = record(draft.variant);
  const hypothesis = record(variant.hypothesis);
  const family = text(hypothesis.changed_family);
  const anchor = family === "QUALIFIED_ACTION"
    ? strategyAnswerValue(strategy, "qualified_result") || model.qualified_result
    : family === "AUDIENCE_SPECIFICITY"
      ? strategyAnswerValue(strategy, "target_audience") || model.audience
      : strategyAnswerValue(strategy, "core_message") || model.value;
  const combined = [draft.keyword, draft.ad_title, draft.ad_text].map(text).join(" ");
  const productCoverage = tokenCoverage(combined, strategyAnswerValue(strategy, "advertised_offer") || model.product) ?? 0;
  const anchorCoverage = tokenCoverage(combined, anchor) ?? 0;
  const value = 100 * (0.55 * productCoverage + 0.45 * anchorCoverage);
  return value >= 85 ? 100 : value >= 60 ? 75 : value >= 30 ? 50 : 0;
}

function fitDimension(draft: DraftCandidate, model: Record<string, unknown>, strategy: Record<string, unknown>, evidence: Record<string, unknown> | null | undefined) {
  const productClaims = claimsFor(evidence, ["product"]);
  const audienceClaims = claimsFor(evidence, ["audience"]);
  const valueClaims = claimsFor(evidence, ["value"]);
  const outcomeClaims = claimsFor(evidence, ["qualified_result"]);
  return dimension("offer_audience_fit", [
    feature({ rule: "product-offer-supported-v1", pointers: ["/business_model/product"], value: tierScore(productClaims), status: productClaims.length ? "KNOWN" : "UNKNOWN", claims: productClaims, uncertaintyGroup: productClaims.length ? undefined : "business-fit" }),
    feature({ rule: "audience-need-supported-v1", pointers: ["/business_model/audience"], value: tierScore(audienceClaims), status: audienceClaims.length ? "KNOWN" : "UNKNOWN", claims: audienceClaims, uncertaintyGroup: audienceClaims.length ? undefined : "business-fit" }),
    feature({ rule: "offer-addresses-need-v1", pointers: ["/business_model/value", "/business_model/qualified_result"], value: rounded((tierScore(valueClaims) + tierScore(outcomeClaims)) / 2, 4), status: valueClaims.length && outcomeClaims.length ? "KNOWN" : "UNKNOWN", claims: [...valueClaims, ...outcomeClaims], uncertaintyGroup: valueClaims.length && outcomeClaims.length ? undefined : "business-fit" }),
    feature({ rule: "message-approved-alignment-v1", pointers: ["/draft/keyword", "/draft/ad_title", "/draft/ad_text"], value: messageAlignment(draft, model, strategy) }),
  ]);
}

function directDimension(draft: DraftCandidate, evidence: Record<string, unknown> | null | undefined) {
  const source = sourceById(evidence, "direct");
  const sourceStatus = text(source.status);
  const projection = record(record(draft.publish_projection).direct);
  const campaign = record(projection.campaign);
  const group = record(projection.ad_group);
  const keyword = record(projection.keyword);
  const ad = record(projection.ad);
  const bidding = record(record(record(campaign.UnifiedCampaign).BiddingStrategy));
  const search = record(bidding.Search);
  const network = record(bidding.Network);
  const expectedCore =
    text(search.BiddingStrategyType) === "WB_MAXIMUM_CLICKS"
    && text(network.BiddingStrategyType) === "SERVING_OFF";
  return dimension("direct_feasibility", [
    sourceStatus === "VERIFIED" || sourceStatus === "PARTIAL"
      ? feature({ rule: "direct-account-currency-ready-v1", pointers: ["/analytics_evidence/sources/direct"], value: 100 })
      : unknownFeature("direct-account-currency-ready-v1", ["/analytics_evidence/sources/direct"], "direct-account-preflight"),
    feature({ rule: "direct-campaign-group-core-v1", pointers: ["/draft/publish_projection/direct/campaign", "/draft/publish_projection/direct/ad_group"], value: campaign.UnifiedCampaign && group.UnifiedAdGroup ? 100 : 0 }),
    feature({ rule: "direct-strategy-placement-core-v1", pointers: ["/draft/publish_projection/direct/campaign/UnifiedCampaign/BiddingStrategy"], value: expectedCore ? 100 : 0 }),
    feature({ rule: "direct-criteria-ad-core-v1", pointers: ["/draft/publish_projection/direct/keyword", "/draft/publish_projection/direct/ad"], value: text(keyword.Keyword) && record(ad.TextAd).Title ? 100 : 0 }),
    unknownFeature("direct-live-limits-fit-v1", ["/direct_capability/restrictions"], "direct-live-restrictions"),
    feature({ rule: "direct-local-schema-policy-v1", pointers: ["/draft/publish_projection/schema_version"], value: text(record(draft.publish_projection).schema_version) ? 100 : 0 }),
  ]);
}

function measurementDimension(evidence: Record<string, unknown> | null | undefined) {
  const source = sourceById(evidence, "metrika");
  const status = text(source.status);
  const known = status === "VERIFIED" || status === "PARTIAL";
  const verifiedValue = status === "VERIFIED" ? 100 : status === "PARTIAL" ? 75 : 50;
  return dimension("measurement", [
    known ? feature({ rule: "metrika-counter-readable-v1", pointers: ["/analytics_evidence/sources/metrika"], value: verifiedValue }) : unknownFeature("metrika-counter-readable-v1", ["/analytics_evidence/sources/metrika"], "measurement-binding"),
    known ? feature({ rule: "metrika-goal-active-v1", pointers: ["/analytics_evidence/sources/metrika"], value: verifiedValue }) : unknownFeature("metrika-goal-active-v1", ["/analytics_evidence/sources/metrika"], "measurement-binding"),
    unknownFeature("goal-qualified-outcome-mapping-v1", ["/measurement/goal_mapping"], "measurement-semantics"),
    unknownFeature("landing-counter-binding-v1", ["/measurement/landing_binding"], "measurement-binding"),
    unknownFeature("attribution-timezone-window-v1", ["/measurement/attribution_contract"], "measurement-semantics"),
    unknownFeature("diagnostic-maturity-contract-v1", ["/measurement/maturity_contract"], "measurement-semantics"),
  ]);
}

function claimQuality(claim: Record<string, unknown>, materialUncertaintyCount: number) {
  const confidence = record(claim.confidence);
  const source = { A: 100, B: 80, C: 60, D: 30, U: 0 }[text(confidence.quality ?? confidence.source_quality)] ?? 0;
  const freshness = { current: 100, aging: 70, stale: 30, unknown: 0 }[text(confidence.freshness)] ?? 0;
  const consistency = { corroborated: 100, single: 70, conflicted: 20, scope_mismatch: 0, not_evaluated: 0 }[text(confidence.consistency)] ?? 0;
  const coverage = { complete_for_scope: 100, sampled_with_denominator: 70, partial: 40, unknown: 0 }[text(confidence.coverage)] ?? 0;
  const uncertainty = Math.max(0, 100 - 20 * materialUncertaintyCount);
  return (source + freshness + consistency + coverage + uncertainty) / 5;
}

function evidenceQualityDimension(evidence: Record<string, unknown> | null | undefined) {
  const materialPredicates = new Set(["product", "audience", "value", "qualified_result", "campaign_inventory", "observed_performance"]);
  const claims = list(evidence?.claims).map(record).filter((claim) => materialPredicates.has(text(claim.predicate)));
  const uncertaintyCount = list(evidence?.material_uncertainties).length;
  if (!claims.length) {
    return dimension("evidence_quality", [feature({ rule: "material-claim-quality-v1", pointers: ["/analytics_evidence/claims"], value: 0 })]);
  }
  return dimension("evidence_quality", claims.map((claim) => feature({
    rule: "material-claim-quality-v1",
    pointers: [`/analytics_evidence/claims/${text(claim.claim_id)}`],
    value: claimQuality(claim, uncertaintyCount),
    claims: [claim],
  })));
}

function buildDimensions(
  draft: DraftCandidate,
  model: Record<string, unknown>,
  strategy: Record<string, unknown>,
  evidence: Record<string, unknown> | null | undefined,
  demandPercentile: number | undefined,
  costPercentile: number | undefined,
) {
  const { frequency } = demandObservation(draft);
  const volume = demandPercentile;
  const hasVolume = hasVolumeScore(frequency);
  const seasonality = seasonalityScore(frequency);
  const demand = dimension("demand", [
    volume === undefined
      ? unknownFeature("comparable-demand-midrank-v1", ["/draft/market_evidence/frequency/observed_unique_count"], "demand-volume")
      : feature({ rule: "comparable-demand-midrank-v1", pointers: ["/draft/market_evidence/frequency/observed_unique_count"], value: volume }),
    hasVolume === null
      ? unknownFeature("direct-has-search-volume-v1", ["/draft/market_evidence/frequency/has_search_volume/all_devices"], "demand-volume")
      : feature({ rule: "direct-has-search-volume-v1", pointers: ["/draft/market_evidence/frequency/has_search_volume/all_devices"], value: hasVolume }),
    seasonality === null
      ? unknownFeature("same-period-seasonality-v1", ["/draft/market_evidence/frequency/seasonality/ratio"], "demand-seasonality")
      : feature({ rule: "same-period-seasonality-v1", pointers: ["/draft/market_evidence/frequency/seasonality/ratio"], value: seasonality }),
  ]);
  const cost = dimension("cost", [
    costPercentile === undefined
      ? unknownFeature("comparable-cost-midrank-v1", ["/draft/market_evidence/cost"], "prelaunch-cost")
      : feature({ rule: "comparable-cost-midrank-v1", pointers: ["/draft/market_evidence/cost"], value: 100 - costPercentile }),
  ]);
  return {
    demand,
    cost,
    economics: economicsDimension(strategy, draft),
    offer_audience_fit: fitDimension(draft, model, strategy, evidence),
    direct_feasibility: directDimension(draft, evidence),
    measurement: measurementDimension(evidence),
    evidence_quality: evidenceQualityDimension(evidence),
  };
}

function weightedResult(dimensions: Record<DimensionName, ScoreDimension>) {
  const names = Object.keys(WEIGHTS) as DimensionName[];
  return {
    raw: names.reduce((sum, name) => sum + dimensions[name].value * WEIGHTS[name], 0),
    lower: names.reduce((sum, name) => sum + dimensions[name].lower * WEIGHTS[name], 0),
    upper: names.reduce((sum, name) => sum + dimensions[name].upper * WEIGHTS[name], 0),
  };
}

function intervalsOverlap(left: PreparedDraft<DraftCandidate>, right: PreparedDraft<DraftCandidate>) {
  return Number(left.scoreLower) <= Number(right.scoreUpper) && Number(right.scoreLower) <= Number(left.scoreUpper);
}

export async function scoreCampaignDrafts<T extends DraftCandidate>({
  drafts,
  model,
  strategy,
  analyticsEvidence,
  scoredAt,
}: ScoreDraftsInput<T>): Promise<T[]> {
  const demandRows = drafts.map((draft) => {
    const observation = demandObservation(draft);
    return observation.count !== null && observation.scope
      ? { id: draft.draft_id, value: Math.log1p(observation.count), scope: observation.scope }
      : null;
  }).filter((row): row is { id: string; value: number; scope: string } => Boolean(row));
  const costRows = drafts.map((draft) => {
    const observation = costObservation(draft);
    return observation.reference !== null && observation.scope
      ? { id: draft.draft_id, value: observation.reference, scope: observation.scope }
      : null;
  }).filter((row): row is { id: string; value: number; scope: string } => Boolean(row));
  const demandPercentiles = midrankPercentiles(demandRows);
  const costPercentiles = midrankPercentiles(costRows);
  const cohortFingerprint = await sha256({
    strategy_revision_id: strategy.strategy_revision_id,
    evidence_snapshot_id: analyticsEvidence?.snapshot_id ?? "UNAVAILABLE",
    draft_revision_ids: drafts.map((draft) => draft.draft_revision_id).sort(),
    demand_rows: demandRows,
    cost_rows: costRows,
  });
  const policyFingerprint = await sha256({
    contract: SCORE_CONTRACT_VERSION,
    weights: WEIGHTS,
    hidden_threshold: HIDDEN_THRESHOLD,
    unknown_midpoint: 50,
  });

  const prepared: PreparedDraft<T>[] = [];
  for (const draft of drafts) {
    const eligibility = evaluateEligibility(draft, model, strategy, analyticsEvidence);
    const dimensions = eligibility.status === "ELIGIBLE"
      ? buildDimensions(
          draft,
          model,
          strategy,
          analyticsEvidence,
          demandPercentiles.get(draft.draft_id),
          costPercentiles.get(draft.draft_id),
        )
      : null;
    const values = dimensions ? weightedResult(dimensions) : null;
    prepared.push({
      draft,
      eligibility,
      dimensions,
      scoreRaw: values ? rounded(values.raw, 4) : null,
      scoreLower: values ? Math.floor(values.lower) : null,
      scoreUpper: values ? Math.ceil(values.upper) : null,
      evidenceQuality: dimensions?.evidence_quality.value ?? 0,
      inputFingerprint: await sha256({
        contract: SCORE_CONTRACT_VERSION,
        draft_revision_id: draft.draft_revision_id,
        draft_fields: {
          keyword: draft.keyword,
          ad_title: draft.ad_title,
          ad_text: draft.ad_text,
          projection: draft.publish_projection,
          market_evidence: draft.market_evidence ?? null,
        },
        strategy,
        evidence_snapshot_id: analyticsEvidence?.snapshot_id ?? "UNAVAILABLE",
      }),
    });
  }

  const ranked = prepared
    .filter((item) => item.scoreRaw !== null)
    .sort((left, right) =>
      Number(right.scoreRaw) - Number(left.scoreRaw)
      || right.evidenceQuality - left.evidenceQuality
      || (Number(left.scoreUpper) - Number(left.scoreLower)) - (Number(right.scoreUpper) - Number(right.scoreLower))
      || left.draft.draft_id.localeCompare(right.draft.draft_id)
    );
  const ranks = new Map<string, number>();
  for (const [index, item] of ranked.entries()) {
    const previous = ranked[index - 1];
    const tied = previous
      && Math.abs(Number(previous.scoreRaw) - Number(item.scoreRaw)) <= 0.5
      && Math.abs(previous.evidenceQuality - item.evidenceQuality) <= 0.5
      && intervalsOverlap(previous as PreparedDraft<DraftCandidate>, item as PreparedDraft<DraftCandidate>);
    ranks.set(item.draft.draft_id, tied ? Number(ranks.get(previous.draft.draft_id)) : index + 1);
  }

  return prepared.map((item) => {
    const rank = ranks.get(item.draft.draft_id) ?? null;
    const tiedDraftIds = rank === null
      ? []
      : ranked.filter((candidate) => ranks.get(candidate.draft.draft_id) === rank).map((candidate) => candidate.draft.draft_id).sort();
    const unresolvedGap = text(item.draft.market_evidence_status) === "EVIDENCE_GAP"
      || Object.values(item.dimensions ?? {}).some((value) => value.features.some((entry) => entry.status !== "KNOWN"));
    const scoreHidden = item.scoreUpper !== null
      && item.scoreUpper < HIDDEN_THRESHOLD
      && item.evidenceQuality >= 60
      && !unresolvedGap;
    const structurallyHidden = item.draft.visibility === "HIDDEN";
    const visibility = structurallyHidden || scoreHidden ? "HIDDEN" as const : "VISIBLE" as const;
    const reason = structurallyHidden
      ? text(item.draft.suppression_reason) || "HIDDEN:STRUCTURAL"
      : scoreHidden
        ? "HIDDEN:VIABILITY_THRESHOLD_V1"
        : null;
    const missingDimensions = item.dimensions
      ? (Object.entries(item.dimensions) as Array<[DimensionName, ScoreDimension]>)
          .filter(([, value]) => value.features.some((entry) => entry.status !== "KNOWN"))
          .map(([name]) => name)
      : [];
    const result: ViabilityScoreResult = {
      schema_version: SCORE_SCHEMA_VERSION,
      contract_version: SCORE_CONTRACT_VERSION,
      policy_status: "UNCALIBRATED_POLICY_V1",
      eligibility: item.eligibility,
      score: item.scoreRaw === null ? null : rounded(item.scoreRaw),
      score_raw: item.scoreRaw,
      score_lower: item.scoreLower,
      score_upper: item.scoreUpper,
      uncertainty_width: item.scoreLower === null || item.scoreUpper === null ? null : item.scoreUpper - item.scoreLower,
      rank,
      tied_draft_ids: tiedDraftIds,
      dimensions: item.dimensions,
      visibility: { status: visibility, reason, threshold_version: "score-hidden-v1" },
      explanation: {
        label: "COMPARATIVE_PRELAUNCH_PRIORITY_NOT_A_FORECAST",
        landing_audit_used: false,
        missing_dimensions: missingDimensions,
      },
      fingerprints: {
        input: item.inputFingerprint,
        cohort: cohortFingerprint,
        policy: policyFingerprint,
        implementation_build: "sites-p0-viability-v1",
      },
      scored_at: scoredAt,
    };
    return {
      ...item.draft,
      visibility,
      suppression_reason: reason,
      viability_score: result,
    };
  });
}

export function explainScoreDelta(
  previous: ViabilityScoreResult | undefined,
  current: ViabilityScoreResult | undefined,
  changedPointers: string[],
) {
  const names = Object.keys(WEIGHTS) as DimensionName[];
  return {
    schema_version: "viability-score-delta-v1",
    contract_version: SCORE_CONTRACT_VERSION,
    changed_pointers: [...changedPointers].sort(),
    score: {
      previous: previous?.score ?? null,
      current: current?.score ?? null,
      delta: previous?.score !== null && previous?.score !== undefined && current?.score !== null && current?.score !== undefined
        ? current.score - previous.score
        : null,
    },
    rank: { previous: previous?.rank ?? null, current: current?.rank ?? null },
    eligibility: {
      previous: previous?.eligibility.status ?? null,
      current: current?.eligibility.status ?? null,
    },
    dimensions: Object.fromEntries(names.map((name) => {
      const before = previous?.dimensions?.[name]?.weighted_points ?? null;
      const after = current?.dimensions?.[name]?.weighted_points ?? null;
      return [name, {
        previous_weighted_points: before,
        current_weighted_points: after,
        delta: before === null || after === null ? null : rounded(after - before, 4),
      }];
    })),
    fingerprints: {
      previous_input: previous?.fingerprints.input ?? null,
      current_input: current?.fingerprints.input ?? null,
      same_policy: previous?.fingerprints.policy === current?.fingerprints.policy,
      same_cohort: previous?.fingerprints.cohort === current?.fingerprints.cohort,
    },
  };
}

export const viabilityScorePolicy = {
  contract_version: SCORE_CONTRACT_VERSION,
  schema_version: SCORE_SCHEMA_VERSION,
  weights: WEIGHTS,
  hidden_threshold: HIDDEN_THRESHOLD,
  label: "COMPARATIVE_PRELAUNCH_PRIORITY_NOT_A_FORECAST",
  landing_audit_used: false,
} as const;
