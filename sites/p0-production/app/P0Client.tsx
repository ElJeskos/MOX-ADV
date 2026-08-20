"use client";

/* eslint-disable @typescript-eslint/no-explicit-any -- API payloads are validated server-side and intentionally revisioned. */
import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { buildAdText, buildAdTitle } from "../lib/ad-copy";

type Payload = {
  revision: number;
  updated_at: string;
  state: Record<string, any>;
  context: Record<string, any>;
  write_readiness: { ready: boolean; blockers: string[] };
};

const steps = [
  ["Контекст", "Реальные подключения"],
  ["Модель", "Агентное исследование"],
  ["Strategy", "Критические решения"],
  ["Draft", "Точная проекция"],
  ["Подтверждение", "Guarded write"],
];

async function request(path: string, init?: RequestInit) {
  const response = await fetch(path, init);
  const value = (await response.json()) as Record<string, any>;
  if (!response.ok) throw new Error(String(value.error || `HTTP ${response.status}`));
  return value;
}

function currentStep(payload: Payload) {
  const state = payload.state;
  if (state.draft?.publish_projection) return 4;
  if (state.strategy) return 3;
  if (state.business_model?.source === "REAL_SITE_RESEARCH_PLUS_OWNER_CONFIRMATION") return 2;
  if (state.site_analysis) return 1;
  return 0;
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
        setStep(currentStep(next));
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setBusy(""));
  }, []);

  const maxStep = useMemo(() => (payload ? Math.max(step, currentStep(payload)) : 0), [payload, step]);

  async function apply(action: string, value?: Record<string, unknown>, extra?: Record<string, unknown>) {
    if (!payload) return;
    setError("");
    setBusy(action === "analyze_site" ? "Агент исследует first-party страницы и реальные подключения…" : "Сохраняю production-ревизию…");
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
      setStep(currentStep(next));
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
  const direct = context.direct || {};
  const metrika = context.metrika || {};
  const performance = context.performance || null;

  return (
    <div className="site-shell">
      <header className="topbar">
        <Link className="brand" href="/"><span>M</span>MOX-ADV</Link>
        <nav aria-label="Основная навигация"><Link className="active" href="/">Стратегия</Link><span>Production Module · P0</span></nav>
        <div className="ready"><i />Система готова</div>
      </header>

      <main className="page">
        <section className="hero">
          <div><p className="eyebrow">GPT SITES · PRODUCTION MODULE · P0</p><h1>Стратегия и создание кампании</h1><p>Агент выполняет всю безопасную работу. Человеку остаются критические решения и существенная неопределённость.</p></div>
          <strong className="real-badge">ТОЛЬКО РЕАЛЬНЫЕ ДАННЫЕ</strong>
        </section>

        <ol className="steps" aria-label="Путь создания кампании">
          {steps.map(([title, detail], index) => (
            <li key={title}>
              <button disabled={index > maxStep} className={index === step ? "current" : index < currentStep(payload) ? "done" : ""} onClick={() => setStep(index)}>
                <span>{index < currentStep(payload) ? "✓" : index + 1}</span><div><strong>{title}</strong><small>{detail}</small></div>
              </button>
            </li>
          ))}
        </ol>

        <div className="workspace">
          <aside className="agent-pane">
            <div className="agent-head"><span>AI</span><div><strong>Агент кампании</strong><small>GPT Sites · production-only</small></div></div>
            <section className="agent-message"><strong>{steps[step][0]}</strong><p>{[
              "Проверяю реальные API и сам исследую сайт.",
              "Показываю готовую модель с доказательствами и уверенностью.",
              "Готовлю Strategy; владелец задаёт только денежные и временные границы.",
              "Компилирую точную publish projection без молчаливых полей.",
              "Внешняя запись остаётся закрытой, пока production gates не готовы.",
            ][step]}</p></section>
            <section className="connections"><h3>Подключённые данные</h3>
              <Connection label="Яндекс Директ" ready={direct.ready === true} detail={direct.ready ? `${direct.account} · ${direct.campaigns_total} кампаний` : direct.blockers?.[0]} />
              <Connection label="Яндекс Метрика" ready={metrika.ready === true} detail={metrika.ready ? "Счётчик и цель читаются через API" : metrika.blockers?.[0]} />
              <Connection label="Последний реальный срез" ready={Boolean(performance)} detail={performance ? `${performance.period_start} — ${performance.period_end} · ${performance.display_metrics.goal_visits} целей` : "Нет подтверждённого среза"} />
            </section>
            <section className="write-boundary"><span>Готовность внешней записи</span><strong>Заблокирована</strong><small>{payload.write_readiness.blockers[0]}</small></section>
          </aside>

          <section className="artifact">
            {step === 0 && <ContextStep payload={payload} busy={Boolean(busy)} apply={apply} />}
            {step === 1 && <ModelStep payload={payload} apply={apply} back={() => setStep(0)} />}
            {step === 2 && <StrategyStep payload={payload} apply={apply} back={() => setStep(1)} />}
            {step === 3 && <DraftStep payload={payload} apply={apply} back={() => setStep(2)} />}
            {step === 4 && <ConfirmationStep payload={payload} back={() => setStep(3)} />}
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
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void apply("analyze_site", undefined, { url: fieldValue(event.currentTarget, "url") });
  }
  return <>
    <ArtifactHead eyebrow="Шаг 1 · production preflight" title="Реальный контекст до создания" copy="Агент начинает с разрешённых источников и не перекладывает безопасное исследование на человека." />
    <div className="context-strip"><Metric label="Директ" value={payload.context.direct.ready ? payload.context.direct.account : "Не готов"} copy={payload.context.direct.ready ? `${payload.context.direct.campaigns_total} кампаний прочитано` : payload.context.direct.blockers?.[0]} /><Metric label="Метрика" value={payload.context.metrika.ready ? "Реальная цель подключена" : "Не готова"} copy={payload.context.metrika.ready ? "Production API подтвердил подключение" : payload.context.metrika.blockers?.[0]} /><Metric label="Сайт" value={analysis ? analysis.title || analysis.url : "Нужен реальный URL"} copy={analysis ? `${analysis.research?.pages_analyzed || 1} first-party страниц исследовано` : "Scope первого P0 задаёт владелец"} /></div>
    <form className="form" onSubmit={submit}><label className="wide"><span>Публичный сайт бизнеса</span><input type="url" name="url" required defaultValue={analysis?.url || ""} placeholder="https://example.ru/" /></label><div className="agent-work"><strong>Что агент сделает сам</strong><p>Обойдёт до шести релевантных first-party страниц, сопоставит их с Директом и Метрикой, заполнит модель и приложит доказательства.</p></div><Actions revision={payload.revision} label="Исследовать и собрать модель" disabled={busy} submit /></form>
  </>;
}

