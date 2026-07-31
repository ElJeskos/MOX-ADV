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
  campaignSource: "test",
  campaignDraft: null,
  campaignCatalog: [],
  directCampaignCatalog: [],
  selectedDirectCampaignId: null,
  directCampaignFetchedAt: null,
  directCampaignAccount: null,
  directCampaignBusy: false,
  campaignDirty: false,
  campaignBusy: false,
  campaignLaunch: null,
  campaignGoalLifecycle: null,
  campaignGoalBusy: false,
  campaignPrimaryEvent: "",
  campaignLandingPageValue: "",
  campaignGoals: [],
  campaignAdGroups: [],
  selectedAdGroupId: null,
  selectedAdId: null,
  historyCompact: true,
  historyPage: 1,
  historyPages: 1,
  historyEntries: [],
  historyTotal: 0,
  historyPageCache: new Map(),
  historyCacheSignature: "",
  selectedOutcomeRunId: null,
};

const campaignLifecycleSteps = Object.freeze([
  "CAMPAIGN_ADD",
  "AD_GROUP_ADD",
  "ADS_ADD",
  "KEYWORD_ADD",
  "MODERATION_SUBMIT",
  "MODERATION_READBACK",
  "CAMPAIGN_LAUNCH",
  "FULL_READBACK",
]);

const elements = {
  pages: Array.from(document.querySelectorAll("[data-page]")),
  navigationLinks: Array.from(document.querySelectorAll("[data-nav]")),
  pageLinks: Array.from(document.querySelectorAll("[data-page-link]")),
  publicDemoBanner: document.querySelector("#public-demo-banner"),
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
  campaignGoalSummary: document.querySelector("#campaign-goal-summary"),
  reportCampaignGoal: document.querySelector("#report-campaign-goal"),
  reportGoalUsage: document.querySelector("#report-goal-usage"),
  reportGoalTarget: document.querySelector("#report-goal-target"),
  reportGoalActual: document.querySelector("#report-goal-actual"),
  reportGoalAchievement: document.querySelector(
    "#report-goal-achievement",
  ),
  reportGoalStatus: document.querySelector("#report-goal-status"),
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
  historyDecisionsTab: document.querySelector("#history-decisions-tab"),
  historyOutcomesTab: document.querySelector("#history-outcomes-tab"),
  historyDecisionsPanel: document.querySelector("#history-decisions-panel"),
  historyOutcomesPanel: document.querySelector("#history-outcomes-panel"),
  historyExpand: document.querySelector("#history-expand"),
  historyPagination: document.querySelector("#history-pagination"),
  historyPrevious: document.querySelector("#history-previous"),
  historyNext: document.querySelector("#history-next"),
  historyPageStatus: document.querySelector("#history-page-status"),
  historyTotal: document.querySelector("#history-total"),
  decisionOutcome: document.querySelector("#decision-outcome"),
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
  campaignDraftStatus: document.querySelector("#campaign-draft-status"),
  campaignDraftMeta: document.querySelector("#campaign-draft-meta"),
  campaignMessage: document.querySelector("#campaign-message"),
  campaignConsoleDescription: document.querySelector(
    "#campaign-console-description",
  ),
  campaignSourceButtons: Array.from(
    document.querySelectorAll("[data-campaign-source]"),
  ),
  campaignSourceNote: document.querySelector("#campaign-source-note"),
  campaignCount: document.querySelector("#campaign-count"),
  campaignCountLabel: document.querySelector("#campaign-count-label"),
  campaignFilterCount: document.querySelector("#campaign-filter-count"),
  campaignSearch: document.querySelector("#campaign-search"),
  campaignList: document.querySelector("#campaign-list"),
  campaignEmpty: document.querySelector("#campaign-empty"),
  campaignRegistryEyebrow: document.querySelector(
    "#campaign-registry-eyebrow",
  ),
  campaignRegistryTitle: document.querySelector("#campaign-registry-title"),
  campaignBudgetHeading: document.querySelector(
    "#campaign-budget-heading",
  ),
  campaignMetricHeading: document.querySelector(
    "#campaign-metric-heading",
  ),
  campaignEditorTitle: document.querySelector("#campaign-editor-title"),
  campaignStatusBadge: document.querySelector("#campaign-status-badge"),
  newCampaign: document.querySelector("#new-campaign"),
  refreshDirectCampaigns: document.querySelector(
    "#refresh-direct-campaigns",
  ),
  saveCampaign: document.querySelector("#save-campaign"),
  launchCampaign: document.querySelector("#launch-campaign"),
  deleteCampaign: document.querySelector("#delete-campaign"),
  campaignInspectorActions: document.querySelector(
    "#campaign-inspector-actions",
  ),
  campaignLaunchStatus: document.querySelector("#campaign-launch-status"),
  campaignLaunchTitle: document.querySelector("#campaign-launch-title"),
  campaignLaunchCopy: document.querySelector("#campaign-launch-copy"),
  campaignLaunchSteps: document.querySelector("#campaign-launch-steps"),
  campaignLaunchSafety: document.querySelector("#campaign-launch-safety"),
  campaignLaunchTime: document.querySelector("#campaign-launch-time"),
  campaignLaunchRunId: document.querySelector("#campaign-launch-run-id"),
  campaignGoalLifecycle: document.querySelector(
    "#campaign-goal-lifecycle",
  ),
  campaignGoalLifecycleTitle: document.querySelector(
    "#campaign-goal-lifecycle-title",
  ),
  campaignGoalLifecycleCopy: document.querySelector(
    "#campaign-goal-lifecycle-copy",
  ),
  campaignGoalBadge: document.querySelector("#campaign-goal-badge"),
  campaignGoalCandidate: document.querySelector(
    "#campaign-goal-candidate",
  ),
  campaignGoalEvent: document.querySelector("#campaign-goal-event"),
  campaignGoalDelivery: document.querySelector(
    "#campaign-goal-delivery",
  ),
  campaignGoalOptimization: document.querySelector(
    "#campaign-goal-optimization",
  ),
  campaignGoalSafety: document.querySelector("#campaign-goal-safety"),
  campaignGoalRunId: document.querySelector("#campaign-goal-run-id"),
  campaignGoalEvidenceDetails: document.querySelector(
    "#campaign-goal-evidence-details",
  ),
  campaignGoalEvidenceId: document.querySelector(
    "#campaign-goal-evidence-id",
  ),
  campaignGoalEvidenceType: document.querySelector(
    "#campaign-goal-evidence-type",
  ),
  campaignGoalEvidenceEvent: document.querySelector(
    "#campaign-goal-evidence-event",
  ),
  campaignGoalEvidenceSelector: document.querySelector(
    "#campaign-goal-evidence-selector",
  ),
  campaignGoalEvidenceScenario: document.querySelector(
    "#campaign-goal-evidence-scenario",
  ),
  campaignGoalEvidenceCheckedAt: document.querySelector(
    "#campaign-goal-evidence-checked-at",
  ),
  campaignGoalEvidenceAuthor: document.querySelector(
    "#campaign-goal-evidence-author",
  ),
  campaignGoalEvidenceVersion: document.querySelector(
    "#campaign-goal-evidence-version",
  ),
  verifyCampaignGoal: document.querySelector("#verify-campaign-goal"),
  approveCampaignGoal: document.querySelector("#approve-campaign-goal"),
  rejectCampaignGoal: document.querySelector("#reject-campaign-goal"),
  campaignGoalMessage: document.querySelector("#campaign-goal-message"),
  campaignDeleteDialog: document.querySelector("#campaign-delete-dialog"),
  campaignDeleteName: document.querySelector("#campaign-delete-name"),
  cancelCampaignDelete: document.querySelector("#cancel-campaign-delete"),
  confirmCampaignDelete: document.querySelector(
    "#confirm-campaign-delete",
  ),
  campaignEditor: document.querySelector("#campaign-editor"),
  directCampaignInspector: document.querySelector(
    "#direct-campaign-inspector",
  ),
  directCampaignFacts: {
    campaign_id: document.querySelector("#direct-campaign-id"),
    type: document.querySelector("#direct-campaign-type"),
    state: document.querySelector("#direct-campaign-state"),
    status: document.querySelector("#direct-campaign-status"),
    status_payment: document.querySelector("#direct-campaign-payment"),
    daily_budget_micros: document.querySelector("#direct-campaign-budget"),
    start_date: document.querySelector("#direct-campaign-start"),
    end_date: document.querySelector("#direct-campaign-end"),
    timezone: document.querySelector("#direct-campaign-timezone"),
    client_info: document.querySelector("#direct-campaign-client"),
  },
  campaignInputs: {
    name: document.querySelector("#campaign-name"),
    weekly_budget_rub: document.querySelector("#campaign-weekly-budget"),
    keyword: document.querySelector("#campaign-keyword"),
    landing_page: document.querySelector("#campaign-landing-page"),
    business_goal: document.querySelector("#campaign-business-goal"),
    target_cpa_rub: document.querySelector("#campaign-target-cpa"),
    goal_strategy: document.querySelector("#campaign-goal-strategy"),
    payment_model: document.querySelector("#campaign-payment-model"),
    attribution_model: document.querySelector("#campaign-attribution-model"),
    counter_id: document.querySelector("#campaign-counter-id"),
  },
  campaignGoals: document.querySelector("#campaign-goals"),
  addCampaignGoal: document.querySelector("#add-campaign-goal"),
  campaignAdGroupSelect: document.querySelector(
    "#campaign-ad-group-select",
  ),
  addAdGroup: document.querySelector("#add-ad-group"),
  deleteAdGroup: document.querySelector("#delete-ad-group"),
  campaignPilotGroup: document.querySelector("#campaign-pilot-group"),
  campaignAdGroupName: document.querySelector("#campaign-ad-group-name"),
  campaignAdGroupKeywords: document.querySelector(
    "#campaign-ad-group-keywords",
  ),
  campaignAdGroupNegativeKeywords: document.querySelector(
    "#campaign-ad-group-negative-keywords",
  ),
  campaignAutotargeting: Array.from(
    document.querySelectorAll("[data-autotargeting]"),
  ),
  addCampaignAd: document.querySelector("#add-campaign-ad"),
  campaignAdTabs: document.querySelector("#campaign-ad-tabs"),
  campaignAdEditor: document.querySelector("#campaign-ad-editor"),
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

const executionReasonLabels = {
  MONETARY_LIMIT_EXCEEDED: "Лимит денежных изменений превышен",
  DAILY_CHANGE_LIMIT_EXCEEDED: "Суточный лимит изменений превышен",
  ACTION_QUOTA_REACHED: "Лимит действий исчерпан",
  COOLDOWN_ACTIVE: "Период ожидания после прошлого изменения ещё не завершён",
  KILL_SWITCH_UNAVAILABLE: "Аварийная остановка недоступна",
  SNAPSHOT_NOT_COMPARABLE: "Данные нельзя безопасно сопоставить",
  DIRECT_SNAPSHOT_STALE: "Данные Директа устарели",
  METRIKA_SNAPSHOT_STALE: "Данные Метрики устарели",
  WATERMARK_SKEW_EXCEEDED: "Источники обновлены в несовместимое время",
  FINGERPRINT_MISMATCH: "Кампания изменилась после подготовки предложения",
};

function executionReason(execution) {
  const reasonCode = String(execution?.reason_code || "");
  return (
    executionReasonLabels[reasonCode] ||
    reasonCode ||
    "Безопасная проверка остановила применение"
  );
}

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
  campaign: "Рекламная кампания",
  control: "Контроль",
};

