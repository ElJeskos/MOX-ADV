import assert from "node:assert/strict";
import test from "node:test";

import {
  LANDING_ADVISORY_DIMENSIONS,
  LANDING_ADVISORY_SCHEMA,
  LANDING_ARTIFACT_MAX_BYTES,
  PINNED_LANDING_TOOL_VERSIONS,
  createLandingBrowserPolicy,
  landingAdvisoryPriorities,
  runLandingAdvisory,
  verifyLandingAdvisoryRun,
} from "../lib/landing-advisory.ts";

const PUBLIC_ADDRESSES = ["93.184.216.34"];

function strategy(overrides = {}) {
  return {
    strategy_revision_id: "campaign-strategy-r7",
    answers: [
      { field_id: "advertised_offer", value: "Участие в промышленной выставке" },
      { field_id: "qualified_result", value: "Отправленная заявка на участие" },
      { field_id: "landing_page", value: "https://owner.example/participate" },
      { field_id: "core_message", value: "Найдите новых покупателей на выставке" },
    ],
    ...overrides,
  };
}

function contextState() {
  return {
    facts: {
      site: { url: "https://owner.example/" },
      metrika: { counter_id: "424242", goal_id: "1717" },
    },
  };
}

function analyticsEvidence({ partial = false, visits = "10", goalVisits = "2" } = {}) {
  return {
    claims: [{
      predicate: "observed_performance",
      normalized: {
        value: {
          counter_id: "424242",
          goal_id: "1717",
          visits,
          goal_visits: goalVisits,
          report: {
            metadata_complete: true,
            sampled: partial,
            contains_sensitive_data: false,
            sample_share: partial ? 0.5 : 1,
            sample_size: 10,
            sample_space: partial ? 20 : 10,
            data_lag: 0,
            attribution: "last_direct_click_order_dimension",
            timezone: "Europe/Moscow",
            dimensions: ["ym:s:date", "ym:s:lastDirectClickOrder"],
            filters: "ym:s:lastDirectClickOrder=='77'",
            period_start: "2026-08-01",
            period_end: "2026-08-20",
          },
        },
      },
      confidence: { coverage: partial ? "partial" : "complete_for_scope" },
      evidence_ids: ["metrika-performance"],
    }],
  };
}

function lighthouseResult(sequence) {
  return {
    performance_score: [0.72, 0.91, 0.84, 0.88, 0.79][sequence - 1],
    metrics: {
      first_contentful_paint_ms: [1200, 900, 1100, 1000, 1300][sequence - 1],
      largest_contentful_paint_ms: [2500, 1800, 2200, 2100, 2600][sequence - 1],
      cumulative_layout_shift: [0.1, 0.02, 0.08, 0.04, 0.12][sequence - 1],
      total_blocking_time_ms: [300, 100, 220, 180, 350][sequence - 1],
      speed_index_ms: [3000, 2100, 2600, 2400, 3200][sequence - 1],
    },
  };
}

