import type { DirectProjection } from "./direct-write";
import { strategyAnswerValue, strategyPeriod } from "./campaign-strategy.ts";

const text = (value: unknown) => String(value ?? "").replace(/\s+/g, " ").trim();

const REGION_IDS: Record<string, number> = {
  "россия": 225,
  "москва": 213,
  "санкт-петербург": 2,
};

export function buildCampaignNames(product: unknown, _geography: unknown, qualifiedResult: unknown) {
  const offer = text(product) || "Новая кампания";
  const participation = /участ|participant/u.test(text(qualifiedResult).toLowerCase());
  return {
    campaignName: offer,
    groupName: participation ? "Заявка на участие" : "Основной коммерческий спрос",
  };
}

export function isLegacySearchName(value: unknown) {
  return /\s·\sПоиск$/iu.test(text(value));
}

export function isCampaignNameWithGeography(value: unknown, geography: unknown) {
  const region = text(geography);
  return Boolean(region) && text(value).endsWith(` · ${region}`);
}

export function hasDuplicateCampaignName(existingNames: unknown[], candidate: unknown) {
  const normalizedCandidate = text(candidate).toLowerCase();
  return existingNames.some((name) => text(name).toLowerCase() === normalizedCandidate);
}

export function buildPublishProjection(
  model: Record<string, unknown>,
  strategy: Record<string, unknown>,
  draft: Record<string, unknown>,
): DirectProjection {
  const geography = text(strategyAnswerValue(strategy, "geography")).toLowerCase();
  const regionId = REGION_IDS[geography];
  if (!regionId) throw new Error("Выбранная география пока не поддерживается production P0.");
  const weeklyBudget = Number(strategyAnswerValue(strategy, "weekly_budget"));
  if (!Number.isSafeInteger(weeklyBudget) || weeklyBudget < 1) {
    throw new Error("Недельный бюджет некорректен.");
  }
  const bidCeilingRub = Math.min(Math.max(Math.floor(weeklyBudget / 100), 100), 3_000);
  const negativeKeywords = text(draft.negative_keywords)
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (!negativeKeywords.length) throw new Error("Нужна хотя бы одна минус-фраза.");
  const period = strategyPeriod(strategy);

  return {
    schema_version: "p0-direct-projection-v3",
    lineage: {
      strategy_revision_id: draft.strategy_revision_id,
      draft_id: draft.draft_id,
      capability_profile_id: draft.capability_profile_id,
    },
    business: {
      product: strategyAnswerValue(strategy, "advertised_offer") || model.product,
      audience: strategyAnswerValue(strategy, "target_audience") || model.audience,
      qualified_result: strategyAnswerValue(strategy, "qualified_result") || model.qualified_result,
      goal: strategyAnswerValue(strategy, "business_goal"),
      target_cpa_rub: strategyAnswerValue(strategy, "target_result_cost"),
    },
    safety: {
      must_end_non_serving: true,
      resume_allowed: false,
      network_serving: false,
    },
    direct: {
      campaign: {
        Name: draft.campaign_name,
        StartDate: period.start_date,
        EndDate: period.end_date,
        UnifiedCampaign: {
          BiddingStrategy: {
            Search: {
              BiddingStrategyType: "WB_MAXIMUM_CLICKS",
              PlacementTypes: {
                SearchResults: "YES",
                ProductGallery: "NO",
              },
              WbMaximumClicks: {
                WeeklySpendLimit: weeklyBudget * 1_000_000,
                BidCeiling: bidCeilingRub * 1_000_000,
              },
            },
            Network: { BiddingStrategyType: "SERVING_OFF" },
          },
        },
      },
      ad_group: {
        Name: draft.group_name,
        RegionIds: [regionId],
        NegativeKeywords: { Items: negativeKeywords },
        UnifiedAdGroup: { OfferRetargeting: "NO" },
      },
      keyword: { Keyword: draft.keyword },
      ad: {
        TextAd: {
          Title: draft.ad_title,
          Text: draft.ad_text,
          Href: strategyAnswerValue(strategy, "landing_page"),
          Mobile: "NO",
        },
      },
    },
  };
}
