const state = {
  mode: "test",
  currentPage: "overview",
  status: null,
  statusError: false,
  running: false,
  automation: null,
  knownHistoryRun: null,
  operatingMode: "OBSERVE",
  currentReportRunId: null,
  currentReport: null,
  currentProposalId: null,
  currentApprovalId: null,
  controlPlane: null,
  evidence: null,
};

const elements = {
  pages: Array.from(document.querySelectorAll("[data-page]")),
  navigationLinks: Array.from(document.querySelectorAll("[data-nav]")),
  pageLinks: Array.from(document.querySelectorAll("[data-page-link]")),
  overviewAutomationState: document.querySelector(
    "#overview-automation-state",
  ),
  overviewNextRun: document.querySelector("#overview-next-run"),
  overviewLastDecision: document.querySelector("#overview-last-decision"),
  overviewLastRun: document.querySelector("#overview-last-run"),
  modeButtons: Array.from(document.querySelectorAll(".mode-button")),
  modeName: document.querySelector("#mode-name"),
  modeDescription: document.querySelector("#mode-description"),
  modeIndicator: document.querySelector("#mode-indicator"),
  sourceList: document.querySelector("#source-list"),
  runButton: document.querySelector("#run-button"),
  runButtonLabel: document.querySelector("#run-button-label"),
  controlNote: document.querySelector("#control-note"),
  workspaceTitle: document.querySelector("#workspace-title"),
  runStatus: document.querySelector("#run-status"),
  pipeline: Array.from(document.querySelectorAll("#pipeline li")),
  emptyState: document.querySelector("#empty-state"),
  report: document.querySelector("#report"),
  blockedPanel: document.querySelector("#blocked-panel"),
  blockedMessage: document.querySelector("#blocked-message"),
  readinessChecks: document.querySelector("#readiness-checks"),
  metrics: document.querySelector("#metrics"),
  reportRunId: document.querySelector("#report-run-id"),
  reportPeriod: document.querySelector("#report-period"),
  decisionTitle: document.querySelector("#decision-title"),
  decisionCopy: document.querySelector("#decision-copy"),
  changeLabel: document.querySelector("#change-label"),
  changeValue: document.querySelector("#change-value"),
  executionLabel: document.querySelector("#execution-label"),
  executionLine: document.querySelector("#execution-line"),
  safetyCopy: document.querySelector("#safety-copy"),
  downloadReport: document.querySelector("#download-report"),
  proposalReview: document.querySelector("#proposal-review"),
  proposalStep: document.querySelector("#proposal-step"),
  reviseProposal: document.querySelector("#revise-proposal"),
  acceptProposal: document.querySelector("#accept-proposal"),
  proposalMessage: document.querySelector("#proposal-message"),
  testLab: document.querySelector("#test-lab"),
  scenarioInputs: {
    impressions: document.querySelector("#scenario-impressions"),
    clicks: document.querySelector("#scenario-clicks"),
    spend_rub: document.querySelector("#scenario-spend"),
    visits: document.querySelector("#scenario-visits"),
    conversions: document.querySelector("#scenario-conversions"),
    weekly_budget_rub: document.querySelector("#scenario-budget"),
    baseline_spend_rub: document.querySelector("#scenario-baseline-spend"),
    baseline_conversions: document.querySelector(
      "#scenario-baseline-conversions",
    ),
    expected_spend_rub: document.querySelector("#scenario-expected-spend"),
    baseline_impressions: document.querySelector(
      "#scenario-baseline-impressions",
    ),
    baseline_clicks: document.querySelector("#scenario-baseline-clicks"),
    baseline_visits: document.querySelector("#scenario-baseline-visits"),
    hours_since_last_conversion: document.querySelector(
      "#scenario-goal-silence",
    ),
    source_mismatch_percent: document.querySelector(
      "#scenario-source-mismatch",
    ),
    direct_age_minutes: document.querySelector("#scenario-direct-age"),
    metrika_age_minutes: document.querySelector("#scenario-metrika-age"),
    watermark_skew_minutes: document.querySelector(
      "#scenario-watermark-skew",
    ),
    external_change: document.querySelector("#scenario-external-change"),
    campaign_state: document.querySelector("#scenario-campaign-state"),
  },
  derivedPreview: document.querySelector("#derived-preview"),
  automationInterval: document.querySelector("#automation-interval"),
  automationState: document.querySelector("#automation-state"),
  saveAutomation: document.querySelector("#save-automation"),
  toggleAutomation: document.querySelector("#toggle-automation"),
  automationMessage: document.querySelector("#automation-message"),
  automationTiming: document.querySelector("#automation-timing"),
  ruleBudgetEnabled: document.querySelector("#rule-budget-enabled"),
  ruleBudgetThreshold: document.querySelector("#rule-budget-threshold"),
  ruleGrowthEnabled: document.querySelector("#rule-growth-enabled"),
  ruleGrowthThreshold: document.querySelector("#rule-growth-threshold"),
  ruleConversionCeiling: document.querySelector("#rule-conversion-ceiling"),
  ruleNoConversionEnabled: document.querySelector(
    "#rule-no-conversion-enabled",
  ),
  ruleNoConversionThreshold: document.querySelector(
    "#rule-no-conversion-threshold",
  ),
  extendedRules: {
    pacing_ahead: {
      enabled: document.querySelector("#rule-pacing-enabled"),
      threshold_percent: document.querySelector("#rule-pacing-threshold"),
    },
    cpc_deviation: {
      enabled: document.querySelector("#rule-cpc-enabled"),
      threshold_percent: document.querySelector("#rule-cpc-threshold"),
    },
    ctr_deviation: {
      enabled: document.querySelector("#rule-ctr-enabled"),
      threshold_percent: document.querySelector("#rule-ctr-threshold"),
    },
    conversion_rate_deviation: {
      enabled: document.querySelector("#rule-cvr-enabled"),
      threshold_percent: document.querySelector("#rule-cvr-threshold"),
    },
    goal_cessation: {
      enabled: document.querySelector("#rule-goal-enabled"),
      threshold_hours: document.querySelector("#rule-goal-hours"),
      minimum_visits: document.querySelector("#rule-goal-visits"),
    },
    source_mismatch: {
      enabled: document.querySelector("#rule-source-enabled"),
      threshold_percent: document.querySelector("#rule-source-threshold"),
    },
    external_change: {
      enabled: document.querySelector("#rule-external-enabled"),
    },
    freshness: {
      enabled: document.querySelector("#rule-freshness-enabled"),
      direct_minutes: document.querySelector("#rule-direct-freshness"),
      metrika_minutes: document.querySelector("#rule-metrika-freshness"),
      watermark_skew_minutes: document.querySelector(
        "#rule-watermark-freshness",
      ),
    },
  },
  recommendationInputs: {
    minimum_clicks: document.querySelector("#recommend-minimum-clicks"),
    minimum_conversions: document.querySelector(
      "#recommend-minimum-conversions",
    ),
    target_cpa_rub: document.querySelector("#recommend-target-cpa"),
    budget_pressure_percent: document.querySelector(
      "#recommend-budget-pressure",
    ),
    no_conversion_spend_rub: document.querySelector(
      "#recommend-no-conversion-spend",
    ),
    low_ctr_percent: document.querySelector("#recommend-low-ctr"),
    low_ctr_minimum_impressions: document.querySelector(
      "#recommend-low-ctr-impressions",
    ),
    bid_increase_maximum_clicks: document.querySelector(
      "#recommend-bid-max-clicks",
    ),
  },
  decisionRuleSelect: document.querySelector("#decision-rule-select"),
  selectedRuleTitle: document.querySelector("#selected-rule-title"),
  selectedRuleFormula: document.querySelector("#selected-rule-formula"),
  decisionRuleNote: document.querySelector("#decision-rule-note"),
  decisionCriterionLabels: Array.from(
    document.querySelectorAll("[data-criterion]"),
  ),
  decisionSafetyCriterionLabels: Array.from(
    document.querySelectorAll("[data-safety-criterion]"),
  ),
  decisionSafetyInputs: {
    source_mismatch_percent: document.querySelector(
      "#recommend-source-mismatch",
    ),
    direct_age_minutes: document.querySelector(
      "#recommend-direct-freshness",
    ),
    metrika_age_minutes: document.querySelector(
      "#recommend-metrika-freshness",
    ),
    watermark_skew_minutes: document.querySelector(
      "#recommend-watermark-freshness",
    ),
  },
  recommendationMatrixBody: document.querySelector(
    "#recommendation-matrix-body",
  ),
  saveRecommendationRules: document.querySelector(
    "#save-recommendation-rules",
  ),
  recommendationMessage: document.querySelector("#recommendation-message"),
  triggerRulesHost: document.querySelector("#trigger-rules-host"),
  decisionHistory: document.querySelector("#decision-history"),
  operatingModes: Array.from(
    document.querySelectorAll("#operating-modes button"),
  ),
  operatingModeNote: document.querySelector("#operating-mode-note"),
  approvalState: document.querySelector("#approval-state"),
  approvalFacts: document.querySelector("#approval-facts"),
  grantApproval: document.querySelector("#grant-approval"),
  applyApproval: document.querySelector("#apply-approval"),
  revokeApproval: document.querySelector("#revoke-approval"),
  mandateState: document.querySelector("#mandate-state"),
  mandateFacts: document.querySelector("#mandate-facts"),
  issueMandate: document.querySelector("#issue-mandate"),
  revokeMandate: document.querySelector("#revoke-mandate"),
  killState: document.querySelector("#kill-state"),
  killScope: document.querySelector("#kill-scope"),
  killReleaseConfirmation: document.querySelector(
    "#kill-release-confirmation",
  ),
  engageKillSwitch: document.querySelector("#engage-kill-switch"),
  releaseKillSwitch: document.querySelector("#release-kill-switch"),
  controlPlaneMessage: document.querySelector("#control-plane-message"),
  runCampaignWorkflow: document.querySelector("#run-campaign-workflow"),
  campaignWorkflowSteps: document.querySelector("#campaign-workflow-steps"),
  runGoalWorkflow: document.querySelector("#run-goal-workflow"),
  approveGoal: document.querySelector("#approve-goal"),
  rejectGoal: document.querySelector("#reject-goal"),
  goalWorkflowSteps: document.querySelector("#goal-workflow-steps"),
  workflowMessage: document.querySelector("#workflow-message"),
  impactFixture: document.querySelector("#impact-fixture"),
  runImpact: document.querySelector("#run-impact"),
  impactResult: document.querySelector("#impact-result"),
  refreshEvidence: document.querySelector("#refresh-evidence"),
  runFullEvidence: document.querySelector("#run-full-evidence"),
  evidenceReportDownload: document.querySelector(
    "#evidence-report-download",
  ),
  evidenceMessage: document.querySelector("#evidence-message"),
  capabilityMatrix: document.querySelector("#capability-matrix"),
  gateStrip: document.querySelector("#gate-strip"),
};