function pageFromPath(pathname) {
  const candidate = pathname.replace(/^\/+|\/+$/g, "") || "overview";
  if (candidate === "workflows") return "campaign";
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

function renderCampaignGoal(goal) {
  const statusLabels = {
    ACHIEVED: "Достигнута",
    NOT_ACHIEVED: "Не достигнута",
    INSUFFICIENT_DATA: "Недостаточно данных",
    NEEDS_REVIEW: "Нужна проверка",
    NOT_EVALUABLE: "Нельзя оценить",
  };
  setText(elements.reportCampaignGoal, goal.business_goal.meaning);
  setText(
    elements.reportGoalUsage,
    goal.used_in_decision
      ? "Учитывается при выборе решения"
      : "Не используется в решении",
  );
  setText(
    elements.reportGoalTarget,
    `≤ ${formatRuleNumber(goal.target_kpi.target_maximum)} ₽`,
  );
  setText(
    elements.reportGoalActual,
    goal.target_kpi.actual === "NOT_APPLICABLE"
      ? "Недоступно"
      : `${formatRuleNumber(goal.target_kpi.actual)} ₽`,
  );
  setText(
    elements.reportGoalStatus,
    statusLabels[goal.achievement_status] || goal.achievement_status,
  );
  elements.reportGoalAchievement.classList.toggle(
    "is-achieved",
    goal.achievement_status === "ACHIEVED",
  );
  elements.reportGoalAchievement.classList.toggle(
    "is-not-achieved",
    goal.achievement_status === "NOT_ACHIEVED",
  );
  elements.reportGoalAchievement.classList.toggle(
    "is-pending",
    !["ACHIEVED", "NOT_ACHIEVED"].includes(goal.achievement_status),
  );
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

function updateHistoryOverview(items) {
  if (!items.length) {
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
}

function showHistoryTab(tab) {
  const outcomes = tab === "outcomes";
  elements.historyDecisionsTab.setAttribute(
    "aria-selected",
    String(!outcomes),
  );
  elements.historyOutcomesTab.setAttribute(
    "aria-selected",
    String(outcomes),
  );
  elements.historyDecisionsTab.tabIndex = outcomes ? -1 : 0;
  elements.historyOutcomesTab.tabIndex = outcomes ? 0 : -1;
  elements.historyDecisionsPanel.hidden = outcomes;
  elements.historyOutcomesPanel.hidden = !outcomes;
}

function impactSnapshotMetrics(snapshot) {
  const metrics = snapshot?.metrics || {};
  const conversions = Number(metrics.goal_visits || 0);
  const spendRub = Number(metrics.cost_micros || 0) / 1_000_000;
  return {
    conversions,
    spendRub,
    cpa: conversions > 0 ? spendRub / conversions : null,
  };
}

function outcomeFact(label, value, detail = "") {
  const row = document.createElement("div");
  const name = document.createElement("span");
  const result = document.createElement("strong");
  setText(name, label);
  setText(result, value);
  row.append(name, result);
  if (detail) {
    const note = document.createElement("small");
    setText(note, detail);
    row.append(note);
  }
  return row;
}

function periodLabel(snapshot) {
  if (!snapshot?.period_start || !snapshot?.period_end) return "Период не указан";
  return `${snapshot.period_start} — ${snapshot.period_end}`;
}

function executionChange(report) {
  const execution = report?.execution || {};
  if (
    typeof execution.before_micros === "number" &&
    typeof execution.after_micros === "number"
  ) {
    return (
      `${formatRuleNumber(execution.before_micros / 1_000_000)} ₽ → ` +
      `${formatRuleNumber(execution.after_micros / 1_000_000)} ₽`
    );
  }
  if (execution.status === "NO_CHANGE") return "Настройки сохранены без изменений";
  return "Решение зафиксировано в журнале";
}

function renderDecisionOutcome(payload, entry, report) {
  const workflow = payload?.outcome || null;
  const executionLabels = {
    APPLIED: "Применено",
    NO_CHANGE: "Без изменений",
    PENDING_APPROVAL: "Ждёт решения",
    BLOCKED: "Остановлено",
    NOT_STARTED: "Не применялось",
  };
  const heading = document.createElement("div");
  const eyebrow = document.createElement("p");
  const title = document.createElement("h3");
  const accepted = document.createElement("section");
  const acceptedLabel = document.createElement("p");
  const acceptedTitle = document.createElement("h4");
  const acceptedReason = document.createElement("p");
  const acceptedFacts = document.createElement("div");

  heading.className = "decision-outcome-head";
  eyebrow.className = "eyebrow";
  accepted.className = "accepted-decision";
  acceptedLabel.className = "accepted-decision-label";
  acceptedReason.className = "accepted-decision-reason";
  acceptedFacts.className = "accepted-decision-facts";
  setText(
    eyebrow,
    `Решение от ${formatMoment(entry.created_at)}`,
  );
  setText(title, actionLabels[entry.action] || entry.action);
  heading.append(eyebrow, title);
  setText(acceptedLabel, "Принятое решение");
  setText(acceptedTitle, actionLabels[entry.action] || entry.action);
  setText(acceptedReason, operatorReason(entry.reason));
  acceptedFacts.append(
    outcomeFact(
      "Статус",
      executionLabels[entry.execution_status] || entry.execution_status,
    ),
    outcomeFact("Фактическое изменение", executionChange(report)),
  );
  accepted.append(
    acceptedLabel,
    acceptedTitle,
    acceptedReason,
    acceptedFacts,
  );

  if (!workflow) {
    const pending = document.createElement("section");
    const pendingLabel = document.createElement("p");
    const pendingTitle = document.createElement("h4");
    const pendingCopy = document.createElement("p");
    pending.className = "outcome-pending";
    pendingLabel.className = "eyebrow";
    setText(pendingLabel, "Наблюдение после изменения");
    setText(pendingTitle, "Исход ещё формируется");
    setText(
      pendingCopy,
      "Данные за сопоставимый период «после» ещё не собраны. " +
        "Когда наблюдение завершится, здесь появятся CPA, конверсии и следующий шаг.",
    );
    pending.append(pendingLabel, pendingTitle, pendingCopy);
    elements.decisionOutcome.replaceChildren(heading, accepted, pending);
    return;
  }

  const before = impactSnapshotMetrics(workflow.exact_diff?.before);
  const after = impactSnapshotMetrics(workflow.exact_diff?.after);
  const decisionLabels = {
    KEEP_CHANGE: "Сохранить изменение",
    ROLLBACK_CHANGE: "Откатить изменение",
    ADJUST_CHANGE: "Скорректировать изменение",
    ESCALATE_TO_HUMAN: "Передать решение человеку",
  };
  const confidenceLabels = {
    READY: "Данных достаточно для решения",
    INSUFFICIENT_DATA: "Недостаточно данных",
    STALE_DATA: "Данные устарели",
  };
  const resultHeading = document.createElement("div");
  const resultLabel = document.createElement("p");
  const resultTitle = document.createElement("h4");
  const grid = document.createElement("div");
  const baseline = document.createElement("section");
  const observed = document.createElement("section");
  const baselineTitle = document.createElement("h5");
  const observedTitle = document.createElement("h5");
  const recommendation = document.createElement("section");
  const recommendationLabel = document.createElement("p");
  const recommendationTitle = document.createElement("h4");
  const recommendationCopy = document.createElement("p");

  resultHeading.className = "outcome-result-heading";
  resultLabel.className = "eyebrow";
  grid.className = "decision-outcome-grid";
  recommendation.className = "decision-outcome-recommendation";
  recommendationLabel.className = "eyebrow";
  setText(resultLabel, "Измеренный результат");
  setText(resultTitle, "Сравнение до и после");
  resultHeading.append(resultLabel, resultTitle);
  setText(baselineTitle, "До изменения");
  baseline.append(
    baselineTitle,
    outcomeFact(
      "CPA",
      before.cpa === null
        ? "Недоступно"
        : `${formatRuleNumber(before.cpa)} ₽`,
    ),
    outcomeFact("Конверсии", formatRuleNumber(before.conversions)),
    outcomeFact("Расход", `${formatRuleNumber(before.spendRub)} ₽`),
    outcomeFact("Период", periodLabel(workflow.exact_diff?.before)),
  );
  setText(observedTitle, "После изменения");
  observed.append(
    observedTitle,
    outcomeFact(
      "CPA",
      after.cpa === null
        ? "Недоступно"
        : `${formatRuleNumber(after.cpa)} ₽`,
    ),
    outcomeFact("Конверсии", formatRuleNumber(after.conversions)),
    outcomeFact("Расход", `${formatRuleNumber(after.spendRub)} ₽`),
    outcomeFact("Период", periodLabel(workflow.exact_diff?.after)),
  );
  grid.append(baseline, observed);
  setText(recommendationLabel, "Следующий шаг");
  setText(
    recommendationTitle,
    decisionLabels[workflow.recommended_next_decision] ||
      workflow.recommended_next_decision ||
      "Требуется проверка",
  );
  setText(
    recommendationCopy,
    confidenceLabels[workflow.impact_report?.confidence] ||
      workflow.impact_report?.confidence ||
      "Уверенность не определена",
  );
  recommendation.append(
    recommendationLabel,
    recommendationTitle,
    recommendationCopy,
  );
  elements.decisionOutcome.replaceChildren(
    heading,
    accepted,
    resultHeading,
    grid,
    recommendation,
  );
}

async function loadDecisionOutcome(entry) {
  state.selectedOutcomeRunId = entry.run_id;
  showHistoryTab("outcomes");
  elements.decisionOutcome.replaceChildren();
  const loading = document.createElement("p");
  loading.className = "history-empty";
  setText(loading, "Загружаем связанный исход…");
  elements.decisionOutcome.append(loading);
  try {
    const [report, outcomeResponse] = await Promise.all([
      requestJson(`/api/runs/${encodeURIComponent(entry.run_id)}`),
      fetch(
        `/api/test-history/${encodeURIComponent(entry.run_id)}/outcome`,
      ),
    ]);
    let payload = null;
    if (outcomeResponse.ok) {
      payload = await outcomeResponse.json();
    } else if (outcomeResponse.status !== 404) {
      const errorPayload = await outcomeResponse.json();
      throw new Error(
        errorPayload.message ||
          errorPayload.reason_code ||
          "Не удалось загрузить исход.",
      );
    }
    if (state.selectedOutcomeRunId !== entry.run_id) return;
    renderDecisionOutcome(payload, entry, report);
  } catch (error) {
    loading.classList.add("is-error");
    setText(loading, error.message);
  }
}

function renderHistory(items) {
  state.historyEntries = items;
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
    setText(reason, operatorReason(entry.reason));

    const result = document.createElement("div");
    const status = document.createElement("strong");
    const link = document.createElement("a");
    const outcomeButton = document.createElement("button");
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
    outcomeButton.type = "button";
    outcomeButton.className = "history-outcome-link";
    setText(outcomeButton, "Посмотреть исход");
    outcomeButton.addEventListener("click", () => {
      loadDecisionOutcome(entry);
    });
    result.append(outcomeButton);
    item.append(origin, trigger, reason, result);
    elements.decisionHistory.append(item);
  });
}

function updateHistoryPagination(page) {
  state.historyPage = page.page;
  state.historyPages = page.pages;
  state.historyTotal = page.total;
  setText(elements.historyTotal, page.total);
  setText(
    elements.historyPageStatus,
    `Страница ${page.page} из ${page.pages}`,
  );
  elements.historyPrevious.disabled = page.page <= 1;
  elements.historyNext.disabled = page.page >= page.pages;
}

function renderHistoryPage(result) {
  state.historyCompact = false;
  renderHistory(result.items);
  updateHistoryPagination(result);
  elements.historyExpand.hidden = false;
  setText(elements.historyExpand, "Свернуть до последних 3");
  elements.historyPagination.hidden = result.pages <= 1;
  showHistoryTab("decisions");
}

function primeHistoryPage(page) {
  const cached = state.historyPageCache.get(page);
  if (cached) return Promise.resolve(cached);
  return requestJson(`/api/test-history?page=${page}&page_size=10`).then(
    (result) => {
      state.historyPageCache.set(result.page, result);
      return result;
    },
  );
}

async function loadHistoryPage(page) {
  const cached = state.historyPageCache.get(page);
  if (cached) {
    renderHistoryPage(cached);
    if (page < cached.pages && !state.historyPageCache.has(page + 1)) {
      elements.historyNext.disabled = true;
      primeHistoryPage(page + 1).then(() => {
        if (state.historyPage === page) {
          elements.historyNext.disabled = false;
        }
      });
    }
    return;
  }
  try {
    const result = await primeHistoryPage(page);
    renderHistoryPage(result);
  } catch (error) {
    elements.decisionHistory.replaceChildren();
    const message = document.createElement("p");
    message.className = "history-empty is-error";
    setText(message, error.message);
    elements.decisionHistory.append(message);
  }
}

async function collapseHistory() {
  state.historyCompact = true;
  state.historyPage = 1;
  await refreshTestState(false);
  showHistoryTab("decisions");
}

async function refreshTestState(autoRenderLatest = false) {
  try {
    const [settingsResponse, historyResponse] = await Promise.all([
      fetch("/api/test-automation"),
      fetch("/api/test-history?page=1&page_size=3"),
    ]);
    if (!settingsResponse.ok || !historyResponse.ok) return;
    const settings = await settingsResponse.json();
    const history = await historyResponse.json();
    state.automation = settings;
    renderAutomationState(settings);
    updateHistoryOverview(history.items);
    state.historyTotal = history.total;
    setText(elements.historyTotal, history.total);
    const signature = `${history.total}:${history.items[0]?.run_id || ""}`;
    if (signature !== state.historyCacheSignature) {
      state.historyPageCache.clear();
      state.historyCacheSignature = signature;
    }
    if (state.historyCompact) {
      renderHistory(history.items);
      setText(elements.historyExpand, "Показать весь журнал");
      elements.historyPagination.hidden = true;
      if (history.total <= 3) {
        elements.historyExpand.hidden = true;
      } else {
        elements.historyExpand.hidden = true;
        primeHistoryPage(1)
          .then(() => {
            if (state.historyCompact) {
              elements.historyExpand.hidden = false;
            }
          })
          .catch(() => {
            elements.historyExpand.hidden = false;
          });
      }
    }
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
  const blocked = report.execution.status === "BLOCKED";
  elements.emptyState.hidden = true;
  elements.blockedPanel.hidden = true;
  elements.report.hidden = false;
  elements.proposalReview.hidden = true;
  elements.proposalMessage.classList.remove("is-error");
  setText(elements.proposalMessage, "");
  setText(
    elements.workspaceTitle,
    blocked
      ? "Предложение заблокировано"
      : report.execution.status === "APPLIED"
        ? "Предложение применено"
      : readOnly && report.recommendation.status === "NEEDS_HUMAN"
        ? "Анализ завершён · нужна проверка"
        : readOnly
          ? "Анализ завершён"
          : "Цикл завершён",
  );
  setStatus(
    blocked
      ? "Заблокировано"
      : readOnly && report.recommendation.status === "NEEDS_HUMAN"
      ? "Нужна проверка"
      : "Успешно",
    blocked ? "is-blocked" : "is-running",
  );
  setText(elements.reportRunId, report.run_id);
  setText(
    elements.reportPeriod,
    `${report.period.start} — ${report.period.end}`,
  );
  elements.campaignGoalSummary.hidden = !report.campaign_goal;
  if (report.campaign_goal) {
    renderCampaignGoal(report.campaign_goal);
  }
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
      `${executionReason(report.execution)}. Реальная кампания не изменена`,
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

function campaignLocalId(prefix) {
  if (window.crypto?.randomUUID) {
    return `${prefix.slice(0, 18)}-${window.crypto.randomUUID().slice(0, 12)}`;
  }
  return `${prefix.slice(0, 18)}-${Date.now().toString(36)}-${Math.random()
    .toString(16)
    .slice(2, 10)}`;
}

function cloneCampaignValue(value) {
  return JSON.parse(JSON.stringify(value));
}

function campaignLines(value) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function primaryCampaignGoal() {
  return (
    state.campaignGoals.find((goal) => goal.primary) ||
    state.campaignGoals[0] ||
    null
  );
}

function markCampaignDirty() {
  state.campaignDirty = true;
  elements.launchCampaign.disabled = true;
  setText(elements.campaignDraftStatus, "Есть несохранённые изменения");
  setText(
    elements.campaignDraftMeta,
    "Сохраните, чтобы применить в следующем цикле",
  );
  renderCampaignLaunchStatus({
    ...state.campaignLaunch,
    launch_status: "DIRTY",
  });
  renderCampaignGoalLifecycle({
    ...state.campaignGoalLifecycle,
    lifecycle_status: "DIRTY",
  });
}

function campaignLabel(title, control, className = "") {
  const label = document.createElement("label");
  const caption = document.createElement("span");
  if (className) label.className = className;
  setText(caption, title);
  label.append(caption, control);
  return label;
}

function campaignSelect(options, selected) {
  const select = document.createElement("select");
  options.forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    setText(option, label);
    select.append(option);
  });
  select.value = selected;
  return select;
}

function renderCampaignGoals() {
  elements.campaignGoals.replaceChildren();
  state.campaignGoals.forEach((goal, index) => {
    const item = document.createElement("article");
    const head = document.createElement("div");
    const identity = document.createElement("div");
    const primaryLabel = document.createElement("label");
    const primary = document.createElement("input");
    const primaryText = document.createElement("span");
    const title = document.createElement("strong");
    const meta = document.createElement("small");
    const remove = document.createElement("button");
    const fields = document.createElement("div");

    item.className = "campaign-goal-item";
    item.dataset.goalId = goal.id;
    head.className = "campaign-goal-head";
    identity.className = "campaign-goal-identity";
    primaryLabel.className = "campaign-goal-primary";
    primary.type = "radio";
    primary.name = "campaign-primary-goal";
    primary.checked = goal.primary;
    setText(primaryText, "Основная цель");
    primaryLabel.append(primary, primaryText);
    setText(title, goal.name || `Цель ${index + 1}`);
    setText(
      meta,
      `${goal.event || "Событие не задано"} · ${
        goal.value_mode === "DYNAMIC"
          ? "динамическая ценность"
          : `${formatRuleNumber(goal.value_rub || 0)} ₽`
      }`,
    );
    identity.append(title, meta);
    remove.type = "button";
    remove.className = "text-button danger-text";
    setText(remove, "Удалить цель");
    remove.disabled = state.campaignGoals.length <= 1 || goal.primary;
    head.append(primaryLabel, identity, remove);

    const name = document.createElement("input");
    name.type = "text";
    name.maxLength = 128;
    name.value = goal.name;
    name.addEventListener("input", () => {
      goal.name = name.value;
      setText(title, name.value || `Цель ${index + 1}`);
    });

    const event = document.createElement("input");
    event.type = "text";
    event.maxLength = 128;
    event.value = goal.event;
    event.readOnly = goal.primary;
    event.setAttribute("aria-readonly", String(goal.primary));
    event.addEventListener("input", () => {
      goal.event = event.value;
    });

    const selector = document.createElement("input");
    selector.type = "text";
    selector.maxLength = 500;
    selector.value = goal.site_location;
    selector.addEventListener("input", () => {
      goal.site_location = selector.value;
    });

    const type = campaignSelect(
      [
        ["ACTION", "Действие на сайте"],
        ["ECOMMERCE", "Ecommerce"],
        ["COMPOSITE", "Составная"],
        ["OFFLINE", "Офлайн-конверсия"],
      ],
      goal.type,
    );
    type.addEventListener("change", () => {
      goal.type = type.value;
    });

    const source = campaignSelect(
      [
        ["METRIKA", "Яндекс Метрика"],
        ["AUTO", "Автоцель"],
        ["OFFLINE", "Офлайн-конверсии"],
      ],
      goal.source,
    );
    source.addEventListener("change", () => {
      goal.source = source.value;
    });

    const valueMode = campaignSelect(
      [
        ["FIXED", "Задать вручную"],
        ["DYNAMIC", "Из Метрики (динамическая)"],
      ],
      goal.value_mode,
    );
    valueMode.addEventListener("change", () => {
      goal.value_mode = valueMode.value;
      goal.value_rub = valueMode.value === "DYNAMIC"
        ? null
        : Math.max(1, Number(goal.value_rub) || 1);
      renderCampaignGoals();
      markCampaignDirty();
    });

    const value = document.createElement("input");
    value.type = "number";
    value.min = "1";
    value.max = "1000000000";
    value.value = goal.value_rub === null ? "" : String(goal.value_rub);
    value.disabled = goal.value_mode === "DYNAMIC";
    value.addEventListener("input", () => {
      goal.value_rub = Number(value.value);
    });

    fields.className = "campaign-goal-fields";
    fields.append(
      campaignLabel("Название цели", name, "campaign-goal-name"),
      campaignLabel("Событие", event),
      campaignLabel("Селектор на сайте", selector),
      campaignLabel("Тип цели", type),
      campaignLabel("Источник", source),
      campaignLabel("Ценность", valueMode),
      campaignLabel("Ценность, ₽", value),
    );

    primary.addEventListener("change", () => {
      if (!primary.checked) return;
      state.campaignGoals.forEach((candidate) => {
        candidate.primary = candidate.id === goal.id;
      });
      goal.event = state.campaignPrimaryEvent;
      renderCampaignGoals();
      markCampaignDirty();
    });
    remove.addEventListener("click", () => {
      state.campaignGoals = state.campaignGoals.filter(
        (candidate) => candidate.id !== goal.id,
      );
      renderCampaignGoals();
      markCampaignDirty();
    });
    item.append(head, fields);
    elements.campaignGoals.append(item);
  });
  elements.addCampaignGoal.disabled = state.campaignGoals.length >= 30;
}

function addCampaignGoal() {
  if (state.campaignGoals.length >= 30) return;
  state.campaignGoals.push({
    id: campaignLocalId("goal"),
    name: "Новая цель",
    event: "new_goal_event",
    site_location: "#target",
    type: "ACTION",
    source: "METRIKA",
    value_mode: "FIXED",
    value_rub: 100,
    primary: false,
  });
  renderCampaignGoals();
  markCampaignDirty();
}

function selectedCampaignAdGroup() {
  return (
    state.campaignAdGroups.find(
      (group) => group.id === state.selectedAdGroupId,
    ) || state.campaignAdGroups[0] || null
  );
}

function selectedCampaignAd() {
  const group = selectedCampaignAdGroup();
  if (!group) return null;
  return (
    group.ads.find((ad) => ad.id === state.selectedAdId) ||
    group.ads[0] ||
    null
  );
}

function defaultCampaignAd(groupId, index, pilotRole = null) {
  const landing =
    elements.campaignInputs.landing_page.value ||
    state.campaignDraft?.campaign.landing_page ||
    "https://allowlisted.example/lead";
  return {
    id: campaignLocalId(`${groupId}-ad`),
    pilot_role: pilotRole,
    titles: [`Новое объявление ${index}`],
    texts: ["Расскажите пользователю о вашем предложении"],
    href: landing,
    display_url_path: "offer",
    image_references: [
      pilotRole === "B" ? "prepared-media-2" : "prepared-media-1",
    ],
    sitelinks: [],
    callouts: [],
  };
}

function defaultCampaignAdGroup() {
  const id = campaignLocalId("group");
  return {
    id,
    name: `Группа ${state.campaignAdGroups.length + 1}`,
    selected_for_pilot: false,
    keywords: [
      elements.campaignInputs.keyword.value.trim() || "консультация",
    ],
    negative_keywords: [],
    autotargeting: {
      EXACT: true,
      ALTERNATIVE: true,
      COMPETITOR: false,
      BROADER: true,
      ACCESSORY: false,
    },
    ads: [
      defaultCampaignAd(id, 1),
      defaultCampaignAd(id, 2),
    ],
  };
}

function assignPilotGroup(group) {
  state.campaignAdGroups.forEach((candidate) => {
    candidate.selected_for_pilot = candidate.id === group.id;
    candidate.ads.forEach((ad) => {
      ad.pilot_role = null;
    });
  });
  while (group.ads.length < 2) {
    group.ads.push(defaultCampaignAd(group.id, group.ads.length + 1));
  }
  group.ads[0].pilot_role = "A";
  group.ads[1].pilot_role = "B";
}

function renderCampaignAdGroups() {
  const group = selectedCampaignAdGroup();
  elements.campaignAdGroupSelect.replaceChildren();
  state.campaignAdGroups.forEach((candidate, index) => {
    const option = document.createElement("option");
    option.value = candidate.id;
    setText(
      option,
      `${candidate.name || `Группа ${index + 1}`}${
        candidate.selected_for_pilot ? " · пилот" : ""
      }`,
    );
    elements.campaignAdGroupSelect.append(option);
  });
  if (!group) {
    elements.campaignAdEditor.replaceChildren();
    return;
  }
  state.selectedAdGroupId = group.id;
  elements.campaignAdGroupSelect.value = group.id;
  elements.campaignAdGroupName.value = group.name;
  elements.campaignAdGroupKeywords.value = group.keywords.join("\n");
  elements.campaignAdGroupNegativeKeywords.value =
    group.negative_keywords.join("\n");
  elements.campaignPilotGroup.checked = group.selected_for_pilot;
  elements.campaignAutotargeting.forEach((input) => {
    input.checked = Boolean(group.autotargeting[input.dataset.autotargeting]);
  });
  elements.deleteAdGroup.disabled = state.campaignAdGroups.length <= 1;
  renderCampaignAdTabs();
}

function addCampaignAdGroup() {
  if (state.campaignAdGroups.length >= 20) return;
  const group = defaultCampaignAdGroup();
  state.campaignAdGroups.push(group);
  state.selectedAdGroupId = group.id;
  state.selectedAdId = group.ads[0].id;
  renderCampaignAdGroups();
  markCampaignDirty();
}

function deleteCampaignAdGroup() {
  if (state.campaignAdGroups.length <= 1) return;
  const deleted = selectedCampaignAdGroup();
  state.campaignAdGroups = state.campaignAdGroups.filter(
    (group) => group.id !== deleted.id,
  );
  const replacement = state.campaignAdGroups[0];
  if (deleted.selected_for_pilot) assignPilotGroup(replacement);
  state.selectedAdGroupId = replacement.id;
  state.selectedAdId = replacement.ads[0].id;
  renderCampaignAdGroups();
  markCampaignDirty();
}

function renderCampaignAdTabs() {
  const group = selectedCampaignAdGroup();
  elements.campaignAdTabs.replaceChildren();
  if (!group) return;
  const selected = selectedCampaignAd();
  state.selectedAdId = selected?.id || null;
  group.ads.forEach((ad, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "campaign-ad-tab";
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", String(ad.id === state.selectedAdId));
    setText(
      button,
      ad.pilot_role
        ? `Вариант ${ad.pilot_role}`
        : `Объявление ${index + 1}`,
    );
    button.addEventListener("click", () => {
      state.selectedAdId = ad.id;
      renderCampaignAdTabs();
    });
    elements.campaignAdTabs.append(button);
  });
  elements.addCampaignAd.disabled = group.ads.length >= 50;
  renderCampaignAdEditor();
}

function addCampaignAd() {
  const group = selectedCampaignAdGroup();
  if (!group || group.ads.length >= 50) return;
  const ad = defaultCampaignAd(group.id, group.ads.length + 1);
  group.ads.push(ad);
  state.selectedAdId = ad.id;
  renderCampaignAdTabs();
  markCampaignDirty();
}

function removeCampaignAd() {
  const group = selectedCampaignAdGroup();
  const ad = selectedCampaignAd();
  if (
    !group ||
    !ad ||
    group.ads.length <= 1 ||
    ad.pilot_role
  ) {
    return;
  }
  group.ads = group.ads.filter((candidate) => candidate.id !== ad.id);
  state.selectedAdId = group.ads[0].id;
  renderCampaignAdTabs();
  markCampaignDirty();
}

function renderAdPreview(host, ad) {
  host.replaceChildren();
  const label = document.createElement("span");
  const title = document.createElement("strong");
  const text = document.createElement("p");
  const link = document.createElement("small");
  setText(label, "Предпросмотр на поиске");
  setText(title, ad.titles.filter(Boolean).slice(0, 2).join(" — "));
  setText(text, ad.texts.filter(Boolean)[0] || "");
  setText(
    link,
    `${new URL(ad.href).hostname}/${ad.display_url_path || ""}`,
  );
  host.append(label, title, text, link);
}

function renderCampaignAdEditor() {
  const group = selectedCampaignAdGroup();
  const ad = selectedCampaignAd();
  elements.campaignAdEditor.replaceChildren();
  if (!group || !ad) return;

  const head = document.createElement("div");
  const title = document.createElement("div");
  const eyebrow = document.createElement("p");
  const heading = document.createElement("h5");
  const actions = document.createElement("div");
  const pilotRole = campaignSelect(
    [
      ["", "Не участвует"],
      ["A", "Вариант A"],
      ["B", "Вариант B"],
    ],
    ad.pilot_role || "",
  );
  const remove = document.createElement("button");
  const layout = document.createElement("div");
  const fields = document.createElement("div");
  const preview = document.createElement("aside");

  head.className = "campaign-ad-editor-head";
  eyebrow.className = "eyebrow";
  setText(eyebrow, "Комбинаторное объявление");
  setText(
    heading,
    ad.pilot_role ? `Вариант ${ad.pilot_role}` : "Черновик объявления",
  );
  title.append(eyebrow, heading);
  pilotRole.setAttribute("aria-label", "Роль в пилоте");
  pilotRole.disabled = !group.selected_for_pilot;
  pilotRole.addEventListener("change", () => {
    const nextRole = pilotRole.value || null;
    if (nextRole) {
      const currentRole = ad.pilot_role;
      const occupied = group.ads.find(
        (candidate) =>
          candidate.id !== ad.id && candidate.pilot_role === nextRole,
      );
      if (occupied) occupied.pilot_role = currentRole;
    }
    ad.pilot_role = nextRole;
    renderCampaignAdTabs();
    markCampaignDirty();
  });
  remove.type = "button";
  remove.className = "text-button danger-text";
  remove.disabled = group.ads.length <= 1 || Boolean(ad.pilot_role);
  setText(remove, "Удалить объявление");
  remove.addEventListener("click", removeCampaignAd);
  actions.className = "campaign-ad-editor-actions";
  actions.append(campaignLabel("Роль в пилоте", pilotRole), remove);
  head.append(title, actions);

  fields.className = "campaign-ad-fields";
  const titlesSection = document.createElement("section");
  const titlesHead = document.createElement("div");
  const titlesTitle = document.createElement("h6");
  const addTitle = document.createElement("button");
  titlesSection.className = "campaign-ad-copy-section";
  setText(titlesTitle, `Заголовки · ${ad.titles.length}/7`);
  addTitle.type = "button";
  addTitle.className = "text-button";
  addTitle.disabled = ad.titles.length >= 7;
  setText(addTitle, "Добавить заголовок");
  addTitle.addEventListener("click", () => {
    ad.titles.push("");
    renderCampaignAdEditor();
    markCampaignDirty();
  });
  titlesHead.append(titlesTitle, addTitle);
  titlesSection.append(titlesHead);
  ad.titles.forEach((value, index) => {
    const row = document.createElement("div");
    const input = document.createElement("input");
    const removeTitle = document.createElement("button");
    row.className = "campaign-ad-copy-row";
    input.type = "text";
    input.maxLength = 56;
    input.value = value;
    input.setAttribute("aria-label", `Заголовок ${index + 1}`);
    input.addEventListener("input", () => {
      ad.titles[index] = input.value;
      renderAdPreview(preview, ad);
    });
    removeTitle.type = "button";
    removeTitle.className = "text-button danger-text";
    removeTitle.disabled = ad.titles.length <= 1;
    removeTitle.setAttribute(
      "aria-label",
      `Убрать вариант заголовка № ${index + 1}`,
    );
    setText(removeTitle, "×");
    removeTitle.addEventListener("click", () => {
      ad.titles.splice(index, 1);
      renderCampaignAdEditor();
      markCampaignDirty();
    });
    row.append(input, removeTitle);
    titlesSection.append(row);
  });

  const textsSection = document.createElement("section");
  const textsHead = document.createElement("div");
  const textsTitle = document.createElement("h6");
  const addText = document.createElement("button");
  textsSection.className = "campaign-ad-copy-section";
  setText(textsTitle, `Тексты · ${ad.texts.length}/3`);
  addText.type = "button";
  addText.className = "text-button";
  addText.disabled = ad.texts.length >= 3;
  setText(addText, "Добавить текст");
  addText.addEventListener("click", () => {
    ad.texts.push("");
    renderCampaignAdEditor();
    markCampaignDirty();
  });
  textsHead.append(textsTitle, addText);
  textsSection.append(textsHead);
  ad.texts.forEach((value, index) => {
    const row = document.createElement("div");
    const input = document.createElement("textarea");
    const removeText = document.createElement("button");
    row.className = "campaign-ad-copy-row";
    input.rows = 2;
    input.maxLength = 81;
    input.value = value;
    input.setAttribute("aria-label", `Текст ${index + 1}`);
    input.addEventListener("input", () => {
      ad.texts[index] = input.value;
      renderAdPreview(preview, ad);
    });
    removeText.type = "button";
    removeText.className = "text-button danger-text";
    removeText.disabled = ad.texts.length <= 1;
    removeText.setAttribute(
      "aria-label",
      `Убрать текстовый вариант № ${index + 1}`,
    );
    setText(removeText, "×");
    removeText.addEventListener("click", () => {
      ad.texts.splice(index, 1);
      renderCampaignAdEditor();
      markCampaignDirty();
    });
    row.append(input, removeText);
    textsSection.append(row);
  });

  const href = document.createElement("input");
  href.type = "url";
  href.maxLength = 2048;
  href.value = ad.href;
  href.addEventListener("input", () => {
    ad.href = href.value;
    try {
      renderAdPreview(preview, ad);
    } catch {
      preview.replaceChildren();
    }
  });
  const displayPath = document.createElement("input");
  displayPath.type = "text";
  displayPath.maxLength = 20;
  displayPath.value = ad.display_url_path;
  displayPath.addEventListener("input", () => {
    ad.display_url_path = displayPath.value;
    renderAdPreview(preview, ad);
  });
  const callouts = document.createElement("textarea");
  callouts.rows = 3;
  callouts.value = ad.callouts.join("\n");
  callouts.placeholder = "Одно уточнение на строку";
  callouts.addEventListener("input", () => {
    ad.callouts = campaignLines(callouts.value);
  });
  const sitelinks = document.createElement("textarea");
  sitelinks.rows = 3;
  sitelinks.value = ad.sitelinks
    .map((item) => `${item.title} | ${item.href}`)
    .join("\n");
  sitelinks.placeholder = "Название | https://example.ru/page";
  sitelinks.addEventListener("input", () => {
    ad.sitelinks = campaignLines(sitelinks.value)
      .map((line) => line.split("|").map((item) => item.trim()))
      .filter(([linkTitle, linkHref]) => linkTitle && linkHref)
      .map(([linkTitle, linkHref]) => ({
        title: linkTitle,
        href: linkHref,
      }));
  });

  const media = document.createElement("fieldset");
  const mediaLegend = document.createElement("legend");
  setText(mediaLegend, "Изображения");
  media.className = "campaign-ad-media";
  media.append(mediaLegend);
  ["prepared-media-1", "prepared-media-2"].forEach((reference, index) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    const caption = document.createElement("span");
    input.type = "checkbox";
    input.checked = ad.image_references.includes(reference);
    input.addEventListener("change", () => {
      if (input.checked) {
        ad.image_references = [...ad.image_references, reference];
      } else {
        ad.image_references = ad.image_references.filter(
          (item) => item !== reference,
        );
      }
    });
    setText(caption, `Подготовленное изображение ${index + 1}`);
    label.append(input, caption);
    media.append(label);
  });

  fields.append(
    titlesSection,
    textsSection,
    campaignLabel("Посадочная страница объявления", href),
    campaignLabel("Отображаемая ссылка", displayPath),
    campaignLabel("Быстрые ссылки", sitelinks),
    campaignLabel("Уточнения", callouts),
    media,
  );
  layout.className = "campaign-ad-editor-layout";
  preview.className = "campaign-ad-preview";
  renderAdPreview(preview, ad);
  layout.append(fields, preview);
  elements.campaignAdEditor.append(head, layout);
}

