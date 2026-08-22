"use client";

/* eslint-disable @typescript-eslint/no-explicit-any -- API payloads are validated server-side and intentionally revisioned. */
import Link from "next/link";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  filterAndSortCampaignDrafts,
  type CampaignCanvasFilters,
  type CampaignEvidenceStatus,
} from "../lib/campaign-canvas";
import { weeklyBudgetValidationMessage } from "../lib/direct-limits";
import { landingAdvisoryPriorities } from "../lib/landing-advisory";
import { MarketEvidenceDisclosure } from "./MarketEvidenceDisclosure";
import {
  CampaignDraftCard,
  DraftEditFeedback,
  DraftFieldRegistryDisclosure,
  DraftPublicationBlockers,
  RecommendationSetDisclosure,
  ViabilityScoreDisclosure,
} from "./RecommendationSetDisclosure";

type Payload = {
  contract: { name: string; version: string; document_schema: string };
  revision: number;
  updated_at: string;
  state: Record<string, any>;
  workflow: {
    steps: Array<{ id: string; label: string; detail: string }>;
    current_step: number;
    maximum_reachable_step: number;
    allowed_commands: string[];
  };
  context: Record<string, any>;
  context_preflight: { ready: boolean; blockers: string[]; maximum_age_ms: number };
  context_change_policy: {
    affected_steps: Array<{ id: string; label: string }>;
    normalization_only_changes_invalidate: boolean;
    confirmation_requires_recomputation: boolean;
  };
  shortlist_controls: Array<{ draft_id: string; status: "SELECTED" | "REMOVED" | "AVAILABLE" | "BLOCKED"; disabled_reason: string | null }>;
  decision_readiness: { ready: boolean; blockers: string[]; confirmed: boolean; independent_execution: true; external_writes_performed: boolean };
  revision_history?: Array<Record<string, any>>;
  write_readiness: { ready: boolean; blockers: string[] };
};

async function request(path: string, init?: RequestInit) {
  const response = await fetch(path, init);
  const value = (await response.json()) as Record<string, any>;
  if (!response.ok) throw new Error(String(value.error || `HTTP ${response.status}`));
  return value;
}

function fieldValue(form: HTMLFormElement, name: string) {
  return String(new FormData(form).get(name) || "").trim();
}

function confidenceLabel(value: string) {
  return {
    HIGH: "Высокая уверенность",
    MEDIUM: "Гипотеза агента — проверьте",
    LOW: "Недостаточно данных",
    OWNER_CONFIRMED: "Подтверждено владельцем",
  }[value] || value;
}

export default function P0Client() {
  const [payload, setPayload] = useState<Payload | null>(null);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState("Загружаю реальные подключения…");
  const [error, setError] = useState("");

  useEffect(() => {
    request("/api/p0")
      .then((value) => {
        const next = value as Payload;
        setPayload(next);
        setStep(next.workflow.current_step);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setBusy(""));
  }, []);

  const maxStep = useMemo(
    () => (payload ? Math.max(step, payload.workflow.maximum_reachable_step) : 0),
    [payload, step],
  );

  async function apply(action: string, value?: Record<string, unknown>, extra?: Record<string, unknown>) {
    if (!payload || busy) return;
    setError("");
    setBusy(
      action === "analyze_site"
        ? "Проверяю точные API bindings и исследую безопасный first-party target…"
        : action === "confirm_context_goal"
          ? "Сохраняю решение владельца и начинаю полную аналитику…"
          : action === "dispatch_package"
            ? "Исполняю exact package независимо по каждой кампании…"
            : action === "poll_package_moderation" || action === "poll_package_correction_moderation"
              ? "Проверяю один due moderation item через официальный Direct readback…"
              : action === "resubmit_package_correction"
                ? "Повторно отправляю только новую confirmed correction revision…"
                : "Сохраняю production-ревизию…",
    );
    try {
      const result = await request("/api/p0", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action,
          expected_revision: payload.revision,
          ...(value ? { value } : {}),
          ...extra,
        }),
      });
      const next = { ...payload, ...result } as Payload;
      setPayload(next);
      setStep(action === "recalculate_recommendations" ? 3 : next.workflow.current_step);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy("");
    }
  }

  if (!payload) {
    return (
      <div className="site-shell">
        <header className="topbar">
          <Link className="brand" href="/"><span>M</span>MOX-ADV</Link>
          <nav aria-label="Основная навигация"><Link className="active" href="/">Стратегия</Link><span>Production Module · P0</span></nav>
          <div className="ready"><i />Подключение</div>
        </header>
        <main className="page">
          <section className="hero">
            <div><p className="eyebrow">GPT SITES · PRODUCTION MODULE · P0</p><h1>Стратегия и создание кампании</h1><p>Агент выполняет всю безопасную работу. Человеку остаются критические решения и существенная неопределённость.</p></div>
            <strong className="real-badge">ТОЛЬКО РЕАЛЬНЫЕ ДАННЫЕ</strong>
          </section>
          <section className="loading-product"><strong>Подключаю production-контекст</strong><p>{error || busy}</p></section>
        </main>
      </div>
    );
  }

  const context = payload.context || {};
  const steps = payload.workflow.steps;
  const direct = context.direct || {};
  const metrika = context.metrika || {};
  const performance = context.performance || null;

  return (
    <div className="site-shell">
      <header className="topbar">
        <Link className="brand" href="/"><span>M</span>MOX-ADV</Link>
        <nav aria-label="Основная навигация"><Link className="active" href="/">Стратегия</Link><span>Production Module · P0</span></nav>
        <div className={`ready ${payload.context_preflight.ready ? "" : "blocked"}`}><i />{payload.context_preflight.ready ? "API bindings подтверждены" : "Preflight заблокирован"}</div>
      </header>

      <main className="page">
        <section className="hero">
          <div><p className="eyebrow">GPT SITES · PRODUCTION MODULE · P0</p><h1>Стратегия и создание кампании</h1><p>Агент выполняет всю безопасную работу. Человеку остаются критические решения и существенная неопределённость.</p></div>
          <strong className="real-badge">ТОЛЬКО РЕАЛЬНЫЕ ДАННЫЕ</strong>
        </section>

        <ol className="steps" aria-label="Путь создания кампании">
          {steps.map(({ id, label, detail }, index) => (
            <li key={id}>
              <button disabled={index > maxStep || Boolean(busy)} className={index === step ? "current" : index < payload.workflow.current_step ? "done" : ""} onClick={() => setStep(index)}>
                <span>{index < payload.workflow.current_step ? "✓" : index + 1}</span><div><strong>{label}</strong><small>{detail}</small></div>
              </button>
            </li>
          ))}
        </ol>

        <div className="workspace">
          <aside className="agent-pane">
            <div className="agent-head"><span>AI</span><div><strong>Агент кампании</strong><small>GPT Sites · production-only</small></div></div>
            <section className="agent-message"><strong>{steps[step]?.label}</strong><p>{[
              "Проверяю точные API bindings, исследую безопасный сайт и предлагаю одну provisional бизнес-цель.",
              "Показываю готовую модель с доказательствами и уверенностью.",
              "Готовлю Strategy; владелец задаёт только денежные и временные границы.",
              "Компилирую точную publish projection без молчаливых полей.",
              "Внешняя запись остаётся закрытой, пока production gates не готовы.",
            ][step]}</p></section>
            <section className="connections"><h3>Подключённые данные</h3>
              <Connection label="Яндекс Директ" ready={direct.ready === true} detail={direct.ready ? `${direct.account} · binding подтверждён · ${direct.campaigns_total} кампаний` : direct.blockers?.[0]} />
              <Connection label="Яндекс Метрика" ready={metrika.ready === true} detail={metrika.ready ? `Счётчик ${metrika.counter_id} · цель ${metrika.goal_id} · API` : metrika.blockers?.[0]} />
              <Connection label="Последний реальный срез" ready={Boolean(performance)} detail={performance ? `${performance.period_start} — ${performance.period_end} · ${performance.display_metrics.goal_visits} целей` : "Нет подтверждённого среза"} />
            </section>
            <section className="write-boundary"><span>Human Decision Gate</span><strong>{payload.state.package_execution ? `Package · ${payload.state.package_execution.status}` : payload.decision_readiness.confirmed ? "Authority подтверждена" : payload.state.package_review ? "Пакет reviewed" : "Требует package review"}</strong><small>{payload.state.package_execution ? `${payload.state.package_execution.dispatched_count}/${payload.state.package_execution.selected_count} item executions durable; atomic transaction: NO.` : payload.decision_readiness.confirmed ? "Authority готова к независимому item dispatch." : payload.decision_readiness.blockers[0] || "Точный пакет готов к подтверждению."}</small></section>
          </aside>

          <section className="artifact">
            {payload.state.last_cascade?.recomputation_status === "PENDING" && <div className="recomputation-pending" role="status"><strong>Идёт downstream recomputation</strong><p>Confirmation и все mutations заблокированы. Обновите данные после завершения пересчёта.</p></div>}
            {payload.state.last_cascade?.recomputation_status === "REQUIRED" && <div className="recomputation-pending" role="status"><strong>Downstream пересчёт обязателен</strong><p>Material Context/Model change уже инвалидировал Strategy, Drafts, shortlist и confirmation. Завершите следующие шаги заново.</p></div>}
            {step === 0 && <ContextStep payload={payload} busy={Boolean(busy)} apply={apply} />}
            {step === 1 && <ModelStep payload={payload} apply={apply} back={() => setStep(0)} />}
            {step === 2 && <StrategyStep payload={payload} apply={apply} back={() => setStep(1)} />}
            {step === 3 && <DraftStep payload={payload} apply={apply} back={() => setStep(2)} openReview={() => setStep(4)} />}
            {step === 4 && <ConfirmationStep payload={payload} apply={apply} busy={Boolean(busy)} back={() => setStep(3)} />}
            {busy && <p className="notice">{busy}</p>}
            {error && <p className="notice error">{error}</p>}
          </section>
        </div>
      </main>
    </div>
  );
}