function adapter(overrides = {}) {
  const calls = [];
  let activeLighthouse = 0;
  return {
    calls,
    availability: { available: true, reason: null },
    async resolveHostname(_hostname, signal) {
      assert.equal(signal instanceof AbortSignal, true);
      return PUBLIC_ADDRESSES;
    },
    async versions(signal) {
      assert.equal(signal instanceof AbortSignal, true);
      return { ...PINNED_LANDING_TOOL_VERSIONS };
    },
    async inspect(input) {
      assert.equal(input.signal instanceof AbortSignal, true);
      calls.push(`inspect:${input.url}`);
      input.policy.authorizeRequest({
        url: input.url,
        method: "GET",
        resource_type: "document",
        headers: {},
        body_present: false,
        resolved_addresses: PUBLIC_ADDRESSES,
      });
      input.policy.authorizeRequest({
        url: "https://owner.example/assets/app.js",
        method: "GET",
        resource_type: "script",
        headers: {},
        body_present: false,
        resolved_addresses: PUBLIC_ADDRESSES,
      });
      return {
        requested_url: input.url,
        final_url: input.url,
        redirect_chain: [input.url],
        network_requests: [
          { url: input.url, method: "GET", resource_type: "document", headers: {}, body_present: false, resolved_addresses: PUBLIC_ADDRESSES },
          { url: "https://owner.example/assets/app.js", method: "GET", resource_type: "script", headers: {}, body_present: false, resolved_addresses: PUBLIC_ADDRESSES },
        ],
        response_bytes: 32_000,
        page: {
          title: "Участие в промышленной выставке",
          headings: ["Найдите новых покупателей"],
          text_excerpt: "Оставьте заявку на участие в промышленной выставке.",
          ctas: [{ label: "Оставить заявку", kind: "link" }],
          forms: [{ method: "POST", action_kind: "same_page", fields_count: 4 }],
          metrika_tag_detected: true,
          http_status: 200,
          content_type: "text/html",
        },
        hypotheses: [{
          dimension: "OFFER_MESSAGE_MATCH",
          title: "Первый экран может яснее назвать результат",
          detail: "Это гипотеза для ручной проверки, не установленный факт.",
        }],
      };
    },
    async runLighthouse(input) {
      assert.equal(input.signal instanceof AbortSignal, true);
      assert.equal(activeLighthouse, 0, "Lighthouse runs must never overlap");
      activeLighthouse += 1;
      calls.push(`lighthouse:${input.sequence}:start`);
      await Promise.resolve();
      calls.push(`lighthouse:${input.sequence}:end`);
      activeLighthouse -= 1;
      return lighthouseResult(input.sequence);
    },
    async runAxe(input) {
      assert.equal(input.signal instanceof AbortSignal, true);
      calls.push(`axe:${input.url}`);
      return {
        violations: { count: 1, items: [{ id: "color-contrast", impact: "serious", nodes: 2, help: "Elements must meet contrast" }] },
        passes: { count: 17, items: [{ id: "document-title", impact: null, nodes: 1, help: "Document has a title" }] },
        incomplete: { count: 2, items: [{ id: "aria-prohibited-attr", impact: "minor", nodes: 1, help: "Needs manual review" }] },
        inapplicable: { count: 5, items: [] },
      };
    },
    ...overrides,
  };
}

async function runWith(auditAdapter, evidence = analyticsEvidence()) {
  let tick = 0;
  return runLandingAdvisory({
    strategy: strategy(),
    contextState: contextState(),
    analyticsEvidence: evidence,
    adapter: auditAdapter,
    now: () => `2026-08-21T12:00:${String(tick++).padStart(2, "0")}.000Z`,
  });
}

function canonicalizeForTest(value) {
  if (Array.isArray(value)) return value.map(canonicalizeForTest);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value).sort(([left], [right]) => left.localeCompare(right)).map(([key, item]) => [key, canonicalizeForTest(item)]));
}

async function sha256ForTest(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(canonicalizeForTest(value))));
  return `sha256:${[...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("")}`;
}

async function rehashRun(run) {
  run.advisory_key = `landing-advisory-key:${await sha256ForTest({
    strategy_revision_id: run.strategy_revision_id,
    final_url: run.final_url ?? run.requested_url,
  })}`;
  const withoutRunId = Object.fromEntries(Object.entries(run).filter(([key]) => key !== "run_id"));
  run.run_id = `landing-advisory:${await sha256ForTest(withoutRunId)}`;
  return run;
}

test("LandingAdvisoryRun is versioned to exact Strategy/final URL and preserves typed coverage and tool evidence", async () => {
  const auditAdapter = adapter();
  const run = await runWith(auditAdapter);

  assert.equal(run.schema_version, LANDING_ADVISORY_SCHEMA);
  assert.equal(run.strategy_revision_id, "campaign-strategy-r7");
  assert.equal(run.requested_url, "https://owner.example/participate");
  assert.equal(run.final_url, "https://owner.example/participate");
  assert.match(run.advisory_key, /^landing-advisory-key:sha256:[a-f0-9]{64}$/u);
  assert.match(run.run_id, /^landing-advisory:sha256:[a-f0-9]{64}$/u);
  assert.deepEqual(run.coverage.map((item) => item.dimension), LANDING_ADVISORY_DIMENSIONS);
  assert.equal(run.findings.every((item) => ["OBSERVED_FACT", "DETERMINISTIC_CHECK", "LLM_HYPOTHESIS"].includes(item.type)), true);
  assert.equal(run.findings.every((item) => ["ISSUE_OBSERVED", "NO_ISSUE_FOUND", "INSUFFICIENT_EVIDENCE", "NOT_APPLICABLE"].includes(item.evidence_status)), true);
  assert.equal(run.findings.find((item) => item.type === "LLM_HYPOTHESIS").evidence_status, "INSUFFICIENT_EVIDENCE");
  assert.equal(run.tools.version_status, "PINNED_MATCH");
  assert.deepEqual(run.tools.observed, PINNED_LANDING_TOOL_VERSIONS);
  assert.equal(await verifyLandingAdvisoryRun(run), true);
});