const metricDefinitions = [
  ["ctr_percent", "CTR", "%"],
  ["cpc_rub", "CPC", "₽"],
  ["conversion_rate_percent", "Конверсия", "%"],
  ["cpa_rub", "CPA", "₽"],
  ["budget_utilization_percent", "Бюджет", "%"],
];

const actionLabels = {
  INCREASE_WEEKLY_BUDGET: "Увеличить недельный бюджет",
  DECREASE_WEEKLY_BUDGET: "Уменьшить недельный бюджет",
  INCREASE_SEARCH_BID: "Увеличить поисковую ставку",
  DECREASE_SEARCH_BID: "Уменьшить поисковую ставку",
  SET_AD_VARIANT: "Сменить вариант объявления",
  SUSPEND_CAMPAIGN: "Приостановить кампанию",
  NO_CHANGE: "Сохранить текущие настройки",
  RESUME_CAMPAIGN: "Возобновить кампанию",
  REQUEST_HUMAN_HELP: "Передать человеку",
};

function formatRuleNumber(value) {
  return new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: 1,
  })
    .format(Number(value))
    .replace(/\u00a0/g, " ");
}

function enoughSampleFormula(rules) {
  return (
    `клики от ${formatRuleNumber(rules.minimum_clicks)}, конверсии от ` +
    `${formatRuleNumber(rules.minimum_conversions)}`
  );
}

const decisionRuleDefinitions = {
  SUSPEND_CAMPAIGN: {
    title: "Приостановить кампанию",
    outcome: "Тестовая кампания приостанавливается",
    criteria: ["no_conversion_spend_rub"],
    labels: {
      no_conversion_spend_rub: "Расход без конверсий от, ₽",
    },
    formula: (rules) =>
      `0 конверсий и расход от ${formatRuleNumber(
        rules.no_conversion_spend_rub,
      )} ₽.`,
  },
  NO_CHANGE_SAMPLE: {
    title: "Собрать больше данных",
    matrixAction: "NO_CHANGE",
    outcome: "Цикл запрашивает больше данных",
    criteria: ["minimum_clicks", "minimum_conversions"],
    labels: {
      minimum_clicks: "Кликов меньше",
      minimum_conversions: "Конверсий меньше",
    },
    formula: (rules) =>
      `Кликов меньше ${formatRuleNumber(
        rules.minimum_clicks,
      )} или конверсий меньше ${formatRuleNumber(
        rules.minimum_conversions,
      )}.`,
  },
  SET_AD_VARIANT: {
    title: "Сменить вариант объявления",
    outcome: "Активируется другой тестовый вариант объявления",
    criteria: [
      "minimum_clicks",
      "minimum_conversions",
      "low_ctr_percent",
      "low_ctr_minimum_impressions",
    ],
    labels: {
      minimum_clicks: "Кликов от",
      minimum_conversions: "Конверсий от",
      low_ctr_percent: "Низкий CTR, %",
      low_ctr_minimum_impressions: "Показов от",
    },
    formula: (rules) =>
      `CTR ниже ${formatRuleNumber(
        rules.low_ctr_percent,
      )}%, показов от ${formatRuleNumber(
        rules.low_ctr_minimum_impressions,
      )}; ${enoughSampleFormula(rules)}.`,
  },
  INCREASE_WEEKLY_BUDGET: {
    title: "Увеличить недельный бюджет",
    outcome: "Недельный бюджет увеличивается на 10%",
    criteria: [
      "minimum_clicks",
      "minimum_conversions",
      "target_cpa_rub",
      "budget_pressure_percent",
    ],
    labels: {
      minimum_clicks: "Кликов от",
      minimum_conversions: "Конверсий от",
      target_cpa_rub: "CPA не выше, ₽",
      budget_pressure_percent: "Использование бюджета от, %",
    },
    formula: (rules) =>
      `${enoughSampleFormula(rules)}; CPA не выше ${formatRuleNumber(
        rules.target_cpa_rub,
      )} ₽; использование бюджета от ${formatRuleNumber(
        rules.budget_pressure_percent,
      )}%.`,
  },
  DECREASE_WEEKLY_BUDGET: {
    title: "Уменьшить недельный бюджет",
    outcome: "Недельный бюджет уменьшается на 10%",
    criteria: [
      "minimum_clicks",
      "minimum_conversions",
      "target_cpa_rub",
      "budget_pressure_percent",
    ],
    labels: {
      minimum_clicks: "Кликов от",
      minimum_conversions: "Конверсий от",
      target_cpa_rub: "CPA выше, ₽",
      budget_pressure_percent: "Использование бюджета от, %",
    },
    formula: (rules) =>
      `${enoughSampleFormula(rules)}; CPA выше ${formatRuleNumber(
        rules.target_cpa_rub,
      )} ₽; использование бюджета от ${formatRuleNumber(
        rules.budget_pressure_percent,
      )}%.`,
  },
  DECREASE_SEARCH_BID: {
    title: "Уменьшить поисковую ставку",
    outcome: "Поисковая ставка уменьшается на 10%",
    criteria: [
      "minimum_clicks",
      "minimum_conversions",
      "target_cpa_rub",
      "budget_pressure_percent",
    ],
    labels: {
      minimum_clicks: "Кликов от",
      minimum_conversions: "Конверсий от",
      target_cpa_rub: "CPA выше, ₽",
      budget_pressure_percent: "Использование бюджета ниже, %",
    },
    formula: (rules) =>
      `${enoughSampleFormula(rules)}; CPA выше ${formatRuleNumber(
        rules.target_cpa_rub,
      )} ₽; использование бюджета ниже ${formatRuleNumber(
        rules.budget_pressure_percent,
      )}%.`,
  },
  INCREASE_SEARCH_BID: {
    title: "Увеличить поисковую ставку",
    outcome: "Поисковая ставка увеличивается на 10%",
    criteria: [
      "minimum_clicks",
      "minimum_conversions",
      "target_cpa_rub",
      "budget_pressure_percent",
      "bid_increase_maximum_clicks",
    ],
    labels: {
      minimum_clicks: "Кликов от",
      minimum_conversions: "Конверсий от",
      target_cpa_rub: "CPA не выше, ₽",
      budget_pressure_percent: "Использование бюджета ниже, %",
      bid_increase_maximum_clicks: "Кликов не больше",
    },
    formula: (rules) =>
      `${enoughSampleFormula(rules)}; CPA не выше ${formatRuleNumber(
        rules.target_cpa_rub,
      )} ₽; использование бюджета ниже ${formatRuleNumber(
        rules.budget_pressure_percent,
      )}%; кликов не больше ${formatRuleNumber(
        rules.bid_increase_maximum_clicks,
      )}.`,
  },
  RESUME_CAMPAIGN: {
    title: "Возобновить кампанию",
    outcome: "Кампания возобновляется только после подтверждения",
    criteria: [
      "minimum_clicks",
      "minimum_conversions",
      "target_cpa_rub",
    ],
    labels: {
      minimum_clicks: "Кликов от",
      minimum_conversions: "Конверсий от",
      target_cpa_rub: "CPA не выше, ₽",
    },
    formula: (rules) =>
      `Кампания приостановлена; ${enoughSampleFormula(
        rules,
      )}; CPA не выше ${formatRuleNumber(rules.target_cpa_rub)} ₽.`,
  },
  REQUEST_HUMAN_HELP: {
    title: "Передать решение человеку",
    outcome: "Применение останавливается, решение передаётся пользователю",
    criteria: [],
    safetyCriteria: [
      "source_mismatch_percent",
      "direct_age_minutes",
      "metrika_age_minutes",
      "watermark_skew_minutes",
    ],
    labels: {},
    formula: (_rules, safety) =>
      `Расхождение источников от ${formatRuleNumber(
        safety.source_mismatch_percent,
      )}% или задержка данных выше предела: Директ — ${formatRuleNumber(
        safety.direct_age_minutes,
      )} мин, Метрика — ${formatRuleNumber(
        safety.metrika_age_minutes,
      )} мин, разница времени — ${formatRuleNumber(
        safety.watermark_skew_minutes,
      )} мин. Внешнее изменение также передаёт решение человеку.`,
    note:
      "Эти пределы синхронизированы со стоп-условиями качества данных выше.",
  },
  NO_CHANGE: {
    title: "Сохранить текущие настройки",
    outcome: "Настройки сохраняются без изменения кампании",
    criteria: [
      "minimum_clicks",
      "minimum_conversions",
      "target_cpa_rub",
      "budget_pressure_percent",
      "no_conversion_spend_rub",
      "low_ctr_percent",
      "low_ctr_minimum_impressions",
      "bid_increase_maximum_clicks",
    ],
    labels: {
      minimum_clicks: "Минимум кликов",
      minimum_conversions: "Минимум конверсий",
      target_cpa_rub: "Целевой CPA, ₽",
      budget_pressure_percent: "Давление бюджета, %",
      no_conversion_spend_rub: "Расход без конверсий, ₽",
      low_ctr_percent: "Низкий CTR, %",
      low_ctr_minimum_impressions: "Показов для проверки CTR",
      bid_increase_maximum_clicks: "Кликов для роста ставки, до",
    },
    formula: () =>
      "Ни одно из условий решений с более высоким приоритетом не выполнено.",
    note:
      "Это резервное решение. Его границы меняются вместе с критериями остальных рекомендаций.",
  },
};

