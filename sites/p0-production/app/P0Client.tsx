"use client";

/* eslint-disable @typescript-eslint/no-explicit-any -- API payloads are validated server-side and intentionally revisioned. */
import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { weeklyBudgetValidationMessage } from "../lib/direct-limits";

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
    if (!payload) return;
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
      setStep(next.workflow.current_step);
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
              <button disabled={index > maxStep} className={index === step ? "current" : index < payload.workflow.current_step ? "done" : ""} onClick={() => setStep(index)}>
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
            {step === 0 && <ContextStep payload={payload} busy={Boolean(busy)} apply={apply} />}
            {step === 1 && <ModelStep payload={payload} apply={apply} back={() => setStep(0)} />}
            {step === 2 && <StrategyStep payload={payload} apply={apply} back={() => setStep(1)} />}
            {step === 3 && <DraftStep payload={payload} apply={apply} back={() => setStep(2)} />}
            {step === 4 && <ConfirmationStep payload={payload} apply={apply} back={() => setStep(3)} editStrategy={() => setStep(2)} />}
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
  return <section className="evidence-overview" aria-labelledby="evidence-overview-title">
    <header><div><p className="eyebrow">Versioned evidence snapshot</p><h3 id="evidence-overview-title">Краткая сводка аналитики</h3><p>Факты раскрываются до claim и source locator; score и hard blockers не смешиваются.</p></div><strong className={String(evidence.recommendation_status || "").toLowerCase()}>{evidenceStatusLabel(evidence.recommendation_status)}</strong></header>
    <div className="evidence-kpis"><Metric label="Источники" value={`${summary.sources_verified || 0} проверено · ${summary.sources_partial || 0} частично`} copy={`${summary.sources_unavailable || 0} недоступно из ${summary.sources_total || 0}`} /><Metric label="Claims" value={String(summary.claims_supported || 0)} copy="Каждый связан с Evidence Record" /><Metric label="Стоимость до запуска" value={prelaunchCost.status === "HISTORICAL_FIRST_PARTY" ? "First-party history" : "Недоступна"} copy={prelaunchCost.reason || "Wordstat не является CPC forecast"} /></div>
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
    {analyticsEvidence && <AnalyticsEvidencePanel evidence={analyticsEvidence} />}
    <div className="research-strip"><Metric label="Исследовано" value={`${research.pages_analyzed || 1} страниц`} copy="First-party public HTTPS" /><Metric label="Источники" value={String(research.sources?.length || 0)} copy={(research.sources || []).join(" · ")} /><Metric label="Сделано агентом" value={`${research.completed_fields?.length || 0} / 5 полей`} copy="Человеку — подтверждение и разногласия" /></div>
    {model.assumptions?.length > 0 && <div className="assumption"><strong>Где нужна проверка</strong><span>{model.assumptions.join(" · ")}</span></div>}
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

function StrategyStep({ payload, apply, back }: { payload: Payload; apply: (action: string, value?: Record<string, unknown>) => Promise<void>; back: () => void }) {
  const model = payload.state.business_model || {};
  const site = payload.state.site_analysis || {};
  const existing = payload.state.strategy || {};
  const contextGoal = payload.state.context_state?.business_goal_decision?.value || `Получать: ${model.qualified_result}`;
  const minimumWeeklyBudget = Number(payload.context.direct?.minimum_weekly_budget_rub || 1);
  const [weeklyBudget, setWeeklyBudget] = useState(String(existing.weekly_budget_rub || ""));
  const weeklyBudgetError = weeklyBudgetValidationMessage(weeklyBudget, minimumWeeklyBudget);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = Object.fromEntries(["goal", "geography", "period_start", "period_end", "landing_page", "weekly_budget_rub", "target_cpa_rub", "message"].map((name) => [name, fieldValue(form, name)]));
    void apply("save_strategy", value);
  }
  return <>
    <ArtifactHead eyebrow="Шаг 3 · Human Decision Gate" title="Агент подготовил Campaign Strategy" copy="Безопасные поля уже предложены. Человек задаёт только период и денежные границы." />
    <div className="decision-packet"><article><span>1</span><div><strong>Период размещения</strong><p>Укажите допустимое рекламное окно. До решения внешняя запись невозможна.</p></div></article><article><span>2</span><div><strong>Экономика кампании</strong><p>В реальном срезе недостаточно оснований изобретать бюджет и CPA. Зафиксируйте максимальную экспозицию.</p></div></article></div>
    <form className="form two" onSubmit={submit}>
      <label className="wide"><span>Бизнес-цель · подтверждена в Context</span><input name="goal" required readOnly value={existing.goal || contextGoal} /><small>Material change выполняется на шаге «Контекст», где заранее показан каскад invalidation.</small></label>
      <label><span>География</span><select name="geography" defaultValue={existing.geography || "Россия"}><option>Россия</option><option>Москва</option><option>Санкт-Петербург</option></select></label>
      <label><span>Посадочная страница</span><input type="url" name="landing_page" required defaultValue={existing.landing_page || site.url} /></label>
      <label><span>Дата начала</span><input type="date" name="period_start" required defaultValue={existing.period_start || ""} /></label>
      <label><span>Дата окончания</span><input type="date" name="period_end" required defaultValue={existing.period_end || ""} /></label>
      <label><span>Недельный бюджет, ₽</span><input className={weeklyBudgetError ? "field-invalid" : ""} type="number" min={minimumWeeklyBudget} name="weekly_budget_rub" required value={weeklyBudget} aria-invalid={Boolean(weeklyBudgetError)} aria-describedby="weekly-budget-help" onChange={(event) => setWeeklyBudget(event.target.value)} /><small id="weekly-budget-help" className={weeklyBudgetError ? "field-error" : ""} role={weeklyBudgetError ? "alert" : undefined}>{weeklyBudgetError || `Минимум Direct для RUB сейчас: ${minimumWeeklyBudget} ₽ в неделю.`}</small></label>
      <label><span>Целевой CPA, ₽</span><input type="number" min="1" name="target_cpa_rub" required defaultValue={existing.target_cpa_rub || ""} /></label>
      <Field wide label="Основное сообщение" name="message" value={existing.message || model.value} />
      <div className="wide"><Actions revision={payload.revision} label="Принять критические решения" disabled={Boolean(weeklyBudgetError)} back={back} submit /></div>
    </form>
  </>;
}

