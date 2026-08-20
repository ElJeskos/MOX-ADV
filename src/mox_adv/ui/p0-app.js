/* Production P0 candidate: real context, real revisions, guarded Direct write. */

const p0Steps = Object.freeze([
  ["Контекст", "Реальные подключения"],
  ["Модель", "Смысл бизнеса"],
  ["Strategy", "Цель и границы"],
  ["Draft", "Точная проекция"],
  ["Подтверждение", "Одна запись"],
  ["Кампания", "Фактический статус"],
]);

const p0Elements = {
  app: document.querySelector("#p0-app"),
  loading: document.querySelector("#p0-loading"),
  error: document.querySelector("#p0-error"),
  steps: document.querySelector("#p0-steps"),
  agent: document.querySelector("#p0-agent-pane"),
  artifact: document.querySelector("#p0-artifact-pane"),
};

function p0Escape(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function p0StateStep() {
  const value = state.p0Production?.state || {};
  if (value.campaign) return 5;
  if (value.draft?.publish_projection) return 4;
  if (value.strategy) return 3;
  if (value.business_model?.missing_questions?.length === 0) return 2;
  if (value.site_analysis) return 1;
  return 0;
}

function p0MaxStep() {
  return Math.max(state.p0Step || 0, p0StateStep());
}

function p0ConnectionRow(label, ready, detail) {
  return `<div class="p0-connection-row ${ready ? "" : "is-blocked"}"><span></span><div><strong>${p0Escape(label)}</strong><small>${p0Escape(detail)}</small></div></div>`;
}

function renderP0Agent() {
  const payload = state.p0Production;
  if (!payload) return;
  const context = payload.context || {};
  const direct = context.direct || {};
  const metrika = context.metrika || {};
  const readiness = payload.write_readiness || { ready: false, blockers: [] };
  const messages = [
    "Проверяю реальный сайт и уже подключённые источники. Не буду спрашивать то, что могу получить сам.",
    "Показываю выводы из сайта. От владельца нужны только отсутствующие продуктовые факты.",
    "Вы фиксируете бизнес-цель и границы. Техническую стратегию Директа выбираю я.",
    "Показываю ровно одну кампанию, группу, фразу и объявление, которые будут опубликованы.",
    "Запись возможна только при готовом guarded write-контуре и точном подтверждении владельца.",
    "Кампания остаётся остановленной. Создание, модерация и измерение показываются независимо.",
  ];
  const metrics = context.performance?.display_metrics || {};
  p0Elements.agent.innerHTML = `
    <div class="p0-agent-head"><span>AI</span><div><strong>Агент кампании</strong><small>Production-контекст · без Test Scenario</small></div></div>
    <div class="p0-agent-message"><strong>${p0Escape(p0Steps[state.p0Step][0])}</strong><p>${p0Escape(messages[state.p0Step])}</p></div>
    <section class="p0-agent-section"><h4>Подключённые данные</h4><div class="p0-connection-list">
      ${p0ConnectionRow("Яндекс Директ", direct.ready === true, direct.ready ? `${direct.account || "Аккаунт"} · ${direct.campaigns_total || 0} кампаний` : (direct.blockers || ["Не готов"])[0])}
      ${p0ConnectionRow("Яндекс Метрика", metrika.ready === true, metrika.ready ? "Счётчик и цель читаются через API" : (metrika.blockers || ["Не готова"])[0])}
      ${p0ConnectionRow("Последний реальный срез", Boolean(context.performance), context.performance ? `${context.performance.period_start} — ${context.performance.period_end} · CTR ${metrics.ctr_percent || "—"}` : "Нет подтверждённого среза")}
    </div></section>
    <div class="p0-agent-boundary"><span>Готовность внешней записи</span><strong>${readiness.ready ? "Разрешена после подтверждения" : "Заблокирована"}</strong><small>${readiness.ready ? "Финиш: State = SUSPENDED" : (readiness.blockers || ["Guarded write-контур не готов"])[0]}</small></div>`;
}

function p0ArtifactHead(eyebrow, title, copy, badge = "REAL DATA") {
  return `<div class="p0-artifact-head"><div><p class="eyebrow">${p0Escape(eyebrow)}</p><h3>${p0Escape(title)}</h3><p>${p0Escape(copy)}</p></div><span class="p0-source-badge">${p0Escape(badge)}</span></div>`;
}

function p0Actions(primaryLabel, action, { back = true, disabled = false } = {}) {
  return `<div class="p0-artifact-actions"><span>Ревизия ${state.p0Production.revision} · production data only</span>${back ? '<button class="secondary-button" type="button" data-p0-back>Назад</button>' : ""}${primaryLabel ? `<button class="primary-button" type="button" data-p0-action="${p0Escape(action)}" ${disabled ? "disabled" : ""}>${p0Escape(primaryLabel)}</button>` : ""}</div><p class="p0-inline-message" id="p0-message" aria-live="polite"></p>`;
}

function renderP0Context() {
  const payload = state.p0Production;
  const context = payload.context || {};
  const direct = context.direct || {};
  const metrika = context.metrika || {};
  const analysis = payload.state.site_analysis;
  p0Elements.artifact.innerHTML = `
    ${p0ArtifactHead("Шаг 1 · production preflight", "Реальный контекст до создания", "Начинаем с сайта и подключений, а не с демонстрационной анкеты.")}
    <div class="p0-real-context-strip"><div><span>Директ</span><strong>${direct.ready ? p0Escape(direct.account || "Подключён") : "Не готов"}</strong><small>${direct.ready ? `${direct.campaigns_total || 0} реальных кампаний прочитано` : p0Escape((direct.blockers || ["Проверьте подключение"])[0])}</small></div><div><span>Метрика</span><strong>${metrika.ready ? "Реальная цель подключена" : "Не готова"}</strong><small>${metrika.ready ? "Данные цели подтверждены production API" : p0Escape((metrika.blockers || ["Проверьте подключение"])[0])}</small></div><div><span>Сайт</span><strong>${analysis ? p0Escape(analysis.title || analysis.url) : "Нужен реальный URL"}</strong><small>${analysis ? `Прочитан ${p0Escape(analysis.fetched_at)}` : "HTTPS · публичная страница бизнеса"}</small></div></div>
    <form class="p0-form-grid" id="p0-site-form"><label class="is-wide"><span>Сайт или посадочная страница реального бизнеса</span><input type="url" name="url" required placeholder="https://example.ru/" value="${p0Escape(analysis?.url || "")}"></label></form>
    <ul class="p0-publish-list"><li><span>1</span><div><strong>Агент прочитает только публичный HTML</strong><br>Локальные адреса, credentials, нестандартные порты и redirects в private network блокируются.</div></li><li><span>2</span><div><strong>Директ и Метрика уже читаются через официальные API</strong><br>Их реальные факты будут показаны рядом с моделью бизнеса и Campaign Draft.</div></li></ul>
    ${p0Actions("Анализировать реальный сайт", "analyze_site", { back: false, disabled: !direct.ready })}`;
}

function renderP0Model() {
  const model = state.p0Production.state.business_model || {};
  const questions = model.missing_questions || [];
  p0Elements.artifact.innerHTML = `
    ${p0ArtifactHead("Шаг 2 · модель бизнеса", "Понимание агента по реальному сайту", "Исправьте выводы и заполните только факты, которых на сайте действительно не хватило.")}
    ${questions.length ? `<ul class="p0-question-list">${questions.map((question, index) => `<li><span>${index + 1}</span><div>${p0Escape(question)}</div></li>`).join("")}</ul>` : ""}
    <form class="p0-form-grid" id="p0-model-form">
      <label class="is-wide"><span>Продукт или предложение</span><textarea name="product" required>${p0Escape(model.product || "")}</textarea></label>
      <label><span>Кто принимает решение</span><textarea name="audience" required>${p0Escape(model.audience || "")}</textarea></label>
      <label><span>Ценность для покупателя</span><textarea name="value" required>${p0Escape(model.value || "")}</textarea></label>
      <label><span>Квалифицированный результат</span><textarea name="qualified_result" required>${p0Escape(model.qualified_result || "")}</textarea></label>
      <label><span>Что не является результатом</span><textarea name="exclusions" required>${p0Escape(model.exclusions || "")}</textarea></label>
    </form>
    ${p0Actions("Подтвердить модель бизнеса", "save_business_model")}`;
}

function renderP0Strategy() {
  const value = state.p0Production.state.strategy || {};
  const site = state.p0Production.state.site_analysis || {};
  p0Elements.artifact.innerHTML = `
    ${p0ArtifactHead("Шаг 3 · Campaign Strategy", "Цель и бизнес-границы кампании", "Здесь нет API-enum и технических ставок: владелец задаёт только реальный продуктовый контракт.")}
    <form class="p0-form-grid" id="p0-strategy-form">
      <label class="is-wide"><span>Основная бизнес-цель</span><input name="goal" required value="${p0Escape(value.goal || "")}"></label>
      <label><span>География первого P0</span><select name="geography" required><option value="">Выберите</option>${["Россия", "Москва", "Санкт-Петербург"].map((item) => `<option ${value.geography === item ? "selected" : ""}>${item}</option>`).join("")}</select></label>
      <label><span>Посадочная страница</span><input type="url" name="landing_page" required value="${p0Escape(value.landing_page || site.url || "")}"></label>
      <label><span>Дата начала</span><input type="date" name="period_start" required value="${p0Escape(value.period_start || "")}"></label>
      <label><span>Дата окончания</span><input type="date" name="period_end" required value="${p0Escape(value.period_end || "")}"></label>
      <label><span>Недельный бюджет, ₽</span><input type="number" min="1" name="weekly_budget_rub" required value="${p0Escape(value.weekly_budget_rub || "")}"></label>
      <label><span>Целевая стоимость результата, ₽</span><input type="number" min="1" name="target_cpa_rub" required value="${p0Escape(value.target_cpa_rub || "")}"></label>
      <label class="is-wide"><span>Основное сообщение</span><textarea name="message" required>${p0Escape(value.message || "")}</textarea></label>
    </form>
    ${p0Actions("Сохранить Campaign Strategy", "save_strategy")}`;
}

function renderP0Draft() {
  const current = state.p0Production.state.draft || {};
  const model = state.p0Production.state.business_model || {};
  const strategy = state.p0Production.state.strategy || {};
  const campaignName = current.campaign_name || `${model.product || ""} · Поиск`.slice(0, 255);
  const groupName = current.group_name || `${strategy.geography || ""} · Поиск`.slice(0, 255);
  const adTitle = current.ad_title || String(model.product || "").slice(0, 56);
  const adText = current.ad_text || String(strategy.message || "").slice(0, 81);
  p0Elements.artifact.innerHTML = `
    ${p0ArtifactHead("Шаг 4 · Campaign Draft", "Точная publish projection", "Каждое редактируемое поле ниже входит в поддерживаемую реальную запись. Ничего не будет молча отброшено.")}
    <div class="p0-strategy-strip"><div><span>Бизнес-цель</span><strong>${p0Escape(strategy.goal)}</strong><small>${p0Escape(model.qualified_result)}</small></div><div><span>Бюджет</span><strong>${p0Escape(strategy.weekly_budget_rub)} ₽ / неделю</strong><small>Search only · сети отключены</small></div><div><span>Безопасный финиш</span><strong>State = SUSPENDED</strong><small>Запуска и списаний в P0 нет</small></div></div>
    <form class="p0-form-grid" id="p0-draft-form">
      <label><span>Название кампании</span><input name="campaign_name" maxlength="255" required value="${p0Escape(campaignName)}"></label>
      <label><span>Название группы</span><input name="group_name" maxlength="255" required value="${p0Escape(groupName)}"></label>
      <label class="is-wide"><span>Одна ключевая фраза</span><input name="keyword" required value="${p0Escape(current.keyword || "")}"></label>
      <label class="is-wide"><span>Минус-фразы через запятую</span><input name="negative_keywords" required value="${p0Escape((current.negative_keywords || []).join(", "))}"></label>
      <label class="is-wide"><span>Заголовок объявления</span><input name="ad_title" maxlength="56" required value="${p0Escape(adTitle)}"></label>
      <label class="is-wide"><span>Текст объявления</span><textarea name="ad_text" maxlength="81" required>${p0Escape(adText)}</textarea></label>
    </form>
    ${p0Actions("Зафиксировать точную проекцию", "save_draft")}`;
}

function renderP0Confirmation() {
  const payload = state.p0Production;
  const draft = payload.state.draft || {};
  const projection = draft.publish_projection || {};
  const direct = projection.direct || {};
  const readiness = payload.write_readiness || { ready: false, blockers: [] };
  const duplicateCandidates = draft.duplicate_candidates || [];
  const duplicateBlocked = duplicateCandidates.length > 0 && draft.duplicate_override !== true;
  const blockers = [
    ...(duplicateBlocked ? ["Найдена похожая кампания — подтвердите создание отдельной"] : []),
    ...(readiness.blockers || []),
  ];
  p0Elements.artifact.innerHTML = `
    ${p0ArtifactHead("Шаг 5 · единственное подтверждение", "Создать кампанию и отправить объявление на модерацию", "Перед внешней записью показывается ровно зафиксированная проекция и фактическая готовность guarded write-контура.", "OFFICIAL API")}
    <div class="p0-publish-grid"><article class="p0-publish-card"><span>01 · Кампания</span><h4>${p0Escape(direct.campaign?.Name)}</h4><p>Search WB_MAXIMUM_CLICKS · Network SERVING_OFF · после add немедленный suspend и readback.</p></article><article class="p0-publish-card"><span>02 · Группа</span><h4>${p0Escape(direct.ad_group?.Name)}</h4><p>Один регион · без автотаргетинга · минус-фразы публикуются.</p></article><article class="p0-publish-card"><span>03 · Ключевая фраза</span><h4>${p0Escape(direct.keyword?.Keyword)}</h4><p>Одна phrase без ручной keyword bid.</p></article><article class="p0-publish-card"><span>04 · Объявление</span><h4>${p0Escape(direct.ad?.TextAd?.Title)}</h4><p>${p0Escape(direct.ad?.TextAd?.Text)}<br>${p0Escape(direct.ad?.TextAd?.Href)}</p></article></div>
    <div class="p0-confirmation"><p class="eyebrow">Обещание перед записью</p><h4>Показы и списания не начнутся</h4><p>Кампания будет создана через официальный Direct API, немедленно остановлена и останется остановленной. P0 не вызывает resume. Модерация и измерение показываются отдельными фактическими статусами.</p></div>
    ${duplicateCandidates.length ? `<ul class="p0-question-list">${duplicateCandidates.map((name, index) => `<li><span>${index + 1}</span><div><strong>Похожая кампания в реальном аккаунте</strong><br>${p0Escape(name)}</div></li>`).join("")}</ul>` : ""}
    ${readiness.ready && !duplicateBlocked ? `<div class="p0-form-grid"><label class="is-wide"><span>Введите точное подтверждение CREATE_SUSPENDED_CAMPAIGN</span><input id="p0-confirmation" autocomplete="off"></label></div>${p0Actions("Создать реальную остановленную кампанию", "confirm_creation")}` : `<ul class="p0-write-blockers">${blockers.map((blocker, index) => `<li><span>${index + 1}</span><div>${p0Escape(blocker)}</div></li>`).join("")}</ul><div class="p0-artifact-actions"><span>Создание не показывается как доступное, пока все production gates не готовы.</span><button class="secondary-button" type="button" data-p0-back>Назад</button>${duplicateBlocked ? '<button class="primary-button" type="button" data-p0-action="confirm_distinct_campaign">Создать отдельную кампанию</button>' : ""}</div><p class="p0-inline-message" id="p0-message"></p>`}`;
}

function renderP0Campaign() {
  const campaign = state.p0Production.state.campaign || {};
  p0Elements.artifact.innerHTML = `
    ${p0ArtifactHead("Постоянная страница кампании", campaign.status || "Созданная кампания", "Это фактические статусы реального объекта Директа, а не одноразовый экран успеха.", "YANDEX DIRECT")}
    <div class="p0-campaign-status-strip"><div><span>Безопасное состояние</span><strong>${p0Escape(campaign.campaign_state || "Не подтверждено")}</strong><small>Показы не запускались</small></div><div><span>Модерация</span><strong>${p0Escape(campaign.moderation_status || "Ожидается")}</strong><small>Асинхронный внешний статус</small></div><div><span>Измерение</span><strong>${state.p0Production.context?.metrika?.ready ? "Цель подключена" : "Требует настройки"}</strong><small>Запуск относится к P1</small></div></div>
    <ul class="p0-publish-list">${(campaign.steps || []).map((step, index) => `<li><span>${index + 1}</span><div>${p0Escape(step)}</div></li>`).join("")}</ul>
    <div class="p0-artifact-actions"><span>Execution ${p0Escape(campaign.execution_id || "—")}</span><button class="secondary-button" type="button" data-p0-action="reset">Создать следующую кампанию</button></div><p class="p0-inline-message" id="p0-message"></p>`;
}

function renderP0() {
  if (!state.p0Production) return;
  const maxStep = p0MaxStep();
  state.p0Step = Math.min(state.p0Step ?? p0StateStep(), maxStep);
  p0Elements.steps.innerHTML = p0Steps.map(([title, detail], index) => `<li><button type="button" data-p0-step="${index}" ${index > maxStep ? "disabled" : ""} class="${index === state.p0Step ? "is-current" : ""} ${index < p0StateStep() || (index === 5 && p0StateStep() === 5) ? "is-done" : ""}"><span>${index < p0StateStep() || (index === 5 && p0StateStep() === 5) ? "✓" : index + 1}</span><div><strong>${p0Escape(title)}</strong><small>${p0Escape(detail)}</small></div></button></li>`).join("");
  renderP0Agent();
  [renderP0Context, renderP0Model, renderP0Strategy, renderP0Draft, renderP0Confirmation, renderP0Campaign][state.p0Step]();
}

async function loadP0() {
  if (!p0Elements.app) return;
  p0Elements.loading.hidden = false;
  p0Elements.error.hidden = true;
  try {
    state.p0Production = await requestJson("/api/p0");
    state.p0Step = p0StateStep();
    p0Elements.app.hidden = false;
    renderP0();
  } catch (error) {
    p0Elements.error.hidden = false;
    setText(p0Elements.error, error.message);
  } finally {
    p0Elements.loading.hidden = true;
  }
}

function p0FormValue(formId, names) {
  const form = document.querySelector(formId);
  if (!form || !form.reportValidity()) return null;
  const data = new FormData(form);
  return Object.fromEntries(names.map((name) => [name, String(data.get(name) || "").trim()]));
}

async function applyP0Action(action) {
  const message = document.querySelector("#p0-message");
  if (message) {
    message.classList.remove("is-error");
    setText(message, "Сохраняем production-ревизию…");
  }
  let value = null;
  let extra = {};
  if (action === "analyze_site") {
    value = p0FormValue("#p0-site-form", ["url"]);
    if (!value) return;
    extra = { url: value.url };
  } else if (action === "save_business_model") {
    value = p0FormValue("#p0-model-form", ["product", "audience", "value", "qualified_result", "exclusions"]);
    if (!value) return;
  } else if (action === "save_strategy") {
    value = p0FormValue("#p0-strategy-form", ["goal", "geography", "period_start", "period_end", "landing_page", "weekly_budget_rub", "target_cpa_rub", "message"]);
    if (!value) return;
    value.weekly_budget_rub = Number(value.weekly_budget_rub);
    value.target_cpa_rub = Number(value.target_cpa_rub);
  } else if (action === "save_draft") {
    value = p0FormValue("#p0-draft-form", ["campaign_name", "group_name", "keyword", "negative_keywords", "ad_title", "ad_text"]);
    if (!value) return;
    value.negative_keywords = value.negative_keywords.split(",").map((item) => item.trim()).filter(Boolean);
  } else if (action === "confirm_creation") {
    extra = { confirmation: document.querySelector("#p0-confirmation")?.value || "" };
  }
  try {
    const result = await requestJson("/api/p0", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action,
        expected_revision: state.p0Production.revision,
        ...(value ? { value } : {}),
        ...extra,
      }),
    });
    state.p0Production.revision = result.revision;
    state.p0Production.updated_at = result.updated_at;
    state.p0Production.state = result.state;
    state.p0Step = p0StateStep();
    renderP0();
  } catch (error) {
    const currentMessage = document.querySelector("#p0-message");
    if (currentMessage) {
      currentMessage.classList.add("is-error");
      setText(currentMessage, error.message);
    }
  }
}

p0Elements.steps?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-p0-step]");
  if (!button || button.disabled) return;
  state.p0Step = Number(button.dataset.p0Step);
  renderP0();
});

p0Elements.artifact?.addEventListener("click", (event) => {
  const back = event.target.closest("[data-p0-back]");
  if (back) {
    state.p0Step = Math.max(0, state.p0Step - 1);
    renderP0();
    return;
  }
  const action = event.target.closest("[data-p0-action]")?.dataset.p0Action;
  if (action) applyP0Action(action);
});

const p0StrategyLink = document.querySelector('[data-page-link="strategy"]');
p0StrategyLink?.addEventListener("click", () => {
  if (!state.p0Production) loadP0();
});
window.addEventListener("popstate", () => {
  if (window.location.pathname === "/strategy" && !state.p0Production) loadP0();
});
if (window.location.pathname === "/strategy") loadP0();