const decisionRuleOrder = [
  "REQUEST_HUMAN_HELP",
  "SUSPEND_CAMPAIGN",
  "NO_CHANGE_SAMPLE",
  "RESUME_CAMPAIGN",
  "SET_AD_VARIANT",
  "DECREASE_WEEKLY_BUDGET",
  "DECREASE_SEARCH_BID",
  "INCREASE_WEEKLY_BUDGET",
  "INCREASE_SEARCH_BID",
  "NO_CHANGE",
];

function operatorReason(value) {
  const text = String(value || "");
  const legacyPrefixes = [
    [
      "Точный одноразовый Approval подтверждён оператором.",
      "Предложение подтверждено пользователем.",
    ],
    [
      "Связанные показатели собраны. В режиме OBSERVE proposal и executor не запускаются.",
      "Связанные показатели собраны без применения изменений.",
    ],
    [
      "Ни один активный триггер не сработал. Рекомендация сохранена, executor не запускался.",
      "Ни один активный триггер не сработал. Предложение сохранено без изменения кампании.",
    ],
  ];
  for (const [technicalPrefix, operatorPrefix] of legacyPrefixes) {
    if (text.startsWith(technicalPrefix)) {
      return operatorPrefix + text.slice(technicalPrefix.length);
    }
  }
  return text;
}

const progressCopy = {
  direct: "Читаем данные Яндекс.Директа",
  metrika: "Читаем данные Яндекс.Метрики",
  analytics: "Рассчитываем связанные показатели",
  recommend: "Формируем решение",
  apply: "Проверяем границу исполнения",
};

function setText(element, value) {
  if (!element) return;
  element.textContent = String(value);
}

const pageTitles = {
  overview: "Обзор",
  cycle: "Запуск цикла",
  autopilot: "Автопилот",
  rules: "Правила",
  history: "История",
  workflows: "Сценарии",
  control: "Контроль",
};

function pageFromPath(pathname) {
  const candidate = pathname.replace(/^\/+|\/+$/g, "") || "overview";
  return Object.hasOwn(pageTitles, candidate) ? candidate : "overview";
}

function showPage(page, pushHistory = false) {
  const selectedPage = Object.hasOwn(pageTitles, page) ? page : "overview";
  state.currentPage = selectedPage;
  elements.pages.forEach((item) => {
    item.hidden =
      item.dataset.page !== selectedPage ||
      (item.classList.contains("scenario-panel") && state.mode !== "test");
  });
  elements.pageLinks.forEach((link) => {
    const active = link.dataset.pageLink === selectedPage;
    link.classList.toggle("is-active", active);
    if (active) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  });
  document.title = `${pageTitles[selectedPage]} — MOX-ADV`;
  if (pushHistory && window.location.pathname !== `/${selectedPage}`) {
    window.history.pushState({ page: selectedPage }, "", `/${selectedPage}`);
  }
  window.scrollTo({ top: 0, behavior: "instant" });
}

function organizePages() {
  const triggerRules = document.querySelector(".automation-panel .rule-list");
  if (triggerRules && elements.triggerRulesHost) {
    elements.triggerRulesHost.append(triggerRules);
    const secondaryRules = Array.from(
      triggerRules.querySelectorAll(":scope > .rule-row"),
    ).slice(3);
    if (secondaryRules.length) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      const rules = document.createElement("div");
      details.className = "advanced-rules";
      rules.className = "advanced-rules-list";
      setText(summary, `Дополнительные триггеры · ${secondaryRules.length}`);
      secondaryRules.forEach((rule) => rules.append(rule));
      details.append(summary, rules);
      elements.triggerRulesHost.append(details);
    }
  }

  const scenarioFields = document.querySelector(".scenario-fields");
  const secondaryFields = scenarioFields
    ? Array.from(scenarioFields.querySelectorAll(":scope > label")).slice(6)
    : [];
  if (scenarioFields && secondaryFields.length) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    const fields = document.createElement("div");
    details.className = "advanced-metrics";
    fields.className = "advanced-metrics-grid";
    setText(summary, "Дополнительные показатели");
    secondaryFields.forEach((field) => fields.append(field));
    details.append(summary, fields);
    scenarioFields.append(details);
  }
}

