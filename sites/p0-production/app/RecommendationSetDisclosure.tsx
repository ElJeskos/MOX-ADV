/* eslint-disable @typescript-eslint/no-explicit-any -- Recommendation Set is validated by the application contract. */

export function RecommendationSetDisclosure({ recommendationSet }: { recommendationSet: Record<string, any> }) {
  const candidateAudit = Array.isArray(recommendationSet.candidate_audit) ? recommendationSet.candidate_audit : [];
  const hiddenAudit = candidateAudit.filter((item: Record<string, any>) => item.visibility === "HIDDEN");
  const coverage = recommendationSet.coverage || {};
  const profile = recommendationSet.capability_profile || {};
  const playbook = recommendationSet.playbook_release || {};
  return <>
    <div className="context-strip">
      <div><span>Покрытие</span><strong>{coverage.generated_count ?? candidateAudit.length} generated</strong><small>{coverage.visible_count ?? 0} visible · {coverage.hidden_count ?? hiddenAudit.length} hidden · reconciliation {coverage.reconciliation?.generated_equals_visible_plus_hidden ? "OK" : "BLOCKED"}</small></div>
      <div><span>Direct-профиль</span><strong>Unified · Search</strong><small>{profile.profile_id || "—"}@{profile.profile_version || "—"} · {profile.search_strategy || "WB_MAXIMUM_CLICKS"} · Network {profile.network_strategy || "SERVING_OFF"}</small></div>
      <div><span>Безопасный финиш</span><strong>Только SUSPENDED</strong><small>Явный suspend подтверждается до дочерних записей</small></div>
    </div>
    <section className="recommendation-governance" aria-label="Capability и curated playbook Recommendation Set">
      <div><strong>Curated playbook</strong><code>{playbook.release_id || "BLOCKED_FAIL_CLOSED"}@{playbook.release_version || "—"}</code><small>{playbook.status} · {String(playbook.content_digest || "no digest").slice(0, 28)}…</small></div>
      <div><strong>Direct capability</strong><code>{profile.campaign_type} · {profile.ad_group_type} · {profile.criteria?.join("+")} · {profile.ad_type}</code><small>v501 exact account snapshot {recommendationSet.direct_capability_snapshot_id || "MISSING"} · Product Gallery OFF · Network SERVING_OFF</small></div>
    </section>
    {hiddenAudit.length > 0 && <details className="hidden-drafts"><summary>Hidden candidate audit · {hiddenAudit.length}</summary><ul>{hiddenAudit.map((item: Record<string, any>) => <li key={item.candidate_id}><strong>{item.candidate_type}{item.playbook_rule_id ? ` · ${item.playbook_rule_id}` : ""}</strong><span>{item.reason_code}{item.draft_id ? ` · ${item.draft_id}` : ""}</span></li>)}</ul></details>}
  </>;
}

export function DraftVariantLabel({ draft }: { draft: Record<string, any> }) {
  const label = draft.variant?.kind === "CONTROL"
    ? draft.variant?.control_basis?.kind
    : `IMPROVEMENT · ${draft.treatment_delta?.changed_family}`;
  return <b>{label}</b>;
}

export function DraftTreatmentDelta({ draft }: { draft: Record<string, any> }) {
  if (!draft.treatment_delta) return null;
  return <small>One-factor delta: {draft.treatment_delta.changed_fields?.join(" · ")}</small>;
}

export function DraftPublicationBlockers({ draft }: { draft: Record<string, any> }) {
  const blockers = Array.isArray(draft.publication_blockers) ? draft.publication_blockers : [];
  if (!blockers.length) return null;
  return <section className="wide viability-summary blocked" aria-label="Publication blockers">
    <strong>Publication заблокирована</strong>
    <ul>{blockers.map((item: Record<string, any>) => <li key={`${item.code}-${item.field_path || "draft"}`}>{item.code}: {item.message}{item.field_path ? ` · ${item.field_path}` : ""}</li>)}</ul>
  </section>;
}
