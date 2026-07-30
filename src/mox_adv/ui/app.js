const state = {
  mode: "production",
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
  recommendationMatrixBody: document.querySelector(
    "#recommendation-matrix-body",
  ),
  saveRecommendationRules: document.querySelector(
    "#save-recommendation-rules",
  ),
  recommendationMessage: document.querySelector("#recommendation-message"),
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

const operatingModeCopy = {
  OBSERVE:
    "Только сбор связанных данных и объяснение. Proposal и executor не запускаются.",
  RECOMMEND:
    "Proposal создаётся без применения. Approval и executor не запускаются.",
  APPROVAL_REQUIRED:
    "Изменение возможно только после подтверждения точного proposal и повторного policy-check.",
  BOUNDED_AUTONOMY:
    "Scheduler выполняет не более одного обратимого действия внутри активного Mandate.",
};

const progressCopy = {
  direct: "Читаем данные Яндекс.Директа",
  metrika: "Читаем данные Яндекс.Метрики",
  analytics: "Рассчитываем связанные показатели",
  recommend: "Формируем решение",
  apply: "Проверяем границу исполнения",
};

function setText(element, value) {
  element.textContent = String(value);
}

function updateMode() {
  const isTest = state.mode === "test";
  elements.modeButtons.forEach((button) => {
    const active = button.dataset.mode === state.mode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  setText(elements.modeName, isTest ? "Тестовый контур" : "Основной контур");
  setText(
    elements.modeDescription,
    isTest
      ? "Связанные fixtures Директа и Метрики. Изменение применяется только к fake-объекту."
      : "Read-only анализ реальных данных Яндекс.Директа и Метрики. Рекомендация формируется без approval и применения.",
  );
  elements.modeIndicator.style.background = isTest ? "var(--green)" : "var(--amber)";
  elements.modeIndicator.style.boxShadow = isTest
    ? "0 0 0 4px var(--green-soft)"
    : "0 0 0 4px var(--amber-soft)";
  elements.sourceList.replaceChildren();
  const sources = isTest
    ? [
        ["Директ", "Fixture"],
        ["Метрика", "Fixture"],
        ["Изменения", "Sealed fake"],
      ]
    : [
        ["Директ", "Production API · read-only"],
        ["Метрика", "Production API · read-only"],
        ["Изменения", "Запрещены"],
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
    isTest ? "Запустить тестовый цикл" : "Запустить read-only анализ",
  );
  setText(
    elements.controlNote,
    isTest
      ? "Реальные credentials не загружаются. Внешние write-запросы запрещены."
      : "Executor и approval отключены. Любые внешние write-запросы запрещены.",
  );
  elements.report.hidden = true;
  elements.blockedPanel.hidden = true;
  elements.emptyState.hidden = false;
  elements.testLab.hidden = !isTest;
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

function renderRecommendationMatrix() {
  const rules = readRecommendationRules();
  const enoughSample =
    `клики ≥ ${rules.minimum_clicks} и конверсии ≥ ` +
    `${rules.minimum_conversions}`;
  const rows = [
    [
      "01",
      `0 конверсий и расход ≥ ${rules.no_conversion_spend_rub} ₽`,
      "SUSPEND_CAMPAIGN",
      "Кампания приостанавливается в sealed fake",
    ],
    [
      "02",
      `клики < ${rules.minimum_clicks} или конверсии < ` +
        `${rules.minimum_conversions}`,
      "NO_CHANGE",
      "Цикл запрашивает больше данных",
    ],
    [
      "03",
      `CTR < ${rules.low_ctr_percent}% и показы ≥ ` +
        `${rules.low_ctr_minimum_impressions}; ${enoughSample}`,
      "SET_AD_VARIANT",
      "Активируется другой тестовый вариант объявления",
    ],
    [
      "04",
      `${enoughSample}; CPA ≤ ${rules.target_cpa_rub} ₽; ` +
        `бюджет ≥ ${rules.budget_pressure_percent}%`,
      "INCREASE_WEEKLY_BUDGET",
      "Недельный бюджет увеличивается на 10%",
    ],
    [
      "05",
      `${enoughSample}; CPA > ${rules.target_cpa_rub} ₽; ` +
        `бюджет ≥ ${rules.budget_pressure_percent}%`,
      "DECREASE_WEEKLY_BUDGET",
      "Недельный бюджет уменьшается на 10%",
    ],
    [
      "06",
      `${enoughSample}; CPA > ${rules.target_cpa_rub} ₽; ` +
        `бюджет < ${rules.budget_pressure_percent}%`,
      "DECREASE_SEARCH_BID",
      "Поисковая ставка уменьшается на 10%",
    ],
    [
      "07",
      `${enoughSample}; CPA ≤ ${rules.target_cpa_rub} ₽; ` +
        `бюджет < ${rules.budget_pressure_percent}%; клики ≤ ` +
        `${rules.bid_increase_maximum_clicks}`,
      "INCREASE_SEARCH_BID",
      "Поисковая ставка увеличивается на 10%",
    ],
    [
      "08",
      `кампания SUSPENDED; ${enoughSample}; CPA ≤ ${rules.target_cpa_rub} ₽`,
      "RESUME_CAMPAIGN",
      "Кампания возобновляется только через точный Approval",
    ],
    [
      "09",
      "Источники несовместимы, freshness нарушен или найден внешний writer",
      "REQUEST_HUMAN_HELP",
      "Write блокируется, решение передаётся оператору",
    ],
    [
      "10",
      "Ни одно из условий выше не выполнено",
      "NO_CHANGE",
      "Настройки сохраняются без write-вызова",
    ],
  ];
  elements.recommendationMatrixBody.replaceChildren();
  rows.forEach(([priority, condition, action, outcome]) => {
    const row = document.createElement("tr");
    row.dataset.action = action;
    [priority, condition, actionLabels[action] || action, outcome].forEach(
      (value) => {
        const cell = document.createElement("td");
        setText(cell, value);
        row.append(cell);
      },
    );
    elements.recommendationMatrixBody.append(row);
  });
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
}

function automationPayload(enabled) {
  return {
    enabled,
    mode: "test",
    operating_mode: state.operatingMode,
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
      setText(message, "Логика рекомендаций сохранена.");
    } else {
      setText(
        message,
        payload.enabled
          ? "Настройки сохранены. Первый цикл поставлен в очередь."
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
    return;
  }
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
    setText(reason, entry.reason);

    const result = document.createElement("div");
    const status = document.createElement("strong");
    const link = document.createElement("a");
    result.className = "history-status";
    setText(status, entry.execution_status);
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
  setText(
    elements.workspaceTitle,
    readOnly && report.recommendation.status === "NEEDS_HUMAN"
      ? "Read-only анализ завершён · нужна проверка"
      : readOnly
        ? "Read-only анализ завершён"
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
    report.decision?.reason || report.recommendation.explanation_ru,
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
  elements.recommendationMatrixBody
    .querySelectorAll("tr")
    .forEach((row) => {
      row.classList.toggle(
        "is-current",
        row.dataset.action ===
          (report.recommendation.primary_action ||
            report.recommendation.action),
      );
    });
  if (readOnly) {
    setText(elements.executionLabel, "Граница исполнения");
    setText(
      elements.executionLine,
      "Рекомендация сформирована · не применено",
    );
    setText(
      elements.safetyCopy,
      "Read-only · executor отключён · write-запросы запрещены",
    );
  } else if (
    report.execution.status === "NOT_STARTED" &&
    report.execution.reason_code === "READ_ONLY_MODE"
  ) {
    setText(elements.executionLabel, "Граница исполнения");
    setText(
      elements.executionLine,
      "Рекомендация сформирована · не применено",
    );
    setText(
      elements.safetyCopy,
      "Режим RECOMMEND · executor отключён · write-запросы запрещены",
    );
  } else if (report.execution.status === "PENDING_APPROVAL") {
    setText(elements.executionLabel, "Ожидает полномочия");
    setText(
      elements.executionLine,
      "Ожидает точного Approval · executor ещё не запускался",
    );
    setText(
      elements.safetyCopy,
      "Proposal сохранён · внешняя запись отсутствует",
    );
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
    setText(elements.executionLabel, "Применение и readback");
    setText(
      elements.executionLine,
      `${executionValue(report.execution.before_micros)} → ` +
        `${executionValue(report.execution.after_micros)} · ` +
        `readback ${executionValue(report.execution.readback_micros)}`,
    );
    setText(
      elements.safetyCopy,
      report.safety.external_write_sent
        ? "Внешняя запись выполнена"
        : "Внешняя запись отсутствует · sealed fake",
    );
  } else if (report.execution.status === "NO_CHANGE") {
    setText(elements.executionLabel, "Результат решения");
    setText(
      elements.executionLine,
      "Изменение не требуется · write-вызов не выполнялся",
    );
    setText(
      elements.safetyCopy,
      "Тестовый policy завершил цикл без изменения",
    );
  } else {
    setText(elements.executionLabel, "Результат policy");
    setText(
      elements.executionLine,
      `Применение остановлено · ${report.execution.reason_code}`,
    );
    setText(
      elements.safetyCopy,
      "Внешняя запись отсутствует · policy fail-closed",
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
      : "Выполняется read-only анализ",
  );
  setStatus("В работе", "is-running");
  try {
    const requestPayload = {
      mode: state.mode,
      operating_mode: state.operatingMode,
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

function setFactValues(container, values) {
  const targets = Array.from(container.querySelectorAll("dd"));
  values.forEach((value, index) => {
    if (targets[index]) setText(targets[index], value);
  });
}

function renderControlPlane(control) {
  state.controlPlane = control;
  state.operatingMode = control.operating_mode.selected;
  elements.operatingModes.forEach((button) => {
    const active = button.dataset.operatingMode === state.operatingMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  setText(
    elements.operatingModeNote,
    operatingModeCopy[state.operatingMode],
  );

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
  container.replaceChildren();
  steps.forEach((label, index) => {
    const row = document.createElement("div");
    const number = document.createElement("span");
    const name = document.createElement("span");
    const status = document.createElement("strong");
    row.className = "workflow-step";
    setText(number, String(index + 1).padStart(2, "0"));
    setText(name, label.replaceAll("_", " "));
    setText(status, "PASSED");
    row.append(number, name, status);
    container.append(row);
  });
}

async function runCampaignWorkflow() {
  elements.runCampaignWorkflow.disabled = true;
  setText(elements.workflowMessage, "Выполняется локальная campaign saga…");
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
      `Campaign lifecycle завершён: ${result.status}`,
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
    "Проверяется цель, site event и доставка reachGoal…",
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
      "Техническая проверка VERIFIED. Требуется отдельное решение о бизнес-смысле.",
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
      `Goal lifecycle завершён: ${result.status}`,
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
    setText(title, result.recommended_next_decision.replaceAll("_", " "));
    setText(
      copy,
      `Confidence: ${result.impact_report.confidence} · ${result.status}`,
    );
    await refreshEvidence();
  } catch (error) {
    elements.impactResult.querySelector("strong").textContent = "BLOCKED";
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
    "Выполняются аналитика, policy, lifecycle, safety и audit проверки…",
  );
  try {
    const result = await requestJson("/api/evidence/run", { method: "POST" });
    renderEvidence(result);
    setText(
      elements.evidenceMessage,
      `Полный тестовый контур завершён · ${result.overall_status} · ${result.run_id}.`,
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
Object.values(elements.scenarioInputs).forEach((input) => {
  input.addEventListener("input", renderDerivedPreview);
});
Object.values(elements.recommendationInputs).forEach((input) => {
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

updateMode();
renderDerivedPreview();
renderRecommendationMatrix();
refreshTestState(false);
refreshControlPlane();
refreshEvidence();
window.setInterval(() => refreshTestState(true), 1000);
