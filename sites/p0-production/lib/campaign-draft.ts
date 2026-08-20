const text = (value: unknown) => String(value ?? "").replace(/\s+/g, " ").trim();

export function buildCampaignNames(product: unknown, geography: unknown, qualifiedResult: unknown) {
  const offer = text(product) || "Новая кампания";
  const region = text(geography) || "Россия";
  const participation = /участ|participant/u.test(text(qualifiedResult).toLowerCase());
  return {
    campaignName: `${offer} · ${region}`,
    groupName: participation ? "Заявка на участие" : "Основной коммерческий спрос",
  };
}

export function isLegacySearchName(value: unknown) {
  return /\s·\sПоиск$/iu.test(text(value));
}
