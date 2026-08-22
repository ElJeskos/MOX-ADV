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
  assert.match(clientSource, /recommendationSet\.field_registry\?\.fields/u);
  assert.match(clientSource, /field\.editable === true && typeof field\.input_name === "string"/u);
  assert.doesNotMatch(clientSource, /\["campaign_name", "group_name", "negative_keywords", "keyword", "ad_title", "ad_text"\]/u);
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

test("card shortlist controls, persistent exact footer and package Gate disclose independent non-transactional execution", () => {
  assert.match(clientSource, /Исключить из shortlist/u);
  assert.match(clientSource, /Вернуть в shortlist/u);
  assert.match(clientSource, /Добавить в shortlist/u);
  assert.match(clientSource, /disabled_reason/u);
  assert.match(clientSource, /aria-label="Persistent shortlist summary"/u);
  assert.match(clientSource, /draft_revision_id/u);
  assert.match(clientSource, /publish_fingerprint/u);
  assert.match(clientSource, /Создать package review/u);
  assert.match(clientSource, /Открыть current package review/u);
  assert.match(clientSource, /payload\.state\.package_review \? openReview\(\) : void apply\("review_package"\)/u);
  assert.match(clientSource, /Точный immutable package review/u);
  assert.match(clientSource, /Analytics Evidence Snapshot/u);
  assert.match(clientSource, /Direct account binding/u);
  assert.match(clientSource, /Capability profile/u);
  assert.match(clientSource, /Подтверждаю точный пакет и независимое исполнение кампаний/u);
  assert.match(clientSource, /CONFIRM_EXACT_SHORTLIST_PACKAGE/u);
  assert.match(clientSource, /Confirmation не выполняет Direct writes/u);
  assert.match(clientSource, /Кампании исполняются и оцениваются независимо/u);
  assert.match(styles, /\.shortlist-footer \{[^}]*position: sticky/u);
  assert.match(styles, /\.package-review \{[^}]*min-width: 0/u);
  assert.doesNotMatch(clientSource, /apply\("confirm_creation"/u);
});

test("rejected package items expose focused correction, renewed review and separate PASS_AFTER_CORRECTION accounting", () => {
  assert.match(clientSource, /Исправить отклонённый Draft/u);
  assert.match(clientSource, /start_package_correction/u);
  assert.match(clientSource, /Focused correction/u);
  assert.match(clientSource, /StatusClarification/u);
  assert.match(clientSource, /save_package_correction/u);
  assert.match(clientSource, /review_package_correction/u);
  assert.match(clientSource, /confirm_package_correction/u);
  assert.match(clientSource, /resubmit_package_correction/u);
  assert.match(clientSource, /poll_package_correction_moderation/u);
  assert.match(clientSource, /Initial package verdict/u);
  assert.match(clientSource, /Correction progress/u);
  assert.match(clientSource, /Corrected terminal outcome/u);
  assert.match(clientSource, /PASS_AFTER_CORRECTION/u);
});

test("confirmation renders independent durable item progress and dispatches only the exact Gate", () => {
  assert.match(clientSource, /Исполнить подтверждённый пакет/u);
  assert.match(clientSource, /apply\("dispatch_package"/u);
  assert.match(clientSource, /package_id: gate\.package_id/u);
  assert.match(clientSource, /gate_id: gate\.gate_id/u);
  assert.match(clientSource, /aria-label="Package campaign executions"/u);
  assert.match(clientSource, /Validation/u);
  assert.match(clientSource, /Creation/u);
  assert.match(clientSource, /Suspension/u);
  assert.match(clientSource, /Child graph/u);
  assert.match(clientSource, /Readback/u);
  assert.match(clientSource, /Moderation/u);
  assert.match(clientSource, /item\.ownership/u);
  assert.match(clientSource, /item\.provider_issues/u);
  assert.match(clientSource, /Package verdict/u);
  assert.match(clientSource, /next_poll_at/u);
  assert.match(clientSource, /poll_package_moderation/u);
  assert.match(clientSource, /status_clarification/u);
  assert.match(clientSource, /item\.accountability\.direct_accepted/u);
  assert.match(clientSource, /item\.containment/u);
  assert.match(styles, /\.package-executions \{[^}]*min-width: 0/u);
  assert.match(styles, /\.execution-progress \{[^}]*grid-template-columns: repeat\(6, minmax\(0, 1fr\)\)/u);
});
