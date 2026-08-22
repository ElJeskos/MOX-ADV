/* eslint-disable @typescript-eslint/no-explicit-any -- Recommendation Set is validated by the application contract. */
import { projectionFieldValue } from "../lib/campaign-draft-fields.ts";

export function RecommendationSetDisclosure({ recommendationSet }: { recommendationSet: Record<string, any> }) {
  const candidateAudit = Array.isArray(recommendationSet.candidate_audit) ? recommendationSet.candidate_audit : [];
  const hiddenAudit = candidateAudit.filter((item: Record<string, any>) => item.visibility === "HIDDEN");
  const coverage = recommendationSet.coverage || {};
  const profile = recommendationSet.capability_profile || {};
  const playbook = recommendationSet.playbook_release || {};
  const scoreContract = recommendationSet.score_contract || {};
  return <>
    <div className="context-strip">
      <div><span>Покрытие</span><strong>{coverage.generated_count ?? candidateAudit.length} generated</strong><small>{coverage.visible_count ?? 0} visible · {coverage.hidden_count ?? hiddenAudit.length} hidden · reconciliation {coverage.reconciliation?.generated_equals_visible_plus_hidden ? "OK" : "BLOCKED"}</small></div>
      <div><span>Direct-профиль</span><strong>Unified · Search</strong><small>{profile.profile_id || "—"}@{profile.profile_version || "—"} · {profile.search_strategy || "WB_MAXIMUM_CLICKS"} · Network {profile.network_strategy || "SERVING_OFF"}</small></div>
      <div><span>Безопасный финиш</span><strong>Только SUSPENDED</strong><small>Явный suspend подтверждается до дочерних записей</small></div>
    </div>
    <section className="recommendation-governance" aria-label="Capability и curated playbook Recommendation Set">
      <div><strong>Curated playbook</strong><code>{playbook.release_id || "BLOCKED_FAIL_CLOSED"}@{playbook.release_version || "—"}</code><small>{playbook.status} · {String(playbook.content_digest || "no digest").slice(0, 28)}…</small></div>
      <div><strong>Direct capability</strong><code>{profile.campaign_type} · {profile.ad_group_type} · {profile.criteria?.join("+")} · {profile.ad_type}</code><small>v501 exact account snapshot {recommendationSet.direct_capability_snapshot_id || "MISSING"} · Product Gallery OFF · Network SERVING_OFF</small></div>
      <div><strong>Comparative score contract</strong><code>{scoreContract.version || "viability-score/1.0.0"}</code><small>18 demand · 12 cost · 20 economics · 18 fit · 12 Direct · 10 measurement · 10 evidence = 100% · unknown midpoint 50</small></div>
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

function displayValue(value: unknown) {
  if (value === undefined) return "NOT_PRESENT";
  if (value === null) return "null";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export function CampaignDraftCard({ draft, selected = false }: { draft: Record<string, any>; selected?: boolean }) {
  const score = draft.viability_score || {};
  const frequency = score.scopes?.frequency || {};
  const cost = score.scopes?.cost || {};
  const blockers = Array.isArray(draft.publication_blockers) ? draft.publication_blockers : [];
  const evidenceQuality = score.dimensions?.evidence_quality?.value ?? score.visibility?.gates?.evidence_quality ?? "unknown";
  const tied = Array.isArray(score.tied_draft_ids) && score.tied_draft_ids.length > 1;
  const costRange = cost.range?.low !== null && cost.range?.low !== undefined
    ? `${cost.range.low}–${cost.range.high} ${cost.currency || ""}`.trim() : "range unavailable";
  return <div className={`campaign-draft-card ${selected ? "selected" : ""} ${draft.visibility === "HIDDEN" ? "hidden" : ""}`} data-draft-id={draft.draft_id}>
    <header><DraftVariantLabel draft={draft} /><em>Comparative {score.score ?? "—"}/100</em></header>
    <strong>{draft.dimensions?.keyword_cluster || draft.campaign_name}</strong>
    <p>{draft.dimensions?.offer || draft.ad_text}</p>
    <dl>
      <div><dt>Rank</dt><dd>{score.rank ? `Semantic rank ${score.rank}${tied ? " · tie" : ""}` : "Not ranked"}</dd></div>
      <div><dt>Sensitivity</dt><dd>{score.score_lower !== null && score.score_lower !== undefined ? `Sensitivity ${score.score_lower}–${score.score_upper}` : "Blocked before score"}</dd></div>
      <div><dt>Evidence</dt><dd>Evidence {draft.market_evidence_status || "UNAVAILABLE"} · quality {evidenceQuality}</dd></div>
      <div><dt>Frequency</dt><dd>Frequency {frequency.observed_unique_count ?? "unknown"} · {frequency.source || "source unavailable"}<small>{[frequency.method, frequency.snapshot_batch_id, frequency.declared_window].filter(Boolean).join(" · ")}</small></dd></div>
      <div><dt>Cost</dt><dd>Cost {cost.status || "UNAVAILABLE"} · {cost.source || "source unavailable"}<small>{costRange} · {[cost.scenario, cost.as_of, cost.vat_treatment].filter(Boolean).join(" · ")}</small></dd></div>
    </dl>
    <footer><span>Review: доступен</span><strong>Publish: {draft.publish_eligibility || "BLOCKED"}</strong><b>Publish blockers · {blockers.length}</b></footer>
    {blockers.length > 0 && <small>{blockers.map((item: Record<string, any>) => item.code).join(" · ")}</small>}
    {draft.visibility === "HIDDEN" && <small>Suppression: {draft.suppression_reason || "Persisted suppression reason missing · FAIL CLOSED"}</small>}
  </div>;
}

export function DraftFieldRegistryDisclosure({ registry, draft, titleId = "draft-field-registry-title" }: { registry: Record<string, any>; draft: Record<string, any>; titleId?: string }) {
  const fields = Array.isArray(registry?.fields) ? registry.fields : [];
  return <section className="draft-field-registry" aria-labelledby={titleId}>
    <header><div><p className="eyebrow">EXACT DIRECT v501 PROJECTION</p><h3 id={titleId}>Поддерживаемые publishable fields</h3></div><code>{registry?.profile_id}@{registry?.profile_version}</code></header>
    <p>Editable controls round-trip server-side. Strategy/capability fixed and conditionally absent fields are review-only and are never silently dropped.</p>
    <div>{fields.map((field: Record<string, any>) => {
      const projectionValue = projectionFieldValue(draft.publish_projection, field.pointer);
      const editableValue = field.input_name ? draft[field.input_name] : projectionValue;
      return <label key={field.pointer} data-direct-field={field.pointer} data-editable={String(field.editable === true)}>
        <span><strong>{field.label}</strong><code>{field.pointer}</code></span>
        <small>{field.classification}{field.presence === "NOT_PRESENT" ? " · NOT_PRESENT" : ""}</small>
        {field.editable === true
          ? field.input_name === "ad_text"
            ? <textarea name={field.input_name} required maxLength={field.maximum_length || undefined} defaultValue={displayValue(editableValue)} />
            : <input name={field.input_name} required maxLength={field.maximum_length || undefined} defaultValue={displayValue(editableValue)} />
          : <output>{displayValue(projectionValue)}</output>}
        <em>{field.reason}</em>
      </label>;
    })}</div>
  </section>;
}

export function DraftEditFeedback({ draft }: { draft: Record<string, any> }) {
  const save = draft.draft_save_result;
  if (!save) return null;
  if (save.material_change !== true) return <section className="draft-edit-feedback no-change" role="status"><strong>{save.message}</strong></section>;
  const material = draft.material_delta || {};
  const score = draft.score_delta || {};
  return <section className="draft-edit-feedback material" role="status">
    <header><strong>{save.message}</strong><span>Score {score.score?.previous ?? "—"} → {score.score?.current ?? "—"} · rank {score.rank?.previous ?? "—"} → {score.rank?.current ?? "—"}</span></header>
    <p><b>{material.policy_reason?.code}</b> · {material.policy_reason?.message}</p>
    <ul>{(material.fields || []).map((field: Record<string, any>) => <li key={field.pointer}><code>{field.pointer}</code><span>{displayValue(field.previous_normalized_value)} → {displayValue(field.current_normalized_value)}</span></li>)}</ul>
    <details><summary>Dimension contribution deltas</summary><ul>{Object.entries(score.dimensions || {}).map(([name, value]) => <li key={name}><b>{name}</b><span>{String((value as Record<string, any>).delta ?? "blocked")}</span></li>)}</ul></details>
  </section>;
}

export function DraftPublicationBlockers({ draft }: { draft: Record<string, any> }) {
  const blockers = Array.isArray(draft.publication_blockers) ? draft.publication_blockers : [];
  if (!blockers.length) return null;
  return <section className="wide viability-summary blocked" aria-label="Publication blockers">
    <strong>Publication заблокирована</strong>
    <ul>{blockers.map((item: Record<string, any>) => <li key={`${item.code}-${item.field_path || "draft"}`}>{item.code}: {item.message}{item.field_path ? ` · ${item.field_path}` : ""}</li>)}</ul>
  </section>;
}

const viabilityDimensionLabels: Record<string, string> = {
  demand: "Спрос",
  cost: "Стоимость",
  economics: "Экономика",
  offer_audience_fit: "Offer–audience fit",
  direct_feasibility: "Direct feasibility",
  measurement_readiness: "Measurement readiness",
  evidence_quality: "Evidence quality",
};

function scoreScopeLine(score: Record<string, any>) {
  const frequency = score.scopes?.frequency || {};
  const cost = score.scopes?.cost || {};
  const frequencyScope = [
    frequency.source,
    frequency.method,
    frequency.snapshot_batch_id,
    frequency.operator_profiles?.join("+"),
    frequency.region_ids?.join("+"),
    frequency.devices?.join("+"),
    frequency.declared_window,
  ].filter(Boolean).join(" · ") || "scope unavailable";
  const costScope = [
    cost.source,
    cost.scenario,
    cost.currency,
    cost.vat_treatment,
    cost.as_of,
    cost.sample_size ? JSON.stringify(cost.sample_size) : null,
    cost.scope ? JSON.stringify(cost.scope) : null,
  ].filter(Boolean).join(" · ") || "qualified source unavailable";
  return <div className="score-scopes">
    <p><strong>Frequency scope</strong> {frequency.status || "UNAVAILABLE"} · {frequency.semantics || "UNAVAILABLE_NOT_ZERO"} · {frequency.observed_unique_count ?? "unknown"} · {frequencyScope}</p>
    <p><strong>Cost scope</strong> {cost.status || "UNAVAILABLE"} · {cost.semantics || "ONE QUALIFIED SOURCE; NOT AVERAGED"} · {costScope}</p>
  </div>;
}

export function ViabilityScoreDisclosure({ score, delta }: { score: Record<string, any> | undefined; delta?: Record<string, any> }) {
  if (!score) return <section className="wide viability-summary blocked"><strong>Comparative score contract отсутствует</strong></section>;
  const blockers = Array.isArray(score.eligibility?.blockers) ? score.eligibility.blockers : [];
  const requiredGaps = Array.isArray(score.evidence_gaps?.required) ? score.evidence_gaps.required : [];
  const optionalGaps = Array.isArray(score.evidence_gaps?.optional) ? score.evidence_gaps.optional : [];
  const dimensions = Object.entries(score.dimensions || {}) as Array<[string, Record<string, any>]>;
  const deltaValue = delta?.score?.delta;
  const ranking = score.ranking || {};
  const visibility = score.visibility || {};
  const gates = visibility.gates || {};
  if (score.score === null || score.score === undefined) {
    return <section className="wide viability-summary blocked" aria-label="Comparative viability score blocked">
      <header><div><p className="eyebrow">UNCALIBRATED POLICY V1</p><h3>COMPARATIVE PRELAUNCH PRIORITY / NOT A PREDICTION</h3></div><em>{score.eligibility?.status || "BLOCKED"}</em></header>
      <p>Hard eligibility и required EVIDENCE_GAP оценены до score. Blocker нельзя усреднить, обойти высоким баллом, добавить в shortlist или скрыть score-правилом.</p>
      {blockers.length > 0 && <section><strong>Hard blockers</strong><ul>{blockers.map((item: Record<string, any>) => <li key={`${item.code}-${item.input_pointer}`}>{item.code}: {item.remediation} · {item.input_pointer}</li>)}</ul></section>}
      {requiredGaps.length > 0 && <section><strong>Unresolved EVIDENCE_GAP</strong><ul>{requiredGaps.map((item: Record<string, any>) => <li key={`${item.code}-${item.input_pointer}`}>{item.code}: {item.description} · {item.input_pointer}</li>)}</ul></section>}
      {scoreScopeLine(score)}
      <footer><code>{score.contract_version}</code><span>{ranking.cohort_id}</span><span>rank отсутствует · {ranking.status}</span></footer>
    </section>;
  }
  return <section className="wide viability-summary" aria-labelledby="viability-score-title">
    <header><div><p className="eyebrow">COMPARATIVE PRELAUNCH PRIORITY / NOT A PREDICTION</p><h3 id="viability-score-title"><strong>{score.score}</strong><span>/100</span></h3></div><div><b>Rank {score.rank}{score.tied_draft_ids?.length > 1 ? " · semantic tie" : ""}</b><small>Sensitivity {score.score_lower}–{score.score_upper}</small></div><em>Не прогноз эффективности</em></header>
    <p>Детерминированный сравнительный pre-launch priority только для exact Recommendation Set и capability cohort. Landing advisory, post-launch outcomes и calibration не участвуют.</p>
    <div className="ranking-lineage"><strong>{ranking.cohort_id}</strong><span>{ranking.comparable_set_id}</span><small>{ranking.recommendation_set_id} · stable ID влияет только на display order</small></div>
    {typeof deltaValue === "number" && <div className="score-delta"><strong>После ручной правки: {deltaValue > 0 ? "+" : ""}{deltaValue} балл.</strong><span>Полный пересчёт на тех же frozen policy inputs.</span></div>}
    <div className="viability-bars">{dimensions.map(([name, item]) => <div key={name}><span>{viabilityDimensionLabels[name] || name}</span><i><b style={{ width: `${Math.max(0, Math.min(100, Number(item.value || 0)))}%` }} /></i><strong>{Math.round(Number(item.value || 0))}</strong><small>{item.weight_percent}% · {Number(item.weighted_contribution || 0).toFixed(2)} pt · {item.state}</small></div>)}</div>
    {scoreScopeLine(score)}
    <details><summary>Contributions, evidence pointers, unknown midpoint и sensitivity</summary><div className="viability-detail">
      <p><strong>Sensitivity:</strong> unknown dimensions {score.sensitivity?.unknown_dimensions?.length ? score.sensitivity.unknown_dimensions.join(" · ") : "нет"}; midpoint 50; lower recomputes unknown dimensions at 0; upper at 100; known dimensions remain fixed.</p>
      {optionalGaps.length > 0 && <p><strong>Optional unavailable inputs:</strong> {optionalGaps.map((item: Record<string, any>) => item.code).join(" · ")}. Они не являются fabricated evidence.</p>}
      {dimensions.map(([name, item]) => <section key={name}><strong>{viabilityDimensionLabels[name] || name} · raw {item.value} · weight {item.weight_percent}% → {Number(item.weighted_contribution || 0).toFixed(2)} points · {item.state}</strong>
        <ul>{(item.features || []).map((feature: Record<string, any>, index: number) => <li key={`${name}-${feature.rule}-${index}`}><span>{feature.rule} · {feature.input_pointers?.join(" · ")} · claims {feature.claim_ids?.join(", ") || "none"} · evidence {feature.evidence_ids?.join(", ") || "none"}</span><b>{feature.value} · {feature.status}{feature.midpoint_applied ? " · midpoint 50" : ""}</b></li>)}</ul>
      </section>)}
    </div></details>
    <section className="score-threshold"><strong>Visibility decision · {visibility.reason || "REVIEW_VISIBLE"}</strong><p>{visibility.decision} · upper {gates.sensitivity_upper} &lt; 45: {String(gates.upper_below_threshold)} · evidence quality {gates.evidence_quality} ≥ 60: {String(gates.evidence_quality_sufficient)} · unresolved gap: {String(gates.unresolved_evidence_gap)} · structural reason: {gates.structural_reason || "none"}</p></section>
    <footer><code>{score.contract_version}</code><span>{String(score.fingerprints?.input || "").slice(0, 24)}…</span><span>landing=false · post-launch=false · calibration=false</span></footer>
  </section>;
}
