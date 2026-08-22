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
import type { CuratedPlaybookRelease } from "./campaign-playbook.ts";
import {
  buildCampaignNames,
  buildPublishProjection,
  isCampaignNameWithGeography,
  isLegacySearchName,
} from "./campaign-draft.ts";
import {
  DIRECT_V501_DRAFT_FIELD_REGISTRY,
  isCanonicalDirectV501DraftFieldRegistry,
  nextDraftRevisionId,
} from "./campaign-draft-fields.ts";
import {
  buildCampaignRecommendationSet,
  campaignDraftPublishBlockers,
  directProjectionMaterialDelta,
  fingerprintDirectProjection,
  preserveSelectedConditionalProjection,
  resolveActivePlaybookReleaseIdentity,
  type CampaignRecommendationSet,
  type DirectCapabilitySnapshot,
} from "./campaign-fanout.ts";
import {
  buildDecisionInvalidation,
  buildHumanDecisionGate,
  buildPackageReview,
  emptyShortlist,
  PACKAGE_CONFIRMATION_TOKEN,
  rebaseShortlist,
  restoredInsertionIndex,
  reviseShortlist,
  selectionForDraft,
  stableRemovedIndex,
  shortlistSelectionBlockReason,
  verifyDecisionInvalidation,
  verifyHumanDecisionGate,
  verifyPackageReview,
  verifyShortlist,
  type DecisionInvalidation,
  type DecisionInvalidationReason,
  type DirectAccountBinding,
  type HumanDecisionGate,
  type P0Shortlist,
  type PackageReview,
} from "./campaign-decision-gate.ts";
import {
  beginPackageItemDispatch,
  beginPackageItemModerationPoll,
  exactPackageDispatchPlans,
  initializePackageExecution,
  migrateLegacyPackageExecution,
  packageExecutionBlocksFollowingItems,
  packageItemModerationPollIsDue,
  recordPackageItemOutcome,
  verifyPackageExecution,
  type PackageExecution,
  type PackageItemExecution,
  type PackageItemExternalOutcome,
} from "./campaign-package-execution.ts";
import {
  CAMPAIGN_STRATEGY_SCHEMA,
  STRATEGY_QUESTIONNAIRE_SCHEMA,
  buildStrategyQuestionnaire,
  missingStrategyDecisions,
  normalizeStrategyAnswers,
  strategyAnswerValue,
  strategyAnswersFingerprint,
  type CampaignStrategyRevision,
  type StrategyQuestionnaire,
} from "./campaign-strategy.ts";
import {
  explainScoreDelta,
  recommendationSetRevisionId,
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
import {
  runLandingAdvisory,
  unavailableLandingAdvisoryAdapter,
  verifyLandingAdvisoryRun,
  type LandingAdvisoryAdapter,
  type LandingAdvisoryRun,
} from "./landing-advisory.ts";

export const P0_APPLICATION_CONTRACT = "mox-adv.p0.application";
export const P0_APPLICATION_CONTRACT_VERSION = "1.10.0";
export const P0_DOCUMENT_SCHEMA = "p0-application-document-v7";
const P0_LEGACY_DOCUMENT_SCHEMAS = new Set(["p0-application-document-v1", "p0-application-document-v2", "p0-application-document-v3", "p0-application-document-v4", "p0-application-document-v5", "p0-application-document-v6"]);
const P0_PRE_PACKAGE_AUTHORITY_DOCUMENT_SCHEMAS = new Set(["p0-application-document-v1", "p0-application-document-v2", "p0-application-document-v3", "p0-application-document-v4"]);
export const P0_CONTEXT_SCHEMA = "p0-context-v2";
const P0_LEGACY_CONTEXT_SCHEMA = "p0-context-v1";
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
      capability_snapshot: DirectCapabilitySnapshot;
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
  context_revision_id: string;
  research_fingerprint: string;
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
  strategy_questionnaire: StrategyQuestionnaire | null;
  strategy: CampaignStrategyRevision | Record<string, unknown> | null;
  landing_advisory_run: LandingAdvisoryRun | null;
  recommendation_set: CampaignRecommendationSet | null;
  draft: Record<string, unknown> | null;
  shortlist: P0Shortlist | null;
  package_review: PackageReview | null;
  human_decision_gate: HumanDecisionGate | null;
  package_execution: PackageExecution | null;
  last_decision_invalidation: DecisionInvalidation | null;
  external_write_intent: {
    strategy_revision_id: string;
    draft_revision_id: string;
    publish_fingerprint: string;
    confirmed_at: string;
  } | null;
  campaign: Record<string, unknown> | null;
  recommendation_recalculation: {
    schema_version: "p0-recommendation-recalculation-v1";
    material_change: boolean;
    message: string;
    reason_code: "ACTIVE_PLAYBOOK_RELEASE_CHANGED_OR_ROLLED_BACK" | "NO_ACTIVE_PLAYBOOK_MATERIAL_CHANGE";
    recalculated_at: string;
    previous_recommendation_set_id: string;
    current_recommendation_set_id: string;
    previous_playbook_release_id: string | null;
    current_playbook_release_id: string | null;
    changes: Array<Record<string, unknown>>;
    evaluator_traces_exposed: false;
  } | null;
  last_cascade: {
    schema_version: "p0-recomputation-cascade-v1";
    trigger: "CONTEXT" | "MODEL" | "STRATEGY";
    affected_steps: string[];
    changed_at: string;
    recomputation_status: "REQUIRED" | "PENDING" | "COMPLETE";
    confirmation_blocked_while_pending: true;
    previous_lineage: ReturnType<typeof previousLineage>;
  } | null;
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
  landingAdvisory?: LandingAdvisoryAdapter;
  readPlaybookReleases?(): Promise<CuratedPlaybookRelease[]>;
  externalWriteConfiguration(): P0ExternalWriteConfiguration;
  createExternalOutcome(input: {
    key: string;
    state: P0Document;
    projection: DirectProjection;
  }): Promise<Record<string, unknown>>;
  createPackageItemOutcome(input: {
    key: string;
    state: P0Document;
    package_execution_id: string;
    item_execution_id: string;
    selection: P0Shortlist["selections"][number];
    projection: DirectProjection;
    draft: CampaignRecommendationSet["drafts"][number];
  }): Promise<PackageItemExternalOutcome>;
  pollPackageItemOutcome(input: {
    key: string;
    state: P0Document;
    package_execution_id: string;
    item_execution_id: string;
    selection: P0Shortlist["selections"][number];
    projection: DirectProjection;
    draft: CampaignRecommendationSet["drafts"][number];
    item: PackageItemExecution;
  }): Promise<PackageItemExternalOutcome>;
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
      owner_edited?: boolean;
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

function packageNotDispatched(state: P0Document) {
  return !state.package_execution && !state.campaign && !state.external_write_intent;
}

export const P0_COMMAND_TRUTH_TABLE = {
  analyze_site: (state: P0Document) => packageNotDispatched(state),
  confirm_context_goal: (state: P0Document) => Boolean(
    state.context_state && state.site_analysis && packageNotDispatched(state),
  ),
  save_business_model: (state: P0Document) => Boolean(
    state.site_analysis && state.business_model && packageNotDispatched(state),
  ),
  approve_strategy: (state: P0Document) => (
    state.business_model?.source === "REAL_SITE_RESEARCH_PLUS_OWNER_CONFIRMATION"
    && state.strategy_questionnaire?.schema_version === STRATEGY_QUESTIONNAIRE_SCHEMA
    && packageNotDispatched(state)
  ),
  run_landing_advisory: (state: P0Document) => Boolean(
    state.strategy && packageNotDispatched(state),
  ),
  recalculate_recommendations: (state: P0Document) => Boolean(
    state.strategy && state.recommendation_set && packageNotDispatched(state),
  ),
  save_draft: (state: P0Document) => Boolean(
    state.strategy && state.recommendation_set && packageNotDispatched(state),
  ),
  add_to_shortlist: (state: P0Document) => Boolean(
    state.strategy && state.recommendation_set && state.shortlist && packageNotDispatched(state),
  ),
  remove_from_shortlist: (state: P0Document) => Boolean(
    state.strategy && state.recommendation_set && state.shortlist?.selections.length && packageNotDispatched(state),
  ),
  restore_to_shortlist: (state: P0Document) => Boolean(
    state.strategy && state.recommendation_set && state.shortlist?.removed_selections.length && packageNotDispatched(state),
  ),
  review_package: (state: P0Document) => Boolean(
    state.strategy && state.recommendation_set && state.shortlist?.selections.length && packageNotDispatched(state),
  ),
  confirm_package: (state: P0Document) => Boolean(
    state.package_review && !state.human_decision_gate && state.shortlist?.selections.length && packageNotDispatched(state),
  ),
  dispatch_package: (state: P0Document) => Boolean(
    state.package_review
      && state.human_decision_gate
      && (!state.package_execution || state.package_execution.items.some((item) => item.status === "QUEUED" || item.status === "DISPATCHING"))
      && !state.campaign
      && !state.external_write_intent,
  ),
  poll_package_moderation: (state: P0Document) => Boolean(
    state.package_review
      && state.human_decision_gate
      && state.package_execution?.items.some((item) => item.status === "MODERATION_PENDING" || item.status === "OUTCOME_UNKNOWN")
      && !state.campaign
      && !state.external_write_intent,
  ),
  // Legacy one-Draft dispatch remains unavailable; package execution is authoritative.
  confirm_creation: () => false,
  reset: (state: P0Document) => packageNotDispatched(state),
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
    strategy_questionnaire: null,
    strategy: null,
    landing_advisory_run: null,
    recommendation_set: null,
    draft: null,
    shortlist: null,
    package_review: null,
    human_decision_gate: null,
    package_execution: null,
    last_decision_invalidation: null,
    external_write_intent: null,
    campaign: null,
    recommendation_recalculation: null,
    last_cascade: null,
  };
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function activePlaybookReleaseIdentity(recommendationSet: CampaignRecommendationSet) {
  const release = record(recommendationSet.playbook_release);
  const appliedRuleIds = Array.isArray(release.applied_rule_ids)
    ? release.applied_rule_ids.map(String)
    : [];
  const explicitRuleIdentities = Array.isArray(release.applied_rule_identities)
    ? release.applied_rule_identities.map((identity) => ({
        rule_id: String(record(identity).rule_id ?? ""),
        rule_version: String(record(identity).rule_version ?? ""),
      }))
    : null;
  const compatibleRuleIdentities = appliedRuleIds.flatMap((ruleId) => [...new Set(recommendationSet.drafts
    .filter((draft) => draft.playbook_rule_id === ruleId)
    .map((draft) => String(draft.playbook_rule_version ?? "")))]
    .sort()
    .map((ruleVersion) => ({ rule_id: ruleId, rule_version: ruleVersion })));
  return {
    status: String(release.status ?? ""),
    release_id: release.release_id === null ? null : String(release.release_id ?? ""),
    release_version: release.release_version === null ? null : String(release.release_version ?? ""),
    content_digest: release.content_digest === null ? null : String(release.content_digest ?? ""),
    applied_governed_rule_identities: explicitRuleIdentities ?? compatibleRuleIdentities,
  };
}

function draftReplacementSemanticKey(draft: CampaignRecommendationSet["drafts"][number]) {
  const variant = record(draft.variant);
  const treatment = record(draft.treatment_delta);
  const controlBasis = record(variant.control_basis);
  return JSON.stringify({
    delivery_key_fingerprint: String(draft.delivery_key_fingerprint ?? ""),
    demand_cluster_ids: Array.isArray(draft.demand_cluster_ids) ? draft.demand_cluster_ids.map(String).sort() : [],
    capability_profile_id: draft.capability_profile_id,
    capability_profile_version: draft.capability_profile_version,
    direct_capability_snapshot_id: draft.direct_capability_snapshot_id ?? null,
    variant: variant.kind === "CONTROL"
      ? { kind: "CONTROL", control_basis: String(controlBasis.kind ?? "") }
      : {
          kind: String(variant.kind ?? ""),
          changed_family: String(treatment.changed_family ?? ""),
          expected_changed_fields: Array.isArray(treatment.expected_changed_fields)
            ? treatment.expected_changed_fields.map(String).sort()
            : [],
        },
  });
}

function recommendationRecalculationChanges(
  previousSet: CampaignRecommendationSet,
  currentSet: CampaignRecommendationSet,
) {
  const previous = previousSet.drafts;
  const current = currentSet.drafts;
  const previousBySemanticKey = new Map<string, typeof previous>();
  const currentBySemanticKey = new Map<string, typeof current>();
  for (const draft of previous) {
    const key = draftReplacementSemanticKey(draft);
    previousBySemanticKey.set(key, [...(previousBySemanticKey.get(key) ?? []), draft]);
  }
  for (const draft of current) {
    const key = draftReplacementSemanticKey(draft);
    currentBySemanticKey.set(key, [...(currentBySemanticKey.get(key) ?? []), draft]);
  }
  const matchedPreviousIds = new Set<string>();
  const matchedCurrentIds = new Set<string>();
  const changes: Array<Record<string, unknown>> = [];
  for (const [key, previousMatches] of previousBySemanticKey) {
    const currentMatches = currentBySemanticKey.get(key) ?? [];
    if (previousMatches.length !== 1 || currentMatches.length !== 1) continue;
    const previousDraft = previousMatches[0];
    const currentDraft = currentMatches[0];
    matchedPreviousIds.add(previousDraft.draft_id);
    matchedCurrentIds.add(currentDraft.draft_id);
    changes.push({
      change_type: "REPLACED",
      previous_draft_id: previousDraft.draft_id,
      current_draft_id: currentDraft.draft_id,
      previous_draft_revision_id: previousDraft.draft_revision_id,
      current_draft_revision_id: currentDraft.draft_revision_id,
      previous_publish_fingerprint: previousDraft.publish_fingerprint,
      current_publish_fingerprint: currentDraft.publish_fingerprint,
      previous_score: previousDraft.viability_score?.score ?? null,
      current_score: currentDraft.viability_score?.score ?? null,
      previous_rank: previousDraft.viability_score?.rank ?? null,
      current_rank: currentDraft.viability_score?.rank ?? null,
      fields: directProjectionMaterialDelta(previousDraft.publish_projection, currentDraft.publish_projection),
      policy_reason: {
        code: "ACTIVE_PLAYBOOK_DRAFT_REPLACED",
        message: "Active curated playbook lineage changed; a Draft with the same delivery, capability and variant semantics was regenerated.",
      },
    });
  }
  for (const previousDraft of previous.filter((draft) => !matchedPreviousIds.has(draft.draft_id))) {
    changes.push({
      change_type: "REMOVED",
      previous_draft_id: previousDraft.draft_id,
      current_draft_id: null,
      previous_draft_revision_id: previousDraft.draft_revision_id,
      current_draft_revision_id: null,
      previous_publish_fingerprint: previousDraft.publish_fingerprint,
      current_publish_fingerprint: null,
      previous_score: previousDraft.viability_score?.score ?? null,
      current_score: null,
      previous_rank: previousDraft.viability_score?.rank ?? null,
      current_rank: null,
      fields: [],
      policy_reason: {
        code: "ACTIVE_PLAYBOOK_DRAFT_REMOVED",
        message: "The previous Draft has no corresponding delivery, capability and variant semantics in the active release.",
      },
    });
  }
  for (const currentDraft of current.filter((draft) => !matchedCurrentIds.has(draft.draft_id))) {
    changes.push({
      change_type: "ADDED",
      previous_draft_id: null,
      current_draft_id: currentDraft.draft_id,
      previous_draft_revision_id: null,
      current_draft_revision_id: currentDraft.draft_revision_id,
      previous_publish_fingerprint: null,
      current_publish_fingerprint: currentDraft.publish_fingerprint,
      previous_score: null,
      current_score: currentDraft.viability_score?.score ?? null,
      previous_rank: null,
      current_rank: currentDraft.viability_score?.rank ?? null,
      fields: [],
      policy_reason: {
        code: "ACTIVE_PLAYBOOK_DRAFT_ADDED",
        message: "The active release introduced a Draft with new delivery, capability or variant semantics.",
      },
    });
  }
  return changes.sort((left, right) => `${left.previous_draft_id ?? ""}:${left.current_draft_id ?? ""}`
    .localeCompare(`${right.previous_draft_id ?? ""}:${right.current_draft_id ?? ""}`));
}

function correspondingDraft(
  previousDraft: Record<string, unknown> | null,
  currentSet: CampaignRecommendationSet,
) {
  if (!previousDraft) return null;
  const semanticKey = draftReplacementSemanticKey(previousDraft as CampaignRecommendationSet["drafts"][number]);
  const matches = currentSet.drafts.filter((draft) => draftReplacementSemanticKey(draft) === semanticKey);
  return matches.length === 1 ? matches[0] : null;
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

function isValidIsoCalendarDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/u.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return Number.isFinite(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value;
}

function artifactText(value: unknown, maximum: number) {
  const normalized = String(value ?? "").normalize("NFKC");
  return cleanText(redactSensitiveEvidenceText(normalized, maximum), maximum + 20);
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

function sanitizeDirectCapabilitySnapshot(value: unknown): DirectCapabilitySnapshot {
  const snapshot = record(value);
  const restrictions = Array.isArray(snapshot.restrictions) ? snapshot.restrictions : [];
  const conditional = Array.isArray(snapshot.conditional_capabilities) ? snapshot.conditional_capabilities : [];
  return {
    schema_version: cleanText(String(snapshot.schema_version ?? ""), 100) as DirectCapabilitySnapshot["schema_version"],
    snapshot_id: cleanText(String(snapshot.snapshot_id ?? ""), 255),
    observed_at: cleanText(String(snapshot.observed_at ?? ""), 100),
    source: cleanText(String(snapshot.source ?? ""), 100) as DirectCapabilitySnapshot["source"],
    account: cleanText(String(snapshot.account ?? ""), 255),
    api_version: cleanText(String(snapshot.api_version ?? ""), 20) as DirectCapabilitySnapshot["api_version"],
    currency: cleanText(String(snapshot.currency ?? ""), 20),
    available_campaign_types: stringList(snapshot.available_campaign_types).sort(),
    edit_campaigns_grant: ["YES", "NO"].includes(String(snapshot.edit_campaigns_grant))
      ? String(snapshot.edit_campaigns_grant) as "YES" | "NO" : "UNKNOWN",
    archived: ["YES", "NO"].includes(String(snapshot.archived))
      ? String(snapshot.archived) as "YES" | "NO" : "UNKNOWN",
    restrictions: restrictions.map((item) => {
      const restriction = record(item);
      return { element: cleanText(String(restriction.element ?? ""), 100), value: Number(restriction.value) };
    }).filter((item) => item.element && Number.isFinite(item.value)).sort((left, right) => left.element.localeCompare(right.element)),
    conditional_capabilities: conditional.map((item) => {
      const capability = record(item);
      const apiCheck = record(capability.official_api_check);
      const accountCheck = record(capability.account_eligibility_check);
      return {
        capability: cleanText(String(capability.capability ?? ""), 100) as DirectCapabilitySnapshot["conditional_capabilities"][number]["capability"],
        field_paths: stringList(capability.field_paths).sort(),
        official_api_check: {
          source: cleanText(String(apiCheck.source ?? ""), 100) as "YANDEX_DIRECT_API_V501",
          endpoint: cleanText(String(apiCheck.endpoint ?? ""), 255),
          method: cleanText(String(apiCheck.method ?? ""), 100),
          evidence_id: cleanText(String(apiCheck.evidence_id ?? ""), 255),
          verified: apiCheck.verified === true,
        },
        account_eligibility_check: {
          account: cleanText(String(accountCheck.account ?? ""), 255),
          evidence_id: cleanText(String(accountCheck.evidence_id ?? ""), 255),
          eligible: accountCheck.eligible === true,
        },
      };
    }).filter((item) => ["AUTOTARGETING", "SITELINKS", "PRODUCT_GALLERY", "NETWORK"].includes(item.capability)),
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
      capability_snapshot: sanitizeDirectCapabilitySnapshot(direct.capability_snapshot),
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
  const directCapability = record(direct.capability_snapshot);
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
  if (
    directCapability.schema_version !== "direct-account-capability-snapshot-v1"
    || directCapability.source !== "YANDEX_DIRECT_API_V501"
    || directCapability.api_version !== "v501"
    || directCapability.account !== direct.account
    || directCapability.archived !== "NO"
    || directCapability.edit_campaigns_grant !== "YES"
    || !Array.isArray(directCapability.available_campaign_types)
    || !directCapability.available_campaign_types.includes("UNIFIED_CAMPAIGN")
  ) blockers.push("Direct core v501 capability profile не подтверждён exact account preflight");
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
      capability_snapshot: sanitizeDirectCapabilitySnapshot(direct.capability_snapshot),
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

function directCapabilityMaterialFacts(value: unknown) {
  const snapshot = sanitizeDirectCapabilitySnapshot(value);
  return {
    schema_version: snapshot.schema_version,
    source: snapshot.source,
    account: snapshot.account,
    api_version: snapshot.api_version,
    currency: snapshot.currency,
    available_campaign_types: snapshot.available_campaign_types,
    edit_campaigns_grant: snapshot.edit_campaigns_grant,
    archived: snapshot.archived,
    restrictions: snapshot.restrictions,
    conditional_capabilities: [...snapshot.conditional_capabilities]
      .sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right))),
  } satisfies Omit<DirectCapabilitySnapshot, "snapshot_id" | "observed_at">;
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
      capability_snapshot: directCapabilityMaterialFacts(direct.capability_snapshot),
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
      capability_snapshot: directCapabilityMaterialFacts(facts.direct.capability_snapshot),
    },
    metrika: {
      counter_id: facts.metrika.counter_id,
      goal_id: facts.metrika.goal_id,
    },
  };
}

