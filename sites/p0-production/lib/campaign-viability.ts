import { strategyAnswerValue, strategyPeriod } from "./campaign-strategy.ts";

const SCORE_CONTRACT_VERSION = "viability-score/1.0.0";
const SCORE_SCHEMA_VERSION = "viability-score-result-v1";
const SCORE_THRESHOLD_VERSION = "score-hidden-v1";
const HIDDEN_THRESHOLD = 45;
const MINIMUM_HIDING_EVIDENCE_QUALITY = 60;
const UNKNOWN_MIDPOINT = 50;
const SCORE_LABEL = "COMPARATIVE PRELAUNCH PRIORITY / NOT A PREDICTION";
const SCORE_HIDDEN_REASON = "HIDDEN:VIABILITY_SENSITIVITY_UPPER_BELOW_45_V1";
const FORBIDDEN_INPUT_FIELD = /(?:landing.*advisory|advisory.*landing|post.*launch|launch.*outcome|campaign.*outcome|moderation.*outcome|outcome.*learning|calibrat)/iu;

const WEIGHTS_PERCENT = {
  demand: 18,
  cost: 12,
  economics: 20,
  offer_audience_fit: 18,
  direct_feasibility: 12,
  measurement_readiness: 10,
  evidence_quality: 10,
} as const;

const WEIGHTS = {
  demand: 0.18,
  cost: 0.12,
  economics: 0.2,
  offer_audience_fit: 0.18,
  direct_feasibility: 0.12,
  measurement_readiness: 0.1,
  evidence_quality: 0.1,
} as const;

const WEIGHT_SUM_PERCENT = Object.values(WEIGHTS_PERCENT).reduce((sum, weight) => sum + weight, 0);
if (WEIGHT_SUM_PERCENT !== 100) throw new Error("Viability score weights must sum exactly to 100%.");

export type DimensionName = keyof typeof WEIGHTS;
type FeatureStatus = "KNOWN" | "UNKNOWN" | "CONFLICTING";

type EvidencePointer = {
  input_pointer: string;
  claim_ids: string[];
  evidence_ids: string[];
};

type ScoreFeature = {
  rule: string;
  input_pointers: string[];
  value: number;
  status: FeatureStatus;
  midpoint_applied: boolean;
  unknown_reason: string | null;
  claim_ids: string[];
  evidence_ids: string[];
  uncertainty_group_id?: string;
};

export type ScoreDimension = {
  state: "KNOWN" | "UNKNOWN";
  value: number;
  observed_known_value: number | null;
  lower: number;
  upper: number;
  weight: number;
  weight_percent: number;
  weighted_contribution: number;
  weighted_points: number;
  midpoint: {
    applied: boolean;
    value: 50 | null;
    reason: string | null;
  };
  unknown_input_rules: string[];
  evidence_pointers: EvidencePointer[];
  features: ScoreFeature[];
};

export type EligibilityBlocker = {
  code: string;
  rule_id: string;
  rule_version: string;
  input_pointer: string;
  claim_ids: string[];
  evidence_ids: string[];
  remediation: string;
};

export type EvidenceGapDisclosure = {
  code: string;
  gap_id: string | null;
  source_id: string | null;
  input_pointer: string;
  description: string;
  required: boolean;
};

type VisibilityResult = {
  status: "VISIBLE" | "HIDDEN";
  reason: string | null;
  threshold_contract_version: typeof SCORE_THRESHOLD_VERSION;
  decision: "STRUCTURAL_REASON_PRECEDENCE" | "SCORE_THRESHOLD_APPLIED" | "REVIEW_VISIBLE";
  gates: {
    structural_reason: string | null;
    sensitivity_upper: number | null;
    upper_threshold_exclusive: 45;
    upper_below_threshold: boolean;
    evidence_quality: number | null;
    minimum_evidence_quality_inclusive: 60;
    evidence_quality_sufficient: boolean;
    unresolved_evidence_gap: boolean;
    applied_by_score: boolean;
  };
};

export type ViabilityScoreResult = {
  schema_version: typeof SCORE_SCHEMA_VERSION;
  contract_version: typeof SCORE_CONTRACT_VERSION;
  policy_status: "UNCALIBRATED_POLICY_V1";
  eligibility: {
    evaluated_before_score: true;
    status: "ELIGIBLE" | "INELIGIBLE" | "BLOCKED_UNKNOWN";
    blockers: EligibilityBlocker[];
  };
  evidence_gaps: {
    evaluated_before_score: true;
    status: "RESOLVED" | "UNRESOLVED";
    required: EvidenceGapDisclosure[];
    optional: EvidenceGapDisclosure[];
  };
  score: number | null;
  score_raw: number | null;
  score_lower: number | null;
  score_upper: number | null;
  uncertainty_width: number | null;
  sensitivity: {
    method: "UNKNOWN_DIMENSIONS_RECOMPUTED_AT_0_AND_100;_KNOWN_DIMENSIONS_FIXED";
    midpoint_value: 50;
    unknown_dimensions: DimensionName[];
    lower: { score: number | null; unknown_dimensions_value: 0; known_dimensions_fixed: true };
    upper: { score: number | null; unknown_dimensions_value: 100; known_dimensions_fixed: true };
  };
  rank: number | null;
  tied_draft_ids: string[];
  ranking: {
    status: "RANKED" | "BLOCKED_HARD_ELIGIBILITY" | "BLOCKED_EVIDENCE_GAP" | "STRUCTURALLY_NON_COMPARABLE";
    recommendation_set_id: string;
    cohort_id: string;
    comparable_set_id: string | null;
    rank: number | null;
    tied_draft_ids: string[];
    semantic_tie_rule: "EXACT_SCORE_RAW_EQUALITY_WITHIN_COHORT";
    stable_id_display_order_only: true;
  };
  dimensions: Record<DimensionName, ScoreDimension> | null;
  scopes: {
    frequency: Record<string, unknown>;
    cost: Record<string, unknown>;
  };
  visibility: VisibilityResult;
  explanation: {
    label: typeof SCORE_LABEL;
    comparative_not_predictive: true;
    landing_advisory_used: false;
    post_launch_inputs_used: false;
    calibration_used: false;
    unknown_midpoint_value: 50;
    missing_dimensions: DimensionName[];
    forbidden_inputs: readonly string[];
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
  recommendationSetId: string;
  drafts: T[];
  model: Record<string, unknown>;
  strategy: Record<string, unknown>;
  analyticsEvidence?: Record<string, unknown> | null;
  scoredAt: string;
};

type Prerequisites = {
  eligibility: ReturnType<typeof evaluateEligibility>;
  evidenceGaps: ReturnType<typeof evaluateEvidenceGaps>;
  structuralReason: string | null;
};

type PreparedDraft<T extends DraftCandidate> = Prerequisites & {
  draft: T;
  cohortId: string;
  dimensions: Record<DimensionName, ScoreDimension> | null;
  scoreRaw: number | null;
  scoreLower: number | null;
  scoreUpper: number | null;
  evidenceQuality: number | null;
  comparableSetId: string | null;
  rank: number | null;
  tiedDraftIds: string[];
  inputFingerprint: string;
};

const FORBIDDEN_INPUTS = Object.freeze([
  "LandingAdvisoryRun",
  "landing_advisory",
  "post_launch_outcomes",
  "campaign_outcomes",
  "moderation_outcomes",
  "outcome_learning",
  "calibration",
] as const);

const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};

