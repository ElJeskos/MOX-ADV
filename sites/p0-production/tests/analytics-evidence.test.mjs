import assert from "node:assert/strict";
import test from "node:test";

import {
  ANALYTICS_EVIDENCE_SCHEMA,
  buildAnalyticsEvidence,
} from "../lib/analytics-evidence.ts";

function fixture({ sampled = false, missing = [] } = {}) {
  return {
    site: {
      fetched_at: "2026-08-21T10:00:00.000Z",
      pages: [{ url: "https://owner.example/", title: "Owner" }],
      research: { pages_analyzed: 1 },
    },
    model: {
      product: "Промышленная выставка",
      audience: "Руководители компаний",
      value: "Найти партнёров",
      qualified_result: "Заявка на участие",
      exclusions: "Посетители без заявки",
      missing_questions: missing,
      field_evidence: {
        product: {
          confidence: "MEDIUM",
          source_url: "https://owner.example/",
          quote: "Международная промышленная выставка",
        },
        audience: {
          confidence: "OWNER_CONFIRMED",
          source_url: "",
          quote: "",
          owner_confirmed: true,
        },
      },
    },
    context: {
      direct: {
        ready: true,
        account: "owner-login",
        campaigns_total: 7,
        observed_at: "2026-08-21T10:02:00.000Z",
      },
      campaign_catalog: {
        active: [
          { campaign_id: "1", name: "Campaign A", state: "ON", status: "ACCEPTED" },
          { campaign_id: "2", name: "Campaign B", state: "SUSPENDED", status: "ACCEPTED" },
        ],
      },
      metrika: {
        ready: true,
        counter_id: "123",
        goal_id: "456",
        observed_at: "2026-08-21T10:03:00.000Z",
      },
      performance: {
        period_start: "2026-08-13",
        period_end: "2026-08-20",
        display_metrics: { visits: "42", goal_visits: "3" },
        provenance: {
          observed_at: "2026-08-21T10:03:00.000Z",
          sampling: {
            sampled,
            contains_sensitive_data: false,
            sample_share: sampled ? 0.5 : 1,
            sample_size: sampled ? 21 : 42,
            sample_space: 42,
            data_lag: 0,
          },
        },
      },
    },
  };
}

test("builds a deterministic primary-source evidence snapshot with explicit gaps", async () => {
  const first = await buildAnalyticsEvidence(fixture());
  const second = await buildAnalyticsEvidence(fixture());

  assert.equal(first.schema_version, ANALYTICS_EVIDENCE_SCHEMA);
  assert.equal(first.snapshot_id, second.snapshot_id);
  assert.match(first.snapshot_id, /^sha256:[a-f0-9]{64}$/);
  assert.equal(first.recommendation_status, "EVIDENCE_READY_WITH_GAPS");
  assert.deepEqual(first.sources.map((source) => source.source_id), [
    "first-party",
    "direct",
    "metrika",
    "competitors",
    "wordstat",
  ]);
  assert.equal(first.sources.find((source) => source.source_id === "direct")?.status, "PARTIAL");
  assert.equal(first.sources.find((source) => source.source_id === "competitors")?.status, "UNAVAILABLE");
  assert.equal(first.prelaunch_cost.status, "UNAVAILABLE");
  assert.match(first.prelaunch_cost.reason, /не является CPC\/budget forecast/);
  assert.ok(first.claims.every((claim) => claim.evidence_ids.length > 0));
  assert.equal(new Set(first.evidence.map((item) => item.evidence_id)).size, first.evidence.length);
  assert.ok(first.evidence.every((item) => /^sha256:[a-f0-9]{64}$/.test(item.raw.sha256)));
  assert.ok(first.evidence.every((item) => item.claim_links.length === 1));
  assert.ok(first.evidence.every((item) => first.claims.some((claim) => claim.claim_id === item.claim_links[0].claim_id)));
});

test("keeps web provenance when the owner confirms the same claim", async () => {
  const input = fixture();
  input.model.field_evidence.product.owner_confirmed = true;
  input.model.field_evidence.product.owner_confirmed_at = "2026-08-21T10:04:00.000Z";
  input.model.field_evidence.product.confidence = "OWNER_CONFIRMED";

  const result = await buildAnalyticsEvidence(input);
  const claim = result.claims.find((item) => item.predicate === "product");
  const records = result.evidence.filter((item) => claim?.evidence_ids.includes(item.evidence_id));

  assert.equal(claim?.confidence.consistency, "corroborated");
  assert.deepEqual(records.map((item) => item.source_kind).sort(), [
    "first_party_web",
    "owner_confirmation",
  ]);
  assert.equal(records.find((item) => item.source_kind === "first_party_web")?.source_locator.url, "https://owner.example/");
  assert.equal(records.find((item) => item.source_kind === "owner_confirmation")?.source_locator.state_path, "business_model.product");
});

test("preserves Metrica sampling as partial coverage instead of verified completeness", async () => {
  const result = await buildAnalyticsEvidence(fixture({ sampled: true }));
  const source = result.sources.find((item) => item.source_id === "metrika");
  const claim = result.claims.find((item) => item.predicate === "observed_performance");

  assert.equal(source?.status, "PARTIAL");
  assert.match(source?.limitations.join(" ") ?? "", /sampled/);
  assert.equal(claim?.confidence.coverage, "partial");
  assert.equal(claim?.confidence.tier, "TIER_3_INDICATIVE");
});

test("blocks recommendation status when current Direct inventory cannot be read", async () => {
  const input = fixture();
  input.context.direct = {
    ready: false,
    inventory_ready: false,
    blockers: ["Direct read unavailable"],
  };
  input.context.campaign_catalog = null;

  const result = await buildAnalyticsEvidence(input);

  assert.equal(result.recommendation_status, "BLOCKED_UNKNOWN");
  assert.ok(result.summary.hard_blockers.some((item) => item.includes("Direct inventory")));
  assert.equal(result.sources.find((item) => item.source_id === "direct")?.status, "UNAVAILABLE");
});

test("keeps hard business unknowns outside comparative confidence", async () => {
  const result = await buildAnalyticsEvidence(
    fixture({ missing: ["Какое предложение нужно рекламировать?"] }),
  );

  assert.equal(result.recommendation_status, "BLOCKED_UNKNOWN");
  assert.deepEqual(result.summary.hard_blockers, [
    "Не разрешено: Какое предложение нужно рекламировать?",
  ]);
  assert.ok(result.material_uncertainties.some((item) => item.startsWith("Material Uncertainty:")));
});