function Connection({ label, ready, detail }: { label: string; ready: boolean; detail?: string }) {
  return <div className={`connection ${ready ? "" : "blocked"}`}><i /><div><strong>{label}</strong><small>{detail || "Не готово"}</small></div></div>;
}

function ArtifactHead({ eyebrow, title, copy, badge = "REAL DATA" }: { eyebrow: string; title: string; copy: string; badge?: string }) {
  return <header className="artifact-head"><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2><p>{copy}</p></div><strong>{badge}</strong></header>;
}

function Actions({ revision, label, disabled, back, submit }: { revision: number; label: string; disabled?: boolean; back?: () => void; submit?: boolean }) {
  return <footer className="actions"><span>Ревизия {revision} · production data only</span>{back && <button type="button" className="secondary" onClick={back}>Назад</button>}<button type={submit ? "submit" : "button"} disabled={disabled}>{label}</button></footer>;
}

function ContextStep({ payload, busy, apply }: { payload: Payload; busy: boolean; apply: (action: string, value?: Record<string, unknown>, extra?: Record<string, unknown>) => Promise<void> }) {
  const analysis = payload.state.site_analysis;
  const contextState = payload.state.context_state;
  const goal = contextState?.business_goal_decision?.value || contextState?.provisional_business_goal?.value || "";
  const preflight = payload.context_preflight;
  function submitResearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void apply("analyze_site", undefined, { url: fieldValue(event.currentTarget, "url") });
  }
  function submitGoal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void apply("confirm_context_goal", undefined, {
      confirmation: "CONFIRM_CONTEXT_GOAL",
      goal: fieldValue(event.currentTarget, "goal"),
    });
  }
  return <>
    <ArtifactHead eyebrow="Шаг 1 · production preflight" title="Контекст и provisional бизнес-цель" copy="До полной аналитики модуль проверяет точные official API bindings, безопасно исследует first-party target и просит одно явное решение владельца." badge={preflight.ready ? "BINDINGS VERIFIED" : "FAIL CLOSED"} />
    <div className="context-strip"><Metric label="Директ" value={payload.context.direct.ready ? payload.context.direct.account : "Не готов"} copy={payload.context.direct.ready ? `clients.get подтвердил account · ${payload.context.direct.campaigns_total} кампаний` : preflight.blockers[0]} /><Metric label="Метрика" value={payload.context.metrika.ready ? `Счётчик ${payload.context.metrika.counter_id}` : "Не готова"} copy={payload.context.metrika.ready ? `Цель ${payload.context.metrika.goal_id} подтверждена Management API` : preflight.blockers[0]} /><Metric label="Сайт" value={analysis ? analysis.title || analysis.url : "Нужен публичный HTTPS URL"} copy={analysis ? `${analysis.research?.pages_analyzed || 1} first-party страниц · bounded research` : "Private/local targets и unsafe redirects отклоняются"} /></div>
    {!preflight.ready && <div className="preflight-blocked"><strong>Продолжение заблокировано</strong><ul>{preflight.blockers.map((item) => <li key={item}>{item}</li>)}</ul><small>Credentials остаются только server-side и не передаются в этот state.</small></div>}
    <form className="form" onSubmit={submitResearch}>
      <label className="wide"><span>Публичный first-party сайт бизнеса</span><input type="text" inputMode="url" name="url" required defaultValue={analysis?.url || ""} placeholder="example.ru или https://example.ru/" /><small>HTTPS добавляется технически; credentials, private/local/link-local targets, unsafe redirects и превышение лимитов отклоняются до исследования.</small></label>
      {analysis && <div className="material-impact"><strong>До material Context change</strong><p>Будут затронуты: {payload.context_change_policy.affected_steps.map((item) => item.label).join(" → ")}. Confirmation заблокируется до пересчёта. Пробелы и техническая URL-нормализация сами по себе ничего не инвалидируют.</p></div>}
      <div className="agent-work"><strong>Что агент сделает сам до полной аналитики</strong><p>Проверит exact account/counter/goal authority через official APIs, обойдёт не более шести bounded first-party страниц и предложит ровно одну evidence-grounded цель.</p></div>
      <Actions revision={payload.revision} label={analysis ? "Повторно проверить Context" : "Проверить Context и предложить цель"} disabled={busy || !preflight.ready} submit />
    </form>
    {contextState && <form key={`${payload.revision}-${contextState.status}`} className="goal-decision" onSubmit={submitGoal}>
      <header><div><p className="eyebrow">Одна provisional бизнес-цель</p><h3>{contextState.status === "GOAL_CONFIRMED" ? "Решение владельца сохранено" : "Подтвердите или исправьте до полной аналитики"}</h3></div><strong>{contextState.status === "GOAL_CONFIRMED" ? "OWNER CONFIRMED" : "PROVISIONAL"}</strong></header>
      <label><span>Бизнес-цель</span><textarea name="goal" required maxLength={500} defaultValue={goal} /></label>
      <blockquote>{contextState.provisional_business_goal.rationale}</blockquote>
      {contextState.status === "GOAL_CONFIRMED" && <div className="material-impact"><strong>Перед изменением подтверждённой цели</strong><p>Material edit затронет: {payload.context_change_policy.affected_steps.map((item) => item.label).join(" → ")}. Техническая нормализация пробелов не создаёт invalidation.</p></div>}
      {contextState.last_material_change && <p className="invalidation-note">Downstream lineage сохранён в audit history; Strategy, Recommendation Set, Campaign Drafts, shortlist и confirmation инвалидированы.</p>}
      <Actions revision={payload.revision} label={contextState.status === "GOAL_CONFIRMED" ? "Сохранить Context goal" : "Подтвердить цель и продолжить анализ"} disabled={busy || !preflight.ready} submit />
    </form>}
  </>;
}

function Metric({ label, value, copy }: { label: string; value: string; copy?: string }) {
  return <div><span>{label}</span><strong>{value}</strong><small>{copy || "—"}</small></div>;
}

function Evidence({ model, field }: { model: Record<string, any>; field: string }) {
  const item = model.field_evidence?.[field] || {};
  return <small className={`evidence ${String(item.confidence || "LOW").toLowerCase()}`}><strong>{confidenceLabel(item.confidence || "LOW")}</strong>{item.quote ? ` · «${String(item.quote).slice(0, 180)}»` : ""}</small>;
}

function sourceStatusLabel(value: string) {
  return { VERIFIED: "Проверено", PARTIAL: "Частично", UNAVAILABLE: "Нет данных" }[value] || value;
}

function evidenceStatusLabel(value: string) {
  return {
    EVIDENCE_READY_WITH_GAPS: "Готово с пробелами",
    BLOCKED_UNKNOWN: "Нужны критические факты",
  }[value] || value;
}

function evidenceValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function EvidenceClaimDisclosure({ claim, records }: { claim: Record<string, any>; records: Record<string, any>[] }) {
  const linkedRecords = records.filter((record) => (claim.evidence_ids || []).includes(record.evidence_id));
  return <details className="evidence-claim">
    <summary aria-label={`Раскрыть claim ${claim.predicate}`}><strong>{claim.predicate}</strong><span>{claim.classification} · {claim.confidence?.tier}</span></summary>
    <div className="evidence-claim-body">
      <p><strong>Normalized claim:</strong> {evidenceValue(claim.normalized?.value ?? claim.value).slice(0, 500)}</p>
      <dl className="claim-confidence"><div><dt>Quality</dt><dd>{claim.confidence?.quality}</dd></div><div><dt>Freshness</dt><dd>{claim.confidence?.freshness}</dd></div><div><dt>Consistency</dt><dd>{claim.confidence?.consistency}</dd></div><div><dt>Coverage</dt><dd>{claim.confidence?.coverage}</dd></div><div><dt>Uncertainty</dt><dd>{claim.confidence?.uncertainty?.length || 0}</dd></div></dl>
      <code>{claim.claim_id}</code>
      {linkedRecords.map((record) => <details className="evidence-record" key={record.evidence_id}>
        <summary aria-label={`Раскрыть Evidence Record ${record.evidence_id}`}><strong>Evidence Record · {record.source_kind}</strong><span>{record.observed_at || "as_of unavailable"}</span></summary>
        <div>
          {record.raw?.quote && <blockquote>«{record.raw.quote}»</blockquote>}
          <p><strong>Bounded raw value</strong><code>{evidenceValue(record.raw?.value)}</code></p>
          <p><strong>Raw locator</strong><code>{evidenceValue(record.source_locator)}</code></p>
          <p><strong>Transform metadata</strong><code>{evidenceValue(record.transforms)}</code></p>
          <p><strong>Versions and hashes</strong><code>{evidenceValue({ versions: record.versions, extraction: record.extraction, raw_sha256: record.raw?.sha256, record_hash: record.record_hash })}</code></p>
        </div>
      </details>)}
    </div>
  </details>;
}

function AnalyticsEvidencePanel({ evidence }: { evidence: Record<string, any> }) {
  const summary = evidence.summary || {};
  const confidence = evidence.confidence || {};
  const sources = Array.isArray(evidence.sources) ? evidence.sources : [];
  const claims = Array.isArray(evidence.claims) ? evidence.claims : [];
  const records = Array.isArray(evidence.evidence) ? evidence.evidence : [];
  const uncertainties = Array.isArray(confidence.uncertainty) ? confidence.uncertainty : [];
  const blockers = Array.isArray(summary.hard_blockers) ? summary.hard_blockers : [];
  const conflicts = Array.isArray(evidence.conflicts) ? evidence.conflicts : [];
  const gaps = Array.isArray(evidence.gaps) ? evidence.gaps : [];
  const prelaunchCost = evidence.prelaunch_cost || {};
  const marketEvidence = evidence.market_evidence || null;
  return <section className="evidence-overview" aria-labelledby="evidence-overview-title">
    <header><div><p className="eyebrow">Versioned evidence snapshot</p><h3 id="evidence-overview-title">Краткая сводка аналитики</h3><p>Факты раскрываются до claim и source locator; score и hard blockers не смешиваются.</p></div><strong className={String(evidence.recommendation_status || "").toLowerCase()}>{evidenceStatusLabel(evidence.recommendation_status)}</strong></header>
    <div className="evidence-kpis"><Metric label="Источники" value={`${summary.sources_verified || 0} проверено · ${summary.sources_partial || 0} частично`} copy={`${summary.sources_unavailable || 0} недоступно из ${summary.sources_total || 0}`} /><Metric label="Claims" value={String(summary.claims_supported || 0)} copy="Каждый связан с Evidence Record" /><Metric label="Стоимость до запуска" value={prelaunchCost.status === "AVAILABLE" ? String(prelaunchCost.compact_source || "Qualified source") : "Недоступна"} copy={prelaunchCost.status === "AVAILABLE" ? `${prelaunchCost.range?.low}–${prelaunchCost.range?.high} ${prelaunchCost.currency} · VAT ${prelaunchCost.vat_treatment}` : "Нет квалифицированного comparable source"} /></div>
    {marketEvidence && <MarketEvidenceDisclosure evidence={marketEvidence} context="model" />}
    <dl className="confidence-vector" aria-label="Confidence dimensions"><div><dt>Качество</dt><dd>{confidence.quality || "UNKNOWN"}</dd></div><div><dt>Свежесть</dt><dd>{confidence.freshness || "UNKNOWN"}</dd></div><div><dt>Согласованность</dt><dd>{confidence.consistency || "NOT_EVALUATED"}</dd></div><div><dt>Покрытие</dt><dd>{confidence.coverage || "UNKNOWN"}</dd></div><div><dt>Неопределённость</dt><dd>{uncertainties.length}</dd></div></dl>
    <div className="evidence-source-grid">{sources.map((source: Record<string, any>) => <details key={source.source_id} className={`evidence-source ${String(source.status || "").toLowerCase()}`}><summary><span /><div><strong>{source.title}</strong><small>{sourceStatusLabel(source.status)}</small></div></summary><div className="evidence-source-body">{source.facts?.length > 0 && <ul>{source.facts.map((fact: string) => <li key={fact}>{fact}</li>)}</ul>}{source.limitations?.length > 0 && <ul className="limitations">{source.limitations.map((item: string) => <li key={item}>{item}</li>)}</ul>}<code>{source.source_kind} · {source.observed_at || "as_of unavailable"}</code></div></details>)}</div>
    {blockers.length > 0 && <section className="evidence-blockers" aria-labelledby="evidence-hard-blockers"><strong id="evidence-hard-blockers">Hard blockers оцениваются отдельно от score</strong><ul>{blockers.map((item: string) => <li key={item}>{item}</li>)}</ul></section>}
    <div className="evidence-separate-grid">
      <section className="evidence-missing" aria-labelledby="evidence-missing-title"><strong id="evidence-missing-title">Missing evidence</strong>{gaps.length ? <ul>{gaps.map((gap: Record<string, any>) => <li key={gap.gap_id}><b>{gap.material ? "MATERIAL" : "GAP"}</b>{gap.description}</li>)}</ul> : <p>Не зафиксировано.</p>}</section>
      <section className="evidence-conflicts" aria-labelledby="evidence-conflicts-title"><strong id="evidence-conflicts-title">Conflicts</strong>{conflicts.length ? <ul>{conflicts.map((conflict: Record<string, any>) => <li key={conflict.conflict_id}><b>{conflict.material ? "MATERIAL" : conflict.relation}</b>{conflict.predicate} · {conflict.resolution}</li>)}</ul> : <p>Неразрешённых конфликтов нет.</p>}</section>
    </div>
    {uncertainties.length > 0 && <div className="evidence-uncertainty"><strong>Неопределённость раскрыта, а не заполнена догадкой</strong><ul>{uncertainties.slice(0, 5).map((item: string) => <li key={item}>{item}</li>)}</ul></div>}
    <details className="evidence-index"><summary aria-label="Раскрыть Evidence index">Evidence index · claim → Evidence Record → bounded raw locator/value · {claims.length} claims · {records.length} records</summary><div>{claims.map((claim: Record<string, any>) => <EvidenceClaimDisclosure key={claim.claim_id} claim={claim} records={records} />)}</div></details>
    <footer><code>{String(evidence.snapshot_id || "")}</code><span>generated {evidence.generated_at}</span><span>as of {evidence.as_of}</span><span>{evidence.schema_version}</span></footer>
  </section>;
}

function BusinessModelSummary({ model }: { model: Record<string, any> }) {
  return <section className="business-model-summary" aria-labelledby="business-model-summary-title"><header><p className="eyebrow">Business model</p><h3 id="business-model-summary-title">Краткая модель бизнеса</h3></header><div><Metric label="Предложение" value={model.product || "Missing evidence"} copy={model.value || "Ценность не подтверждена"} /><Metric label="Аудитория" value={model.audience || "Missing evidence"} copy={model.exclusions || "Исключения не подтверждены"} /><Metric label="Квалифицированный результат" value={model.qualified_result || "Missing evidence"} copy="Owner confirmation хранится отдельно от first-party evidence" /></div></section>;
}

const landingDimensionLabels: Record<string, string> = {
  OFFER_MESSAGE_MATCH: "Offer / message match",
  CTA_ACTION: "CTA / qualified action",
  FORMS: "Forms",
  MEASUREMENT_READINESS: "Measurement readiness",
  TECHNICAL_ACCESS: "Technical access",
  PERFORMANCE: "Performance",
  ACCESSIBILITY: "Accessibility",
  OBSERVED_METRIKA_BEHAVIOR: "Observed Metrika behavior",
};