test("pinned Lighthouse runs exactly five times sequentially and records deterministic medians without averaging", async () => {
  const auditAdapter = adapter();
  const run = await runWith(auditAdapter);

  assert.deepEqual(run.lighthouse.runs.map((item) => item.sequence), [1, 2, 3, 4, 5]);
  assert.equal(run.lighthouse.runs.every((item) => item.status === "SUCCEEDED"), true);
  assert.deepEqual(auditAdapter.calls.filter((item) => item.startsWith("lighthouse")), [
    "lighthouse:1:start", "lighthouse:1:end",
    "lighthouse:2:start", "lighthouse:2:end",
    "lighthouse:3:start", "lighthouse:3:end",
    "lighthouse:4:start", "lighthouse:4:end",
    "lighthouse:5:start", "lighthouse:5:end",
  ]);
  assert.equal(run.lighthouse.median.performance_score, 0.84);
  assert.equal(run.lighthouse.median.metrics.first_contentful_paint_ms, 1100);
  assert.equal(run.lighthouse.median.metrics.largest_contentful_paint_ms, 2200);
  assert.equal(run.lighthouse.median.metrics.cumulative_layout_shift, 0.08);
  assert.equal(run.lighthouse.median.metrics.total_blocking_time_ms, 220);
  assert.equal(run.lighthouse.median.metrics.speed_index_ms, 2600);
  assert.equal(run.lighthouse.aggregation, "COMPONENT_MEDIAN_OF_EXACTLY_FIVE_NO_AVERAGING");
  assert.deepEqual(run.viewport, { form_factor: "desktop", width: 1920, height: 1080, device_scale_factor: 1 });
});

test("failed Lighthouse attempts stay visible and make performance evidence insufficient", async () => {
  const base = adapter();
  const original = base.runLighthouse;
  base.runLighthouse = async (input) => {
    if (input.sequence === 3) throw new Error("Bearer should-not-persist");
    return original(input);
  };
  const run = await runWith(base);

  assert.deepEqual(run.lighthouse.runs.map((item) => item.sequence), [1, 2, 3, 4, 5]);
  assert.equal(run.lighthouse.runs[2].status, "FAILED");
  assert.equal(run.lighthouse.runs[2].error_code, "LIGHTHOUSE_RUN_FAILED");
  assert.equal(run.lighthouse.median, null);
  assert.equal(run.coverage.find((item) => item.dimension === "PERFORMANCE").evidence_status, "INSUFFICIENT_EVIDENCE");
  assert.doesNotMatch(JSON.stringify(run), /should-not-persist/u);
});

test("axe-core preserves bounded raw category counts and incomplete remains explicit manual review", async () => {
  const run = await runWith(adapter());

  assert.deepEqual(Object.keys(run.axe.categories), ["violations", "passes", "incomplete", "inapplicable"]);
  assert.equal(run.axe.categories.violations.count, 1);
  assert.equal(run.axe.categories.passes.count, 17);
  assert.equal(run.axe.categories.incomplete.count, 2);
  assert.equal(run.axe.manual_review.required, true);
  assert.match(run.axe.manual_review.disclosure, /incomplete/u);
  assert.equal(run.coverage.find((item) => item.dimension === "ACCESSIBILITY").evidence_status, "ISSUE_OBSERVED");
});

test("browser policy denies cross-party egress, credentials, restricted paths and every write interaction before an adapter can use them", () => {
  const policy = createLandingBrowserPolicy("https://owner.example/participate", "https://owner.example/");
  policy.bindHostResolution("owner.example", PUBLIC_ADDRESSES);
  assert.equal(policy.profile.allow_form_submission, false);
  assert.equal(policy.profile.allow_clicks, false);
  assert.equal(policy.profile.allow_uploads, false);
  assert.equal(policy.profile.allow_downloads, false);
  assert.equal(policy.profile.persist_cookies, false);
  assert.equal(policy.profile.allow_credentials, false);

  for (const request of [
    { url: "https://tracker.example/pixel", method: "GET", resource_type: "image", headers: {}, body_present: false },
    { url: "https://owner.example/admin", method: "GET", resource_type: "document", headers: {}, body_present: false },
    { url: "https://owner.example/login", method: "GET", resource_type: "document", headers: {}, body_present: false },
    { url: "https://owner.example/participate", method: "POST", resource_type: "document", headers: {}, body_present: true },
    { url: "https://owner.example/participate", method: "GET", resource_type: "document", headers: { authorization: "Bearer secret" }, body_present: false },
    { url: "https://user:secret@owner.example/participate", method: "GET", resource_type: "document", headers: {}, body_present: false },
    { url: "https://owner.example/participate?email=owner@example.com", method: "GET", resource_type: "document", headers: {}, body_present: false },
  ]) {
    assert.throws(() => policy.authorizeRequest({ ...request, resolved_addresses: PUBLIC_ADDRESSES }), /LANDING_(?:DNS_IP|EGRESS|RESTRICTED_PATH|WRITE|CREDENTIAL)_DENIED/u);
  }
  assert.throws(
    () => policy.authorizeRequest({ url: "https://owner.example/assets/app.css", method: "GET", resource_type: "stylesheet", headers: {}, body_present: false, resolved_addresses: ["127.0.0.1"] }),
    /LANDING_DNS_IP_DENIED/u,
  );
  assert.doesNotThrow(() => policy.authorizeRequest({ url: "https://owner.example/assets/app.css", method: "GET", resource_type: "stylesheet", headers: {}, body_present: false, resolved_addresses: PUBLIC_ADDRESSES }));
});

