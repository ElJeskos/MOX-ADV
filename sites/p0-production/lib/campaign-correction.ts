import { canonicalizeEvidence } from "./analytics-evidence.ts";
import type { HumanDecisionGate, P0Shortlist, PackageReview } from "./campaign-decision-gate.ts";
import type {
  PackageExecution,
  PackageItemExecution,
  PackageVerdict,
} from "./campaign-package-execution.ts";
import type { CampaignRecommendationSet } from "./campaign-fanout.ts";

export const PACKAGE_CORRECTION_SCHEMA = "p0-package-correction-v1";

export type PackageCorrectionStatus =
  | "EDITING"
  | "PACKAGE_REVIEW_REQUIRED"
  | "HUMAN_GATE_REQUIRED"
  | "READY_TO_RESUBMIT"
  | "RESUBMISSION_PENDING"
  | "PASS_AFTER_CORRECTION"
  | "CORRECTION_FAILED";

export type PackageCorrectionTerminalOutcome = "PASS_AFTER_CORRECTION" | "FAIL" | null;

type Draft = CampaignRecommendationSet["drafts"][number];

export type PackageCorrection = {
  schema_version: typeof PACKAGE_CORRECTION_SCHEMA;
  contract_version: "1.0.0";
  correction_id: string;
  status: PackageCorrectionStatus;
  source: {
    initial_package_execution_id: string;
    initial_package_content_hash: string;
    initial_package_verdict: PackageVerdict;
    package_id: string;
    package_review_id: string;
    gate_id: string;
    item_execution_id: string;
    item_status: "REJECTED_NEEDS_EDIT";
    selection: PackageItemExecution["selection"];
    item_snapshot: PackageItemExecution;
    draft_snapshot: Draft;
    status_clarifications: string[];
    provider_issues: Array<Record<string, unknown>>;
  };
  corrected_recommendation_set: CampaignRecommendationSet | null;
  corrected_draft: Draft | null;
  shortlist: P0Shortlist | null;
  package_review: PackageReview | null;
  human_decision_gate: HumanDecisionGate | null;
  execution: PackageExecution | null;
  terminal_outcome: PackageCorrectionTerminalOutcome;
  accounting: {
    initial_package_verdict: PackageVerdict;
    initial_generation_passed: false;
    corrected_terminal_outcome: PackageCorrectionTerminalOutcome;
  };
  created_at: string;
  updated_at: string;
  content_hash: string;
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

async function sha256(value: unknown) {
  const bytes = new TextEncoder().encode(canonicalizeEvidence(value));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return `sha256:${[...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("")}`;
}

function unsignedCorrection(value: PackageCorrection) {
  const unsigned = { ...value } as Omit<PackageCorrection, "content_hash"> & { content_hash?: string };
  delete unsigned.content_hash;
  return unsigned as Omit<PackageCorrection, "content_hash">;
}

export async function sealPackageCorrection(
  value: Omit<PackageCorrection, "content_hash"> | PackageCorrection,
): Promise<PackageCorrection> {
  const unsigned = "content_hash" in value
    ? unsignedCorrection(value as PackageCorrection)
    : value as Omit<PackageCorrection, "content_hash">;
  return { ...structuredClone(unsigned), content_hash: await sha256(unsigned) };
}

function sourceClarifications(item: PackageItemExecution) {
  return [...new Set(item.moderation.ad_outcomes
    .filter((ad) => ad.status === "REJECTED")
    .map((ad) => String(ad.status_clarification ?? "").trim())
    .filter(Boolean))];
}

export async function initializePackageCorrection(input: {
  execution: PackageExecution;
  item: PackageItemExecution;
  draft: Draft;
  createdAt: string;
}) {
  if (input.execution.verdict === "PENDING" || input.execution.status === "DISPATCHING") {
    throw new Error("Correction requires the initial package to have a terminal verdict.");
  }
  if (input.item.status !== "REJECTED_NEEDS_EDIT"
    || input.item.ownership !== "PROVIDER"
    || input.item.account_lock !== "RELEASED"
    || input.item.accountability.provider_outcome_accounted !== true) {
    throw new Error("Only a fully-accounted provider content rejection can enter correction.");
  }
  if (input.draft.draft_id !== input.item.selection.draft_id
    || input.draft.draft_revision_id !== input.item.selection.draft_revision_id
    || input.draft.publish_fingerprint !== input.item.selection.publish_fingerprint) {
    throw new Error("Rejected item lost its exact Campaign Draft lineage.");
  }
  const statusClarifications = sourceClarifications(input.item);
  if (!statusClarifications.length && !input.item.provider_issues.length) {
    throw new Error("Provider content rejection has no StatusClarification or issue details.");
  }
  const correctionId = await sha256({
    schema_version: PACKAGE_CORRECTION_SCHEMA,
    initial_package_execution_id: input.execution.package_execution_id,
    initial_package_content_hash: input.execution.content_hash,
    item_execution_id: input.item.item_execution_id,
  });
  return sealPackageCorrection({
    schema_version: PACKAGE_CORRECTION_SCHEMA,
    contract_version: "1.0.0",
    correction_id: correctionId,
    status: "EDITING",
    source: {
      initial_package_execution_id: input.execution.package_execution_id,
      initial_package_content_hash: input.execution.content_hash,
      initial_package_verdict: input.execution.verdict,
      package_id: input.execution.package_id,
      package_review_id: input.execution.package_review_id,
      gate_id: input.execution.gate_id,
      item_execution_id: input.item.item_execution_id,
      item_status: "REJECTED_NEEDS_EDIT",
      selection: structuredClone(input.item.selection),
      item_snapshot: structuredClone(input.item),
      draft_snapshot: structuredClone(input.draft),
      status_clarifications: statusClarifications,
      provider_issues: structuredClone(input.item.provider_issues),
    },
    corrected_recommendation_set: null,
    corrected_draft: null,
    shortlist: null,
    package_review: null,
    human_decision_gate: null,
    execution: null,
    terminal_outcome: null,
    accounting: {
      initial_package_verdict: input.execution.verdict,
      initial_generation_passed: false,
      corrected_terminal_outcome: null,
    },
    created_at: input.createdAt,
    updated_at: input.createdAt,
  });
}

export async function updatePackageCorrection(
  correction: PackageCorrection,
  patch: Partial<Omit<PackageCorrection, "schema_version" | "contract_version" | "correction_id" | "source" | "created_at" | "content_hash">>,
  updatedAt: string,
) {
  return sealPackageCorrection({
    ...unsignedCorrection(correction),
    ...structuredClone(patch),
    updated_at: updatedAt,
  });
}

export async function recordCorrectionExecution(
  correction: PackageCorrection,
  execution: PackageExecution,
  updatedAt: string,
) {
  const terminalOutcome: PackageCorrectionTerminalOutcome = execution.verdict === "PASS"
    ? "PASS_AFTER_CORRECTION"
    : execution.verdict === "FAIL" || execution.verdict === "PASS_WITH_PLATFORM_REJECTIONS"
      ? "FAIL"
      : null;
  const status: PackageCorrectionStatus = terminalOutcome === "PASS_AFTER_CORRECTION"
    ? "PASS_AFTER_CORRECTION"
    : terminalOutcome === "FAIL"
      ? "CORRECTION_FAILED"
      : "RESUBMISSION_PENDING";
  return updatePackageCorrection(correction, {
    execution,
    status,
    terminal_outcome: terminalOutcome,
    accounting: {
      initial_package_verdict: correction.source.initial_package_verdict,
      initial_generation_passed: false,
      corrected_terminal_outcome: terminalOutcome,
    },
  }, updatedAt);
}

function statusShapeIsValid(correction: PackageCorrection) {
  const hasDraft = Boolean(correction.corrected_recommendation_set && correction.corrected_draft && correction.shortlist);
  const hasReview = Boolean(correction.package_review);
  const hasGate = Boolean(correction.human_decision_gate);
  const hasExecution = Boolean(correction.execution);
  if (correction.status === "EDITING") return !hasDraft && !hasReview && !hasGate && !hasExecution && correction.terminal_outcome === null;
  if (correction.status === "PACKAGE_REVIEW_REQUIRED") return hasDraft && !hasReview && !hasGate && !hasExecution && correction.terminal_outcome === null;
  if (correction.status === "HUMAN_GATE_REQUIRED") return hasDraft && hasReview && !hasGate && !hasExecution && correction.terminal_outcome === null;
  if (correction.status === "READY_TO_RESUBMIT") return hasDraft && hasReview && hasGate && !hasExecution && correction.terminal_outcome === null;
  if (correction.status === "RESUBMISSION_PENDING") return hasDraft && hasReview && hasGate && hasExecution && correction.execution?.verdict === "PENDING" && correction.terminal_outcome === null;
  if (correction.status === "PASS_AFTER_CORRECTION") return hasDraft && hasReview && hasGate && hasExecution && correction.execution?.verdict === "PASS" && correction.terminal_outcome === "PASS_AFTER_CORRECTION";
  if (correction.status === "CORRECTION_FAILED") return hasDraft && hasReview && hasGate && hasExecution && correction.terminal_outcome === "FAIL";
  return false;
}

export async function verifyPackageCorrection(input: {
  correction: PackageCorrection | unknown;
  sourceExecution: PackageExecution;
  sourceRecommendationSet: CampaignRecommendationSet;
}) {
  const candidate = record(input.correction) as PackageCorrection;
  if (candidate.schema_version !== PACKAGE_CORRECTION_SCHEMA
    || candidate.contract_version !== "1.0.0"
    || !candidate.correction_id
    || !candidate.created_at
    || !candidate.updated_at
    || !candidate.source
    || !candidate.accounting
    || candidate.accounting.initial_generation_passed !== false
    || candidate.accounting.initial_package_verdict !== candidate.source.initial_package_verdict
    || candidate.accounting.corrected_terminal_outcome !== candidate.terminal_outcome
    || !statusShapeIsValid(candidate)) return false;
  const unsigned = unsignedCorrection(candidate);
  if (candidate.content_hash !== await sha256(unsigned)) return false;
  const sourceItem = input.sourceExecution.items.find((item) => item.item_execution_id === candidate.source.item_execution_id);
  const sourceDraft = input.sourceRecommendationSet.drafts.find((draft) => draft.draft_id === candidate.source.selection.draft_id);
  if (!sourceItem || !sourceDraft
    || candidate.source.initial_package_execution_id !== input.sourceExecution.package_execution_id
    || candidate.source.initial_package_content_hash !== input.sourceExecution.content_hash
    || candidate.source.initial_package_verdict !== input.sourceExecution.verdict
    || candidate.source.package_id !== input.sourceExecution.package_id
    || candidate.source.package_review_id !== input.sourceExecution.package_review_id
    || candidate.source.gate_id !== input.sourceExecution.gate_id
    || candidate.source.item_status !== "REJECTED_NEEDS_EDIT"
    || JSON.stringify(candidate.source.selection) !== JSON.stringify(sourceItem.selection)
    || JSON.stringify(candidate.source.item_snapshot) !== JSON.stringify(sourceItem)
    || JSON.stringify(candidate.source.draft_snapshot) !== JSON.stringify(sourceDraft)
    || JSON.stringify(candidate.source.provider_issues) !== JSON.stringify(sourceItem.provider_issues)
    || JSON.stringify(candidate.source.status_clarifications) !== JSON.stringify(sourceClarifications(sourceItem))) return false;
  if (candidate.corrected_draft && candidate.corrected_recommendation_set) {
    const corrected = candidate.corrected_recommendation_set.drafts.find((draft) => draft.draft_id === candidate.corrected_draft?.draft_id);
    if (!corrected || JSON.stringify(corrected) !== JSON.stringify(candidate.corrected_draft)) return false;
    if (candidate.corrected_draft.draft_revision_id === candidate.source.selection.draft_revision_id
      || candidate.corrected_draft.publish_fingerprint === candidate.source.selection.publish_fingerprint) return false;
  }
  return true;
}
