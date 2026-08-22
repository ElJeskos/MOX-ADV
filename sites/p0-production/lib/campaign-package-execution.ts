import { canonicalizeEvidence } from "./analytics-evidence.ts";
import {
  campaignDraftPublishBlockers,
  fingerprintDirectProjection,
  type CampaignRecommendationSet,
} from "./campaign-fanout.ts";
import type {
  HumanDecisionGate,
  PackageReview,
  ShortlistSelection,
} from "./campaign-decision-gate.ts";
import type { DirectProjection } from "./direct-write.ts";

export const PACKAGE_EXECUTION_SCHEMA = "p0-package-execution-v2";
export const PACKAGE_ITEM_EXECUTION_SCHEMA = "p0-package-item-execution-v2";
const PACKAGE_ITEM_EXECUTION_IDENTITY_SCHEMA = "p0-package-item-execution-v1";
export const PACKAGE_MODERATION_POLL_INTERVAL_MS = 60_000;

export type PackageItemOwnership =
  | "UNCLASSIFIED"
  | "PENDING_PROVIDER_OUTCOME"
  | "PROVIDER"
  | "SYSTEM"
  | "UNKNOWN";

export type PackageItemStatus =
  | "QUEUED"
  | "DISPATCHING"
  | "MODERATION_PENDING"
  | "OUTCOME_UNKNOWN"
  | "DIRECT_ACCEPTED"
  | "REJECTED_NEEDS_EDIT"
  | "PROVIDER_REJECTED"
  | "SYSTEM_FAILED"
  | "RECONCILIATION_REQUIRED";

export type PackageItemContainment =
  | "PENDING"
  | "NOT_CREATED"
  | "CONFIRMED_SUSPENDED"
  | "NON_SERVING_CONFIRMED"
  | "RECONCILIATION_REQUIRED"
  | "MANUAL_RECONCILIATION_REQUIRED"
  | "UNKNOWN";

export type PackageItemAccountLock =
  | "NOT_ACQUIRED"
  | "ACQUIRING"
  | "RELEASED"
  | "HELD_FOR_RECONCILIATION";

export type PackageItemProgress = {
  validation: "PENDING" | "PASSED" | "FAILED";
  creation: "PENDING" | "NOT_ATTEMPTED" | "CREATED" | "REJECTED" | "FAILED" | "UNKNOWN";
  suspension: "PENDING" | "CONFIRMED_SUSPENDED" | "NOT_APPLICABLE" | "FAILED" | "UNKNOWN";
  child_graph: "PENDING" | "CREATED" | "NOT_APPLICABLE" | "PARTIAL" | "FAILED" | "UNKNOWN";
  readback: "PENDING" | "VERIFIED" | "NOT_APPLICABLE" | "FAILED" | "UNKNOWN";
  moderation: "PENDING" | "ACCEPTED" | "REJECTED" | "NOT_APPLICABLE" | "UNKNOWN";
};

export type PackageAdModerationOutcome = {
  ad_id: string;
  ad_group_id: string;
  status: "MODERATION" | "PREACCEPTED" | "ACCEPTED" | "REJECTED" | "UNKNOWN";
  terminal: boolean;
  accepted: boolean;
  status_clarification: string | null;
  provider_issues: Array<Record<string, unknown>>;
  observed_at: string;
};

export type PackageItemModeration = {
  provider_status: "NOT_SUBMITTED" | "MODERATION" | "PREACCEPTED" | "ACCEPTED" | "REJECTED" | "MIXED" | "UNKNOWN";
  poll_attempts: number;
  last_poll_started_at: string | null;
  last_polled_at: string | null;
  next_poll_at: string | null;
  ad_outcomes: PackageAdModerationOutcome[];
  observations: Array<{
    observed_at: string;
    provider_status: PackageItemModeration["provider_status"];
    ad_outcomes: PackageAdModerationOutcome[];
  }>;
};

export type PackageItemAccountability = {
  supported_graph_verified: boolean;
  campaign_suspended: boolean;
  published_ad_group_ids: string[];
  published_ad_ids: string[];
  accepted_ad_group_ids: string[];
  all_ads_terminal: boolean;
  all_additional_ads_visible: boolean;
  direct_accepted: boolean;
  provider_outcome_accounted: boolean;
};

export type PackageItemExecution = {
  schema_version: typeof PACKAGE_ITEM_EXECUTION_SCHEMA;
  item_execution_id: string;
  position: number;
  selection: ShortlistSelection;
  status: PackageItemStatus;
  ownership: PackageItemOwnership;
  progress: PackageItemProgress;
  provider_ids: {
    campaign_id: string | null;
    ad_group_id: string | null;
    keyword_id: string | null;
    ad_group_ids: string[];
    keyword_ids: string[];
    ad_ids: string[];
  };
  provider_issues: Array<Record<string, unknown>>;
  readback: Record<string, unknown> | null;
  campaign_state: string | null;
  moderation: PackageItemModeration;
  accountability: PackageItemAccountability;
  containment: PackageItemContainment;
  failure: { code: string; message: string } | null;
  account_lock: PackageItemAccountLock;
  started_at: string | null;
  updated_at: string;
};

export type PackageVerdict = "PENDING" | "PASS" | "PASS_WITH_PLATFORM_REJECTIONS" | "FAIL";

export type PackageExecution = {
  schema_version: typeof PACKAGE_EXECUTION_SCHEMA;
  contract_version: "2.0.0";
  package_execution_id: string;
  package_id: string;
  package_review_id: string;
  gate_id: string;
  status: "DISPATCHING" | PackageVerdict;
  verdict: PackageVerdict;
  atomic_transaction: false;
  selected_count: number;
  dispatched_count: number;
  items: PackageItemExecution[];
  started_at: string;
  updated_at: string;
  content_hash: string;
};

export type PackageDispatchPlan = {
  item_execution_id: string;
  selection: ShortlistSelection;
  projection: DirectProjection;
  draft: CampaignRecommendationSet["drafts"][number];
};

export type PackageItemExternalOutcome = Record<string, unknown> & {
  execution_id?: string;
  status?: string;
};

export type DirectExecutionFailure = Error & {
  code?: string;
  partial?: Record<string, unknown>;
};

type ProviderIds = PackageItemExecution["provider_ids"];

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function uniqueStrings(values: unknown[]) {
  return [...new Set(values.map(String).filter((value) => /^\d+$/u.test(value)))];
}

function nextPollAt(value: string) {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) throw new Error("Moderation poll timestamp is invalid.");
  return new Date(timestamp + PACKAGE_MODERATION_POLL_INTERVAL_MS).toISOString();
}