function LandingAdvisoryPanel({ run }: { run: Record<string, any> | null }) {
  const priorities = landingAdvisoryPriorities(run);
  const findings = Array.isArray(run?.findings) ? run.findings : [];
  const coverage = Array.isArray(run?.coverage) ? run.coverage : [];
  const insufficient = !run || run.status === "INSUFFICIENT_EVIDENCE" || run.status === "SAFETY_BLOCKED" || coverage.some((item: Record<string, any>) => item.evidence_status === "INSUFFICIENT_EVIDENCE");
  return <section className="landing-advisory" aria-labelledby="landing-advisory-title">
    <header><div><p className="eyebrow">LANDING PAGE · ADVISORY ONLY</p><h3 id="landing-advisory-title">Landing advisory</h3><p>Неблокирующий анализ точной Strategy revision. Findings не меняют eligibility, publish readiness, score, rank, thresholds, calibration или publish fingerprint.</p></div><strong>ADVISORY · NON-BLOCKING</strong></header>
    {!run && <div className="advisory-insufficient" role="status"><strong>Недостаточно доказательств</strong><p>Сначала утвердите Campaign Strategy revision. Отсутствие landing findings не считается успехом и не блокирует publish decisions.</p></div>}
    {run && <>
      <div className="advisory-lineage"><span>{run.strategy_revision_id}</span><code>{run.final_url || run.requested_url}</code><b>{run.status}</b></div>
      {insufficient && <div className="advisory-insufficient" role="status"><strong>Insufficient evidence раскрыто явно</strong><p>Неполные tool runs, Metrika coverage или manual-review items не превращены в zero, pass или факт.</p></div>}
      <section className="advisory-priorities" aria-label="До трёх landing advisory priorities"><h4>Приоритеты · максимум 3</h4>{priorities.length ? <ol>{priorities.map((item) => <li key={item.finding_id}><span>{landingDimensionLabels[item.dimension] || item.dimension}</span><strong>{item.title}</strong><small>{item.type} · {item.evidence_status}</small></li>)}</ol> : <p>Детерминированных приоритетов нет. Это не означает доказанное отсутствие проблем.</p>}</section>
      <details className="advisory-details"><summary>Все details · evidence types, statuses и tool versions</summary><div className="advisory-tools"><code>{JSON.stringify({ required: run.tools?.required, observed: run.tools?.observed, version_status: run.tools?.version_status })}</code><p>Lighthouse: {run.lighthouse?.runs?.length || 0}/5 sequential desktop runs · median: {run.lighthouse?.median ? "available" : "insufficient evidence"}</p><p>axe incomplete: {run.axe?.categories?.incomplete?.count ?? "unavailable"} · {run.axe?.manual_review?.disclosure}</p></div><ul>{findings.map((item: Record<string, any>) => <li key={item.finding_id}><header><strong>{landingDimensionLabels[item.dimension] || item.dimension}</strong><span>{item.type} · {item.evidence_status}</span></header><p>{item.title}</p><small>{item.detail}</small></li>)}</ul></details>
    </>}
  </section>;
}

function ModelStep({ payload, apply, back }: { payload: Payload; apply: (action: string, value?: Record<string, unknown>) => Promise<void>; back: () => void }) {
  const model = payload.state.business_model || {};
  const research = model.research || {};
  const analyticsEvidence = payload.state.analytics_evidence_snapshot || null;
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    void apply("save_business_model", Object.fromEntries(["product", "audience", "value", "qualified_result", "exclusions"].map((name) => [name, fieldValue(form, name)])));
  }
  return <>
    <ArtifactHead eyebrow="Шаг 2 · агентное исследование" title="Агент уже собрал модель бизнеса" copy="Сначала — краткая сводка, затем раскрываемые доказательства. Исправьте только неверную гипотезу или факт, которого действительно нет в разрешённых источниках." badge="AGENT RESEARCH" />
    <BusinessModelSummary model={model} />
    <LandingAdvisoryPanel run={payload.state.landing_advisory_run || null} />
    {analyticsEvidence && <AnalyticsEvidencePanel evidence={analyticsEvidence} />}
    <div className="research-strip"><Metric label="Исследовано" value={`${research.pages_analyzed || 1} страниц`} copy="First-party public HTTPS" /><Metric label="Источники" value={String(research.sources?.length || 0)} copy={(research.sources || []).join(" · ")} /><Metric label="Сделано агентом" value={`${research.completed_fields?.length || 0} / 5 полей`} copy="Человеку — подтверждение и разногласия" /></div>
    {model.assumptions?.length > 0 && <div className="assumption"><strong>Где нужна проверка</strong><span>{model.assumptions.join(" · ")}</span></div>}
    {payload.state.strategy && <div className="material-impact"><strong>До material Model change</strong><p>Strategy, Recommendation Set, Campaign Drafts, shortlist и confirmation будут инвалидированы. Пробелы и техническая нормализация значений не запускают каскад.</p></div>}
    <form className="form two" onSubmit={submit}>
      <Field wide label="Рекламируемое предложение" name="product" value={model.product}><Evidence model={model} field="product" /></Field>
      <Field label="Лица, принимающие решение" name="audience" value={model.audience}><Evidence model={model} field="audience" /></Field>
      <Field label="Ценность для покупателя" name="value" value={model.value}><Evidence model={model} field="value" /></Field>
      <Field label="Квалифицированный результат" name="qualified_result" value={model.qualified_result}><Evidence model={model} field="qualified_result" /></Field>
      <Field label="Исключения из результата" name="exclusions" value={model.exclusions}><Evidence model={model} field="exclusions" /></Field>
      <div className="wide"><Actions revision={payload.revision} label="Подтвердить вывод агента" back={back} submit /></div>
    </form>
  </>;
}

function Field({ label, name, value, wide, maxLength, children }: { label: string; name: string; value: string; wide?: boolean; maxLength?: number; children?: React.ReactNode }) {
  return <label className={wide ? "wide" : ""}><span>{label}</span><textarea name={name} required maxLength={maxLength} defaultValue={value} />{children}</label>;
}

const strategyFieldLabels: Record<string, string> = {
  business_goal: "Бизнес-цель",
  advertised_offer: "Рекламируемое предложение",
  target_audience: "Целевая аудитория",
  qualified_result: "Квалифицированный результат",
  exclusions: "Исключения",
  geography: "География",
  period: "Период",
  landing_page: "Посадочная страница",
  weekly_budget: "Недельный бюджет, ₽",
  target_result_cost: "Целевая стоимость результата, ₽",
  core_message: "Основное сообщение",
};

function strategyAnswer(strategy: Record<string, any>, fieldId: string) {
  const answer = (Array.isArray(strategy.answers) ? strategy.answers : []).find((item: Record<string, any>) => item.field_id === fieldId);
  return answer?.value;
}

function StrategyRecommendation({ field }: { field: Record<string, any> }) {
  const recommendation = field.recommended_value;
  const display = recommendation && typeof recommendation === "object"
    ? `${recommendation.start_date || "—"} — ${recommendation.end_date || "—"}`
    : recommendation ?? "Рекомендации нет";
  return <aside className={`strategy-recommendation ${field.status === "нет данных" ? "missing" : ""}`}>
    <span>Рекомендация агента</span><strong>{String(display)}</strong><p>{field.explanation}</p>
    <footer><b>{field.source_category}</b><em>{field.status}</em></footer>
    {field.prepared_decision && <div className="prepared-decision"><strong>{field.prepared_decision.question}</strong><ul>{field.prepared_decision.consequences.map((item: string) => <li key={item}>{item}</li>)}</ul></div>}
  </aside>;
}

