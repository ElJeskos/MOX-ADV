import assert from "node:assert/strict";
import { readFile, rm, writeFile } from "node:fs/promises";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

async function loadComponent(t) {
  const sourceUrl = new URL("../app/MarketEvidenceDisclosure.tsx", import.meta.url);
  const outputUrl = new URL(`../app/.market-evidence-ui-test-${process.pid}-${Date.now()}.mjs`, import.meta.url);
  const source = await readFile(sourceUrl, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  await writeFile(outputUrl, compiled, "utf8");
  t.after(() => rm(outputUrl, { force: true }));
  return (await import(outputUrl.href)).MarketEvidenceDisclosure;
}

function evidence(overrides = {}) {
  return {
    contract_version: "demand-cost-packing-v1",
    snapshot_batch_id: "sha256:batch-104",
    batch_started_at: "2026-08-21T10:00:00.000Z",
    batch_finished_at: "2026-08-21T10:00:04.000Z",
    frequency: {
      status: "AVAILABLE",
      source: "YANDEX_WORDSTAT_V1",
      method: "/v1/topRequests",
      snapshot_batch_id: "sha256:batch-104",
      declared_window: "rolling_last_30_days",
      source_window_end: "undisclosed_by_api",
      observed_unique_count: { value: 67, semantics: "LOWER_BOUND_OBSERVED_TOP_ROWS" },
      scopes: [{ operator_profile: "BROAD_CONTAINING", region_ids: [213], region_names: ["Москва"], device: "desktop", observed_unique_count: { value: 67 } }],
      unique_assigned_rows: [{ row_id: "row-1" }, { row_id: "row-2" }, { row_id: "row-3" }],
      seed_matched_row_counts: [],
      seasonality: { status: "AVAILABLE", source: "/v1/dynamics", operator_profile: "DYNAMICS_BROAD", observations: [] },
      geo_evidence: { status: "AVAILABLE", source: "/v1/regions", observations: [] },
      gaps: [],
    },
    cost: {
      status: "UNAVAILABLE",
      compact_source: null,
      scenario: null,
      scope: null,
      as_of: null,
      currency: null,
      vat_treatment: null,
      sample_size: null,
      range: null,
      aggregation: "FIRST_QUALIFIED_SOURCE_NO_AVERAGING",
      observations: [],
      missing_or_conflict_reasons: ["NO_QUALIFIED_PRELAUNCH_COST_SOURCE"],
    },
    packing: { status: "AWAITING_APPROVED_CAMPAIGN_STRATEGY", demand_cluster_ids: ["cluster-1"] },
    ...overrides,
  };
}

test("Model disclosure renders scoped lower-bound frequency, batch, unique rows and explicit unavailable cost", async (t) => {
  const MarketEvidenceDisclosure = await loadComponent(t);
  const html = renderToStaticMarkup(React.createElement(MarketEvidenceDisclosure, { evidence: evidence(), context: "model" }));
  assert.match(html, /67\+ запросов/);
  assert.match(html, /Нижняя граница по наблюдаемым популярным запросам/);
  assert.match(html, /Москва · компьютеры · профиль операторов: BROAD_CONTAINING · собрано 2026-08-21T10:00:04.000Z/);
  assert.match(html, /sha256:batch-104/);
  assert.match(html, /3 уникальн/);
  assert.match(html, /точный конец окна API не раскрывает/);
  assert.match(html, /Сопоставимая оценка цены недоступна/);
  assert.match(html, /NO_QUALIFIED_PRELAUNCH_COST_SOURCE/);
});

test("Model disclosure renders selected source without averaging plus scenario, scope, date, currency, VAT and sample size", async (t) => {
  const MarketEvidenceDisclosure = await loadComponent(t);
  const cost = {
    status: "AVAILABLE",
    compact_source: "KEYWORDBIDS_V5_CURRENT_PROXY",
    scenario: "traffic volume 65",
    scope: { keyword_id: "9007199254740993", geography: "SAME" },
    as_of: "2026-08-21T09:00:00.000Z",
    currency: "RUB",
    vat_treatment: "EXCLUDED",
    sample_size: { unit: "auction_scenarios", value: 2 },
    range: { low: 120, high: 180, kind: "SCENARIO" },
    aggregation: "FIRST_QUALIFIED_SOURCE_NO_AVERAGING",
    observations: [],
    missing_or_conflict_reasons: [],
  };
  const html = renderToStaticMarkup(React.createElement(MarketEvidenceDisclosure, { evidence: evidence({ cost }), context: "model" }));
  assert.match(html, /120–180 RUB/);
  assert.match(html, /KEYWORDBIDS_V5_CURRENT_PROXY/);
  assert.match(html, /traffic volume 65/);
  assert.match(html, /2026-08-21T09:00:00.000Z/);
  assert.match(html, /НДС: EXCLUDED/);
  assert.match(html, /2 auction_scenarios/);
  assert.match(html, /первый подходящий источник/);
  assert.match(html, /9007199254740993/);
});
