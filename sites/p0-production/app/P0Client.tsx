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
            <section className="write-boundary"><span>Готовность внешней записи</span><strong>{payload.write_readiness.ready ? "Готова к подтверждению" : "Заблокирована"}</strong><small>{payload.write_readiness.ready ? "Реальный Direct API · показы останутся выключенными" : payload.write_readiness.blockers[0]}</small></section>
          </aside>

          <section className="artifact">
            {payload.state.last_cascade?.recomputation_status === "PENDING" && <div className="recomputation-pending" role="status"><strong>Идёт downstream recomputation</strong><p>Confirmation и все mutations заблокированы. Обновите данные после завершения пересчёта.</p></div>}
            {payload.state.last_cascade?.recomputation_status === "REQUIRED" && <div className="recomputation-pending" role="status"><strong>Downstream пересчёт обязателен</strong><p>Material Context/Model change уже инвалидировал Strategy, Drafts, shortlist и confirmation. Завершите следующие шаги заново.</p></div>}
            {step === 0 && <ContextStep payload={payload} busy={Boolean(busy)} apply={apply} />}
            {step === 1 && <ModelStep payload={payload} apply={apply} back={() => setStep(0)} />}
            {step === 2 && <StrategyStep payload={payload} apply={apply} back={() => setStep(1)} />}
            {step === 3 && <DraftStep payload={payload} apply={apply} back={() => setStep(2)} />}
            {step === 4 && <ConfirmationStep payload={payload} apply={apply} busy={Boolean(busy)} back={() => setStep(3)} editStrategy={() => setStep(2)} />}
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

function DraftStep({ payload, apply, back }: { payload: Payload; apply: (action: string, value?: Record<string, unknown>) => Promise<void>; back: () => void }) {
  const existing = payload.state.draft || {};
  const recommendationSet = payload.state.recommendation_set || {};
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
    const value = {
      draft_id: String(selected.draft_id || ""),
      ...Object.fromEntries(["campaign_name", "group_name", "negative_keywords", "keyword", "ad_title", "ad_text"].map((name) => [name, fieldValue(form, name)])),
    };
    void apply("save_draft", value);
  }
  return <>
    <ArtifactHead eyebrow="Шаг 4 · Campaign Drafts" title="Campaign Canvas" copy="Ranked cards показывают сравнительный приоритет без predictive claims. Правый drawer редактирует только exact server-supported Direct projection; blocked и hidden Drafts остаются reviewable." />
    {payload.state.recommendation_recalculation?.material_change === true && <section className="recommendation-recalculated" role="status"><strong>Рекомендация пересчитана</strong><p>{payload.state.recommendation_recalculation.message}</p><ul>{payload.state.recommendation_recalculation.changes?.flatMap((change: Record<string, any>) => change.fields?.map((field: Record<string, any>) => <li key={`${change.previous_draft_id}-${change.current_draft_id}-${field.pointer}`}><code>{field.pointer}</code><span>{evidenceValue(field.previous_normalized_value)} → {evidenceValue(field.current_normalized_value)}</span><small>score {change.previous_score ?? "—"} → {change.current_score ?? "—"} · rank {change.previous_rank ?? "—"} → {change.current_rank ?? "—"}</small></li>))}</ul></section>}
    <RecommendationSetDisclosure recommendationSet={recommendationSet} />
    <section className="canvas-controls" aria-label="Фильтры и сортировка Campaign Canvas">
      <label><span>Variant</span><select aria-label="Фильтр variant" value={variantFilter} onChange={(event) => setVariantFilter(event.target.value as typeof variantFilter)}><option value="ALL">Все variants</option><option value="CONTROL">Comparator / control</option><option value="IMPROVEMENT">Improvements</option></select></label>
      <label><span>Evidence</span><select aria-label="Фильтр evidence status" value={evidenceFilter} onChange={(event) => setEvidenceFilter(event.target.value as CampaignCanvasFilters["evidence"])}><option value="ALL">Все evidence statuses</option>{evidenceStatuses.map((status) => <option key={status} value={status}>{status}</option>)}</select></label>
      <label><span>Sort</span><select aria-label="Сортировка Drafts" value={sort} onChange={(event) => setSort(event.target.value as typeof sort)}><option value="RANK">Semantic rank</option><option value="SCORE">Comparative score</option></select></label>
      <label className="show-hidden"><input type="checkbox" checked={includeHidden} onChange={(event) => setIncludeHidden(event.target.checked)} /><span>Показать hidden Drafts с suppression reasons</span></label>
    </section>
    <section className="draft-canvas" aria-label="Ranked Campaign Draft cards">
      {filteredDrafts.map((item: Record<string, any>) => <article key={item.draft_id} className={`draft-card-shell ${item.draft_id === selected?.draft_id ? "selected" : ""}`}>
        <CampaignDraftCard draft={item} selected={item.draft_id === selected?.draft_id} />
        <button type="button" aria-label={`Открыть Draft ${item.draft_id}`} onClick={(event) => openDrawer(item.draft_id, event.currentTarget)}>Открыть точную Direct projection</button>
      </article>)}
      {filteredDrafts.length === 0 && <p className="canvas-empty">Нет Drafts для выбранных deterministic filters. Измените variant/evidence filter; кандидаты остаются в audit.</p>}
    </section>
    {revisionHistory.length > 0 && <details className="hidden-drafts revision-history"><summary>История Strategy и Draft · {revisionHistory.length}</summary><ul>{revisionHistory.map((item: Record<string, any>) => <li key={item.revision}><strong>Ревизия {item.revision} · {item.status}</strong><span>{item.strategy_revision_id}{item.draft_revision_id ? ` · ${item.draft_revision_id}` : " · Draft ещё не зафиксирован"}{item.publish_fingerprint ? ` · ${String(item.publish_fingerprint).slice(0, 12)}…` : ""}</span></li>)}</ul></details>}
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