export function directExecutionFailureOutcome(
  itemExecutionId: string,
  error: DirectExecutionFailure,
): PackageItemExternalOutcome {
  const partial = record(error.partial);
  const previousResult = record(partial.previous_result);
  const recovered = Object.keys(previousResult).length ? previousResult : partial;
  const previousStatus = String(partial.previous_status ?? "");
  const preDispatchValidationFailure = new Set([
    "P0_EXECUTION_ID_INVALID",
    "P0_WRITE_CREDENTIAL_MISSING",
    "P0_PUBLICATION_BLOCKED",
    "P0_PROJECTION_INCOMPLETE",
    "P0_PROJECTION_UNSAFE",
    "P0_CAPABILITY_OR_ACCOUNT_MISMATCH",
    "P0_PROJECTION_FINGERPRINT_MISMATCH",
  ]).has(String(error.code ?? ""));
  const status = previousStatus === "PROVIDER_REJECTED" || recovered.rejected === true
    ? "PROVIDER_REJECTED"
    : previousStatus === "SYSTEM_FAILED"
      ? "SYSTEM_FAILED"
      : recovered.requires_reconciliation === true || recovered.account_lock === "HELD_FOR_RECONCILIATION"
        ? "RECONCILIATION_REQUIRED"
        : "SYSTEM_FAILED";
  return {
    ...recovered,
    ...(preDispatchValidationFailure ? {
      validation_failed: true,
      dispatch_not_attempted: true,
      containment: "NOT_CREATED",
    } : {}),
    execution_id: itemExecutionId,
    status,
    error_code: String(recovered.error_code ?? error.code ?? "P0_PACKAGE_ITEM_SYSTEM_FAILURE"),
    error_message: String(recovered.error_message ?? error.message ?? "Package item execution failed."),
    account_lock: String(recovered.account_lock ?? (status === "RECONCILIATION_REQUIRED" ? "HELD_FOR_RECONCILIATION" : "RELEASED")),
  };
}

async function sha256(value: unknown) {
  const bytes = new TextEncoder().encode(canonicalizeEvidence(value));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return `sha256:${[...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("")}`;
}

async function itemExecutionId(
  packageId: string,
  gateId: string,
  position: number,
  selection: ShortlistSelection,
) {
  return sha256({
    schema_version: PACKAGE_ITEM_EXECUTION_IDENTITY_SCHEMA,
    package_id: packageId,
    gate_id: gateId,
    position,
    selection,
  });
}

function selectionMatchesDraft(
  selection: ShortlistSelection,
  draft: CampaignRecommendationSet["drafts"][number],
  recommendationSet: CampaignRecommendationSet,
) {
  return selection.draft_id === draft.draft_id
    && selection.draft_revision_id === draft.draft_revision_id
    && selection.publish_fingerprint === draft.publish_fingerprint
    && selection.strategy_revision_id === draft.strategy_revision_id
    && selection.capability_profile_id === draft.capability_profile_id
    && selection.capability_profile_version === draft.capability_profile_version
    && selection.recommendation_set_id === recommendationSet.recommendation_set_id;
}

export async function exactPackageDispatchPlans(input: {
  review: PackageReview;
  gate: HumanDecisionGate;
  recommendationSet: CampaignRecommendationSet;
}) {
  if (input.gate.package_id !== input.review.package_id
    || input.gate.package_review_id !== input.review.package_review_id
    || input.gate.authority.strategy_revision_id !== input.recommendationSet.strategy_revision_id
    || input.gate.authority.recommendation_set_id !== input.recommendationSet.recommendation_set_id
    || JSON.stringify(input.gate.authority) !== JSON.stringify(input.review.authority)
    || JSON.stringify(input.gate.authority.capability_profile) !== JSON.stringify(input.recommendationSet.capability_profile)) {
    throw new Error("Exact package Gate, Strategy, Recommendation Set или capability profile не совпадают.");
  }
  if (!input.gate.authority.ordered_selections.length) {
    throw new Error("Exact package Gate не содержит selected Drafts.");
  }
  const plans: PackageDispatchPlan[] = [];
  for (const [position, selection] of input.gate.authority.ordered_selections.entries()) {
    const draft = input.recommendationSet.drafts.find((item) => item.draft_id === selection.draft_id);
    if (!draft || !selectionMatchesDraft(selection, draft, input.recommendationSet)) {
      throw new Error(`Selected Draft ${selection.draft_id} revision или fingerprint не совпадает с exact Gate.`);
    }
    const blockers = campaignDraftPublishBlockers(draft);
    if (blockers.length) throw new Error(`Selected Draft ${selection.draft_id} blocked: ${blockers[0]}`);
    const projection = draft.publish_projection as DirectProjection;
    if (!projection || await fingerprintDirectProjection(projection as unknown as Record<string, unknown>) !== selection.publish_fingerprint) {
      throw new Error(`Selected Draft ${selection.draft_id} projection fingerprint не совпадает с exact Gate.`);
    }
    const lineage = record(projection.lineage);
    if (lineage.strategy_revision_id !== selection.strategy_revision_id
      || lineage.draft_id !== selection.draft_id
      || lineage.draft_revision_id !== selection.draft_revision_id
      || lineage.capability_profile_id !== selection.capability_profile_id
      || lineage.capability_profile_version !== selection.capability_profile_version) {
      throw new Error(`Selected Draft ${selection.draft_id} projection lineage не совпадает с exact Gate.`);
    }
    plans.push({
      item_execution_id: await itemExecutionId(input.gate.package_id, input.gate.gate_id, position, selection),
      selection: structuredClone(selection),
      projection: structuredClone(projection),
      draft,
    });
  }
  return plans;
}

function emptyProgress(): PackageItemProgress {
  return {
    validation: "PENDING",
    creation: "PENDING",
    suspension: "PENDING",
    child_graph: "PENDING",
    readback: "PENDING",
    moderation: "PENDING",
  };
}

function emptyModeration(): PackageItemModeration {
  return {
    provider_status: "NOT_SUBMITTED",
    poll_attempts: 0,
    last_poll_started_at: null,
    last_polled_at: null,
    next_poll_at: null,
    ad_outcomes: [],
    observations: [],
  };
}

function emptyAccountability(): PackageItemAccountability {
  return {
    supported_graph_verified: false,
    campaign_suspended: false,
    published_ad_group_ids: [],
    published_ad_ids: [],
    accepted_ad_group_ids: [],
    all_ads_terminal: false,
    all_additional_ads_visible: false,
    direct_accepted: false,
    provider_outcome_accounted: false,
  };
}

async function sealExecution(unsigned: Omit<PackageExecution, "content_hash">): Promise<PackageExecution> {
  return { ...unsigned, content_hash: await sha256(unsigned) };
}

