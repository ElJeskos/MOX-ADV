import assert from "node:assert/strict";
import test from "node:test";

import { minimumWeeklyBudgetRub, validateWeeklyBudgetRub } from "../lib/direct-limits.ts";

const currencies = [{
  Currency: "RUB",
  Properties: [
    { Name: "MinimumBid", Value: "300000" },
    { Name: "MinimumWeeklySpendLimit", Value: "300000000" },
  ],
}];

test("reads the current RUB minimum from the Direct currencies dictionary", () => {
  assert.equal(minimumWeeklyBudgetRub(currencies), 300);
});

test("rejects a weekly budget below the live Direct minimum", () => {
  assert.throws(
    () => validateWeeklyBudgetRub("100", 300),
    /не меньше 300 ₽/u,
  );
  assert.equal(validateWeeklyBudgetRub("300", 300), 300);
});
