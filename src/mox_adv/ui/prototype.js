const PAGES = new Set([
  "overview",
  "cycle",
  "autopilot",
  "rules",
  "history",
  "campaign",
  "control",
]);

const PAGE_TITLES = {
  overview: "Обзор",
  cycle: "Запуск цикла",
  autopilot: "Автопилот",
  rules: "Правила",
  history: "История",
  campaign: "Кампания",
  control: "Контроль",
};

const state = {
  page: "overview",
  automation: true,
  interval: 15,
  freeze: false,
  channel: "direct",
  running: false,
  campaignName: "Участие со стендом — ИННОПРОМ-2027",
  history: [
    {
      time: "День 12 · 10:30",
      origin: "По расписанию",
      trigger: "CPA сегмента выше цели",
      action: "Снизить ставку на 8%",
      reason: "Сегмент посетителей расходовал бюджет без квалифицированных заявок.",
      status: "Применено в Test Scenario",
    },
    {
      time: "День 11 · 18:15",
      origin: "SEO-наблюдение",
      trigger: "Страница готова к усилению",
      action: "Запросить решение владельца",
      reason: "Платное размещение и публикация выходят за действующий Mandate.",
      status: "Ждёт решения",
    },
    {
      time: "День 10 · 09:00",
      origin: "Ручной цикл",
      trigger: "Данные сопоставимы",
      action: "Сохранить настройки",
      reason: "Недостаточно данных для нового финансового изменения.",
      status: "Без изменений",
    },
  ],
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
let toastTimer = null;

function setText(selector, value) {
  const element = typeof selector === "string" ? $(selector) : selector;
  if (element) element.textContent = String(value);
}

function showToast(message) {
  const toast = $("#hybrid-toast");
  if (!toast) return;
  window.clearTimeout(toastTimer);
  toast.textContent = message;
  toast.classList.add("is-visible");
  toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 3200);
}

function pageFromLocation() {
  const query = new URLSearchParams(window.location.search);
  const candidate = query.get("view") || "overview";
  return PAGES.has(candidate) ? candidate : "overview";
}

