import { canonicalizeEvidence } from "./analytics-evidence.ts";
import { campaignDraftPublishBlockers, type CampaignRecommendationSet } from "./campaign-fanout.ts";

export const SHORTLIST_SCHEMA = "p0-shortlist-v2";
export const PACKAGE_REVIEW_SCHEMA = "p0-package-review-v1";
export const HUMAN_DECISION_GATE_SCHEMA = "p0-human-decision-gate-v1";
export const DECISION_INVALIDATION_SCHEMA = "p0-decision-invalidation-v1";
export const PACKAGE_CONFIRMATION_TOKEN = "CONFIRM_EXACT_SHORTLIST_PACKAGE";
export const INDEPENDENT_EXECUTION_DISCLOSURE = "Каждая выбранная кампания будет отправляться, сдерживаться, модерироваться и оцениваться независимо. Пакет не является одной атомарной внешней транзакцией.";

export type ShortlistSelection = {
  draft_id: string;
  draft_revision_id: string;
  publish_fingerprint: string;
  strategy_revision_id: string;
  capability_profile_id: string;
  capability_profile_version: string;
  recommendation_set_id: string;
};

export type RemovedShortlistSelection = ShortlistSelection & {
  removed_at: string;
  removed_index: number;
};

export type P0Shortlist = {
  schema_version: typeof SHORTLIST_SCHEMA;
  contract_version: "2.0.0";
  shortlist_revision_id: string;
  strategy_revision_id: string;
  recommendation_set_id: string;
  ordering: "INSERTION_ORDER_WITH_POSITIONAL_RESTORE";
  selections: ShortlistSelection[];
  removed_selections: RemovedShortlistSelection[];
  updated_at: string;
  content_hash: string;
};

export type DirectAccountBinding = {
  source_kind: "YANDEX_DIRECT_API_V501";
  account: string;
  client_id: string;
  verified: true;
};

export type PackageAuthority = {
  schema_version: "p0-package-authority-v1";
  ordered_selections: ShortlistSelection[];
  shortlist_revision_id: string;
  recommendation_set_id: string;
  strategy_revision_id: string;
  direct_account_binding: DirectAccountBinding;
  direct_capability_snapshot: Record<string, unknown>;
  capability_profile: Record<string, unknown>;
  analytics_evidence_snapshot_id: string;
  orchestration: {
    external_transactionality: "NOT_PROMISED";
    selected_campaigns_execute_independently: true;
    disclosure: typeof INDEPENDENT_EXECUTION_DISCLOSURE;
  };
};

export type PackageReview = {
  schema_version: typeof PACKAGE_REVIEW_SCHEMA;
  contract_version: "1.0.0";
  package_review_id: string;
  package_id: string;
  reviewed_at: string;
  authority: PackageAuthority;
};

export type HumanDecisionGate = {
  schema_version: typeof HUMAN_DECISION_GATE_SCHEMA;
  contract_version: "1.0.0";
  gate_id: string;
  package_review_id: string;
  package_id: string;
  confirmation_token: typeof PACKAGE_CONFIRMATION_TOKEN;
  confirmed_at: string;
  authority: PackageAuthority;
  independent_execution_acknowledged: true;
  external_transactionality_promised: false;
  external_writes_performed: false;
};

export type DecisionInvalidationReason =
  | "SHORTLIST_MEMBERSHIP_CHANGED"
  | "SHORTLIST_ORDER_CHANGED"
  | "DRAFT_MATERIAL_CHANGE"
  | "STRATEGY_MATERIAL_CHANGE"
  | "MODEL_MATERIAL_CHANGE"
  | "CONTEXT_MATERIAL_CHANGE"
  | "ACCOUNT_OR_CAPABILITY_LINEAGE_CHANGED"
  | "EVIDENCE_LINEAGE_CHANGED"
  | "PLAYBOOK_REGENERATION"
  | "PACKAGE_REVIEW_REPLACED"
  | "LEGACY_AUTHORITY_REQUIRES_REVIEW";

export type DecisionInvalidation = {
  schema_version: typeof DECISION_INVALIDATION_SCHEMA;
  invalidation_id: string;
  reason_code: DecisionInvalidationReason;
  reason: string;
  invalidated_at: string;
  previous_shortlist_revision_id: string | null;
  previous_package_review_id: string | null;
  previous_package_id: string | null;
  previous_gate_id: string | null;
};

type DraftRecord = CampaignRecommendationSet["drafts"][number];

