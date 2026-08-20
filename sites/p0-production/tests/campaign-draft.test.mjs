import assert from "node:assert/strict";
import test from "node:test";

import {
  buildCampaignNames,
  hasDuplicateCampaignName,
  isCampaignNameWithGeography,
  isLegacySearchName,
} from "../lib/campaign-draft.ts";

test("keeps campaign name and geography as separate meanings", () => {
  assert.deepEqual(buildCampaignNames("ИННОПРОМ", "Россия", "Заявка на участие"), {
    campaignName: "ИННОПРОМ",
    groupName: "Заявка на участие",
  });
  assert.equal(
    buildCampaignNames("ИННОПРОМ", "Москва", "Заявка на участие").campaignName,
    "ИННОПРОМ",
  );
});

test("recognizes legacy compound campaign names", () => {
  assert.equal(isLegacySearchName("ИННОПРОМ · Поиск"), true);
  assert.equal(isLegacySearchName("ИННОПРОМ · Россия"), false);
  assert.equal(isCampaignNameWithGeography("ИННОПРОМ · Россия", "Россия"), true);
  assert.equal(isCampaignNameWithGeography("ИННОПРОМ", "Россия"), false);
});

test("blocks a duplicate active campaign name independent of case", () => {
  assert.equal(
    hasDuplicateCampaignName(["ИННОПРОМ · Россия", "Другая кампания"], "иннопром · россия"),
    true,
  );
  assert.equal(hasDuplicateCampaignName(["Другая кампания"], "ИННОПРОМ · Россия"), false);
});