function StrategyStep({ payload, apply, back }: { payload: Payload; apply: (action: string, value?: Record<string, unknown>, extra?: Record<string, unknown>) => Promise<void>; back: () => void }) {
  const questionnaire = payload.state.strategy_questionnaire || { fields: [] };
  const existing = payload.state.strategy || {};
  const fields = Array.isArray(questionnaire.fields) ? questionnaire.fields : [];
  const field = (fieldId: string) => fields.find((item: Record<string, any>) => item.field_id === fieldId) || {};
  const initialValue = (fieldId: string) => strategyAnswer(existing, fieldId) ?? field(fieldId).recommended_value ?? "";
  const existingPeriod = initialValue("period");
  const [weeklyBudget, setWeeklyBudget] = useState(String(initialValue("weekly_budget")));
  const minimumWeeklyBudget = Number(payload.context.direct?.minimum_weekly_budget_rub);
  const minimumWeeklyBudgetAvailable = Number.isFinite(minimumWeeklyBudget) && minimumWeeklyBudget > 0;
  const weeklyBudgetError = minimumWeeklyBudgetAvailable
    ? weeklyBudgetValidationMessage(weeklyBudget, minimumWeeklyBudget)
    : "Direct minimum недоступен; approval заблокирован без доказуемого platform constraint.";
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const answers = {
      business_goal: fieldValue(form, "business_goal"),
      advertised_offer: fieldValue(form, "advertised_offer"),
      target_audience: fieldValue(form, "target_audience"),
      qualified_result: fieldValue(form, "qualified_result"),
      exclusions: fieldValue(form, "exclusions"),
      geography: fieldValue(form, "geography"),
      period: { start_date: fieldValue(form, "period_start"), end_date: fieldValue(form, "period_end") },
      landing_page: fieldValue(form, "landing_page"),
      weekly_budget: fieldValue(form, "weekly_budget"),
      target_result_cost: fieldValue(form, "target_result_cost"),
      core_message: fieldValue(form, "core_message"),
    };
    void apply("approve_strategy", undefined, { confirmation: "APPROVE_CAMPAIGN_STRATEGY", answers });
  }
  const inputFor = (fieldId: string) => {
    const value = initialValue(fieldId);
    if (fieldId === "business_goal") return <input name={fieldId} required readOnly value={String(value)} />;
    if (["advertised_offer", "target_audience", "qualified_result", "exclusions", "core_message"].includes(fieldId)) return <textarea name={fieldId} required defaultValue={String(value)} />;
    if (fieldId === "geography") return <select name={fieldId} required defaultValue={String(value)}><option value="" disabled>Выберите business-owned географию</option><option>Россия</option><option>Москва</option><option>Санкт-Петербург</option></select>;
    if (fieldId === "period") return <div className="period-inputs"><label><span>Начало</span><input type="date" name="period_start" required defaultValue={String(existingPeriod?.start_date || "")} /></label><label><span>Окончание</span><input type="date" name="period_end" required defaultValue={String(existingPeriod?.end_date || "")} /></label></div>;
    if (fieldId === "landing_page") return <input type="url" name={fieldId} required defaultValue={String(value)} />;
    if (fieldId === "weekly_budget") return <><input className={weeklyBudgetError ? "field-invalid" : ""} type="number" {...(minimumWeeklyBudgetAvailable ? { min: minimumWeeklyBudget } : {})} name={fieldId} required value={weeklyBudget} aria-invalid={Boolean(weeklyBudgetError)} aria-describedby="weekly-budget-help" onChange={(event) => setWeeklyBudget(event.target.value)} /><small id="weekly-budget-help" className={weeklyBudgetError ? "field-error" : ""} role={weeklyBudgetError ? "alert" : undefined}>{weeklyBudgetError || `Минимум Direct: ${minimumWeeklyBudget} ₽; это constraint, не recommendation.`}</small></>;
    return <input type="number" min="1" name={fieldId} required defaultValue={String(value)} />;
  };
  return <>
    <ArtifactHead eyebrow="Шаг 3 · одно approval" title="Фиксированный Campaign Strategy questionnaire" copy="Все 11 полей всегда идут в одном порядке. Агент рекомендует только доказуемое; business-owned пробелы остаются подготовленными решениями без defaults." />
    {existing.strategy_revision_id && <div className="material-impact"><strong>До material Strategy change</strong><p>Будет создана новая immutable Strategy revision, Recommendation Set детерминированно регенерируется, Campaign Drafts и shortlist очистятся, confirmation останется заблокированным до завершения пересчёта. Пробелы и техническая нормализация не запускают каскад.</p></div>}
    <form className="strategy-form" onSubmit={submit}>
      <ol className="strategy-questionnaire" aria-label="Campaign Strategy questionnaire">
        {fields.map((item: Record<string, any>, index: number) => <li key={item.field_id} data-strategy-field={item.field_id}>
          <header><span>{index + 1}</span><strong>{strategyFieldLabels[item.field_id] || item.field_id}</strong><code>{item.field_id}</code></header>
          <StrategyRecommendation field={item} />
          <div className="strategy-answer"><span>Утверждаемое значение</span>{inputFor(item.field_id)}</div>
        </li>)}
      </ol>
      <footer className="actions"><span>Ревизия {payload.revision} · questionnaire {questionnaire.contract_version}</span><button type="button" className="secondary" onClick={back}>Назад</button><button type="submit" disabled={Boolean(weeklyBudgetError) || fields.length !== 11}>Утвердить всю Campaign Strategy</button></footer>
    </form>
  </>;
}

