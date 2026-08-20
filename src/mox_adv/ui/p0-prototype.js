/*
 * Throwaway prototype for issue 86.
 * Three variants of the production P0 path, switchable via ?variant=A|B|C,
 * mounted inside the accepted /prototype/mox-adv Dashboard route.
 */

(() => {
  const VARIANTS = [
    { key: "A", name: "Пошаговый маршрут" },
    { key: "B", name: "Стол агента" },
    { key: "C", name: "Контур готовности" },
  ];
  const query = new URLSearchParams(window.location.search);
  const requestedVariant = (query.get("variant") || "").toUpperCase();
  if (!VARIANTS.some((item) => item.key === requestedVariant)) return;

  const stages = [
    { short: "Готовность", title: "Проверить исходные подключения" },
    { short: "Модель", title: "Подтвердить модель бизнеса" },
    { short: "Стратегия", title: "Зафиксировать цель и стратегию" },
    { short: "Draft", title: "Проверить точную проекцию в Директ" },
    { short: "Подтверждение", title: "Разрешить единственную внешнюю запись" },
    { short: "Кампания", title: "Наблюдать фактическое состояние" },
  ];

  const state = {
    variant: requestedVariant,
    step: 0,
    maxStep: 0,
    directReady: true,
    metrikaReady: true,
    measurementReady: true,
    duplicateFound: false,
    duplicateOverride: false,
    creating: false,
    moderation: "PENDING",
    creationStatus: ["WAITING", "WAITING", "WAITING", "WAITING"],
    product: "Участие со стендом на ИННОПРОМ-2027",
    audience: "Руководители и коммерческие директора промышленных компаний",
    value: "Переговоры с промышленными заказчиками и партнёрами на одной площадке",
    qualifiedResult: "Заявка компании, готовой обсуждать формат участия со стендом",
    exclusions: "Посетители, соискатели, запросы билетов и общий информационный интерес",
    goal: "Получать квалифицированные заявки промышленных компаний",
    geography: "Россия",
    period: "01.09 — 30.11.2026",
    landing: "https://expo.innoprom.com/exhibitors",
    weeklyBudget: "50000",
    targetCpa: "12000",
    message: "Представьте технологию ключевым промышленным заказчикам на ИННОПРОМ-2027",
    campaignName: "MOX · ИННОПРОМ-2027 · Поиск",
    keyword: "участие в промышленной выставке",
    negativeKeywords: "билеты, посетить, вакансии, работа",
    adTitle: "Станьте экспонентом ИННОПРОМ-2027",
    adText: "Покажите технологии промышленным заказчикам. Получите условия участия.",
  };

  const existingBanner = document.querySelector("#public-demo-banner");
  if (existingBanner) existingBanner.hidden = true;
  const existingContext = document.querySelector(".hybrid-business-context");
  if (existingContext) existingContext.hidden = true;
  document.body.classList.add("is-p0-prototype");

  const header = document.querySelector(".app-header");
  const simulationBanner = document.createElement("aside");
  simulationBanner.className = "p0-simulation-banner";
  simulationBanner.innerHTML = `
    <strong>Прототип Production Module</strong>
    <span>Демонстрационные значения · все записи и статусы симулируются в памяти · внешние API-вызовы, показы и списания отключены</span>`;
  header.insertAdjacentElement("afterend", simulationBanner);

  const host = document.createElement("section");
  host.id = "p0-prototype-host";
  host.className = "p0-prototype-host";
  host.setAttribute("aria-live", "polite");
  simulationBanner.insertAdjacentElement("afterend", host);

  const switcher = document.createElement("nav");
  switcher.className = "p0-variant-switcher";
  switcher.setAttribute("aria-label", "Варианты P0-прототипа");
  document.body.append(switcher);

  const field = (label, key, options = {}) => {
    const wide = options.wide ? " p0-field-wide" : "";
    const value = state[key];
    const element = options.textarea
      ? `<textarea rows="${options.rows || 3}" data-p0-field="${key}">${value}</textarea>`
      : `<input ${options.type ? `type="${options.type}"` : ""} data-p0-field="${key}" value="${value}">`;
    return `<label class="p0-field${wide}"><span>${label}</span>${element}</label>`;
  };

  function stageHeader(eyebrow, title, copy) {
    return `<div class="p0-stage-heading"><div><p class="eyebrow">${eyebrow}</p><h2>${title}</h2><p>${copy}</p></div><span class="p0-sim-chip">Симуляция</span></div>`;
  }

  function readinessStage() {
    return `
      ${stageHeader("Шаг 1 · preflight", "Реальный контекст до создания", "Агент проверяет доступность сайта и подключений. Директ обязателен для записи; Метрика не блокирует безопасное создание остановленной кампании.")}
      <div class="p0-connection-grid">
        <article class="p0-connection is-ready"><div class="p0-icon">WEB</div><div><span>Сайт</span><strong>Доступен для анализа</strong><small>${state.landing}</small></div><button type="button" data-p0-action="site-unavailable">Нет доступа</button></article>
        <article class="p0-connection ${state.directReady ? "is-ready" : "is-blocked"}"><div class="p0-icon">ЯД</div><div><span>Яндекс Директ</span><strong>${state.directReady ? "Аккаунт доступен" : "Подключение обязательно"}</strong><small>${state.directReady ? "Разрешение записи будет запрошено отдельно" : "Создание кампании заблокировано"}</small></div><button type="button" data-p0-action="toggle-direct">${state.directReady ? "Сымитировать сбой" : "Восстановить"}</button></article>
        <article class="p0-connection ${state.metrikaReady ? "is-ready" : "is-warning"}"><div class="p0-icon">ЯМ</div><div><span>Яндекс Метрика</span><strong>${state.metrikaReady ? "Счётчик и цель найдены" : "Цель не найдена"}</strong><small>${state.metrikaReady ? "Квалифицированная заявка · read-only" : "Создание возможно, запуск будет заблокирован"}</small></div><button type="button" data-p0-action="toggle-metrika">${state.metrikaReady ? "Нет цели" : "Цель найдена"}</button></article>
      </div>
      <div class="p0-agent-note"><span>AI</span><div><strong>${state.directReady ? "Можно переходить к анализу бизнеса" : "Нужно восстановить подключение Директа"}</strong><p>${state.directReady ? "Я не буду повторно спрашивать то, что можно извлечь из сайта и подключений." : "Без подтверждённого аккаунта Директа внешняя запись недоступна."}</p></div></div>`;
  }

  function modelStage() {
    return `
      ${stageHeader("Шаг 2 · понимание бизнеса", "Модель, которую будет использовать агент", "Показываем выводы из сайта и просим исправить только то, что влияет на результат кампании.")}
      <div class="p0-model-summary"><div><span>AI</span><p>На сайте ясно описаны продукт и география. Я уточнил квалификацию заявки и исключения — эти ответы будут переиспользованы следующими кампаниями.</p></div><span class="p0-status is-good">Пробелы закрыты</span></div>
      <div class="p0-form-grid">
        ${field("Предложение", "product", { textarea: true, wide: true })}
        ${field("Кто принимает решение", "audience", { textarea: true })}
        ${field("Ценность для покупателя", "value", { textarea: true })}
        ${field("Квалифицированный результат", "qualifiedResult", { textarea: true })}
        ${field("Что исключаем", "exclusions", { textarea: true })}
      </div>
      <div class="p0-revision-note"><strong>Модель бизнеса · ревизия 1</strong><span>Изменения повлияют только на новые стратегии и не перепишут созданные кампании.</span></div>`;
  }

  function strategyStage() {
    return `
      ${stageHeader("Шаг 3 · business contract", "Цель и Campaign Strategy", "Владелец фиксирует бизнес-границы. Стратегию API и технические defaults агент выбирает сам и не выдаёт за продуктовый выбор.")}
      <div class="p0-strategy-summary"><div><span>Главная цель</span><strong>${state.goal}</strong></div><div><span>Ориентир</span><strong>${Number(state.targetCpa).toLocaleString("ru-RU")} ₽ за результат</strong></div><div><span>Предел</span><strong>${Number(state.weeklyBudget).toLocaleString("ru-RU")} ₽ в неделю</strong></div></div>
      <div class="p0-form-grid">
        ${field("Бизнес-цель кампании", "goal", { wide: true })}
        ${field("География", "geography")}
        ${field("Период", "period")}
        ${field("Посадочная страница", "landing", { wide: true })}
        ${field("Недельный бюджет, ₽", "weeklyBudget", { type: "number" })}
        ${field("Целевая стоимость результата, ₽", "targetCpa", { type: "number" })}
        ${field("Основное сообщение", "message", { textarea: true, wide: true })}
      </div>
      <div class="p0-agent-note"><span>AI</span><div><strong>Стартовый режим: накопление данных</strong><p>Целевой CPA остаётся бизнес-ориентиром. P0 не обещает уже работающую оптимизацию по конверсиям.</p></div></div>`;
  }

  function draftStage() {
    const conflict = state.duplicateFound
      ? `<div class="p0-conflict"><div><strong>Найдена похожая кампания</strong><p>«ИННОПРОМ · экспоненты · поиск» использует сходную посадочную страницу и фразу. Автоматическое подключение запрещено.</p></div><button type="button" data-p0-action="override-duplicate">${state.duplicateOverride ? "Отдельная кампания подтверждена" : "Создать отдельную кампанию"}</button></div>`
      : `<button class="p0-text-action" type="button" data-p0-action="find-duplicate">Сымитировать найденную похожую кампанию</button>`;
    return `
      ${stageHeader("Шаг 4 · publish projection", "Campaign Draft без скрытой магии", "Перед подтверждением виден ровно тот тонкий объект, который будет создан: одна кампания, одна группа, одна фраза и одно текстовое объявление.")}
      ${conflict}
      <div class="p0-draft-grid">
        <article><span class="p0-object-index">01</span><small>Кампания</small>${field("Название", "campaignName")}${field("Недельный бюджет, ₽", "weeklyBudget", { type: "number" })}<p>Поиск · сети отключены · останется остановленной</p></article>
        <article><span class="p0-object-index">02</span><small>Группа</small>${field("География", "geography")}${field("Минус-фразы", "negativeKeywords")}<p>Одна группа · без аудиторий и автотаргетинга</p></article>
        <article><span class="p0-object-index">03</span><small>Ключевая фраза</small>${field("Фраза", "keyword")}<p>Одна явная фраза · ставки управляются стартовой стратегией</p></article>
        <article><span class="p0-object-index">04</span><small>Текстовое объявление</small>${field("Заголовок", "adTitle")}${field("Текст", "adText", { textarea: true })}<p>${state.landing}</p></article>
      </div>
      <details class="p0-non-goals"><summary>Что намеренно не публикуется в P0</summary><p>Второе объявление, изображения, сети, автотаргетинг, дополнительные группы, фразы и цели. Ничто не будет молча отброшено.</p></details>`;
  }

  function confirmationStage() {
    const blockedByDuplicate = state.duplicateFound && !state.duplicateOverride;
    return `
      ${stageHeader("Шаг 5 · единственное подтверждение", "Создать реальную кампанию и отправить объявление на модерацию", "Это единственная точка, где будущий настоящий модуль выполнит внешнюю запись.")}
      <div class="p0-confirmation-promise">
        <span class="p0-lock">■</span>
        <div><p class="eyebrow">Обещание перед записью</p><h3>Показы и списания не начнутся</h3><p>После создания кампания будет немедленно остановлена и останется остановленной. Объявление уйдёт на асинхронную модерацию. Первый запуск относится к P1 и потребует отдельного решения.</p></div>
      </div>
      <dl class="p0-confirmation-facts"><div><dt>Аккаунт</dt><dd>Один разрешённый аккаунт Директа</dd></div><div><dt>Создаётся</dt><dd>1 кампания · 1 группа · 1 фраза · 1 объявление</dd></div><div><dt>Бюджет</dt><dd>${Number(state.weeklyBudget).toLocaleString("ru-RU")} ₽ / неделя</dd></div><div><dt>Измерение</dt><dd>${state.metrikaReady ? "Цель Метрики найдена" : "Требует настройки до запуска"}</dd></div></dl>
      ${blockedByDuplicate ? `<div class="p0-blocker">Сначала подтвердите создание отдельной кампании на предыдущем шаге.</div>` : ""}
      <button class="p0-danger-action" type="button" data-p0-action="create" ${blockedByDuplicate || !state.directReady ? "disabled" : ""}>Симулировать создание реальной кампании</button>
      <p class="p0-action-disclaimer">Прототип: кнопка не вызывает API и не создаёт объектов.</p>`;
  }

  function statusStage() {
    const statusLabels = [
      ["Создание объекта", "Кампания получила ID 107842"],
      ["Подтверждённая остановка", "State = SUSPENDED · readback совпал"],
      ["Объекты объявления", "Группа, фраза и объявление созданы"],
      ["Модерация", state.moderation === "ACCEPTED" ? "Принято" : state.moderation === "REJECTED" ? "Отклонено · нужно исправление" : "Проверяется Яндексом"],
    ];
    return `
      ${stageHeader("Постоянная страница кампании", state.campaignName, "Создание завершилось не экраном «Готово», а наблюдаемым объектом с независимыми фактическими статусами.")}
      <div class="p0-campaign-hero"><div><span class="p0-status is-stopped">Остановлена</span><span class="p0-campaign-id">Direct ID · 107842</span></div><strong>0 ₽ списано · показы не запускались</strong></div>
      <div class="p0-status-grid">
        ${statusLabels.map((item, index) => `<article class="${state.creationStatus[index] === "DONE" ? "is-done" : "is-waiting"}"><span>${index + 1}</span><div><small>${item[0]}</small><strong>${item[1]}</strong></div></article>`).join("")}
      </div>
      <div class="p0-outcome-grid">
        <article><p class="eyebrow">1 · безопасное состояние</p><h3>Создана и остановлена</h3><p>Остановка подтверждена чтением из Директа. P0 не предлагает запустить показы.</p></article>
        <article><p class="eyebrow">2 · модерация</p><h3>${state.moderation === "ACCEPTED" ? "Объявление принято" : state.moderation === "REJECTED" ? "Нужно исправление" : "Ожидаем решение Яндекса"}</h3><p>${state.moderation === "REJECTED" ? "Замечание: обещание результата требует уточнения. Доступен сфокусированный возврат в Draft." : "Статус обновляется отдельно и не меняет остановленное состояние кампании."}</p><div class="p0-simulation-controls"><button type="button" data-p0-action="moderation-accepted">Симулировать принятие</button><button type="button" data-p0-action="moderation-rejected">Симулировать отклонение</button>${state.moderation === "REJECTED" ? '<button type="button" data-p0-action="fix-rejection">Исправить замечание</button>' : ""}</div></article>
        <article><p class="eyebrow">3 · измерение</p><h3>${state.metrikaReady ? "Цель Метрики найдена" : "Настройка обязательна до запуска"}</h3><p>${state.metrikaReady ? "Объект цели связан. Фактическая доставка квалифицированной конверсии будет проверена до P1." : "Кампания создана безопасно, но не может перейти к запуску."}</p></article>
      </div>
      <div class="p0-next-module"><div><strong>P0 завершён на безопасной границе</strong><p>Первый запуск, расходы и автономное управление начинаются только в P1.</p></div><button type="button" data-p0-action="new-campaign">Создать ещё одну кампанию</button></div>`;
  }

  function stageContent() {
    return [readinessStage, modelStage, strategyStage, draftStage, confirmationStage, statusStage][state.step]();
  }

  function stepNav(mode = "vertical") {
    return `<ol class="p0-step-nav is-${mode}">${stages.map((stage, index) => {
      const done = index < state.step || (index === 5 && state.creationStatus[1] === "DONE");
      const current = index === state.step;
      return `<li class="${done ? "is-done" : ""} ${current ? "is-current" : ""}"><button type="button" data-p0-step="${index}" ${index > state.maxStep ? "disabled" : ""}><span>${done ? "✓" : index + 1}</span><small>${stage.short}</small></button></li>`;
    }).join("")}</ol>`;
  }

  function actionBar() {
    if (state.step === 5) return "";
    const previous = state.step > 0 ? '<button class="p0-secondary" type="button" data-p0-action="back">Назад</button>' : "";
    const labels = ["Анализировать сайт", "Подтвердить модель", "Сохранить Strategy", "Проверить перед записью", ""];
    const disabled = state.step === 0 && !state.directReady;
    return `<div class="p0-action-bar"><span>Прототип · изменения сохраняются только в памяти этой вкладки</span><div>${previous}<button class="p0-primary" type="button" data-p0-action="next" ${disabled ? "disabled" : ""}>${labels[state.step]}</button></div></div>`;
  }

  function variantA() {
    return `
      <div class="p0-titlebar"><div><p class="eyebrow">P0 · Стратегия и создание кампании</p><h1>Маршрут от сайта до остановленной кампании</h1><p>Один последовательный путь; на каждом шаге видны решение владельца и граница работы агента.</p></div><span class="p0-variant-note">A · Guided flow</span></div>
      <div class="p0-route-layout"><aside><p class="eyebrow">Маршрут</p>${stepNav("vertical")}<div class="p0-side-fact"><span>Внешних подтверждений</span><strong>1</strong><small>Только перед созданием</small></div></aside><main>${stageContent()}${actionBar()}</main></div>`;
  }

  function agentTranscript() {
    const messages = [
      ["Проверяю то, что уже доступно", "Сайт, аккаунт Директа и существующую цель Метрики."],
      ["Я собрал модель бизнеса", "Нужно подтвердить квалификацию результата и исключения."],
      ["Стратегия готова к ревизии", "Вы задаёте бизнес-границы; технический режим выбираю я."],
      ["Publish projection собрана", "Показываю только то, что действительно будет опубликовано в P0."],
      ["Нужно одно разрешение", "После него кампания останется остановленной, а объявление уйдёт на модерацию."],
      ["Кампания наблюдаема", "Статусы создания, модерации и измерения больше не смешиваются."],
    ];
    return `<div class="p0-chat"><div class="p0-chat-agent">AI</div><div><strong>${messages[state.step][0]}</strong><p>${messages[state.step][1]}</p></div></div>`;
  }

  function variantB() {
    return `
      <div class="p0-titlebar p0-titlebar-compact"><div><p class="eyebrow">P0 · совместная работа с агентом</p><h1>Стол агента</h1></div><span class="p0-variant-note">B · Copilot desk</span></div>
      ${stepNav("horizontal")}
      <div class="p0-desk-layout"><aside><div class="p0-thread-head"><span class="p0-live-dot"></span><div><strong>Диалог кампании</strong><small>Контекст сохраняется между шагами</small></div></div>${agentTranscript()}<div class="p0-thread-summary"><p class="eyebrow">Текущий артефакт</p><strong>${stages[state.step].title}</strong><p>Владелец отвечает только за продуктовый смысл. Проверки, проекция и безопасный lifecycle остаются агенту.</p></div><div class="p0-side-fact"><span>Риск расходов сейчас</span><strong>0 ₽</strong><small>Запуск не входит в P0</small></div></aside><main><div class="p0-artifact-label"><span>Рабочий артефакт</span><strong>Ревизия ${Math.min(state.step + 1, 5)}</strong></div>${stageContent()}${actionBar()}</main></div>`;
  }

  function readinessRail() {
    const gates = [
      ["Контекст", state.step > 0],
      ["Модель", state.step > 1],
      ["Strategy", state.step > 2],
      ["Projection", state.step > 3],
      ["Разрешение", state.step > 4],
      ["Suspended", state.creationStatus[1] === "DONE"],
    ];
    return `<div class="p0-gate-rail">${gates.map(([label, ready], index) => `<button type="button" data-p0-step="${index}" ${index > state.maxStep ? "disabled" : ""} class="${ready ? "is-ready" : index === state.step ? "is-current" : ""}"><span>${ready ? "✓" : index + 1}</span><small>${label}</small></button>`).join("")}</div>`;
  }

  function variantC() {
    const decisionCopy = [
      "Подключения дают достаточно фактов, чтобы не начинать с анкеты.",
      "Подтвердите, что модель правильно отделяет квалифицированный результат от шума.",
      "Зафиксируйте цель, бюджет, географию и сообщение.",
      "Проверьте точную и намеренно узкую проекцию в Директ.",
      "Разрешите создание, понимая безопасное конечное состояние.",
      "Следите за тремя независимыми внешними статусами.",
    ][state.step];
    return `
      <div class="p0-titlebar"><div><p class="eyebrow">P0 · readiness review</p><h1>Контур готовности к записи</h1><p>Путь организован как набор доказательств и gate-решений, а не как мастер настройки.</p></div><span class="p0-variant-note">C · Evidence first</span></div>
      ${readinessRail()}
      <div class="p0-readiness-layout"><main>${stageContent()}${actionBar()}</main><aside><p class="eyebrow">Решение владельца</p><h3>${stages[state.step].title}</h3><p>${decisionCopy}</p><dl><div><dt>Статус</dt><dd>${state.step === 5 ? "Зафиксирован" : "Нужно решение"}</dd></div><div><dt>Запись сейчас</dt><dd>${state.step === 4 ? "После подтверждения" : "Нет"}</dd></div><div><dt>Расходы</dt><dd>Заблокированы</dd></div></dl><div class="p0-agent-boundary"><strong>Агент решает сам</strong><p>API-тип, bidding strategy, RegionIds, retry, polling и readback.</p></div></aside></div>`;
  }

  function renderSwitcher() {
    const currentIndex = VARIANTS.findIndex((item) => item.key === state.variant);
    switcher.innerHTML = `<button type="button" data-p0-switch="prev" aria-label="Предыдущий вариант">←</button><span>${state.variant} — ${VARIANTS[currentIndex].name}</span><button type="button" data-p0-switch="next" aria-label="Следующий вариант">→</button>`;
  }

  function render() {
    host.innerHTML = state.variant === "A" ? variantA() : state.variant === "B" ? variantB() : variantC();
    renderSwitcher();
    document.title = `P0 · ${VARIANTS.find((item) => item.key === state.variant).name} · MOX-ADV`;
    document.querySelectorAll("[data-page-link]").forEach((link) => {
      link.classList.toggle("is-active", link.dataset.pageLink === "strategy");
    });
    host.querySelectorAll("[data-p0-field]").forEach((input) => {
      input.addEventListener("input", () => {
        state[input.dataset.p0Field] = input.value;
      });
    });
  }

  function goToStep(step) {
    state.step = Math.max(0, Math.min(5, step));
    state.maxStep = Math.max(state.maxStep, state.step);
    render();
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  async function simulateCreation(button) {
    if (state.creating) return;
    state.creating = true;
    button.disabled = true;
    button.textContent = "Симуляция записи…";
    for (let index = 0; index < state.creationStatus.length; index += 1) {
      state.creationStatus[index] = index < 3 ? "DONE" : "WAITING";
      await new Promise((resolve) => window.setTimeout(resolve, 260));
    }
    state.creationStatus[3] = "DONE";
    state.moderation = "PENDING";
    state.creating = false;
    goToStep(5);
  }

  function switchVariant(direction) {
    const currentIndex = VARIANTS.findIndex((item) => item.key === state.variant);
    const nextIndex = (currentIndex + direction + VARIANTS.length) % VARIANTS.length;
    state.variant = VARIANTS[nextIndex].key;
    const url = new URL(window.location.href);
    url.searchParams.set("variant", state.variant);
    url.searchParams.set("view", "strategy");
    window.history.replaceState({}, "", url);
    render();
  }

  host.addEventListener("click", async (event) => {
    const stepButton = event.target.closest("[data-p0-step]");
    if (stepButton && !stepButton.disabled) {
      goToStep(Number(stepButton.dataset.p0Step));
      return;
    }
    const button = event.target.closest("[data-p0-action]");
    if (!button) return;
    const action = button.dataset.p0Action;
    if (action === "next") goToStep(state.step + 1);
    if (action === "back") goToStep(state.step - 1);
    if (action === "toggle-direct") { state.directReady = !state.directReady; render(); }
    if (action === "toggle-metrika") { state.metrikaReady = !state.metrikaReady; state.measurementReady = state.metrikaReady; render(); }
    if (action === "site-unavailable") {
      state.product = "Внести реальные сведения о предложении вручную";
      goToStep(1);
    }
    if (action === "find-duplicate") { state.duplicateFound = true; state.duplicateOverride = false; render(); }
    if (action === "override-duplicate") { state.duplicateOverride = true; render(); }
    if (action === "create") await simulateCreation(button);
    if (action === "moderation-accepted") { state.moderation = "ACCEPTED"; render(); }
    if (action === "moderation-rejected") { state.moderation = "REJECTED"; render(); }
    if (action === "fix-rejection") { state.adText = "Покажите технологии промышленным заказчикам. Узнайте подтверждённые условия участия."; goToStep(3); }
    if (action === "new-campaign") {
      state.step = 0;
      state.maxStep = 0;
      state.duplicateFound = false;
      state.duplicateOverride = false;
      state.creationStatus = ["WAITING", "WAITING", "WAITING", "WAITING"];
      state.moderation = "PENDING";
      render();
    }
  });

  switcher.addEventListener("click", (event) => {
    const button = event.target.closest("[data-p0-switch]");
    if (!button) return;
    switchVariant(button.dataset.p0Switch === "next" ? 1 : -1);
  });

  document.addEventListener("keydown", (event) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    const target = event.target;
    if (target.matches("input, textarea, select, [contenteditable='true']")) return;
    event.preventDefault();
    switchVariant(event.key === "ArrowRight" ? 1 : -1);
  });

  document.querySelector(".main-nav")?.addEventListener("click", (event) => {
    const link = event.target.closest("[data-page-link]");
    if (!link || ["strategy", "campaign"].includes(link.dataset.pageLink)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const url = new URL(window.location.href);
    url.searchParams.delete("variant");
    url.searchParams.set("view", link.dataset.pageLink);
    window.location.assign(url);
  }, true);

  render();
})();
