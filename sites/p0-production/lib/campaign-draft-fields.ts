export const DIRECT_DRAFT_FIELD_REGISTRY_SCHEMA = "direct-v501-draft-field-registry-v1";

export type DraftFieldClassification =
  | "EDITABLE"
  | "FIXED_BY_STRATEGY"
  | "FIXED_BY_CAPABILITY"
  | "CONDITIONALLY_ELIGIBLE";

export type DraftFieldRegistryEntry = {
  pointer: string;
  input_name: string | null;
  object_kind: "CAMPAIGN" | "AD_GROUP" | "CRITERION" | "AD" | "ASSET";
  label: string;
  classification: DraftFieldClassification;
  editable: boolean;
  presence: "PRESENT" | "NOT_PRESENT";
  capability: string | null;
  normalization: "COLLAPSED_TEXT" | "UNORDERED_TEXT_ARRAY" | "EXACT_PROVIDER_VALUE";
  maximum_length: number | null;
  reason: string;
};

const field = (
  pointer: string,
  objectKind: DraftFieldRegistryEntry["object_kind"],
  label: string,
  classification: DraftFieldClassification,
  options: Partial<Omit<DraftFieldRegistryEntry, "pointer" | "object_kind" | "label" | "classification">> = {},
): DraftFieldRegistryEntry => ({
  pointer,
  input_name: null,
  object_kind: objectKind,
  label,
  classification,
  editable: classification === "EDITABLE",
  presence: "PRESENT",
  capability: null,
  normalization: "EXACT_PROVIDER_VALUE",
  maximum_length: null,
  reason: classification === "FIXED_BY_STRATEGY"
    ? "Значение зафиксировано утверждённой Campaign Strategy."
    : classification === "FIXED_BY_CAPABILITY"
      ? "Значение зафиксировано принятым Direct v501 capability profile."
      : classification === "CONDITIONALLY_ELIGIBLE"
        ? "Поле отсутствует: требуется отдельная official API и exact-account capability eligibility."
        : "Изменение публикуется в точную Direct projection.",
  ...options,
});

export const DIRECT_V501_DRAFT_FIELD_REGISTRY = Object.freeze({
  schema_version: DIRECT_DRAFT_FIELD_REGISTRY_SCHEMA,
  profile_id: "direct-v501-unified-search-explicit-text",
  profile_version: "1.0.0",
  api_version: "v501",
  fields: Object.freeze([
    field("/direct/campaign/Name", "CAMPAIGN", "Название кампании", "EDITABLE", { input_name: "campaign_name", normalization: "COLLAPSED_TEXT", maximum_length: 255 }),
    field("/direct/campaign/StartDate", "CAMPAIGN", "Дата начала", "FIXED_BY_STRATEGY"),
    field("/direct/campaign/EndDate", "CAMPAIGN", "Дата окончания", "FIXED_BY_STRATEGY"),
    field("/direct/campaign/UnifiedCampaign/BiddingStrategy/Search/BiddingStrategyType", "CAMPAIGN", "Стратегия поиска", "FIXED_BY_CAPABILITY"),
    field("/direct/campaign/UnifiedCampaign/BiddingStrategy/Search/PlacementTypes/SearchResults", "CAMPAIGN", "Показы в результатах поиска", "FIXED_BY_CAPABILITY"),
    field("/direct/campaign/UnifiedCampaign/BiddingStrategy/Search/PlacementTypes/ProductGallery", "CAMPAIGN", "Товарная галерея", "FIXED_BY_CAPABILITY", { capability: "PRODUCT_GALLERY" }),
    field("/direct/campaign/UnifiedCampaign/BiddingStrategy/Search/WbMaximumClicks/WeeklySpendLimit", "CAMPAIGN", "Недельный лимит расходов, micros", "FIXED_BY_STRATEGY"),
    field("/direct/campaign/UnifiedCampaign/BiddingStrategy/Search/WbMaximumClicks/BidCeiling", "CAMPAIGN", "Ограничение ставки, micros", "FIXED_BY_STRATEGY", { reason: "Технически нормализовано из утверждённого недельного бюджета." }),
    field("/direct/campaign/UnifiedCampaign/BiddingStrategy/Network/BiddingStrategyType", "CAMPAIGN", "Стратегия сетей", "FIXED_BY_CAPABILITY", { capability: "NETWORK" }),
    field("/direct/ad_group/Name", "AD_GROUP", "Название группы", "EDITABLE", { input_name: "group_name", normalization: "COLLAPSED_TEXT", maximum_length: 255 }),
    field("/direct/ad_group/RegionIds", "AD_GROUP", "Регионы", "FIXED_BY_STRATEGY", { normalization: "UNORDERED_TEXT_ARRAY" }),
    field("/direct/ad_group/NegativeKeywords/Items", "AD_GROUP", "Минус-фразы", "EDITABLE", { input_name: "negative_keywords", normalization: "UNORDERED_TEXT_ARRAY", maximum_length: 1_000 }),
    field("/direct/ad_group/UnifiedAdGroup/OfferRetargeting", "AD_GROUP", "Ретаргетинг офферов", "FIXED_BY_CAPABILITY"),
    field("/direct/keyword/Keyword", "CRITERION", "Ключевая фраза", "EDITABLE", { input_name: "keyword", normalization: "COLLAPSED_TEXT", maximum_length: 4_096 }),
    field("/direct/keyword/AutotargetingSettings", "CRITERION", "Настройки автотаргетинга", "CONDITIONALLY_ELIGIBLE", { presence: "NOT_PRESENT", capability: "AUTOTARGETING" }),
    field("/direct/ad/TextAd/Title", "AD", "Заголовок объявления", "EDITABLE", { input_name: "ad_title", normalization: "COLLAPSED_TEXT", maximum_length: 56 }),
    field("/direct/ad/TextAd/Text", "AD", "Текст объявления", "EDITABLE", { input_name: "ad_text", normalization: "COLLAPSED_TEXT", maximum_length: 81 }),
    field("/direct/ad/TextAd/Href", "AD", "Посадочная страница", "FIXED_BY_STRATEGY"),
    field("/direct/ad/TextAd/Mobile", "AD", "Мобильное объявление", "FIXED_BY_CAPABILITY"),
    field("/direct/ad/TextAd/SitelinkSetId", "ASSET", "Привязка набора быстрых ссылок", "CONDITIONALLY_ELIGIBLE", { presence: "NOT_PRESENT", capability: "SITELINKS" }),
    field("/direct/sitelink_sets", "ASSET", "Наборы быстрых ссылок", "CONDITIONALLY_ELIGIBLE", { presence: "NOT_PRESENT", capability: "SITELINKS" }),
  ] satisfies DraftFieldRegistryEntry[]),
});