function DraftStep({ payload, apply, back }: { payload: Payload; apply: (action: string, value?: Record<string, unknown>) => Promise<void>; back: () => void }) {
  const existing = payload.state.draft || {};
  const recommendationSet = payload.state.recommendation_set || {};
  const drafts = Array.isArray(recommendationSet.drafts) ? recommendationSet.drafts : [];
  const visibleDrafts = drafts
    .filter((item: Record<string, any>) => item.visibility === "VISIBLE")
    .sort((left: Record<string, any>, right: Record<string, any>) =>
      Number(left.viability_score?.rank || 999) - Number(right.viability_score?.rank || 999)
      || String(left.draft_id).localeCompare(String(right.draft_id))
    );
  const hiddenDrafts = drafts
    .filter((item: Record<string, any>) => item.visibility === "HIDDEN")
    .sort((left: Record<string, any>, right: Record<string, any>) =>
      Number(left.viability_score?.rank || 999) - Number(right.viability_score?.rank || 999)
      || String(left.draft_id).localeCompare(String(right.draft_id))
    );
  const revisionHistory = (Array.isArray(payload.revision_history) ? payload.revision_history : [])
    .filter((item: Record<string, any>) => item.strategy_revision_id || item.draft_revision_id);
  const [selectedDraftId, setSelectedDraftId] = useState(String(existing.draft_id || visibleDrafts[0]?.draft_id || ""));
  const generated = visibleDrafts.find((item: Record<string, any>) => item.draft_id === selectedDraftId) || visibleDrafts[0] || existing;
  const selected = existing.draft_id === generated.draft_id ? { ...generated, ...existing } : generated;
  const profile = recommendationSet.capability_profile || {};
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = {
      draft_id: String(selected.draft_id || ""),
      ...Object.fromEntries(["campaign_name", "group_name", "keyword", "negative_keywords", "ad_title", "ad_text"].map((name) => [name, fieldValue(form, name)])),
    };
    void apply("save_draft", value);
  }
  return <>
    <ArtifactHead eyebrow="Шаг 4 · Campaign Drafts" title="Детерминированный fan-out Strategy" copy="Одна immutable Strategy revision дала несколько существенно различающихся полных проекций. Варианты с EVIDENCE_GAP доступны для review, но не входят в shortlist и не могут быть опубликованы." />
    <div className="context-strip"><Metric label="Покрытие" value={`${recommendationSet.coverage?.visible_drafts || visibleDrafts.length} review · ${recommendationSet.coverage?.hidden_drafts || hiddenDrafts.length} скрыт`} copy={`${recommendationSet.coverage?.publishable_drafts || 0} доступно для publish; каждый кандидат имеет terminal disposition`} /><Metric label="Direct-профиль" value="Unified · Search" copy={`${profile.search_strategy || "WB_MAXIMUM_CLICKS"} · Network ${profile.network_strategy || "SERVING_OFF"}`} /><Metric label="Безопасный финиш" value="Только SUSPENDED" copy="Явный suspend подтверждается до дочерних записей" /></div>
    <section className="draft-canvas" aria-label="Варианты Campaign Draft">
      {visibleDrafts.map((item: Record<string, any>) => <button type="button" key={item.draft_id} className={item.draft_id === selected.draft_id ? "selected" : ""} aria-pressed={item.draft_id === selected.draft_id} onClick={() => setSelectedDraftId(item.draft_id)}>
        <span className="draft-card-head"><b>{item.variant?.kind === "CONTROL" ? "BASELINE" : "IMPROVEMENT"}</b><em>{item.viability_score?.score ?? "—"}<small>/100</small></em></span>
        <strong>{item.dimensions?.keyword_cluster}</strong>
        <p>{item.dimensions?.offer}</p>
        <small>{item.viability_score?.rank ? `Rank ${item.viability_score.rank} · диапазон ${item.viability_score.score_lower}–${item.viability_score.score_upper}` : "Score заблокирован hard eligibility"}</small>
        <small>{item.market_evidence_status === "EVIDENCE_GAP" ? "REVIEW ONLY · demand evidence отсутствует" : item.market_evidence_status}</small>
      </button>)}
    </section>
    {hiddenDrafts.length > 0 && <details className="hidden-drafts"><summary>Скрытые варианты · {hiddenDrafts.length}</summary><ul>{hiddenDrafts.map((item: Record<string, any>) => <li key={item.draft_id}><strong>{item.dimensions?.keyword_cluster}</strong><span>{item.viability_score?.score ?? "—"}/100 · {item.suppression_reason}</span></li>)}</ul></details>}
    {revisionHistory.length > 0 && <details className="hidden-drafts revision-history"><summary>История Strategy и Draft · {revisionHistory.length}</summary><ul>{revisionHistory.map((item: Record<string, any>) => <li key={item.revision}><strong>Ревизия {item.revision} · {item.status}</strong><span>{item.strategy_revision_id}{item.draft_revision_id ? ` · ${item.draft_revision_id}` : " · Draft ещё не зафиксирован"}{item.publish_fingerprint ? ` · ${String(item.publish_fingerprint).slice(0, 12)}…` : ""}</span></li>)}</ul></details>}
    {selected?.draft_id && <form key={selected.draft_id} className="form two" onSubmit={submit}>
      <div className="wide draft-lineage"><strong>{selected.variant?.kind === "CONTROL" ? "Базовый comparator" : selected.variant?.hypothesis?.changed_family}</strong><span>{selected.strategy_revision_id} · {String(selected.publish_fingerprint || "").slice(0, 18)}…</span><small>{selected.publish_eligibility === "BLOCKED_EVIDENCE_GAP" ? "Publish заблокирован до допустимого demand evidence." : "Score v1 · не прогноз эффективности"}</small></div>
      <ViabilityDisclosure score={selected.viability_score} delta={selected.score_delta} />
      <label><span>Название кампании</span><input name="campaign_name" required defaultValue={selected.campaign_name} /></label>
      <label><span>Название группы объявлений</span><input name="group_name" required defaultValue={selected.group_name} /></label>
      <label className="wide"><span>Ключевая фраза</span><input name="keyword" required defaultValue={selected.keyword} /></label>
      <label className="wide"><span>Минус-фразы</span><input name="negative_keywords" required defaultValue={selected.negative_keywords} /></label>
      <label className="wide"><span>Заголовок объявления</span><input name="ad_title" maxLength={56} required defaultValue={selected.ad_title} /><small>До 56 символов.</small></label>
      <Field wide label="Текст объявления" name="ad_text" maxLength={81} value={selected.ad_text}><small>До 81 символа; слова не обрезаются.</small></Field>
      <div className="wide"><Actions revision={payload.revision} label="Выбрать и зафиксировать проекцию" back={back} submit /></div>
    </form>}
  </>;
}

