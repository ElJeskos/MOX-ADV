import { cleanText } from "./text.ts";

export const STRATEGY_QUESTIONNAIRE_SCHEMA = "p0-strategy-questionnaire-v1";
export const STRATEGY_QUESTIONNAIRE_CONTRACT_VERSION = "1.0.0";
export const CAMPAIGN_STRATEGY_SCHEMA = "p0-campaign-strategy-v1";

export const STRATEGY_FIELD_ORDER = [
  "business_goal",
  "advertised_offer",
  "target_audience",
  "qualified_result",
  "exclusions",
  "geography",
  "period",
  "landing_page",
  "weekly_budget",
  "target_result_cost",
  "core_message",
] as const;

export type StrategyFieldId = typeof STRATEGY_FIELD_ORDER[number];
export type StrategySourceCategory = "сайт" | "Директ" | "Метрика" | "аналитика агента" | "решение владельца";
export type StrategyFieldStatus = "уверенно" | "нужно проверить" | "нет данных";
export type StrategyPeriod = { start_date: string; end_date: string };
export type StrategyAnswerValue = string | number | StrategyPeriod;

export type PreparedStrategyDecision = {
  required: true;
  question: string;
  consequences: string[];
};

export type StrategyQuestionnaireField = {
  field_id: StrategyFieldId;
  recommended_value: StrategyAnswerValue | null;
  explanation: string;
  source_category: StrategySourceCategory;
  status: StrategyFieldStatus;
  prepared_decision: PreparedStrategyDecision | null;
};

export type StrategyQuestionnaire = {
  schema_version: typeof STRATEGY_QUESTIONNAIRE_SCHEMA;
  contract_version: typeof STRATEGY_QUESTIONNAIRE_CONTRACT_VERSION;
  questionnaire_id: string;
  generated_at: string;
  context_revision_id: string;
  context_material_fingerprint: string;
  analytics_evidence_snapshot_id: string;
  fields: StrategyQuestionnaireField[];
};

export type CampaignStrategyRevision = {
  schema_version: typeof CAMPAIGN_STRATEGY_SCHEMA;
  strategy_revision_id: string;
  questionnaire_id: string;
  questionnaire_contract_version: string;
  context_revision_id: string;
  context_material_fingerprint: string;
  analytics_evidence_snapshot_id: string;
  answers: Array<{ field_id: StrategyFieldId; value: StrategyAnswerValue }>;
  material_fingerprint: string;
  approved_at: string;
  approved_by: "OWNER";
  approval_command: "APPROVE_CAMPAIGN_STRATEGY";
  lineage: { previous_strategy_revision_id: string | null };
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function normalizedText(value: unknown, maximum = 2_000) {
  return cleanText(String(value ?? "").normalize("NFKC"), maximum);
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonicalize(item)]),
  );
}

async function sha256(value: unknown) {
  const bytes = new TextEncoder().encode(JSON.stringify(canonicalize(value)));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return `sha256:${[...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("")}`;
}

function modelRecommendation(
  model: Record<string, unknown>,
  fieldId: "product" | "audience" | "qualified_result" | "exclusions" | "value",
) {
  const value = normalizedText(model[fieldId]);
  const evidence = record(record(model.field_evidence)[fieldId]);
  const confidence = normalizedText(evidence.confidence, 100);
  const sourceCategory: StrategySourceCategory = evidence.owner_edited === true
    ? "решение владельца"
    : normalizedText(evidence.source_url)
      ? "сайт"
      : evidence.owner_confirmed === true
        ? "решение владельца"
        : "аналитика агента";
  const status: StrategyFieldStatus = !value
    ? "нет данных"
    : ["HIGH", "OWNER_CONFIRMED"].includes(confidence)
      ? "уверенно"
      : "нужно проверить";
  return { value: value || null, sourceCategory, status };
}

function missingDecision(question: string, consequences: string[]): PreparedStrategyDecision {
  return { required: true, question, consequences };
}

function preparedField(
  fieldId: StrategyFieldId,
  explanation: string,
  question: string,
  consequences: string[],
): StrategyQuestionnaireField {
  return {
    field_id: fieldId,
    recommended_value: null,
    explanation,
    source_category: "решение владельца",
    status: "нет данных",
    prepared_decision: missingDecision(question, consequences),
  };
}