test("unsafe adapter trace fails closed and never persists cross-party URLs or raw secrets", async () => {
  const unsafe = adapter({
    async inspect(input) {
      return {
        requested_url: input.url,
        final_url: input.url,
        redirect_chain: [input.url],
        network_requests: [{ url: "https://tracker.example/pixel?email=owner@example.com", method: "GET", resource_type: "image", headers: {}, body_present: false, resolved_addresses: PUBLIC_ADDRESSES }],
        response_bytes: 1,
        page: { title: "Bearer secret", headings: [], text_excerpt: "owner@example.com", ctas: [], forms: [], metrika_tag_detected: false, http_status: 200, content_type: "text/html" },
        hypotheses: [],
      };
    },
  });
  const run = await runWith(unsafe);

  assert.equal(run.status, "SAFETY_BLOCKED");
  assert.equal(run.final_url, null);
  assert.equal(run.lighthouse.runs.length, 0);
  assert.doesNotMatch(JSON.stringify(run), /tracker\.example|owner@example\.com|Bearer secret/u);
  assert.equal(await verifyLandingAdvisoryRun(run), true);
});

test("artifacts are bounded and redact secrets and PII", async () => {
  const huge = "x".repeat(LANDING_ARTIFACT_MAX_BYTES * 2);
  const withSensitivePage = adapter({
    async inspect(input) {
      return {
        requested_url: input.url,
        final_url: input.url,
        redirect_chain: [input.url],
        network_requests: [{ url: input.url, method: "GET", resource_type: "document", headers: {}, body_present: false, resolved_addresses: PUBLIC_ADDRESSES }],
        response_bytes: 20,
        page: {
          title: "Authorization: Bearer page-secret",
          headings: ["sales@example.com"],
          text_excerpt: `${huge} +7 999 123-45-67`,
          ctas: [{ label: "owner@example.com", kind: "link" }],
          forms: [{ method: "POST", action_kind: "same_page", fields_count: 99 }],
          metrika_tag_detected: true,
          http_status: 200,
          content_type: "text/html",
        },
        hypotheses: [],
      };
    },
  });
  const run = await runWith(withSensitivePage);
  const serialized = JSON.stringify(run);

  assert.equal(new TextEncoder().encode(JSON.stringify(run.artifacts)).byteLength <= LANDING_ARTIFACT_MAX_BYTES, true);
  assert.doesNotMatch(serialized, /page-secret|sales@example\.com|owner@example\.com|999 123-45-67/u);
  assert.match(serialized, /\[REDACTED_(?:CREDENTIAL|PII)\]/u);
});

test("missing or partial exact Metrika observations stay insufficient rather than zero or success", async () => {
  const partial = await runWith(adapter(), analyticsEvidence({ partial: true, visits: "0", goalVisits: "0" }));
  const missingGoalMetric = await runWith(adapter(), analyticsEvidence({ visits: "10", goalVisits: null }));
  const missing = await runWith(adapter(), { claims: [] });

  for (const run of [partial, missingGoalMetric, missing]) {
    const finding = run.findings.find((item) => item.dimension === "OBSERVED_METRIKA_BEHAVIOR");
    assert.equal(finding.type, "OBSERVED_FACT");
    assert.equal(finding.evidence_status, "INSUFFICIENT_EVIDENCE");
    assert.doesNotMatch(finding.title, /успех|success/iu);
  }
  assert.equal(partial.metrika.source, "PERSISTED_ANALYTICS_EVIDENCE_ONLY");
  assert.equal(partial.metrika.browser_cabinet_used, false);
  assert.equal(partial.metrika.counter_id, "424242");
  assert.equal(partial.metrika.goal_id, "1717");
});