const list = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
const text = (value: unknown) => String(value ?? "").normalize("NFKC").replace(/\s+/g, " ").trim();
const numberOrNull = (value: unknown) => {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};
const clamp = (value: number) => Math.min(100, Math.max(0, value));
const rounded = (value: number, precision = 0) => {
  const factor = 10 ** precision;
  return Math.round((value + Number.EPSILON) * factor) / factor;
};
const boundedText = (value: unknown, maximum = 500) => text(value).slice(0, maximum);
const boundedStrings = (value: unknown, maximumItems = 32, maximumLength = 500) =>
  [...new Set(list(value).map((item) => boundedText(item, maximumLength)).filter(Boolean))].sort().slice(0, maximumItems);

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
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
  return `sha256:${[...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("")}`;
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
  return values.length ? Math.max(...values) : UNKNOWN_MIDPOINT;
}

function evidenceLinks(claims: Record<string, unknown>[], additionalEvidenceIds: string[] = []) {
  return {
    claimIds: boundedStrings(claims.map((claim) => claim.claim_id)),
    evidenceIds: boundedStrings([
      ...claims.flatMap((claim) => list(claim.evidence_ids)),
      ...additionalEvidenceIds,
    ]),
  };
}

function feature({
  rule,
  pointers,
  value,
  status = "KNOWN",
  claims = [],
  evidenceIds = [],
  uncertaintyGroup,
  unknownReason,
}: {
  rule: string;
  pointers: string[];
  value: number;
  status?: FeatureStatus;
  claims?: Record<string, unknown>[];
  evidenceIds?: string[];
  uncertaintyGroup?: string;
  unknownReason?: string;
}): ScoreFeature {
  const links = evidenceLinks(claims, evidenceIds);
  const unknown = status !== "KNOWN";
  return {
    rule: boundedText(rule, 255),
    input_pointers: boundedStrings(pointers, 16, 500),
    value: unknown ? UNKNOWN_MIDPOINT : clamp(value),
    status,
    midpoint_applied: unknown,
    unknown_reason: unknown ? boundedText(unknownReason || "Optional pre-launch input is unavailable; midpoint 50 is disclosed, not observed.", 500) : null,
    claim_ids: links.claimIds,
    evidence_ids: links.evidenceIds,
    ...(uncertaintyGroup ? { uncertainty_group_id: boundedText(uncertaintyGroup, 255) } : {}),
  };
}

function unknownFeature(rule: string, pointers: string[], uncertaintyGroup: string, reason?: string) {
  return feature({ rule, pointers, value: UNKNOWN_MIDPOINT, status: "UNKNOWN", uncertaintyGroup, unknownReason: reason });
}

function dimension(name: DimensionName, features: ScoreFeature[]): ScoreDimension {
  if (!features.length) throw new Error(`Viability dimension ${name} must contain at least one feature.`);
  const unknownFeatures = features.filter((item) => item.status !== "KNOWN");
  const knownFeatures = features.filter((item) => item.status === "KNOWN");
  const state = unknownFeatures.length ? "UNKNOWN" as const : "KNOWN" as const;
  const observedKnownValue = knownFeatures.length
    ? rounded(knownFeatures.reduce((sum, item) => sum + item.value, 0) / knownFeatures.length, 4)
    : null;
  const value = state === "UNKNOWN"
    ? UNKNOWN_MIDPOINT
    : rounded(features.reduce((sum, item) => sum + item.value, 0) / features.length, 4);
  const evidencePointers = features.flatMap((item) => item.input_pointers.map((inputPointer) => ({
    input_pointer: inputPointer,
    claim_ids: item.claim_ids,
    evidence_ids: item.evidence_ids,
  })));
  const uniquePointers = [...new Map(evidencePointers.map((pointer) => [JSON.stringify(pointer), pointer])).values()].slice(0, 32);
  const weightedContribution = rounded(value * WEIGHTS[name], 4);
  return {
    state,
    value,
    observed_known_value: observedKnownValue,
    lower: state === "UNKNOWN" ? 0 : value,
    upper: state === "UNKNOWN" ? 100 : value,
    weight: WEIGHTS[name],
    weight_percent: WEIGHTS_PERCENT[name],
    weighted_contribution: weightedContribution,
    weighted_points: weightedContribution,
    midpoint: {
      applied: state === "UNKNOWN",
      value: state === "UNKNOWN" ? 50 : null,
      reason: state === "UNKNOWN" ? "At least one optional input is unknown/unavailable; this whole comparative dimension uses disclosed midpoint 50." : null,
    },
    unknown_input_rules: unknownFeatures.map((item) => item.rule).sort(),
    evidence_pointers: uniquePointers,
    features,
  };
}

function blocker(
  code: string,
  pointer: string,
  remediation: string,
  links: { claimIds?: string[]; evidenceIds?: string[] } = {},
): EligibilityBlocker {
  return {
    code: boundedText(code, 255),
    rule_id: `score-eligibility-${code.toLowerCase().replace(/_/g, "-")}`,
    rule_version: "1",
    input_pointer: boundedText(pointer, 500),
    claim_ids: boundedStrings(links.claimIds ?? []),
    evidence_ids: boundedStrings(links.evidenceIds ?? []),
    remediation: boundedText(remediation, 1_000),
  };
}

