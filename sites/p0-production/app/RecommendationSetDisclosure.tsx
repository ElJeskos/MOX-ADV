/* eslint-disable @typescript-eslint/no-explicit-any -- Recommendation Set is validated by the application contract. */
import { projectionFieldValue } from "../lib/campaign-draft-fields.ts";
import { classificationLabel, fieldRegistryLabel, fieldRegistryReason, localizedText, machineLabel, yesNoLabel } from "./ui-copy.ts";

const changedFamilyLabels: Record<string, string> = {
  AUDIENCE_SPECIFICITY: "точность аудитории",
  CRITERIA_AUTOTARGETING: "автотаргетинг",
  EXTENSION: "расширение",
  MESSAGE_OFFER: "сообщение и предложение",
  PLACEMENT: "место показа",
  QUALIFIED_ACTION: "целевое действие",
};

export function RecommendationSetDisclosure({ recommendationSet }: { recommendationSet: Record<string, any> }) {
  const candidateAudit = Array.isArray(recommendationSet.candidate_audit) ? recommendationSet.candidate_audit : [];
  const hiddenAudit = candidateAudit.filter((item: Record<string, any>) => item.visibility === "HIDDEN");
  const coverage = recommendationSet.coverage || {};
  const profile = recommendationSet.capability_profile || {};
  const playbook = recommendationSet.playbook_release || {};
  const scoreContract = recommendationSet.score_contract || {};
  return <>
    <div className="context-strip">
      <div><span>Покрытие</span><strong>{coverage.generated_count ?? candidateAudit.length} создано</strong><small>{coverage.visible_count ?? 0} видимых · {coverage.hidden_count ?? hiddenAudit.length} скрытых · сверка {coverage.reconciliation?.generated_equals_visible_plus_hidden ? "успешна" : "заблокирована"}</small></div>
      <div><span>Профиль Яндекс Директа</span><strong>Единая кампания · Поиск</strong><small>{profile.profile_id || "—"}@{profile.profile_version || "—"} · стратегия поиска {profile.search_strategy || "не указана"} · стратегия сетей {machineLabel(profile.network_strategy, "показы отключены")}</small></div>
      <div><span>Безопасный финиш</span><strong>Только остановленная кампания</strong><small>Явная остановка подтверждается до дочерних записей</small></div>
    </div>
    <section className="recommendation-governance" aria-label="Возможности и свод правил набора рекомендаций">
      <div><strong>Проверенная сводка правил</strong><code>{playbook.release_id || "безопасно заблокировано"}@{playbook.release_version || "—"}</code><small>{machineLabel(playbook.status)} · {String(playbook.content_digest || "отпечаток отсутствует").slice(0, 28)}…</small></div>
      <div><strong>Возможности Яндекс Директа</strong><code>{profile.campaign_type} · {profile.ad_group_type} · {profile.criteria?.join("+")} · {profile.ad_type}</code><small>Точный снимок аккаунта API v501: {recommendationSet.direct_capability_snapshot_id || "отсутствует"} · товарная галерея отключена · сети отключены</small></div>
      <div><strong>Правила сравнительной оценки</strong><code>{scoreContract.version || "viability-score/1.0.0"}</code><small>18 спрос · 12 стоимость · 20 экономика · 18 соответствие · 12 Директ · 10 измерение · 10 доказательства = 100% · середина для неизвестного 50</small></div>
    </section>
    {hiddenAudit.length > 0 && <details className="hidden-drafts"><summary>Проверка скрытых кандидатов · {hiddenAudit.length}</summary><ul>{hiddenAudit.map((item: Record<string, any>) => <li key={item.candidate_id}><strong>{machineLabel(item.candidate_type)}{item.playbook_rule_id ? ` · ${item.playbook_rule_id}` : ""}</strong><span>{item.reason_code}{item.draft_id ? ` · ${item.draft_id}` : ""}</span></li>)}</ul></details>}
  </>;
}

