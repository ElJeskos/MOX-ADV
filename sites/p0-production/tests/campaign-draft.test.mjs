import assert from "node:assert/strict";
import test from "node:test";

import {
  buildCampaignNames,
  hasDuplicateCampaignName,
  isLegacySearchName,
} from "../lib/campaign-draft.ts";

test("names campaign and group by business meaning without duplicate channel markers", () => {
  assert.deepEqual(buildCampaignNames("ИННОПРОМ", "Россия", "Заявка на участие"), {
    campaignName: "ИННОПРОМ · Россия",
    groupName: "Заявка на участие",
  });
});

test("recognizes legacy names ending in the search channel marker", () => {
  assert.equal(isLegacySearchName("ИННОПРОМ · Поиск"), true);
  assert.equal(isLegacySearchName("ИННОПРОМ · Россия"), false);
});

test("blocks a duplicate active campaign name independent of case", () => {
  assert.equal(
    hasDuplicateCampaignName(["ИННОПРОМ · Россия", "Другая кампания"], "иннопром · россия"),
    true,
  );
  assert.equal(hasDuplicateCampaignName(["Другая кампания"], "ИННОПРОМ · Россия"), false);
});