function updateMode() {
  const isTest = state.mode === "test";
  elements.modeButtons.forEach((button) => {
    const active = button.dataset.mode === state.mode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  setText(elements.modeName, isTest ? "Тестовые данные" : "Реальные данные");
  setText(
    elements.modeDescription,
    isTest
      ? "Укажите показатели кампании и посмотрите, какое решение примет система."
      : "Система проанализирует реальные данные Директа и Метрики. Кампания не изменится без вашего согласия.",
  );
  elements.modeIndicator.style.background = isTest ? "var(--green)" : "var(--amber)";
  elements.modeIndicator.style.boxShadow = isTest
    ? "0 0 0 4px var(--green-soft)"
    : "0 0 0 4px var(--amber-soft)";
  elements.sourceList.replaceChildren();
  const sources = isTest
    ? [
        ["Директ", "Тестовые данные"],
        ["Метрика", "Тестовые данные"],
        ["Кампания", "Без реальных изменений"],
      ]
    : [
        ["Директ", "Реальные данные"],
        ["Метрика", "Реальные данные"],
        ["Кампания", "Только после согласия"],
      ];
  sources.forEach(([label, value]) => {
    const item = document.createElement("li");
    const name = document.createElement("span");
    const detail = document.createElement("strong");
    setText(name, label);
    setText(detail, value);
    item.append(name, detail);
    elements.sourceList.append(item);
  });
  setText(
    elements.runButtonLabel,
    "Получить предложение",
  );
  setText(
    elements.controlNote,
    isTest
      ? "Реальная рекламная кампания не изменяется."
      : "Перед применением система обязательно попросит ваше согласие.",
  );
  elements.report.hidden = true;
  elements.blockedPanel.hidden = true;
  elements.emptyState.hidden = false;
  showPage(state.currentPage);
  resetPipeline();
  const readiness = state.status?.production_mode;
  const productionUnavailable = !isTest && readiness?.ready !== true;
  elements.runButton.disabled = state.running || productionUnavailable;
  if (productionUnavailable) {
    renderBlocked({
      message: state.statusError
        ? "Не удалось проверить готовность основного read-only режима."
        : readiness?.blockers?.[0] ||
          "Проверяется готовность основного read-only режима.",
    });
  }
}

function resetPipeline() {
  elements.pipeline.forEach((item) => {
    item.classList.remove("is-running", "is-done", "is-skipped", "is-blocked");
    setText(item.querySelector(".step-state"), "Ожидает");
  });
  setText(elements.workspaceTitle, "Готов к анализу");
  setStatus("Ожидание", "is-idle");
}

function setStatus(label, className) {
  elements.runStatus.className = `run-status ${className}`;
  setText(elements.runStatus, label);
}

function markStep(index, status) {
  const item = elements.pipeline[index];
  item.classList.remove("is-running", "is-done", "is-skipped", "is-blocked");
  if (status === "running") {
    item.classList.add("is-running");
    setText(item.querySelector(".step-state"), "В работе");
  } else if (status === "done") {
    item.classList.add("is-done");
    setText(item.querySelector(".step-state"), "Готово");
  } else if (status === "skipped") {
    item.classList.add("is-skipped");
    setText(item.querySelector(".step-state"), "Не выполняется");
  } else {
    item.classList.add("is-blocked");
    setText(item.querySelector(".step-state"), "Заблокировано");
  }
}

function renderConfirmedPipeline(steps) {
  for (const step of steps) {
    const index = elements.pipeline.findIndex(
      (item) => item.dataset.step === step.id,
    );
    if (index < 0) continue;
    const status =
      step.status === "PASSED"
        ? "done"
        : step.status === "SKIPPED"
          ? "skipped"
          : "blocked";
    markStep(index, status);
  }
}

function renderProgressEvent(event) {
  const index = elements.pipeline.findIndex(
    (item) => item.dataset.step === event.step,
  );
  if (index < 0) return;
  const status = {
    RUNNING: "running",
    PASSED: "done",
    SKIPPED: "skipped",
    BLOCKED: "blocked",
  }[event.status];
  if (!status) return;
  markStep(index, status);
  if (event.status === "RUNNING") {
    setText(
      elements.workspaceTitle,
      progressCopy[event.step] || "Выполняется read-only анализ",
    );
  }
}

function wait(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function parseStreamEvent(line) {
  const event = JSON.parse(line);
  if (!event || typeof event !== "object" || !event.type) {
    throw new Error("Сервер вернул некорректное событие прогресса.");
  }
  return event;
}

async function readProductionRun(response) {
  if (!response.ok || !response.body) {
    const payload = await response.json();
    const error = new Error(payload.message || payload.reason_code);
    error.payload = payload;
    throw error;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let report = null;

  const handleLine = async (line) => {
    if (!line.trim()) return;
    const event = parseStreamEvent(line);
    if (event.type === "progress") {
      renderProgressEvent(event);
      await wait(200);
      return;
    }
    if (event.type === "error") {
      const error = new Error(event.message || event.reason_code);
      error.payload = event;
      throw error;
    }
    if (event.type === "report") {
      report = event.report;
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      await handleLine(line);
    }
    if (done) break;
  }
  await handleLine(buffer);
  if (!report) {
    throw new Error("Поток завершился без итогового отчёта.");
  }
  return report;
}

function renderMetrics(metrics) {
  elements.metrics.replaceChildren();
  metricDefinitions.forEach(([key, label, unit]) => {
    const item = document.createElement("div");
    item.className = "metric";
    const name = document.createElement("span");
    const value = document.createElement("strong");
    const suffix = document.createElement("small");
    const unavailable = metrics[key] === "NOT_APPLICABLE";
    setText(name, label);
    setText(value, unavailable ? "Недоступно" : metrics[key]);
    setText(suffix, unavailable ? "" : unit);
    item.append(name, value, suffix);
    elements.metrics.append(item);
  });
}

function rublesFromMicros(value) {
  return new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: 0,
  }).format(Number(value) / 1_000_000);
}

function executionValue(value) {
  if (typeof value === "number") {
    return `${rublesFromMicros(value)} ₽`;
  }
  return (
    {
      ON: "Кампания включена",
      SUSPENDED: "Кампания приостановлена",
      A: "Вариант A",
      B: "Вариант B",
    }[value] || String(value ?? "—")
  );
}

function integerValue(input) {
  const value = Number(input.value);
  return Number.isFinite(value) ? Math.trunc(value) : 0;
}

function numericValue(input) {
  const value = Number(input.value);
  return Number.isFinite(value) ? value : 0;
}

function readScenario() {
  return Object.fromEntries(
    Object.entries(elements.scenarioInputs).map(([name, input]) => [
      name,
      name === "campaign_state"
        ? input.value
        : name === "external_change"
          ? input.checked
            ? 1
            : 0
          : integerValue(input),
    ]),
  );
}

function readRules() {
  const extended = Object.fromEntries(
    Object.entries(elements.extendedRules).map(([ruleName, inputs]) => [
      ruleName,
      Object.fromEntries(
        Object.entries(inputs).map(([name, input]) => [
          name,
          name === "enabled" ? input.checked : integerValue(input),
        ]),
      ),
    ]),
  );
  return {
    budget_pressure: {
      enabled: elements.ruleBudgetEnabled.checked,
      threshold_percent: integerValue(elements.ruleBudgetThreshold),
    },
    spend_growth_without_conversion: {
      enabled: elements.ruleGrowthEnabled.checked,
      threshold_rub: integerValue(elements.ruleGrowthThreshold),
      maximum_conversion_growth_percent: integerValue(
        elements.ruleConversionCeiling,
      ),
    },
    no_conversion_spend: {
      enabled: elements.ruleNoConversionEnabled.checked,
      threshold_rub: integerValue(elements.ruleNoConversionThreshold),
    },
    ...extended,
  };
}

function readRecommendationRules() {
  return Object.fromEntries(
    Object.entries(elements.recommendationInputs).map(([name, input]) => [
      name,
      name === "low_ctr_percent" ? numericValue(input) : integerValue(input),
    ]),
  );
}

function safetyRuleSourceInputs() {
  return {
    source_mismatch_percent:
      elements.extendedRules.source_mismatch.threshold_percent,
    direct_age_minutes: elements.extendedRules.freshness.direct_minutes,
    metrika_age_minutes: elements.extendedRules.freshness.metrika_minutes,
    watermark_skew_minutes:
      elements.extendedRules.freshness.watermark_skew_minutes,
  };
}

function readDecisionSafetyRules() {
  return Object.fromEntries(
    Object.entries(elements.decisionSafetyInputs).map(([name, input]) => [
      name,
      integerValue(input),
    ]),
  );
}

function syncDecisionSafetyInputsFromRules() {
  Object.entries(safetyRuleSourceInputs()).forEach(([name, input]) => {
    elements.decisionSafetyInputs[name].value = input.value;
  });
}

function renderDecisionRuleEditor() {
  const selected = elements.decisionRuleSelect.value;
  const definition =
    decisionRuleDefinitions[selected] ||
    decisionRuleDefinitions.SUSPEND_CAMPAIGN;
  const visibleCriteria = new Set(definition.criteria);
  const visibleSafetyCriteria = new Set(definition.safetyCriteria || []);

  elements.decisionCriterionLabels.forEach((label) => {
    const criterion = label.dataset.criterion;
    label.hidden = !visibleCriteria.has(criterion);
    if (visibleCriteria.has(criterion)) {
      setText(
        label.querySelector("span"),
        definition.labels[criterion] || criterion,
      );
    }
  });
  elements.decisionSafetyCriterionLabels.forEach((label) => {
    label.hidden = !visibleSafetyCriteria.has(label.dataset.safetyCriterion);
  });
  setText(elements.selectedRuleTitle, definition.title);
  setText(
    elements.selectedRuleFormula,
    definition.formula(
      readRecommendationRules(),
      readDecisionSafetyRules(),
    ),
  );
  setText(
    elements.decisionRuleNote,
    definition.note ||
      "Общие показатели синхронизируются между решениями и используются в следующем запуске цикла.",
  );
}

function populateDecisionRuleSelect() {
  elements.decisionRuleSelect.replaceChildren();
  decisionRuleOrder.forEach((ruleId) => {
    const option = document.createElement("option");
    option.value = ruleId;
    setText(option, decisionRuleDefinitions[ruleId].title);
    elements.decisionRuleSelect.append(option);
  });
}

function restoreDecisionRuleSelection() {
  try {
    const selected = window.localStorage.getItem(
      "mox-adv-selected-recommendation",
    );
    if (selected && decisionRuleDefinitions[selected]) {
      elements.decisionRuleSelect.value = selected;
    }
  } catch {
    // The editor still works when browser storage is unavailable.
  }
}

function renderRecommendationMatrix() {
  syncDecisionSafetyInputsFromRules();
  const rules = readRecommendationRules();
  const safetyRules = readDecisionSafetyRules();
  elements.recommendationMatrixBody.replaceChildren();
  decisionRuleOrder.forEach((ruleId, index) => {
    const definition = decisionRuleDefinitions[ruleId];
    const action = definition.matrixAction || ruleId;
    const row = document.createElement("tr");
    row.dataset.rule = ruleId;
    row.dataset.action = action;
    [
      String(index + 1).padStart(2, "0"),
      definition.formula(rules, safetyRules),
      definition.title,
      definition.outcome,
    ].forEach((value) => {
      const cell = document.createElement("td");
      setText(cell, value);
      row.append(cell);
    });
    elements.recommendationMatrixBody.append(row);
  });
  elements.recommendationMatrixBody
    .querySelectorAll("tr")
    .forEach((row) =>
      row.classList.toggle(
        "is-current",
        row.dataset.rule === elements.decisionRuleSelect.value,
      ),
    );
  renderDecisionRuleEditor();
}

function decisionRuleForRecommendation(recommendation) {
  const action = recommendation.primary_action || recommendation.action;
  if (
    action === "NO_CHANGE" &&
    recommendation.status === "INSUFFICIENT_DATA"
  ) {
    return "NO_CHANGE_SAMPLE";
  }
  return decisionRuleDefinitions[action] ? action : "NO_CHANGE";
}

function ratio(numerator, denominator, multiplier = 1) {
  if (!denominator) return "—";
  return ((numerator / denominator) * multiplier).toFixed(2);
}

function renderDerivedPreview() {
  const scenario = readScenario();
  const values = [
    ["CTR", ratio(scenario.clicks, scenario.impressions, 100), "%"],
    ["CPC", ratio(scenario.spend_rub, scenario.clicks), "₽"],
    ["Конверсия", ratio(scenario.conversions, scenario.visits, 100), "%"],
    ["CPA", ratio(scenario.spend_rub, scenario.conversions), "₽"],
    [
      "Бюджет",
      ratio(scenario.spend_rub, scenario.weekly_budget_rub, 100),
      "%",
    ],
  ];
  elements.derivedPreview.replaceChildren();
  values.forEach(([label, value, unit]) => {
    const item = document.createElement("div");
    const name = document.createElement("span");
    const metric = document.createElement("strong");
    setText(name, label);
    setText(metric, value === "—" ? value : `${value} ${unit}`);
    item.append(name, metric);
    elements.derivedPreview.append(item);
  });
}

function applyAutomationSettings(settings) {
  state.automation = settings;
  elements.automationInterval.value = String(settings.interval_minutes);
  Object.entries(settings.scenario).forEach(([name, value]) => {
    if (elements.scenarioInputs[name]) {
      if (name === "external_change") {
        elements.scenarioInputs[name].checked = Boolean(value);
      } else {
        elements.scenarioInputs[name].value = String(value);
      }
    }
  });
  const rules = settings.rules;
  elements.ruleBudgetEnabled.checked = rules.budget_pressure.enabled;
  elements.ruleBudgetThreshold.value = String(
    rules.budget_pressure.threshold_percent,
  );
  elements.ruleGrowthEnabled.checked =
    rules.spend_growth_without_conversion.enabled;
  elements.ruleGrowthThreshold.value = String(
    rules.spend_growth_without_conversion.threshold_rub,
  );
  elements.ruleConversionCeiling.value = String(
    rules.spend_growth_without_conversion.maximum_conversion_growth_percent,
  );
  elements.ruleNoConversionEnabled.checked =
    rules.no_conversion_spend.enabled;
  elements.ruleNoConversionThreshold.value = String(
    rules.no_conversion_spend.threshold_rub,
  );
  Object.entries(elements.extendedRules).forEach(([ruleName, inputs]) => {
    Object.entries(inputs).forEach(([name, input]) => {
      if (name === "enabled") {
        input.checked = rules[ruleName][name];
      } else {
        input.value = String(rules[ruleName][name]);
      }
    });
  });
  Object.entries(settings.recommendation_rules).forEach(([name, value]) => {
    if (elements.recommendationInputs[name]) {
      elements.recommendationInputs[name].value = String(value);
    }
  });
  renderAutomationState(settings);
  renderDerivedPreview();
  renderRecommendationMatrix();
}

function formatMoment(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(new Date(value));
}

function renderAutomationState(settings) {
  elements.automationState.classList.toggle("is-active", settings.enabled);
  setText(
    elements.automationState,
    settings.enabled ? "Автопилот включён" : "Автопилот выключен",
  );
  setText(
    elements.toggleAutomation,
    settings.enabled ? "Выключить автопилот" : "Включить автопилот",
  );
  setText(
    elements.automationTiming,
    settings.enabled
      ? `Последний запуск: ${formatMoment(settings.last_run_at)} · ` +
          `Следующий запуск: ${formatMoment(settings.next_run_at)}`
      : settings.last_run_at
        ? `Последний запуск: ${formatMoment(settings.last_run_at)}`
        : "Запуски ещё не выполнялись.",
  );
  setText(
    elements.overviewAutomationState,
    settings.enabled ? "Включён" : "Выключен",
  );
  setText(
    elements.overviewNextRun,
    settings.enabled
      ? `Следующий цикл: ${formatMoment(settings.next_run_at)}`
      : "Запуски не запланированы",
  );
}

function automationPayload(enabled) {
  return {
    enabled,
    mode: "test",
    operating_mode: "BOUNDED_AUTONOMY",
    interval_minutes: integerValue(elements.automationInterval),
    rules: readRules(),
    scenario: readScenario(),
    recommendation_rules: readRecommendationRules(),
  };
}

async function saveAutomation(enabled, source = "automation") {
  const message =
    source === "recommendation"
      ? elements.recommendationMessage
      : elements.automationMessage;
  elements.saveAutomation.disabled = true;
  elements.toggleAutomation.disabled = true;
  elements.saveRecommendationRules.disabled = true;
  message.classList.remove("is-error");
  setText(message, "Сохраняем настройки…");
  try {
    const response = await fetch("/api/test-automation", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(automationPayload(enabled)),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || payload.reason_code);
    }
    applyAutomationSettings(payload);
    if (source === "recommendation") {
      setText(message, "Логика решений сохранена.");
    } else {
      setText(
        message,
        payload.enabled
          ? "Автопилот включён. Циклы будут запускаться и применяться автоматически."
          : "Настройки сохранены.",
      );
    }
  } catch (error) {
    message.classList.add("is-error");
    setText(message, error.message);
  } finally {
    elements.saveAutomation.disabled = false;
    elements.toggleAutomation.disabled = false;
    elements.saveRecommendationRules.disabled = false;
  }
}

function historyOrigin(value) {
  return value === "SCHEDULED" ? "По расписанию" : "Ручной запуск";
}

function renderHistory(items) {
  elements.decisionHistory.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "history-empty";
    setText(empty, "История появится после первого тестового цикла.");
    elements.decisionHistory.append(empty);
    setText(elements.overviewLastDecision, "Решений пока нет");
    setText(elements.overviewLastRun, "Запустите первый цикл вручную");
    return;
  }
  const latest = items[0];
  setText(
    elements.overviewLastDecision,
    actionLabels[latest.action] || latest.action,
  );
  setText(
    elements.overviewLastRun,
    `${historyOrigin(latest.origin)} · ${formatMoment(latest.created_at)}`,
  );
  items.forEach((entry) => {
    const item = document.createElement("article");
    const origin = document.createElement("div");
    const originLabel = document.createElement("strong");
    const originTime = document.createElement("p");
    origin.className = "history-origin";
    setText(originLabel, historyOrigin(entry.origin));
    setText(originTime, formatMoment(entry.created_at));
    origin.append(originLabel, originTime);

    const trigger = document.createElement("div");
    const triggerTitle = document.createElement("h4");
    const triggerValue = document.createElement("p");
    const triggerLabels = entry.matched_triggers.length
      ? entry.matched_triggers.map((value) => value.label).join(", ")
      : "Без совпадения";
    setText(triggerTitle, triggerLabels);
    setText(triggerValue, actionLabels[entry.action] || entry.action);
    trigger.append(triggerTitle, triggerValue);

    const reason = document.createElement("p");
    setText(reason, operatorReason(entry.reason));

    const result = document.createElement("div");
    const status = document.createElement("strong");
    const link = document.createElement("a");
    result.className = "history-status";
    const executionLabels = {
      APPLIED: "Применено",
      PENDING_APPROVAL: "Ждёт решения",
      NO_CHANGE: "Без изменений",
      BLOCKED: "Остановлено",
      NOT_STARTED: "Не применялось",
    };
    setText(
      status,
      executionLabels[entry.execution_status] || entry.execution_status,
    );
    result.append(status, document.createElement("br"));
    if (entry.report_href) {
      link.href = entry.report_href;
      link.download = "";
      setText(link, "HTML-отчёт");
      result.append(link);
    } else {
      const noReport = document.createElement("span");
      setText(noReport, "Отчёт не создан");
      result.append(noReport);
    }
    item.append(origin, trigger, reason, result);
    elements.decisionHistory.append(item);
  });
}