function updateCampaignGoalActions() {
  const status =
    state.campaignGoalLifecycle?.lifecycle_status || "NOT_STARTED";
  const pending = status === "AWAITING_SEMANTIC_DECISION";
  const canReject = state.campaignGoalLifecycle?.can_reject === true;
  const outdatedPending = status === "OUTDATED" && canReject;
  const unavailable =
    state.campaignBusy ||
    state.campaignGoalBusy ||
    state.campaignDirty ||
    state.campaignSource !== "test" ||
    !state.campaignDraft;
  elements.verifyCampaignGoal.hidden =
    pending || outdatedPending || status === "APPROVED";
  elements.verifyCampaignGoal.disabled = unavailable;
  elements.approveCampaignGoal.hidden = !pending;
  elements.rejectCampaignGoal.hidden = !pending && !outdatedPending;
  setText(
    elements.rejectCampaignGoal,
    outdatedPending ? "Очистить устаревшую проверку" : "Отклонить цель",
  );
  elements.approveCampaignGoal.disabled = unavailable;
  elements.rejectCampaignGoal.disabled = unavailable;
}

function renderCampaignGoalLifecycle(lifecycle) {
  state.campaignGoalLifecycle = lifecycle;
  const status = lifecycle?.lifecycle_status || "NOT_STARTED";
  const evidence = lifecycle?.technical_evidence || {};
  const candidate = lifecycle?.candidate || {};
  const classes = [
    "is-idle",
    "is-running",
    "is-pending",
    "is-approved",
    "is-rejected",
    "is-outdated",
    "is-error",
  ];
  elements.campaignGoalLifecycle.classList.remove(...classes);
  const className = {
    LOADING: "is-running",
    RUNNING: "is-running",
    AWAITING_SEMANTIC_DECISION: "is-pending",
    APPROVED: "is-approved",
    REJECTED: "is-rejected",
    OUTDATED: "is-outdated",
    FAILED: "is-error",
  }[status] || "is-idle";
  elements.campaignGoalLifecycle.classList.add(className);

  if (status === "LOADING") {
    setText(elements.campaignGoalBadge, "Проверяется");
    setText(elements.campaignGoalLifecycleTitle, "Проверяем статус цели");
    setText(
      elements.campaignGoalLifecycleCopy,
      "Сверяем выбранную версию цели с журналом Goal Lifecycle.",
    );
  } else if (status === "RUNNING") {
    setText(elements.campaignGoalBadge, "Проверяется");
    setText(
      elements.campaignGoalLifecycleTitle,
      "Выполняется техническая проверка",
    );
    setText(
      elements.campaignGoalLifecycleCopy,
      "Создаём кандидатную цель, устанавливаем событие и проверяем его доставку в изолированном контуре.",
    );
  } else if (status === "AWAITING_SEMANTIC_DECISION") {
    setText(elements.campaignGoalBadge, "Нужна оценка");
    setText(
      elements.campaignGoalLifecycleTitle,
      "Симуляция технической проверки завершена",
    );
    setText(
      elements.campaignGoalLifecycleCopy,
      "Изолированные адаптеры смоделировали одно событие без дублей. Реальная Метрика и сайт не изменялись. Подтвердите бизнес-смысл цели.",
    );
  } else if (status === "APPROVED") {
    setText(elements.campaignGoalBadge, "Подтверждена");
    setText(
      elements.campaignGoalLifecycleTitle,
      "Смысл тестовой цели подтверждён",
    );
    setText(
      elements.campaignGoalLifecycleCopy,
      "Бизнес-смысл подтверждён на симуляционных данных. Реальная техническая доставка ещё не доказана; до оптимизации нужны TEST_COUNTER-проверка, период обучения и минимальная выборка.",
    );
  } else if (status === "REJECTED") {
    setText(elements.campaignGoalBadge, "Отклонена");
    setText(elements.campaignGoalLifecycleTitle, "Цель отклонена");
    setText(
      elements.campaignGoalLifecycleCopy,
      "Кандидат исключён из решений, а смоделированные цель и публикация события очищены.",
    );
  } else if (status === "OUTDATED") {
    setText(
      elements.campaignGoalBadge,
      lifecycle?.can_reject ? "Устарела" : "Нужна проверка",
    );
    setText(
      elements.campaignGoalLifecycleTitle,
      "Цель изменена после проверки",
    );
    setText(
      elements.campaignGoalLifecycleCopy,
      lifecycle?.can_reject
        ? "Сохранённая версия цели больше не совпадает с незавершённой проверкой. Сначала очистите устаревшую симуляцию."
        : "Сохранённая версия цели больше не совпадает с доказательством. Запустите симуляцию заново.",
    );
  } else if (status === "DIRTY") {
    setText(elements.campaignGoalBadge, "Не сохранено");
    setText(
      elements.campaignGoalLifecycleTitle,
      "Сначала сохраните изменения цели",
    );
    setText(
      elements.campaignGoalLifecycleCopy,
      "Техническая проверка привязывается к точной сохранённой версии кампании и основной цели.",
    );
  } else if (status === "FAILED") {
    setText(elements.campaignGoalBadge, "Ошибка");
    setText(
      elements.campaignGoalLifecycleTitle,
      "Проверка цели не завершена",
    );
    setText(
      elements.campaignGoalLifecycleCopy,
      lifecycle.message || "Goal Lifecycle остановлен безопасной проверкой.",
    );
  } else {
    setText(elements.campaignGoalBadge, "SIMULATED");
    setText(elements.campaignGoalLifecycleTitle, "Проверка цели Метрики");
    setText(
      elements.campaignGoalLifecycleCopy,
      "Проверьте кандидатную цель на изолированных адаптерах и отдельно подтвердите её бизнес-смысл.",
    );
  }

  setText(
    elements.campaignGoalCandidate,
    candidate.name || primaryCampaignGoal()?.name || "—",
  );
  setText(
    elements.campaignGoalEvent,
    Number(evidence.emitted_count) === 1
      ? "1 смоделированное событие · без дублей"
      : "Не проверено",
  );
  setText(
    elements.campaignGoalDelivery,
    lifecycle?.technical_status === "VERIFIED" &&
      evidence.delivery_observed === true
      ? "Симуляция доставки подтверждена"
      : "Не проверена",
  );
  setText(
    elements.campaignGoalOptimization,
    status === "APPROVED"
      ? "Период обучения · ожидает выборку"
      : status === "REJECTED"
        ? "Исключена из решений"
        : "Не допущена",
  );
  setText(
    elements.campaignGoalSafety,
    lifecycle?.external_write_sent
      ? "Выполнена внешняя запись"
      : "SIMULATED · внешних изменений нет",
  );
  setText(elements.campaignGoalRunId, lifecycle?.run_id || "—");
  const hasEvidence = Boolean(evidence.goal_id);
  elements.campaignGoalEvidenceDetails.hidden = !hasEvidence;
  if (hasEvidence) {
    setText(elements.campaignGoalEvidenceId, evidence.goal_id);
    setText(
      elements.campaignGoalEvidenceType,
      `${evidence.goal_type || "—"} · ${evidence.classification || "—"}`,
    );
    setText(elements.campaignGoalEvidenceEvent, evidence.event || "—");
    setText(elements.campaignGoalEvidenceSelector, evidence.selector || "—");
    setText(
      elements.campaignGoalEvidenceScenario,
      `${evidence.http_method || "—"} · ${evidence.trigger_selector || "—"}`,
    );
    setText(
      elements.campaignGoalEvidenceCheckedAt,
      formatMoment(evidence.checked_at),
    );
    setText(elements.campaignGoalEvidenceAuthor, evidence.author || "—");
    setText(
      elements.campaignGoalEvidenceVersion,
      evidence.configuration_version || "—",
    );
  }
  setCampaignBusy(state.campaignBusy);
}

