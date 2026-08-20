import assert from "node:assert/strict";
import test from "node:test";

import {
  minimumWeeklyBudgetRub,
  validateWeeklyBudgetRub,
  weeklyBudgetValidationMessage,
} from "../lib/direct-limits.ts";

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
    /Укажите 300 ₽ или больше/u,
  );
  assert.equal(validateWeeklyBudgetRub("300", 300), 300);
});

test("returns an inline message while the owner enters an invalid budget", () => {
  assert.equal(weeklyBudgetValidationMessage("", 300), "");
  assert.equal(
    weeklyBudgetValidationMessage("200", 300),
    "Минимальный недельный бюджет в Яндекс Директе — 300 ₽. Укажите 300 ₽ или больше.",
  );
  assert.equal(weeklyBudgetValidationMessage("300", 300), "");
});