function Metric({ label, value, copy }: { label: string; value: string; copy?: string }) {
  return <div><span>{label}</span><strong>{value}</strong><small>{copy || "—"}</small></div>;
}

function Evidence({ model, field }: { model: Record<string, any>; field: string }) {
  const item = model.field_evidence?.[field] || {};
  return <small className={`evidence ${String(item.confidence || "LOW").toLowerCase()}`}><strong>{confidenceLabel(item.confidence || "LOW")}</strong>{item.quote ? ` · «${String(item.quote).slice(0, 180)}»` : ""}</small>;
}

function ModelStep({ payload, apply, back }: { payload: Payload; apply: (action: string, value?: Record<string, unknown>) => Promise<void>; back: () => void }) {
  const model = payload.state.business_model || {};
  const research = model.research || {};
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    void apply("save_business_model", Object.fromEntries(["product", "audience", "value", "qualified_result", "exclusions"].map((name) => [name, fieldValue(form, name)])));
  }
  return <>
    <ArtifactHead eyebrow="Шаг 2 · агентное исследование" title="Агент уже собрал модель бизнеса" copy="Исправьте только неверную гипотезу или факт, которого действительно нет в разрешённых источниках." badge="AGENT RESEARCH" />
    <div className="research-strip"><Metric label="Исследовано" value={`${research.pages_analyzed || 1} страниц`} copy="First-party public HTTPS" /><Metric label="Источники" value={String(research.sources?.length || 0)} copy={(research.sources || []).join(" · ")} /><Metric label="Сделано агентом" value={`${research.completed_fields?.length || 0} / 5 полей`} copy="Человеку — подтверждение и разногласия" /></div>
    {model.assumptions?.length > 0 && <div className="assumption"><strong>Где нужна проверка</strong><span>{model.assumptions.join(" · ")}</span></div>}
    <form className="form two" onSubmit={submit}>
      <Field wide label="Продукт или предложение" name="product" value={model.product}><Evidence model={model} field="product" /></Field>
      <Field label="Кто принимает решение" name="audience" value={model.audience}><Evidence model={model} field="audience" /></Field>
      <Field label="Ценность для покупателя" name="value" value={model.value}><Evidence model={model} field="value" /></Field>
      <Field label="Квалифицированный результат" name="qualified_result" value={model.qualified_result}><Evidence model={model} field="qualified_result" /></Field>
      <Field label="Что не является результатом" name="exclusions" value={model.exclusions}><Evidence model={model} field="exclusions" /></Field>
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
      <label className="wide"><span>Бизнес-цель · предложено агентом</span><input name="goal" required defaultValue={existing.goal || `Получать: ${model.qualified_result}`} /></label>
      <label><span>География · предложено агентом</span><select name="geography" defaultValue={existing.geography || "Россия"}><option>Россия</option><option>Москва</option><option>Санкт-Петербург</option></select></label>
      <label><span>Посадочная страница · проверена агентом</span><input type="url" name="landing_page" required defaultValue={existing.landing_page || site.url} /></label>
      <label><span>Дата начала · решение владельца</span><input type="date" name="period_start" required defaultValue={existing.period_start || ""} /></label>
      <label><span>Дата окончания · решение владельца</span><input type="date" name="period_end" required defaultValue={existing.period_end || ""} /></label>
      <label><span>Недельный бюджет, ₽ · решение владельца</span><input type="number" min="1" name="weekly_budget_rub" required defaultValue={existing.weekly_budget_rub || ""} /></label>
      <label><span>Целевой CPA, ₽ · решение владельца</span><input type="number" min="1" name="target_cpa_rub" required defaultValue={existing.target_cpa_rub || ""} /></label>
      <Field wide label="Основное сообщение · предложено агентом" name="message" value={existing.message || model.value} />
      <div className="wide"><Actions revision={payload.revision} label="Принять критические решения" back={back} submit /></div>
    </form>
  </>;
}