function DraftStep({ payload, apply, back, openReview }: { payload: Payload; apply: (action: string, value?: Record<string, unknown>, extra?: Record<string, unknown>) => Promise<void>; back: () => void; openReview: () => void }) {
  const existing = payload.state.draft || {};
  const recommendationSet = payload.state.recommendation_set || {};
  const shortlist = payload.state.shortlist || { selections: [], removed_selections: [] };
  const shortlistSelections = Array.isArray(shortlist.selections) ? shortlist.selections : [];
  const shortlistControlByDraft = new Map(payload.shortlist_controls.map((control) => [control.draft_id, control]));
  const drafts = Array.isArray(recommendationSet.drafts) ? recommendationSet.drafts : [];
  const revisionHistory = (Array.isArray(payload.revision_history) ? payload.revision_history : [])
    .filter((item: Record<string, any>) => item.strategy_revision_id || item.draft_revision_id);
  const initialDraft = drafts.find((item: Record<string, any>) => item.visibility === "VISIBLE") || drafts[0] || existing;
  const [selectedDraftId, setSelectedDraftId] = useState(String(existing.draft_id || initialDraft?.draft_id || ""));
  const [variantFilter, setVariantFilter] = useState<"ALL" | "CONTROL" | "IMPROVEMENT">("ALL");
  const [evidenceFilter, setEvidenceFilter] = useState<CampaignCanvasFilters["evidence"]>("ALL");
  const [sort, setSort] = useState<"RANK" | "SCORE">("RANK");
  const [includeHidden, setIncludeHidden] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const lastTriggerRef = useRef<HTMLButtonElement | null>(null);
  const filteredDrafts = filterAndSortCampaignDrafts(drafts, {
    variant: variantFilter,
    evidence: evidenceFilter,
    sort,
    includeHidden,
  });
  const generated = drafts.find((item: Record<string, any>) => item.draft_id === selectedDraftId) || initialDraft;
  const selected = existing.draft_id === generated?.draft_id ? { ...generated, ...existing } : generated;
  const selectedShortlistEligible = selected?.shortlist_eligible === true
    && selected?.viability_score?.eligibility?.status === "ELIGIBLE"
    && selected?.viability_score?.evidence_gaps?.status === "RESOLVED"
    && selected?.visibility === "VISIBLE";
  const evidenceStatuses = [...new Set<CampaignEvidenceStatus>(drafts.map((item: Record<string, any>) => String(item.market_evidence_status || "UNAVAILABLE") as CampaignEvidenceStatus))].sort();

  function closeDrawer() {
    setDrawerOpen(false);
    queueMicrotask(() => lastTriggerRef.current?.focus());
  }

  function openDrawer(draftId: string, trigger: HTMLButtonElement) {
    lastTriggerRef.current = trigger;
    setSelectedDraftId(draftId);
    setDrawerOpen(true);
  }

  useEffect(() => {
    if (!drawerOpen) return;
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeDrawer();
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) return;
      const focusable = [...drawerRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), summary, [tabindex]:not([tabindex='-1'])")];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable.at(-1)!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [drawerOpen, selectedDraftId]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const registryFields = Array.isArray(recommendationSet.field_registry?.fields)
      ? recommendationSet.field_registry.fields as Array<Record<string, unknown>>
      : [];
    const editableInputNames = registryFields
      .filter((field) => field.editable === true && typeof field.input_name === "string" && field.input_name.length > 0)
      .map((field) => String(field.input_name));
    const value = {
      draft_id: String(selected.draft_id || ""),
      ...Object.fromEntries(editableInputNames.map((name) => [name, fieldValue(form, name)])),
    };
    void apply("save_draft", value);
  }
  return <>
    <ArtifactHead eyebrow="Шаг 4 · Campaign Drafts" title="Campaign Canvas" copy="Ranked cards показывают сравнительный приоритет без predictive claims. Правый drawer редактирует только exact server-supported Direct projection; blocked и hidden Drafts остаются reviewable." />
    {payload.state.recommendation_recalculation?.material_change === true && <section className="recommendation-recalculated" role="status">
      <strong>Рекомендация пересчитана</strong><p>{payload.state.recommendation_recalculation.message}</p>
      <ul>{payload.state.recommendation_recalculation.changes?.map((change: Record<string, any>) => <li key={`${change.change_type}-${change.previous_draft_id}-${change.current_draft_id}`}>
        <strong>{change.change_type} · {change.previous_draft_id || "—"} → {change.current_draft_id || "—"}</strong>
        <small>score {change.previous_score ?? "—"} → {change.current_score ?? "—"} · rank {change.previous_rank ?? "—"} → {change.current_rank ?? "—"}</small>
        {(change.fields || []).length > 0
          ? <ul>{change.fields.map((field: Record<string, any>) => <li key={field.pointer}><code>{field.pointer}</code><span>{evidenceValue(field.previous_normalized_value)} → {evidenceValue(field.current_normalized_value)}</span></li>)}</ul>
          : <span>Без соответствующего material Direct projection delta.</span>}
      </li>)}</ul>
    </section>}
    <RecommendationSetDisclosure recommendationSet={recommendationSet} />
    <section className="canvas-controls" aria-label="Фильтры и сортировка Campaign Canvas">
      <label><span>Variant</span><select aria-label="Фильтр variant" value={variantFilter} onChange={(event) => setVariantFilter(event.target.value as typeof variantFilter)}><option value="ALL">Все variants</option><option value="CONTROL">Comparator / control</option><option value="IMPROVEMENT">Improvements</option></select></label>
      <label><span>Evidence</span><select aria-label="Фильтр evidence status" value={evidenceFilter} onChange={(event) => setEvidenceFilter(event.target.value as CampaignCanvasFilters["evidence"])}><option value="ALL">Все evidence statuses</option>{evidenceStatuses.map((status) => <option key={status} value={status}>{status}</option>)}</select></label>
      <label><span>Sort</span><select aria-label="Сортировка Drafts" value={sort} onChange={(event) => setSort(event.target.value as typeof sort)}><option value="RANK">Semantic rank</option><option value="SCORE">Comparative score</option></select></label>
      <label className="show-hidden"><input type="checkbox" checked={includeHidden} onChange={(event) => setIncludeHidden(event.target.checked)} /><span>Показать hidden Drafts с suppression reasons</span></label>
    </section>
    <section className="draft-canvas" aria-label="Ranked Campaign Draft cards">
      {filteredDrafts.map((item: Record<string, any>) => {
        const control = shortlistControlByDraft.get(item.draft_id);
        const shortlistAction = control?.status === "SELECTED"
          ? "remove_from_shortlist"
          : control?.status === "REMOVED"
            ? "restore_to_shortlist"
            : "add_to_shortlist";
        const shortlistLabel = control?.status === "SELECTED"
          ? "Исключить из shortlist"
          : control?.status === "REMOVED"
            ? "Вернуть в shortlist"
            : "Добавить в shortlist";
        return <article key={item.draft_id} className={`draft-card-shell ${item.draft_id === selected?.draft_id ? "selected" : ""}`}>
          <CampaignDraftCard draft={item} selected={item.draft_id === selected?.draft_id} />
          <div className="draft-card-actions">
            <button type="button" aria-label={`${shortlistLabel}: ${item.draft_id}`} disabled={!control || control.status === "BLOCKED"} onClick={() => void apply(shortlistAction, undefined, { draft_id: item.draft_id })}>{shortlistLabel}</button>
            <button type="button" aria-label={`Открыть Draft ${item.draft_id}`} onClick={(event) => openDrawer(item.draft_id, event.currentTarget)}>Открыть точную Direct projection</button>
          </div>
          {control?.status === "BLOCKED" && <small className="shortlist-disabled-reason" role="status">Shortlist недоступен: {control.disabled_reason}</small>}
        </article>;
      })}
      {filteredDrafts.length === 0 && <p className="canvas-empty">Нет Drafts для выбранных deterministic filters. Измените variant/evidence filter; кандидаты остаются в audit.</p>}
    </section>
    {revisionHistory.length > 0 && <details className="hidden-drafts revision-history"><summary>История Strategy и Draft · {revisionHistory.length}</summary><ul>{revisionHistory.map((item: Record<string, any>) => <li key={item.revision}><strong>Ревизия {item.revision} · {item.status}</strong><span>{item.strategy_revision_id}{item.draft_revision_id ? ` · ${item.draft_revision_id}` : " · Draft ещё не зафиксирован"}{item.publish_fingerprint ? ` · ${String(item.publish_fingerprint).slice(0, 12)}…` : ""}</span></li>)}</ul></details>}
    <section className="shortlist-footer" aria-label="Persistent shortlist summary">
      <div><p className="eyebrow">ORDERED SHORTLIST · {shortlistSelections.length}</p><strong>{shortlistSelections.length ? "Точный пакет выбранных Campaign Drafts" : "Добавьте publish-ready Drafts"}</strong><small>Footer не зависит от card filters. Порядок выбора фиксируется в package authority.</small></div>
      <ol>{shortlistSelections.map((item: Record<string, any>) => <li key={item.draft_id}><span>{item.draft_revision_id}</span><code>{String(item.publish_fingerprint || "").slice(0, 18)}…</code></li>)}</ol>
      <button type="button" disabled={!shortlistSelections.length} onClick={() => payload.state.package_review ? openReview() : void apply("review_package")}>{payload.state.package_review ? "Открыть current package review" : "Создать package review"}</button>
    </section>
    {payload.state.last_decision_invalidation && !payload.state.package_review && <p className="decision-invalidation" role="status"><strong>Предыдущая authority инвалидирована:</strong> {payload.state.last_decision_invalidation.reason}</p>}
    <footer className="actions"><span>{filteredDrafts.length} Drafts в canvas · {drafts.length} persisted Draft candidates</span><button type="button" className="secondary" onClick={() => void apply("recalculate_recommendations")}>Проверить active playbook</button><button type="button" className="secondary" onClick={back}>Назад</button></footer>
    {drawerOpen && selected?.draft_id && <div className="drawer-layer">
      <aside ref={drawerRef} className="campaign-drawer" role="dialog" aria-modal="true" aria-labelledby="campaign-drawer-title">
        <header className="drawer-head"><div><p className="eyebrow">CAMPAIGN DRAFT · REVIEW</p><h2 id="campaign-drawer-title">Точная будущая Direct projection</h2><span>{selected.draft_revision_id} · {String(selected.publish_fingerprint || "")}</span></div><button ref={closeButtonRef} type="button" aria-label="Закрыть drawer" onClick={closeDrawer}>×</button></header>
        <div className="drawer-scroll">
          <div className="draft-lineage"><strong>{selected.variant?.kind === "CONTROL" ? selected.variant?.control_basis?.kind : selected.variant?.hypothesis?.changed_family}</strong><span>{selected.strategy_revision_id} · {selected.draft_revision_id}</span><small>{selected.playbook_release_id || "FAIL_CLOSED"}@{selected.playbook_release_version || "—"} · {selected.capability_profile_id}@{selected.capability_profile_version}</small></div>
          <DraftPublicationBlockers draft={selected} />
          {!selectedShortlistEligible && <div className="preflight-blocked"><strong>Review доступен · Publish readiness заблокирована</strong><p>Hard blocker, hidden disposition или unresolved EVIDENCE_GAP нельзя обойти score, edit или provisional shortlist.</p></div>}
          <DraftEditFeedback draft={selected} />
          <ViabilityScoreDisclosure score={selected.viability_score} delta={selected.score_delta} />
          {selected.market_evidence && <MarketEvidenceDisclosure evidence={selected.market_evidence} context="draft" />}
          <form key={`${selected.draft_id}-${selected.draft_revision_id}-${payload.revision}`} className="drawer-form" onSubmit={submit}>
            <DraftFieldRegistryDisclosure registry={recommendationSet.field_registry} draft={selected} />
            <Actions revision={payload.revision} label={selectedShortlistEligible ? "Сохранить material revision" : "Сохранить review-правки без publish readiness"} submit />
          </form>
        </div>
      </aside>
    </div>}
  </>;
}

const executionProgressLabels = {
  validation: "Validation",
  creation: "Creation",
  suspension: "Suspension",
  child_graph: "Child graph",
  readback: "Readback",
  moderation: "Moderation",
} as const;