async function loadCampaignGoalLifecycle(draftId) {
  if (!draftId) return;
  renderCampaignGoalLifecycle({
    draft_id: draftId,
    lifecycle_status: "LOADING",
    candidate: {
      name: primaryCampaignGoal()?.name || "—",
    },
    external_write_sent: false,
  });
  try {
    const lifecycle = await requestJson(
      `/api/campaigns/${encodeURIComponent(draftId)}/goal`,
    );
    if (
      state.campaignSource === "test" &&
      state.campaignDraft?.draft_id === draftId &&
      !state.campaignDirty
    ) {
      renderCampaignGoalLifecycle(lifecycle);
    }
  } catch (error) {
    if (state.campaignDraft?.draft_id === draftId) {
      renderCampaignGoalLifecycle({
        draft_id: draftId,
        lifecycle_status: "FAILED",
        message: error.message,
        candidate: {
          name: primaryCampaignGoal()?.name || "—",
        },
        external_write_sent: false,
      });
    }
  }
}

async function verifySelectedCampaignGoal() {
  if (
    !state.campaignDraft ||
    state.campaignDirty ||
    state.campaignSource !== "test"
  ) {
    return;
  }
  const draftId = state.campaignDraft.draft_id;
  state.campaignGoalBusy = true;
  setCampaignBusy(true);
  elements.campaignGoalMessage.classList.remove("is-error");
  setText(
    elements.campaignGoalMessage,
    "Проверяем создание цели, установку события и доставку…",
  );
  renderCampaignGoalLifecycle({
    draft_id: draftId,
    lifecycle_status: "RUNNING",
    candidate: {
      name: primaryCampaignGoal()?.name || "—",
    },
    external_write_sent: false,
  });
  try {
    await requestJson(
      `/api/campaigns/${encodeURIComponent(draftId)}/goal/technical`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: state.campaignDraft.revision,
        }),
      },
    );
    await loadCampaignGoalLifecycle(draftId);
    setText(
      elements.campaignGoalMessage,
      "Техническая проверка завершена. Требуется оценка бизнес-смысла.",
    );
  } catch (error) {
    elements.campaignGoalMessage.classList.add("is-error");
    setText(elements.campaignGoalMessage, error.message);
    renderCampaignGoalLifecycle({
      draft_id: draftId,
      lifecycle_status: "FAILED",
      message: error.message,
      candidate: {
        name: primaryCampaignGoal()?.name || "—",
      },
      external_write_sent: false,
    });
  } finally {
    state.campaignGoalBusy = false;
    setCampaignBusy(false);
  }
}