async function contextResearchFingerprint(site: SiteAnalysis, context: P0Context) {
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

async function confirmedContextMaterialFingerprint(researchFingerprint: string, businessGoal: string) {
  return sha256({
    research_fingerprint: researchFingerprint,
    business_goal: cleanText(businessGoal.normalize("NFKC"), 500),
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

function cascadeRecord(
  state: P0Document,
  trigger: "CONTEXT" | "MODEL" | "STRATEGY",
  changedAt: string,
  affectedSteps: string[],
): NonNullable<P0Document["last_cascade"]> {
  return {
    schema_version: "p0-recomputation-cascade-v1",
    trigger,
    affected_steps: affectedSteps,
    changed_at: changedAt,
    recomputation_status: trigger === "STRATEGY" ? "COMPLETE" : "REQUIRED",
    confirmation_blocked_while_pending: true,
    previous_lineage: previousLineage(state),
  };
}

async function invalidateDecisionAuthority(
  state: P0Document,
  reasonCode: DecisionInvalidationReason,
  reason: string,
  invalidatedAt: string,
) {
  state.last_decision_invalidation = await buildDecisionInvalidation({
    reason_code: reasonCode,
    reason: cleanText(reason, 500),
    invalidated_at: invalidatedAt,
    previous_shortlist_revision_id: state.shortlist?.shortlist_revision_id ?? null,
    previous_package_review_id: state.package_review?.package_review_id ?? null,
    previous_package_id: state.package_review?.package_id ?? state.human_decision_gate?.package_id ?? null,
    previous_gate_id: state.human_decision_gate?.gate_id ?? null,
  });
  state.package_review = null;
  state.human_decision_gate = null;
}

function directAccountBinding(state: P0Document): DirectAccountBinding | null {
  const direct = state.context_state?.facts.direct;
  if (!direct?.account || !direct.client_id || direct.source_kind !== "YANDEX_DIRECT_API_V501") return null;
  return {
    source_kind: "YANDEX_DIRECT_API_V501",
    account: direct.account,
    client_id: direct.client_id,
    verified: true,
  };
}

function persistedDecisionContext(state: P0Document): P0Context {
  const facts = state.context_state?.facts;
  if (!facts) fail("P0_CONTEXT_STATE_MISSING", "Persisted Context facts отсутствуют для decision response.");
  return {
    environment: "PRODUCTION",
    test_scenario: false,
    direct: {
      ready: true,
      inventory_ready: true,
      authority: "VERIFIED",
      access: "YANDEX_DIRECT_API_V501",
      account: facts.direct.account,
      client_id: facts.direct.client_id,
      binding: { expected_account: facts.direct.account, api_account: facts.direct.account, matched: true },
      campaigns_total: facts.direct.campaigns_total,
      minimum_weekly_budget_rub: facts.direct.minimum_weekly_budget_rub,
      observed_at: facts.direct.observed_at,
      capability_snapshot: facts.direct.capability_snapshot,
      read_limitations: {
        inventory_complete: true,
        limited_by: null,
        methods_read: ["PERSISTED_CONTEXT_FACTS"],
        methods_not_read: [],
        statistics_provisional_days: 3,
      },
      blockers: [],
    },
    metrika: {
      ready: true,
      authority: "VERIFIED",
      access: "YANDEX_METRIKA_MANAGEMENT_AND_REPORTS_API",
      counter_id: facts.metrika.counter_id,
      goal_id: facts.metrika.goal_id,
      binding: { expected_counter_id: facts.metrika.counter_id, api_counter_id: facts.metrika.counter_id, matched: true },
      goal_binding: { expected_goal_id: facts.metrika.goal_id, api_goal_id: facts.metrika.goal_id, matched: true },
      observed_at: facts.metrika.observed_at,
      blockers: [],
    },
    campaign_catalog: null,
    performance: null,
  };
}

function invalidateContextDownstream(state: P0Document) {
  state.strategy_questionnaire = null;
  state.strategy = null;
  state.landing_advisory_run = null;
  state.recommendation_set = null;
  state.draft = null;
  state.shortlist = null;
  state.package_review = null;
  state.human_decision_gate = null;
  state.package_execution = null;
  state.external_write_intent = null;
  state.recommendation_recalculation = null;
}

function invalidateStrategyDownstream(state: P0Document) {
  state.strategy = null;
  state.landing_advisory_run = null;
  state.recommendation_set = null;
  state.draft = null;
  state.shortlist = null;
  state.package_review = null;
  state.human_decision_gate = null;
  state.package_execution = null;
  state.external_write_intent = null;
  state.recommendation_recalculation = null;
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
  if (version !== undefined && version !== P0_DOCUMENT_SCHEMA && !P0_LEGACY_DOCUMENT_SCHEMAS.has(String(version))) {
    fail("P0_DOCUMENT_SCHEMA_UNSUPPORTED", `Persisted P0 document использует неподдерживаемую схему ${String(version)}.`);
  }
  const state = raw as unknown as P0Document;
  const legacyDocument = version !== P0_DOCUMENT_SCHEMA;
  const legacyAuthorityDocument = version === undefined || P0_PRE_PACKAGE_AUTHORITY_DOCUMENT_SCHEMAS.has(String(version));
  const legacyShortlistPresent = Boolean(record(raw.shortlist).shortlist_revision_id);
  let changed = legacyDocument;
  if (changed) state.schema_version = P0_DOCUMENT_SCHEMA;
  const legacyModel = record(state.business_model);
  if (!state.analytics_evidence_snapshot && legacyModel.analysis_evidence) {
    state.analytics_evidence_snapshot = legacyModel.analysis_evidence as AnalyticsEvidenceBundle;
    delete legacyModel.analysis_evidence;
    changed = true;
  }

  if (state.context_state) {
    if (record(state.context_state).schema_version === P0_LEGACY_CONTEXT_SCHEMA) {
      const legacyContext = state.context_state as unknown as Record<string, unknown>;
      const researchFingerprint = cleanText(String(legacyContext.material_fingerprint ?? ""), 255);
      const decision = record(legacyContext.business_goal_decision);
      legacyContext.schema_version = P0_CONTEXT_SCHEMA;
      legacyContext.context_revision_id = `context-r${Math.max(1, revision)}`;
      legacyContext.research_fingerprint = researchFingerprint;
      legacyContext.material_fingerprint = decision.value
        ? await confirmedContextMaterialFingerprint(researchFingerprint, String(decision.value))
        : researchFingerprint;
      changed = true;
    } else if (state.context_state.schema_version !== P0_CONTEXT_SCHEMA) {
      fail("P0_CONTEXT_SCHEMA_UNSUPPORTED", "Persisted Context использует неподдерживаемую схему.");
    }
    if (!state.context_state.context_revision_id || !state.context_state.research_fingerprint) {
      lineageError("Context revision или research fingerprint отсутствует.");
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
  if (state.shortlist && (!state.strategy || !state.recommendation_set)) {
    lineageError("shortlist не связан с Campaign Strategy и Recommendation Set.");
  }
  if (state.recommendation_set && !state.strategy) {
    lineageError("Recommendation Set не связан с Campaign Strategy.");
  }
  if (state.strategy && !state.business_model) {
    lineageError("Campaign Strategy не связана с моделью бизнеса.");
  }

  for (const key of ["context_state", "site_analysis", "business_model", "analytics_evidence_snapshot", "strategy_questionnaire", "strategy", "landing_advisory_run", "recommendation_set", "draft", "shortlist", "package_review", "human_decision_gate", "package_execution", "last_decision_invalidation", "external_write_intent", "campaign", "recommendation_recalculation", "last_cascade"] as const) {
    if (!(key in state)) {
      if (!legacyDocument) lineageError(`same-schema document field ${key} отсутствует.`);
      state[key] = null as never;
      changed = true;
    }
  }
  if (legacyAuthorityDocument) {
    state.shortlist = null;
    state.package_review = null;
    state.human_decision_gate = null;
    state.package_execution = null;
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
  if (modelChanged && model) {
    state.analytics_evidence_snapshot = null;
    state.strategy_questionnaire = null;
    state.last_cascade = cascadeRecord(state, "MODEL", updatedAt, ["campaign_strategy", "recommendation_set", "campaign_drafts", "shortlist", "confirmation"]);
    await invalidateDecisionAuthority(state, "MODEL_MATERIAL_CHANGE", "Legacy Model normalization changed material Campaign Strategy lineage.", updatedAt);
    invalidateStrategyDownstream(state);
  }

  if (
    !state.strategy_questionnaire
    && state.context_state
    && model?.source === "REAL_SITE_RESEARCH_PLUS_OWNER_CONFIRMATION"
    && state.analytics_evidence_snapshot
  ) {
    state.strategy_questionnaire = await buildStrategyQuestionnaire({
      contextState: state.context_state as unknown as Record<string, unknown>,
      model: model as unknown as Record<string, unknown>,
      analyticsEvidence: state.analytics_evidence_snapshot as unknown as Record<string, unknown>,
      generatedAt: updatedAt,
    });
    changed = true;
  }
  if (state.strategy_questionnaire) {
    if (!state.context_state || !model || !state.analytics_evidence_snapshot) {
      lineageError("Strategy questionnaire потерял Context, Model или Analytics Evidence Snapshot.");
    }
    const rebuiltQuestionnaire = await buildStrategyQuestionnaire({
      contextState: state.context_state as unknown as Record<string, unknown>,
      model: model as unknown as Record<string, unknown>,
      analyticsEvidence: state.analytics_evidence_snapshot as unknown as Record<string, unknown>,
      generatedAt: state.strategy_questionnaire.generated_at,
    });
    if (JSON.stringify(rebuiltQuestionnaire) !== JSON.stringify(state.strategy_questionnaire)) {
      lineageError("Strategy questionnaire contract, field order, metadata или lineage не прошли проверку.");
    }
  }

  if (state.recommendation_set) {
    if (!Object.hasOwn(state.recommendation_set, "field_registry")) {
      state.recommendation_set.field_registry = DIRECT_V501_DRAFT_FIELD_REGISTRY;
      changed = true;
    } else if (!isCanonicalDirectV501DraftFieldRegistry(state.recommendation_set.field_registry)) {
      lineageError("Recommendation Set field registry не совпадает с canonical Direct v501 registry.");
    }
  }

  const strategy = state.strategy;
  if (strategy && model) {
    if (strategy.schema_version === CAMPAIGN_STRATEGY_SCHEMA) {
      if (!state.context_state || !state.analytics_evidence_snapshot || !state.strategy_questionnaire) {
        lineageError("Campaign Strategy revision потеряла Context, questionnaire или Analytics Evidence Snapshot.");
      }
      if (
        strategy.questionnaire_id !== state.strategy_questionnaire.questionnaire_id
        || strategy.context_revision_id !== state.context_state.context_revision_id
        || strategy.context_material_fingerprint !== state.context_state.material_fingerprint
        || strategy.analytics_evidence_snapshot_id !== state.analytics_evidence_snapshot.snapshot_id
      ) {
        lineageError("Campaign Strategy revision ссылается на другую Context/Model lineage.");
      }
      const persistedAnswerRows = Array.isArray(strategy.answers)
        ? strategy.answers as Array<{ field_id: string; value: unknown }>
        : [];
      const persistedAnswers = Object.fromEntries(persistedAnswerRows.map((answer) => [answer.field_id, answer.value]));
      if (await strategyAnswersFingerprint(persistedAnswers as never) !== strategy.material_fingerprint) {
        lineageError("Campaign Strategy material fingerprint verification failed.");
      }
    }
    if (!strategy.strategy_revision_id) {
      strategy.strategy_revision_id = `campaign-strategy-r${Math.max(1, revision)}`;
      strategy.approved_at = updatedAt;
      changed = true;
    }
    if (
      !state.recommendation_set
      || state.recommendation_set.strategy_revision_id !== strategy.strategy_revision_id
      || state.recommendation_set.schema_version !== "campaign-recommendation-set-v3"
    ) {
      state.recommendation_set = await buildCampaignRecommendationSet({
        model: model as unknown as Record<string, unknown>,
        strategy: strategy as unknown as Record<string, unknown>,
        analyticsEvidence: state.analytics_evidence_snapshot as unknown as Record<string, unknown> | undefined,
        playbookReleases: [],
        directCapabilitySnapshot: state.context_state?.facts.direct.capability_snapshot ?? null,
        generatedAt: updatedAt,
      });
      changed = true;
    }
  }

  if (state.landing_advisory_run) {
    if (!strategy) lineageError("LandingAdvisoryRun потерял Campaign Strategy revision.");
    if (!await verifyLandingAdvisoryRun(state.landing_advisory_run)) {
      lineageError("LandingAdvisoryRun schema, enums, bounds или content hash verification failed.");
    }
    if (
      state.landing_advisory_run.strategy_revision_id !== strategy.strategy_revision_id
      || state.landing_advisory_run.requested_url !== normalizePublicHttpsUrl(String(strategyAnswerValue(strategy, "landing_page") ?? "")).toString()
    ) {
      lineageError("LandingAdvisoryRun ссылается на другую Strategy revision или landing URL.");
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
      draft.capability_profile_version = state.recommendation_set?.capability_profile.profile_version;
      draft.playbook_release_id = baseline.playbook_release_id;
      draft.playbook_release_version = baseline.playbook_release_version;
      draft.playbook_rule_id = baseline.playbook_rule_id;
      draft.playbook_rule_version = baseline.playbook_rule_version;
      changed = true;
      draftChanged = true;
    }
    if (draft.strategy_revision_id !== strategy.strategy_revision_id) {
      lineageError("Campaign Draft ссылается на другую Campaign Strategy revision.");
    }
    const advertisedOffer = strategyAnswerValue(strategy, "advertised_offer") || model.product;
    const geography = strategyAnswerValue(strategy, "geography");
    const qualifiedResult = strategyAnswerValue(strategy, "qualified_result") || model.qualified_result;
    const names = buildCampaignNames(advertisedOffer, geography, qualifiedResult);
    if (
      isLegacySearchName(draft.campaign_name)
      || isCampaignNameWithGeography(draft.campaign_name, geography)
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

  if (strategy && state.recommendation_set) {
    if (legacyAuthorityDocument) {
      state.shortlist = await emptyShortlist({
        shortlistRevisionId: `p0-shortlist-r${Math.max(1, revision + 1)}`,
        strategyRevisionId: String(strategy.strategy_revision_id ?? ""),
        recommendationSetId: state.recommendation_set.recommendation_set_id,
        updatedAt,
      });
      if (legacyShortlistPresent) {
        await invalidateDecisionAuthority(
          state,
          "LEGACY_AUTHORITY_REQUIRES_REVIEW",
          "Legacy provisional one-Draft shortlist was discarded; exact package review is required.",
          updatedAt,
        );
      }
      changed = true;
    } else if (!state.shortlist) {
      lineageError("versioned shortlist отсутствует у текущего Recommendation Set.");
    } else if (!await verifyShortlist(state.shortlist, state.recommendation_set, String(strategy.strategy_revision_id ?? ""))) {
      lineageError("shortlist content hash, order или exact Draft lineage не прошли проверку.");
    }
    const binding = directAccountBinding(state);
    const capabilitySnapshot = state.context_state?.facts.direct.capability_snapshot;
    const evidenceSnapshotId = state.analytics_evidence_snapshot?.snapshot_id;
    if (state.package_review) {
      if (!binding || !capabilitySnapshot || !evidenceSnapshotId || !state.shortlist
        || !await verifyPackageReview({
          review: state.package_review,
          shortlist: state.shortlist,
          recommendationSet: state.recommendation_set,
          strategyRevisionId: String(strategy.strategy_revision_id ?? ""),
          accountBinding: binding,
          capabilitySnapshot: capabilitySnapshot as unknown as Record<string, unknown>,
          analyticsEvidenceSnapshotId: evidenceSnapshotId,
        })) {
        lineageError("package review identity или exact authority snapshot не прошли проверку.");
      }
    }
    if (state.human_decision_gate) {
      if (!state.package_review || !await verifyHumanDecisionGate(state.human_decision_gate, state.package_review)) {
        lineageError("Human Decision Gate confirmation или package authority не прошли проверку.");
      }
    }
    if (state.package_execution && legacyDocument && record(state.package_execution).schema_version === "p0-package-execution-v1") {
      try {
        state.package_execution = await migrateLegacyPackageExecution(state.package_execution, updatedAt);
        changed = true;
      } catch (error) {
        lineageError(`legacy package execution migration failed: ${errorMessage(error)}`);
      }
    }
    if (state.package_execution) {
      if (!state.human_decision_gate || !await verifyPackageExecution({
        execution: state.package_execution,
        gate: state.human_decision_gate,
        recommendationSet: state.recommendation_set,
      })) {
        lineageError("package execution identity, item order или durable outcome hash не прошли проверку.");
      }
    }
  } else if (state.shortlist || state.package_review || state.human_decision_gate || state.package_execution) {
    lineageError("shortlist/package authority или execution существует без Strategy и Recommendation Set.");
  }
  if (state.last_decision_invalidation && !await verifyDecisionInvalidation(state.last_decision_invalidation)) {
    lineageError("decision invalidation audit hash verification failed.");
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
  if (state.package_review || state.human_decision_gate) return 4;
  if (state.strategy) return 3;
  if (state.business_model?.source === "REAL_SITE_RESEARCH_PLUS_OWNER_CONFIRMATION") return 2;
  if (state.business_model) return 1;
  return 0;
}

function allowedCommands(state: P0Document): CommandName[] {
  if (state.last_cascade?.recomputation_status === "PENDING") return [];
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

function shortlistControls(state: P0Document) {
  if (!state.recommendation_set || !state.shortlist) return [];
  return state.recommendation_set.drafts.map((draft) => {
    const selected = state.shortlist?.selections.find((item) => item.draft_id === draft.draft_id);
    if (selected) return { draft_id: draft.draft_id, status: "SELECTED" as const, disabled_reason: null };
    const removed = state.shortlist?.removed_selections.find((item) => item.draft_id === draft.draft_id);
    const blocker = shortlistSelectionBlockReason(draft);
    if (blocker) return { draft_id: draft.draft_id, status: "BLOCKED" as const, disabled_reason: blocker };
    return { draft_id: draft.draft_id, status: removed ? "REMOVED" as const : "AVAILABLE" as const, disabled_reason: null };
  });
}

function decisionReadiness(state: P0Document) {
  const blockers: string[] = [];
  if (!state.shortlist) blockers.push("Versioned shortlist ещё не создан.");
  else if (!state.shortlist.selections.length) blockers.push("Shortlist пуст: выберите хотя бы один publish-ready Draft.");
  if (!state.package_review) blockers.push("Точный package review ещё не выполнен.");
  return {
    ready: blockers.length === 0,
    blockers,
    confirmed: Boolean(state.human_decision_gate),
    independent_execution: true,
    external_writes_performed: Boolean(state.package_execution),
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

  private async buildLandingAdvisory(state: P0Document) {
    if (!state.strategy || !state.context_state || !state.analytics_evidence_snapshot) {
      fail("P0_PREREQUISITE_MISSING", "Landing advisory требует exact Strategy, Context и Analytics Evidence Snapshot lineage.");
    }
    return runLandingAdvisory({
      strategy: state.strategy as Record<string, unknown>,
      contextState: state.context_state as unknown as Record<string, unknown>,
      analyticsEvidence: state.analytics_evidence_snapshot as unknown as Record<string, unknown>,
      adapter: this.adapters.landingAdvisory ?? unavailableLandingAdvisoryAdapter,
      now: () => this.adapters.now(),
    });
  }

  private async playbookReleases() {
    return this.adapters.readPlaybookReleases ? await this.adapters.readPlaybookReleases() : [];
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
        validateWeeklyBudgetRub(strategyAnswerValue(state.strategy, "weekly_budget"), minimumBudget);
      } catch (error) {
        blockers.push(errorMessage(error));
      }
    }
    if (["REQUIRED", "PENDING"].includes(String(state.last_cascade?.recomputation_status ?? ""))) {
      blockers.push("Downstream recomputation ещё не завершён");
    }
    if (!state.package_review || !state.human_decision_gate) {
      blockers.push("Точный package review и Human Decision Gate ещё не подтверждены");
    }
    if (state.package_execution) {
      blockers.push(`Package execution уже создано со статусом ${state.package_execution.status}`);
    }
    const uniqueBlockers = [...new Set(blockers)];
    return { ready: uniqueBlockers.length === 0, blockers: uniqueBlockers };
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
      shortlist_controls: shortlistControls(viewState),
      decision_readiness: decisionReadiness(viewState),
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
      const researchFingerprint = await contextResearchFingerprint(site, context);
      const previousContext = state.context_state;
      const normalizationOnly = previousContext?.research_fingerprint === researchFingerprint;
      if (normalizationOnly && previousContext) {
        // Keep the exact persisted evidence/provenance; a technical re-entry only advances document revision.
      } else {
        state.site_analysis = site;
        const hasPreviousContext = Boolean(previousContext || state.business_model || state.strategy || state.draft || state.shortlist);
        const lastMaterialChange = hasPreviousContext ? invalidationRecord(state, timestamp) : null;
        if (hasPreviousContext) {
          state.last_cascade = cascadeRecord(state, "CONTEXT", timestamp, ["campaign_strategy", "recommendation_set", "campaign_drafts", "shortlist", "confirmation"]);
          const capabilityChanged = previousContext
            && JSON.stringify(directCapabilityMaterialFacts(previousContext.facts.direct.capability_snapshot))
              !== JSON.stringify(providerMaterialFacts(context).direct.capability_snapshot);
          await invalidateDecisionAuthority(
            state,
            capabilityChanged ? "ACCOUNT_OR_CAPABILITY_LINEAGE_CHANGED" : "CONTEXT_MATERIAL_CHANGE",
            capabilityChanged
              ? "Exact Direct account or capability lineage changed during Context reanalysis."
              : "Material Context research changed after package review.",
            timestamp,
          );
        }
        state.context_state = {
          schema_version: P0_CONTEXT_SCHEMA,
          status: "GOAL_PROVISIONAL",
          facts: persistedContextFacts(site, context),
          provisional_business_goal: provisionalBusinessGoal(site, timestamp),
          business_goal_decision: null,
          context_revision_id: `context-r${current.revision + 1}`,
          research_fingerprint: researchFingerprint,
          material_fingerprint: researchFingerprint,
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
        state.last_cascade = cascadeRecord(state, "CONTEXT", timestamp, ["campaign_strategy", "recommendation_set", "campaign_drafts", "shortlist", "confirmation"]);
        await invalidateDecisionAuthority(state, "CONTEXT_MATERIAL_CHANGE", "Confirmed Context goal changed materially.", timestamp);
        invalidateContextDownstream(state);
      }
      const contextDecisionChanged = !previousDecision || changedConfirmedGoal;
      const provisionalValue = state.context_state.provisional_business_goal.value;
      state.context_state = {
        ...state.context_state,
        status: "GOAL_CONFIRMED",
        facts: persistedContextFacts(state.site_analysis, context),
        business_goal_decision: {
          value: goal,
          provisional_value: provisionalValue,
          decision: goal === provisionalValue ? "CONFIRMED" : "CORRECTED",
          decided_at: contextDecisionChanged ? timestamp : previousDecision.decided_at,
          owner_confirmed: true,
        },
        context_revision_id: contextDecisionChanged ? `context-r${current.revision + 1}` : state.context_state.context_revision_id,
        material_fingerprint: contextDecisionChanged
          ? await confirmedContextMaterialFingerprint(state.context_state.research_fingerprint, goal)
          : state.context_state.material_fingerprint,
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
      if (!state.site_analysis || !state.context_state) {
        fail("P0_EVIDENCE_LINEAGE_INVALID", "Model потеряла persisted Context или first-party site analysis.");
      }
      const value = record(payload.value);
      const fields = ["product", "audience", "value", "qualified_result", "exclusions"] as const;
      const confirmedValues = Object.fromEntries(fields.map((field) => {
        const confirmedValue = artifactText(value[field], 1_000);
        if (!confirmedValue) fail("P0_INPUT_REQUIRED", `Поле ${field} требует подтверждённого значения.`);
        return [field, confirmedValue];
      }));
      const firstOwnerApproval = state.business_model.source !== "REAL_SITE_RESEARCH_PLUS_OWNER_CONFIRMATION";
      const materialModelChange = fields.some((field) => cleanText(String(state.business_model?.[field] ?? ""), 1_000) !== confirmedValues[field]);
      const modelApprovedAt = this.adapters.now();
      const context = sanitizeContext(await this.adapters.readContext());
      this.assertContextPreflight(context, modelApprovedAt);
      this.assertPersistedBindings(state, context);
      if (materialModelChange && (state.strategy || state.draft || state.shortlist)) {
        state.last_cascade = cascadeRecord(state, "MODEL", modelApprovedAt, ["campaign_strategy", "recommendation_set", "campaign_drafts", "shortlist", "confirmation"]);
        await invalidateDecisionAuthority(state, "MODEL_MATERIAL_CHANGE", "Material Model evidence or owner-confirmed facts changed.", modelApprovedAt);
        invalidateStrategyDownstream(state);
      }
      const modelRecomputationRequired = !state.analytics_evidence_snapshot;
      if (firstOwnerApproval || materialModelChange || modelRecomputationRequired) {
        for (const field of fields) {
          const fieldChanged = cleanText(String(state.business_model[field] ?? ""), 1_000) !== confirmedValues[field];
          state.business_model[field] = confirmedValues[field];
          state.business_model.field_evidence[field] = {
            ...state.business_model.field_evidence[field],
            confidence: "OWNER_CONFIRMED",
            owner_confirmed: true,
            owner_confirmed_at: modelApprovedAt,
            owner_edited: state.business_model.field_evidence[field]?.owner_edited === true || fieldChanged,
          };
        }
        state.business_model.source = "REAL_SITE_RESEARCH_PLUS_OWNER_CONFIRMATION";
        state.business_model.assumptions = [];
        state.business_model.missing_questions = [];
        state.analytics_evidence_snapshot = await this.buildModelEvidence(
          state.site_analysis,
          state.business_model,
          context,
          modelApprovedAt,
        );
        state.strategy_questionnaire = await buildStrategyQuestionnaire({
          contextState: state.context_state as unknown as Record<string, unknown>,
          model: state.business_model as unknown as Record<string, unknown>,
          analyticsEvidence: state.analytics_evidence_snapshot as unknown as Record<string, unknown>,
          generatedAt: modelApprovedAt,
        });
      } else if (!state.strategy_questionnaire && state.analytics_evidence_snapshot) {
        state.strategy_questionnaire = await buildStrategyQuestionnaire({
          contextState: state.context_state as unknown as Record<string, unknown>,
          model: state.business_model as unknown as Record<string, unknown>,
          analyticsEvidence: state.analytics_evidence_snapshot as unknown as Record<string, unknown>,
          generatedAt: modelApprovedAt,
        });
      }
    } else if (action === "approve_strategy") {
      if (payload.confirmation !== "APPROVE_CAMPAIGN_STRATEGY") {
        fail("P0_STRATEGY_APPROVAL_REQUIRED", "Нужно одним точным подтверждением утвердить всю Campaign Strategy.");
      }
      if (!state.business_model || !state.context_state || !state.analytics_evidence_snapshot || !state.strategy_questionnaire) {
        fail("P0_PREREQUISITE_MISSING", "Сначала подтвердите Model и подготовьте Strategy questionnaire.");
      }
      const questionnaire = state.strategy_questionnaire;
      if (
        questionnaire.context_revision_id !== state.context_state.context_revision_id
        || questionnaire.context_material_fingerprint !== state.context_state.material_fingerprint
        || questionnaire.analytics_evidence_snapshot_id !== state.analytics_evidence_snapshot.snapshot_id
      ) {
        fail("P0_STRATEGY_LINEAGE_STALE", "Strategy questionnaire устарел после material Context или Model change.");
      }
      const normalizedAnswers = normalizeStrategyAnswers(
        payload.answers,
        (input, maximum) => artifactText(input, maximum),
      );
      const missing = missingStrategyDecisions(normalizedAnswers);
      if (missing.length) {
        fail("P0_STRATEGY_DECISION_REQUIRED", `Campaign Strategy требует решения владельца: ${missing[0]}.`);
      }
      const confirmedContextGoal = state.context_state.business_goal_decision?.value;
      if (normalizedAnswers.business_goal !== confirmedContextGoal) {
        fail("P0_CONTEXT_GOAL_CHANGED", "Измените business goal на шаге «Контекст», чтобы применить material cascade.");
      }
      const period = normalizedAnswers.period as { start_date: string; end_date: string };
      if (!isValidIsoCalendarDate(period.start_date) || !isValidIsoCalendarDate(period.end_date) || period.start_date > period.end_date) {
        fail("P0_STRATEGY_PERIOD_INVALID", "Период Campaign Strategy должен содержать допустимые даты в правильном порядке.");
      }
      normalizedAnswers.landing_page = normalizePublicHttpsUrl(String(normalizedAnswers.landing_page)).toString();
      const limits = await this.adapters.readCurrencyLimits();
      validateWeeklyBudgetRub(normalizedAnswers.weekly_budget, limits.minimum_weekly_budget_rub);
      const materialFingerprint = await strategyAnswersFingerprint(normalizedAnswers);
      const existingStrategy = state.strategy;
      if (existingStrategy?.material_fingerprint !== materialFingerprint) {
        const approvedAt = this.adapters.now();
        const stateBeforeRecomputation = structuredClone(state);
        state.last_cascade = {
          ...cascadeRecord(state, "STRATEGY", approvedAt, ["recommendation_set", "campaign_drafts", "shortlist", "confirmation"]),
          recomputation_status: "PENDING",
        };
        if (existingStrategy || state.package_review || state.human_decision_gate || state.shortlist?.selections.length) {
          await invalidateDecisionAuthority(state, "STRATEGY_MATERIAL_CHANGE", "Material Campaign Strategy revision changed.", approvedAt);
        }
        const pendingRow: P0StoredRow = {
          revision: persistedRevision + 1,
          updated_at: approvedAt,
          value_json: JSON.stringify(state),
        };
        if (!await this.store.compareAndSwap(key, persistedRevision, pendingRow)) {
          fail("P0_REVISION_CONFLICT", "P0 изменился в другой вкладке. Обновите страницу.");
        }
        persistedRevision = pendingRow.revision;
        try {
          state.strategy = {
            schema_version: CAMPAIGN_STRATEGY_SCHEMA,
            strategy_revision_id: `campaign-strategy-r${persistedRevision + 1}`,
            questionnaire_id: questionnaire.questionnaire_id,
            questionnaire_contract_version: questionnaire.contract_version,
            context_revision_id: state.context_state.context_revision_id,
            context_material_fingerprint: state.context_state.material_fingerprint,
            analytics_evidence_snapshot_id: state.analytics_evidence_snapshot.snapshot_id,
            answers: questionnaire.fields.map((field) => ({
              field_id: field.field_id,
              value: normalizedAnswers[field.field_id]!,
            })),
            material_fingerprint: materialFingerprint,
            approved_at: approvedAt,
            approved_by: "OWNER",
            approval_command: "APPROVE_CAMPAIGN_STRATEGY",
            lineage: {
              previous_strategy_revision_id: existingStrategy ? String(existingStrategy.strategy_revision_id ?? "") || null : null,
            },
          };
          state.recommendation_set = await buildCampaignRecommendationSet({
            model: state.business_model as unknown as Record<string, unknown>,
            strategy: state.strategy as unknown as Record<string, unknown>,
            analyticsEvidence: state.analytics_evidence_snapshot as unknown as Record<string, unknown>,
            playbookReleases: await this.playbookReleases(),
            directCapabilitySnapshot: state.context_state?.facts.direct.capability_snapshot ?? null,
            generatedAt: approvedAt,
          });
          state.landing_advisory_run = await this.buildLandingAdvisory(state);
          state.draft = null;
          state.shortlist = await emptyShortlist({
            shortlistRevisionId: `p0-shortlist-r${persistedRevision + 1}`,
            strategyRevisionId: String(state.strategy.strategy_revision_id ?? ""),
            recommendationSetId: state.recommendation_set.recommendation_set_id,
            updatedAt: approvedAt,
          });
          state.package_review = null;
          state.human_decision_gate = null;
          state.external_write_intent = null;
          state.recommendation_recalculation = null;
          state.last_cascade.recomputation_status = "COMPLETE";
        } catch (error) {
          const rollbackAt = this.adapters.now();
          const rollbackRow: P0StoredRow = {
            revision: persistedRevision + 1,
            updated_at: rollbackAt,
            value_json: JSON.stringify(stateBeforeRecomputation),
          };
          if (!await this.store.compareAndSwap(key, persistedRevision, rollbackRow)) {
            fail("P0_RECOMPUTATION_RECOVERY_REQUIRED", "Strategy recomputation не завершён; confirmation остаётся заблокированным до recovery.");
          }
          throw error;
        }
      }
    } else if (action === "run_landing_advisory") {
      state.landing_advisory_run = await this.buildLandingAdvisory(state);
    } else if (action === "recalculate_recommendations") {
      if (!state.strategy || !state.business_model || !state.analytics_evidence_snapshot || !state.recommendation_set) {
        fail("P0_PREREQUISITE_MISSING", "Recommendation recalculation требует exact Strategy, Model, Evidence Snapshot и текущий Recommendation Set.");
      }
      const recalculatedAt = this.adapters.now();
      const previousSet = state.recommendation_set;
      const playbookReleases = await this.playbookReleases();
      const releaseChanged = JSON.stringify(activePlaybookReleaseIdentity(previousSet))
        !== JSON.stringify(await resolveActivePlaybookReleaseIdentity(playbookReleases));
      let changes: Array<Record<string, unknown>> = [];
      if (releaseChanged) {
        const currentSet = await buildCampaignRecommendationSet({
          model: state.business_model as unknown as Record<string, unknown>,
          strategy: state.strategy as unknown as Record<string, unknown>,
          analyticsEvidence: state.analytics_evidence_snapshot as unknown as Record<string, unknown>,
          playbookReleases,
          directCapabilitySnapshot: state.context_state?.facts.direct.capability_snapshot ?? null,
          generatedAt: recalculatedAt,
        });
        changes = recommendationRecalculationChanges(previousSet, currentSet);
        const replacement = correspondingDraft(state.draft, currentSet);
        await invalidateDecisionAuthority(state, "PLAYBOOK_REGENERATION", "Active governed playbook regeneration changed exact Recommendation Set lineage.", recalculatedAt);
        state.recommendation_set = currentSet;
        state.draft = replacement;
        state.shortlist = await emptyShortlist({
          shortlistRevisionId: `p0-shortlist-r${current.revision + 1}`,
          strategyRevisionId: String(state.strategy.strategy_revision_id ?? ""),
          recommendationSetId: currentSet.recommendation_set_id,
          updatedAt: recalculatedAt,
        });
        state.external_write_intent = null;
      }
      state.recommendation_recalculation = {
        schema_version: "p0-recommendation-recalculation-v1",
        material_change: releaseChanged,
        message: releaseChanged
          ? "Активный curated playbook изменился или был откачен; Recommendation Set регенерирован по exact release lineage."
          : "Active playbook check завершён без material изменения active release lineage.",
        reason_code: releaseChanged ? "ACTIVE_PLAYBOOK_RELEASE_CHANGED_OR_ROLLED_BACK" : "NO_ACTIVE_PLAYBOOK_MATERIAL_CHANGE",
        recalculated_at: recalculatedAt,
        previous_recommendation_set_id: previousSet.recommendation_set_id,
        current_recommendation_set_id: state.recommendation_set.recommendation_set_id,
        previous_playbook_release_id: String(previousSet.playbook_release.release_id ?? "") || null,
        current_playbook_release_id: String(state.recommendation_set.playbook_release.release_id ?? "") || null,
        changes,
        evaluator_traces_exposed: false,
      };
    } else if (action === "save_draft") {
      const value = record(payload.value);
      if (!state.strategy || !state.business_model) {
        fail("P0_PREREQUISITE_MISSING", "Сначала подтвердите модель и Strategy.");
      }
      const editableRegistryFields = DIRECT_V501_DRAFT_FIELD_REGISTRY.fields
        .filter((field) => field.editable && field.input_name);
      const allowedDraftInputs = new Set(["draft_id", ...editableRegistryFields.map((field) => String(field.input_name))]);
      const unsupportedDraftInput = Object.keys(value).find((field) => !allowedDraftInputs.has(field));
      if (unsupportedDraftInput) {
        fail("P0_DRAFT_FIELD_UNSUPPORTED", `Campaign Draft field ${unsupportedDraftInput} is not editable in the current exact projection contract and was not applied.`);
      }
      const draftId = requiredInput(value.draft_id, "Campaign Draft", 255);
      const recommendationSet = state.recommendation_set;
      const generated = recommendationSet?.drafts.find((item) => item.draft_id === draftId);
      if (!recommendationSet || !generated) {
        fail("P0_DRAFT_INVALID", "Выбранный Campaign Draft не принадлежит текущей Strategy revision.");
      }
      const normalizedFields = Object.fromEntries(editableRegistryFields.map((registryField) => {
        const fieldName = String(registryField.input_name);
        return [fieldName, requiredInput(value[fieldName], registryField.label, Number(registryField.maximum_length))];
      }));
      const lineage = {
        draft_id: draftId,
        draft_revision_id: generated.draft_revision_id,
        strategy_revision_id: state.strategy.strategy_revision_id,
        capability_profile_id: recommendationSet.capability_profile.profile_id,
        capability_profile_version: recommendationSet.capability_profile.profile_version,
        playbook_release_id: generated.playbook_release_id,
        playbook_release_version: generated.playbook_release_version,
        playbook_rule_id: generated.playbook_rule_id,
        playbook_rule_version: generated.playbook_rule_version,
      };
      const normalized = { ...normalizedFields, ...lineage };
      const normalizedProjection = buildPublishProjection(
        state.business_model as unknown as Record<string, unknown>,
        state.strategy,
        normalized,
      ) as unknown as Record<string, unknown>;
      const normalizedCapability = preserveSelectedConditionalProjection({
        generatedDraft: generated,
        editedProjection: normalizedProjection,
        snapshot: state.context_state?.facts.direct.capability_snapshot ?? null,
      });
      const normalizedFingerprint = await fingerprintDirectProjection(normalizedCapability.projection);
      const editedAt = this.adapters.now();
      const noMaterialChange = normalizedFingerprint === generated.publish_fingerprint;
      if (noMaterialChange) {
        const draftSaveResult = {
          schema_version: "p0-draft-save-result-v1",
          material_change: false,
          message: "Нет material changes: нормализация не создала Draft revision.",
          previous_draft_revision_id: generated.draft_revision_id,
          current_draft_revision_id: generated.draft_revision_id,
          previous_publish_fingerprint: generated.publish_fingerprint,
          current_publish_fingerprint: generated.publish_fingerprint,
          changed_fields: [] as Array<Record<string, unknown>>,
        };
        state.draft = {
          ...generated,
          material_delta: null,
          score_delta: null,
          draft_save_result: draftSaveResult,
        };
        recommendationSet.drafts = recommendationSet.drafts.map((item) => item.draft_id === draftId
          ? state.draft as typeof item : item);
      } else {
        const nextDraftRevision = nextDraftRevisionId(draftId, generated.draft_revision_id);
        const materialLineage = { ...normalized, draft_revision_id: nextDraftRevision };
        const basicProjection = buildPublishProjection(
          state.business_model as unknown as Record<string, unknown>,
          state.strategy,
          materialLineage,
        ) as unknown as Record<string, unknown>;
        const preservedCapability = preserveSelectedConditionalProjection({
          generatedDraft: generated,
          editedProjection: basicProjection,
          snapshot: state.context_state?.facts.direct.capability_snapshot ?? null,
        });
        const projection = preservedCapability.projection;
        const materialFields = directProjectionMaterialDelta(generated.publish_projection, projection);
        if (!materialFields.length) {
          fail("P0_DRAFT_MATERIALITY_INVALID", "Publish fingerprint changed without a supported Direct field delta.");
        }
        const scoreEvidence = state.analytics_evidence_snapshot;
        if (!scoreEvidence) {
          fail("P0_EVIDENCE_LINEAGE_INVALID", "Scoring требует persisted Analytics Evidence Snapshot из Model revision.");
        }
        const capabilityBlockerCodes = new Set([
          "UNSUPPORTED_SELECTED_FIELD",
          "CONDITIONAL_CAPABILITY_EVIDENCE_MISSING",
          "CONDITIONAL_CAPABILITY_ACCOUNT_INELIGIBLE",
        ]);
        const publicationBlockers = (Array.isArray(generated.publication_blockers) ? generated.publication_blockers : [])
          .filter((blocker) => !capabilityBlockerCodes.has(String((blocker as Record<string, unknown>).code ?? "")));
        publicationBlockers.push(...preservedCapability.capability_selection.blockers.map((blocker) => ({
          code: blocker.code,
          message: blocker.message,
          field_path: blocker.field_path,
        })));
        const publishEligibility = publicationBlockers.some((blocker) => String((blocker as Record<string, unknown>).code ?? "") === "DEMAND_EVIDENCE_GAP")
          ? "BLOCKED_EVIDENCE_GAP" : publicationBlockers.length === 0 ? "ELIGIBLE" : "BLOCKED_HARD";
        const editedDraft = {
          ...generated,
          ...materialLineage,
          source: "OWNER_REVIEWED_PUBLISH_PROJECTION",
          edited_at: editedAt,
          capability_selection: preservedCapability.capability_selection,
          unsupported_fields: preservedCapability.capability_selection.unsupported_fields,
          publication_blockers: publicationBlockers,
          shortlist_eligible: publishEligibility === "ELIGIBLE",
          publish_eligibility: publishEligibility,
          publish_projection: projection,
          publish_fingerprint: await fingerprintDirectProjection(projection),
        } as typeof generated;
        const exactDraftRevision = recommendationSet.drafts.map((item) => item.draft_id === draftId ? editedDraft : item);
        const rescoredRecommendationSetId = await recommendationSetRevisionId(recommendationSet.recommendation_set_id, exactDraftRevision);
        const rescored = await scoreCampaignDrafts({
          recommendationSetId: rescoredRecommendationSetId,
          drafts: exactDraftRevision,
          model: state.business_model as unknown as Record<string, unknown>,
          strategy: state.strategy,
          analyticsEvidence: scoreEvidence as unknown as Record<string, unknown>,
          scoredAt: editedAt,
        });
        const currentDraft = rescored.find((item) => item.draft_id === draftId);
        if (!currentDraft) fail("P0_DRAFT_INVALID", "Пересчёт Campaign Draft не вернул выбранную ревизию.");
        const scoreDelta = explainScoreDelta(
          generated.viability_score,
          currentDraft.viability_score,
          materialFields.map((field) => field.pointer),
        );
        const draftSaveResult = {
          schema_version: "p0-draft-save-result-v1",
          material_change: true,
          message: "Создана новая immutable Draft revision; полный Recommendation Set пересчитан.",
          previous_draft_revision_id: generated.draft_revision_id,
          current_draft_revision_id: currentDraft.draft_revision_id,
          previous_publish_fingerprint: generated.publish_fingerprint,
          current_publish_fingerprint: currentDraft.publish_fingerprint,
          changed_fields: materialFields,
        };
        state.draft = {
          ...currentDraft,
          material_delta: {
            schema_version: "p0-draft-material-delta-v1",
            changed_at: editedAt,
            previous_draft_revision_id: generated.draft_revision_id,
            current_draft_revision_id: currentDraft.draft_revision_id,
            previous_publish_fingerprint: generated.publish_fingerprint,
            current_publish_fingerprint: currentDraft.publish_fingerprint,
            fields: materialFields,
            policy_reason: scoreDelta.comparative_priority_reason,
          },
          score_delta: scoreDelta,
          draft_save_result: draftSaveResult,
        };
        recommendationSet.recommendation_set_id = rescoredRecommendationSetId;
        recommendationSet.drafts = rescored.map((item) => item.draft_id === draftId ? state.draft as typeof item : item);
        recommendationSet.candidate_audit = recommendationSet.candidate_audit.map((candidate) => {
          if (candidate.candidate_type !== "DRAFT" || !candidate.draft_id) return candidate;
          const rescoredDraft = recommendationSet.drafts.find((item) => item.draft_id === candidate.draft_id);
          return rescoredDraft ? {
            ...candidate,
            visibility: rescoredDraft.visibility,
            reason_code: rescoredDraft.visibility === "VISIBLE"
              ? "VISIBLE:GENERATED_DRAFT"
              : String(rescoredDraft.suppression_reason || "HIDDEN:STRUCTURAL"),
          } : candidate;
        });
        recommendationSet.coverage.visible_count = recommendationSet.candidate_audit.filter((candidate) => candidate.visibility === "VISIBLE").length;
        recommendationSet.coverage.hidden_count = recommendationSet.candidate_audit.length - Number(recommendationSet.coverage.visible_count);
        recommendationSet.coverage.visible_drafts = recommendationSet.drafts.filter((item) => item.visibility === "VISIBLE").length;
        recommendationSet.coverage.hidden_drafts = recommendationSet.drafts.length - Number(recommendationSet.coverage.visible_drafts);
        await invalidateDecisionAuthority(state, "DRAFT_MATERIAL_CHANGE", "A material publishable Campaign Draft edit changed exact package lineage.", editedAt);
        if (!state.shortlist) fail("P0_SHORTLIST_MISSING", "Versioned shortlist отсутствует у current Recommendation Set.");
        state.shortlist = await rebaseShortlist({
          previous: state.shortlist,
          recommendationSet,
          shortlistRevisionId: `p0-shortlist-r${current.revision + 1}`,
          updatedAt: editedAt,
        });
      }
    } else if (action === "add_to_shortlist" || action === "remove_from_shortlist" || action === "restore_to_shortlist") {
      if (!state.strategy || !state.recommendation_set || !state.shortlist) {
        fail("P0_SHORTLIST_MISSING", "Shortlist mutation требует current Strategy и Recommendation Set.");
      }
      const draftId = requiredInput(payload.draft_id, "Campaign Draft", 255);
      const draft = state.recommendation_set.drafts.find((item) => item.draft_id === draftId);
      if (!draft) fail("P0_DRAFT_INVALID", "Draft отсутствует в current Recommendation Set.");
      const changedAt = this.adapters.now();
      const selections = structuredClone(state.shortlist.selections);
      let removedSelections = structuredClone(state.shortlist.removed_selections);
      if (action === "add_to_shortlist") {
        if (selections.some((item) => item.draft_id === draftId)) {
          fail("P0_SHORTLIST_DUPLICATE", "Draft уже присутствует в ordered shortlist.");
        }
        if (removedSelections.some((item) => item.draft_id === draftId)) {
          fail("P0_SHORTLIST_RESTORE_REQUIRED", "Removed Draft нужно вернуть через restore, чтобы сохранить positional semantics.");
        }
        try {
          selections.push(selectionForDraft(draft, state.recommendation_set));
        } catch (error) {
          fail("P0_SHORTLIST_BLOCKED", errorMessage(error));
        }
      } else if (action === "remove_from_shortlist") {
        const index = selections.findIndex((item) => item.draft_id === draftId);
        if (index < 0) fail("P0_SHORTLIST_NOT_SELECTED", "Draft отсутствует в ordered shortlist.");
        const [removed] = selections.splice(index, 1);
        removedSelections = [
          ...removedSelections.filter((item) => item.draft_id !== draftId),
          { ...removed, removed_at: changedAt, removed_index: stableRemovedIndex(index, removedSelections) },
        ];
      } else {
        const removed = removedSelections.find((item) => item.draft_id === draftId);
        if (!removed) fail("P0_SHORTLIST_NOT_REMOVED", "Draft не имеет current removed disposition для restore.");
        let exact;
        try {
          exact = selectionForDraft(draft, state.recommendation_set);
        } catch (error) {
          fail("P0_SHORTLIST_BLOCKED", errorMessage(error));
        }
        const removedIdentity = {
          draft_id: removed.draft_id,
          draft_revision_id: removed.draft_revision_id,
          publish_fingerprint: removed.publish_fingerprint,
          strategy_revision_id: removed.strategy_revision_id,
          capability_profile_id: removed.capability_profile_id,
          capability_profile_version: removed.capability_profile_version,
          recommendation_set_id: removed.recommendation_set_id,
        };
        if (JSON.stringify(removedIdentity) !== JSON.stringify(exact)) {
          fail("P0_SHORTLIST_STALE", "Removed Draft revision больше не совпадает с current authoritative Draft.");
        }
        selections.splice(restoredInsertionIndex(removed, removedSelections, selections.length), 0, exact);
        removedSelections = removedSelections.filter((item) => item.draft_id !== draftId);
      }
      if (state.package_review || state.human_decision_gate || state.shortlist.selections.length > 0) {
        await invalidateDecisionAuthority(
          state,
          action === "restore_to_shortlist" ? "SHORTLIST_ORDER_CHANGED" : "SHORTLIST_MEMBERSHIP_CHANGED",
          action === "add_to_shortlist"
            ? "Draft added to ordered shortlist."
            : action === "remove_from_shortlist"
              ? "Draft removed from ordered shortlist without changing Recommendation Set evidence or candidate audit."
              : "Removed Draft restored at its previous shortlist position.",
          changedAt,
        );
      }
      state.shortlist = await reviseShortlist({
        previous: state.shortlist,
        shortlistRevisionId: `p0-shortlist-r${current.revision + 1}`,
        updatedAt: changedAt,
        selections,
        removedSelections,
      });
    } else if (action === "review_package") {
      if (!state.strategy || !state.recommendation_set || !state.shortlist || !state.analytics_evidence_snapshot || !state.context_state) {
        fail("P0_PACKAGE_PREREQUISITE_MISSING", "Package review требует current Strategy, Recommendation Set, shortlist, Context и Evidence Snapshot.");
      }
      if (!state.shortlist.selections.length) fail("P0_PACKAGE_EMPTY", "Empty shortlist cannot be reviewed.");
      const reviewedAt = this.adapters.now();
      const binding = directAccountBinding(state);
      if (!binding) fail("P0_PACKAGE_ACCOUNT_BINDING_INVALID", "Exact Direct account binding отсутствует.");
      if (!state.package_review) {
        try {
          state.package_review = await buildPackageReview({
            shortlist: state.shortlist,
            recommendationSet: state.recommendation_set,
            strategyRevisionId: String(state.strategy.strategy_revision_id ?? ""),
            accountBinding: binding,
            capabilitySnapshot: state.context_state.facts.direct.capability_snapshot as unknown as Record<string, unknown>,
            analyticsEvidenceSnapshotId: state.analytics_evidence_snapshot.snapshot_id,
            reviewedAt,
          });
        } catch (error) {
          fail("P0_PACKAGE_STALE", errorMessage(error));
        }
        state.human_decision_gate = null;
      }
    } else if (action === "confirm_package") {
      if (payload.confirmation !== PACKAGE_CONFIRMATION_TOKEN) {
        fail("P0_PACKAGE_CONFIRMATION_REQUIRED", `Нужно точное подтверждение ${PACKAGE_CONFIRMATION_TOKEN}.`);
      }
      if (!state.package_review || !state.shortlist || !state.recommendation_set || !state.strategy || !state.context_state || !state.analytics_evidence_snapshot) {
        fail("P0_PACKAGE_REVIEW_MISSING", "Сначала выполните current package review.");
      }
      if (payload.package_review_id !== state.package_review.package_review_id || payload.package_id !== state.package_review.package_id) {
        fail("P0_PACKAGE_IDENTITY_STALE", "Package review identity изменилась; повторите review и confirmation.");
      }
      const confirmedAt = this.adapters.now();
      const binding = directAccountBinding(state);
      if (!binding || !await verifyPackageReview({
        review: state.package_review,
        shortlist: state.shortlist,
        recommendationSet: state.recommendation_set,
        strategyRevisionId: String(state.strategy.strategy_revision_id ?? ""),
        accountBinding: binding,
        capabilitySnapshot: state.context_state.facts.direct.capability_snapshot as unknown as Record<string, unknown>,
        analyticsEvidenceSnapshotId: state.analytics_evidence_snapshot.snapshot_id,
      })) {
        fail("P0_PACKAGE_STALE", "Package review больше не совпадает с current authoritative state.");
      }
      state.human_decision_gate = await buildHumanDecisionGate(state.package_review, confirmedAt);
    } else if (action === "dispatch_package") {
      if (!state.package_review || !state.human_decision_gate || !state.recommendation_set || !state.context_state) {
        fail("P0_PACKAGE_AUTHORITY_MISSING", "Package dispatch требует current package review, exact Human Decision Gate, Recommendation Set и Context.");
      }
      if (payload.package_id !== state.human_decision_gate.package_id || payload.gate_id !== state.human_decision_gate.gate_id) {
        fail("P0_PACKAGE_IDENTITY_STALE", "Dispatch identity не совпадает с current exact Human Decision Gate.");
      }
      const preflightAt = this.adapters.now();
      const preflightContext = sanitizeContext(await this.adapters.readContext());
      this.assertContextPreflight(preflightContext, preflightAt);
      this.assertPersistedBindings(state, preflightContext);
      const configuration = this.adapters.externalWriteConfiguration();
      if (!configuration.ready) {
        fail("P0_WRITE_NOT_READY", configuration.blockers[0] ?? "Direct production credentials не настроены.");
      }
      if (configuration.account !== state.human_decision_gate.authority.direct_account_binding.account) {
        fail("P0_CONTEXT_ACCOUNT_MISMATCH", "Direct write account не совпадает с exact package Gate binding.");
      }
      let plans;
      try {
        plans = await exactPackageDispatchPlans({
          review: state.package_review,
          gate: state.human_decision_gate,
          recommendationSet: state.recommendation_set,
        });
      } catch (error) {
        fail("P0_PACKAGE_DISPATCH_BLOCKED", errorMessage(error));
      }
      const persistPackageCheckpoint = async (checkpointAt: string) => {
        const checkpoint: P0StoredRow = {
          revision: persistedRevision + 1,
          updated_at: checkpointAt,
          value_json: JSON.stringify(state),
        };
        if (!await this.store.compareAndSwap(key, persistedRevision, checkpoint)) {
          fail("P0_REVISION_CONFLICT", "P0 изменился в другой вкладке. Package checkpoint не сохранён.");
        }
        persistedRevision = checkpoint.revision;
      };
      if (!state.package_execution) {
        state.package_execution = await initializePackageExecution({
          review: state.package_review,
          gate: state.human_decision_gate,
          plans,
          startedAt: preflightAt,
        });
        await persistPackageCheckpoint(preflightAt);
      }
      for (const plan of plans) {
        const currentItem = state.package_execution.items.find((item) => item.item_execution_id === plan.item_execution_id);
        if (!currentItem || !["QUEUED", "DISPATCHING"].includes(currentItem.status)) continue;
        if (packageExecutionBlocksFollowingItems(state.package_execution)) break;
        const itemStartedAt = this.adapters.now();
        state.package_execution = await beginPackageItemDispatch(state.package_execution, plan.item_execution_id, itemStartedAt);
        await persistPackageCheckpoint(itemStartedAt);
        let outcome: PackageItemExternalOutcome;
        try {
          outcome = await this.adapters.createPackageItemOutcome({
            key,
            state,
            package_execution_id: state.package_execution.package_execution_id,
            item_execution_id: plan.item_execution_id,
            selection: plan.selection,
            projection: plan.projection,
            draft: plan.draft,
          });
        } catch (error) {
          const failure = error as Error & { code?: string; partial?: Record<string, unknown> };
          const partial = record(failure.partial);
          outcome = {
            execution_id: plan.item_execution_id,
            ...partial,
            status: partial.requires_reconciliation === true || partial.account_lock === "HELD_FOR_RECONCILIATION"
              ? "RECONCILIATION_REQUIRED"
              : partial.rejected === true ? "PROVIDER_REJECTED" : "SYSTEM_FAILED",
            error_code: failure.code ?? "P0_PACKAGE_ITEM_SYSTEM_FAILURE",
            error_message: failure.message || "Package item execution failed.",
          };
        }
        if (outcome.execution_id !== plan.item_execution_id) {
          outcome = {
            status: "RECONCILIATION_REQUIRED",
            execution_id: plan.item_execution_id,
            requires_reconciliation: true,
            account_lock: "HELD_FOR_RECONCILIATION",
            containment: "RECONCILIATION_REQUIRED",
            error_code: "P0_PACKAGE_ITEM_IDENTITY_MISMATCH",
            error_message: "External item outcome did not match the durable package execution identity.",
          };
        }
        const itemUpdatedAt = this.adapters.now();
        state.package_execution = await recordPackageItemOutcome(
          state.package_execution,
          plan.item_execution_id,
          outcome,
          itemUpdatedAt,
        );
        await persistPackageCheckpoint(itemUpdatedAt);
        if (packageExecutionBlocksFollowingItems(state.package_execution)) break;
      }
    } else if (action === "poll_package_moderation") {
      if (!state.package_review || !state.human_decision_gate || !state.recommendation_set || !state.package_execution) {
        fail("P0_PACKAGE_EXECUTION_MISSING", "Moderation poll требует current package execution и exact Human Decision Gate.");
      }
      if (payload.package_id !== state.package_execution.package_id) {
        fail("P0_PACKAGE_IDENTITY_STALE", "Moderation poll package identity не совпадает с current execution.");
      }
      const itemExecutionId = String(payload.item_execution_id ?? "");
      const currentItem = state.package_execution.items.find((item) => item.item_execution_id === itemExecutionId);
      if (!currentItem) fail("P0_PACKAGE_ITEM_MISSING", "Moderation poll item execution отсутствует в selected package.");
      const pollStartedAt = this.adapters.now();
      if (!packageItemModerationPollIsDue(currentItem, pollStartedAt)) {
        fail("P0_MODERATION_POLL_NOT_DUE", `Moderation poll доступен после ${currentItem.moderation.next_poll_at ?? "terminal outcome"}.`);
      }
      const configuration = this.adapters.externalWriteConfiguration();
      if (!configuration.ready) fail("P0_WRITE_NOT_READY", configuration.blockers[0] ?? "Direct production credentials не настроены.");
      if (configuration.account !== state.human_decision_gate.authority.direct_account_binding.account) {
        fail("P0_CONTEXT_ACCOUNT_MISMATCH", "Direct poll account не совпадает с exact package Gate binding.");
      }
      let plans;
      try {
        plans = await exactPackageDispatchPlans({
          review: state.package_review,
          gate: state.human_decision_gate,
          recommendationSet: state.recommendation_set,
        });
      } catch (error) {
        fail("P0_PACKAGE_DISPATCH_BLOCKED", errorMessage(error));
      }
      const plan = plans.find((item) => item.item_execution_id === itemExecutionId);
      if (!plan) fail("P0_PACKAGE_ITEM_MISSING", "Moderation poll item потерял exact Draft projection lineage.");
      const persistPollCheckpoint = async (checkpointAt: string) => {
        const checkpoint: P0StoredRow = {
          revision: persistedRevision + 1,
          updated_at: checkpointAt,
          value_json: JSON.stringify(state),
        };
        if (!await this.store.compareAndSwap(key, persistedRevision, checkpoint)) {
          fail("P0_REVISION_CONFLICT", "P0 изменился в другой вкладке. Moderation checkpoint не сохранён.");
        }
        persistedRevision = checkpoint.revision;
      };
      state.package_execution = await beginPackageItemModerationPoll(
        state.package_execution,
        itemExecutionId,
        pollStartedAt,
      );
      await persistPollCheckpoint(pollStartedAt);
      let outcome: PackageItemExternalOutcome;
      try {
        outcome = await this.adapters.pollPackageItemOutcome({
          key,
          state,
          package_execution_id: state.package_execution.package_execution_id,
          item_execution_id: itemExecutionId,
          selection: plan.selection,
          projection: plan.projection,
          draft: plan.draft,
          item: state.package_execution.items.find((item) => item.item_execution_id === itemExecutionId)!,
        });
      } catch (error) {
        const failure = error as Error & { code?: string; partial?: Record<string, unknown> };
        const partial = record(failure.partial);
        outcome = {
          ...partial,
          execution_id: itemExecutionId,
          status: partial.requires_reconciliation === true ? "OUTCOME_UNKNOWN" : "SYSTEM_FAILED",
          account_lock: "RELEASED",
          error_code: failure.code ?? "P0_MODERATION_POLL_FAILED",
          error_message: failure.message || "Moderation poll failed.",
        };
      }
      if (outcome.execution_id !== itemExecutionId) {
        outcome = {
          execution_id: itemExecutionId,
          status: "OUTCOME_UNKNOWN",
          account_lock: "RELEASED",
          error_code: "P0_PACKAGE_ITEM_IDENTITY_MISMATCH",
          error_message: "Moderation outcome did not match the durable package item identity.",
        };
      }
      const pollCompletedAt = this.adapters.now();
      state.package_execution = await recordPackageItemOutcome(
        state.package_execution,
        itemExecutionId,
        outcome,
        pollCompletedAt,
        { moderationPoll: true },
      );
      await persistPollCheckpoint(pollCompletedAt);
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
    const decisionOnly = action === "review_package" || action === "confirm_package" || action === "dispatch_package" || action === "poll_package_moderation";
    const context = decisionOnly
      ? persistedDecisionContext(state)
      : sanitizeContext(await this.adapters.readContext());
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
      shortlist_controls: shortlistControls(state),
      decision_readiness: decisionReadiness(state),
      revision_history: await this.history(key, next.revision),
      write_readiness: this.writeReadiness(state, context, responseAt),
    };
  }
}