async function refreshTestState(autoRenderLatest = false) {
  try {
    const [settingsResponse, historyResponse] = await Promise.all([
      fetch("/api/test-automation"),
      fetch("/api/test-history"),
    ]);
    if (!settingsResponse.ok || !historyResponse.ok) return;
    const settings = await settingsResponse.json();
    const history = await historyResponse.json();
    state.automation = settings;
    renderAutomationState(settings);
    renderHistory(history.items);
    const latest = history.items[0];
    const isNew = latest && latest.run_id !== state.knownHistoryRun;
    if (
      autoRenderLatest &&
      isNew &&
      latest.origin === "SCHEDULED" &&
      state.mode === "test" &&
      !state.running
    ) {
      const response = await fetch(`/api/runs/${latest.run_id}`);
      if (response.ok) {
        const report = await response.json();
        renderConfirmedPipeline(report.steps);
        renderReport(report);
      }
    }
    state.knownHistoryRun = latest?.run_id || null;
  } catch {
    // The manual test run remains usable when history refresh is unavailable.
  }
}

function renderReport(report) {
  state.currentReportRunId = report.run_id;
  state.currentReport = report;
  state.currentProposalId = report.recommendation.proposal_id || null;
  const readOnly = report.mode === "PRODUCTION_READ_ONLY";
  elements.emptyState.hidden = true;
  elements.blockedPanel.hidden = true;
  elements.report.hidden = false;
  elements.proposalReview.hidden = true;
  elements.proposalMessage.classList.remove("is-error");
  setText(elements.proposalMessage, "");
  setText(
    elements.workspaceTitle,
    readOnly && report.recommendation.status === "NEEDS_HUMAN"
      ? "Анализ завершён · нужна проверка"
      : readOnly
        ? "Анализ завершён"
        : "Цикл завершён",
  );
  setStatus(
    readOnly && report.recommendation.status === "NEEDS_HUMAN"
      ? "Нужна проверка"
      : "Успешно",
    "is-running",
  );
  setText(elements.reportRunId, report.run_id);
  setText(
    elements.reportPeriod,
    `${report.period.start} — ${report.period.end}`,
  );
  renderMetrics(report.metrics);
  setText(
    elements.decisionTitle,
    actionLabels[
      report.recommendation.primary_action || report.recommendation.action
    ] ||
      report.recommendation.primary_action ||
      report.recommendation.action,
  );
  setText(
    elements.decisionCopy,
    operatorReason(
      report.decision?.reason || report.recommendation.explanation_ru,
    ),
  );
  setText(elements.changeLabel, readOnly ? "Предложение" : "Изменение");
  setText(
    elements.changeValue,
    report.recommendation.relative_step_percent
      ? `${
          report.recommendation.action.startsWith("DECREASE") ? "-" : "+"
        }${report.recommendation.relative_step_percent}%`
      : "Без изменения",
  );
  elements.decisionRuleSelect.value = decisionRuleForRecommendation(
    report.recommendation,
  );
  renderRecommendationMatrix();
  if (readOnly) {
    setText(elements.executionLabel, "Результат");
    setText(
      elements.executionLine,
      "Рекомендация сформирована · не применено",
    );
    setText(
      elements.safetyCopy,
      "Реальная кампания не изменена",
    );
  } else if (
    report.execution.status === "NOT_STARTED" &&
    report.execution.reason_code === "READ_ONLY_MODE"
  ) {
    setText(elements.executionLabel, "Результат");
    setText(
      elements.executionLine,
      "Рекомендация сформирована · не применено",
    );
    setText(
      elements.safetyCopy,
      "Реальная кампания не изменена",
    );
  } else if (report.execution.status === "PENDING_APPROVAL") {
    setText(elements.executionLabel, "Нужно ваше решение");
    setText(
      elements.executionLine,
      "Предложение готово и ещё не применено",
    );
    setText(
      elements.safetyCopy,
      "Вы можете изменить размер шага или принять предложение",
    );
    const step = Number(report.recommendation.relative_step_percent || 0);
    elements.proposalReview.hidden = false;
    elements.proposalStep.value = String(step || 1);
    elements.proposalStep.disabled = step <= 0;
    elements.reviseProposal.disabled = step <= 0;
    elements.acceptProposal.disabled = false;
    setText(elements.approvalState, "Ожидает решения");
    setFactValues(elements.approvalFacts, [
      report.recommendation.proposal_id,
      report.recommendation.action,
      `${executionValue(report.execution.before_micros)} → ${executionValue(
        report.execution.after_micros,
      )}`,
      report.recommendation.risks.join(", "),
      "30 минут",
    ]);
  } else if (report.execution.status === "APPLIED") {
    setText(elements.executionLabel, "Изменение применено");
    setText(
      elements.executionLine,
      `${executionValue(report.execution.before_micros)} → ` +
        `${executionValue(report.execution.after_micros)}`,
    );
    setText(
      elements.safetyCopy,
      report.safety.external_write_sent
        ? "Изменение подтверждено в рекламной системе"
        : "Тестовый результат подтверждён без изменения реальной кампании",
    );
  } else if (report.execution.status === "NO_CHANGE") {
    setText(elements.executionLabel, "Результат решения");
    setText(
      elements.executionLine,
      "Изменение не требуется · write-вызов не выполнялся",
    );
    setText(
      elements.safetyCopy,
      "Безопасная проверка завершила цикл без изменения",
    );
  } else {
    setText(elements.executionLabel, "Результат проверки");
    setText(
      elements.executionLine,
      "Применение остановлено безопасной проверкой",
    );
    setText(
      elements.safetyCopy,
      "Реальная кампания не изменена",
    );
  }
  elements.downloadReport.href = report.artifacts.html;
}