function requiredStrategyFields(strategy: Record<string, unknown>) {
  const period = strategyPeriod(strategy);
  const values: Record<string, unknown> = {
    strategy_revision_id: strategy.strategy_revision_id,
    business_goal: strategyAnswerValue(strategy, "business_goal"),
    advertised_offer: strategyAnswerValue(strategy, "advertised_offer"),
    target_audience: strategyAnswerValue(strategy, "target_audience"),
    qualified_result: strategyAnswerValue(strategy, "qualified_result"),
    exclusions: strategyAnswerValue(strategy, "exclusions"),
    geography: strategyAnswerValue(strategy, "geography"),
    period_start: period.start_date,
    period_end: period.end_date,
    landing_page: strategyAnswerValue(strategy, "landing_page"),
    weekly_budget: strategyAnswerValue(strategy, "weekly_budget"),
    target_result_cost: strategyAnswerValue(strategy, "target_result_cost"),
    core_message: strategyAnswerValue(strategy, "core_message"),
  };
  return Object.entries(values).filter(([, value]) => !text(value)).map(([key]) => key);
}

function structuralReason(draft: DraftCandidate) {
  const reason = text(draft.suppression_reason);
  if (draft.visibility !== "HIDDEN") return null;
  if (reason === SCORE_HIDDEN_REASON || reason === "HIDDEN:VIABILITY_THRESHOLD_V1") return null;
  return reason || "HIDDEN:STRUCTURAL";
}

function publicationBlockers(draft: DraftCandidate) {
  return list(draft.publication_blockers).map(record);
}

function evaluateEligibility(
  draft: DraftCandidate,
  model: Record<string, unknown>,
  strategy: Record<string, unknown>,
  evidence: Record<string, unknown> | null | undefined,
) {
  const blockers: EligibilityBlocker[] = [];
  if (!text(model.product) || !text(model.audience) || !text(model.qualified_result)) {
    blockers.push(blocker("BUSINESS_MODEL_INCOMPLETE", "/business_model", "Подтвердить product, audience и qualified outcome в модели бизнеса."));
  }
  const missingStrategy = requiredStrategyFields(strategy);
  if (missingStrategy.length) {
    blockers.push(blocker("STRATEGY_INCOMPLETE", `/strategy/${missingStrategy[0]}`, "Принять полную Campaign Strategy revision."));
  }
  if (!text(draft.draft_revision_id) || !record(draft.publish_projection).direct) {
    blockers.push(blocker("PUBLISH_PROJECTION_INCOMPLETE", "/draft/publish_projection", "Скомпилировать и провалидировать exact Direct projection."));
  }
  if (text(draft.duplicate_of)) {
    blockers.push(blocker("EXACT_DUPLICATE", "/draft/duplicate_of", "Использовать канонический Draft или создать material treatment delta."));
  }
  const structural = structuralReason(draft);
  if (structural) {
    blockers.push(blocker("STRUCTURAL_DISPOSITION", "/draft/suppression_reason", structural));
  }
  const persistedPublicationBlockers = publicationBlockers(draft);
  for (const [index, item] of persistedPublicationBlockers.entries()) {
    const code = text(item.code) || "PUBLICATION_BLOCKER";
    if (code.includes("EVIDENCE_GAP")) continue;
    blockers.push(blocker(
      `PUBLICATION_${code}`,
      text(item.field_path) || `/draft/publication_blockers/${index}`,
      text(item.message) || code,
    ));
  }
  if (text(draft.publish_eligibility) === "BLOCKED_HARD" && !persistedPublicationBlockers.some((item) => !text(item.code).includes("EVIDENCE_GAP"))) {
    blockers.push(blocker("PUBLICATION_HARD_BLOCKED", "/draft/publish_eligibility", "Resolve the persisted hard publication blocker before comparative scoring."));
  }
  const evidenceBlockers = list(record(evidence?.summary).hard_blockers).map(text).filter(Boolean);
  for (const [index, item] of evidenceBlockers.entries()) {
    blockers.push(blocker("EVIDENCE_HARD_BLOCKER", `/analytics_evidence/summary/hard_blockers/${index}`, item));
  }
  if (!text(evidence?.snapshot_id)) {
    blockers.push(blocker("EVIDENCE_SNAPSHOT_MISSING", "/analytics_evidence/snapshot_id", "Зафиксировать immutable Analytics Evidence Snapshot до scoring."));
  }
  const unknown = blockers.some((item) => [
    "EVIDENCE_HARD_BLOCKER",
    "EVIDENCE_SNAPSHOT_MISSING",
  ].includes(item.code) || item.code.includes("CAPABILITY_SNAPSHOT_MISSING") || item.code.includes("EVIDENCE_MISSING"));
  return {
    evaluated_before_score: true as const,
    status: blockers.length ? (unknown ? "BLOCKED_UNKNOWN" as const : "INELIGIBLE" as const) : "ELIGIBLE" as const,
    blockers,
  };
}

function gapDisclosure(value: Record<string, unknown>, pointer: string, required: boolean): EvidenceGapDisclosure {
  return {
    code: boundedText(value.code || "EVIDENCE_GAP", 255),
    gap_id: text(value.gap_id) ? boundedText(value.gap_id, 255) : null,
    source_id: text(value.source_id) ? boundedText(value.source_id, 255) : null,
    input_pointer: boundedText(pointer, 500),
    description: boundedText(value.description || value.detail || value.message || value.code || "Required evidence is unavailable.", 1_000),
    required,
  };
}

function evaluateEvidenceGaps(draft: DraftCandidate, evidence: Record<string, unknown> | null | undefined) {
  const required: EvidenceGapDisclosure[] = [];
  const optional: EvidenceGapDisclosure[] = [];
  for (const [index, raw] of list(evidence?.gaps).map(record).entries()) {
    const material = raw.material === true;
    const disclosure = gapDisclosure(raw, `/analytics_evidence/gaps/${index}`, material);
    (material ? required : optional).push(disclosure);
  }
  const demandGap = text(draft.market_evidence_status) === "EVIDENCE_GAP"
    || text(draft.publish_eligibility) === "BLOCKED_EVIDENCE_GAP"
    || publicationBlockers(draft).some((item) => text(item.code).includes("EVIDENCE_GAP"));
  if (demandGap && !required.some((gap) => gap.code === "DEMAND_EVIDENCE_GAP")) {
    required.push(gapDisclosure({
      code: "DEMAND_EVIDENCE_GAP",
      source_id: "wordstat",
      description: "Campaign Draft lacks required comparable demand evidence; unavailable is not zero demand.",
    }, "/draft/market_evidence_status", true));
  }
  required.sort((left, right) => `${left.code}:${left.gap_id}`.localeCompare(`${right.code}:${right.gap_id}`));
  optional.sort((left, right) => `${left.code}:${left.gap_id}`.localeCompare(`${right.code}:${right.gap_id}`));
  return {
    evaluated_before_score: true as const,
    status: required.length ? "UNRESOLVED" as const : "RESOLVED" as const,
    required: required.slice(0, 64),
    optional: optional.slice(0, 64),
  };
}