function PackageExecutionPanel({
  execution,
  busy,
  canPoll,
  poll,
  correctionItemIds = [],
  startCorrection,
}: {
  execution: Record<string, any>;
  busy: boolean;
  canPoll: boolean;
  poll: (itemExecutionId: string) => void;
  correctionItemIds?: string[];
  startCorrection?: (itemExecutionId: string) => void;
}) {
  const items = Array.isArray(execution.items) ? execution.items : [];
  return <section className="package-executions" aria-label="Package campaign executions">
    <header><div><p className="eyebrow">DURABLE INDEPENDENT EXECUTIONS</p><h3>Результат каждого Campaign Draft сохранён отдельно</h3><p>Package verdict {execution.verdict || "PENDING"} · status {execution.status}. PASS появляется только после полной accountability selected set.</p></div><strong>{execution.dispatched_count}/{execution.selected_count}</strong></header>
    <ol>{items.map((item: Record<string, any>) => <li key={item.item_execution_id} className={`package-execution-item ${String(item.ownership || "unknown").toLowerCase()}`}>
      <header><div><span>#{Number(item.position) + 1}</span><strong>{item.selection?.draft_revision_id}</strong><code>{item.item_execution_id}</code></div><div><b>{item.status}</b><small>Ownership · {item.ownership}</small></div></header>
      <dl className="execution-progress">{Object.entries(executionProgressLabels).map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{item.progress?.[key] || "PENDING"}</dd></div>)}</dl>
      <div className="execution-identifiers"><span>Campaign <code>{item.provider_ids?.campaign_id || "—"}</code></span><span>Ad groups <code>{item.provider_ids?.ad_group_ids?.join(", ") || item.provider_ids?.ad_group_id || "—"}</code></span><span>Keywords <code>{item.provider_ids?.keyword_ids?.join(", ") || item.provider_ids?.keyword_id || "—"}</code></span><span>Ads <code>{item.provider_ids?.ad_ids?.join(", ") || "—"}</code></span></div>
      {item.accountability && <dl className="execution-progress"><div><dt>Graph</dt><dd>{item.accountability.supported_graph_verified ? "VERIFIED" : "PENDING"}</dd></div><div><dt>Non-serving</dt><dd>{item.accountability.campaign_suspended ? "SUSPENDED" : "UNCONFIRMED"}</dd></div><div><dt>Ads terminal</dt><dd>{item.accountability.all_ads_terminal ? "YES" : "NO"}</dd></div><div><dt>Direct accepted</dt><dd>{item.accountability.direct_accepted ? "YES" : "NO"}</dd></div></dl>}
      <footer><span>Containment · <strong>{item.containment}</strong></span><span>Account lock · <strong>{item.account_lock}</strong></span></footer>
      {item.moderation?.next_poll_at && <p className="execution-failure" role="status"><strong>Next moderation poll</strong> · {item.moderation.next_poll_at} · attempts {item.moderation.poll_attempts}<button type="button" disabled={busy || !canPoll} onClick={() => poll(String(item.item_execution_id))}>Проверить due item</button></p>}
      {Array.isArray(item.moderation?.ad_outcomes) && item.moderation.ad_outcomes.length > 0 && <details><summary>Ad moderation outcomes · {item.moderation.ad_outcomes.length}</summary><ul>{item.moderation.ad_outcomes.map((ad: Record<string, any>) => <li key={ad.ad_id}><strong>{ad.ad_id} · {ad.status}</strong><span>{ad.status_clarification || "StatusClarification отсутствует"}</span></li>)}</ul></details>}
      {item.failure && <p className="execution-failure" role="status"><strong>{item.failure.code}</strong> · {item.failure.message}</p>}
      {item.status === "REJECTED_NEEDS_EDIT" && startCorrection && <button type="button" className="correction-start" disabled={busy || correctionItemIds.includes(String(item.item_execution_id))} onClick={() => startCorrection(String(item.item_execution_id))}>{correctionItemIds.includes(String(item.item_execution_id)) ? "Focused correction уже открыта" : "Исправить отклонённый Draft"}</button>}
      {Array.isArray(item.provider_issues) && item.provider_issues.length > 0 && <details><summary>Provider details · {item.provider_issues.length}</summary><ul>{item.provider_issues.map((issue: Record<string, any>, index: number) => <li key={`${issue.operation}-${issue.code}-${index}`}><strong>{issue.operation} · {issue.code}</strong><span>{issue.message}{issue.details ? ` · ${issue.details}` : ""}</span></li>)}</ul></details>}
      {item.readback && <details><summary>Semantic readback</summary><code>{JSON.stringify(item.readback)}</code></details>}
    </li>)}</ol>
  </section>;
}

function PackageCorrectionsPanel({
  corrections,
  fieldRegistry,
  busy,
  canPoll,
  apply,
}: {
  corrections: Array<Record<string, any>>;
  fieldRegistry: Record<string, any>;
  busy: boolean;
  canPoll: boolean;
  apply: (action: string, value?: Record<string, unknown>, extra?: Record<string, unknown>) => Promise<void>;
}) {
  const [confirmedCorrectionId, setConfirmedCorrectionId] = useState("");
  function submitCorrection(event: FormEvent<HTMLFormElement>, correction: Record<string, any>) {
    event.preventDefault();
    const registryFields = Array.isArray(fieldRegistry?.fields) ? fieldRegistry.fields as Array<Record<string, unknown>> : [];
    const editableInputNames = registryFields
      .filter((field) => field.editable === true && typeof field.input_name === "string" && field.input_name.length > 0)
      .map((field) => String(field.input_name));
    const form = event.currentTarget;
    void apply("save_package_correction", {
      draft_id: String(correction.source?.draft_snapshot?.draft_id || ""),
      ...Object.fromEntries(editableInputNames.map((name) => [name, fieldValue(form, name)])),
    }, { correction_id: correction.correction_id });
  }
  return <section className="package-corrections" aria-label="Focused correction flows">
    <header><div><p className="eyebrow">FOCUSED CORRECTION · IMMUTABLE LINEAGE</p><h3>Provider rejection correction</h3><p>Initial execution, provider responses и verdict остаются immutable. Только material Draft revision может получить новый review, Gate и resubmission.</p></div><strong>{corrections.length}</strong></header>
    {corrections.map((correction, correctionIndex) => {
      const source = correction.source || {};
      const sourceDraft = source.draft_snapshot || {};
      const correctedDraft = correction.corrected_draft || null;
      const correctedExecution = correction.execution || null;
      const decisionPacket = correction.decision_packet || null;
      const correctionItem = correctedExecution?.items?.[0] || null;
      const canConfirm = confirmedCorrectionId === correction.correction_id;
      return <article key={correction.correction_id} className="package-correction-flow">
        <header><div><p className="eyebrow">Correction progress</p><strong>{correction.status}</strong><code>{correction.correction_id}</code></div><span>{source.item_execution_id}</span></header>
        <dl className="correction-accounting">
          <div><dt>Initial package verdict</dt><dd>{source.initial_package_verdict}</dd></div>
          <div><dt>Correction progress</dt><dd>{correction.status}</dd></div>
          <div><dt>Corrected terminal outcome</dt><dd>{correction.terminal_outcome || "PENDING"}</dd></div>
        </dl>
        <section className="correction-provider-context"><strong>StatusClarification</strong>{source.status_clarifications?.length ? <ul>{source.status_clarifications.map((item: string) => <li key={item}>{item}</li>)}</ul> : <p>Provider clarification отсутствует; correction остаётся fail-closed.</p>}{source.provider_issues?.length > 0 && <details open><summary>Конкретные provider issues · {source.provider_issues.length}</summary><ul>{source.provider_issues.map((issue: Record<string, any>, index: number) => <li key={`${issue.operation}-${issue.code}-${index}`}><strong>{issue.operation} · {issue.code}</strong><span>{issue.message}{issue.details ? ` · ${issue.details}` : ""}</span></li>)}</ul></details>}<small>Initial package {source.package_id} · Gate {source.gate_id}</small></section>
        {correction.status === "EDITING" && <form className="correction-form" onSubmit={(event) => submitCorrection(event, correction)}>
          <DraftFieldRegistryDisclosure registry={fieldRegistry} draft={sourceDraft} titleId={`correction-draft-fields-${correctionIndex}`} />
          <button type="submit" disabled={busy}>Сохранить новую material correction revision</button>
        </form>}
        {correctedDraft && <section className="corrected-draft-review"><DraftEditFeedback draft={correctedDraft} /><ViabilityScoreDisclosure score={correctedDraft.viability_score} delta={correctedDraft.score_delta} /><dl><div><dt>Draft revision</dt><dd>{correctedDraft.draft_revision_id}</dd></div><div><dt>Publish fingerprint</dt><dd><code>{correctedDraft.publish_fingerprint}</code></dd></div></dl></section>}
        {decisionPacket && <section className="correction-decision-packet" aria-label="Prepared corrected Human Decision Gate packet">
          <header><div><p className="eyebrow">PREPARED HUMAN DECISION GATE</p><h4>Рекомендация · {decisionPacket.recommendation.action}</h4><p>{decisionPacket.recommendation.rationale}</p></div><strong>Confidence · {decisionPacket.confidence.status}</strong></header>
          <p>{decisionPacket.confidence.rationale}</p>
          <dl><div><dt>Evidence</dt><dd>{decisionPacket.evidence.changed_pointers.join(" · ")}</dd></div><div><dt>Score / rank</dt><dd>{decisionPacket.evidence.score.previous ?? "—"} → {decisionPacket.evidence.score.current ?? "—"} · {decisionPacket.evidence.rank.previous ?? "—"} → {decisionPacket.evidence.rank.current ?? "—"}</dd></div></dl>
          <div className="correction-options"><strong>Alternatives</strong><ul>{decisionPacket.alternatives.map((alternative: Record<string, any>) => <li key={alternative.action}><b>{alternative.action}</b><span>{alternative.consequence}</span></li>)}</ul></div>
          <div className="correction-consequences"><strong>Consequences</strong><ul>{decisionPacket.consequences.map((consequence: string) => <li key={consequence}>{consequence}</li>)}</ul></div>
        </section>}
        {correction.status === "PACKAGE_REVIEW_REQUIRED" && <button type="button" disabled={busy} onClick={() => void apply("review_package_correction", undefined, { correction_id: correction.correction_id })}>Проверить corrected package revision</button>}
        {correction.status === "HUMAN_GATE_REQUIRED" && <div className="correction-gate"><label><input type="checkbox" checked={canConfirm} onChange={(event) => setConfirmedCorrectionId(event.target.checked ? correction.correction_id : "")} /><span>Подтверждаю recommendation, evidence, confidence, alternatives, consequences и новый exact corrected fingerprint</span></label><button type="button" disabled={busy || !canConfirm} onClick={() => void apply("confirm_package_correction", undefined, { correction_id: correction.correction_id, confirmation: "CONFIRM_EXACT_SHORTLIST_PACKAGE", package_review_id: correction.package_review.package_review_id, package_id: correction.package_review.package_id })}>Создать новый Human Decision Gate</button></div>}
        {correction.status === "READY_TO_RESUBMIT" && <button type="button" disabled={busy} onClick={() => void apply("resubmit_package_correction", undefined, { correction_id: correction.correction_id, package_id: correction.human_decision_gate.package_id, gate_id: correction.human_decision_gate.gate_id })}>Повторно отправить confirmed correction revision</button>}
        {correctedExecution && <PackageExecutionPanel execution={correctedExecution} busy={busy} canPoll={canPoll} poll={(itemExecutionId) => void apply("poll_package_correction_moderation", undefined, { correction_id: correction.correction_id, package_id: correctedExecution.package_id, item_execution_id: itemExecutionId })} />}
        {correctionItem?.status === "RECONCILIATION_REQUIRED" && <p className="execution-failure" role="status"><strong>Reconciliation boundary удерживается</strong> · ambiguous corrected write не является content correction.</p>}
        {correction.terminal_outcome === "PASS_AFTER_CORRECTION" && <div className="correction-terminal" role="status"><strong>PASS_AFTER_CORRECTION</strong><p>Corrected revision принята и остаётся non-serving. Initial generation verdict не изменён.</p></div>}
      </article>;
    })}
  </section>;
}