export function DraftVariantLabel({ draft }: { draft: Record<string, any> }) {
  const label = draft.variant?.kind === "CONTROL"
    ? `Контрольный вариант · ${machineLabel(draft.variant?.control_basis?.kind)}`
    : `Улучшение · ${changedFamilyLabels[draft.treatment_delta?.changed_family] || machineLabel(draft.treatment_delta?.changed_family)}`;
  return <b>{label}</b>;
}

export function DraftTreatmentDelta({ draft }: { draft: Record<string, any> }) {
  if (!draft.treatment_delta) return null;
  return <small>Изменение одного фактора: {draft.treatment_delta.changed_fields?.join(" · ")}</small>;
}

function displayValue(value: unknown) {
  if (value === undefined) return "отсутствует";
  if (value === null) return "пусто";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export function CampaignDraftCard({ draft, selected = false }: { draft: Record<string, any>; selected?: boolean }) {
  const score = draft.viability_score || {};
  const frequency = score.scopes?.frequency || {};
  const cost = score.scopes?.cost || {};
  const blockers = Array.isArray(draft.publication_blockers) ? draft.publication_blockers : [];
  const evidenceQuality = score.dimensions?.evidence_quality?.value ?? score.visibility?.gates?.evidence_quality ?? "неизвестно";
  const tied = Array.isArray(score.tied_draft_ids) && score.tied_draft_ids.length > 1;
  const costRange = cost.range?.low !== null && cost.range?.low !== undefined
    ? `${cost.range.low}–${cost.range.high} ${cost.currency || ""}`.trim() : "диапазон недоступен";
  return <div className={`campaign-draft-card ${selected ? "selected" : ""} ${draft.visibility === "HIDDEN" ? "hidden" : ""}`} data-draft-id={draft.draft_id}>
    <header><DraftVariantLabel draft={draft} /><em>Сравнительная оценка {score.score ?? "—"}/100</em></header>
    <strong>{draft.dimensions?.keyword_cluster || draft.campaign_name}</strong>
    <p>{draft.dimensions?.offer || draft.ad_text}</p>
    <dl>
      <div><dt>Место</dt><dd>{score.rank ? `Смысловое место ${score.rank}${tied ? " · равенство" : ""}` : "Место не присвоено"}</dd></div>
      <div><dt>Чувствительность</dt><dd>{score.score_lower !== null && score.score_lower !== undefined ? `Диапазон ${score.score_lower}–${score.score_upper}` : "Заблокировано до оценки"}</dd></div>
      <div><dt>Доказательства</dt><dd>{machineLabel(draft.market_evidence_status, "Недоступно")} · качество {evidenceQuality}</dd></div>
      <div><dt>Частотность</dt><dd>{frequency.observed_unique_count ?? "неизвестно"} · {frequency.source || "источник недоступен"}<small>{[frequency.method, frequency.snapshot_batch_id, frequency.declared_window].filter(Boolean).join(" · ")}</small></dd></div>
      <div><dt>Стоимость</dt><dd>{machineLabel(cost.status, "Недоступно")} · {cost.source || "источник недоступен"}<small>{costRange} · {[cost.scenario, cost.as_of, cost.vat_treatment].filter(Boolean).join(" · ")}</small></dd></div>
    </dl>
    <footer><span>Проверка: доступна</span><strong>Публикация: {machineLabel(draft.publish_eligibility, "Заблокировано")}</strong><b>Блокирующие причины · {blockers.length}</b></footer>
    {blockers.length > 0 && <small>{blockers.map((item: Record<string, any>) => item.code).join(" · ")}</small>}
    {draft.visibility === "HIDDEN" && <small>Причина скрытия: {localizedText(draft.suppression_reason || "Сохранённая причина отсутствует · безопасно заблокировано")}</small>}
  </div>;
}

export function DraftFieldRegistryDisclosure({ registry, draft, titleId = "draft-field-registry-title" }: { registry: Record<string, any>; draft: Record<string, any>; titleId?: string }) {
  const fields = Array.isArray(registry?.fields) ? registry.fields : [];
  return <section className="draft-field-registry" aria-labelledby={titleId}>
    <header><div><p className="eyebrow">ТОЧНАЯ ПРОЕКЦИЯ ЯНДЕКС ДИРЕКТА API v501</p><h3 id={titleId}>Поддерживаемые поля публикации</h3></div><code>{registry?.profile_id}@{registry?.profile_version}</code></header>
    <p>Редактируемые значения проходят полный цикл через сервер. Поля, зафиксированные стратегией или возможностями аккаунта, а также условно отсутствующие поля доступны только для проверки и никогда не отбрасываются молча.</p>
    <div>{fields.map((field: Record<string, any>) => {
      const projectionValue = projectionFieldValue(draft.publish_projection, field.pointer);
      const editableValue = field.input_name ? draft[field.input_name] : projectionValue;
      return <label key={field.pointer} data-direct-field={field.pointer} data-editable={String(field.editable === true)}>
        <span><strong>{fieldRegistryLabel(field.label)}</strong><code>{field.pointer}</code></span>
        <small>{classificationLabel(field.classification)}{field.presence === "NOT_PRESENT" ? " · отсутствует" : ""}</small>
        {field.editable === true
          ? field.input_name === "ad_text"
            ? <textarea name={field.input_name} required maxLength={field.maximum_length || undefined} defaultValue={displayValue(editableValue)} />
            : <input name={field.input_name} required maxLength={field.maximum_length || undefined} defaultValue={displayValue(editableValue)} />
          : <output>{displayValue(projectionValue)}</output>}
        <em>{fieldRegistryReason(field.reason)}</em>
      </label>;
    })}</div>
  </section>;
}

export function DraftEditFeedback({ draft }: { draft: Record<string, any> }) {
  const save = draft.draft_save_result;
  if (!save) return null;
  if (save.material_change !== true) return <section className="draft-edit-feedback no-change" role="status"><strong>{localizedText(save.message)}</strong></section>;
  const material = draft.material_delta || {};
  const score = draft.score_delta || {};
  return <section className="draft-edit-feedback material" role="status">
    <header><strong>{localizedText(save.message)}</strong><span>Оценка {score.score?.previous ?? "—"} → {score.score?.current ?? "—"} · место {score.rank?.previous ?? "—"} → {score.rank?.current ?? "—"}</span></header>
    <p><b>{material.policy_reason?.code}</b> · {localizedText(material.policy_reason?.message)}</p>
    <ul>{(material.fields || []).map((field: Record<string, any>) => <li key={field.pointer}><code>{field.pointer}</code><span>{displayValue(field.previous_normalized_value)} → {displayValue(field.current_normalized_value)}</span></li>)}</ul>
    <details><summary>Изменения вкладов измерений</summary><ul>{Object.entries(score.dimensions || {}).map(([name, value]) => <li key={name}><b>{viabilityDimensionLabels[name] || name}</b><span>{String((value as Record<string, any>).delta ?? "заблокировано")}</span></li>)}</ul></details>
  </section>;
}

export function DraftPublicationBlockers({ draft }: { draft: Record<string, any> }) {
  const blockers = Array.isArray(draft.publication_blockers) ? draft.publication_blockers : [];
  if (!blockers.length) return null;
  return <section className="wide viability-summary blocked" aria-label="Причины блокировки публикации">
    <strong>Публикация заблокирована</strong>
    <ul>{blockers.map((item: Record<string, any>) => <li key={`${item.code}-${item.field_path || "draft"}`}>{item.code}: {localizedText(item.message)}{item.field_path ? ` · ${item.field_path}` : ""}</li>)}</ul>
  </section>;
}

const viabilityDimensionLabels: Record<string, string> = {
  demand: "Спрос",
  cost: "Стоимость",
  economics: "Экономика",
  offer_audience_fit: "Соответствие предложения аудитории",
  direct_feasibility: "Реализуемость в Яндекс Директе",
  measurement_readiness: "Готовность измерения",
  evidence_quality: "Качество доказательств",
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
  ].filter(Boolean).join(" · ") || "охват недоступен";
  const costScope = [
    cost.source,
    cost.scenario,
    cost.currency,
    cost.vat_treatment,
    cost.as_of,
    cost.sample_size ? JSON.stringify(cost.sample_size) : null,
    cost.scope ? JSON.stringify(cost.scope) : null,
  ].filter(Boolean).join(" · ") || "подходящий источник недоступен";
  return <div className="score-scopes">
    <p><strong>Охват частотности</strong> {machineLabel(frequency.status, "Недоступно")} · {frequency.semantics === "UNAVAILABLE_NOT_ZERO" ? "недоступно, но не равно нулю" : frequency.semantics === "LOWER_BOUND_OBSERVED_TOP_ROWS" ? "нижняя граница по наблюдаемым популярным запросам" : frequency.semantics || "смысл не указан"} · {frequency.observed_unique_count ?? "неизвестно"} · {frequencyScope}</p>
    <p><strong>Охват стоимости</strong> {machineLabel(cost.status, "Недоступно")} · {String(cost.semantics || "").includes("NOT_AVERAGED") ? "один подходящий источник, без усреднения" : cost.semantics || "смысл не указан"} · {costScope}</p>
  </div>;
}

