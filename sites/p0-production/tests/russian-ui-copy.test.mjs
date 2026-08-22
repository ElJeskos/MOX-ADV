import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { localizedText, machineLabel } from "../app/ui-copy.ts";

const uiSources = (await Promise.all([
  "../app/P0Client.tsx",
  "../app/RecommendationSetDisclosure.tsx",
  "../app/MarketEvidenceDisclosure.tsx",
  "../app/page.tsx",
  "../app/layout.tsx",
].map((path) => readFile(new URL(path, import.meta.url), "utf8")))).join("\n");

const obsoleteVisiblePhrases = [
  "Production Module",
  "PRODUCTION MODULE",
  "production-контекст",
  "Official scoped market evidence",
  "Qualified pre-launch cost",
  "Business model",
  "LANDING PAGE · ADVISORY ONLY",
  "ADVISORY · NON-BLOCKING",
  "Campaign Canvas",
  "Показать hidden Drafts",
  "Review доступен · Publish readiness",
  "Исключить из shortlist",
  "Создать package review",
  "Human Decision Gate",
  "Package campaign executions",
  "Focused correction",
  "Provider rejection correction",
  "Initial package verdict",
  "Correction progress",
  "Corrected terminal outcome",
  "Prepared corrected Human Decision Gate packet",
  "External writes performed",
];

test("видимые тексты интерфейса не содержат прежнюю английскую терминологию", () => {
  for (const phrase of obsoleteVisiblePhrases) {
    assert.equal(uiSources.includes(phrase), false, `Найден непереведённый текст: ${phrase}`);
  }
});

test("машинные состояния и серверные пояснения получают русское представление", () => {
  assert.equal(machineLabel("PASS_AFTER_CORRECTION"), "Пройдено после исправления");
  assert.equal(machineLabel("REJECTED_NEEDS_EDIT"), "Отклонено — требуется исправление");
  assert.equal(machineLabel("CONFIRMED_SUSPENDED"), "Остановка подтверждена");
  assert.equal(
    localizedText("Campaign Draft requires persisted official API evidence and exact account binding."),
    "Черновик кампании требует сохранённых доказательств официального API и точной привязки аккаунта.",
  );
});