async function decideSelectedCampaignGoal(semanticDecision) {
  const lifecycleStatus =
    state.campaignGoalLifecycle?.lifecycle_status || "NOT_STARTED";
  const canRejectOutdated =
    semanticDecision === "REJECT" &&
    lifecycleStatus === "OUTDATED" &&
    state.campaignGoalLifecycle?.can_reject === true;
  if (
    !state.campaignDraft ||
    state.campaignDirty ||
    state.campaignSource !== "test" ||
    (lifecycleStatus !== "AWAITING_SEMANTIC_DECISION" &&
      !canRejectOutdated)
  ) {
    return;
  }
  const draftId = state.campaignDraft.draft_id;
  const runId = state.campaignGoalLifecycle.run_id;
  state.campaignGoalBusy = true;
  setCampaignBusy(true);
  elements.campaignGoalMessage.classList.remove("is-error");
  setText(
    elements.campaignGoalMessage,
    semanticDecision === "APPROVE"
      ? "Сохраняем подтверждение бизнес-смысла…"
      : "Отклоняем цель и очищаем тестовые изменения…",
  );
  try {
    await requestJson(
      `/api/campaigns/${encodeURIComponent(draftId)}/goal/decision`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: state.campaignDraft.revision,
          run_id: runId,
          semantic_decision: semanticDecision,
        }),
      },
    );
    await loadCampaignGoalLifecycle(draftId);
    setText(
      elements.campaignGoalMessage,
      semanticDecision === "APPROVE"
        ? "Бизнес-смысл цели подтверждён."
        : canRejectOutdated
          ? "Устаревшая симуляция очищена. Цель можно проверить заново."
          : "Цель отклонена и исключена из решений.",
    );
  } catch (error) {
    elements.campaignGoalMessage.classList.add("is-error");
    setText(elements.campaignGoalMessage, error.message);
  } finally {
    state.campaignGoalBusy = false;
    setCampaignBusy(false);
  }
}

