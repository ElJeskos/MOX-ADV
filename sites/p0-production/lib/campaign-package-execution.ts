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

export const PACKAGE_EXECUTION_SCHEMA = "p0-package-execution-v1";
export const PACKAGE_ITEM_EXECUTION_SCHEMA = "p0-package-item-execution-v1";

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
  | "READY_TO_LAUNCH"
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
    ad_ids: string[];
  };
  provider_issues: Array<Record<string, unknown>>;
  readback: Record<string, unknown> | null;
  containment: PackageItemContainment;
  failure: { code: string; message: string } | null;
  account_lock: PackageItemAccountLock;
  started_at: string | null;
  updated_at: string;
};

export type PackageExecution = {
  schema_version: typeof PACKAGE_EXECUTION_SCHEMA;
  contract_version: "1.0.0";
  package_execution_id: string;
  package_id: string;
  package_review_id: string;
  gate_id: string;
  status: "DISPATCHING" | "PENDING" | "FAIL_CLOSED" | "RECONCILIATION_REQUIRED";
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

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
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
    schema_version: PACKAGE_ITEM_EXECUTION_SCHEMA,
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
    contract_version: "1.0.0",
    package_execution_id: packageExecutionId,
    package_id: input.gate.package_id,
    package_review_id: input.gate.package_review_id,
    gate_id: input.gate.gate_id,
    status: "DISPATCHING",
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
      provider_ids: { campaign_id: null, ad_group_id: null, keyword_id: null, ad_ids: [] },
      provider_issues: [],
      readback: null,
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

function packageStatus(items: PackageItemExecution[]): PackageExecution["status"] {
  if (items.some((item) => item.ownership === "UNKNOWN" || item.status === "RECONCILIATION_REQUIRED")) {
    return "RECONCILIATION_REQUIRED";
  }
  if (items.some((item) => item.provider_ids.campaign_id && item.progress.suspension !== "CONFIRMED_SUSPENDED")) {
    return "FAIL_CLOSED";
  }
  if (items.some((item) => item.ownership === "SYSTEM" && item.containment !== "CONFIRMED_SUSPENDED" && item.containment !== "NOT_CREATED")) {
    return "FAIL_CLOSED";
  }
  if (items.some((item) => item.status === "QUEUED" || item.status === "DISPATCHING")) return "DISPATCHING";
  return "PENDING";
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
  const unsignedExecution = Object.fromEntries(
    Object.entries(execution).filter(([key]) => key !== "content_hash"),
  ) as Omit<PackageExecution, "content_hash">;
  return sealExecution({
    ...unsignedExecution,
    items,
    status: packageStatus(items),
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

function providerIds(outcome: PackageItemExternalOutcome) {
  const directIds = record(outcome.provider_ids);
  const adIds = Array.isArray(directIds.ad_ids)
    ? directIds.ad_ids.map(String)
    : outcome.ad_id ? [String(outcome.ad_id)] : [];
  return {
    campaign_id: outcome.campaign_id ? String(outcome.campaign_id) : directIds.campaign_id ? String(directIds.campaign_id) : null,
    ad_group_id: outcome.ad_group_id ? String(outcome.ad_group_id) : directIds.ad_group_id ? String(directIds.ad_group_id) : null,
    keyword_id: outcome.keyword_id ? String(outcome.keyword_id) : directIds.keyword_id ? String(directIds.keyword_id) : null,
    ad_ids: adIds,
  };
}

const PACKAGE_ITEM_STATUSES = new Set<PackageItemStatus>([
  "QUEUED", "DISPATCHING", "MODERATION_PENDING", "READY_TO_LAUNCH", "REJECTED_NEEDS_EDIT",
  "PROVIDER_REJECTED", "SYSTEM_FAILED", "RECONCILIATION_REQUIRED",
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
  if (["READY_TO_LAUNCH", "PROVIDER_REJECTED", "REJECTED_NEEDS_EDIT", "SYSTEM_FAILED"].includes(item.status) && item.account_lock !== "RELEASED") return false;
  if (["PROVIDER_REJECTED", "REJECTED_NEEDS_EDIT"].includes(item.status) && item.ownership !== "PROVIDER") return false;
  if (item.status === "SYSTEM_FAILED" && item.ownership !== "SYSTEM") return false;
  if (item.status === "RECONCILIATION_REQUIRED" && (item.ownership !== "UNKNOWN" || item.account_lock !== "HELD_FOR_RECONCILIATION")) return false;
  const providerIds = [item.provider_ids.campaign_id, item.provider_ids.ad_group_id, item.provider_ids.keyword_id, ...item.provider_ids.ad_ids];
  if (providerIds.some((providerId) => providerId !== null && !/^\d+$/u.test(providerId))) return false;
  if (item.containment === "NOT_CREATED" && item.provider_ids.campaign_id) return false;
  if (item.containment === "CONFIRMED_SUSPENDED" && (!item.provider_ids.campaign_id || item.progress.suspension !== "CONFIRMED_SUSPENDED")) return false;
  return true;
}

function normalizedOutcomeStatus(outcome: PackageItemExternalOutcome): PackageItemStatus {
  const value = String(outcome.status ?? "") as PackageItemStatus;
  const accountLock = String(outcome.account_lock ?? "RELEASED");
  if (outcome.requires_reconciliation === true
    || accountLock === "HELD_FOR_RECONCILIATION"
    || ["RECONCILIATION_REQUIRED", "MANUAL_RECONCILIATION_REQUIRED"].includes(String(outcome.containment ?? ""))
    || !["RELEASED", "HELD_FOR_RECONCILIATION"].includes(accountLock)) return "RECONCILIATION_REQUIRED";
  if (PACKAGE_ITEM_STATUSES.has(value) && !["QUEUED", "DISPATCHING"].includes(value)) return value;
  if (outcome.rejected === true) return "PROVIDER_REJECTED";
  return "SYSTEM_FAILED";
}

function outcomeOwnership(status: PackageItemStatus, outcome: PackageItemExternalOutcome): PackageItemOwnership {
  if (status === "RECONCILIATION_REQUIRED" || outcome.requires_reconciliation === true || outcome.account_lock === "HELD_FOR_RECONCILIATION") return "UNKNOWN";
  if (outcome.rejected === true || status === "PROVIDER_REJECTED" || status === "REJECTED_NEEDS_EDIT") return "PROVIDER";
  if (status === "SYSTEM_FAILED" || outcome.error_code) return "SYSTEM";
  if (["MODERATION_PENDING", "PREACCEPTED", "MODERATION"].includes(status) || ["MODERATION", "PREACCEPTED"].includes(String(outcome.moderation_status ?? ""))) {
    return "PENDING_PROVIDER_OUTCOME";
  }
  return "UNCLASSIFIED";
}

function outcomeProgress(
  status: PackageItemStatus,
  outcome: PackageItemExternalOutcome,
  ids: ReturnType<typeof providerIds>,
): PackageItemProgress {
  const steps = new Set(Array.isArray(outcome.steps) ? outcome.steps.map(String) : []);
  const rejected = outcome.rejected === true || status === "PROVIDER_REJECTED";
  const unknown = status === "RECONCILIATION_REQUIRED" || outcome.requires_reconciliation === true;
  const campaignCreated = Boolean(ids.campaign_id);
  const childCount = Number(Boolean(ids.ad_group_id)) + Number(Boolean(ids.keyword_id)) + Number(ids.ad_ids.length > 0);
  const suspended = outcome.campaign_state === "SUSPENDED" || steps.has("NON_SERVING_CONFIRMED");
  const readback = record(outcome.semantic_graph);
  const moderation = String(outcome.moderation_status ?? "");
  const notCreatedTerminal = !campaignCreated && !unknown;
  const validationFailed = outcome.validation_failed === true;
  const dispatchNotAttempted = outcome.dispatch_not_attempted === true;
  return {
    validation: validationFailed ? "FAILED" : "PASSED",
    creation: dispatchNotAttempted ? "NOT_ATTEMPTED" : campaignCreated ? "CREATED" : unknown ? "UNKNOWN" : rejected ? "REJECTED" : "FAILED",
    suspension: suspended ? "CONFIRMED_SUSPENDED" : notCreatedTerminal ? "NOT_APPLICABLE" : unknown ? "UNKNOWN" : "FAILED",
    child_graph: childCount === 3 ? "CREATED" : notCreatedTerminal ? "NOT_APPLICABLE" : childCount > 0 ? "PARTIAL" : unknown ? "UNKNOWN" : "FAILED",
    readback: Object.keys(readback).length ? "VERIFIED" : notCreatedTerminal ? "NOT_APPLICABLE" : unknown ? "UNKNOWN" : "FAILED",
    moderation: moderation === "ACCEPTED" ? "ACCEPTED" : moderation === "REJECTED" ? "REJECTED" : ["MODERATION", "PREACCEPTED"].includes(moderation) || status === "MODERATION_PENDING" ? "PENDING" : notCreatedTerminal ? "NOT_APPLICABLE" : "UNKNOWN",
  };
}

function outcomeContainment(outcome: PackageItemExternalOutcome, progress: PackageItemProgress): PackageItemContainment {
  if (progress.suspension === "CONFIRMED_SUSPENDED") return "CONFIRMED_SUSPENDED";
  if (!outcome.campaign_id && (outcome.rejected === true || outcome.dispatch_not_attempted === true)) return "NOT_CREATED";
  const value = String(outcome.containment ?? "UNKNOWN") as PackageItemContainment;
  return PACKAGE_ITEM_CONTAINMENTS.has(value) ? value : "UNKNOWN";
}

function outcomeAccountLock(outcome: PackageItemExternalOutcome): PackageItemAccountLock {
  if (["RECONCILIATION_REQUIRED", "MANUAL_RECONCILIATION_REQUIRED"].includes(String(outcome.containment ?? ""))) {
    return "HELD_FOR_RECONCILIATION";
  }
  const value = String(outcome.account_lock ?? "RELEASED") as PackageItemAccountLock;
  return PACKAGE_ITEM_ACCOUNT_LOCKS.has(value) ? value : "HELD_FOR_RECONCILIATION";
}

export async function recordPackageItemOutcome(
  execution: PackageExecution,
  itemExecutionId: string,
  outcome: PackageItemExternalOutcome,
  updatedAt: string,
) {
  const status = normalizedOutcomeStatus(outcome);
  const ids = providerIds(outcome);
  const progress = outcomeProgress(status, outcome, ids);
  const issues = Array.isArray(outcome.provider_issues)
    ? outcome.provider_issues.map((issue) => structuredClone(record(issue)))
    : [];
  const semanticGraph = record(outcome.semantic_graph);
  const errorCode = String(outcome.error_code ?? "");
  const errorMessage = String(outcome.error_message ?? "");
  return replaceItem(execution, itemExecutionId, (item) => ({
    ...item,
    status,
    ownership: outcomeOwnership(status, outcome),
    progress,
    provider_ids: ids,
    provider_issues: issues,
    readback: Object.keys(semanticGraph).length ? structuredClone(semanticGraph) : null,
    containment: outcomeContainment(outcome, progress),
    failure: errorCode || errorMessage ? { code: errorCode || "P0_PACKAGE_ITEM_FAILED", message: errorMessage || "Package item execution failed." } : null,
    account_lock: outcomeAccountLock(outcome),
    updated_at: updatedAt,
  }), updatedAt);
}

export function packageExecutionBlocksFollowingItems(execution: PackageExecution) {
  return execution.status === "RECONCILIATION_REQUIRED" || execution.status === "FAIL_CLOSED";
}

export async function verifyPackageExecution(input: {
  execution: PackageExecution | unknown;
  gate: HumanDecisionGate;
  recommendationSet: CampaignRecommendationSet;
}) {
  const candidate = record(input.execution) as PackageExecution;
  if (candidate.schema_version !== PACKAGE_EXECUTION_SCHEMA
    || candidate.contract_version !== "1.0.0"
    || candidate.package_id !== input.gate.package_id
    || candidate.package_review_id !== input.gate.package_review_id
    || candidate.gate_id !== input.gate.gate_id
    || candidate.atomic_transaction !== false
    || !Array.isArray(candidate.items)
    || candidate.items.length !== input.gate.authority.ordered_selections.length
    || candidate.selected_count !== candidate.items.length
    || candidate.dispatched_count !== candidate.items.filter((item) => !["QUEUED", "DISPATCHING"].includes(item.status)).length
    || candidate.status !== packageStatus(candidate.items)) return false;
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
      || !Array.isArray(item.provider_ids.ad_ids)
      || !Array.isArray(item.provider_issues)
      || !validItemState(item)) return false;
  }
  return true;
}