function DraftStep({ payload, apply, back }: { payload: Payload; apply: (action: string, value?: Record<string, unknown>) => Promise<void>; back: () => void }) {
  const model = payload.state.business_model || {};
  const strategy = payload.state.strategy || {};
  const existing = payload.state.draft || {};
  const participation = /участ|participant/i.test(model.qualified_result || "");
  const adTitle = buildAdTitle(existing.ad_title || model.product);
  const adText = buildAdText(existing.ad_text || strategy.message, model.product, participation);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = Object.fromEntries(["campaign_name", "group_name", "keyword", "negative_keywords", "ad_title", "ad_text"].map((name) => [name, fieldValue(form, name)]));
    void apply("save_draft", value);
  }
  return <>
    <ArtifactHead eyebrow="Шаг 4 · Campaign Draft" title="Точная publish projection" copy="Агент подготовил все поддерживаемые поля. Ничего не будет молча отброшено." />
    <div className="context-strip"><Metric label="Цель" value={strategy.goal} copy={model.qualified_result} /><Metric label="Бюджет" value={`${strategy.weekly_budget_rub} ₽ / неделю`} copy="Search only · сети выключены" /><Metric label="Безопасный финиш" value="State = SUSPENDED" copy="resume отсутствует" /></div>
    <form className="form two" onSubmit={submit}>
      <label><span>Название кампании</span><input name="campaign_name" required defaultValue={existing.campaign_name || `${model.product} · Поиск`} /></label>
      <label><span>Название группы</span><input name="group_name" required defaultValue={existing.group_name || `${strategy.geography} · Поиск`} /></label>
      <label className="wide"><span>Ключевая фраза · подготовлена агентом</span><input name="keyword" required defaultValue={existing.keyword || `${model.product}${participation ? " стать участником" : ""}`.toLowerCase()} /></label>
      <label className="wide"><span>Минус-фразы · выведены из исключений</span><input name="negative_keywords" required defaultValue={existing.negative_keywords || "бесплатно, вакансии, посетитель, билет"} /></label>
      <label className="wide"><span>Заголовок объявления · до 56 символов</span><input name="ad_title" maxLength={56} required defaultValue={adTitle} /></label>
      <Field wide label="Текст объявления · до 81 символа, без обрыва слов" name="ad_text" maxLength={81} value={adText} />
      <div className="wide"><Actions revision={payload.revision} label="Зафиксировать проекцию" back={back} submit /></div>
    </form>
  </>;
}

function ConfirmationStep({ payload, back }: { payload: Payload; back: () => void }) {
  return <>
    <ArtifactHead eyebrow="Шаг 5 · guarded write" title="Внешняя запись заблокирована" copy="GPT Sites-кандидат не симулирует создание кампании и не показывает недоступную кнопку." badge="FAIL CLOSED" />
    <div className="confirmation"><p className="eyebrow">Обещание безопасности</p><h3>Показы и списания не начнутся</h3><p>Production write появится только после отдельного Human Decision Gate, привязки single writer и официального Direct API-контура с обязательным readback State=SUSPENDED.</p></div>
    <ul className="blockers">{payload.write_readiness.blockers.map((item, index) => <li key={item}><span>{index + 1}</span>{item}</li>)}</ul>
    <Actions revision={payload.revision} label="Запись недоступна" disabled back={back} />
  </>;
}