function renderCampaignLaunchStatus(launch) {
  state.campaignLaunch = launch;
  const status = launch?.launch_status || "NOT_LAUNCHED";
  const completed = Array.isArray(launch?.completed_steps)
    ? launch.completed_steps.length
    : 0;
  const total = Number(launch?.total_steps) || 8;
  const launched = status === "LAUNCHED";
  const outdated = status === "OUTDATED" || status === "DIRTY";
  const running = status === "RUNNING" || status === "LOADING";
  const failed = status === "FAILED";

  elements.campaignLaunchStatus.classList.toggle("is-launched", launched);
  elements.campaignLaunchStatus.classList.toggle("is-outdated", outdated);
  elements.campaignLaunchStatus.classList.toggle("is-running", running);
  elements.campaignLaunchStatus.classList.toggle("is-error", failed);
  elements.campaignLaunchStatus.classList.toggle(
    "is-idle",
    !launched && !outdated && !running && !failed,
  );
  elements.campaignStatusBadge.classList.toggle("is-launched", launched);
  elements.campaignStatusBadge.classList.toggle(
    "is-outdated",
    outdated || failed,
  );

  if (launched) {
    setText(elements.campaignStatusBadge, "Тест запущен");
    setText(elements.campaignLaunchTitle, "Тестовая кампания запущена");
    setText(
      elements.campaignLaunchCopy,
      "Campaign Lifecycle завершён и подтверждён полным чтением состояния.",
    );
  } else if (status === "OUTDATED") {
    setText(elements.campaignStatusBadge, "Нужен перезапуск");
    setText(elements.campaignLaunchTitle, "Кампания изменена после запуска");
    setText(
      elements.campaignLaunchCopy,
      "Сохранённая версия отличается от последнего тестового запуска.",
    );
  } else if (status === "DIRTY") {
    setText(elements.campaignStatusBadge, "Не сохранено");
    setText(elements.campaignLaunchTitle, "Сначала сохраните изменения");
    setText(
      elements.campaignLaunchCopy,
      "Тестовый запуск доступен только для сохранённой версии кампании.",
    );
  } else if (status === "RUNNING") {
    setText(elements.campaignStatusBadge, "Запускается");
    setText(elements.campaignLaunchTitle, "Выполняется тестовый запуск");
    setText(
      elements.campaignLaunchCopy,
      "Создаём объекты, проверяем модерацию и состояние в sealed fake-контуре.",
    );
  } else if (status === "LOADING") {
    setText(elements.campaignStatusBadge, "Проверяется");
    setText(elements.campaignLaunchTitle, "Проверяем статус запуска");
    setText(
      elements.campaignLaunchCopy,
      "Сверяем выбранную версию кампании с журналом Campaign Lifecycle.",
    );
  } else if (failed) {
    setText(elements.campaignStatusBadge, "Ошибка запуска");
    setText(elements.campaignLaunchTitle, "Тестовый запуск не завершён");
    setText(
      elements.campaignLaunchCopy,
      launch.message || "Campaign Lifecycle остановлен безопасной проверкой.",
    );
  } else {
    setText(elements.campaignStatusBadge, "Черновик");
    setText(elements.campaignLaunchTitle, "Тестовая кампания не запускалась");
    setText(
      elements.campaignLaunchCopy,
      "Запуск выполнит Campaign Lifecycle в изолированном контуре.",
    );
  }

  setText(
    elements.campaignLaunchSteps,
    running && completed === 0 ? "Подготовка" : `${completed} из ${total} этапов`,
  );
  setText(
    elements.campaignLaunchSafety,
    launch?.external_write_sent
      ? "Внешний write отправлен"
      : "Внешних изменений нет",
  );
  setText(
    elements.campaignLaunchTime,
    launch?.requested_at ? formatMoment(launch.requested_at) : "—",
  );
  setText(elements.campaignLaunchRunId, launch?.run_id || "—");
}

async function loadCampaignLaunch(draftId) {
  if (!draftId) return;
  renderCampaignLaunchStatus({
    draft_id: draftId,
    launch_status: "LOADING",
    completed_steps: [],
    total_steps: campaignLifecycleSteps.length,
    external_write_sent: false,
  });
  try {
    const launch = await requestJson(
      `/api/campaigns/${encodeURIComponent(draftId)}/launch`,
    );
    if (
      state.campaignSource === "test" &&
      state.campaignDraft?.draft_id === draftId &&
      !state.campaignDirty
    ) {
      renderCampaignLaunchStatus(launch);
      elements.launchCampaign.disabled = state.campaignBusy;
    }
  } catch (error) {
    if (state.campaignDraft?.draft_id === draftId) {
      renderCampaignLaunchStatus({
        draft_id: draftId,
        launch_status: "FAILED",
        message: error.message,
        completed_steps: [],
        total_steps: 8,
        external_write_sent: false,
      });
      elements.launchCampaign.disabled = true;
    }
  }
}

function renderCampaignDraft(draft) {
  state.campaignDraft = draft;
  state.campaignDirty = false;
  state.campaignPrimaryEvent = draft.metrika_goal.event;
  state.campaignGoals = cloneCampaignValue(draft.goal_settings.goals);
  state.campaignAdGroups = cloneCampaignValue(draft.ad_groups);
  state.selectedAdGroupId =
    state.campaignAdGroups.find((group) => group.selected_for_pilot)?.id ||
    state.campaignAdGroups[0]?.id ||
    null;
  state.selectedAdId =
    selectedCampaignAdGroup()?.ads[0]?.id || null;
  elements.campaignInputs.name.value = draft.campaign.name;
  elements.campaignInputs.weekly_budget_rub.value = String(
    draft.campaign.weekly_budget_rub,
  );
  elements.campaignInputs.keyword.value = draft.campaign.keyword;
  elements.campaignInputs.landing_page.value = draft.campaign.landing_page;
  state.campaignLandingPageValue = draft.campaign.landing_page;
  elements.campaignInputs.business_goal.value = draft.business_goal.meaning;
  elements.campaignInputs.target_cpa_rub.value = String(
    draft.business_goal.target_cpa_rub,
  );
  elements.campaignInputs.goal_strategy.value = draft.goal_settings.strategy;
  elements.campaignInputs.payment_model
    .querySelector('option[value="CONVERSIONS"]')
    .disabled = draft.goal_settings.strategy === "MAXIMIZE_CLICKS";
  elements.campaignInputs.payment_model.value =
    draft.goal_settings.payment_model;
  elements.campaignInputs.attribution_model.value =
    draft.goal_settings.attribution_model;
  elements.campaignInputs.counter_id.value = draft.goal_settings.counter_id;
  renderCampaignGoals();
  renderCampaignAdGroups();
  setText(elements.campaignEditorTitle, draft.campaign.name);
  setText(
    elements.campaignDraftStatus,
    draft.revision > 0
      ? `Версия ${draft.revision} · выбрана для следующего цикла`
      : "Новый черновик · ещё не редактировался",
  );
  setText(
    elements.campaignDraftMeta,
    draft.updated_at
      ? `Сохранено ${formatMoment(draft.updated_at)}`
      : "Локальный черновик",
  );
  elements.campaignStatusBadge.classList.remove(
    "is-launched",
    "is-outdated",
  );
  setText(elements.campaignStatusBadge, "Черновик");
}

function setCampaignBusy(busy) {
  state.campaignBusy = busy;
  const localMode = state.campaignSource === "test";
  const goalDecisionPending =
    state.campaignGoalLifecycle?.lifecycle_status ===
    "AWAITING_SEMANTIC_DECISION";
  const editorLocked = busy || goalDecisionPending;
  elements.campaignSourceButtons.forEach((button) => {
    button.disabled = busy;
  });
  elements.campaignList
    .querySelectorAll(".campaign-name-button")
    .forEach((button) => {
      button.disabled = busy;
    });
  elements.newCampaign.disabled = editorLocked || !localMode;
  elements.saveCampaign.disabled = editorLocked || !state.campaignDraft;
  elements.launchCampaign.disabled =
    editorLocked ||
    !state.campaignDraft ||
    state.campaignDirty ||
    !localMode;
  elements.deleteCampaign.disabled =
    editorLocked ||
    !state.campaignDraft ||
    state.campaignCatalog.length <= 1;
  elements.campaignSearch.disabled = busy;
  elements.campaignEditor
    .querySelectorAll("input, textarea, select, button")
    .forEach((field) => {
      field.disabled = editorLocked;
    });
  updateCampaignGoalActions();
}

function setDirectCampaignBusy(busy) {
  state.directCampaignBusy = busy;
  elements.refreshDirectCampaigns.disabled = busy;
  elements.refreshDirectCampaigns.setAttribute("aria-busy", String(busy));
}

const directStateLabels = {
  ARCHIVED: "В архиве",
  CONVERTED: "Преобразована",
  ENDED: "Завершена",
  OFF: "Показы остановлены",
  ON: "Показы идут",
  SUSPENDED: "Приостановлена",
};

const directStatusLabels = {
  ACCEPTED: "Принята",
  DRAFT: "Черновик",
  MODERATION: "На модерации",
  REJECTED: "Отклонена",
};

const directPaymentLabels = {
  ALLOWED: "Оплата разрешена",
  DISALLOWED: "Оплата недоступна",
};

const directTypeLabels = {
  CPM_BANNER_CAMPAIGN: "Медийная кампания",
  MOBILE_APP_CAMPAIGN: "Продвижение приложений",
  TEXT_CAMPAIGN: "Текстово-графическая",
  UNIFIED_CAMPAIGN: "Единая перфоманс-кампания",
};

function directLabel(value, labels) {
  if (!value) return "—";
  return labels[value] || value;
}

function formatDirectDate(value) {
  if (!value) return "Не задано";
  const [year, month, day] = String(value).split("-");
  return `${day}.${month}.${year}`;
}

function formatDirectBudget(value) {
  if (value === null || value === undefined) return "Не задан";
  return `${formatRuleNumber(Number(value) / 1_000_000)} ₽ в день`;
}

