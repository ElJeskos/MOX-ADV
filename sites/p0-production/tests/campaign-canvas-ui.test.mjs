import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const clientSource = await readFile(new URL("../app/P0Client.tsx", import.meta.url), "utf8");
const disclosureSource = await readFile(new URL("../app/RecommendationSetDisclosure.tsx", import.meta.url), "utf8");
const styles = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");

test("Campaign Canvas exposes deterministic variant/evidence filters, rank/score sort and hidden Draft discovery", () => {
  assert.match(clientSource, /aria-label="Фильтр вариантов"/u);
  assert.match(clientSource, /aria-label="Фильтр состояния доказательств"/u);
  assert.match(clientSource, /Смысловое место/u);
  assert.match(clientSource, /Сравнительная оценка/u);
  assert.match(clientSource, /Показать скрытые черновики с причинами скрытия/u);
  assert.match(clientSource, /filterAndSortCampaignDrafts/u);
  assert.match(clientSource, /Проверить действующую сводку правил/u);
  assert.match(clientSource, /apply\("recalculate_recommendations"\)/u);
  assert.match(disclosureSource, /Проверка скрытых кандидатов/u);
  assert.match(disclosureSource, /reason_code/u);
  assert.match(disclosureSource, /Сохранённая причина отсутствует · безопасно заблокировано/u);
});

test("right Campaign Draft drawer has a keyboard dialog, focus trap, Escape close and server-derived field registry", () => {
  assert.match(clientSource, /role="dialog" aria-modal="true"/u);
  assert.match(clientSource, /aria-label="Закрыть панель"/u);
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
  assert.match(clientSource, /Проверка доступна · готовность к публикации заблокирована/u);
  assert.match(clientSource, /Сохранить проверочные правки без готовности к публикации/u);
  assert.match(disclosureSource, /draft-edit-feedback no-change/u);
  assert.match(clientSource, /Рекомендация пересчитана/u);
  assert.match(clientSource, /previous_normalized_value/u);
  assert.doesNotMatch(clientSource, /evaluator.trace|chain.of.thought/iu);
});

test("card shortlist controls, persistent exact footer and package Gate disclose independent non-transactional execution", () => {
  assert.match(clientSource, /Исключить из списка/u);
  assert.match(clientSource, /Вернуть в список/u);
  assert.match(clientSource, /Добавить в список/u);
  assert.match(clientSource, /disabled_reason/u);
  assert.match(clientSource, /aria-label="Постоянная сводка списка"/u);
  assert.match(clientSource, /draft_revision_id/u);
  assert.match(clientSource, /publish_fingerprint/u);
  assert.match(clientSource, /Создать проверку пакета/u);
  assert.match(clientSource, /Открыть текущую проверку пакета/u);
  assert.match(clientSource, /payload\.state\.package_review \? openReview\(\) : void apply\("review_package"\)/u);
  assert.match(clientSource, /Точная неизменяемая проверка пакета/u);
  assert.match(clientSource, /Снимок аналитических доказательств/u);
  assert.match(clientSource, /Привязка аккаунта Яндекс Директа/u);
  assert.match(clientSource, /Профиль возможностей/u);
  assert.match(clientSource, /Подтверждаю точный пакет и независимое исполнение кампаний/u);
  assert.match(clientSource, /CONFIRM_EXACT_SHORTLIST_PACKAGE/u);
  assert.match(clientSource, /Подтверждение не выполняет записи в Яндекс Директ/u);
  assert.match(clientSource, /Кампании исполняются и оцениваются независимо/u);
  assert.match(styles, /\.shortlist-footer \{[^}]*position: sticky/u);
  assert.match(styles, /\.package-review \{[^}]*min-width: 0/u);
  assert.doesNotMatch(clientSource, /apply\("confirm_creation"/u);
});

test("rejected package items expose focused correction, renewed review and separate PASS_AFTER_CORRECTION accounting", () => {
  assert.match(clientSource, /Исправить отклонённый черновик/u);
  assert.match(clientSource, /start_package_correction/u);
  assert.match(clientSource, /Точечное исправление/u);
  assert.match(clientSource, /Пояснение состояния/u);
  assert.match(clientSource, /save_package_correction/u);
  assert.match(clientSource, /review_package_correction/u);
  assert.match(clientSource, /confirm_package_correction/u);
  assert.match(clientSource, /resubmit_package_correction/u);
  assert.match(clientSource, /poll_package_correction_moderation/u);
  assert.match(clientSource, /Первичный вердикт пакета/u);
  assert.match(clientSource, /Ход исправления/u);
  assert.match(clientSource, /Итог исправленной редакции/u);
  assert.match(clientSource, /Подготовленный пакет исправленного контрольного решения человека/u);
  assert.match(clientSource, /decisionPacket\.recommendation/u);
  assert.match(clientSource, /decisionPacket\.confidence/u);
  assert.match(clientSource, /Альтернативы/u);
  assert.match(clientSource, /Последствия/u);
  assert.match(clientSource, /PASS_AFTER_CORRECTION/u);
});

test("confirmation renders independent durable item progress and dispatches only the exact Gate", () => {
  assert.match(clientSource, /Исполнить подтверждённый пакет/u);
  assert.match(clientSource, /apply\("dispatch_package"/u);
  assert.match(clientSource, /package_id: gate\.package_id/u);
  assert.match(clientSource, /gate_id: gate\.gate_id/u);
  assert.match(clientSource, /aria-label="Исполнения кампаний пакета"/u);
  assert.match(clientSource, /Проверка/u);
  assert.match(clientSource, /Создание/u);
  assert.match(clientSource, /Остановка/u);
  assert.match(clientSource, /Дочерние объекты/u);
  assert.match(clientSource, /Обратная проверка/u);
  assert.match(clientSource, /Модерация/u);
  assert.match(clientSource, /item\.ownership/u);
  assert.match(clientSource, /item\.provider_issues/u);
  assert.match(clientSource, /Вердикт пакета/u);
  assert.match(clientSource, /next_poll_at/u);
  assert.match(clientSource, /poll_package_moderation/u);
  assert.match(clientSource, /status_clarification/u);
  assert.match(clientSource, /item\.accountability\.direct_accepted/u);
  assert.match(clientSource, /item\.containment/u);
  assert.match(styles, /\.package-executions \{[^}]*min-width: 0/u);
  assert.match(styles, /\.execution-progress \{[^}]*grid-template-columns: repeat\(6, minmax\(0, 1fr\)\)/u);
});
