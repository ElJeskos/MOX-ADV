import assert from "node:assert/strict";
import test from "node:test";

import { buildAdText, buildAdTitle } from "../lib/ad-copy.ts";

test("replaces a cut-off long message with complete ad copy", () => {
  const value = buildAdText(
    "Регион-партнер Регион-партнер Партнерство с регионами, представляющими свои экономические возможности",
    "Регион-партнер",
    false,
  );

  assert.equal(value, "Регион-партнер. Оставьте заявку на сайте.");
  assert.ok(value.length <= 81);
  assert.match(value, /[.!?…]$/u);
});

test("preserves a complete short message", () => {
  assert.equal(buildAdText("Узнайте условия участия", "Выставка", true), "Узнайте условия участия.");
});

test("shortens long titles without cutting through a word", () => {
  const value = buildAdTitle("Международная промышленная выставка и деловая программа для регионов");

  assert.ok(value.length <= 56);
  assert.match(value, /…$/u);
  assert.doesNotMatch(value, /програ…$/u);
});