function renderDirectCampaign(campaign) {
  if (!campaign) {
    state.selectedDirectCampaignId = null;
    setText(elements.campaignEditorTitle, "Кампании не найдены");
    setText(
      elements.campaignDraftStatus,
      "В доступном аккаунте нет кампаний Яндекс Директа.",
    );
    setText(elements.campaignDraftMeta, "Источник: Campaigns.get");
    Object.values(elements.directCampaignFacts).forEach((element) => {
      setText(element, "—");
    });
    return;
  }
  state.selectedDirectCampaignId = campaign.campaign_id;
  setText(elements.campaignEditorTitle, campaign.name);
  setText(
    elements.campaignDraftStatus,
    `${directLabel(campaign.state, directStateLabels)} · ` +
      `${directLabel(campaign.status, directStatusLabels)}`,
  );
  setText(
    elements.campaignDraftMeta,
    state.directCampaignFetchedAt
      ? `Обновлено ${formatMoment(state.directCampaignFetchedAt)}`
      : "Источник: Campaigns.get",
  );
  setText(elements.directCampaignFacts.campaign_id, campaign.campaign_id);
  setText(
    elements.directCampaignFacts.type,
    directLabel(campaign.type, directTypeLabels),
  );
  setText(
    elements.directCampaignFacts.state,
    directLabel(campaign.state, directStateLabels),
  );
  setText(
    elements.directCampaignFacts.status,
    directLabel(campaign.status, directStatusLabels),
  );
  setText(
    elements.directCampaignFacts.status_payment,
    directLabel(campaign.status_payment, directPaymentLabels),
  );
  setText(
    elements.directCampaignFacts.daily_budget_micros,
    formatDirectBudget(campaign.daily_budget_micros),
  );
  setText(
    elements.directCampaignFacts.start_date,
    formatDirectDate(campaign.start_date),
  );
  setText(
    elements.directCampaignFacts.end_date,
    formatDirectDate(campaign.end_date),
  );
  setText(elements.directCampaignFacts.timezone, campaign.timezone || "—");
  setText(
    elements.directCampaignFacts.client_info,
    campaign.client_info || state.directCampaignAccount || "—",
  );
}

function renderCampaignList() {
  const directMode = state.campaignSource === "direct";
  const sourceItems = directMode
    ? state.directCampaignCatalog
    : state.campaignCatalog;
  const query = elements.campaignSearch.value.trim().toLocaleLowerCase("ru");
  const filtered = sourceItems.filter((item) => {
    const haystack = (
      directMode
        ? `${item.name} ${item.campaign_id} ${item.status} ${item.state}`
        : `${item.name} ${item.keyword}`
    ).toLocaleLowerCase("ru");
    return haystack.includes(query);
  });
  setText(
    elements.campaignFilterCount,
    query
      ? `${filtered.length} из ${sourceItems.length}`
      : `${filtered.length}`,
  );
  elements.campaignList.replaceChildren();
  filtered.forEach((item) => {
    const row = document.createElement("tr");
    const nameCell = document.createElement("td");
    const budgetCell = document.createElement("td");
    const cpaCell = document.createElement("td");
    const selectButton = document.createElement("button");
    const detail = document.createElement("small");

    const selected = directMode
      ? item.campaign_id === state.selectedDirectCampaignId
      : item.selected;
    row.classList.toggle("is-selected", selected);
    if (selected) {
      row.setAttribute("aria-current", "true");
    }
    selectButton.type = "button";
    selectButton.className = "campaign-name-button";
    selectButton.disabled = state.campaignBusy;
    selectButton.setAttribute(
      "aria-label",
      directMode ? `Открыть ${item.name}` : `Редактировать ${item.name}`,
    );
    setText(selectButton, item.name);
    setText(
      detail,
      directMode
        ? `ID ${item.campaign_id} · ${directLabel(
            item.status,
            directStatusLabels,
          )}`
        : item.updated_at
          ? `Изменена ${formatMoment(item.updated_at)}`
          : `Новый черновик · ${item.keyword}`,
    );
    selectButton.append(detail);
    selectButton.addEventListener("click", () => {
      if (directMode) {
        state.selectedDirectCampaignId = item.campaign_id;
        renderCampaignList();
        renderDirectCampaign(item);
      } else {
        selectCampaignDraft(item.draft_id);
      }
    });
    setText(
      budgetCell,
      directMode
        ? formatDirectBudget(item.daily_budget_micros).replace(" в день", "")
        : `${formatRuleNumber(item.weekly_budget_rub)} ₽`,
    );
    setText(
      cpaCell,
      directMode
        ? directLabel(item.state, directStateLabels)
        : `${formatRuleNumber(item.target_cpa_rub)} ₽`,
    );
    nameCell.append(selectButton);
    row.append(nameCell, budgetCell, cpaCell);
    elements.campaignList.append(row);
  });
  elements.campaignEmpty.hidden = filtered.length > 0;
  setText(
    elements.campaignEmpty,
    directMode
      ? "В аккаунте Яндекс Директа нет кампаний по этому запросу."
      : "По вашему запросу кампаний не найдено.",
  );
}

function renderCampaignCatalog(catalog) {
  state.campaignCatalog = Array.isArray(catalog.items) ? catalog.items : [];
  if (catalog.selected) {
    renderCampaignDraft(catalog.selected);
    loadCampaignLaunch(catalog.selected.draft_id);
    loadCampaignGoalLifecycle(catalog.selected.draft_id);
  }
  if (state.campaignSource === "test") {
    setText(
      elements.campaignCount,
      catalog.total ?? state.campaignCatalog.length,
    );
    renderCampaignList();
    setCampaignBusy(false);
  }
}

function renderDirectCampaignCatalog(catalog) {
  state.directCampaignCatalog = Array.isArray(catalog.items)
    ? catalog.items
    : [];
  state.directCampaignFetchedAt = catalog.fetched_at || null;
  state.directCampaignAccount = catalog.account || null;
  const selected =
    state.directCampaignCatalog.find(
      (item) => item.campaign_id === state.selectedDirectCampaignId,
    ) || state.directCampaignCatalog[0];
  state.selectedDirectCampaignId = selected?.campaign_id || null;
  if (state.campaignSource !== "direct") return;
  setText(
    elements.campaignCount,
    catalog.total ?? state.directCampaignCatalog.length,
  );
  renderCampaignList();
  renderDirectCampaign(selected);
  setText(
    elements.campaignSourceNote,
    state.directCampaignFetchedAt
      ? `Аккаунт ${state.directCampaignAccount} · обновлено ` +
          `${formatMoment(state.directCampaignFetchedAt)}`
      : "Реальные данные · только чтение",
  );
}

function applyCampaignSourceLayout() {
  const directMode = state.campaignSource === "direct";
  elements.campaignSourceButtons.forEach((button) => {
    const active = button.dataset.campaignSource === state.campaignSource;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  elements.newCampaign.hidden = directMode;
  elements.refreshDirectCampaigns.hidden = !directMode;
  elements.campaignInspectorActions.hidden = directMode;
  elements.campaignLaunchStatus.hidden = directMode;
  elements.campaignEditor.hidden = directMode;
  elements.directCampaignInspector.hidden = !directMode;
  elements.campaignStatusBadge.classList.toggle("is-live", directMode);
  setText(
    elements.campaignStatusBadge,
    directMode ? "Только чтение" : "Черновик",
  );
  setText(
    elements.campaignConsoleDescription,
    directMode
      ? (
          "Изучайте реальные кампании аккаунта Яндекс Директа. " +
          "Создание, редактирование и удаление отключены."
        )
      : (
          "Просматривайте, создавайте и редактируйте локальные " +
          "тестовые кампании."
        ),
  );
  setText(
    elements.campaignSourceNote,
    directMode
      ? state.directCampaignFetchedAt
        ? `Аккаунт ${state.directCampaignAccount} · обновлено ` +
          `${formatMoment(state.directCampaignFetchedAt)}`
        : "Реальные данные · только чтение"
      : "Изменения сохраняются только локально",
  );
  setText(
    elements.campaignCountLabel,
    directMode ? "кампаний в Директе" : "тестовых кампаний",
  );
  setText(
    elements.campaignRegistryEyebrow,
    directMode ? "Production · read-only" : "Все черновики",
  );
  setText(
    elements.campaignRegistryTitle,
    directMode ? "Кампании Яндекс Директа" : "Текущие кампании",
  );
  setText(
    elements.campaignBudgetHeading,
    directMode ? "Дневной бюджет" : "Бюджет",
  );
  setText(
    elements.campaignMetricHeading,
    directMode ? "Состояние" : "CPA",
  );
  elements.campaignSearch.placeholder = directMode
    ? "Название, ID или статус"
    : "Название или ключевая фраза";
  elements.campaignSearch.value = "";

  if (directMode) {
    setText(elements.campaignCount, state.directCampaignCatalog.length);
    renderCampaignList();
    renderDirectCampaign(
      state.directCampaignCatalog.find(
        (item) => item.campaign_id === state.selectedDirectCampaignId,
      ) || state.directCampaignCatalog[0],
    );
  } else {
    setText(elements.campaignCount, state.campaignCatalog.length);
    renderCampaignList();
    if (state.campaignDraft) {
      renderCampaignDraft(state.campaignDraft);
      loadCampaignLaunch(state.campaignDraft.draft_id);
      loadCampaignGoalLifecycle(state.campaignDraft.draft_id);
    }
    setCampaignBusy(false);
  }
}

async function selectCampaignSource(source) {
  if (
    state.campaignBusy ||
    !["test", "direct"].includes(source) ||
    source === state.campaignSource ||
    (state.campaignSource === "test" && !confirmCampaignDiscard())
  ) {
    return;
  }
  if (state.campaignSource === "test" && state.campaignDirty) {
    renderCampaignDraft(state.campaignDraft);
  }
  state.campaignSource = source;
  elements.campaignMessage.classList.remove("is-error");
  setText(elements.campaignMessage, "");
  applyCampaignSourceLayout();
  if (source === "direct" && state.directCampaignCatalog.length === 0) {
    await loadDirectCampaigns();
  }
}

async function loadDirectCampaigns() {
  if (state.directCampaignBusy) return;
  setDirectCampaignBusy(true);
  elements.campaignMessage.classList.remove("is-error");
  setText(
    elements.campaignMessage,
    "Получаем реальные кампании из Яндекс Директа…",
  );
  try {
    const catalog = await requestJson("/api/yandex-direct/campaigns");
    renderDirectCampaignCatalog(catalog);
    setText(
      elements.campaignMessage,
      catalog.truncated
        ? "Показаны первые 10 000 кампаний. Доступ остаётся только для чтения."
        : (
            `Получено кампаний: ${catalog.total}. ` +
            "Доступ остаётся только для чтения."
          ),
    );
  } catch (error) {
    state.directCampaignCatalog = [];
    state.selectedDirectCampaignId = null;
    renderDirectCampaignCatalog({ items: [], total: 0 });
    elements.campaignMessage.classList.add("is-error");
    setText(elements.campaignMessage, error.message);
  } finally {
    setDirectCampaignBusy(false);
  }
}

function campaignEditorPayload() {
  const goals = cloneCampaignValue(state.campaignGoals).map((goal) => ({
    ...goal,
    value_rub:
      goal.value_mode === "DYNAMIC"
        ? null
        : Math.trunc(Number(goal.value_rub)),
  }));
  return {
    campaign: {
      name: elements.campaignInputs.name.value.trim(),
      weekly_budget_rub: integerValue(
        elements.campaignInputs.weekly_budget_rub,
      ),
      keyword: elements.campaignInputs.keyword.value.trim(),
      landing_page: elements.campaignInputs.landing_page.value.trim(),
    },
    business_goal: {
      meaning: elements.campaignInputs.business_goal.value.trim(),
      target_cpa_rub: integerValue(
        elements.campaignInputs.target_cpa_rub,
      ),
    },
    goal_settings: {
      strategy: elements.campaignInputs.goal_strategy.value,
      payment_model: elements.campaignInputs.payment_model.value,
      attribution_model: elements.campaignInputs.attribution_model.value,
      counter_id: elements.campaignInputs.counter_id.value,
      goals,
    },
    ad_groups: cloneCampaignValue(state.campaignAdGroups),
  };
}

async function loadCampaignDraft() {
  try {
    const catalog = await requestJson("/api/campaigns");
    renderCampaignCatalog(catalog);
  } catch (error) {
    elements.campaignMessage.classList.add("is-error");
    setText(elements.campaignMessage, error.message);
  }
}

function confirmCampaignDiscard() {
  return (
    !state.campaignDirty ||
    window.confirm(
      "Отменить несохранённые изменения и открыть другую кампанию?",
    )
  );
}

async function selectCampaignDraft(draftId) {
  if (
    state.campaignBusy ||
    !draftId ||
    draftId === state.campaignDraft?.draft_id ||
    !confirmCampaignDiscard()
  ) {
    return;
  }
  setCampaignBusy(true);
  elements.campaignMessage.classList.remove("is-error");
  try {
    const catalog = await requestJson(
      `/api/campaigns/${encodeURIComponent(draftId)}/select`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      },
    );
    renderCampaignCatalog(catalog);
    setText(elements.campaignMessage, "Кампания выбрана для редактирования.");
  } catch (error) {
    elements.campaignMessage.classList.add("is-error");
    setText(elements.campaignMessage, error.message);
    setCampaignBusy(false);
  }
}

async function createCampaignDraft() {
  if (!confirmCampaignDiscard()) return;
  setCampaignBusy(true);
  elements.campaignMessage.classList.remove("is-error");
  try {
    const catalog = await requestJson("/api/campaigns", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_revision: state.campaignDraft?.revision || 0,
      }),
    });
    renderCampaignCatalog(catalog);
    setText(
      elements.campaignMessage,
      "Новая кампания добавлена. Заполните параметры и сохраните изменения.",
    );
  } catch (error) {
    elements.campaignMessage.classList.add("is-error");
    setText(elements.campaignMessage, error.message);
    setCampaignBusy(false);
  }
}

