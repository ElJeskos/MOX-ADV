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
import { localizedText, machineLabel } from "./ui-copy.ts";

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
  fixture_acceptance_evidence?: Record<string, any>;
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
        ? "Проверяю точные подключения API и безопасно исследую собственный сайт…"
        : action === "confirm_context_goal"
          ? "Сохраняю решение владельца и начинаю полную аналитику…"
          : action === "dispatch_package"
            ? "Исполняю точный пакет независимо по каждой кампании…"
            : action === "poll_package_moderation" || action === "poll_package_correction_moderation"
              ? "Проверяю один запланированный результат модерации через официальный API Яндекс Директа…"
              : action === "resubmit_package_correction"
                ? "Повторно отправляю только новую подтверждённую редакцию исправления…"
                : "Сохраняю рабочую редакцию…",
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
          <nav aria-label="Основная навигация"><Link className="active" href="/">Стратегия</Link><span>Рабочий модуль · P0</span></nav>
          <div className="ready"><i />Подключение</div>
        </header>
        <main className="page">
          <section className="hero">
            <div><p className="eyebrow">GPT SITES · РАБОЧИЙ МОДУЛЬ · P0</p><h1>Стратегия и создание кампании</h1><p>Агент выполняет всю безопасную работу. Человеку остаются критические решения и существенная неопределённость.</p></div>
            <strong className="real-badge">ТОЛЬКО РЕАЛЬНЫЕ ДАННЫЕ</strong>
          </section>
          <section className="loading-product"><strong>Подключаю рабочий контекст</strong><p>{error || busy}</p></section>
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
        <nav aria-label="Основная навигация"><Link className="active" href="/">Стратегия</Link><span>Рабочий модуль · P0</span></nav>
        <div className={`ready ${payload.context_preflight.ready ? "" : "blocked"}`}><i />{payload.context_preflight.ready ? "Подключения API подтверждены" : "Предварительная проверка заблокирована"}</div>
      </header>

      <main className="page">
        <section className="hero">
          <div><p className="eyebrow">GPT SITES · РАБОЧИЙ МОДУЛЬ · P0</p><h1>Стратегия и создание кампании</h1><p>Агент выполняет всю безопасную работу. Человеку остаются критические решения и существенная неопределённость.</p></div>
          <strong className="real-badge">ТОЛЬКО РЕАЛЬНЫЕ ДАННЫЕ</strong>
        </section>

        {payload.fixture_acceptance_evidence && <FixtureAcceptanceEvidence evidence={payload.fixture_acceptance_evidence} />}

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
            <div className="agent-head"><span>ИИ</span><div><strong>Агент кампании</strong><small>GPT Sites · только рабочие данные</small></div></div>
            <section className="agent-message"><strong>{steps[step]?.label}</strong><p>{[
              "Проверяю точные подключения API, исследую безопасный сайт и предлагаю одну предварительную бизнес-цель.",
              "Показываю готовую модель с доказательствами и уверенностью.",
              "Готовлю стратегию; владелец задаёт только денежные и временные границы.",
              "Компилирую точную проекцию публикации без молчаливо отброшенных полей.",
              "Внешняя запись остаётся закрытой, пока рабочие проверки не готовы.",
            ][step]}</p></section>
            <section className="connections"><h3>Подключённые данные</h3>
              <Connection label="Яндекс Директ" ready={direct.ready === true} detail={direct.ready ? `${direct.account} · привязка подтверждена · ${direct.campaigns_total} кампаний` : direct.blockers?.[0]} />
              <Connection label="Яндекс Метрика" ready={metrika.ready === true} detail={metrika.ready ? `Счётчик ${metrika.counter_id} · цель ${metrika.goal_id} · API` : metrika.blockers?.[0]} />
              <Connection label="Последний реальный срез" ready={Boolean(performance)} detail={performance ? `${performance.period_start} — ${performance.period_end} · ${performance.display_metrics.goal_visits} целей` : "Нет подтверждённого среза"} />
            </section>
            <section className="write-boundary"><span>Контрольное решение человека</span><strong>{payload.state.package_execution ? `Пакет · ${machineLabel(payload.state.package_execution.status)}` : payload.decision_readiness.confirmed ? "Полномочие подтверждено" : payload.state.package_review ? "Пакет проверен" : "Требуется проверка пакета"}</strong><small>{payload.state.package_execution ? `${payload.state.package_execution.dispatched_count}/${payload.state.package_execution.selected_count} независимых исполнений сохранено; атомарная транзакция: нет.` : payload.decision_readiness.confirmed ? "Полномочие готово к независимой отправке элементов." : localizedText(payload.decision_readiness.blockers[0]) || "Точный пакет готов к подтверждению."}</small></section>
          </aside>

          <section className="artifact">
            {payload.state.last_cascade?.recomputation_status === "PENDING" && <div className="recomputation-pending" role="status"><strong>Идёт пересчёт зависимых данных</strong><p>Подтверждение и все изменения заблокированы. Обновите данные после завершения пересчёта.</p></div>}
            {payload.state.last_cascade?.recomputation_status === "REQUIRED" && <div className="recomputation-pending" role="status"><strong>Пересчёт зависимых данных обязателен</strong><p>Существенное изменение контекста или модели уже отменило стратегию, черновики, список и подтверждение. Завершите следующие шаги заново.</p></div>}
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

function FixtureAcceptanceEvidence({ evidence }: { evidence: Record<string, any> }) {
  return <section className="fixture-acceptance-banner">
    <strong>ДЕТЕРМИНИРОВАННЫЙ СТЕНД ПРОВАЙДЕРА · БЕЗ ВНЕШНЕЙ СЕТИ И ДЕНЕГ</strong>
    <span>Проверочный стенд доступен только локально; рабочие подключения и учётные данные не загружены.</span>
    <details aria-label="Доказательства проверочного стенда провайдера">
      <summary>Машиночитаемые доказательства приёмки · {evidence.calls?.length || 0} вызовов провайдера</summary>
      <pre>{JSON.stringify(evidence, null, 2)}</pre>
    </details>
  </section>;
}

function Connection({ label, ready, detail }: { label: string; ready: boolean; detail?: string }) {
  return <div className={`connection ${ready ? "" : "blocked"}`}><i /><div><strong>{label}</strong><small>{detail || "Не готово"}</small></div></div>;
}

function ArtifactHead({ eyebrow, title, copy, badge = "РЕАЛЬНЫЕ ДАННЫЕ" }: { eyebrow: string; title: string; copy: string; badge?: string }) {
  return <header className="artifact-head"><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2><p>{copy}</p></div><strong>{badge}</strong></header>;
}