function safeScope(value: unknown): unknown {
  if (Array.isArray(value)) return value.slice(0, 32).map(safeScope);
  if (!value || typeof value !== "object") {
    if (typeof value === "string") return boundedText(value, 500);
    return value ?? null;
  }
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([key]) => !FORBIDDEN_INPUT_FIELD.test(key))
      .slice(0, 32)
      .map(([key, item]) => [boundedText(key, 100), safeScope(item)]),
  );
}

function frequencyEvidenceIds(frequency: Record<string, unknown>) {
  return boundedStrings(list(frequency.unique_assigned_rows).flatMap((row) => {
    const value = record(row);
    return list(record(value.provenance).call_ids);
  }));
}

function costEvidenceIds(cost: Record<string, unknown>) {
  const selected = list(cost.observations).map(record).find((item) => text(item.source) === text(cost.compact_source));
  return boundedStrings([
    ...list(selected?.evidence_ids),
    selected?.observation_id,
    selected?.source_observation_id,
  ]);
}

function demandScope(frequency: Record<string, unknown>) {
  const explicit = text(frequency.scope_fingerprint) || text(frequency.request_fingerprint);
  if (explicit) return explicit;
  return JSON.stringify(canonicalize({
    source: frequency.source,
    method: frequency.method,
    snapshot_batch_id: frequency.snapshot_batch_id,
    declared_window: frequency.declared_window,
    scopes: list(frequency.scopes).map((item) => {
      const scope = record(item);
      return {
        operator_profile: scope.operator_profile,
        region_ids: scope.region_ids,
        device: scope.device,
      };
    }),
  }));
}

function demandObservation(draft: DraftCandidate) {
  const frequency = record(record(draft.market_evidence).frequency);
  const count = numberOrNull(record(frequency.observed_unique_count).value);
  const usable = ["AVAILABLE", "PARTIAL", "VERIFIED"].includes(text(frequency.status));
  return {
    frequency,
    count: usable && count !== null && count >= 0 ? count : null,
    scope: usable ? demandScope(frequency) : "",
    evidenceIds: frequencyEvidenceIds(frequency),
  };
}

function costObservation(draft: DraftCandidate) {
  const cost = record(record(draft.market_evidence).cost);
  const range = record(cost.range);
  const low = numberOrNull(range.low);
  const high = numberOrNull(range.high);
  const weightedMean = numberOrNull(cost.weighted_historical_mean);
  const reference = low !== null && high !== null ? (low + high) / 2 : weightedMean;
  const source = text(cost.compact_source);
  const usable = ["AVAILABLE", "VERIFIED"].includes(text(cost.status));
  const scope = usable && source
    ? `${source}|${JSON.stringify(canonicalize(disclosedCostScope(cost.scope)))}|${text(cost.scenario)}|${text(cost.currency)}|${text(cost.vat_treatment ?? cost.vat_mode)}`
    : "";
  return { cost, reference: usable && reference !== null && reference >= 0 ? reference : null, scope, evidenceIds: costEvidenceIds(cost) };
}

function disclosedCostScope(value: unknown) {
  return safeScope(value);
}

function scoreScopes(draft: DraftCandidate) {
  const { frequency } = demandObservation(draft);
  const { cost } = costObservation(draft);
  const frequencyScopes = list(frequency.scopes).map(record);
  const operatorProfiles = boundedStrings(frequencyScopes.map((scope) => scope.operator_profile));
  const regionIds = [...new Set(frequencyScopes.flatMap((scope) => list(scope.region_ids).map(Number)).filter(Number.isFinite))].sort((left, right) => left - right).slice(0, 32);
  const devices = boundedStrings(frequencyScopes.map((scope) => scope.device));
  return {
    frequency: {
      status: boundedText(frequency.status, 100) || "UNAVAILABLE",
      source: boundedText(frequency.source, 255) || null,
      method: boundedText(frequency.method, 255) || null,
      semantics: boundedText(record(frequency.observed_unique_count).semantics, 255) || "UNAVAILABLE_NOT_ZERO",
      observed_unique_count: numberOrNull(record(frequency.observed_unique_count).value),
      snapshot_batch_id: boundedText(frequency.snapshot_batch_id, 255) || null,
      declared_window: boundedText(frequency.declared_window, 255) || null,
      source_window_end: boundedText(frequency.source_window_end, 255) || null,
      operator_profiles: operatorProfiles,
      region_ids: regionIds,
      devices,
      scope_fingerprint: demandScope(frequency) || null,
      evidence_ids: frequencyEvidenceIds(frequency),
    },
    cost: {
      status: boundedText(cost.status, 100) || "UNAVAILABLE",
      semantics: "ONE_QUALIFIED_PRELAUNCH_SOURCE; SOURCES_NOT_AVERAGED",
      source: boundedText(cost.compact_source, 255) || null,
      scenario: boundedText(cost.scenario, 500) || null,
      scope: disclosedCostScope(cost.scope),
      as_of: boundedText(cost.as_of, 100) || null,
      currency: boundedText(cost.currency, 100) || null,
      vat_treatment: boundedText(cost.vat_treatment ?? cost.vat_mode, 100) || null,
      sample_size: {
        unit: boundedText(record(cost.sample_size).unit, 100) || null,
        value: numberOrNull(record(cost.sample_size).value),
      },
      range: {
        low: numberOrNull(record(cost.range).low),
        high: numberOrNull(record(cost.range).high),
        kind: boundedText(record(cost.range).kind, 100) || null,
      },
      evidence_ids: costEvidenceIds(cost),
    },
  };
}

