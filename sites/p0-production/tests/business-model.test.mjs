import assert from "node:assert/strict";
import test from "node:test";

import { inferDecisionMakers, isUnprocessedAudience } from "../lib/business-model.ts";

const innopromEvidence =
  "САУДОВСКАЯ АРАВИЯ Эр-Рияд, Саудовская Аравия ПОДРОБНЕЕ ИННОПРОМ Международная промышленная выставка, объединяющая на своей площадке производителей и байеров со всего мира.";

test("extracts decision-maker roles instead of copying the page fragment", () => {
  assert.equal(
    inferDecisionMakers(innopromEvidence),
    "Байеры и руководители по закупкам и представители компаний-производителей",
  );
});

test("detects a raw evidence quote stored as the audience answer", () => {
  assert.equal(isUnprocessedAudience(innopromEvidence, innopromEvidence), true);
  assert.equal(isUnprocessedAudience("Байеры и руководители по закупкам", innopromEvidence), false);
});

test("returns no invented role when evidence has none", () => {
  assert.equal(inferDecisionMakers("Международная выставка состоится в октябре"), "");
});