function ConfirmationStep({ payload, apply, busy, back, editStrategy }: { payload: Payload; apply: (action: string, value?: Record<string, unknown>, extra?: Record<string, unknown>) => Promise<void>; busy: boolean; back: () => void; editStrategy: () => void }) {
  const [confirmed, setConfirmed] = useState(false);
  const campaign = payload.state.campaign;
  if (campaign) {
    return <>
      <ArtifactHead eyebrow="Шаг 5 · Direct readback" title="Реальная кампания создана, показы выключены" copy="MOX-ADV подтвердил состояние в Яндекс Директе после записи." badge={String(campaign.campaign_state || "OFF")} />
      <div className="confirmation"><p className="eyebrow">Production result</p><h3>Показы и списания не начались</h3><p>Campaign ID {campaign.campaign_id} · {campaign.status} · модерация: {campaign.moderation_status}</p></div>
      <Actions revision={payload.revision} label="Создание завершено" disabled back={back} />
    </>;
  }
  const ready = payload.write_readiness.ready;
  const draft = payload.state.draft || {};
  const strategy = payload.state.strategy || {};
  const budgetBlocked = payload.write_readiness.blockers.some((item) => item.includes("Недельный бюджет"));
  const period = strategyAnswer(strategy, "period") || {};
  const weeklyBudget = strategyAnswer(strategy, "weekly_budget");
  const landingPage = strategyAnswer(strategy, "landing_page");
  return <>
    <ArtifactHead eyebrow="Шаг 5 · Human Decision Gate" title="Создать реальную кампанию с выключенными показами" copy="Это единственное критическое решение: после подтверждения модуль выполнит официальный Direct API-контур и проверит non-serving readback." badge={ready ? "READY" : "FAIL CLOSED"} />
    <div className="context-strip"><Metric label="Кампания" value={draft.campaign_name} copy={payload.context.direct.account} /><Metric label="Экспозиция" value={`${weeklyBudget} ₽ / неделю`} copy={`${period.start_date} — ${period.end_date}`} /><Metric label="Посадочная" value={String(landingPage || "—")} copy="Search only · сети выключены" /></div>
    <div className="confirmation"><p className="eyebrow">Обещание безопасности</p><h3>Показы и списания не начнутся</h3><p>Campaigns.add → безусловный suspend → readback SUSPENDED → группа → фраза → объявление → модерация → повторный readback SUSPENDED. Campaigns.resume отсутствует.</p></div>
    {!ready && <ul className="blockers">{payload.write_readiness.blockers.map((item, index) => <li key={item}><span>{index + 1}</span>{item}</li>)}</ul>}
    {ready && <div className="decision-confirm"><input aria-label="Подтверждаю создание реальной кампании" type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span><strong>Подтверждаю создание реальной кампании</strong><small>Кампания появится в аккаунте {payload.context.direct.account}, но показы останутся выключенными.</small></span></div>}
    <footer className="actions"><span>Ревизия {payload.revision} · production write</span><button type="button" className="secondary" disabled={busy} onClick={budgetBlocked ? editStrategy : back}>{budgetBlocked ? "Исправить Strategy" : "Назад"}</button><button type="button" disabled={busy || !ready || !confirmed} onClick={() => void apply("confirm_creation", undefined, { confirmation: "CREATE_NON_SERVING_CAMPAIGN" })}>Создать с выключенными показами</button></footer>
  </>;
}