export async function initializePackageExecution(input: {
  review: PackageReview;
  gate: HumanDecisionGate;
  plans: PackageDispatchPlan[];
  startedAt: string;
}) {
  const packageExecutionId = await sha256({
    schema_version: PACKAGE_EXECUTION_SCHEMA,
    package_id: input.gate.package_id,
    package_review_id: input.gate.package_review_id,
    gate_id: input.gate.gate_id,
  });
  return sealExecution({
    schema_version: PACKAGE_EXECUTION_SCHEMA,
    contract_version: "2.0.0",
    package_execution_id: packageExecutionId,
    package_id: input.gate.package_id,
    package_review_id: input.gate.package_review_id,
    gate_id: input.gate.gate_id,
    status: "DISPATCHING",
    verdict: "PENDING",
    atomic_transaction: false,
    selected_count: input.plans.length,
    dispatched_count: 0,
    items: input.plans.map((plan, position) => ({
      schema_version: PACKAGE_ITEM_EXECUTION_SCHEMA,
      item_execution_id: plan.item_execution_id,
      position,
      selection: structuredClone(plan.selection),
      status: "QUEUED",
      ownership: "UNCLASSIFIED",
      progress: emptyProgress(),
      provider_ids: {
        campaign_id: null,
        ad_group_id: null,
        keyword_id: null,
        ad_group_ids: [],
        keyword_ids: [],
        ad_ids: [],
      },
      provider_issues: [],
      readback: null,
      campaign_state: null,
      moderation: emptyModeration(),
      accountability: emptyAccountability(),
      containment: "PENDING",
      failure: null,
      account_lock: "NOT_ACQUIRED",
      started_at: null,
      updated_at: input.startedAt,
    })),
    started_at: input.startedAt,
    updated_at: input.startedAt,
  });
}

function packageVerdict(items: PackageItemExecution[]): PackageVerdict {
  if (items.some((item) => item.ownership === "SYSTEM" || item.status === "SYSTEM_FAILED")) return "FAIL";
  if (items.some((item) => [
    "QUEUED", "DISPATCHING", "MODERATION_PENDING", "OUTCOME_UNKNOWN", "RECONCILIATION_REQUIRED",
  ].includes(item.status))) return "PENDING";
  const accepted = items.filter((item) => item.accountability.direct_accepted);
  if (!accepted.length) return "FAIL";
  if (accepted.length === items.length) return "PASS";
  if (items.every((item) => item.accountability.direct_accepted || item.accountability.provider_outcome_accounted)) {
    return "PASS_WITH_PLATFORM_REJECTIONS";
  }
  return "FAIL";
}

function packageStatus(items: PackageItemExecution[], verdict: PackageVerdict): PackageExecution["status"] {
  if (verdict !== "PENDING") return verdict;
  const dispatching = items.some((item) => item.status === "QUEUED" || item.status === "DISPATCHING");
  const moderationOrUnknown = items.some((item) => [
    "MODERATION_PENDING", "OUTCOME_UNKNOWN", "RECONCILIATION_REQUIRED",
  ].includes(item.status));
  return dispatching && !moderationOrUnknown ? "DISPATCHING" : "PENDING";
}

async function replaceItem(
  execution: PackageExecution,
  itemExecutionId: string,
  update: (item: PackageItemExecution) => PackageItemExecution,
  updatedAt: string,
) {
  const index = execution.items.findIndex((item) => item.item_execution_id === itemExecutionId);
  if (index < 0) throw new Error("Package item execution отсутствует.");
  const items = execution.items.map((item, itemIndex) => itemIndex === index ? update(structuredClone(item)) : structuredClone(item));
  const verdict = packageVerdict(items);
  const unsignedExecution = Object.fromEntries(
    Object.entries(execution).filter(([key]) => key !== "content_hash"),
  ) as Omit<PackageExecution, "content_hash">;
  return sealExecution({
    ...unsignedExecution,
    items,
    status: packageStatus(items, verdict),
    verdict,
    dispatched_count: items.filter((item) => !["QUEUED", "DISPATCHING"].includes(item.status)).length,
    updated_at: updatedAt,
  });
}

export async function beginPackageItemDispatch(
  execution: PackageExecution,
  itemExecutionId: string,
  startedAt: string,
) {
  return replaceItem(execution, itemExecutionId, (item) => ({
    ...item,
    status: "DISPATCHING",
    progress: { ...item.progress, validation: "PENDING" },
    account_lock: "ACQUIRING",
    started_at: item.started_at ?? startedAt,
    updated_at: startedAt,
  }), startedAt);
}

function providerIds(outcome: PackageItemExternalOutcome, previous: ProviderIds): ProviderIds {
  const directIds = record(outcome.provider_ids);
  const adIds = Array.isArray(directIds.ad_ids)
    ? uniqueStrings(directIds.ad_ids)
    : outcome.ad_id ? [String(outcome.ad_id)] : previous.ad_ids;
  const adGroupIds = Array.isArray(directIds.ad_group_ids)
    ? uniqueStrings(directIds.ad_group_ids)
    : outcome.ad_group_id ? [String(outcome.ad_group_id)]
      : directIds.ad_group_id ? [String(directIds.ad_group_id)]
        : previous.ad_group_ids;
  const keywordIds = Array.isArray(directIds.keyword_ids)
    ? uniqueStrings(directIds.keyword_ids)
    : outcome.keyword_id ? [String(outcome.keyword_id)]
      : directIds.keyword_id ? [String(directIds.keyword_id)]
        : previous.keyword_ids;
  return {
    campaign_id: outcome.campaign_id ? String(outcome.campaign_id)
      : directIds.campaign_id ? String(directIds.campaign_id)
        : previous.campaign_id,
    ad_group_id: adGroupIds[0] ?? previous.ad_group_id,
    keyword_id: keywordIds[0] ?? previous.keyword_id,
    ad_group_ids: adGroupIds,
    keyword_ids: keywordIds,
    ad_ids: adIds,
  };
}

function moderationStatus(value: unknown): PackageAdModerationOutcome["status"] {
  const status = String(value ?? "UNKNOWN");
  return ["MODERATION", "PREACCEPTED", "ACCEPTED", "REJECTED"].includes(status)
    ? status as PackageAdModerationOutcome["status"]
    : "UNKNOWN";
}