const editableFields = DIRECT_V501_DRAFT_FIELD_REGISTRY.fields.filter((item) => item.editable && item.input_name);

export function editableDraftFieldNames() {
  return editableFields.map((item) => String(item.input_name));
}

export function editableDraftPointer(inputName: string) {
  return editableFields.find((item) => item.input_name === inputName)?.pointer ?? null;
}

export function projectionFieldValue(projection: unknown, pointer: string): unknown {
  if (!pointer.startsWith("/")) return undefined;
  return pointer.slice(1).split("/").reduce<unknown>((value, segment) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
    return (value as Record<string, unknown>)[segment.replaceAll("~1", "/").replaceAll("~0", "~")];
  }, projection);
}

function inputError(code: string, message: string): never {
  const error = new Error(message) as Error & { code: string };
  error.code = code;
  throw error;
}

function normalizedText(value: unknown, label: string, maximum: number) {
  const normalized = String(value ?? "").normalize("NFKC").replace(/\s+/gu, " ").trim();
  if (!normalized) inputError("P0_INPUT_REQUIRED", `${label} не заполнено.`);
  if (normalized.length > maximum) inputError("P0_INPUT_TOO_LONG", `${label}: максимум ${maximum} символов.`);
  return normalized;
}

export function normalizeDraftFieldInput(value: Record<string, unknown>) {
  const accepted = new Set(["draft_id", ...editableDraftFieldNames()]);
  const unsupported = Object.keys(value).find((name) => !accepted.has(name));
  if (unsupported) inputError(
    "P0_DRAFT_FIELD_UNSUPPORTED",
    `Campaign Draft field ${unsupported} is not editable in the current exact projection contract and was not applied.`,
  );
  const result: Record<string, string> = {
    draft_id: normalizedText(value.draft_id, "Campaign Draft", 255),
  };
  for (const registryField of editableFields) {
    const inputName = String(registryField.input_name);
    result[inputName] = normalizedText(value[inputName], registryField.label, Number(registryField.maximum_length));
  }
  return result as {
    draft_id: string;
    campaign_name: string;
    group_name: string;
    negative_keywords: string;
    keyword: string;
    ad_title: string;
    ad_text: string;
  };
}

export function nextDraftRevisionId(draftId: string, previousRevisionId: string) {
  const escaped = draftId.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
  const match = new RegExp(`^${escaped}-r(\\d+)$`, "u").exec(previousRevisionId);
  if (!match) throw new Error("Campaign Draft revision lineage is invalid.");
  const revision = Number(match[1]);
  if (!Number.isSafeInteger(revision) || revision < 1) throw new Error("Campaign Draft revision lineage is invalid.");
  return `${draftId}-r${revision + 1}`;
}