export async function buildStrategyQuestionnaire({
  contextState,
  model,
  analyticsEvidence,
  generatedAt,
}: {
  contextState: Record<string, unknown>;
  model: Record<string, unknown>;
  analyticsEvidence: Record<string, unknown>;
  generatedAt: string;
}): Promise<StrategyQuestionnaire> {
  const contextDecision = record(contextState.business_goal_decision);
  const contextFacts = record(contextState.facts);
  const siteFacts = record(contextFacts.site);
  const goal = normalizedText(contextDecision.value, 500);
  const offer = modelRecommendation(model, "product");
  const audience = modelRecommendation(model, "audience");
  const qualifiedResult = modelRecommendation(model, "qualified_result");
  const exclusions = modelRecommendation(model, "exclusions");
  const message = modelRecommendation(model, "value");
  const landing = normalizedText(siteFacts.url, 2_000);
  const minimumWeeklyBudget = Number(record(contextFacts.direct).minimum_weekly_budget_rub);
  const minimumBudgetConsequence = Number.isFinite(minimumWeeklyBudget) && minimumWeeklyBudget > 0
    ? `Direct допускает не менее ${minimumWeeklyBudget} ₽ в неделю, но этот технический минимум не является business budget.`
    : "До решения нельзя вычислить допустимую недельную экспозицию.";

  const fields: StrategyQuestionnaireField[] = [
    {
      field_id: "business_goal",
      recommended_value: goal || null,
      explanation: "Цель уже явно подтверждена владельцем в Context.",
      source_category: "решение владельца",
      status: goal ? "уверенно" : "нет данных",
      prepared_decision: goal ? null : missingDecision("Какой бизнес-результат должна поддержать кампания?", ["Без цели Recommendation Set не имеет бизнес-якоря."]),
    },
    {
      field_id: "advertised_offer",
      recommended_value: offer.value,
      explanation: "Предложение нормализовано из подтверждённой модели бизнеса.",
      source_category: offer.sourceCategory,
      status: offer.status,
      prepared_decision: offer.value ? null : missingDecision("Какое реальное предложение рекламировать?", ["Без предложения невозможно подготовить точные объявления."]),
    },
    {
      field_id: "target_audience",
      recommended_value: audience.value,
      explanation: "Аудитория перенесена из подтверждённых Model evidence.",
      source_category: audience.sourceCategory,
      status: audience.status,
      prepared_decision: audience.value ? null : missingDecision("Кто принимает решение о целевом действии?", ["Без аудитории нельзя оценить соответствие сообщения."]),
    },
    {
      field_id: "qualified_result",
      recommended_value: qualifiedResult.value,
      explanation: "Результат описывает подтверждаемое квалифицированное действие.",
      source_category: qualifiedResult.sourceCategory,
      status: qualifiedResult.status,
      prepared_decision: qualifiedResult.value ? null : missingDecision("Какое действие считать квалифицированным результатом?", ["Без определения результата нельзя связать кампанию с измерением."]),
    },
    {
      field_id: "exclusions",
      recommended_value: exclusions.value,
      explanation: "Исключения отделяют нецелевые обращения от квалифицированного результата.",
      source_category: exclusions.sourceCategory,
      status: exclusions.status,
      prepared_decision: exclusions.value ? null : missingDecision("Какие обращения или аудитории исключить?", ["Без явного решения нецелевой спрос может попасть в Drafts."]),
    },
    preparedField(
      "geography",
      "Persisted evidence не доказывает business-owned территорию показа.",
      "В какой географии разрешён показ?",
      ["География меняет доступный спрос, стоимость и Direct projection."],
    ),
    preparedField(
      "period",
      "Evidence не задаёт владельцу допустимое рекламное окно.",
      "Когда кампания может начинаться и заканчиваться?",
      ["Период ограничивает срок внешней экспозиции и сезонную интерпретацию evidence."],
    ),
    {
      field_id: "landing_page",
      recommended_value: landing || null,
      explanation: "Использован исследованный first-party HTTPS URL из persisted Context.",
      source_category: "сайт",
      status: landing ? "уверенно" : "нет данных",
      prepared_decision: landing ? null : missingDecision("На какую first-party страницу вести трафик?", ["Без URL Draft нельзя безопасно опубликовать."]),
    },
    preparedField(
      "weekly_budget",
      "Недельный бюджет является business-owned пределом, а не выводом агента.",
      "Какую максимальную сумму можно расходовать за неделю?",
      [minimumBudgetConsequence, "Без суммы approval остаётся заблокированным."],
    ),
    preparedField(
      "target_result_cost",
      "Pre-launch cost evidence не предоставляет владельцу право установить целевую стоимость результата.",
      "Какова предельная стоимость одного квалифицированного результата?",
      ["Значение определяет экономическую оценку Drafts; без него approval остаётся заблокированным."],
    ),
    {
      field_id: "core_message",
      recommended_value: message.value,
      explanation: "Сообщение основано на подтверждённой first-party ценности.",
      source_category: message.sourceCategory,
      status: message.status,
      prepared_decision: message.value ? null : missingDecision("Какое доказуемое основное сообщение использовать?", ["Без сообщения невозможно сформировать рекламный текст."]),
    },
  ];

  const contextRevisionId = normalizedText(contextState.context_revision_id, 255);
  const contextMaterialFingerprint = normalizedText(contextState.material_fingerprint, 255);
  const snapshotId = normalizedText(analyticsEvidence.snapshot_id, 255);
  if (!contextRevisionId || !contextMaterialFingerprint || !snapshotId) {
    throw new Error("Strategy questionnaire требует точные Context и Analytics Evidence Snapshot lineage.");
  }
  const questionnaireId = await sha256({
    contract_version: STRATEGY_QUESTIONNAIRE_CONTRACT_VERSION,
    context_revision_id: contextRevisionId,
    context_material_fingerprint: contextMaterialFingerprint,
    analytics_evidence_snapshot_id: snapshotId,
    fields,
  });
  return {
    schema_version: STRATEGY_QUESTIONNAIRE_SCHEMA,
    contract_version: STRATEGY_QUESTIONNAIRE_CONTRACT_VERSION,
    questionnaire_id: `strategy-questionnaire:${questionnaireId.slice("sha256:".length, "sha256:".length + 24)}`,
    generated_at: generatedAt,
    context_revision_id: contextRevisionId,
    context_material_fingerprint: contextMaterialFingerprint,
    analytics_evidence_snapshot_id: snapshotId,
    fields,
  };
}