test("private DNS resolution fails closed before browser or tools execute", async () => {
  const privateDns = adapter({ async resolveHostname() { return ["127.0.0.1"]; } });
  const run = await runWith(privateDns);
  assert.equal(run.status, "SAFETY_BLOCKED");
  assert.equal(run.browser_safety.safety_result, "BLOCKED");
  assert.equal(privateDns.calls.length, 0);
  assert.equal(run.final_url, null);
});

test("tool version mismatch is explicit and tools are not executed", async () => {
  const mismatch = adapter({
    async versions() {
      return { ...PINNED_LANDING_TOOL_VERSIONS, lighthouse: "unexpected" };
    },
  });
  const run = await runWith(mismatch);

  assert.equal(run.status, "INSUFFICIENT_EVIDENCE");
  assert.equal(run.tools.version_status, "PINNED_MISMATCH");
  assert.equal(mismatch.calls.length, 0);
  assert.equal(run.lighthouse.runs.length, 0);
  assert.equal(run.coverage.every((item) => item.evidence_status === "INSUFFICIENT_EVIDENCE"), true);
});

test("operator priorities are deterministic, exclude hypotheses and are capped at three", async () => {
  const run = await runWith(adapter());
  run.findings.push(
    { ...run.findings[0], finding_id: "extra-priority", dimension: "FORMS", priority: 0, evidence_status: "ISSUE_OBSERVED" },
    { ...run.findings[0], finding_id: "hypothesis-priority", type: "LLM_HYPOTHESIS", priority: -1, evidence_status: "INSUFFICIENT_EVIDENCE" },
  );
  const priorities = landingAdvisoryPriorities(run);
  assert.equal(priorities.length, 3);
  assert.equal(priorities[0].finding_id, "extra-priority");
  assert.equal(priorities.some((item) => item.type === "LLM_HYPOTHESIS"), false);
});

test("run verification rejects content-rehashed final URL and allowlist policy tampering", async () => {
  const run = await runWith(adapter());
  const crossPartyFinal = structuredClone(run);
  crossPartyFinal.final_url = "https://unrelated.example/participate";
  crossPartyFinal.browser_safety.allowed_hosts = ["owner.example", "unrelated.example"];
  const restrictedFinal = structuredClone(run);
  restrictedFinal.final_url = "https://owner.example/admin";
  const inconsistentAllowedHosts = structuredClone(run);
  inconsistentAllowedHosts.browser_safety.allowed_hosts = ["www.owner.example"];

  assert.equal(await verifyLandingAdvisoryRun(await rehashRun(crossPartyFinal)), false);
  assert.equal(await verifyLandingAdvisoryRun(await rehashRun(restrictedFinal)), false);
  assert.equal(await verifyLandingAdvisoryRun(await rehashRun(inconsistentAllowedHosts)), false);
});

test("run hash verification rejects malformed persisted artifacts and finding enums", async () => {
  const run = await runWith(adapter());
  const malformedFinding = structuredClone(run);
  malformedFinding.findings[0].type = "PROMOTED_GUESS";
  const malformedArtifact = structuredClone(run);
  malformedArtifact.artifacts[0].kind = "COOKIE_JAR";
  const mismatchedArtifact = structuredClone(run);
  mismatchedArtifact.artifacts[1].value.expected_runs = 4;
  const oversized = structuredClone(run);
  oversized.artifacts.push({ artifact_id: "huge", kind: "PAGE_OBSERVATION", value: "x".repeat(LANDING_ARTIFACT_MAX_BYTES) });
  const unredacted = structuredClone(run);
  unredacted.findings[0].detail = "Authorization: Bearer persisted-secret owner@example.com";
  const forged = structuredClone(run);
  forged.findings[0].title = "forged without rehash";

  assert.equal(await verifyLandingAdvisoryRun(await rehashRun(malformedFinding)), false);
  assert.equal(await verifyLandingAdvisoryRun(await rehashRun(malformedArtifact)), false);
  assert.equal(await verifyLandingAdvisoryRun(await rehashRun(mismatchedArtifact)), false);
  assert.equal(await verifyLandingAdvisoryRun(await rehashRun(oversized)), false);
  assert.equal(await verifyLandingAdvisoryRun(await rehashRun(unredacted)), false);
  assert.equal(await verifyLandingAdvisoryRun(forged), false);
});