function showPage(page, pushHistory = true) {
  const selected = PAGES.has(page) ? page : "overview";
  state.page = selected;
  $$('[data-page]').forEach((element) => {
    element.hidden = element.dataset.page !== selected;
  });
  $$('[data-page-link]').forEach((link) => {
    const active = link.dataset.pageLink === selected;
    link.classList.toggle("is-active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  if (pushHistory) {
    const url = new URL(window.location.href);
    url.pathname = window.location.pathname;
    url.searchParams.set("view", selected);
    window.history.pushState({ page: selected }, "", url);
  }
  document.title = `${PAGE_TITLES[selected]} · MOX-ADV Test Scenario`;
  window.scrollTo({ top: 0, behavior: "instant" });
}

function pageFromHref(href) {
  const pathname = new URL(href, window.location.href).pathname;
  const candidate = pathname.replace(/^\//, "");
  return PAGES.has(candidate) ? candidate : null;
}

function organizeOldDashboard() {
  const triggerRules = $(".automation-panel .rule-list");
  const host = $("#trigger-rules-host");
  if (triggerRules && host) {
    host.append(triggerRules);
    const secondary = $$(":scope > .rule-row", triggerRules).slice(3);
    if (secondary.length) {
      const details = document.createElement("details");
      details.className = "advanced-rules";
      details.innerHTML = `<summary>Дополнительные триггеры · ${secondary.length}</summary><div class="advanced-rules-list"></div>`;
      const list = $(".advanced-rules-list", details);
      secondary.forEach((row) => list.append(row));
      host.append(details);
    }
  }

  const scenarioFields = $(".scenario-fields");
  const secondaryFields = scenarioFields
    ? $$(":scope > label", scenarioFields).slice(6)
    : [];
  if (secondaryFields.length) {
    const details = document.createElement("details");
    details.className = "advanced-metrics";
    details.innerHTML = '<summary>Дополнительные показатели</summary><div class="advanced-metrics-grid"></div>';
    const grid = $(".advanced-metrics-grid", details);
    secondaryFields.forEach((field) => grid.append(field));
    scenarioFields.append(details);
  }
}

function numberValue(selector) {
  return Number($(selector)?.value || 0);
}

function renderDerivedMetrics() {
  const impressions = numberValue("#scenario-impressions");
  const clicks = numberValue("#scenario-clicks");
  const spend = numberValue("#scenario-spend");
  const conversions = numberValue("#scenario-conversions");
  const budget = numberValue("#scenario-budget");
  const ctr = impressions ? (clicks / impressions) * 100 : 0;
  const cpa = conversions ? spend / conversions : 0;
  const pacing = budget ? (spend / budget) * 100 : 0;
  const host = $("#derived-preview");
  if (!host) return;
  host.innerHTML = `
    <div><span>CTR</span><strong>${ctr.toFixed(1)}%</strong></div>
    <div><span>CPA</span><strong>${Math.round(cpa).toLocaleString("ru-RU")} ₽</strong></div>
    <div><span>Расход бюджета</span><strong>${Math.round(pacing)}%</strong></div>
    <div><span>Бизнес-цель</span><strong>Квалифицированная заявка</strong></div>`;
}

function updateOverview() {
  setText("#overview-automation-state", state.automation ? "Включен" : "Выключен");
  setText(
    "#overview-next-run",
    state.automation ? `Следующий Monitoring Cycle через 8 минут` : "Запуски не запланированы",
  );
  setText("#overview-last-decision", state.history[0]?.action || "Решений пока нет");
  setText("#overview-last-run", state.history[0]?.time || "Запустите первый цикл вручную");
  setText("#hybrid-decision-count", state.history.filter((item) => item.status === "Ждёт решения").length);
  setText(
    "#hybrid-agent-label",
    state.freeze ? "Изменения остановлены" : state.automation ? "Автопилот · каждые 15 минут" : "Ручной режим",
  );
  const service = $("#service-state");
  if (service) {
    service.classList.toggle("is-frozen", state.freeze);
    setText($("span:last-child", service), state.freeze ? "Изменения остановлены" : "Система готова");
  }
}

function markPipeline(index, status) {
  const item = $$("#pipeline li")[index];
  if (!item) return;
  item.classList.remove("is-running", "is-done", "is-skipped", "is-blocked");
  item.classList.add(status === "done" ? "is-done" : "is-running");
  setText($(".step-state", item), status === "done" ? "Готово" : "В работе");
}

function delay(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function addHistory(entry) {
  state.history.unshift(entry);
  renderHistory();
  updateOverview();
}

function renderCycleReport() {
  const spend = numberValue("#scenario-spend");
  const clicks = numberValue("#scenario-clicks");
  const impressions = numberValue("#scenario-impressions");
  const conversions = numberValue("#scenario-conversions");
  const cpa = conversions ? spend / conversions : 0;
  $("#empty-state").hidden = true;
  $("#blocked-panel").hidden = true;
  $("#report").hidden = false;
  setText("#workspace-title", "Предложение готово");
  setText("#run-status", "Нужно решение");
  $("#run-status").className = "run-status is-running";
  setText("#report-run-id", "TEST-HYBRID-001");
  setText("#report-period", "День 6 — День 12");
  setText("#report-campaign-goal", "Квалифицированная заявка промышленной компании");
  setText("#report-goal-target", "12 000 ₽");
  setText("#report-goal-actual", `${Math.round(cpa).toLocaleString("ru-RU")} ₽`);
  setText("#report-goal-status", cpa <= 12000 ? "Цель достигнута" : "Выше цели");
  $("#metrics").innerHTML = [
    ["Показы", impressions.toLocaleString("ru-RU")],
    ["Клики", clicks.toLocaleString("ru-RU")],
    ["Расход", `${spend.toLocaleString("ru-RU")} ₽`],
    ["Заявки", conversions.toLocaleString("ru-RU")],
    ["CPA", `${Math.round(cpa).toLocaleString("ru-RU")} ₽`],
  ].map(([label, value]) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`).join("");
  setText("#decision-title", "Снизить ставку проблемного сегмента");
  setText("#decision-copy", "Сегмент посетителей расходует бюджет без квалифицированных заявок. Остальная кампания сохраняет эффективность.");
  setText("#change-label", "Предложение");
  setText("#change-value", "−8%");
  setText("#execution-label", "Нужно ваше решение");
  setText("#execution-line", "Предложение готово и ещё не применено");
  setText("#safety-copy", "В Test Scenario внешние изменения отключены");
  $("#proposal-review").hidden = false;
  $("#proposal-step").value = "8";
}

async function runCycle() {
  if (state.running) return;
  state.running = true;
  const button = $("#run-button");
  button.disabled = true;
  setText("#workspace-title", "Выполняется Monitoring Cycle");
  setText("#run-status", "В работе");
  for (let index = 0; index < 5; index += 1) {
    markPipeline(index, "running");
    await delay(180);
    markPipeline(index, "done");
  }
  renderCycleReport();
  state.running = false;
  button.disabled = false;
}

function renderAutomation() {
  setText("#automation-state", state.automation ? "Включен" : "Выключен");
  setText("#toggle-automation", state.automation ? "Выключить автопилот" : "Включить автопилот");
  $("#automation-interval").value = String(state.interval);
  setText(
    "#automation-timing",
    state.automation ? `Monitoring Cycle выполняется каждые ${state.interval} минут. Следующий — через 8 минут.` : "Запуски не запланированы.",
  );
  updateOverview();
}

function renderRulesMatrix() {
  const body = $("#recommendation-matrix-body");
  if (!body) return;
  body.innerHTML = `
    <tr><td>CPA выше цели</td><td>Клики ≥ 30 и конверсии ≥ 2</td><td>Снизить ставку до лимита Mandate</td><td>Средний</td></tr>
    <tr><td>Расход без конверсий</td><td>Расход ≥ 2 000 ₽</td><td>Остановить проблемный сегмент</td><td>Высокий</td></tr>
    <tr><td>SEO требует покупки</td><td>Любой платный заказ</td><td>Передать владельцу</td><td>Требует решения</td></tr>`;
}

function renderHistory() {
  const host = $("#decision-history");
  if (!host) return;
  setText("#history-total", state.history.length);
  host.innerHTML = state.history.map((entry, index) => `
    <article>
      <div class="history-origin"><strong>${entry.origin}</strong><p>${entry.time}</p></div>
      <div><h4>${entry.trigger}</h4><p>${entry.action}</p></div>
      <p>${entry.reason}</p>
      <div class="history-status"><strong>${entry.status}</strong><br><span>Decision Record · Test Scenario</span><button class="history-outcome-link" type="button" data-outcome-index="${index}">Посмотреть исход</button></div>
    </article>`).join("");
}

function showHistoryTab(tab) {
  const outcomes = tab === "outcomes";
  $("#history-decisions-panel").hidden = outcomes;
  $("#history-outcomes-panel").hidden = !outcomes;
  $("#history-decisions-tab").setAttribute("aria-selected", String(!outcomes));
  $("#history-outcomes-tab").setAttribute("aria-selected", String(outcomes));
}

function renderOutcome(index) {
  const entry = state.history[index] || state.history[0];
  showHistoryTab("outcomes");
  $("#decision-outcome").innerHTML = `
    <div class="decision-outcome-head"><p>Решение от ${entry.time}</p><h3>${entry.action}</h3></div>
    <div class="accepted-decision"><p class="accepted-decision-label">Принятое решение</p><h4>${entry.action}</h4><p class="accepted-decision-reason">${entry.reason}</p><div class="accepted-decision-facts"><div><span>Статус</span><strong>${entry.status}</strong></div><div><span>Фактическое изменение</span><strong>−8% · readback совпал</strong></div></div></div>
    <div class="outcome-result-heading"><h4>Измеренный результат</h4><span class="automation-state">Наблюдение завершено</span></div>
    <div class="decision-outcome-grid"><section><h5>До изменения</h5><div><span>CPA</span><strong>18 900 ₽</strong></div><div><span>Конверсии</span><strong>2</strong></div><div><span>Расход</span><strong>37 400 ₽</strong></div></section><section><h5>После изменения</h5><div><span>CPA</span><strong>16 250 ₽</strong></div><div><span>Конверсии</span><strong>2</strong></div><div><span>Расход</span><strong>32 100 ₽</strong></div></section></div>
    <div class="decision-outcome-recommendation"><p class="eyebrow">Следующий шаг</p><h4>Сохранить изменение</h4><p>Продолжить наблюдение до следующего Monitoring Cycle.</p></div>`;
}

function renderCampaign() {
  setText("#campaign-count", "1");
  setText("#campaign-filter-count", "1 объект");
  const list = $("#campaign-list");
  list.innerHTML = `<tr class="is-selected"><td><strong>${state.campaignName}</strong><small>Россия · активна в Test Scenario</small></td><td>50 000 ₽ / нед.</td><td>12 000 ₽</td></tr>`;
  $("#campaign-name").value = state.campaignName;
  $("#campaign-weekly-budget").value = "2000";
  $("#campaign-keyword").value = "участие в промышленной выставке";
  $("#campaign-landing-page").value = "https://expo.innoprom.com/exhibitors";
  $("#campaign-business-goal").value = "Получать квалифицированные заявки промышленных компаний на участие со стендом.";
  $("#campaign-target-cpa").value = "1000";
  $("#campaign-counter-id").value = "TEST-784512";
  $("#campaign-goals").innerHTML = '<div class="campaign-goal-row"><label><span>Основная цель</span><input value="Отправка формы экспонента"></label><label><span>Ценность, ₽</span><input type="number" value="12000"></label><span class="campaign-goal-badge">PRIMARY</span></div>';
  $("#campaign-ad-group-select").innerHTML = '<option>Экспоненты · промышленность</option>';
  $("#campaign-ad-group-name").value = "Экспоненты · промышленность";
  $("#campaign-ad-group-keywords").value = "участие в промышленной выставке\nстать экспонентом\nвыставочный стенд";
  $("#campaign-ad-group-negative-keywords").value = "билеты\nпосетить\nработа";
  $("#campaign-ad-tabs").innerHTML = '<button class="is-active" type="button">Вариант A</button><button type="button">Вариант B</button>';
  $("#campaign-ad-editor").innerHTML = '<div class="campaign-field-grid"><label class="campaign-field-wide"><span>Заголовок</span><input value="Станьте экспонентом ИННОПРОМ-2027"></label><label class="campaign-field-wide"><span>Текст</span><textarea rows="3">Покажите технологии промышленным заказчикам. Получите условия участия.</textarea></label></div>';
  $("#launch-campaign").disabled = false;
}

function showCampaignChannel(channel) {
  state.channel = channel === "seo" ? "seo" : "direct";
  $$("[data-hybrid-channel]", $(".hybrid-channel-switch")).forEach((button) => {
    const active = button.dataset.hybridChannel === state.channel;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  $$("[data-direct-workspace]").forEach((element) => {
    element.hidden = state.channel === "seo";
  });
  $("#hybrid-seo-workspace").hidden = state.channel !== "seo";
}

function renderEvidence() {
  $$("#gate-strip [data-gate]").forEach((gate, index) => {
    setText($("strong", gate), index === 4 ? "READY FOR TEST" : "Готово");
    gate.classList.add("is-ready");
  });
  $$("#capability-matrix article").forEach((item) => {
    setText($("strong", item), "PROVEN · TEST");
    item.classList.add("is-proven");
  });
  setText("#evidence-message", "Test Scenario: проверены интерфейсные контракты; внешних вызовов не было.");
}

function updateFreeze() {
  setText("#kill-state", state.freeze ? "Включена" : "Снят");
  setText("#control-plane-message", state.freeze ? "Account Write Freeze включён. Наблюдение продолжается, новые изменения заблокированы." : "Account Write Freeze снят. Действия снова разрешены внутри Mandate.");
  updateOverview();
}

function bindNavigation() {
  document.addEventListener("click", (event) => {
    const hybridPage = event.target.closest("[data-hybrid-page]");
    if (hybridPage) {
      event.preventDefault();
      showPage(hybridPage.dataset.hybridPage);
      return;
    }
    const nav = event.target.closest("[data-nav]");
    if (!nav) return;
    const page = nav.dataset.pageLink || pageFromHref(nav.href);
    if (!page) return;
    event.preventDefault();
    showPage(page);
  });
  window.addEventListener("popstate", () => showPage(pageFromLocation(), false));
}

function bindInteractions() {
  $$(".mode-button").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.mode === "production") {
        showToast("Test Scenario не включает основной режим и внешние API-записи.");
        return;
      }
      showToast("Тестовый режим уже активен.");
    });
  });
  $$(".scenario-fields input, .scenario-fields select").forEach((input) => input.addEventListener("input", renderDerivedMetrics));
  $("#run-button")?.addEventListener("click", runCycle);
  $("#revise-proposal")?.addEventListener("click", () => {
    setText("#change-value", `−${$("#proposal-step").value}%`);
    setText("#proposal-message", "Правки сохранены только в Test Scenario.");
  });
  $("#accept-proposal")?.addEventListener("click", () => {
    $("#proposal-review").hidden = true;
    setText("#workspace-title", "Предложение применено в Test Scenario");
    setText("#execution-label", "Изменение принято");
    setText("#execution-line", `Ставка сегмента снижена на ${$("#proposal-step").value}%`);
    addHistory({ time: "Сейчас", origin: "Ручной цикл", trigger: "Решение владельца", action: `Снизить ставку на ${$("#proposal-step").value}%`, reason: "Владелец скорректировал и подтвердил предложение.", status: "Применено в Test Scenario" });
    showToast("Решение сохранено в памяти. В Яндекс Директ ничего не отправлено.");
  });
  $("#save-automation")?.addEventListener("click", () => {
    state.interval = Number($("#automation-interval").value);
    renderAutomation();
    setText("#automation-message", "Настройки сохранены только в Test Scenario.");
  });
  $("#toggle-automation")?.addEventListener("click", () => {
    state.automation = !state.automation;
    renderAutomation();
    setText("#automation-message", state.automation ? "Автопилот включён в Test Scenario." : "Автопилот выключен.");
  });
  $("#save-recommendation-rules")?.addEventListener("click", () => setText("#recommendation-message", "Правила и пороги сохранены в памяти браузера."));
  $("#save-hybrid-mandate")?.addEventListener("click", () => setText("#hybrid-mandate-message", "Mandate обновлён. Платные SEO-действия по-прежнему требуют отдельного решения."));
  $("#history-decisions-tab")?.addEventListener("click", () => showHistoryTab("decisions"));
  $("#history-outcomes-tab")?.addEventListener("click", () => showHistoryTab("outcomes"));
  $("#decision-history")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-outcome-index]");
    if (button) renderOutcome(Number(button.dataset.outcomeIndex));
  });
  $("#history-expand")?.addEventListener("click", () => showToast("В Test Scenario показан полный детерминированный журнал."));
  $("#engage-kill-switch")?.addEventListener("click", () => {
    state.freeze = true;
    updateFreeze();
    showToast("Новые изменения аварийно остановлены. Внешних вызовов не было.");
  });
  $("#release-kill-switch")?.addEventListener("click", () => {
    if ($("#kill-release-confirmation").value !== "RELEASE") {
      setText("#control-plane-message", "Для снятия блокировки введите RELEASE.");
      return;
    }
    state.freeze = false;
    updateFreeze();
  });
  $("#refresh-evidence")?.addEventListener("click", renderEvidence);
  $("#run-full-evidence")?.addEventListener("click", () => {
    renderEvidence();
    showToast("Самопроверка Test Scenario завершена без внешних вызовов.");
  });
  $("#save-campaign")?.addEventListener("click", () => {
    state.campaignName = $("#campaign-name").value.trim() || state.campaignName;
    renderCampaign();
    setText("#campaign-message", "Ревизия кампании сохранена только в памяти браузера.");
  });
  $("#launch-campaign")?.addEventListener("click", () => {
    setText("#campaign-launch-title", "Test Campaign Lifecycle завершён");
    setText("#campaign-launch-copy", "Все 8 этапов подтверждены на изолированных mock-адаптерах.");
    setText("#campaign-launch-steps", "8 из 8 этапов");
    setText("#campaign-launch-time", new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }));
    setText("#campaign-launch-run-id", "TEST-LIFECYCLE-001");
    showToast("Тестовый lifecycle завершён. Внешняя кампания не создавалась.");
  });
  $("#verify-campaign-goal")?.addEventListener("click", () => {
    setText("#campaign-goal-copy", "Событие формы найдено и доставлено изолированным mock-адаптером.");
    setText("#campaign-goal-event", "Проверено");
    setText("#campaign-goal-delivery", "SIMULATED");
    setText("#campaign-goal-optimization", "Ждёт подтверждения смысла");
    $("#approve-campaign-goal").hidden = false;
  });
  $("#approve-campaign-goal")?.addEventListener("click", () => {
    setText("#campaign-goal-optimization", "Допущена в Test Scenario");
    setText("#campaign-goal-message", "Бизнес-смысл цели подтверждён владельцем.");
  });
  $("#new-campaign")?.addEventListener("click", () => {
    $("#campaign-name").value = "Новая тестовая кампания";
    setText("#campaign-draft-status", "Новый локальный черновик");
  });
  $("#campaign-source-direct")?.addEventListener("click", () => {
    $("#campaign-editor").hidden = true;
    $("#direct-campaign-inspector").hidden = false;
    $("#campaign-inspector-actions").hidden = true;
    $("#campaign-source-test").classList.remove("is-active");
    $("#campaign-source-direct").classList.add("is-active");
    setText("#direct-campaign-id", "RO-107842");
    setText("#direct-campaign-type", "TEXT_CAMPAIGN");
    setText("#direct-campaign-state", "ON");
    setText("#direct-campaign-status", "ACCEPTED");
    setText("#direct-campaign-payment", "PAID");
    setText("#direct-campaign-budget", "7 140 ₽ / день");
    setText("#direct-campaign-client", "Test Scenario read-only snapshot");
  });
  $("#campaign-source-test")?.addEventListener("click", () => {
    $("#campaign-editor").hidden = false;
    $("#direct-campaign-inspector").hidden = true;
    $("#campaign-inspector-actions").hidden = false;
    $("#campaign-source-direct").classList.remove("is-active");
    $("#campaign-source-test").classList.add("is-active");
  });
  $$("[data-hybrid-channel]").forEach((button) => button.addEventListener("click", () => {
    if (!button.closest(".hybrid-channel-switch") && button.dataset.hybridChannel === "seo") showPage("campaign");
    showCampaignChannel(button.dataset.hybridChannel);
  }));
  $("#save-seo-draft")?.addEventListener("click", () => setText("#hybrid-seo-message", "SEO-черновик сохранён только в памяти браузера."));
  $("#request-seo-approval")?.addEventListener("click", () => {
    if (!state.history.some((item) => item.action === "Подтвердить SEO-изменение страницы")) {
      addHistory({ time: "Сейчас", origin: "SEO", trigger: "Изменение готово", action: "Подтвердить SEO-изменение страницы", reason: "Публикация контента требует решения владельца.", status: "Ждёт решения" });
    }
    setText("#hybrid-seo-message", "Предложение добавлено в Историю решений.");
  });
  $("#open-strategy")?.addEventListener("click", () => $("#hybrid-strategy-dialog").showModal());
  $("#hybrid-strategy-form")?.addEventListener("submit", (event) => {
    const submitter = event.submitter;
    if (submitter?.id !== "save-hybrid-strategy") return;
    event.preventDefault();
    const goal = $("#hybrid-strategy-goal").value.trim();
    if (goal) setText("#hybrid-goal-value", goal);
    $("#hybrid-strategy-dialog").close();
    showToast("Стратегия обновлена для всех рабочих контуров Test Scenario.");
  });
}

function initialize() {
  bindNavigation();
  organizeOldDashboard();
  renderDerivedMetrics();
  renderAutomation();
  renderRulesMatrix();
  renderHistory();
  renderCampaign();
  renderEvidence();
  updateFreeze();
  showCampaignChannel("direct");
  showHistoryTab("decisions");
  showPage(pageFromLocation(), false);
  bindInteractions();
}

initialize();