function midrankPercentiles(rows: Array<{ id: string; value: number; scope: string }>) {
  const result = new Map<string, number>();
  const grouped = new Map<string, Array<{ id: string; value: number; scope: string }>>();
  for (const row of rows) grouped.set(row.scope, [...(grouped.get(row.scope) ?? []), row]);
  for (const scopedRows of grouped.values()) {
    const sorted = [...scopedRows].sort((left, right) => left.value - right.value || left.id.localeCompare(right.id));
    if (sorted.length === 1) {
      result.set(sorted[0].id, 50);
      continue;
    }
    for (const row of sorted) {
      const equalIndexes = sorted.flatMap((candidate, index) => candidate.value === row.value ? [index] : []);
      const averageIndex = equalIndexes.reduce((sum, index) => sum + index, 0) / equalIndexes.length;
      result.set(row.id, 100 * averageIndex / (sorted.length - 1));
    }
  }
  return result;
}

function seasonalityScore(frequency: Record<string, unknown>) {
  const seasonality = record(frequency.seasonality);
  const scopedRatios = list(seasonality.scopes).map((item) => numberOrNull(record(item).ratio)).filter((value): value is number => value !== null);
  const ratio = numberOrNull(seasonality.ratio) ?? (scopedRatios.length === 1 ? scopedRatios[0] : null);
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
  const capacityValue = plannedUnits === null ? null
    : plannedUnits < 3 ? 0
      : plannedUnits < 5 ? 25
        : plannedUnits < 10 ? 50
          : plannedUnits < 20 ? 75 : 100;
  const { cost, evidenceIds } = costObservation(draft);
  const high = numberOrNull(record(cost.range).high);
  const ratio = high !== null && targetCost !== null && targetCost > 0 ? high / targetCost : null;
  const ratioValue = ratio === null ? null
    : ratio <= 0.05 ? 100
      : ratio <= 0.1 ? 80
        : ratio <= 0.2 ? 50
          : ratio <= 0.33 ? 20 : 0;
  return dimension("economics", [
    capacityValue === null
      ? unknownFeature("planned-result-units-v1", ["/strategy/weekly_budget", "/strategy/target_result_cost"], "economics-inputs")
      : feature({ rule: "planned-result-units-v1", pointers: ["/strategy/weekly_budget", "/strategy/target_result_cost"], value: capacityValue }),
    ratioValue === null
      ? unknownFeature("cost-to-target-ratio-v1", ["/draft/market_evidence/cost/range/high", "/strategy/target_result_cost"], "prelaunch-cost")
      : feature({ rule: "cost-to-target-ratio-v1", pointers: ["/draft/market_evidence/cost/range/high", "/strategy/target_result_cost"], value: ratioValue, evidenceIds }),
    feature({ rule: "economics-consistency-v1", pointers: ["/strategy/weekly_budget", "/strategy/target_result_cost"], value: weeklyBudget && targetCost ? 100 : 0 }),
  ]);
}

