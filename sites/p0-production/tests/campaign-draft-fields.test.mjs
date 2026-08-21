import assert from "node:assert/strict";
import test from "node:test";

import {
  DIRECT_V501_DRAFT_FIELD_REGISTRY,
  editableDraftFieldNames,
  nextDraftRevisionId,
  normalizeDraftFieldInput,
  projectionFieldValue,
} from "../lib/campaign-draft-fields.ts";

const EXPECTED_PUBLISHABLE_POINTERS = [
  "/direct/campaign/Name",
  "/direct/campaign/StartDate",
  "/direct/campaign/EndDate",
  "/direct/campaign/UnifiedCampaign/BiddingStrategy/Search/BiddingStrategyType",
  "/direct/campaign/UnifiedCampaign/BiddingStrategy/Search/PlacementTypes/SearchResults",
  "/direct/campaign/UnifiedCampaign/BiddingStrategy/Search/PlacementTypes/ProductGallery",
  "/direct/campaign/UnifiedCampaign/BiddingStrategy/Search/WbMaximumClicks/WeeklySpendLimit",
  "/direct/campaign/UnifiedCampaign/BiddingStrategy/Search/WbMaximumClicks/BidCeiling",
  "/direct/campaign/UnifiedCampaign/BiddingStrategy/Network/BiddingStrategyType",
  "/direct/ad_group/Name",
  "/direct/ad_group/RegionIds",
  "/direct/ad_group/NegativeKeywords/Items",
  "/direct/ad_group/UnifiedAdGroup/OfferRetargeting",
  "/direct/keyword/Keyword",
  "/direct/keyword/AutotargetingSettings",
  "/direct/ad/TextAd/Title",
  "/direct/ad/TextAd/Text",
  "/direct/ad/TextAd/Href",
  "/direct/ad/TextAd/Mobile",
  "/direct/ad/TextAd/SitelinkSetId",
  "/direct/sitelink_sets",
];

const projection = {
  direct: {
    campaign: {
      Name: "Кампания",
      StartDate: "2026-09-01",
      EndDate: "2026-09-30",
      UnifiedCampaign: { BiddingStrategy: {
        Search: {
          BiddingStrategyType: "WB_MAXIMUM_CLICKS",
          PlacementTypes: { SearchResults: "YES", ProductGallery: "NO" },
          WbMaximumClicks: { WeeklySpendLimit: 50_000_000_000, BidCeiling: 500_000_000 },
        },
        Network: { BiddingStrategyType: "SERVING_OFF" },
      } },
    },
    ad_group: {
      Name: "Группа",
      RegionIds: [213],
      NegativeKeywords: { Items: ["вакансии", "бесплатно"] },
      UnifiedAdGroup: { OfferRetargeting: "NO" },
    },
    keyword: { Keyword: "участие в выставке" },
    ad: { TextAd: { Title: "Участие в выставке", Text: "Оставьте заявку", Href: "https://owner.example/", Mobile: "NO" } },
  },
};

test("the accepted Direct v501 field registry covers every core campaign, group, criteria, ad and asset field without enabling absent capabilities", () => {
  assert.equal(DIRECT_V501_DRAFT_FIELD_REGISTRY.profile_id, "direct-v501-unified-search-explicit-text");
  assert.equal(DIRECT_V501_DRAFT_FIELD_REGISTRY.profile_version, "1.0.0");
  assert.deepEqual(DIRECT_V501_DRAFT_FIELD_REGISTRY.fields.map((field) => field.pointer), EXPECTED_PUBLISHABLE_POINTERS);
  assert.deepEqual([...new Set(DIRECT_V501_DRAFT_FIELD_REGISTRY.fields.map((field) => field.object_kind))].sort(), ["AD", "AD_GROUP", "ASSET", "CAMPAIGN", "CRITERION"]);
  assert.equal(new Set(DIRECT_V501_DRAFT_FIELD_REGISTRY.fields.map((field) => field.pointer)).size, EXPECTED_PUBLISHABLE_POINTERS.length);
  assert.deepEqual(editableDraftFieldNames(), ["campaign_name", "group_name", "negative_keywords", "keyword", "ad_title", "ad_text"]);

  const absentConditional = DIRECT_V501_DRAFT_FIELD_REGISTRY.fields.filter((field) => field.classification === "CONDITIONALLY_ELIGIBLE");
  assert.deepEqual(absentConditional.map((field) => field.pointer), [
    "/direct/keyword/AutotargetingSettings",
    "/direct/ad/TextAd/SitelinkSetId",
    "/direct/sitelink_sets",
  ]);
  assert.equal(absentConditional.every((field) => field.editable === false && field.presence === "NOT_PRESENT"), true);
});

test("registry input normalization is the only accepted editable surface and resolves exact projection values", () => {
  const normalized = normalizeDraftFieldInput({
    draft_id: " draft-1 ",
    campaign_name: "  Кампания   новая ",
    group_name: " Группа ",
    negative_keywords: " вакансии, бесплатно, вакансии ",
    keyword: "  участие   в выставке ",
    ad_title: " Новый заголовок ",
    ad_text: " Новый   текст ",
  });
  assert.deepEqual(normalized, {
    draft_id: "draft-1",
    campaign_name: "Кампания новая",
    group_name: "Группа",
    negative_keywords: "вакансии, бесплатно, вакансии",
    keyword: "участие в выставке",
    ad_title: "Новый заголовок",
    ad_text: "Новый текст",
  });
  assert.equal(projectionFieldValue(projection, "/direct/campaign/Name"), "Кампания");
  assert.deepEqual(projectionFieldValue(projection, "/direct/ad_group/NegativeKeywords/Items"), ["вакансии", "бесплатно"]);
  assert.equal(projectionFieldValue(projection, "/direct/keyword/AutotargetingSettings"), undefined);
  assert.throws(
    () => normalizeDraftFieldInput({ draft_id: "draft-1", campaign_name: "A", hidden_field: "drop me" }),
    (error) => error?.code === "P0_DRAFT_FIELD_UNSUPPORTED" && /hidden_field/u.test(error.message),
  );
});

test("Draft revisions advance by immutable Draft lineage rather than document revision", () => {
  assert.equal(nextDraftRevisionId("draft-a", "draft-a-r1"), "draft-a-r2");
  assert.equal(nextDraftRevisionId("draft-a", "draft-a-r19"), "draft-a-r20");
  assert.throws(() => nextDraftRevisionId("draft-a", "draft-other-r1"), /lineage/u);
});