const viabilityDimensionLabels: Record<string, string> = {
  demand: "Спрос",
  cost: "Стоимость",
  economics: "Экономика",
  offer_audience_fit: "Соответствие",
  direct_feasibility: "Direct",
  measurement: "Измерение",
  evidence_quality: "Evidence",
};

function ViabilityDisclosure({ score, delta }: { score: Record<string, any> | undefined; delta: Record<string, any> | undefined }) {
  const blockers = Array.isArray(score?.eligibility?.blockers) ? score.eligibility.blockers : [];
  if (!score || score.score === null || score.score === undefined) {
    return <section className="wide viability-summary blocked"><strong>Viability score не рассчитан</strong><p>Hard eligibility или обязательный snapshot не пройден. Blocker нельзя компенсировать средним баллом.</p>{blockers.length > 0 && <ul>{blockers.map((item: Record<string, any>) => <li key={`${item.code}-${item.input_pointer}`}>{item.code}: {item.remediation}</li>)}</ul>}</section>;
  }
  const dimensions = Object.entries(score.dimensions || {}) as Array<[string, Record<string, any>]>;
  const deltaValue = delta?.score?.delta;
  return <section className="wide viability-summary" aria-labelledby="viability-score-title">
    <header><div><p className="eyebrow">UNCALIBRATED POLICY V1</p><h3 id="viability-score-title"><strong>{score.score}</strong><span>/100</span></h3></div><div><b>Rank {score.rank}{score.tied_draft_ids?.length > 1 ? " · ничья" : ""}</b><small>Диапазон неопределённости {score.score_lower}–{score.score_upper}</small></div><em>Не прогноз эффективности</em></header>
    <p>Детерминированный сравнительный приоритет eligible Campaign Drafts. Landing audit не участвует; hard blockers оцениваются отдельно.</p>
    {typeof deltaValue === "number" && <div className="score-delta"><strong>После ручной правки: {deltaValue > 0 ? "+" : ""}{deltaValue} балл.</strong><span>Полный пересчёт на тех же frozen inputs и policy.</span></div>}
    <div className="viability-bars">{dimensions.map(([name, item]) => <div key={name}><span>{viabilityDimensionLabels[name] || name}</span><i><b style={{ width: `${Math.max(0, Math.min(100, Number(item.value || 0)))}%` }} /></i><strong>{Math.round(Number(item.value || 0))}</strong><small>{Number(item.weight || 0) * 100}%</small></div>)}</div>
    <details><summary>Почему такой балл · evidence и missing data</summary><div className="viability-detail"><p><strong>Missing dimensions:</strong> {score.explanation?.missing_dimensions?.length ? score.explanation.missing_dimensions.map((item: string) => viabilityDimensionLabels[item] || item).join(" · ") : "нет"}. Unknown получает midpoint 50 только для point score и расширяет bounds, а не становится наблюдаемым фактом.</p>{dimensions.map(([name, item]) => <section key={name}><strong>{viabilityDimensionLabels[name] || name} · {Number(item.weight || 0) * 100}% → {Number(item.weighted_points || 0).toFixed(2)} points</strong><ul>{(item.features || []).map((feature: Record<string, any>, index: number) => <li key={`${name}-${feature.rule}-${index}`}><span>{feature.rule}</span><b>{Math.round(Number(feature.value || 0))} · {feature.status}</b></li>)}</ul></section>)}</div></details>
    <footer><code>{score.contract_version}</code><span>{String(score.fingerprints?.input || "").slice(0, 18)}…</span><span>landing_audit_used=false</span></footer>
  </section>;
}