function semanticTokens(value: unknown) {
  return [...new Set(
    text(value).toLocaleLowerCase("ru-RU").replace(/[^\p{L}\p{N}]+/gu, " ").split(" ")
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
  const hypothesis = record(record(draft.variant).hypothesis);
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
  const expectedCore = text(search.BiddingStrategyType) === "WB_MAXIMUM_CLICKS" && text(network.BiddingStrategyType) === "SERVING_OFF";
  const selection = record(draft.capability_selection);
  const liveFitKnown = selection.eligible === true && Boolean(text(selection.capability_snapshot_id ?? draft.direct_capability_snapshot_id));
  const sourceEvidenceIds = boundedStrings(source.evidence_ids);
  return dimension("direct_feasibility", [
    sourceStatus === "VERIFIED" || sourceStatus === "PARTIAL"
      ? feature({ rule: "direct-account-currency-ready-v1", pointers: ["/analytics_evidence/sources/direct"], value: 100, evidenceIds: sourceEvidenceIds })
      : unknownFeature("direct-account-currency-ready-v1", ["/analytics_evidence/sources/direct"], "direct-account-preflight"),
    feature({ rule: "direct-campaign-group-core-v1", pointers: ["/draft/publish_projection/direct/campaign", "/draft/publish_projection/direct/ad_group"], value: campaign.UnifiedCampaign && group.UnifiedAdGroup ? 100 : 0 }),
    feature({ rule: "direct-strategy-placement-core-v1", pointers: ["/draft/publish_projection/direct/campaign/UnifiedCampaign/BiddingStrategy"], value: expectedCore ? 100 : 0 }),
    feature({ rule: "direct-criteria-ad-core-v1", pointers: ["/draft/publish_projection/direct/keyword", "/draft/publish_projection/direct/ad"], value: text(keyword.Keyword) && record(ad.TextAd).Title ? 100 : 0 }),
    liveFitKnown
      ? feature({ rule: "direct-live-limits-fit-v1", pointers: ["/draft/capability_selection"], value: 100 })
      : unknownFeature("direct-live-limits-fit-v1", ["/draft/capability_selection"], "direct-live-restrictions"),
    feature({ rule: "direct-local-schema-policy-v1", pointers: ["/draft/publish_projection/schema_version"], value: text(record(draft.publish_projection).schema_version) ? 100 : 0 }),
  ]);
}

function measurementDimension(evidence: Record<string, unknown> | null | undefined) {
  const source = sourceById(evidence, "metrika");
  const status = text(source.status);
  const sourceKnown = status === "VERIFIED" || status === "PARTIAL";
  const verifiedValue = status === "VERIFIED" ? 100 : status === "PARTIAL" ? 75 : UNKNOWN_MIDPOINT;
  const sourceEvidenceIds = boundedStrings(source.evidence_ids);
  const claimFeature = (predicate: string, rule: string, pointer: string, group: string) => {
    const claims = claimsFor(evidence, [predicate]);
    return claims.length
      ? feature({ rule, pointers: [pointer], value: tierScore(claims), claims })
      : unknownFeature(rule, [pointer], group);
  };
  return dimension("measurement_readiness", [
    sourceKnown ? feature({ rule: "metrika-counter-readable-v1", pointers: ["/analytics_evidence/sources/metrika/scope/counter_id"], value: verifiedValue, evidenceIds: sourceEvidenceIds }) : unknownFeature("metrika-counter-readable-v1", ["/analytics_evidence/sources/metrika"], "measurement-binding"),
    sourceKnown ? feature({ rule: "metrika-goal-active-v1", pointers: ["/analytics_evidence/sources/metrika/scope/goal_id"], value: verifiedValue, evidenceIds: sourceEvidenceIds }) : unknownFeature("metrika-goal-active-v1", ["/analytics_evidence/sources/metrika"], "measurement-binding"),
    claimFeature("measurement_goal_mapping", "goal-qualified-outcome-mapping-v1", "/analytics_evidence/claims/measurement_goal_mapping", "measurement-semantics"),
    claimFeature("measurement_landing_binding", "landing-counter-binding-v1", "/analytics_evidence/claims/measurement_landing_binding", "measurement-binding"),
    claimFeature("measurement_attribution_contract", "attribution-timezone-window-v1", "/analytics_evidence/claims/measurement_attribution_contract", "measurement-semantics"),
    claimFeature("measurement_maturity_contract", "diagnostic-maturity-contract-v1", "/analytics_evidence/claims/measurement_maturity_contract", "measurement-semantics"),
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
  if (!claims.length) return dimension("evidence_quality", [feature({ rule: "material-claim-quality-v1", pointers: ["/analytics_evidence/claims"], value: 0 })]);
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
  const demandObservationValue = demandObservation(draft);
  const { frequency } = demandObservationValue;
  const hasVolume = hasVolumeScore(frequency);
  const seasonality = seasonalityScore(frequency);
  const demand = dimension("demand", [
    demandPercentile === undefined
      ? unknownFeature("comparable-demand-midrank-v1", ["/draft/market_evidence/frequency/observed_unique_count"], "demand-volume")
      : feature({ rule: "comparable-demand-midrank-v1", pointers: ["/draft/market_evidence/frequency/observed_unique_count"], value: demandPercentile, evidenceIds: demandObservationValue.evidenceIds }),
    hasVolume === null
      ? unknownFeature("direct-has-search-volume-v1", ["/draft/market_evidence/frequency/has_search_volume/all_devices"], "demand-volume")
      : feature({ rule: "direct-has-search-volume-v1", pointers: ["/draft/market_evidence/frequency/has_search_volume/all_devices"], value: hasVolume, evidenceIds: demandObservationValue.evidenceIds }),
    seasonality === null
      ? unknownFeature("same-period-seasonality-v1", ["/draft/market_evidence/frequency/seasonality"], "demand-seasonality")
      : feature({ rule: "same-period-seasonality-v1", pointers: ["/draft/market_evidence/frequency/seasonality"], value: seasonality, evidenceIds: demandObservationValue.evidenceIds }),
  ]);
  const costObservationValue = costObservation(draft);
  const cost = dimension("cost", [
    costPercentile === undefined
      ? unknownFeature("comparable-cost-midrank-v1", ["/draft/market_evidence/cost"], "prelaunch-cost")
      : feature({ rule: "comparable-cost-midrank-v1", pointers: ["/draft/market_evidence/cost"], value: 100 - costPercentile, evidenceIds: costObservationValue.evidenceIds }),
  ]);
  return {
    demand,
    cost,
    economics: economicsDimension(strategy, draft),
    offer_audience_fit: fitDimension(draft, model, strategy, evidence),
    direct_feasibility: directDimension(draft, evidence),
    measurement_readiness: measurementDimension(evidence),
    evidence_quality: evidenceQualityDimension(evidence),
  };
}

function weightedResult(dimensions: Record<DimensionName, ScoreDimension>) {
  const names = Object.keys(WEIGHTS) as DimensionName[];
  const raw = names.reduce((sum, name) => sum + dimensions[name].weighted_contribution, 0);
  const lower = names.reduce((sum, name) => sum + dimensions[name].lower * WEIGHTS[name], 0);
  const upper = names.reduce((sum, name) => sum + dimensions[name].upper * WEIGHTS[name], 0);
  return { raw: rounded(raw, 4), lower: rounded(lower, 4), upper: rounded(upper, 4) };
}

function capabilityCohortDescriptor(draft: DraftCandidate) {
  const selection = record(draft.capability_selection);
  return {
    capability_profile_id: boundedText(draft.capability_profile_id, 255) || "MISSING_PROFILE",
    capability_profile_version: boundedText(draft.capability_profile_version, 255) || "MISSING_VERSION",
    conditional_selection_semantics: {
      selected_capabilities: boundedStrings(selection.selected_capabilities),
      selected_fields: boundedStrings(selection.selected_fields),
    },
  };
}

async function cohortId(draft: DraftCandidate) {
  const digest = await sha256(capabilityCohortDescriptor(draft));
  return `capability-cohort:${digest.slice("sha256:".length, "sha256:".length + 24)}`;
}

function safeModel(model: Record<string, unknown>) {
  return {
    product: boundedText(model.product, 2_000),
    audience: boundedText(model.audience, 2_000),
    value: boundedText(model.value, 2_000),
    qualified_result: boundedText(model.qualified_result, 2_000),
  };
}

function safeStrategy(strategy: Record<string, unknown>) {
  const period = strategyPeriod(strategy);
  return {
    strategy_revision_id: boundedText(strategy.strategy_revision_id, 255),
    business_goal: safeScope(strategyAnswerValue(strategy, "business_goal")),
    advertised_offer: safeScope(strategyAnswerValue(strategy, "advertised_offer")),
    target_audience: safeScope(strategyAnswerValue(strategy, "target_audience")),
    qualified_result: safeScope(strategyAnswerValue(strategy, "qualified_result")),
    exclusions: safeScope(strategyAnswerValue(strategy, "exclusions")),
    geography: safeScope(strategyAnswerValue(strategy, "geography")),
    period,
    landing_page: safeScope(strategyAnswerValue(strategy, "landing_page")),
    weekly_budget: safeScope(strategyAnswerValue(strategy, "weekly_budget")),
    target_result_cost: safeScope(strategyAnswerValue(strategy, "target_result_cost")),
    core_message: safeScope(strategyAnswerValue(strategy, "core_message")),
  };
}

export function evaluateScoreVisibility({
  structuralReason: persistedStructuralReason,
  sensitivityUpper,
  evidenceQuality,
  unresolvedEvidenceGap,
}: {
  structuralReason: string | null;
  sensitivityUpper: number | null;
  evidenceQuality: number | null;
  unresolvedEvidenceGap: boolean;
}): VisibilityResult {
  const upperBelowThreshold = sensitivityUpper !== null && sensitivityUpper < HIDDEN_THRESHOLD;
  const evidenceQualitySufficient = evidenceQuality !== null && evidenceQuality >= MINIMUM_HIDING_EVIDENCE_QUALITY;
  const appliedByScore = !persistedStructuralReason && upperBelowThreshold && evidenceQualitySufficient && !unresolvedEvidenceGap;
  const gates = {
    structural_reason: persistedStructuralReason,
    sensitivity_upper: sensitivityUpper,
    upper_threshold_exclusive: HIDDEN_THRESHOLD as 45,
    upper_below_threshold: upperBelowThreshold,
    evidence_quality: evidenceQuality,
    minimum_evidence_quality_inclusive: MINIMUM_HIDING_EVIDENCE_QUALITY as 60,
    evidence_quality_sufficient: evidenceQualitySufficient,
    unresolved_evidence_gap: unresolvedEvidenceGap,
    applied_by_score: appliedByScore,
  };
  if (persistedStructuralReason) {
    return { status: "HIDDEN", reason: persistedStructuralReason, threshold_contract_version: SCORE_THRESHOLD_VERSION, decision: "STRUCTURAL_REASON_PRECEDENCE", gates };
  }
  if (appliedByScore) {
    return { status: "HIDDEN", reason: SCORE_HIDDEN_REASON, threshold_contract_version: SCORE_THRESHOLD_VERSION, decision: "SCORE_THRESHOLD_APPLIED", gates };
  }
  return { status: "VISIBLE", reason: null, threshold_contract_version: SCORE_THRESHOLD_VERSION, decision: "REVIEW_VISIBLE", gates };
}

export async function recommendationSetRevisionId(baseRecommendationSetId: string, drafts: DraftCandidate[]) {
  const digest = await sha256({
    base_recommendation_set_id: boundedText(baseRecommendationSetId, 255),
    exact_membership: drafts.map((draft) => ({
      draft_id: boundedText(draft.draft_id, 255),
      draft_revision_id: boundedText(draft.draft_revision_id, 255),
      publish_fingerprint: boundedText(draft.publish_fingerprint, 255),
      cohort: capabilityCohortDescriptor(draft),
    })).sort((left, right) => left.draft_id.localeCompare(right.draft_id)),
  });
  return `recommendation-set-revision:${digest.slice("sha256:".length, "sha256:".length + 24)}`;
}

export async function scoreCampaignDrafts<T extends DraftCandidate>({
  recommendationSetId,
  drafts,
  model,
  strategy,
  analyticsEvidence,
  scoredAt,
}: ScoreDraftsInput<T>): Promise<T[]> {
  const fixedRecommendationSetId = boundedText(recommendationSetId, 255);
  if (!fixedRecommendationSetId) throw new Error("Scoring requires the exact immutable Recommendation Set revision ID.");
  if (new Set(drafts.map((draft) => draft.draft_id)).size !== drafts.length) throw new Error("Recommendation Set contains duplicate Draft IDs.");

  // Phase 1 is intentionally independent from every dimension: hard eligibility and required evidence gaps run first.
  const prerequisites = await Promise.all(drafts.map(async (draft): Promise<Prerequisites & { draft: T; cohortId: string }> => ({
    draft,
    eligibility: evaluateEligibility(draft, model, strategy, analyticsEvidence),
    evidenceGaps: evaluateEvidenceGaps(draft, analyticsEvidence),
    structuralReason: structuralReason(draft),
    cohortId: await cohortId(draft),
  })));
  const comparable = prerequisites.filter((item) =>
    item.eligibility.status === "ELIGIBLE"
    && item.evidenceGaps.status === "RESOLVED"
    && item.structuralReason === null
  );

  // Comparative demand and cost percentiles can see only eligible members of the same exact capability cohort and evidence scope.
  const demandRows = comparable.flatMap((item) => {
    const observation = demandObservation(item.draft);
    return observation.count !== null && observation.scope
      ? [{ id: item.draft.draft_id, value: Math.log1p(observation.count), scope: `${item.cohortId}|${observation.scope}` }]
      : [];
  });
  const costRows = comparable.flatMap((item) => {
    const observation = costObservation(item.draft);
    return observation.reference !== null && observation.scope
      ? [{ id: item.draft.draft_id, value: observation.reference, scope: `${item.cohortId}|${observation.scope}` }]
      : [];
  });
  const demandPercentiles = midrankPercentiles(demandRows);
  const costPercentiles = midrankPercentiles(costRows);
  const policyFingerprint = await sha256({
    contract: SCORE_CONTRACT_VERSION,
    weights_percent: WEIGHTS_PERCENT,
    hidden_threshold_exclusive: HIDDEN_THRESHOLD,
    minimum_hiding_evidence_quality_inclusive: MINIMUM_HIDING_EVIDENCE_QUALITY,
    unknown_midpoint: UNKNOWN_MIDPOINT,
    forbidden_inputs: FORBIDDEN_INPUTS,
  });

  const prepared: PreparedDraft<T>[] = [];
  for (const item of prerequisites) {
    const isComparable = comparable.some((candidate) => candidate.draft.draft_id === item.draft.draft_id);
    const dimensions = isComparable
      ? buildDimensions(item.draft, model, strategy, analyticsEvidence, demandPercentiles.get(item.draft.draft_id), costPercentiles.get(item.draft.draft_id))
      : null;
    const values = dimensions ? weightedResult(dimensions) : null;
    const scopes = scoreScopes(item.draft);
    const inputFingerprint = await sha256({
      contract: SCORE_CONTRACT_VERSION,
      recommendation_set_id: fixedRecommendationSetId,
      draft_revision_id: item.draft.draft_revision_id,
      model: safeModel(model),
      strategy: safeStrategy(strategy),
      eligibility: item.eligibility,
      evidence_gaps: item.evidenceGaps,
      dimensions,
      scopes,
      cohort: capabilityCohortDescriptor(item.draft),
    });
    prepared.push({
      ...item,
      dimensions,
      scoreRaw: values?.raw ?? null,
      scoreLower: values?.lower ?? null,
      scoreUpper: values?.upper ?? null,
      evidenceQuality: dimensions?.evidence_quality.value ?? null,
      comparableSetId: null,
      rank: null,
      tiedDraftIds: [],
      inputFingerprint,
    });
  }

  const byCohort = new Map<string, PreparedDraft<T>[]>();
  for (const item of prepared.filter((candidate) => candidate.scoreRaw !== null)) {
    byCohort.set(item.cohortId, [...(byCohort.get(item.cohortId) ?? []), item]);
  }
  for (const [currentCohortId, members] of byCohort) {
    const comparableSetDigest = await sha256({
      recommendation_set_id: fixedRecommendationSetId,
      capability_cohort_id: currentCohortId,
      exact_draft_revisions: members.map((item) => ({ draft_id: item.draft.draft_id, draft_revision_id: item.draft.draft_revision_id })).sort((left, right) => left.draft_id.localeCompare(right.draft_id)),
    });
    const comparableSetId = `comparable-set:${comparableSetDigest.slice("sha256:".length, "sha256:".length + 24)}`;
    const sorted = [...members].sort((left, right) => Number(right.scoreRaw) - Number(left.scoreRaw) || left.draft.draft_id.localeCompare(right.draft.draft_id));
    for (const [index, item] of sorted.entries()) {
      const previous = sorted[index - 1];
      item.rank = previous && previous.scoreRaw === item.scoreRaw ? previous.rank : index + 1;
      item.comparableSetId = comparableSetId;
    }
    for (const item of sorted) {
      item.tiedDraftIds = sorted.filter((candidate) => candidate.rank === item.rank && candidate.scoreRaw === item.scoreRaw).map((candidate) => candidate.draft.draft_id).sort();
    }
  }

  return prepared.map((item) => {
    const missingDimensions = item.dimensions
      ? (Object.entries(item.dimensions) as Array<[DimensionName, ScoreDimension]>).filter(([, value]) => value.state === "UNKNOWN").map(([name]) => name)
      : [];
    const visibility = evaluateScoreVisibility({
      structuralReason: item.structuralReason,
      sensitivityUpper: item.scoreUpper,
      evidenceQuality: item.evidenceQuality,
      unresolvedEvidenceGap: item.evidenceGaps.status === "UNRESOLVED",
    });
    const rankingStatus = item.structuralReason
      ? "STRUCTURALLY_NON_COMPARABLE" as const
      : item.eligibility.status !== "ELIGIBLE"
        ? "BLOCKED_HARD_ELIGIBILITY" as const
        : item.evidenceGaps.status === "UNRESOLVED"
          ? "BLOCKED_EVIDENCE_GAP" as const
          : "RANKED" as const;
    const result: ViabilityScoreResult = {
      schema_version: SCORE_SCHEMA_VERSION,
      contract_version: SCORE_CONTRACT_VERSION,
      policy_status: "UNCALIBRATED_POLICY_V1",
      eligibility: item.eligibility,
      evidence_gaps: item.evidenceGaps,
      score: item.scoreRaw === null ? null : rounded(item.scoreRaw),
      score_raw: item.scoreRaw,
      score_lower: item.scoreLower,
      score_upper: item.scoreUpper,
      uncertainty_width: item.scoreLower === null || item.scoreUpper === null ? null : rounded(item.scoreUpper - item.scoreLower, 4),
      sensitivity: {
        method: "UNKNOWN_DIMENSIONS_RECOMPUTED_AT_0_AND_100;_KNOWN_DIMENSIONS_FIXED",
        midpoint_value: 50,
        unknown_dimensions: missingDimensions,
        lower: { score: item.scoreLower, unknown_dimensions_value: 0, known_dimensions_fixed: true },
        upper: { score: item.scoreUpper, unknown_dimensions_value: 100, known_dimensions_fixed: true },
      },
      rank: item.rank,
      tied_draft_ids: item.tiedDraftIds,
      ranking: {
        status: rankingStatus,
        recommendation_set_id: fixedRecommendationSetId,
        cohort_id: item.cohortId,
        comparable_set_id: item.comparableSetId,
        rank: item.rank,
        tied_draft_ids: item.tiedDraftIds,
        semantic_tie_rule: "EXACT_SCORE_RAW_EQUALITY_WITHIN_COHORT",
        stable_id_display_order_only: true,
      },
      dimensions: item.dimensions,
      scopes: scoreScopes(item.draft),
      visibility,
      explanation: {
        label: SCORE_LABEL,
        comparative_not_predictive: true,
        landing_advisory_used: false,
        post_launch_inputs_used: false,
        calibration_used: false,
        unknown_midpoint_value: 50,
        missing_dimensions: missingDimensions,
        forbidden_inputs: FORBIDDEN_INPUTS,
      },
      fingerprints: {
        input: item.inputFingerprint,
        cohort: item.cohortId,
        policy: policyFingerprint,
        implementation_build: "sites-p0-viability-v1",
      },
      scored_at: scoredAt,
    };
    const scoreHidden = visibility.status === "HIDDEN" && visibility.decision === "SCORE_THRESHOLD_APPLIED";
    const reviewVisible = visibility.status === "VISIBLE";
    return {
      ...item.draft,
      visibility: visibility.status,
      suppression_reason: visibility.reason,
      shortlist_eligible: item.draft.shortlist_eligible === true
        && reviewVisible
        && item.eligibility.status === "ELIGIBLE"
        && item.evidenceGaps.status === "RESOLVED",
      ...(scoreHidden ? { score_visibility_blocker: visibility.reason } : {}),
      viability_score: result,
    };
  });
}

export function explainScoreDelta(previous: ViabilityScoreResult | undefined, current: ViabilityScoreResult | undefined, changedPointers: string[]) {
  const names = Object.keys(WEIGHTS) as DimensionName[];
  return {
    schema_version: "viability-score-delta-v1",
    contract_version: SCORE_CONTRACT_VERSION,
    changed_pointers: [...changedPointers].sort(),
    score: {
      previous: previous?.score ?? null,
      current: current?.score ?? null,
      delta: previous?.score !== null && previous?.score !== undefined && current?.score !== null && current?.score !== undefined
        ? current.score - previous.score : null,
    },
    rank: { previous: previous?.rank ?? null, current: current?.rank ?? null },
    eligibility: { previous: previous?.eligibility.status ?? null, current: current?.eligibility.status ?? null },
    dimensions: Object.fromEntries(names.map((name) => {
      const before = previous?.dimensions?.[name]?.weighted_contribution ?? null;
      const after = current?.dimensions?.[name]?.weighted_contribution ?? null;
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
  weights_percent: WEIGHTS_PERCENT,
  weight_sum_percent: WEIGHT_SUM_PERCENT,
  hidden_threshold_exclusive: HIDDEN_THRESHOLD,
  minimum_hiding_evidence_quality_inclusive: MINIMUM_HIDING_EVIDENCE_QUALITY,
  unknown_midpoint: UNKNOWN_MIDPOINT,
  label: SCORE_LABEL,
  landing_advisory_used: false,
  post_launch_inputs_used: false,
  calibration_used: false,
  forbidden_inputs: FORBIDDEN_INPUTS,
} as const;