function ConfirmationStep({ payload, apply, busy, back }: { payload: Payload; apply: (action: string, value?: Record<string, unknown>, extra?: Record<string, unknown>) => Promise<void>; busy: boolean; back: () => void }) {
  const [confirmed, setConfirmed] = useState(false);
  const review = payload.state.package_review;
  const gate = payload.state.human_decision_gate;
  const execution = payload.state.package_execution;
  const corrections = Array.isArray(payload.state.package_corrections) ? payload.state.package_corrections : [];
  const canDispatch = payload.workflow.allowed_commands.includes("dispatch_package");
  const authority = review?.authority;
  const selections = Array.isArray(authority?.ordered_selections) ? authority.ordered_selections : [];
  if (!review || !authority) {
    return <>
      <ArtifactHead eyebrow="Шаг 5 · Human Decision Gate" title="Package review недоступен" copy="Вернитесь в Campaign Canvas, сформируйте непустой ordered shortlist и откройте точный review из persistent footer." badge="FAIL CLOSED" />
      <ul className="blockers">{payload.decision_readiness.blockers.map((item, index) => <li key={item}><span>{index + 1}</span>{item}</li>)}</ul>
      <Actions revision={payload.revision} label="Вернуться к shortlist" disabled back={back} />
    </>;
  }
  const binding = authority.direct_account_binding || {};
  const capability = authority.direct_capability_snapshot || {};
  const profile = authority.capability_profile || {};
  return <>
    <ArtifactHead eyebrow="Шаг 5 · Human Decision Gate" title="Точный immutable package review" copy="Gate даёт authority только этому ordered set revisions и fingerprints. Confirmation не выполняет Direct writes и не обещает атомарную внешнюю транзакцию." badge={gate ? "AUTHORITY CONFIRMED" : "REVIEWED"} />
    <section className="package-review" aria-labelledby="package-review-title">
      <header><div><p className="eyebrow">PACKAGE IDENTITY</p><h3 id="package-review-title">{selections.length} независимых Campaign Drafts</h3></div><strong>{review.reviewed_at}</strong></header>
      <ol>{selections.map((item: Record<string, any>, index: number) => <li key={item.draft_id}><span>{index + 1}</span><div><strong>{item.draft_id}</strong><code>{item.draft_revision_id}</code><small>{item.publish_fingerprint}</small></div></li>)}</ol>
      <dl>
        <div><dt>Package ID</dt><dd><code>{review.package_id}</code></dd></div>
        <div><dt>Package review ID</dt><dd><code>{review.package_review_id}</code></dd></div>
        <div><dt>Recommendation Set</dt><dd><code>{authority.recommendation_set_id}</code></dd></div>
        <div><dt>Strategy revision</dt><dd><code>{authority.strategy_revision_id}</code></dd></div>
        <div><dt>Direct account binding</dt><dd>{binding.account} · client {binding.client_id} · {binding.source_kind}</dd></div>
        <div><dt>Capability snapshot</dt><dd><code>{capability.snapshot_id}</code></dd></div>
        <div><dt>Capability profile</dt><dd><code>{profile.profile_id}@{profile.profile_version}</code></dd></div>
        <div><dt>Analytics Evidence Snapshot</dt><dd><code>{authority.analytics_evidence_snapshot_id}</code></dd></div>
      </dl>
    </section>
    <div className="confirmation"><p className="eyebrow">НЕАТОМАРНЫЙ ПАКЕТ</p><h3>Кампании исполняются и оцениваются независимо</h3><p>{authority.orchestration.disclosure} Confirmation сохраняет durable authority и timestamp, но не вызывает Direct, не deploy’ит, не запускает показы и не начинает spend.</p></div>
    {gate ? <section className="gate-confirmed" role="status"><strong>Human Decision Gate подтверждён</strong><p>{gate.confirmed_at} · {gate.gate_id}</p><small>External writes performed: {execution ? "YES, independently" : "NO"} · transactionality promised: NO</small></section> : <div className="decision-confirm"><input aria-label="Подтверждаю точный пакет и независимое исполнение кампаний" type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span><strong>Подтверждаю точный reviewed package</strong><small>Authority относится только к package {String(review.package_id).slice(0, 20)}…; каждая выбранная кампания будет dispatch/contain/moderate/evaluate независимо.</small></span></div>}
    {execution && <PackageExecutionPanel
      execution={execution}
      busy={busy}
      canPoll={payload.workflow.allowed_commands.includes("poll_package_moderation")}
      poll={(itemExecutionId) => void apply("poll_package_moderation", undefined, { package_id: execution.package_id, item_execution_id: itemExecutionId })}
      correctionItemIds={corrections.map((correction: Record<string, any>) => String(correction.source?.item_execution_id || ""))}
      startCorrection={(itemExecutionId) => void apply("start_package_correction", undefined, { item_execution_id: itemExecutionId })}
    />}
    {corrections.length > 0 && <PackageCorrectionsPanel
      corrections={corrections}
      fieldRegistry={payload.state.recommendation_set?.field_registry || { fields: [] }}
      busy={busy}
      canPoll={payload.workflow.allowed_commands.includes("poll_package_correction_moderation")}
      apply={apply}
    />}
    <footer className="actions"><span>Ревизия {payload.revision} · independent durable item executions</span><button type="button" className="secondary" disabled={busy} onClick={back}>Назад к shortlist</button>{!gate
      ? <button type="button" disabled={busy || !confirmed} onClick={() => void apply("confirm_package", undefined, { confirmation: "CONFIRM_EXACT_SHORTLIST_PACKAGE", package_review_id: review.package_review_id, package_id: review.package_id })}>Подтвердить authority пакета</button>
      : <button type="button" disabled={busy || !canDispatch} onClick={() => void apply("dispatch_package", undefined, { package_id: gate.package_id, gate_id: gate.gate_id })}>{canDispatch && execution ? "Продолжить безопасное исполнение" : execution ? "Package dispatch зафиксирован" : "Исполнить подтверждённый пакет"}</button>}</footer>
  </>;
}
