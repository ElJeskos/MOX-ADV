export type PersistedP0RevisionRow = {
  revision: number;
  updated_at: string;
  value_json: string;
};

export type P0RevisionSummary = {
  revision: number;
  updated_at: string;
  status: "CURRENT" | "SUPERSEDED";
  strategy_revision_id: string | null;
  recommendation_set_id: string | null;
  draft_id: string | null;
  draft_revision_id: string | null;
  publish_fingerprint: string | null;
  campaign_id: string | null;
  campaign_state: string | null;
};

function record(value: unknown) {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function optionalText(value: unknown) {
  const result = String(value ?? "").trim();
  return result || null;
}

export function summarizeP0Revision(
  row: PersistedP0RevisionRow,
  currentRevision: number,
): P0RevisionSummary {
  const state = record(JSON.parse(row.value_json));
  const strategy = record(state.strategy);
  const recommendationSet = record(state.recommendation_set);
  const draft = record(state.draft);
  const campaign = record(state.campaign);
  return {
    revision: Number(row.revision),
    updated_at: String(row.updated_at),
    status: Number(row.revision) === currentRevision ? "CURRENT" : "SUPERSEDED",
    strategy_revision_id: optionalText(strategy.strategy_revision_id),
    recommendation_set_id: optionalText(recommendationSet.recommendation_set_id),
    draft_id: optionalText(draft.draft_id),
    draft_revision_id: optionalText(draft.draft_revision_id),
    publish_fingerprint: optionalText(draft.publish_fingerprint),
    campaign_id: optionalText(campaign.campaign_id),
    campaign_state: optionalText(campaign.campaign_state),
  };
}