function ConfirmationStep({ payload, apply, back, editStrategy }: { payload: Payload; apply: (action: string, value?: Record<string, unknown>, extra?: Record<string, unknown>) => Promise<void>; back: () => void; editStrategy: () => void }) {
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
  return <>
    <ArtifactHead eyebrow="Шаг 5 · Human Decision Gate" title="Создать реальную кампанию с выключенными показами" copy="Это единственное критическое решение: после подтверждения модуль выполнит официальный Direct API-контур и проверит non-serving readback." badge={ready ? "READY" : "FAIL CLOSED"} />
    <div className="context-strip"><Metric label="Кампания" value={draft.campaign_name} copy={payload.context.direct.account} /><Metric label="Экспозиция" value={`${strategy.weekly_budget_rub} ₽ / неделю`} copy={`${strategy.period_start} — ${strategy.period_end}`} /><Metric label="Посадочная" value={strategy.landing_page} copy="Search only · сети выключены" /></div>
    <div className="confirmation"><p className="eyebrow">Обещание безопасности</p><h3>Показы и списания не начнутся</h3><p>Campaigns.add → безусловный suspend → readback SUSPENDED → группа → фраза → объявление → модерация → повторный readback SUSPENDED. Campaigns.resume отсутствует.</p></div>
    {!ready && <ul className="blockers">{payload.write_readiness.blockers.map((item, index) => <li key={item}><span>{index + 1}</span>{item}</li>)}</ul>}
    {ready && <div className="decision-confirm"><input aria-label="Подтверждаю создание реальной кампании" type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span><strong>Подтверждаю создание реальной кампании</strong><small>Кампания появится в аккаунте {payload.context.direct.account}, но показы останутся выключенными.</small></span></div>}
    <footer className="actions"><span>Ревизия {payload.revision} · production write</span><button type="button" className="secondary" onClick={budgetBlocked ? editStrategy : back}>{budgetBlocked ? "Исправить Strategy" : "Назад"}</button><button type="button" disabled={!ready || !confirmed} onClick={() => void apply("confirm_creation", undefined, { confirmation: "CREATE_NON_SERVING_CAMPAIGN" })}>Создать с выключенными показами</button></footer>
  </>;
}