function outcomeAdRows(
  outcome: PackageItemExternalOutcome,
  ids: ProviderIds,
  updatedAt: string,
): PackageAdModerationOutcome[] {
  const source = Array.isArray(outcome.ad_outcomes)
    ? outcome.ad_outcomes
    : outcome.moderation_status && ids.ad_ids.length === 1
      ? [{
          ad_id: ids.ad_ids[0],
          ad_group_id: ids.ad_group_ids[0] ?? ids.ad_group_id ?? "",
          status: outcome.moderation_status,
          status_clarification: outcome.status_clarification ?? null,
          provider_issues: [],
        }]
      : [];
  return source.flatMap((value) => {
    const row = record(value);
    const adId = String(row.ad_id ?? "");
    const adGroupId = String(row.ad_group_id ?? "");
    if (!/^\d+$/u.test(adId) || !/^\d+$/u.test(adGroupId)) return [];
    const status = moderationStatus(row.status);
    return [{
      ad_id: adId,
      ad_group_id: adGroupId,
      status,
      terminal: status === "ACCEPTED" || status === "REJECTED",
      accepted: status === "ACCEPTED",
      status_clarification: row.status_clarification === null || row.status_clarification === undefined
        ? null
        : String(row.status_clarification),
      provider_issues: Array.isArray(row.provider_issues)
        ? row.provider_issues.map((issue) => structuredClone(record(issue)))
        : [],
      observed_at: updatedAt,
    }];
  });
}

function mergeAdOutcomes(
  previous: PackageAdModerationOutcome[],
  current: PackageAdModerationOutcome[],
) {
  const byId = new Map(previous.map((item) => [item.ad_id, structuredClone(item)]));
  for (const item of current) byId.set(item.ad_id, structuredClone(item));
  return [...byId.values()];
}

function aggregateModerationStatus(outcomes: PackageAdModerationOutcome[]): PackageItemModeration["provider_status"] {
  if (!outcomes.length) return "NOT_SUBMITTED";
  const statuses = [...new Set(outcomes.map((item) => item.status))];
  return statuses.length === 1 ? statuses[0] : "MIXED";
}

function graphRows(readback: Record<string, unknown> | null, plural: string, singular: string) {
  if (!readback) return [];
  if (Array.isArray(readback[plural])) return (readback[plural] as unknown[]).map(record);
  const value = record(readback[singular]);
  return Object.keys(value).length ? [value] : [];
}

function exactIdSet(actual: string[], expected: string[]) {
  const sortIds = (values: string[]) => [...values].sort((left, right) => left.localeCompare(right, "en", { numeric: true }));
  return JSON.stringify(sortIds(actual)) === JSON.stringify(sortIds(expected));
}

function accountabilityEvidence(input: {
  ids: ProviderIds;
  readback: Record<string, unknown> | null;
  campaignState: string | null;
  adOutcomes: PackageAdModerationOutcome[];
}) {
  const campaign = record(input.readback?.campaign);
  const groups = graphRows(input.readback, "ad_groups", "ad_group");
  const keywords = graphRows(input.readback, "keywords", "keyword");
  const ads = graphRows(input.readback, "ads", "ad");
  const groupIds = uniqueStrings(groups.map((item) => item.Id));
  const keywordIds = uniqueStrings(keywords.map((item) => item.Id));
  const adIds = uniqueStrings(ads.map((item) => item.Id));
  const campaignMatches = Boolean(input.ids.campaign_id)
    && String(campaign.Id ?? "") === input.ids.campaign_id;
  const groupRelationsMatch = groups.every((item) => String(item.CampaignId ?? "") === input.ids.campaign_id);
  const keywordRelationsMatch = keywords.every((item) => input.ids.ad_group_ids.includes(String(item.AdGroupId ?? "")));
  const adRelationsMatch = ads.every((item) => String(item.CampaignId ?? "") === input.ids.campaign_id
    && input.ids.ad_group_ids.includes(String(item.AdGroupId ?? "")));
  const supportedGraphVerified = campaignMatches
    && input.ids.ad_group_ids.length > 0
    && input.ids.keyword_ids.length > 0
    && input.ids.ad_ids.length > 0
    && exactIdSet(groupIds, input.ids.ad_group_ids)
    && exactIdSet(keywordIds, input.ids.keyword_ids)
    && exactIdSet(adIds, input.ids.ad_ids)
    && groupRelationsMatch
    && keywordRelationsMatch
    && adRelationsMatch;
  const outcomeIds = input.adOutcomes.map((item) => item.ad_id);
  const allAdditionalAdsVisible = input.ids.ad_ids.length > 0
    && input.adOutcomes.length === input.ids.ad_ids.length
    && exactIdSet(outcomeIds, input.ids.ad_ids);
  const allAdsTerminal = allAdditionalAdsVisible && input.adOutcomes.every((item) => item.terminal);
  const acceptedGroupIds = input.ids.ad_group_ids.filter((groupId) => input.adOutcomes.some((item) => item.ad_group_id === groupId && item.accepted));
  const campaignSuspended = input.campaignState === "SUSPENDED" && campaign.State === "SUSPENDED";
  const directAccepted = supportedGraphVerified
    && campaignSuspended
    && allAdsTerminal
    && acceptedGroupIds.length === input.ids.ad_group_ids.length;
  return {
    supported_graph_verified: supportedGraphVerified,
    campaign_suspended: campaignSuspended,
    published_ad_group_ids: structuredClone(input.ids.ad_group_ids),
    published_ad_ids: structuredClone(input.ids.ad_ids),
    accepted_ad_group_ids: acceptedGroupIds,
    all_ads_terminal: allAdsTerminal,
    all_additional_ads_visible: allAdditionalAdsVisible,
    direct_accepted: directAccepted,
  };
}