export function ViabilityScoreDisclosure({ score, delta }: { score: Record<string, any> | undefined; delta?: Record<string, any> }) {
  if (!score) return <section className="wide viability-summary blocked"><strong>Правила сравнительной оценки отсутствуют</strong></section>;
  const blockers = Array.isArray(score.eligibility?.blockers) ? score.eligibility.blockers : [];
  const requiredGaps = Array.isArray(score.evidence_gaps?.required) ? score.evidence_gaps.required : [];
  const optionalGaps = Array.isArray(score.evidence_gaps?.optional) ? score.evidence_gaps.optional : [];
  const dimensions = Object.entries(score.dimensions || {}) as Array<[string, Record<string, any>]>;
  const deltaValue = delta?.score?.delta;
  const ranking = score.ranking || {};
  const visibility = score.visibility || {};
  const gates = visibility.gates || {};
  if (score.score === null || score.score === undefined) {
    return <section className="wide viability-summary blocked" aria-label="Сравнительная оценка жизнеспособности заблокирована">
      <header><div><p className="eyebrow">НЕКАЛИБРОВАННЫЕ ПРАВИЛА V1</p><h3>СРАВНИТЕЛЬНЫЙ ПРИОРИТЕТ ДО ЗАПУСКА · НЕ ПРОГНОЗ</h3></div><em>{machineLabel(score.eligibility?.status, "Заблокировано")}</em></header>
      <p>Жёсткая допустимость и обязательные пробелы в доказательствах оцениваются до балла. Блокирующую причину нельзя усреднить, обойти высоким баллом, добавить в список или скрыть правилом оценки.</p>
      {blockers.length > 0 && <section><strong>Жёсткие блокирующие причины</strong><ul>{blockers.map((item: Record<string, any>) => <li key={`${item.code}-${item.input_pointer}`}>{item.code}: {localizedText(item.remediation)} · {item.input_pointer}</li>)}</ul></section>}
      {requiredGaps.length > 0 && <section><strong>Неразрешённые обязательные пробелы в доказательствах</strong><ul>{requiredGaps.map((item: Record<string, any>) => <li key={`${item.code}-${item.input_pointer}`}>{item.code}: {localizedText(item.description)} · {item.input_pointer}</li>)}</ul></section>}
      {scoreScopeLine(score)}
      <footer><code>{score.contract_version}</code><span>{ranking.cohort_id}</span><span>место отсутствует · {machineLabel(ranking.status)}</span></footer>
    </section>;
  }
  return <section className="wide viability-summary" aria-labelledby="viability-score-title">
    <header><div><p className="eyebrow">СРАВНИТЕЛЬНЫЙ ПРИОРИТЕТ ДО ЗАПУСКА · НЕ ПРОГНОЗ</p><h3 id="viability-score-title"><strong>{score.score}</strong><span>/100</span></h3></div><div><b>Место {score.rank}{score.tied_draft_ids?.length > 1 ? " · смысловое равенство" : ""}</b><small>Чувствительность {score.score_lower}–{score.score_upper}</small></div><em>Не прогноз эффективности</em></header>
    <p>Детерминированный сравнительный приоритет до запуска действует только для точного набора рекомендаций и сопоставимой группы возможностей. Рекомендации по посадочной странице, результаты после запуска и калибровка не участвуют.</p>
    <div className="ranking-lineage"><strong>{ranking.cohort_id}</strong><span>{ranking.comparable_set_id}</span><small>{ranking.recommendation_set_id} · устойчивый ID влияет только на порядок отображения</small></div>
    {typeof deltaValue === "number" && <div className="score-delta"><strong>После ручной правки: {deltaValue > 0 ? "+" : ""}{deltaValue} балл.</strong><span>Полный пересчёт на тех же зафиксированных входах правил.</span></div>}
    <div className="viability-bars">{dimensions.map(([name, item]) => <div key={name}><span>{viabilityDimensionLabels[name] || name}</span><i><b style={{ width: `${Math.max(0, Math.min(100, Number(item.value || 0)))}%` }} /></i><strong>{Math.round(Number(item.value || 0))}</strong><small>{item.weight_percent}% · {Number(item.weighted_contribution || 0).toFixed(2)} балла · {machineLabel(item.state)}</small></div>)}</div>
    {scoreScopeLine(score)}
    <details><summary>Вклады, указатели доказательств, середина для неизвестного и чувствительность</summary><div className="viability-detail">
      <p><strong>Чувствительность:</strong> неизвестные измерения: {score.sensitivity?.unknown_dimensions?.length ? score.sensitivity.unknown_dimensions.map((name: string) => viabilityDimensionLabels[name] || name).join(" · ") : "нет"}; середина 50; нижняя граница пересчитывает неизвестные измерения как 0, верхняя — как 100; известные измерения остаются неизменными.</p>
      {optionalGaps.length > 0 && <p><strong>Необязательные недоступные входы:</strong> {optionalGaps.map((item: Record<string, any>) => item.code).join(" · ")}. Они не считаются выдуманными доказательствами.</p>}
      {dimensions.map(([name, item]) => <section key={name}><strong>{viabilityDimensionLabels[name] || name} · исходное значение {item.value} · вес {item.weight_percent}% → {Number(item.weighted_contribution || 0).toFixed(2)} балла · {machineLabel(item.state)}</strong>
        <ul>{(item.features || []).map((feature: Record<string, any>, index: number) => <li key={`${name}-${feature.rule}-${index}`}><span>{feature.rule} · {feature.input_pointers?.join(" · ")} · утверждения {feature.claim_ids?.join(", ") || "нет"} · доказательства {feature.evidence_ids?.join(", ") || "нет"}</span><b>{feature.value} · {machineLabel(feature.status)}{feature.midpoint_applied ? " · середина 50" : ""}</b></li>)}</ul>
      </section>)}
    </div></details>
    <section className="score-threshold"><strong>Решение о видимости · {machineLabel(visibility.reason, "Доступно для проверки")}</strong><p>{machineLabel(visibility.decision)} · верхняя граница {gates.sensitivity_upper} &lt; 45: {yesNoLabel(gates.upper_below_threshold)} · качество доказательств {gates.evidence_quality} ≥ 60: {yesNoLabel(gates.evidence_quality_sufficient)} · неразрешённый пробел: {yesNoLabel(gates.unresolved_evidence_gap)} · структурная причина: {gates.structural_reason || "нет"}</p></section>
    <footer><code>{score.contract_version}</code><span>{String(score.fingerprints?.input || "").slice(0, 24)}…</span><span>посадочная страница = нет · после запуска = нет · калибровка = нет</span></footer>
  </section>;
}