function renderBlocked(payload, preservePipeline = false) {
  elements.report.hidden = true;
  elements.emptyState.hidden = true;
  elements.blockedPanel.hidden = false;
  setText(elements.workspaceTitle, "Требуется настройка");
  setStatus("Заблокировано", "is-blocked");
  setText(elements.blockedMessage, payload.message);
  elements.readinessChecks.replaceChildren();
  const checks = state.status?.production_mode?.checks || [];
  checks.forEach((check) => {
    const item = document.createElement("li");
    setText(item, `${check.ready ? "Готово" : "Требуется"} · ${check.label}`);
    elements.readinessChecks.append(item);
  });
  if (preservePipeline) {
    elements.pipeline.forEach((item, index) => {
      if (item.classList.contains("is-running")) {
        markStep(index, "blocked");
      }
    });
  } else {
    elements.pipeline.forEach((_, index) => markStep(index, "blocked"));
  }
}

async function run() {
  if (state.running) return;
  state.running = true;
  elements.runButton.disabled = true;
  elements.report.hidden = true;
  elements.blockedPanel.hidden = true;
  elements.emptyState.hidden = false;
  resetPipeline();
  setText(
    elements.workspaceTitle,
    state.mode === "test"
      ? "Выполняется тестовый цикл"
      : "Анализируем реальные данные",
  );
  setStatus("В работе", "is-running");
  try {
    const requestPayload = {
      mode: state.mode,
    };
    if (state.mode === "test") {
      requestPayload.scenario = readScenario();
      requestPayload.rules = readRules();
      requestPayload.recommendation_rules = readRecommendationRules();
    }
    const runUrl =
      state.mode === "production" ? "/api/runs/stream" : "/api/runs";
    const response = await fetch(runUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestPayload),
    });
    const payload =
      state.mode === "production"
        ? await readProductionRun(response)
        : await response.json();
    if (!response.ok || payload.status === "BLOCKED") {
      if (state.mode === "production") {
        try {
          const statusResponse = await fetch("/api/status");
          if (statusResponse.ok) {
            state.status = await statusResponse.json();
            state.statusError = false;
          }
        } catch {
          state.status = null;
          state.statusError = true;
        }
      }
      renderBlocked(payload);
      return;
    }
    renderConfirmedPipeline(payload.steps);
    renderReport(payload);
    if (state.mode === "test") {
      await refreshTestState(false);
      await refreshControlPlane();
    }
  } catch (error) {
    const payload = error.payload || {
      message: `Локальный UI не получил ответ: ${error.message}`,
    };
    if (state.mode === "production") {
      try {
        const statusResponse = await fetch("/api/status");
        if (statusResponse.ok) {
          state.status = await statusResponse.json();
          state.statusError = false;
        }
      } catch {
        state.status = null;
        state.statusError = true;
      }
    }
    renderBlocked(payload, state.mode === "production");
  } finally {
    state.running = false;
    elements.runButton.disabled =
      state.mode === "production" &&
      (!elements.blockedPanel.hidden ||
        state.status?.production_mode?.ready !== true);
  }
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok || payload.status === "BLOCKED") {
    throw new Error(payload.message || payload.reason_code || "Операция отклонена.");
  }
  return payload;
}

async function reviseCurrentProposal() {
  if (!state.currentReportRunId) return;
  const relativeStep = Number(elements.proposalStep.value);
  elements.reviseProposal.disabled = true;
  elements.acceptProposal.disabled = true;
  elements.proposalMessage.classList.remove("is-error");
  setText(elements.proposalMessage, "Сохраняем правки…");
  try {
    const report = await requestJson("/api/proposals/revise", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_id: state.currentReportRunId,
        relative_step_percent: relativeStep,
      }),
    });
    renderConfirmedPipeline(report.steps);
    renderReport(report);
    setText(elements.proposalMessage, "Правки сохранены. Предложение обновлено.");
    await Promise.all([refreshTestState(false), refreshControlPlane()]);
  } catch (error) {
    elements.proposalMessage.classList.add("is-error");
    setText(elements.proposalMessage, error.message);
    elements.reviseProposal.disabled = false;
    elements.acceptProposal.disabled = false;
  }
}

async function acceptCurrentProposal() {
  if (!state.currentReportRunId) return;
  const runId = state.currentReportRunId;
  elements.reviseProposal.disabled = true;
  elements.acceptProposal.disabled = true;
  elements.proposalMessage.classList.remove("is-error");
  setText(elements.proposalMessage, "Применяем согласованное предложение…");
  try {
    await requestJson("/api/control-plane/approvals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "grant_latest", run_id: runId }),
    });
    const report = await requestJson("/api/control-plane/approvals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "apply_latest", run_id: runId }),
    });
    renderConfirmedPipeline(report.steps);
    renderReport(report);
    setText(elements.workspaceTitle, "Предложение применено");
    await Promise.all([refreshTestState(false), refreshControlPlane()]);
  } catch (error) {
    elements.proposalMessage.classList.add("is-error");
    setText(elements.proposalMessage, error.message);
    elements.reviseProposal.disabled = false;
    elements.acceptProposal.disabled = false;
  }
}

function setFactValues(container, values) {
  const targets = Array.from(container.querySelectorAll("dd"));
  values.forEach((value, index) => {
    if (targets[index]) setText(targets[index], value);
  });
}