function mergeIssues(
  previous: Array<Record<string, unknown>>,
  outcome: PackageItemExternalOutcome,
  ads: PackageAdModerationOutcome[],
) {
  const incoming = [
    ...(Array.isArray(outcome.provider_issues) ? outcome.provider_issues.map(record) : []),
    ...ads.flatMap((ad) => ad.provider_issues),
  ];
  const seen = new Set<string>();
  return [...previous, ...incoming].filter((issue) => {
    const key = canonicalizeEvidence(issue);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).map((issue) => structuredClone(issue));
}

function explicitProviderOutcome(status: PackageItemStatus, issues: Array<Record<string, unknown>>, adOutcomes: PackageAdModerationOutcome[]) {
  return ["PROVIDER_REJECTED", "REJECTED_NEEDS_EDIT"].includes(status)
    && (issues.length > 0 || (adOutcomes.length > 0 && adOutcomes.every((item) => item.terminal)));
}

function normalizedOutcomeStatus(input: {
  outcome: PackageItemExternalOutcome;
  evidence: ReturnType<typeof accountabilityEvidence>;
  adOutcomes: PackageAdModerationOutcome[];
  campaignState: string | null;
  ids: ProviderIds;
}): PackageItemStatus {
  const requested = String(input.outcome.status ?? "");
  const accountLock = String(input.outcome.account_lock ?? "RELEASED");
  if (input.outcome.requires_reconciliation === true
    || accountLock === "HELD_FOR_RECONCILIATION"
    || ["RECONCILIATION_REQUIRED", "MANUAL_RECONCILIATION_REQUIRED"].includes(String(input.outcome.containment ?? ""))) {
    return "RECONCILIATION_REQUIRED";
  }
  if (requested === "OUTCOME_UNKNOWN") return "OUTCOME_UNKNOWN";
  if (requested === "SYSTEM_FAILED") return "SYSTEM_FAILED";
  if (input.evidence.direct_accepted) return "DIRECT_ACCEPTED";
  if (input.adOutcomes.length > 0) {
    if (input.adOutcomes.some((item) => item.status === "UNKNOWN")) return "OUTCOME_UNKNOWN";
    if (input.adOutcomes.some((item) => item.status === "MODERATION" || item.status === "PREACCEPTED")) return "MODERATION_PENDING";
    if (!input.evidence.supported_graph_verified || !input.evidence.campaign_suspended) return "SYSTEM_FAILED";
    return "REJECTED_NEEDS_EDIT";
  }
  if (input.ids.campaign_id && input.campaignState !== "SUSPENDED") return "SYSTEM_FAILED";
  if (input.outcome.rejected === true || requested === "PROVIDER_REJECTED" || requested === "REJECTED_NEEDS_EDIT") {
    return requested === "REJECTED_NEEDS_EDIT" ? "REJECTED_NEEDS_EDIT" : "PROVIDER_REJECTED";
  }
  const moderation = String(input.outcome.moderation_status ?? "");
  if (["MODERATION", "PREACCEPTED"].includes(moderation) || requested === "MODERATION_PENDING") return "MODERATION_PENDING";
  return "SYSTEM_FAILED";
}

function outcomeOwnership(status: PackageItemStatus): PackageItemOwnership {
  if (status === "RECONCILIATION_REQUIRED" || status === "OUTCOME_UNKNOWN") return "UNKNOWN";
  if (status === "PROVIDER_REJECTED" || status === "REJECTED_NEEDS_EDIT" || status === "DIRECT_ACCEPTED") return "PROVIDER";
  if (status === "SYSTEM_FAILED") return "SYSTEM";
  if (status === "MODERATION_PENDING") return "PENDING_PROVIDER_OUTCOME";
  return "UNCLASSIFIED";
}

function outcomeProgress(
  status: PackageItemStatus,
  outcome: PackageItemExternalOutcome,
  ids: ProviderIds,
  readback: Record<string, unknown> | null,
  campaignState: string | null,
): PackageItemProgress {
  const rejected = status === "PROVIDER_REJECTED";
  const unknown = status === "RECONCILIATION_REQUIRED" || status === "OUTCOME_UNKNOWN";
  const campaignCreated = Boolean(ids.campaign_id);
  const childKinds = Number(ids.ad_group_ids.length > 0) + Number(ids.keyword_ids.length > 0) + Number(ids.ad_ids.length > 0);
  const suspended = campaignState === "SUSPENDED";
  const notCreatedTerminal = !campaignCreated && !unknown;
  const validationFailed = outcome.validation_failed === true;
  const dispatchNotAttempted = outcome.dispatch_not_attempted === true;
  return {
    validation: validationFailed ? "FAILED" : "PASSED",
    creation: dispatchNotAttempted ? "NOT_ATTEMPTED" : campaignCreated ? "CREATED" : unknown ? "UNKNOWN" : rejected ? "REJECTED" : "FAILED",
    suspension: suspended ? "CONFIRMED_SUSPENDED" : notCreatedTerminal ? "NOT_APPLICABLE" : unknown ? "UNKNOWN" : "FAILED",
    child_graph: childKinds === 3 ? "CREATED" : notCreatedTerminal ? "NOT_APPLICABLE" : childKinds > 0 ? "PARTIAL" : unknown ? "UNKNOWN" : "FAILED",
    readback: readback ? "VERIFIED" : notCreatedTerminal ? "NOT_APPLICABLE" : unknown ? "UNKNOWN" : "FAILED",
    moderation: status === "DIRECT_ACCEPTED" ? "ACCEPTED"
      : status === "PROVIDER_REJECTED" && !campaignCreated ? "NOT_APPLICABLE"
        : status === "REJECTED_NEEDS_EDIT" ? "REJECTED"
          : status === "MODERATION_PENDING" ? "PENDING"
            : unknown ? "UNKNOWN"
              : notCreatedTerminal ? "NOT_APPLICABLE" : "UNKNOWN",
  };
}

function outcomeContainment(
  outcome: PackageItemExternalOutcome,
  progress: PackageItemProgress,
  previous: PackageItemContainment,
): PackageItemContainment {
  if (progress.suspension === "CONFIRMED_SUSPENDED") return "CONFIRMED_SUSPENDED";
  if (!outcome.campaign_id && (outcome.rejected === true || outcome.dispatch_not_attempted === true)) return "NOT_CREATED";
  const value = String(outcome.containment ?? previous) as PackageItemContainment;
  return PACKAGE_ITEM_CONTAINMENTS.has(value) ? value : "UNKNOWN";
}

function outcomeAccountLock(outcome: PackageItemExternalOutcome, previous: PackageItemAccountLock): PackageItemAccountLock {
  if (["RECONCILIATION_REQUIRED", "MANUAL_RECONCILIATION_REQUIRED"].includes(String(outcome.containment ?? ""))) {
    return "HELD_FOR_RECONCILIATION";
  }
  const value = String(outcome.account_lock ?? previous) as PackageItemAccountLock;
  return PACKAGE_ITEM_ACCOUNT_LOCKS.has(value) ? value : "HELD_FOR_RECONCILIATION";
}

function failureFor(
  status: PackageItemStatus,
  outcome: PackageItemExternalOutcome,
  adOutcomes: PackageAdModerationOutcome[],
  evidence: ReturnType<typeof accountabilityEvidence>,
) {
  const errorCode = String(outcome.error_code ?? "");
  const errorMessage = String(outcome.error_message ?? "");
  if (errorCode || errorMessage) {
    return { code: errorCode || "P0_PACKAGE_ITEM_FAILED", message: errorMessage || "Package item execution failed." };
  }
  if (status === "REJECTED_NEEDS_EDIT") {
    const clarification = adOutcomes.map((item) => item.status_clarification).find(Boolean);
    return { code: "P0_DIRECT_MODERATION_REJECTED", message: clarification ?? "Direct rejected every launchable ad in at least one published group." };
  }
  if (status === "SYSTEM_FAILED" && !evidence.campaign_suspended) {
    return { code: "P0_FINAL_SUSPENSION_LOST", message: "Final Direct readback did not confirm State=SUSPENDED." };
  }
  if (status === "SYSTEM_FAILED" && !evidence.supported_graph_verified) {
    return { code: "P0_DIRECT_GRAPH_INCOMPLETE", message: "Final Direct readback did not prove the complete supported graph." };
  }
  return null;
}

export async function recordPackageItemOutcome(
  execution: PackageExecution,
  itemExecutionId: string,
  outcome: PackageItemExternalOutcome,
  updatedAt: string,
  options: { moderationPoll?: boolean } = {},
) {
  return replaceItem(execution, itemExecutionId, (item) => {
    const ids = providerIds(outcome, item.provider_ids);
    const semanticGraph = record(outcome.semantic_graph);
    const readback = Object.keys(semanticGraph).length ? structuredClone(semanticGraph) : item.readback;
    const campaignState = outcome.campaign_state ? String(outcome.campaign_state) : item.campaign_state;
    const observedAds = outcomeAdRows(outcome, ids, updatedAt);
    const adOutcomes = mergeAdOutcomes(item.moderation.ad_outcomes, observedAds);
    const observedProviderStatus = observedAds.length
      ? aggregateModerationStatus(observedAds)
      : item.moderation.provider_status;
    const evidence = accountabilityEvidence({ ids, readback, campaignState, adOutcomes });
    const status = normalizedOutcomeStatus({ outcome, evidence, adOutcomes, campaignState, ids });
    const providerStatus = status === "OUTCOME_UNKNOWN" && observedProviderStatus === "NOT_SUBMITTED"
      ? "UNKNOWN"
      : observedProviderStatus;
    const ownership = outcomeOwnership(status);
    const issues = mergeIssues(item.provider_issues, outcome, observedAds);
    const progress = outcomeProgress(status, outcome, ids, readback, campaignState);
    const containment = outcomeContainment(outcome, progress, item.containment);
    const accountLock = outcomeAccountLock(outcome, item.account_lock === "ACQUIRING" ? "RELEASED" : item.account_lock);
    const safeProviderContainment = containment === "NOT_CREATED"
      || containment === "CONFIRMED_SUSPENDED"
      || containment === "NON_SERVING_CONFIRMED";
    const providerOutcomeAccounted = evidence.direct_accepted || (
      ownership === "PROVIDER"
      && accountLock === "RELEASED"
      && safeProviderContainment
      && explicitProviderOutcome(status, issues, adOutcomes)
    );
    const pending = status === "MODERATION_PENDING" || status === "OUTCOME_UNKNOWN";
    const observation = observedAds.length || options.moderationPoll ? {
      observed_at: updatedAt,
      provider_status: providerStatus,
      ad_outcomes: structuredClone(observedAds),
    } : null;
    return {
      ...item,
      status,
      ownership,
      progress,
      provider_ids: ids,
      provider_issues: issues,
      readback,
      campaign_state: campaignState,
      moderation: {
        ...item.moderation,
        provider_status: providerStatus,
        last_polled_at: options.moderationPoll ? updatedAt : item.moderation.last_polled_at,
        next_poll_at: pending ? nextPollAt(updatedAt) : null,
        ad_outcomes: adOutcomes,
        observations: observation
          ? [...item.moderation.observations, observation].slice(-100)
          : item.moderation.observations,
      },
      accountability: {
        ...evidence,
        provider_outcome_accounted: providerOutcomeAccounted,
      },
      containment,
      failure: failureFor(status, outcome, adOutcomes, evidence),
      account_lock: accountLock,
      updated_at: updatedAt,
    };
  }, updatedAt);
}

export function packageItemModerationPollIsDue(item: PackageItemExecution, at: string) {
  if (!["MODERATION_PENDING", "OUTCOME_UNKNOWN"].includes(item.status) || !item.moderation.next_poll_at) return false;
  const due = Date.parse(item.moderation.next_poll_at);
  const current = Date.parse(at);
  return Number.isFinite(due) && Number.isFinite(current) && current >= due;
}

export async function beginPackageItemModerationPoll(
  execution: PackageExecution,
  itemExecutionId: string,
  startedAt: string,
) {
  return replaceItem(execution, itemExecutionId, (item) => {
    if (!packageItemModerationPollIsDue(item, startedAt)) throw new Error("Package moderation poll is not due.");
    return {
      ...item,
      moderation: {
        ...item.moderation,
        poll_attempts: item.moderation.poll_attempts + 1,
        last_poll_started_at: startedAt,
        next_poll_at: nextPollAt(startedAt),
      },
      updated_at: startedAt,
    };
  }, startedAt);
}

export async function migrateLegacyPackageExecution(
  value: unknown,
  migratedAt: string,
): Promise<PackageExecution> {
  const legacy = record(value);
  if (legacy.schema_version === PACKAGE_EXECUTION_SCHEMA) return legacy as PackageExecution;
  if (legacy.schema_version !== "p0-package-execution-v1" || !Array.isArray(legacy.items)) {
    throw new Error("Unsupported package execution schema.");
  }
  const unsignedLegacy = { ...legacy };
  delete unsignedLegacy.content_hash;
  if (legacy.content_hash !== await sha256(unsignedLegacy)) {
    throw new Error("Legacy package execution content hash verification failed.");
  }
  const items = legacy.items.map((entry, position): PackageItemExecution => {
    const item = record(entry);
    if (item.schema_version !== "p0-package-item-execution-v1") {
      throw new Error("Unsupported package item execution schema.");
    }
    const legacyIds = record(item.provider_ids);
    const adGroupIds = legacyIds.ad_group_id ? [String(legacyIds.ad_group_id)] : [];
    const keywordIds = legacyIds.keyword_id ? [String(legacyIds.keyword_id)] : [];
    const adIds = Array.isArray(legacyIds.ad_ids) ? uniqueStrings(legacyIds.ad_ids) : [];
    const ids: ProviderIds = {
      campaign_id: legacyIds.campaign_id ? String(legacyIds.campaign_id) : null,
      ad_group_id: adGroupIds[0] ?? null,
      keyword_id: keywordIds[0] ?? null,
      ad_group_ids: adGroupIds,
      keyword_ids: keywordIds,
      ad_ids: adIds,
    };
    const legacyProgress = record(item.progress);
    const readbackValue = record(item.readback);
    const readback = Object.keys(readbackValue).length ? structuredClone(readbackValue) : null;
    const legacyStatus = String(item.status ?? "QUEUED");
    const status: PackageItemStatus = legacyStatus === "READY_TO_LAUNCH"
      ? "OUTCOME_UNKNOWN"
      : PACKAGE_ITEM_STATUSES.has(legacyStatus as PackageItemStatus)
        ? legacyStatus as PackageItemStatus
        : "OUTCOME_UNKNOWN";
    const legacyOwnership = String(item.ownership ?? "UNCLASSIFIED") as PackageItemOwnership;
    const ownership: PackageItemOwnership = status === "OUTCOME_UNKNOWN"
      ? "UNKNOWN"
      : PACKAGE_ITEM_OWNERSHIPS.has(legacyOwnership) ? legacyOwnership : outcomeOwnership(status);
    const campaignState = legacyProgress.suspension === "CONFIRMED_SUSPENDED"
      ? "SUSPENDED"
      : readback ? String(record(readback.campaign).State ?? "") || null : null;
    const moderationValue = String(legacyProgress.moderation ?? "PENDING");
    const adStatus = moderationValue === "ACCEPTED" ? "ACCEPTED"
      : moderationValue === "REJECTED" ? "REJECTED"
        : status === "MODERATION_PENDING" ? "MODERATION" : null;
    const adOutcomes: PackageAdModerationOutcome[] = adStatus && adIds.length === 1 && adGroupIds.length === 1
      ? [{
          ad_id: adIds[0],
          ad_group_id: adGroupIds[0],
          status: adStatus,
          terminal: adStatus === "ACCEPTED" || adStatus === "REJECTED",
          accepted: adStatus === "ACCEPTED",
          status_clarification: null,
          provider_issues: [],
          observed_at: String(item.updated_at ?? migratedAt),
        }]
      : [];
    const evidence = accountabilityEvidence({ ids, readback, campaignState, adOutcomes });
    const containment = PACKAGE_ITEM_CONTAINMENTS.has(String(item.containment) as PackageItemContainment)
      ? String(item.containment) as PackageItemContainment
      : "UNKNOWN";
    const accountLock = PACKAGE_ITEM_ACCOUNT_LOCKS.has(String(item.account_lock) as PackageItemAccountLock)
      ? String(item.account_lock) as PackageItemAccountLock
      : status === "RECONCILIATION_REQUIRED" ? "HELD_FOR_RECONCILIATION" : "RELEASED";
    const providerIssues = Array.isArray(item.provider_issues)
      ? item.provider_issues.map((issue) => structuredClone(record(issue)))
      : [];
    const providerOutcomeAccounted = evidence.direct_accepted || (
      ownership === "PROVIDER"
      && accountLock === "RELEASED"
      && ["NOT_CREATED", "CONFIRMED_SUSPENDED", "NON_SERVING_CONFIRMED"].includes(containment)
      && explicitProviderOutcome(status, providerIssues, adOutcomes)
    );
    const providerStatus = aggregateModerationStatus(adOutcomes);
    const pending = status === "MODERATION_PENDING" || status === "OUTCOME_UNKNOWN";
    return {
      schema_version: PACKAGE_ITEM_EXECUTION_SCHEMA,
      item_execution_id: String(item.item_execution_id ?? ""),
      position,
      selection: structuredClone(record(item.selection)) as ShortlistSelection,
      status,
      ownership,
      progress: {
        validation: String(legacyProgress.validation ?? "PENDING") as PackageItemProgress["validation"],
        creation: String(legacyProgress.creation ?? "PENDING") as PackageItemProgress["creation"],
        suspension: String(legacyProgress.suspension ?? "PENDING") as PackageItemProgress["suspension"],
        child_graph: String(legacyProgress.child_graph ?? "PENDING") as PackageItemProgress["child_graph"],
        readback: String(legacyProgress.readback ?? "PENDING") as PackageItemProgress["readback"],
        moderation: status === "OUTCOME_UNKNOWN" ? "UNKNOWN" : String(legacyProgress.moderation ?? "PENDING") as PackageItemProgress["moderation"],
      },
      provider_ids: ids,
      provider_issues: providerIssues,
      readback,
      campaign_state: campaignState,
      moderation: {
        provider_status: providerStatus === "NOT_SUBMITTED" && pending ? "UNKNOWN" : providerStatus,
        poll_attempts: 0,
        last_poll_started_at: null,
        last_polled_at: null,
        next_poll_at: pending ? nextPollAt(migratedAt) : null,
        ad_outcomes: adOutcomes,
        observations: adOutcomes.length ? [{
          observed_at: String(item.updated_at ?? migratedAt),
          provider_status: providerStatus,
          ad_outcomes: structuredClone(adOutcomes),
        }] : [],
      },
      accountability: { ...evidence, provider_outcome_accounted: providerOutcomeAccounted },
      containment,
      failure: Object.keys(record(item.failure)).length
        ? {
            code: String(record(item.failure).code ?? "P0_PACKAGE_ITEM_FAILED"),
            message: String(record(item.failure).message ?? "Package item execution failed."),
          }
        : null,
      account_lock: accountLock,
      started_at: item.started_at === null || item.started_at === undefined ? null : String(item.started_at),
      updated_at: String(item.updated_at ?? migratedAt),
    };
  });
  const verdict = packageVerdict(items);
  return sealExecution({
    schema_version: PACKAGE_EXECUTION_SCHEMA,
    contract_version: "2.0.0",
    package_execution_id: String(legacy.package_execution_id ?? ""),
    package_id: String(legacy.package_id ?? ""),
    package_review_id: String(legacy.package_review_id ?? ""),
    gate_id: String(legacy.gate_id ?? ""),
    status: packageStatus(items, verdict),
    verdict,
    atomic_transaction: false,
    selected_count: items.length,
    dispatched_count: items.filter((item) => !["QUEUED", "DISPATCHING"].includes(item.status)).length,
    items,
    started_at: String(legacy.started_at ?? migratedAt),
    updated_at: migratedAt,
  });
}

export function packageExecutionBlocksFollowingItems(execution: PackageExecution) {
  return execution.items.some((item) => item.status === "RECONCILIATION_REQUIRED"
    || (Boolean(item.provider_ids.campaign_id) && item.progress.suspension !== "CONFIRMED_SUSPENDED"));
}

const PACKAGE_ITEM_STATUSES = new Set<PackageItemStatus>([
  "QUEUED", "DISPATCHING", "MODERATION_PENDING", "OUTCOME_UNKNOWN", "DIRECT_ACCEPTED",
  "REJECTED_NEEDS_EDIT", "PROVIDER_REJECTED", "SYSTEM_FAILED", "RECONCILIATION_REQUIRED",
]);
const PACKAGE_ITEM_OWNERSHIPS = new Set<PackageItemOwnership>([
  "UNCLASSIFIED", "PENDING_PROVIDER_OUTCOME", "PROVIDER", "SYSTEM", "UNKNOWN",
]);
const PACKAGE_ITEM_CONTAINMENTS = new Set<PackageItemContainment>([
  "PENDING", "NOT_CREATED", "CONFIRMED_SUSPENDED", "NON_SERVING_CONFIRMED",
  "RECONCILIATION_REQUIRED", "MANUAL_RECONCILIATION_REQUIRED", "UNKNOWN",
]);
const PACKAGE_ITEM_ACCOUNT_LOCKS = new Set<PackageItemAccountLock>([
  "NOT_ACQUIRED", "ACQUIRING", "RELEASED", "HELD_FOR_RECONCILIATION",
]);
const PACKAGE_PROGRESS_VALUES = {
  validation: new Set(["PENDING", "PASSED", "FAILED"]),
  creation: new Set(["PENDING", "NOT_ATTEMPTED", "CREATED", "REJECTED", "FAILED", "UNKNOWN"]),
  suspension: new Set(["PENDING", "CONFIRMED_SUSPENDED", "NOT_APPLICABLE", "FAILED", "UNKNOWN"]),
  child_graph: new Set(["PENDING", "CREATED", "NOT_APPLICABLE", "PARTIAL", "FAILED", "UNKNOWN"]),
  readback: new Set(["PENDING", "VERIFIED", "NOT_APPLICABLE", "FAILED", "UNKNOWN"]),
  moderation: new Set(["PENDING", "ACCEPTED", "REJECTED", "NOT_APPLICABLE", "UNKNOWN"]),
} as const;

function validItemState(item: PackageItemExecution) {
  const progress = record(item.progress);
  const progressKeys = Object.keys(PACKAGE_PROGRESS_VALUES);
  if (JSON.stringify(Object.keys(progress).sort()) !== JSON.stringify(progressKeys.sort())
    || progressKeys.some((key) => !PACKAGE_PROGRESS_VALUES[key as keyof typeof PACKAGE_PROGRESS_VALUES].has(String(progress[key])))) {
    return false;
  }
  if (item.status === "QUEUED" && (item.ownership !== "UNCLASSIFIED" || item.account_lock !== "NOT_ACQUIRED" || item.started_at !== null)) return false;
  if (item.status === "DISPATCHING" && (item.ownership !== "UNCLASSIFIED" || item.account_lock !== "ACQUIRING" || !item.started_at)) return false;
  if (item.status === "MODERATION_PENDING" && (item.ownership !== "PENDING_PROVIDER_OUTCOME" || item.account_lock !== "RELEASED")) return false;
  if (item.status === "OUTCOME_UNKNOWN" && item.ownership !== "UNKNOWN") return false;
  if (["DIRECT_ACCEPTED", "PROVIDER_REJECTED", "REJECTED_NEEDS_EDIT", "SYSTEM_FAILED"].includes(item.status) && item.account_lock !== "RELEASED") return false;
  if (["DIRECT_ACCEPTED", "PROVIDER_REJECTED", "REJECTED_NEEDS_EDIT"].includes(item.status) && item.ownership !== "PROVIDER") return false;
  if (item.status === "SYSTEM_FAILED" && item.ownership !== "SYSTEM") return false;
  if (item.status === "RECONCILIATION_REQUIRED" && (item.ownership !== "UNKNOWN" || item.account_lock !== "HELD_FOR_RECONCILIATION")) return false;
  const providerIds = [
    item.provider_ids.campaign_id,
    item.provider_ids.ad_group_id,
    item.provider_ids.keyword_id,
    ...item.provider_ids.ad_group_ids,
    ...item.provider_ids.keyword_ids,
    ...item.provider_ids.ad_ids,
  ];
  if (providerIds.some((providerId) => providerId !== null && !/^\d+$/u.test(providerId))) return false;
  if (item.containment === "NOT_CREATED" && item.provider_ids.campaign_id) return false;
  if (item.containment === "CONFIRMED_SUSPENDED" && (!item.provider_ids.campaign_id || item.progress.suspension !== "CONFIRMED_SUSPENDED")) return false;
  if (item.accountability.direct_accepted !== (item.status === "DIRECT_ACCEPTED")) return false;
  if (item.status === "MODERATION_PENDING" && !item.moderation.next_poll_at) return false;
  if (!["MODERATION_PENDING", "OUTCOME_UNKNOWN"].includes(item.status) && item.moderation.next_poll_at !== null) return false;
  const expectedEvidence = accountabilityEvidence({
    ids: item.provider_ids,
    readback: item.readback,
    campaignState: item.campaign_state,
    adOutcomes: item.moderation.ad_outcomes,
  });
  for (const key of Object.keys(expectedEvidence) as Array<keyof typeof expectedEvidence>) {
    if (JSON.stringify(item.accountability[key]) !== JSON.stringify(expectedEvidence[key])) return false;
  }
  return true;
}

export async function verifyPackageExecution(input: {
  execution: PackageExecution | unknown;
  gate: HumanDecisionGate;
  recommendationSet: CampaignRecommendationSet;
}) {
  const candidate = record(input.execution) as PackageExecution;
  if (candidate.schema_version !== PACKAGE_EXECUTION_SCHEMA
    || candidate.contract_version !== "2.0.0"
    || candidate.package_id !== input.gate.package_id
    || candidate.package_review_id !== input.gate.package_review_id
    || candidate.gate_id !== input.gate.gate_id
    || candidate.atomic_transaction !== false
    || !Array.isArray(candidate.items)
    || candidate.items.length !== input.gate.authority.ordered_selections.length
    || candidate.selected_count !== candidate.items.length
    || candidate.dispatched_count !== candidate.items.filter((item) => !["QUEUED", "DISPATCHING"].includes(item.status)).length
    || candidate.verdict !== packageVerdict(candidate.items)
    || candidate.status !== packageStatus(candidate.items, candidate.verdict)) return false;
  const unsigned = { ...candidate } as Record<string, unknown>;
  delete unsigned.content_hash;
  if (candidate.content_hash !== await sha256(unsigned)) return false;
  for (const [position, item] of candidate.items.entries()) {
    const selection = input.gate.authority.ordered_selections[position];
    const draft = input.recommendationSet.drafts.find((entry) => entry.draft_id === selection.draft_id);
    if (item.schema_version !== PACKAGE_ITEM_EXECUTION_SCHEMA
      || item.position !== position
      || JSON.stringify(item.selection) !== JSON.stringify(selection)
      || !draft
      || !selectionMatchesDraft(selection, draft, input.recommendationSet)
      || item.item_execution_id !== await itemExecutionId(input.gate.package_id, input.gate.gate_id, position, selection)
      || !PACKAGE_ITEM_STATUSES.has(item.status)
      || !PACKAGE_ITEM_OWNERSHIPS.has(item.ownership)
      || !PACKAGE_ITEM_CONTAINMENTS.has(item.containment)
      || !PACKAGE_ITEM_ACCOUNT_LOCKS.has(item.account_lock)
      || !item.progress
      || !item.provider_ids
      || !Array.isArray(item.provider_ids.ad_group_ids)
      || !Array.isArray(item.provider_ids.keyword_ids)
      || !Array.isArray(item.provider_ids.ad_ids)
      || !Array.isArray(item.provider_issues)
      || !item.moderation
      || !Array.isArray(item.moderation.ad_outcomes)
      || !Array.isArray(item.moderation.observations)
      || !item.accountability
      || !validItemState(item)) return false;
  }
  return true;
}