function answerRecord(value: unknown) {
  return record(value);
}

export function normalizeStrategyAnswers(
  value: unknown,
  sanitize: (value: unknown, maximum: number) => string = (item, maximum) => normalizedText(item, maximum),
) {
  const input = answerRecord(value);
  const textAnswer = (fieldId: StrategyFieldId, maximum = 2_000) => sanitize(input[fieldId], maximum);
  const period = answerRecord(input.period);
  const normalized: Record<StrategyFieldId, StrategyAnswerValue | null> = {
    business_goal: textAnswer("business_goal", 500) || null,
    advertised_offer: textAnswer("advertised_offer") || null,
    target_audience: textAnswer("target_audience") || null,
    qualified_result: textAnswer("qualified_result") || null,
    exclusions: textAnswer("exclusions") || null,
    geography: textAnswer("geography", 255) || null,
    period: {
      start_date: normalizedText(period.start_date, 20),
      end_date: normalizedText(period.end_date, 20),
    },
    landing_page: textAnswer("landing_page", 2_000) || null,
    weekly_budget: Number(input.weekly_budget),
    target_result_cost: Number(input.target_result_cost),
    core_message: textAnswer("core_message") || null,
  };
  const normalizedPeriod = normalized.period as StrategyPeriod;
  if (!normalizedPeriod.start_date || !normalizedPeriod.end_date) normalized.period = null;
  if (!Number.isSafeInteger(normalized.weekly_budget) || Number(normalized.weekly_budget) <= 0) normalized.weekly_budget = null;
  if (!Number.isSafeInteger(normalized.target_result_cost) || Number(normalized.target_result_cost) <= 0) normalized.target_result_cost = null;
  return normalized;
}

export function missingStrategyDecisions(answers: Record<StrategyFieldId, StrategyAnswerValue | null>) {
  return STRATEGY_FIELD_ORDER.filter((fieldId) => answers[fieldId] === null);
}

export async function strategyAnswersFingerprint(answers: Record<StrategyFieldId, StrategyAnswerValue | null>) {
  return sha256(STRATEGY_FIELD_ORDER.map((fieldId) => ({ field_id: fieldId, value: answers[fieldId] })));
}

const LEGACY_FIELDS: Record<StrategyFieldId, string> = {
  business_goal: "goal",
  advertised_offer: "advertised_offer",
  target_audience: "target_audience",
  qualified_result: "qualified_result",
  exclusions: "exclusions",
  geography: "geography",
  period: "period",
  landing_page: "landing_page",
  weekly_budget: "weekly_budget_rub",
  target_result_cost: "target_cpa_rub",
  core_message: "message",
};

export function strategyAnswerValue(strategy: Record<string, unknown>, fieldId: StrategyFieldId): unknown {
  const answers = Array.isArray(strategy.answers) ? strategy.answers as Array<Record<string, unknown>> : [];
  const answer = answers.find((item) => item.field_id === fieldId);
  if (answer) return answer.value;
  if (fieldId === "period") {
    return { start_date: strategy.period_start, end_date: strategy.period_end };
  }
  return strategy[LEGACY_FIELDS[fieldId]];
}

export function strategyPeriod(strategy: Record<string, unknown>): StrategyPeriod {
  const value = record(strategyAnswerValue(strategy, "period"));
  return {
    start_date: normalizedText(value.start_date, 20),
    end_date: normalizedText(value.end_date, 20),
  };
}