function Actions({ revision, label, disabled, back, submit }: { revision: number; label: string; disabled?: boolean; back?: () => void; submit?: boolean }) {
  return <footer className="actions"><span>Ревизия {revision} · только рабочие данные</span>{back && <button type="button" className="secondary" onClick={back}>Назад</button>}<button type={submit ? "submit" : "button"} disabled={disabled}>{label}</button></footer>;
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
    <ArtifactHead eyebrow="Шаг 1 · предварительная проверка рабочего контура" title="Контекст и предварительная бизнес-цель" copy="До полной аналитики модуль проверяет точные подключения официальных API, безопасно исследует собственный сайт и просит одно явное решение владельца." badge={preflight.ready ? "ПОДКЛЮЧЕНИЯ ПОДТВЕРЖДЕНЫ" : "БЕЗОПАСНО ЗАБЛОКИРОВАНО"} />
    <div className="context-strip"><Metric label="Директ" value={payload.context.direct.ready ? payload.context.direct.account : "Не готов"} copy={payload.context.direct.ready ? `Метод clients.get подтвердил аккаунт · ${payload.context.direct.campaigns_total} кампаний` : preflight.blockers[0]} /><Metric label="Метрика" value={payload.context.metrika.ready ? `Счётчик ${payload.context.metrika.counter_id}` : "Не готова"} copy={payload.context.metrika.ready ? `Цель ${payload.context.metrika.goal_id} подтверждена управляющим API` : preflight.blockers[0]} /><Metric label="Сайт" value={analysis ? analysis.title || analysis.url : "Нужен публичный HTTPS URL"} copy={analysis ? `${analysis.research?.pages_analyzed || 1} страниц собственного сайта · ограниченное исследование` : "Частные и локальные адреса, а также небезопасные перенаправления отклоняются"} /></div>
    {!preflight.ready && <div className="preflight-blocked"><strong>Продолжение заблокировано</strong><ul>{preflight.blockers.map((item) => <li key={item}>{localizedText(item)}</li>)}</ul><small>Учётные данные остаются только на сервере и не передаются в это состояние.</small></div>}
    <form className="form" onSubmit={submitResearch}>
      <label className="wide"><span>Публичный сайт бизнеса</span><input type="text" inputMode="url" name="url" required defaultValue={analysis?.url || ""} placeholder="example.ru или https://example.ru/" /><small>HTTPS добавляется технически; адреса с учётными данными, частные, локальные и служебные адреса, небезопасные перенаправления и превышение лимитов отклоняются до исследования.</small></label>
      {analysis && <div className="material-impact"><strong>До существенного изменения контекста</strong><p>Будут затронуты: {payload.context_change_policy.affected_steps.map((item) => item.label).join(" → ")}. Подтверждение заблокируется до пересчёта. Пробелы и техническая нормализация URL сами по себе ничего не отменяют.</p></div>}
      <div className="agent-work"><strong>Что агент сделает сам до полной аналитики</strong><p>Проверит точные полномочия аккаунта, счётчика и цели через официальные API, обойдёт не более шести страниц собственного сайта в заданных пределах и предложит ровно одну цель на основе доказательств.</p></div>
      <Actions revision={payload.revision} label={analysis ? "Повторно проверить контекст" : "Проверить контекст и предложить цель"} disabled={busy || !preflight.ready} submit />
    </form>
    {contextState && <form key={`${payload.revision}-${contextState.status}`} className="goal-decision" onSubmit={submitGoal}>
      <header><div><p className="eyebrow">Одна предварительная бизнес-цель</p><h3>{contextState.status === "GOAL_CONFIRMED" ? "Решение владельца сохранено" : "Подтвердите или исправьте до полной аналитики"}</h3></div><strong>{contextState.status === "GOAL_CONFIRMED" ? "ПОДТВЕРЖДЕНО ВЛАДЕЛЬЦЕМ" : "ПРЕДВАРИТЕЛЬНО"}</strong></header>
      <label><span>Бизнес-цель</span><textarea name="goal" required maxLength={500} defaultValue={goal} /></label>
      <blockquote>{contextState.provisional_business_goal.rationale}</blockquote>
      {contextState.status === "GOAL_CONFIRMED" && <div className="material-impact"><strong>Перед изменением подтверждённой цели</strong><p>Существенная правка затронет: {payload.context_change_policy.affected_steps.map((item) => item.label).join(" → ")}. Техническая нормализация пробелов не отменяет решения.</p></div>}
      {contextState.last_material_change && <p className="invalidation-note">Происхождение зависимых данных сохранено в истории проверки; стратегия, набор рекомендаций, черновики кампаний, список и подтверждение отменены.</p>}
      <Actions revision={payload.revision} label={contextState.status === "GOAL_CONFIRMED" ? "Сохранить цель контекста" : "Подтвердить цель и продолжить анализ"} disabled={busy || !preflight.ready} submit />
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
    <summary aria-label={`Раскрыть утверждение ${claim.predicate}`}><strong>{claim.predicate}</strong><span>{machineLabel(claim.classification)} · {machineLabel(claim.confidence?.tier)}</span></summary>
    <div className="evidence-claim-body">
      <p><strong>Нормализованное утверждение:</strong> {evidenceValue(claim.normalized?.value ?? claim.value).slice(0, 500)}</p>
      <dl className="claim-confidence"><div><dt>Качество</dt><dd>{machineLabel(claim.confidence?.quality)}</dd></div><div><dt>Свежесть</dt><dd>{machineLabel(claim.confidence?.freshness)}</dd></div><div><dt>Согласованность</dt><dd>{machineLabel(claim.confidence?.consistency)}</dd></div><div><dt>Покрытие</dt><dd>{machineLabel(claim.confidence?.coverage)}</dd></div><div><dt>Неопределённость</dt><dd>{claim.confidence?.uncertainty?.length || 0}</dd></div></dl>
      <code>{claim.claim_id}</code>
      {linkedRecords.map((record) => <details className="evidence-record" key={record.evidence_id}>
        <summary aria-label={`Раскрыть запись доказательства ${record.evidence_id}`}><strong>Запись доказательства · {record.source_kind}</strong><span>{record.observed_at || "дата наблюдения недоступна"}</span></summary>
        <div>
          {record.raw?.quote && <blockquote>«{record.raw.quote}»</blockquote>}
          <p><strong>Ограниченное исходное значение</strong><code>{evidenceValue(record.raw?.value)}</code></p>
          <p><strong>Исходный указатель</strong><code>{evidenceValue(record.source_locator)}</code></p>
          <p><strong>Метаданные преобразований</strong><code>{evidenceValue(record.transforms)}</code></p>
          <p><strong>Версии и хеши</strong><code>{evidenceValue({ versions: record.versions, extraction: record.extraction, raw_sha256: record.raw?.sha256, record_hash: record.record_hash })}</code></p>
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
    <header><div><p className="eyebrow">Версионный снимок доказательств</p><h3 id="evidence-overview-title">Краткая сводка аналитики</h3><p>Факты раскрываются до утверждения и указателя источника; оценка и жёсткие блокирующие причины не смешиваются.</p></div><strong className={String(evidence.recommendation_status || "").toLowerCase()}>{evidenceStatusLabel(evidence.recommendation_status)}</strong></header>
    <div className="evidence-kpis"><Metric label="Источники" value={`${summary.sources_verified || 0} проверено · ${summary.sources_partial || 0} частично`} copy={`${summary.sources_unavailable || 0} недоступно из ${summary.sources_total || 0}`} /><Metric label="Утверждения" value={String(summary.claims_supported || 0)} copy="Каждое связано с записью доказательства" /><Metric label="Стоимость до запуска" value={prelaunchCost.status === "AVAILABLE" ? String(prelaunchCost.compact_source || "Подходящий источник") : "Недоступна"} copy={prelaunchCost.status === "AVAILABLE" ? `${prelaunchCost.range?.low}–${prelaunchCost.range?.high} ${prelaunchCost.currency} · НДС ${prelaunchCost.vat_treatment}` : "Нет подходящего сопоставимого источника"} /></div>
    {marketEvidence && <MarketEvidenceDisclosure evidence={marketEvidence} context="model" />}
    <dl className="confidence-vector" aria-label="Измерения уверенности"><div><dt>Качество</dt><dd>{machineLabel(confidence.quality)}</dd></div><div><dt>Свежесть</dt><dd>{machineLabel(confidence.freshness)}</dd></div><div><dt>Согласованность</dt><dd>{machineLabel(confidence.consistency)}</dd></div><div><dt>Покрытие</dt><dd>{machineLabel(confidence.coverage)}</dd></div><div><dt>Неопределённость</dt><dd>{uncertainties.length}</dd></div></dl>
    <div className="evidence-source-grid">{sources.map((source: Record<string, any>) => <details key={source.source_id} className={`evidence-source ${String(source.status || "").toLowerCase()}`}><summary><span /><div><strong>{localizedText(source.title)}</strong><small>{sourceStatusLabel(source.status)}</small></div></summary><div className="evidence-source-body">{source.facts?.length > 0 && <ul>{source.facts.map((fact: string) => <li key={fact}>{localizedText(fact)}</li>)}</ul>}{source.limitations?.length > 0 && <ul className="limitations">{source.limitations.map((item: string) => <li key={item}>{localizedText(item)}</li>)}</ul>}<code>{source.source_kind} · {source.observed_at || "дата наблюдения недоступна"}</code></div></details>)}</div>
    {blockers.length > 0 && <section className="evidence-blockers" aria-labelledby="evidence-hard-blockers"><strong id="evidence-hard-blockers">Жёсткие блокирующие причины оцениваются отдельно от балла</strong><ul>{blockers.map((item: string) => <li key={item}>{localizedText(item)}</li>)}</ul></section>}
    <div className="evidence-separate-grid">
      <section className="evidence-missing" aria-labelledby="evidence-missing-title"><strong id="evidence-missing-title">Недостающие доказательства</strong>{gaps.length ? <ul>{gaps.map((gap: Record<string, any>) => <li key={gap.gap_id}><b>{gap.material ? "СУЩЕСТВЕННО" : "ПРОБЕЛ"}</b>{localizedText(gap.description)}</li>)}</ul> : <p>Не зафиксировано.</p>}</section>
      <section className="evidence-conflicts" aria-labelledby="evidence-conflicts-title"><strong id="evidence-conflicts-title">Противоречия</strong>{conflicts.length ? <ul>{conflicts.map((conflict: Record<string, any>) => <li key={conflict.conflict_id}><b>{conflict.material ? "СУЩЕСТВЕННО" : machineLabel(conflict.relation)}</b>{localizedText(conflict.predicate)} · {localizedText(conflict.resolution)}</li>)}</ul> : <p>Неразрешённых конфликтов нет.</p>}</section>
    </div>
    {uncertainties.length > 0 && <div className="evidence-uncertainty"><strong>Неопределённость раскрыта, а не заполнена догадкой</strong><ul>{uncertainties.slice(0, 5).map((item: string) => <li key={item}>{localizedText(item)}</li>)}</ul></div>}
    <details className="evidence-index"><summary aria-label="Раскрыть указатель доказательств">Указатель доказательств · утверждение → запись доказательства → ограниченный исходный указатель и значение · {claims.length} утверждений · {records.length} записей</summary><div>{claims.map((claim: Record<string, any>) => <EvidenceClaimDisclosure key={claim.claim_id} claim={claim} records={records} />)}</div></details>
    <footer><code>{String(evidence.snapshot_id || "")}</code><span>создано {evidence.generated_at}</span><span>актуально на {evidence.as_of}</span><span>{evidence.schema_version}</span></footer>
  </section>;
}

function BusinessModelSummary({ model }: { model: Record<string, any> }) {
  return <section className="business-model-summary" aria-labelledby="business-model-summary-title"><header><p className="eyebrow">Модель бизнеса</p><h3 id="business-model-summary-title">Краткая модель бизнеса</h3></header><div><Metric label="Предложение" value={model.product || "Доказательство отсутствует"} copy={model.value || "Ценность не подтверждена"} /><Metric label="Аудитория" value={model.audience || "Доказательство отсутствует"} copy={model.exclusions || "Исключения не подтверждены"} /><Metric label="Квалифицированный результат" value={model.qualified_result || "Доказательство отсутствует"} copy="Подтверждение владельца хранится отдельно от доказательств собственного сайта" /></div></section>;
}

const landingDimensionLabels: Record<string, string> = {
  OFFER_MESSAGE_MATCH: "Соответствие предложения сообщению",
  CTA_ACTION: "Призыв к целевому действию",
  FORMS: "Формы",
  MEASUREMENT_READINESS: "Готовность измерения",
  TECHNICAL_ACCESS: "Техническая доступность",
  PERFORMANCE: "Быстродействие",
  ACCESSIBILITY: "Доступность интерфейса",
  OBSERVED_METRIKA_BEHAVIOR: "Наблюдаемое поведение Метрики",
};

function LandingAdvisoryPanel({ run }: { run: Record<string, any> | null }) {
  const priorities = landingAdvisoryPriorities(run);
  const findings = Array.isArray(run?.findings) ? run.findings : [];
  const coverage = Array.isArray(run?.coverage) ? run.coverage : [];
  const insufficient = !run || run.status === "INSUFFICIENT_EVIDENCE" || run.status === "SAFETY_BLOCKED" || coverage.some((item: Record<string, any>) => item.evidence_status === "INSUFFICIENT_EVIDENCE");
  return <section className="landing-advisory" aria-labelledby="landing-advisory-title">
    <header><div><p className="eyebrow">ПОСАДОЧНАЯ СТРАНИЦА · ТОЛЬКО РЕКОМЕНДАЦИИ</p><h3 id="landing-advisory-title">Рекомендации по посадочной странице</h3><p>Неблокирующий анализ точной редакции стратегии. Выводы не меняют допустимость, готовность к публикации, оценку, место, пороги, калибровку или отпечаток публикации.</p></div><strong>РЕКОМЕНДАЦИИ · НЕ БЛОКИРУЮТ</strong></header>
    {!run && <div className="advisory-insufficient" role="status"><strong>Недостаточно доказательств</strong><p>Сначала утвердите редакцию стратегии кампании. Отсутствие выводов по посадочной странице не считается успехом и не блокирует решения о публикации.</p></div>}
    {run && <>
      <div className="advisory-lineage"><span>{run.strategy_revision_id}</span><code>{run.final_url || run.requested_url}</code><b>{machineLabel(run.status)}</b></div>
      {insufficient && <div className="advisory-insufficient" role="status"><strong>Недостаток доказательств раскрыт явно</strong><p>Неполные запуски инструментов, покрытие Метрики и элементы ручной проверки не превращены в ноль, успех или факт.</p></div>}
      <section className="advisory-priorities" aria-label="До трёх приоритетных рекомендаций по посадочной странице"><h4>Приоритеты · максимум 3</h4>{priorities.length ? <ol>{priorities.map((item) => <li key={item.finding_id}><span>{landingDimensionLabels[item.dimension] || item.dimension}</span><strong>{localizedText(item.title)}</strong><small>{machineLabel(item.type)} · {machineLabel(item.evidence_status)}</small></li>)}</ol> : <p>Детерминированных приоритетов нет. Это не означает доказанное отсутствие проблем.</p>}</section>
      <details className="advisory-details"><summary>Все подробности · типы доказательств, состояния и версии инструментов</summary><div className="advisory-tools"><code>{JSON.stringify({ required: run.tools?.required, observed: run.tools?.observed, version_status: run.tools?.version_status })}</code><p>Lighthouse: {run.lighthouse?.runs?.length || 0}/5 последовательных запусков для компьютера · медиана: {run.lighthouse?.median ? "доступна" : "недостаточно доказательств"}</p><p>Незавершённые проверки axe-core: {run.axe?.categories?.incomplete?.count ?? "недоступно"} · {localizedText(run.axe?.manual_review?.disclosure)}</p></div><ul>{findings.map((item: Record<string, any>) => <li key={item.finding_id}><header><strong>{landingDimensionLabels[item.dimension] || item.dimension}</strong><span>{machineLabel(item.type)} · {machineLabel(item.evidence_status)}</span></header><p>{localizedText(item.title)}</p><small>{localizedText(item.detail)}</small></li>)}</ul></details>
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
    <ArtifactHead eyebrow="Шаг 2 · агентное исследование" title="Агент уже собрал модель бизнеса" copy="Сначала — краткая сводка, затем раскрываемые доказательства. Исправьте только неверную гипотезу или факт, которого действительно нет в разрешённых источниках." badge="ИССЛЕДОВАНИЕ АГЕНТА" />
    <BusinessModelSummary model={model} />
    <LandingAdvisoryPanel run={payload.state.landing_advisory_run || null} />
    {analyticsEvidence && <AnalyticsEvidencePanel evidence={analyticsEvidence} />}
    <div className="research-strip"><Metric label="Исследовано" value={`${research.pages_analyzed || 1} страниц`} copy="Публичный HTTPS собственного сайта" /><Metric label="Источники" value={String(research.sources?.length || 0)} copy={(research.sources || []).join(" · ")} /><Metric label="Сделано агентом" value={`${research.completed_fields?.length || 0} / 5 полей`} copy="Человеку — подтверждение и разногласия" /></div>
    {model.assumptions?.length > 0 && <div className="assumption"><strong>Где нужна проверка</strong><span>{model.assumptions.map((item: string) => localizedText(item)).join(" · ")}</span></div>}
    {payload.state.strategy && <div className="material-impact"><strong>До существенного изменения модели</strong><p>Стратегия, набор рекомендаций, черновики кампаний, список и подтверждение будут отменены. Пробелы и техническая нормализация значений не запускают каскад.</p></div>}
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
    <span>Рекомендация агента</span><strong>{String(display)}</strong><p>{localizedText(field.explanation)}</p>
    <footer><b>{field.source_category}</b><em>{field.status}</em></footer>
    {field.prepared_decision && <div className="prepared-decision"><strong>{localizedText(field.prepared_decision.question)}</strong><ul>{field.prepared_decision.consequences.map((item: string) => <li key={item}>{localizedText(item)}</li>)}</ul></div>}
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
    : "Минимум Яндекс Директа недоступен; утверждение заблокировано без доказуемого ограничения площадки.";
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
    if (fieldId === "geography") return <select name={fieldId} required defaultValue={String(value)}><option value="" disabled>Выберите географию, заданную владельцем</option><option>Россия</option><option>Москва</option><option>Санкт-Петербург</option></select>;
    if (fieldId === "period") return <div className="period-inputs"><label><span>Начало</span><input type="date" name="period_start" required defaultValue={String(existingPeriod?.start_date || "")} /></label><label><span>Окончание</span><input type="date" name="period_end" required defaultValue={String(existingPeriod?.end_date || "")} /></label></div>;
    if (fieldId === "landing_page") return <input type="url" name={fieldId} required defaultValue={String(value)} />;
    if (fieldId === "weekly_budget") return <><input className={weeklyBudgetError ? "field-invalid" : ""} type="number" {...(minimumWeeklyBudgetAvailable ? { min: minimumWeeklyBudget } : {})} name={fieldId} required value={weeklyBudget} aria-invalid={Boolean(weeklyBudgetError)} aria-describedby="weekly-budget-help" onChange={(event) => setWeeklyBudget(event.target.value)} /><small id="weekly-budget-help" className={weeklyBudgetError ? "field-error" : ""} role={weeklyBudgetError ? "alert" : undefined}>{weeklyBudgetError || `Минимум Яндекс Директа: ${minimumWeeklyBudget} ₽; это ограничение, а не рекомендация.`}</small></>;
    return <input type="number" min="1" name={fieldId} required defaultValue={String(value)} />;
  };
  return <>
    <ArtifactHead eyebrow="Шаг 3 · одно утверждение" title="Фиксированная анкета стратегии кампании" copy="Все 11 полей всегда идут в одном порядке. Агент рекомендует только доказуемое; пробелы, зависящие от владельца, остаются подготовленными решениями без значений по умолчанию." />
    {existing.strategy_revision_id && <div className="material-impact"><strong>До существенного изменения стратегии</strong><p>Будет создана новая неизменяемая редакция стратегии, набор рекомендаций детерминированно пересоберётся, черновики кампаний и список очистятся, а подтверждение останется заблокированным до завершения пересчёта. Пробелы и техническая нормализация не запускают каскад.</p></div>}
    <form className="strategy-form" onSubmit={submit}>
      <ol className="strategy-questionnaire" aria-label="Анкета стратегии кампании">
        {fields.map((item: Record<string, any>, index: number) => <li key={item.field_id} data-strategy-field={item.field_id}>
          <header><span>{index + 1}</span><strong>{strategyFieldLabels[item.field_id] || item.field_id}</strong><code>{item.field_id}</code></header>
          <StrategyRecommendation field={item} />
          <div className="strategy-answer"><span>Утверждаемое значение</span>{inputFor(item.field_id)}</div>
        </li>)}
      </ol>
      <footer className="actions"><span>Ревизия {payload.revision} · анкета {questionnaire.contract_version}</span><button type="button" className="secondary" onClick={back}>Назад</button><button type="submit" disabled={Boolean(weeklyBudgetError) || fields.length !== 11}>Утвердить всю стратегию кампании</button></footer>
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
    <ArtifactHead eyebrow="Шаг 4 · черновики кампаний" title="Полотно кампаний" copy="Карточки по местам показывают сравнительный приоритет без прогнозных утверждений. Правая панель редактирует только точную проекцию Яндекс Директа, поддержанную сервером; заблокированные и скрытые черновики остаются доступными для проверки." />
    {payload.state.recommendation_recalculation?.material_change === true && <section className="recommendation-recalculated" role="status">
      <strong>Рекомендация пересчитана</strong><p>{localizedText(payload.state.recommendation_recalculation.message)}</p>
      <ul>{payload.state.recommendation_recalculation.changes?.map((change: Record<string, any>) => <li key={`${change.change_type}-${change.previous_draft_id}-${change.current_draft_id}`}>
        <strong>{change.change_type} · {change.previous_draft_id || "—"} → {change.current_draft_id || "—"}</strong>
        <small>оценка {change.previous_score ?? "—"} → {change.current_score ?? "—"} · место {change.previous_rank ?? "—"} → {change.current_rank ?? "—"}</small>
        {(change.fields || []).length > 0
          ? <ul>{change.fields.map((field: Record<string, any>) => <li key={field.pointer}><code>{field.pointer}</code><span>{evidenceValue(field.previous_normalized_value)} → {evidenceValue(field.current_normalized_value)}</span></li>)}</ul>
          : <span>Без соответствующего существенного изменения проекции Яндекс Директа.</span>}
      </li>)}</ul>
    </section>}
    <RecommendationSetDisclosure recommendationSet={recommendationSet} />
    <section className="canvas-controls" aria-label="Фильтры и сортировка полотна кампаний">
      <label><span>Вариант</span><select aria-label="Фильтр вариантов" value={variantFilter} onChange={(event) => setVariantFilter(event.target.value as typeof variantFilter)}><option value="ALL">Все варианты</option><option value="CONTROL">Контрольные варианты</option><option value="IMPROVEMENT">Улучшения</option></select></label>
      <label><span>Доказательства</span><select aria-label="Фильтр состояния доказательств" value={evidenceFilter} onChange={(event) => setEvidenceFilter(event.target.value as CampaignCanvasFilters["evidence"])}><option value="ALL">Все состояния доказательств</option>{evidenceStatuses.map((status) => <option key={status} value={status}>{machineLabel(status)}</option>)}</select></label>
      <label><span>Сортировка</span><select aria-label="Сортировка черновиков" value={sort} onChange={(event) => setSort(event.target.value as typeof sort)}><option value="RANK">Смысловое место</option><option value="SCORE">Сравнительная оценка</option></select></label>
      <label className="show-hidden"><input type="checkbox" checked={includeHidden} onChange={(event) => setIncludeHidden(event.target.checked)} /><span>Показать скрытые черновики с причинами скрытия</span></label>
    </section>
    <section className="draft-canvas" aria-label="Карточки черновиков кампаний по местам">
      {filteredDrafts.map((item: Record<string, any>) => {
        const control = shortlistControlByDraft.get(item.draft_id);
        const shortlistAction = control?.status === "SELECTED"
          ? "remove_from_shortlist"
          : control?.status === "REMOVED"
            ? "restore_to_shortlist"
            : "add_to_shortlist";
        const shortlistLabel = control?.status === "SELECTED"
          ? "Исключить из списка"
          : control?.status === "REMOVED"
            ? "Вернуть в список"
            : "Добавить в список";
        return <article key={item.draft_id} className={`draft-card-shell ${item.draft_id === selected?.draft_id ? "selected" : ""}`}>
          <CampaignDraftCard draft={item} selected={item.draft_id === selected?.draft_id} />
          <div className="draft-card-actions">
            <button type="button" aria-label={`${shortlistLabel}: ${item.draft_id}`} disabled={!control || control.status === "BLOCKED"} onClick={() => void apply(shortlistAction, undefined, { draft_id: item.draft_id })}>{shortlistLabel}</button>
            <button type="button" aria-label={`Открыть черновик ${item.draft_id}`} onClick={(event) => openDrawer(item.draft_id, event.currentTarget)}>Открыть точную проекцию Яндекс Директа</button>
          </div>
          {control?.status === "BLOCKED" && <small className="shortlist-disabled-reason" role="status">Список недоступен: {localizedText(control.disabled_reason)}</small>}
        </article>;
      })}
      {filteredDrafts.length === 0 && <p className="canvas-empty">Нет черновиков для выбранных детерминированных фильтров. Измените фильтр варианта или доказательств; кандидаты остаются в истории проверки.</p>}
    </section>
    {revisionHistory.length > 0 && <details className="hidden-drafts revision-history"><summary>История стратегии и черновиков · {revisionHistory.length}</summary><ul>{revisionHistory.map((item: Record<string, any>) => <li key={item.revision}><strong>Ревизия {item.revision} · {machineLabel(item.status)}</strong><span>{item.strategy_revision_id}{item.draft_revision_id ? ` · ${item.draft_revision_id}` : " · черновик ещё не зафиксирован"}{item.publish_fingerprint ? ` · ${String(item.publish_fingerprint).slice(0, 12)}…` : ""}</span></li>)}</ul></details>}
    <section className="shortlist-footer" aria-label="Постоянная сводка списка">
      <div><p className="eyebrow">УПОРЯДОЧЕННЫЙ СПИСОК · {shortlistSelections.length}</p><strong>{shortlistSelections.length ? "Точный пакет выбранных черновиков кампаний" : "Добавьте готовые к публикации черновики"}</strong><small>Нижняя панель не зависит от фильтров карточек. Порядок выбора фиксируется в полномочии пакета.</small></div>
      <ol>{shortlistSelections.map((item: Record<string, any>) => <li key={item.draft_id}><span>{item.draft_revision_id}</span><code>{String(item.publish_fingerprint || "").slice(0, 18)}…</code></li>)}</ol>
      <button type="button" disabled={!shortlistSelections.length} onClick={() => payload.state.package_review ? openReview() : void apply("review_package")}>{payload.state.package_review ? "Открыть текущую проверку пакета" : "Создать проверку пакета"}</button>
    </section>
    {payload.state.last_decision_invalidation && !payload.state.package_review && <p className="decision-invalidation" role="status"><strong>Предыдущее полномочие отменено:</strong> {localizedText(payload.state.last_decision_invalidation.reason)}</p>}
    <footer className="actions"><span>{filteredDrafts.length} черновиков на полотне · {drafts.length} сохранённых кандидатов</span><button type="button" className="secondary" onClick={() => void apply("recalculate_recommendations")}>Проверить действующую сводку правил</button><button type="button" className="secondary" onClick={back}>Назад</button></footer>
    {drawerOpen && selected?.draft_id && <div className="drawer-layer">
      <aside ref={drawerRef} className="campaign-drawer" role="dialog" aria-modal="true" aria-labelledby="campaign-drawer-title">
        <header className="drawer-head"><div><p className="eyebrow">ЧЕРНОВИК КАМПАНИИ · ПРОВЕРКА</p><h2 id="campaign-drawer-title">Точная будущая проекция Яндекс Директа</h2><span>{selected.draft_revision_id} · {String(selected.publish_fingerprint || "")}</span></div><button ref={closeButtonRef} type="button" aria-label="Закрыть панель" onClick={closeDrawer}>×</button></header>
        <div className="drawer-scroll">
          <div className="draft-lineage"><strong>{selected.variant?.kind === "CONTROL" ? machineLabel(selected.variant?.control_basis?.kind) : machineLabel(selected.variant?.hypothesis?.changed_family)}</strong><span>{selected.strategy_revision_id} · {selected.draft_revision_id}</span><small>{selected.playbook_release_id || "безопасно заблокировано"}@{selected.playbook_release_version || "—"} · {selected.capability_profile_id}@{selected.capability_profile_version}</small></div>
          <DraftPublicationBlockers draft={selected} />
          {!selectedShortlistEligible && <div className="preflight-blocked"><strong>Проверка доступна · готовность к публикации заблокирована</strong><p>Жёсткую блокирующую причину, скрытое состояние или неразрешённый пробел в доказательствах нельзя обойти оценкой, правкой или предварительным списком.</p></div>}
          <DraftEditFeedback draft={selected} />
          <ViabilityScoreDisclosure score={selected.viability_score} delta={selected.score_delta} />
          {selected.market_evidence && <MarketEvidenceDisclosure evidence={selected.market_evidence} context="draft" />}
          <form key={`${selected.draft_id}-${selected.draft_revision_id}-${payload.revision}`} className="drawer-form" onSubmit={submit}>
            <DraftFieldRegistryDisclosure registry={recommendationSet.field_registry} draft={selected} />
            <Actions revision={payload.revision} label={selectedShortlistEligible ? "Сохранить существенную редакцию" : "Сохранить проверочные правки без готовности к публикации"} submit />
          </form>
        </div>
      </aside>
    </div>}
  </>;
}

const executionProgressLabels = {
  validation: "Проверка",
  creation: "Создание",
  suspension: "Остановка",
  child_graph: "Дочерние объекты",
  readback: "Обратная проверка",
  moderation: "Модерация",
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
  return <section className="package-executions" aria-label="Исполнения кампаний пакета">
    <header><div><p className="eyebrow">СОХРАНЯЕМЫЕ НЕЗАВИСИМЫЕ ИСПОЛНЕНИЯ</p><h3>Результат каждого черновика кампании сохранён отдельно</h3><p>Вердикт пакета: {machineLabel(execution.verdict, "Ожидает")} · состояние: {machineLabel(execution.status)}. Успех появляется только после полной отчётности по всему выбранному набору.</p></div><strong>{execution.dispatched_count}/{execution.selected_count}</strong></header>
    <ol>{items.map((item: Record<string, any>) => <li key={item.item_execution_id} className={`package-execution-item ${String(item.ownership || "unknown").toLowerCase()}`}>
      <header><div><span>#{Number(item.position) + 1}</span><strong>{item.selection?.draft_revision_id}</strong><code>{item.item_execution_id}</code></div><div><b>{machineLabel(item.status)}</b><small>Ответственная сторона · {machineLabel(item.ownership)}</small></div></header>
      <dl className="execution-progress">{Object.entries(executionProgressLabels).map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{machineLabel(item.progress?.[key], "Ожидает")}</dd></div>)}</dl>
      <div className="execution-identifiers"><span>Кампания <code>{item.provider_ids?.campaign_id || "—"}</code></span><span>Группы объявлений <code>{item.provider_ids?.ad_group_ids?.join(", ") || item.provider_ids?.ad_group_id || "—"}</code></span><span>Ключевые фразы <code>{item.provider_ids?.keyword_ids?.join(", ") || item.provider_ids?.keyword_id || "—"}</code></span><span>Объявления <code>{item.provider_ids?.ad_ids?.join(", ") || "—"}</code></span></div>
      {item.accountability && <dl className="execution-progress"><div><dt>Граф объектов</dt><dd>{item.accountability.supported_graph_verified ? "Проверен" : "Ожидает"}</dd></div><div><dt>Показы</dt><dd>{item.accountability.campaign_suspended ? "Остановлены" : "Не подтверждено"}</dd></div><div><dt>Объявления завершены</dt><dd>{item.accountability.all_ads_terminal ? "Да" : "Нет"}</dd></div><div><dt>Принято Директом</dt><dd>{item.accountability.direct_accepted ? "Да" : "Нет"}</dd></div></dl>}
      <footer><span>Сдерживание · <strong>{machineLabel(item.containment)}</strong></span><span>Блокировка аккаунта · <strong>{machineLabel(item.account_lock)}</strong></span></footer>
      {item.moderation?.next_poll_at && <p className="execution-failure" role="status"><strong>Следующая проверка модерации</strong> · {item.moderation.next_poll_at} · попыток: {item.moderation.poll_attempts}<button type="button" disabled={busy || !canPoll} onClick={() => poll(String(item.item_execution_id))}>Проверить запланированный элемент</button></p>}
      {Array.isArray(item.moderation?.ad_outcomes) && item.moderation.ad_outcomes.length > 0 && <details><summary>Результаты модерации объявлений · {item.moderation.ad_outcomes.length}</summary><ul>{item.moderation.ad_outcomes.map((ad: Record<string, any>) => <li key={ad.ad_id}><strong>{ad.ad_id} · {machineLabel(ad.status)}</strong><span>{ad.status_clarification || "Пояснение состояния отсутствует"}</span></li>)}</ul></details>}
      {item.failure && <p className="execution-failure" role="status"><strong>{item.failure.code}</strong> · {localizedText(item.failure.message)}</p>}
      {item.status === "REJECTED_NEEDS_EDIT" && startCorrection && <button type="button" className="correction-start" disabled={busy || correctionItemIds.includes(String(item.item_execution_id))} onClick={() => startCorrection(String(item.item_execution_id))}>{correctionItemIds.includes(String(item.item_execution_id)) ? "Точечное исправление уже открыто" : "Исправить отклонённый черновик"}</button>}
      {Array.isArray(item.provider_issues) && item.provider_issues.length > 0 && <details><summary>Подробности провайдера · {item.provider_issues.length}</summary><ul>{item.provider_issues.map((issue: Record<string, any>, index: number) => <li key={`${issue.operation}-${issue.code}-${index}`}><strong>{issue.operation} · {issue.code}</strong><span>{localizedText(issue.message)}{issue.details ? ` · ${localizedText(issue.details)}` : ""}</span></li>)}</ul></details>}
      {item.readback && <details><summary>Смысловая обратная проверка</summary><code>{JSON.stringify(item.readback)}</code></details>}
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
  return <section className="package-corrections" aria-label="Точечные исправления">
    <header><div><p className="eyebrow">ТОЧЕЧНОЕ ИСПРАВЛЕНИЕ · НЕИЗМЕНЯЕМОЕ ПРОИСХОЖДЕНИЕ</p><h3>Исправление отклонения провайдера</h3><p>Первичное исполнение, ответы провайдера и вердикт остаются неизменными. Только существенная редакция черновика может получить новую проверку, контрольное решение и повторную отправку.</p></div><strong>{corrections.length}</strong></header>
    {corrections.map((correction, correctionIndex) => {
      const source = correction.source || {};
      const sourceDraft = source.draft_snapshot || {};
      const correctedDraft = correction.corrected_draft || null;
      const correctedExecution = correction.execution || null;
      const decisionPacket = correction.decision_packet || null;
      const correctionItem = correctedExecution?.items?.[0] || null;
      const canConfirm = confirmedCorrectionId === correction.correction_id;
      return <article key={correction.correction_id} className="package-correction-flow">
        <header><div><p className="eyebrow">Ход исправления</p><strong>{machineLabel(correction.status)}</strong><code>{correction.correction_id}</code></div><span>{source.item_execution_id}</span></header>
        <dl className="correction-accounting">
          <div><dt>Первичный вердикт пакета</dt><dd>{machineLabel(source.initial_package_verdict)}</dd></div>
          <div><dt>Ход исправления</dt><dd>{machineLabel(correction.status)}</dd></div>
          <div><dt>Итог исправленной редакции</dt><dd>{machineLabel(correction.terminal_outcome, "Ожидает")}</dd></div>
        </dl>
        <section className="correction-provider-context"><strong>Пояснение состояния</strong>{source.status_clarifications?.length ? <ul>{source.status_clarifications.map((item: string) => <li key={item}>{localizedText(item)}</li>)}</ul> : <p>Пояснение провайдера отсутствует; исправление остаётся безопасно заблокированным.</p>}{source.provider_issues?.length > 0 && <details open><summary>Конкретные замечания провайдера · {source.provider_issues.length}</summary><ul>{source.provider_issues.map((issue: Record<string, any>, index: number) => <li key={`${issue.operation}-${issue.code}-${index}`}><strong>{issue.operation} · {issue.code}</strong><span>{localizedText(issue.message)}{issue.details ? ` · ${localizedText(issue.details)}` : ""}</span></li>)}</ul></details>}<small>Первичный пакет {source.package_id} · контрольное решение {source.gate_id}</small></section>
        {correction.status === "EDITING" && <form className="correction-form" onSubmit={(event) => submitCorrection(event, correction)}>
          <DraftFieldRegistryDisclosure registry={fieldRegistry} draft={sourceDraft} titleId={`correction-draft-fields-${correctionIndex}`} />
          <button type="submit" disabled={busy}>Сохранить новую существенную редакцию исправления</button>
        </form>}
        {correctedDraft && <section className="corrected-draft-review"><DraftEditFeedback draft={correctedDraft} /><ViabilityScoreDisclosure score={correctedDraft.viability_score} delta={correctedDraft.score_delta} /><dl><div><dt>Редакция черновика</dt><dd>{correctedDraft.draft_revision_id}</dd></div><div><dt>Отпечаток публикации</dt><dd><code>{correctedDraft.publish_fingerprint}</code></dd></div></dl></section>}
        {decisionPacket && <section className="correction-decision-packet" aria-label="Подготовленный пакет исправленного контрольного решения человека">
          <header><div><p className="eyebrow">ПОДГОТОВЛЕННОЕ КОНТРОЛЬНОЕ РЕШЕНИЕ ЧЕЛОВЕКА</p><h4>Рекомендация · {machineLabel(decisionPacket.recommendation.action)}</h4><p>{localizedText(decisionPacket.recommendation.rationale)}</p></div><strong>Уверенность · {machineLabel(decisionPacket.confidence.status)}</strong></header>
          <p>{localizedText(decisionPacket.confidence.rationale)}</p>
          <dl><div><dt>Доказательства</dt><dd>{decisionPacket.evidence.changed_pointers.join(" · ")}</dd></div><div><dt>Оценка и место</dt><dd>{decisionPacket.evidence.score.previous ?? "—"} → {decisionPacket.evidence.score.current ?? "—"} · {decisionPacket.evidence.rank.previous ?? "—"} → {decisionPacket.evidence.rank.current ?? "—"}</dd></div></dl>
          <div className="correction-options"><strong>Альтернативы</strong><ul>{decisionPacket.alternatives.map((alternative: Record<string, any>) => <li key={alternative.action}><b>{machineLabel(alternative.action)}</b><span>{localizedText(alternative.consequence)}</span></li>)}</ul></div>
          <div className="correction-consequences"><strong>Последствия</strong><ul>{decisionPacket.consequences.map((consequence: string) => <li key={consequence}>{localizedText(consequence)}</li>)}</ul></div>
        </section>}
        {correction.status === "PACKAGE_REVIEW_REQUIRED" && <button type="button" disabled={busy} onClick={() => void apply("review_package_correction", undefined, { correction_id: correction.correction_id })}>Проверить исправленную редакцию пакета</button>}
        {correction.status === "HUMAN_GATE_REQUIRED" && <div className="correction-gate"><label><input type="checkbox" checked={canConfirm} onChange={(event) => setConfirmedCorrectionId(event.target.checked ? correction.correction_id : "")} /><span>Подтверждаю рекомендацию, доказательства, уверенность, альтернативы, последствия и новый точный отпечаток исправления</span></label><button type="button" disabled={busy || !canConfirm} onClick={() => void apply("confirm_package_correction", undefined, { correction_id: correction.correction_id, confirmation: "CONFIRM_EXACT_SHORTLIST_PACKAGE", package_review_id: correction.package_review.package_review_id, package_id: correction.package_review.package_id })}>Создать новое контрольное решение человека</button></div>}
        {correction.status === "READY_TO_RESUBMIT" && <button type="button" disabled={busy} onClick={() => void apply("resubmit_package_correction", undefined, { correction_id: correction.correction_id, package_id: correction.human_decision_gate.package_id, gate_id: correction.human_decision_gate.gate_id })}>Повторно отправить подтверждённую редакцию исправления</button>}
        {correctedExecution && <PackageExecutionPanel execution={correctedExecution} busy={busy} canPoll={canPoll} poll={(itemExecutionId) => void apply("poll_package_correction_moderation", undefined, { correction_id: correction.correction_id, package_id: correctedExecution.package_id, item_execution_id: itemExecutionId })} />}
        {correctionItem?.status === "RECONCILIATION_REQUIRED" && <p className="execution-failure" role="status"><strong>Граница сверки удерживается</strong> · неоднозначная исправленная запись не является исправлением содержания.</p>}
        {correction.terminal_outcome === "PASS_AFTER_CORRECTION" && <div className="correction-terminal" role="status"><strong>ПРОЙДЕНО ПОСЛЕ ИСПРАВЛЕНИЯ</strong><p>Исправленная редакция принята и остаётся без показов. Вердикт первичного создания не изменён.</p></div>}
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
      <ArtifactHead eyebrow="Шаг 5 · контрольное решение человека" title="Проверка пакета недоступна" copy="Вернитесь к полотну кампаний, сформируйте непустой упорядоченный список и откройте точную проверку из постоянной нижней панели." badge="БЕЗОПАСНО ЗАБЛОКИРОВАНО" />
      <ul className="blockers">{payload.decision_readiness.blockers.map((item, index) => <li key={item}><span>{index + 1}</span>{localizedText(item)}</li>)}</ul>
      <Actions revision={payload.revision} label="Вернуться к списку" disabled back={back} />
    </>;
  }
  const binding = authority.direct_account_binding || {};
  const capability = authority.direct_capability_snapshot || {};
  const profile = authority.capability_profile || {};
  return <>
    <ArtifactHead eyebrow="Шаг 5 · контрольное решение человека" title="Точная неизменяемая проверка пакета" copy="Контрольное решение даёт полномочие только этому упорядоченному набору редакций и отпечатков. Подтверждение не выполняет записи в Яндекс Директ и не обещает атомарную внешнюю транзакцию." badge={gate ? "ПОЛНОМОЧИЕ ПОДТВЕРЖДЕНО" : "ПРОВЕРЕНО"} />
    <section className="package-review" aria-labelledby="package-review-title">
      <header><div><p className="eyebrow">ИДЕНТИЧНОСТЬ ПАКЕТА</p><h3 id="package-review-title">{selections.length} независимых черновика кампаний</h3></div><strong>{review.reviewed_at}</strong></header>
      <ol>{selections.map((item: Record<string, any>, index: number) => <li key={item.draft_id}><span>{index + 1}</span><div><strong>{item.draft_id}</strong><code>{item.draft_revision_id}</code><small>{item.publish_fingerprint}</small></div></li>)}</ol>
      <dl>
        <div><dt>ID пакета</dt><dd><code>{review.package_id}</code></dd></div>
        <div><dt>ID проверки пакета</dt><dd><code>{review.package_review_id}</code></dd></div>
        <div><dt>Набор рекомендаций</dt><dd><code>{authority.recommendation_set_id}</code></dd></div>
        <div><dt>Редакция стратегии</dt><dd><code>{authority.strategy_revision_id}</code></dd></div>
        <div><dt>Привязка аккаунта Яндекс Директа</dt><dd>{binding.account} · клиент {binding.client_id} · {binding.source_kind}</dd></div>
        <div><dt>Снимок возможностей</dt><dd><code>{capability.snapshot_id}</code></dd></div>
        <div><dt>Профиль возможностей</dt><dd><code>{profile.profile_id}@{profile.profile_version}</code></dd></div>
        <div><dt>Снимок аналитических доказательств</dt><dd><code>{authority.analytics_evidence_snapshot_id}</code></dd></div>
      </dl>
    </section>
    <div className="confirmation"><p className="eyebrow">НЕАТОМАРНЫЙ ПАКЕТ</p><h3>Кампании исполняются и оцениваются независимо</h3><p>{authority.orchestration.disclosure} Подтверждение сохраняет полномочие и отметку времени, но не вызывает Яндекс Директ, не развёртывает изменения, не запускает показы и не начинает расходы.</p></div>
    {gate ? <section className="gate-confirmed" role="status"><strong>Контрольное решение человека подтверждено</strong><p>{gate.confirmed_at} · {gate.gate_id}</p><small>Внешние записи выполнены: {execution ? "да, независимо" : "нет"} · транзакционность обещана: нет</small></section> : <div className="decision-confirm"><input aria-label="Подтверждаю точный пакет и независимое исполнение кампаний" type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span><strong>Подтверждаю точный проверенный пакет</strong><small>Полномочие относится только к пакету {String(review.package_id).slice(0, 20)}…; каждая выбранная кампания будет отправлена, сдержана, промодерирована и оценена независимо.</small></span></div>}
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
    <footer className="actions"><span>Ревизия {payload.revision} · независимые сохраняемые исполнения элементов</span><button type="button" className="secondary" disabled={busy} onClick={back}>Назад к списку</button>{!gate
      ? <button type="button" disabled={busy || !confirmed} onClick={() => void apply("confirm_package", undefined, { confirmation: "CONFIRM_EXACT_SHORTLIST_PACKAGE", package_review_id: review.package_review_id, package_id: review.package_id })}>Подтвердить полномочие пакета</button>
      : <button type="button" disabled={busy || !canDispatch} onClick={() => void apply("dispatch_package", undefined, { package_id: gate.package_id, gate_id: gate.gate_id })}>{canDispatch && execution ? "Продолжить безопасное исполнение" : execution ? "Отправка пакета зафиксирована" : "Исполнить подтверждённый пакет"}</button>}</footer>
  </>;
}