async function sha256(value: unknown) {
  const bytes = new TextEncoder().encode(canonicalizeEvidence(value));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return `sha256:${[...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("")}`;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function exactSelection(draft: DraftRecord, recommendationSet: CampaignRecommendationSet): ShortlistSelection {
  return {
    draft_id: String(draft.draft_id ?? ""),
    draft_revision_id: String(draft.draft_revision_id ?? ""),
    publish_fingerprint: String(draft.publish_fingerprint ?? ""),
    strategy_revision_id: String(draft.strategy_revision_id ?? ""),
    capability_profile_id: String(draft.capability_profile_id ?? ""),
    capability_profile_version: String(draft.capability_profile_version ?? ""),
    recommendation_set_id: String(recommendationSet.recommendation_set_id ?? ""),
  };
}

export function shortlistSelectionBlockReason(draft: Record<string, unknown> | null | undefined) {
  if (!draft) return "Draft отсутствует в текущем Recommendation Set.";
  if (draft.visibility !== "VISIBLE") {
    return `Draft скрыт: ${String(draft.suppression_reason ?? "HIDDEN:STRUCTURAL")}.`;
  }
  const blockers = campaignDraftPublishBlockers(draft);
  if (blockers.length) return blockers[0];
  if (draft.publish_eligibility !== "ELIGIBLE") {
    return `Publish readiness: ${String(draft.publish_eligibility ?? "BLOCKED_HARD")}.`;
  }
  const score = record(draft.viability_score);
  const eligibility = record(score.eligibility);
  if (eligibility.status !== "ELIGIBLE") {
    const scoreBlockers = Array.isArray(eligibility.blockers) ? eligibility.blockers.map(String).filter(Boolean) : [];
    return scoreBlockers[0] ?? `Hard eligibility: ${String(eligibility.status ?? "BLOCKED_UNKNOWN")}.`;
  }
  const gaps = record(score.evidence_gaps);
  if (gaps.status !== "RESOLVED") {
    const required = Array.isArray(gaps.required) ? gaps.required.map(String).filter(Boolean) : [];
    return required[0] ?? "Required evidence gaps не разрешены.";
  }
  if (draft.shortlist_eligible !== true) return "Draft не прошёл authoritative shortlist eligibility.";
  return null;
}

export function selectionForDraft(draft: DraftRecord, recommendationSet: CampaignRecommendationSet) {
  const blocker = shortlistSelectionBlockReason(draft);
  if (blocker) throw new Error(blocker);
  const selection = exactSelection(draft, recommendationSet);
  if (Object.values(selection).some((value) => !value)) {
    throw new Error("Draft lineage неполна для shortlist selection.");
  }
  return selection;
}

async function sealShortlist(unsigned: Omit<P0Shortlist, "content_hash">): Promise<P0Shortlist> {
  return { ...unsigned, content_hash: await sha256(unsigned) };
}

export async function emptyShortlist(input: {
  shortlistRevisionId: string;
  strategyRevisionId: string;
  recommendationSetId: string;
  updatedAt: string;
}) {
  return sealShortlist({
    schema_version: SHORTLIST_SCHEMA,
    contract_version: "2.0.0",
    shortlist_revision_id: input.shortlistRevisionId,
    strategy_revision_id: input.strategyRevisionId,
    recommendation_set_id: input.recommendationSetId,
    ordering: "INSERTION_ORDER_WITH_POSITIONAL_RESTORE",
    selections: [],
    removed_selections: [],
    updated_at: input.updatedAt,
  });
}

export async function reviseShortlist(input: {
  previous: P0Shortlist;
  shortlistRevisionId: string;
  updatedAt: string;
  selections: ShortlistSelection[];
  removedSelections: RemovedShortlistSelection[];
  recommendationSetId?: string;
}) {
  return sealShortlist({
    schema_version: SHORTLIST_SCHEMA,
    contract_version: "2.0.0",
    shortlist_revision_id: input.shortlistRevisionId,
    strategy_revision_id: input.previous.strategy_revision_id,
    recommendation_set_id: input.recommendationSetId ?? input.previous.recommendation_set_id,
    ordering: "INSERTION_ORDER_WITH_POSITIONAL_RESTORE",
    selections: structuredClone(input.selections),
    removed_selections: structuredClone(input.removedSelections),
    updated_at: input.updatedAt,
  });
}

function equalSelection(left: ShortlistSelection, right: ShortlistSelection) {
  return JSON.stringify(left) === JSON.stringify(right);
}

export async function verifyShortlist(
  shortlist: P0Shortlist | unknown,
  recommendationSet: CampaignRecommendationSet,
  strategyRevisionId: string,
) {
  const candidate = record(shortlist) as P0Shortlist;
  if (candidate.schema_version !== SHORTLIST_SCHEMA
    || candidate.contract_version !== "2.0.0"
    || candidate.ordering !== "INSERTION_ORDER_WITH_POSITIONAL_RESTORE"
    || !candidate.shortlist_revision_id
    || candidate.strategy_revision_id !== strategyRevisionId
    || candidate.recommendation_set_id !== recommendationSet.recommendation_set_id
    || !Array.isArray(candidate.selections)
    || !Array.isArray(candidate.removed_selections)) return false;
  const unsigned = { ...candidate } as Record<string, unknown>;
  delete unsigned.content_hash;
  if (candidate.content_hash !== await sha256(unsigned)) return false;
  const selectedIds = candidate.selections.map((item) => item.draft_id);
  if (new Set(selectedIds).size !== selectedIds.length) return false;
  const removedIds = candidate.removed_selections.map((item) => item.draft_id);
  if (new Set(removedIds).size !== removedIds.length || removedIds.some((id) => selectedIds.includes(id))) return false;
  for (const item of [...candidate.selections, ...candidate.removed_selections]) {
    const draft = recommendationSet.drafts.find((entry) => entry.draft_id === item.draft_id);
    if (!draft || shortlistSelectionBlockReason(draft)) return false;
    const persistedIdentity: ShortlistSelection = {
      draft_id: item.draft_id,
      draft_revision_id: item.draft_revision_id,
      publish_fingerprint: item.publish_fingerprint,
      strategy_revision_id: item.strategy_revision_id,
      capability_profile_id: item.capability_profile_id,
      capability_profile_version: item.capability_profile_version,
      recommendation_set_id: item.recommendation_set_id,
    };
    if (!equalSelection(exactSelection(draft, recommendationSet), persistedIdentity)) return false;
  }
  return candidate.removed_selections.every((item) => Number.isSafeInteger(item.removed_index) && item.removed_index >= 0 && Boolean(item.removed_at));
}

export async function rebaseShortlist(input: {
  previous: P0Shortlist;
  recommendationSet: CampaignRecommendationSet;
  shortlistRevisionId: string;
  updatedAt: string;
}) {
  const selections = input.previous.selections.map((selected) => {
    const draft = input.recommendationSet.drafts.find((item) => item.draft_id === selected.draft_id);
    if (!draft || shortlistSelectionBlockReason(draft)) return null;
    return exactSelection(draft, input.recommendationSet);
  }).filter((item): item is ShortlistSelection => Boolean(item));
  const removedSelections = input.previous.removed_selections.flatMap((removed) => {
    const draft = input.recommendationSet.drafts.find((item) => item.draft_id === removed.draft_id);
    if (!draft || shortlistSelectionBlockReason(draft)) return [];
    return [{ ...exactSelection(draft, input.recommendationSet), removed_at: removed.removed_at, removed_index: removed.removed_index }];
  }).filter((removed) => !selections.some((selected) => selected.draft_id === removed.draft_id));
  return reviseShortlist({
    previous: { ...input.previous, recommendation_set_id: input.recommendationSet.recommendation_set_id },
    shortlistRevisionId: input.shortlistRevisionId,
    updatedAt: input.updatedAt,
    selections,
    removedSelections,
    recommendationSetId: input.recommendationSet.recommendation_set_id,
  });
}

export async function buildPackageReview(input: {
  shortlist: P0Shortlist;
  recommendationSet: CampaignRecommendationSet;
  strategyRevisionId: string;
  accountBinding: DirectAccountBinding;
  capabilitySnapshot: Record<string, unknown>;
  analyticsEvidenceSnapshotId: string;
  reviewedAt: string;
}) {
  if (!input.shortlist.selections.length) throw new Error("Empty shortlist cannot be reviewed.");
  if (!await verifyShortlist(input.shortlist, input.recommendationSet, input.strategyRevisionId)) {
    throw new Error("Shortlist lineage is stale or invalid.");
  }
  const authority: PackageAuthority = {
    schema_version: "p0-package-authority-v1",
    ordered_selections: structuredClone(input.shortlist.selections),
    shortlist_revision_id: input.shortlist.shortlist_revision_id,
    recommendation_set_id: input.recommendationSet.recommendation_set_id,
    strategy_revision_id: input.strategyRevisionId,
    direct_account_binding: structuredClone(input.accountBinding),
    direct_capability_snapshot: structuredClone(input.capabilitySnapshot),
    capability_profile: structuredClone(input.recommendationSet.capability_profile),
    analytics_evidence_snapshot_id: input.analyticsEvidenceSnapshotId,
    orchestration: {
      external_transactionality: "NOT_PROMISED",
      selected_campaigns_execute_independently: true,
      disclosure: INDEPENDENT_EXECUTION_DISCLOSURE,
    },
  };
  const packageId = await sha256(authority);
  const reviewIdentity = { package_id: packageId, reviewed_at: input.reviewedAt, authority };
  return {
    schema_version: PACKAGE_REVIEW_SCHEMA,
    contract_version: "1.0.0",
    package_review_id: await sha256(reviewIdentity),
    package_id: packageId,
    reviewed_at: input.reviewedAt,
    authority,
  } satisfies PackageReview;
}

export async function verifyPackageReview(input: {
  review: PackageReview | unknown;
  shortlist: P0Shortlist;
  recommendationSet: CampaignRecommendationSet;
  strategyRevisionId: string;
  accountBinding: DirectAccountBinding;
  capabilitySnapshot: Record<string, unknown>;
  analyticsEvidenceSnapshotId: string;
}) {
  const candidate = record(input.review) as PackageReview;
  if (candidate.schema_version !== PACKAGE_REVIEW_SCHEMA || candidate.contract_version !== "1.0.0" || !candidate.reviewed_at) return false;
  let rebuilt: PackageReview;
  try {
    rebuilt = await buildPackageReview({
      shortlist: input.shortlist,
      recommendationSet: input.recommendationSet,
      strategyRevisionId: input.strategyRevisionId,
      accountBinding: input.accountBinding,
      capabilitySnapshot: input.capabilitySnapshot,
      analyticsEvidenceSnapshotId: input.analyticsEvidenceSnapshotId,
      reviewedAt: candidate.reviewed_at,
    });
  } catch {
    return false;
  }
  return JSON.stringify(rebuilt) === JSON.stringify(candidate);
}

export async function buildHumanDecisionGate(review: PackageReview, confirmedAt: string) {
  const unsigned = {
    schema_version: HUMAN_DECISION_GATE_SCHEMA as typeof HUMAN_DECISION_GATE_SCHEMA,
    contract_version: "1.0.0" as const,
    package_review_id: review.package_review_id,
    package_id: review.package_id,
    confirmation_token: PACKAGE_CONFIRMATION_TOKEN as typeof PACKAGE_CONFIRMATION_TOKEN,
    confirmed_at: confirmedAt,
    authority: structuredClone(review.authority),
    independent_execution_acknowledged: true as const,
    external_transactionality_promised: false as const,
    external_writes_performed: false as const,
  };
  return { ...unsigned, gate_id: await sha256(unsigned) } satisfies HumanDecisionGate;
}

export async function verifyHumanDecisionGate(gate: HumanDecisionGate | unknown, review: PackageReview) {
  const candidate = record(gate) as HumanDecisionGate;
  if (candidate.schema_version !== HUMAN_DECISION_GATE_SCHEMA
    || candidate.contract_version !== "1.0.0"
    || candidate.confirmation_token !== PACKAGE_CONFIRMATION_TOKEN
    || candidate.package_review_id !== review.package_review_id
    || candidate.package_id !== review.package_id
    || candidate.independent_execution_acknowledged !== true
    || candidate.external_transactionality_promised !== false
    || candidate.external_writes_performed !== false
    || JSON.stringify(candidate.authority) !== JSON.stringify(review.authority)
    || !candidate.confirmed_at) return false;
  const rebuilt = await buildHumanDecisionGate(review, candidate.confirmed_at);
  return JSON.stringify(rebuilt) === JSON.stringify(candidate);
}

export async function buildDecisionInvalidation(input: Omit<DecisionInvalidation, "schema_version" | "invalidation_id">) {
  const unsigned = { schema_version: DECISION_INVALIDATION_SCHEMA as typeof DECISION_INVALIDATION_SCHEMA, ...input };
  return { ...unsigned, invalidation_id: await sha256(unsigned) } satisfies DecisionInvalidation;
}

export async function verifyDecisionInvalidation(value: DecisionInvalidation | unknown) {
  const candidate = record(value) as DecisionInvalidation;
  if (candidate.schema_version !== DECISION_INVALIDATION_SCHEMA || !candidate.invalidation_id || !candidate.invalidated_at || !candidate.reason) return false;
  const unsigned = { ...candidate } as Record<string, unknown>;
  delete unsigned.invalidation_id;
  return candidate.invalidation_id === await sha256(unsigned);
}