function renderControlPlane(control) {
  state.controlPlane = control;
  state.operatingMode = control.operating_mode.selected;

  const approval = state.currentProposalId
    ? control.approvals.find(
        (item) => item.proposal_id === state.currentProposalId,
      )
    : control.approvals[0];
  const displayedReportPending =
    state.currentReport?.execution?.status === "PENDING_APPROVAL";
  const pendingReport =
    !approval && displayedReportPending ? state.currentReport : null;
  state.currentApprovalId = approval?.approval_id || null;
  setText(
    elements.approvalState,
    approval
      ? approval.status
      : pendingReport
        ? "Ожидает решения"
        : "Нет активного",
  );
  setFactValues(
    elements.approvalFacts,
    approval
      ? [
          approval.proposal_id,
          approval.change.action,
          `${executionValue(approval.change.current_value)} → ${executionValue(
            approval.change.target_value,
          )}`,
          approval.change.risk,
          formatMoment(approval.expires_at),
        ]
      : pendingReport
        ? [
            pendingReport.recommendation.proposal_id,
            pendingReport.recommendation.action,
            `${executionValue(
              pendingReport.execution.before_micros,
            )} → ${executionValue(pendingReport.execution.after_micros)}`,
            pendingReport.recommendation.risks.join(", "),
            "30 минут",
          ]
      : ["—", "—", "—", "—", "—"],
  );
  elements.revokeApproval.disabled =
    !approval || !["AVAILABLE", "RESERVED"].includes(approval.status);
  elements.applyApproval.disabled =
    !approval || approval.status !== "AVAILABLE";
  elements.grantApproval.disabled =
    !displayedReportPending ||
    (Boolean(approval) && ["AVAILABLE", "RESERVED"].includes(approval.status));

  const mandate =
    control.mandates.find((item) => item.status === "ACTIVE") ||
    control.mandates[0];
  setText(elements.mandateState, mandate ? mandate.status : "Не активен");
  setFactValues(
    elements.mandateFacts,
    mandate
      ? [
          mandate.scope.targets.join(", "),
          `${mandate.quotas.daily_change_percent.limit}%`,
          `${mandate.quotas.actions_per_24h.used} / ` +
            `${mandate.quotas.actions_per_24h.limit}`,
          formatMoment(mandate.expires_at),
        ]
      : ["Simulation campaign", "10%", "0 / 1", "—"],
  );
  elements.revokeMandate.disabled =
    !mandate || !["ACTIVE", "ISSUED"].includes(mandate.status);

  const activeKill = control.kill_switches.find((item) => item.active);
  setText(elements.killState, activeKill ? "Активен" : "Снят");
  elements.killState.classList.toggle("is-active", Boolean(activeKill));
}

async function refreshControlPlane() {
  try {
    renderControlPlane(await requestJson("/api/control-plane"));
  } catch (error) {
    elements.controlPlaneMessage.classList.add("is-error");
    setText(elements.controlPlaneMessage, error.message);
  }
}

async function selectOperatingMode(mode) {
  elements.operatingModes.forEach((button) => {
    button.disabled = true;
  });
  try {
    await requestJson("/api/control-plane/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    await refreshControlPlane();
    setText(
      elements.controlPlaneMessage,
      `Операционный режим изменён: ${mode}.`,
    );
  } catch (error) {
    elements.controlPlaneMessage.classList.add("is-error");
    setText(elements.controlPlaneMessage, error.message);
  } finally {
    elements.operatingModes.forEach((button) => {
      button.disabled = false;
    });
  }
}

async function updateKillSwitch(action) {
  elements.engageKillSwitch.disabled = true;
  elements.releaseKillSwitch.disabled = true;
  try {
    const result = await requestJson("/api/control-plane/kill-switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action,
        scope: elements.killScope.value,
        confirmation:
          action === "release"
            ? elements.killReleaseConfirmation.value
            : undefined,
      }),
    });
    await refreshControlPlane();
    setText(
      elements.controlPlaneMessage,
      result.active
        ? `Kill switch активирован: ${result.scope}.`
        : `Kill switch снят: ${result.scope}.`,
    );
    if (action === "release") {
      elements.killReleaseConfirmation.value = "";
    }
  } catch (error) {
    elements.controlPlaneMessage.classList.add("is-error");
    setText(elements.controlPlaneMessage, error.message);
  } finally {
    elements.engageKillSwitch.disabled = false;
    elements.releaseKillSwitch.disabled = false;
  }
}

async function updateMandate(action) {
  elements.issueMandate.disabled = true;
  elements.revokeMandate.disabled = true;
  try {
    const result = await requestJson("/api/control-plane/mandates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    await refreshControlPlane();
    setText(
      elements.controlPlaneMessage,
      action === "issue"
        ? `Mandate активирован до ${formatMoment(result.expires_at)}.`
        : "Mandate отозван.",
    );
  } catch (error) {
    elements.controlPlaneMessage.classList.add("is-error");
    setText(elements.controlPlaneMessage, error.message);
  } finally {
    elements.issueMandate.disabled = false;
    elements.revokeMandate.disabled = false;
  }
}

async function grantLatestProposal() {
  elements.grantApproval.disabled = true;
  setText(
    elements.controlPlaneMessage,
    "Фиксируем точный одноразовый Approval…",
  );
  try {
    const approval = await requestJson("/api/control-plane/approvals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "grant_latest",
        run_id: state.currentReportRunId,
      }),
    });
    setText(
      elements.controlPlaneMessage,
      `Точный Approval выдан · ${approval.approval_id}.`,
    );
    await refreshControlPlane();
  } catch (error) {
    elements.controlPlaneMessage.classList.add("is-error");
    setText(elements.controlPlaneMessage, error.message);
  } finally {
    elements.grantApproval.disabled = false;
  }
}

async function revokeLatestApproval() {
  elements.revokeApproval.disabled = true;
  try {
    const approval = await requestJson("/api/control-plane/approvals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "revoke_latest",
        approval_id: state.currentApprovalId,
      }),
    });
    setText(
      elements.controlPlaneMessage,
      `Approval отозван · ${approval.approval_id}.`,
    );
    await refreshControlPlane();
  } catch (error) {
    elements.controlPlaneMessage.classList.add("is-error");
    setText(elements.controlPlaneMessage, error.message);
  } finally {
    elements.revokeApproval.disabled = false;
  }
}

async function applyLatestApproval() {
  elements.applyApproval.disabled = true;
  setText(
    elements.controlPlaneMessage,
    "Повторно проверяем policy и применяем точный diff в sealed fake…",
  );
  try {
    const report = await requestJson("/api/control-plane/approvals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "apply_latest",
        run_id: state.currentReportRunId,
      }),
    });
    renderConfirmedPipeline(report.steps);
    renderReport(report);
    setText(
      elements.controlPlaneMessage,
      `Точный Approval использован · ${report.run_id}.`,
    );
    await refreshControlPlane();
    await refreshEvidence();
  } catch (error) {
    elements.controlPlaneMessage.classList.add("is-error");
    setText(elements.controlPlaneMessage, error.message);
  } finally {
    elements.applyApproval.disabled = false;
  }
}

function renderWorkflowSteps(container, steps) {
  const labels = {
    CAMPAIGN_ADD: "Создание кампании",
    AD_GROUP_ADD: "Создание группы объявлений",
    ADS_ADD: "Добавление объявлений",
    KEYWORD_ADD: "Добавление ключевых фраз",
    MODERATION_SUBMIT: "Отправка на модерацию",
    MODERATION_READBACK: "Проверка модерации",
    CAMPAIGN_LAUNCH: "Запуск кампании",
    FULL_READBACK: "Проверка результата",
    GOAL_CANDIDATE: "Подготовка цели",
    METRIKA_GOAL_ADD: "Создание цели в Метрике",
    SITE_EVENT_PUBLISH: "Публикация события на сайте",
    REACH_GOAL_VERIFY: "Проверка достижения цели",
    DELIVERY_POLLING: "Проверка поступления данных",
    HUMAN_APPROVE: "Смысл цели подтверждён",
    HUMAN_REJECT: "Смысл цели отклонён",
    CLEANUP: "Удаление тестовой цели",
    ACTIVATE_PRIMARY: "Назначение основной цели",
  };
  container.replaceChildren();
  steps.forEach((label, index) => {
    const row = document.createElement("div");
    const number = document.createElement("span");
    const name = document.createElement("span");
    const status = document.createElement("strong");
    row.className = "workflow-step";
    setText(number, String(index + 1).padStart(2, "0"));
    setText(name, labels[label] || label.replaceAll("_", " "));
    setText(status, "Готово");
    row.append(number, name, status);
    container.append(row);
  });
}

async function runCampaignWorkflow() {
  elements.runCampaignWorkflow.disabled = true;
  setText(elements.workflowMessage, "Проверяем создание и запуск кампании…");
  try {
    const result = await requestJson("/api/workflows/campaign", {
      method: "POST",
    });
    renderWorkflowSteps(
      elements.campaignWorkflowSteps,
      result.completed_steps,
    );
    setText(
      elements.workflowMessage,
      result.status === "APPLIED"
        ? "Проверка кампании завершена успешно."
        : "Проверка кампании завершена с ограничениями.",
    );
    await refreshEvidence();
  } catch (error) {
    elements.workflowMessage.classList.add("is-error");
    setText(elements.workflowMessage, error.message);
  } finally {
    elements.runCampaignWorkflow.disabled = false;
  }
}

async function runGoalTechnical() {
  [elements.runGoalWorkflow, elements.approveGoal, elements.rejectGoal].forEach(
    (button) => {
      button.disabled = true;
    },
  );
  setText(
    elements.workflowMessage,
    "Проверяем цель, событие на сайте и поступление данных в Метрику…",
  );
  try {
    const result = await requestJson("/api/workflows/goal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "technical" }),
    });
    renderWorkflowSteps(elements.goalWorkflowSteps, [
      "GOAL_CANDIDATE",
      "METRIKA_GOAL_ADD",
      "SITE_EVENT_PUBLISH",
      "REACH_GOAL_VERIFY",
      "DELIVERY_POLLING",
    ]);
    setText(
      elements.workflowMessage,
      "Техническая проверка завершена. Подтвердите бизнес-смысл цели.",
    );
    elements.approveGoal.disabled = false;
    elements.rejectGoal.disabled = false;
  } catch (error) {
    elements.workflowMessage.classList.add("is-error");
    setText(elements.workflowMessage, error.message);
    elements.runGoalWorkflow.disabled = false;
  }
}

