export type CampaignEvidenceStatus = "AVAILABLE" | "PARTIAL" | "EVIDENCE_GAP" | "UNAVAILABLE";
export type CampaignDraftVisibility = "VISIBLE" | "HIDDEN";

export type CampaignCanvasFilters = {
  variant: "ALL" | "CONTROL" | "IMPROVEMENT";
  evidence: "ALL" | CampaignEvidenceStatus;
  sort: "RANK" | "SCORE";
  includeHidden: boolean;
};

type CanvasDraft = Record<string, unknown> & {
  draft_id: string;
  visibility?: CampaignDraftVisibility;
  variant?: { kind?: "CONTROL" | "IMPROVEMENT" };
  market_evidence_status?: CampaignEvidenceStatus;
  viability_score?: { rank?: number | null; score?: number | null; score_raw?: number | null };
};

const toFiniteNumberOr = (value: unknown, fallback: number) => Number.isFinite(Number(value)) ? Number(value) : fallback;

export function filterAndSortCampaignDrafts<T extends CanvasDraft>(drafts: T[], filters: CampaignCanvasFilters): T[] {
  return drafts
    .filter((draft) => filters.includeHidden || draft.visibility === "VISIBLE")
    .filter((draft) => filters.variant === "ALL" || draft.variant?.kind === filters.variant)
    .filter((draft) => filters.evidence === "ALL" || draft.market_evidence_status === filters.evidence)
    .sort((left, right) => {
      const valueOrder = filters.sort === "SCORE"
        ? toFiniteNumberOr(right.viability_score?.score_raw ?? right.viability_score?.score, Number.NEGATIVE_INFINITY)
          - toFiniteNumberOr(left.viability_score?.score_raw ?? left.viability_score?.score, Number.NEGATIVE_INFINITY)
        : toFiniteNumberOr(left.viability_score?.rank, Number.POSITIVE_INFINITY)
          - toFiniteNumberOr(right.viability_score?.rank, Number.POSITIVE_INFINITY);
      return valueOrder || left.draft_id.localeCompare(right.draft_id);
    });
}
