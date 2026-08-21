import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const clientSource = await readFile(new URL("../app/P0Client.tsx", import.meta.url), "utf8");
const disclosureSource = await readFile(new URL("../app/RecommendationSetDisclosure.tsx", import.meta.url), "utf8");
const styles = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");

test("Campaign Canvas exposes deterministic variant/evidence filters, rank/score sort and hidden Draft discovery", () => {
  assert.match(clientSource, /aria-label="Фильтр variant"/u);
  assert.match(clientSource, /aria-label="Фильтр evidence status"/u);
  assert.match(clientSource, /Semantic rank/u);
  assert.match(clientSource, /Comparative score/u);
  assert.match(clientSource, /Показать hidden Drafts с suppression reasons/u);
  assert.match(clientSource, /filterAndSortCampaignDrafts/u);
  assert.match(clientSource, /Проверить active playbook/u);
  assert.match(clientSource, /apply\("recalculate_recommendations"\)/u);
  assert.match(disclosureSource, /Hidden candidate audit/u);
  assert.match(disclosureSource, /reason_code/u);
  assert.match(disclosureSource, /Persisted suppression reason missing · FAIL CLOSED/u);
});

test("right Campaign Draft drawer has a keyboard dialog, focus trap, Escape close and server-derived field registry", () => {
  assert.match(clientSource, /role="dialog" aria-modal="true"/u);
  assert.match(clientSource, /aria-label="Закрыть drawer"/u);
  assert.match(clientSource, /event\.key === "Escape"/u);
  assert.match(clientSource, /event\.key !== "Tab"/u);
  assert.match(clientSource, /querySelectorAll<HTMLElement>/u);
  assert.match(clientSource, /DraftFieldRegistryDisclosure registry=\{recommendationSet\.field_registry\}/u);
  assert.match(disclosureSource, /field\.editable === true/u);
  assert.match(disclosureSource, /NOT_PRESENT/u);
});

test("1920 desktop layout constrains the drawer and all projection content to minmax-zero columns", () => {
  assert.match(styles, /\.campaign-drawer \{[^}]*width: min\(760px, calc\(100vw - 80px\)\)/u);
  assert.match(styles, /\.drawer-scroll \{[^}]*min-width: 0[^}]*overflow-y: auto/u);
  assert.match(styles, /\.draft-field-registry label \{[^}]*grid-template-columns: minmax\(0, 1fr\)/u);
  assert.match(styles, /\.draft-card-shell \{[^}]*min-width: 0/u);
});

test("blocked review, normalization feedback and playbook recalculation remain visibly distinct from publish readiness", () => {
  assert.match(clientSource, /Review доступен · Publish readiness заблокирована/u);
  assert.match(clientSource, /Сохранить review-правки без publish readiness/u);
  assert.match(disclosureSource, /draft-edit-feedback no-change/u);
  assert.match(clientSource, /Рекомендация пересчитана/u);
  assert.match(clientSource, /previous_normalized_value/u);
  assert.doesNotMatch(clientSource, /evaluator.trace|chain.of.thought/iu);
});