async function decideGoalWorkflow(semanticDecision) {
  elements.approveGoal.disabled = true;
  elements.rejectGoal.disabled = true;
  try {
    const result = await requestJson("/api/workflows/goal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "semantic_decision",
        semantic_decision: semanticDecision,
      }),
    });
    renderWorkflowSteps(elements.goalWorkflowSteps, [
      "GOAL_CANDIDATE",
      "METRIKA_GOAL_ADD",
      "SITE_EVENT_PUBLISH",
      "REACH_GOAL_VERIFY",
      "DELIVERY_POLLING",
      `HUMAN_${semanticDecision}`,
      semanticDecision === "REJECT" ? "CLEANUP" : "ACTIVATE_PRIMARY",
    ]);
    setText(
      elements.workflowMessage,
      result.status === "REJECTED"
        ? "Проверка цели завершена: цель отклонена."
        : "Проверка цели завершена успешно.",
    );
    await refreshEvidence();
  } catch (error) {
    elements.workflowMessage.classList.add("is-error");
    setText(elements.workflowMessage, error.message);
    elements.approveGoal.disabled = false;
    elements.rejectGoal.disabled = false;
    return;
  }
  elements.runGoalWorkflow.disabled = false;
}

async function runImpactEvaluation() {
  elements.runImpact.disabled = true;
  try {
    const result = await requestJson("/api/workflows/impact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fixture: elements.impactFixture.value }),
    });
    const title = elements.impactResult.querySelector("strong");
    const copy = elements.impactResult.querySelector("p");
    const nextDecisionLabels = {
      KEEP_CHANGE: "Сохранить изменение",
      ROLLBACK_CHANGE: "Откатить изменение",
      ADJUST_CHANGE: "Скорректировать изменение",
      ESCALATE_TO_HUMAN: "Передать решение человеку",
    };
    const confidenceLabels = {
      HIGH: "высокая",
      MEDIUM: "средняя",
      LOW: "низкая",
    };
    setText(
      title,
      nextDecisionLabels[result.recommended_next_decision] ||
        "Требуется дополнительная проверка",
    );
    setText(
      copy,
      `Уверенность: ${
        confidenceLabels[result.impact_report.confidence] ||
        result.impact_report.confidence
      }`,
    );
    await refreshEvidence();
  } catch (error) {
    elements.impactResult.querySelector("strong").textContent =
      "Не удалось оценить";
    elements.impactResult.querySelector("p").textContent = error.message;
  } finally {
    elements.runImpact.disabled = false;
  }
}

function renderEvidence(evidence) {
  state.evidence = evidence;
  evidence.capabilities.forEach((item) => {
    const row = elements.capabilityMatrix.querySelector(
      `[data-capability="${item.capability}"]`,
    );
    if (!row) return;
    row.classList.toggle("is-proven", item.status === "PROVEN");
    row.classList.toggle(
      "is-inconclusive",
      item.status === "INCONCLUSIVE",
    );
    setText(row.querySelector("strong"), item.status.replaceAll("_", " "));
    let detail = row.querySelector("small");
    if (!detail) {
      detail = document.createElement("small");
      row.append(detail);
    }
    setText(
      detail,
      `${item.evidence_type} · paths: ${
        item.evidence_paths?.join(", ") || "—"
      } · ${item.limitations?.join(" ") || "Без ограничений"}`,
    );
  });
  evidence.gates.forEach((item) => {
    const number = item.gate.replace("GATE_", "");
    const row = elements.gateStrip.querySelector(`[data-gate="${number}"]`);
    if (!row) return;
    row.classList.toggle("is-ready", item.status === "READY");
    setText(row.querySelector("strong"), item.status.replaceAll("_", " "));
  });
  const htmlReport = evidence.artifacts?.["acceptance-report.html"];
  elements.evidenceReportDownload.hidden = !htmlReport;
  if (htmlReport) {
    elements.evidenceReportDownload.href = htmlReport;
    elements.evidenceReportDownload.download = "";
  }
}

async function refreshEvidence() {
  try {
    renderEvidence(await requestJson("/api/evidence"));
  } catch (error) {
    elements.evidenceMessage.classList.add("is-error");
    setText(elements.evidenceMessage, error.message);
  }
}

async function runFullEvidence() {
  elements.runFullEvidence.disabled = true;
  setText(
    elements.evidenceMessage,
    "Проверяем аналитику, правила, безопасность и журнал решений…",
  );
  try {
    const result = await requestJson("/api/evidence/run", { method: "POST" });
    renderEvidence(result);
    setText(
      elements.evidenceMessage,
      result.overall_status === "PROVEN"
        ? "Полная самопроверка завершена успешно."
        : "Самопроверка завершена. Некоторые возможности требуют дополнительной проверки.",
    );
  } catch (error) {
    elements.evidenceMessage.classList.add("is-error");
    setText(elements.evidenceMessage, error.message);
  } finally {
    elements.runFullEvidence.disabled = false;
  }
}

elements.modeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (state.running) return;
    state.mode = button.dataset.mode;
    updateMode();
  });
});

elements.runButton.addEventListener("click", run);
elements.reviseProposal.addEventListener("click", reviseCurrentProposal);
elements.acceptProposal.addEventListener("click", acceptCurrentProposal);
elements.navigationLinks.forEach((link) => {
  link.addEventListener("click", (event) => {
    const url = new URL(link.href, window.location.origin);
    if (url.origin !== window.location.origin) return;
    event.preventDefault();
    showPage(pageFromPath(url.pathname), true);
  });
});
window.addEventListener("popstate", () => {
  showPage(pageFromPath(window.location.pathname));
});
Object.values(elements.scenarioInputs).forEach((input) => {
  input.addEventListener("input", renderDerivedPreview);
});
Object.values(elements.recommendationInputs).forEach((input) => {
  input.addEventListener("input", renderRecommendationMatrix);
});
elements.decisionRuleSelect.addEventListener("change", () => {
  try {
    window.localStorage.setItem(
      "mox-adv-selected-recommendation",
      elements.decisionRuleSelect.value,
    );
  } catch {
    // Persisting the selected editor is optional.
  }
  renderRecommendationMatrix();
});
Object.entries(elements.decisionSafetyInputs).forEach(([name, input]) => {
  input.addEventListener("input", () => {
    safetyRuleSourceInputs()[name].value = input.value;
    renderRecommendationMatrix();
  });
});
Object.values(safetyRuleSourceInputs()).forEach((input) => {
  input.addEventListener("input", renderRecommendationMatrix);
});
elements.saveAutomation.addEventListener("click", () => {
  saveAutomation(Boolean(state.automation?.enabled));
});
elements.saveRecommendationRules.addEventListener("click", () => {
  saveAutomation(Boolean(state.automation?.enabled), "recommendation");
});
elements.toggleAutomation.addEventListener("click", () => {
  saveAutomation(!state.automation?.enabled);
});
elements.operatingModes.forEach((button) => {
  button.addEventListener("click", () => {
    selectOperatingMode(button.dataset.operatingMode);
  });
});
elements.engageKillSwitch.addEventListener("click", () => {
  updateKillSwitch("engage");
});
elements.releaseKillSwitch.addEventListener("click", () => {
  updateKillSwitch("release");
});
elements.issueMandate.addEventListener("click", () => {
  updateMandate("issue");
});
elements.revokeMandate.addEventListener("click", () => {
  updateMandate("revoke");
});
elements.grantApproval.addEventListener("click", () => {
  grantLatestProposal();
});
elements.revokeApproval.addEventListener("click", () => {
  revokeLatestApproval();
});
elements.applyApproval.addEventListener("click", () => {
  applyLatestApproval();
});
elements.runCampaignWorkflow.addEventListener("click", runCampaignWorkflow);
elements.runGoalWorkflow.addEventListener("click", runGoalTechnical);
elements.approveGoal.addEventListener("click", () => {
  decideGoalWorkflow("APPROVE");
});
elements.rejectGoal.addEventListener("click", () => {
  decideGoalWorkflow("REJECT");
});
elements.runImpact.addEventListener("click", runImpactEvaluation);
elements.refreshEvidence.addEventListener("click", refreshEvidence);
elements.runFullEvidence.addEventListener("click", runFullEvidence);

fetch("/api/status")
  .then((response) => response.json())
  .then((payload) => {
    state.status = payload;
    state.statusError = false;
    if (payload.test_automation) {
      applyAutomationSettings(payload.test_automation);
    }
    updateMode();
  })
  .catch(() => {
    state.status = null;
    state.statusError = true;
    updateMode();
  });

organizePages();
populateDecisionRuleSelect();
restoreDecisionRuleSelection();
showPage(pageFromPath(window.location.pathname));
updateMode();
renderDerivedPreview();
renderRecommendationMatrix();
refreshTestState(false);
refreshControlPlane();
refreshEvidence();
window.setInterval(() => refreshTestState(true), 1000);