async function saveCampaignDraft() {
  if (!state.campaignDraft) return;
  setCampaignBusy(true);
  elements.campaignMessage.classList.remove("is-error");
  try {
    const draft = await requestJson(
      `/api/campaigns/${encodeURIComponent(state.campaignDraft.draft_id)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: state.campaignDraft.revision,
          ...campaignEditorPayload(),
        }),
      },
    );
    renderCampaignDraft(draft);
    const catalog = await requestJson("/api/campaigns");
    renderCampaignCatalog(catalog);
    setText(
      elements.campaignMessage,
      "Черновик сохранён. Реальная кампания не изменена.",
    );
    await refreshTestState(false);
  } catch (error) {
    elements.campaignMessage.classList.add("is-error");
    setText(elements.campaignMessage, error.message);
    setCampaignBusy(false);
  }
}

async function launchTestCampaign() {
  if (!state.campaignDraft || state.campaignSource !== "test") return;
  if (state.campaignDirty) {
    elements.campaignMessage.classList.add("is-error");
    setText(
      elements.campaignMessage,
      "Сохраните изменения перед тестовым запуском кампании.",
    );
    return;
  }
  const draftId = state.campaignDraft.draft_id;
  setCampaignBusy(true);
  elements.launchCampaign.setAttribute("aria-busy", "true");
  setText(elements.launchCampaign, "Запускаем…");
  elements.campaignMessage.classList.remove("is-error");
  setText(
    elements.campaignMessage,
    "Выполняем Campaign Lifecycle в изолированном тестовом контуре…",
  );
  renderCampaignLaunchStatus({
    draft_id: draftId,
    launch_status: "RUNNING",
    completed_steps: [],
    total_steps: campaignLifecycleSteps.length,
    external_write_sent: false,
  });
  try {
    const result = await requestJson(
      `/api/campaigns/${encodeURIComponent(draftId)}/launch`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: state.campaignDraft.revision,
        }),
      },
    );
    const completedSteps = Array.isArray(result.completed_steps)
      ? result.completed_steps
      : [];
    const verified =
      result.status === "APPLIED" &&
      result.execution_mode === "SIMULATION" &&
      completedSteps.length === campaignLifecycleSteps.length &&
      completedSteps.every(
        (step, index) => step === campaignLifecycleSteps[index],
      ) &&
      result.external_write_sent === false;
    if (
      state.campaignSource === "test" &&
      state.campaignDraft?.draft_id === draftId
    ) {
      renderCampaignLaunchStatus({
        draft_id: draftId,
        launch_status: verified ? "LAUNCHED" : "FAILED",
        workflow_status: result.status,
        current: true,
        run_id: result.run_id,
        requested_at: result.requested_at,
        completed_steps: completedSteps,
        total_steps: campaignLifecycleSteps.length,
        external_write_sent: result.external_write_sent,
        message: verified
          ? null
          : result.detail ||
            "Campaign Lifecycle не подтвердил полный тестовый запуск.",
      });
      setText(
        elements.campaignMessage,
        verified
          ? "Тестовая кампания запущена. Внешние изменения не выполнялись."
          : "Тестовый запуск не подтверждён. Проверьте статус Campaign Lifecycle.",
      );
      elements.campaignMessage.classList.toggle("is-error", !verified);
    }
  } catch (error) {
    if (
      state.campaignSource === "test" &&
      state.campaignDraft?.draft_id === draftId
    ) {
      elements.campaignMessage.classList.add("is-error");
      setText(elements.campaignMessage, error.message);
      renderCampaignLaunchStatus({
        draft_id: draftId,
        launch_status: "FAILED",
        message: error.message,
        completed_steps: [],
        total_steps: campaignLifecycleSteps.length,
        external_write_sent: false,
      });
    }
  } finally {
    elements.launchCampaign.removeAttribute("aria-busy");
    setText(elements.launchCampaign, "Запустить тестовую кампанию");
    setCampaignBusy(false);
  }
}

function openCampaignDeleteDialog() {
  if (!state.campaignDraft || state.campaignCatalog.length <= 1) return;
  setText(
    elements.campaignDeleteName,
    state.campaignDraft.campaign.name,
  );
  elements.campaignDeleteDialog.showModal();
}

async function deleteCampaignDraft() {
  if (!state.campaignDraft) return;
  elements.confirmCampaignDelete.disabled = true;
  elements.campaignMessage.classList.remove("is-error");
  try {
    const catalog = await requestJson(
      `/api/campaigns/${encodeURIComponent(state.campaignDraft.draft_id)}`,
      {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: state.campaignDraft.revision,
        }),
      },
    );
    elements.campaignDeleteDialog.close();
    renderCampaignCatalog(catalog);
    setText(elements.campaignMessage, "Кампания удалена из локального списка.");
  } catch (error) {
    elements.campaignMessage.classList.add("is-error");
    setText(elements.campaignMessage, error.message);
  } finally {
    elements.confirmCampaignDelete.disabled = false;
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
elements.newCampaign.addEventListener("click", createCampaignDraft);
elements.refreshDirectCampaigns.addEventListener(
  "click",
  loadDirectCampaigns,
);
elements.campaignSourceButtons.forEach((button) => {
  button.addEventListener("click", () => {
    selectCampaignSource(button.dataset.campaignSource);
  });
});
elements.saveCampaign.addEventListener("click", saveCampaignDraft);
elements.launchCampaign.addEventListener("click", launchTestCampaign);
elements.verifyCampaignGoal.addEventListener(
  "click",
  verifySelectedCampaignGoal,
);
elements.approveCampaignGoal.addEventListener("click", () => {
  decideSelectedCampaignGoal("APPROVE");
});
elements.rejectCampaignGoal.addEventListener("click", () => {
  decideSelectedCampaignGoal("REJECT");
});
elements.deleteCampaign.addEventListener("click", openCampaignDeleteDialog);
elements.cancelCampaignDelete.addEventListener("click", () => {
  elements.campaignDeleteDialog.close();
});
elements.confirmCampaignDelete.addEventListener(
  "click",
  deleteCampaignDraft,
);
elements.campaignSearch.addEventListener("input", renderCampaignList);
elements.campaignEditor.addEventListener("submit", (event) => {
  event.preventDefault();
  saveCampaignDraft();
});
elements.campaignEditor.addEventListener("input", () => {
  markCampaignDirty();
});
elements.addCampaignGoal.addEventListener("click", addCampaignGoal);
elements.campaignAdGroupSelect.addEventListener("change", () => {
  const group = state.campaignAdGroups.find(
    (candidate) => candidate.id === elements.campaignAdGroupSelect.value,
  );
  if (!group) return;
  state.selectedAdGroupId = group.id;
  state.selectedAdId = group.ads[0]?.id || null;
  renderCampaignAdGroups();
});
elements.addAdGroup.addEventListener("click", addCampaignAdGroup);
elements.deleteAdGroup.addEventListener("click", deleteCampaignAdGroup);
elements.campaignPilotGroup.addEventListener("change", () => {
  const group = selectedCampaignAdGroup();
  if (!group) return;
  if (!elements.campaignPilotGroup.checked && group.selected_for_pilot) {
    elements.campaignPilotGroup.checked = true;
    return;
  }
  assignPilotGroup(group);
  renderCampaignAdGroups();
  markCampaignDirty();
});
elements.campaignAdGroupName.addEventListener("input", () => {
  const group = selectedCampaignAdGroup();
  if (!group) return;
  group.name = elements.campaignAdGroupName.value;
  const option = elements.campaignAdGroupSelect.selectedOptions[0];
  if (option) {
    setText(
      option,
      `${group.name || "Группа без названия"}${
        group.selected_for_pilot ? " · пилот" : ""
      }`,
    );
  }
});
elements.campaignAdGroupKeywords.addEventListener("input", () => {
  const group = selectedCampaignAdGroup();
  if (group) {
    group.keywords = campaignLines(elements.campaignAdGroupKeywords.value);
  }
});
elements.campaignAdGroupNegativeKeywords.addEventListener("input", () => {
  const group = selectedCampaignAdGroup();
  if (group) {
    group.negative_keywords = campaignLines(
      elements.campaignAdGroupNegativeKeywords.value,
    );
  }
});
elements.campaignAutotargeting.forEach((input) => {
  input.addEventListener("change", () => {
    const group = selectedCampaignAdGroup();
    if (!group) return;
    group.autotargeting[input.dataset.autotargeting] = input.checked;
    markCampaignDirty();
  });
});
elements.addCampaignAd.addEventListener("click", addCampaignAd);
elements.campaignInputs.goal_strategy.addEventListener("change", () => {
  const clickStrategy =
    elements.campaignInputs.goal_strategy.value === "MAXIMIZE_CLICKS";
  if (clickStrategy) {
    elements.campaignInputs.payment_model.value = "CLICKS";
  }
  elements.campaignInputs.payment_model
    .querySelector('option[value="CONVERSIONS"]')
    .disabled = clickStrategy;
  markCampaignDirty();
});
elements.campaignInputs.landing_page.addEventListener("input", (event) => {
  const previous = state.campaignLandingPageValue;
  state.campaignAdGroups.forEach((group) => {
    group.ads.forEach((ad) => {
      if (ad.href === previous) ad.href = event.target.value;
    });
  });
  state.campaignLandingPageValue = event.target.value;
  if (selectedCampaignAd()) renderCampaignAdEditor();
});
window.addEventListener("beforeunload", (event) => {
  if (!state.campaignDirty) return;
  event.preventDefault();
});
elements.historyDecisionsTab.addEventListener("click", () => {
  showHistoryTab("decisions");
});
elements.historyOutcomesTab.addEventListener("click", () => {
  showHistoryTab("outcomes");
});
elements.historyExpand.addEventListener("click", () => {
  if (state.historyCompact) {
    loadHistoryPage(1);
  } else {
    collapseHistory();
  }
});
elements.historyPrevious.addEventListener("click", () => {
  loadHistoryPage(Math.max(1, state.historyPage - 1));
});
elements.historyNext.addEventListener("click", () => {
  loadHistoryPage(Math.min(state.historyPages, state.historyPage + 1));
});
elements.refreshEvidence.addEventListener("click", refreshEvidence);
elements.runFullEvidence.addEventListener("click", runFullEvidence);

fetch("/api/status")
  .then((response) => response.json())
  .then((payload) => {
    state.status = payload;
    state.statusError = false;
    elements.publicDemoBanner.hidden = payload.public_demo !== true;
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
loadCampaignDraft();
window.setInterval(() => refreshTestState(true), 1000);
