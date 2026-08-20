import assert from "node:assert/strict";
import test from "node:test";

import { buildPublishProjection } from "../lib/campaign-draft.ts";
import { createSuspendedCampaign, DirectWriteError } from "../lib/direct-write.ts";

function jsonResponse(result, status = 200) {
  return new Response(JSON.stringify({ result }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function projection() {
  return buildPublishProjection(
    {
      product: "Участие со стендом в выставке ИННОПРОМ",
      audience: "Руководители промышленных компаний",
      qualified_result: "Заявка на участие",
    },
    {
      geography: "Россия",
      weekly_budget_rub: "10000",
      target_cpa_rub: "2000",
      goal: "Получать заявки",
      period_start: "2026-09-01",
      period_end: "2026-09-30",
      landing_page: "https://innoprom.com/participant/",
    },
    {
      campaign_name: "ИННОПРОМ · Россия",
      group_name: "Заявка на участие",
      keyword: "иннопром стать участником",
      negative_keywords: "бесплатно, вакансии, билет",
      ad_title: "Участие в ИННОПРОМ",
      ad_text: "Подайте заявку на участие.",
    },
  );
}

function successfulFetcher(calls) {
  return async (url, init) => {
    const body = JSON.parse(String(init.body));
    const service = new URL(url).pathname.split("/").at(-1);
    calls.push({ service, method: body.method, params: body.params });
    const key = `${service}.${body.method}`;
    const results = {
      "campaigns.add": { AddResults: [{ Id: 101 }] },
      "campaigns.suspend": { SuspendResults: [{ Id: 101 }] },
      "campaigns.get": { Campaigns: [{ Id: 101, State: "SUSPENDED", Status: "DRAFT" }] },
      "adgroups.add": { AddResults: [{ Id: 201 }] },
      "keywords.add": { AddResults: [{ Id: 301 }] },
      "ads.add": { AddResults: [{ Id: 401 }] },
      "ads.moderate": { ModerateResults: [{ Id: 401 }] },
      "ads.get": { Ads: [{ Id: 401, Status: "DRAFT", State: "OFF" }] },
    };
    return jsonResponse(results[key]);
  };
}

test("creates a real-shape Direct graph and ends with suspended readback", async () => {
  const calls = [];
  const progress = [];
  const result = await createSuspendedCampaign(
    { token: "secret", account: "moxstudio" },
    projection(),
    successfulFetcher(calls),
    (status) => progress.push(status),
  );

  assert.equal(result.campaign_id, "101");
  assert.equal(result.campaign_state, "SUSPENDED");
  assert.equal(result.spend_started, false);
  assert.equal(result.status, "MODERATION_PENDING");
  assert.deepEqual(progress, [
    "CAMPAIGN_CREATED",
    "SUSPENDED_CONFIRMED",
    "OBJECT_GRAPH_CREATED",
    "MODERATION_PENDING",
  ]);
  assert.equal(calls.some((call) => call.method === "resume"), false);
  assert.equal(
    calls[0].params.Campaigns[0].UnifiedCampaign.BiddingStrategy.Network.BiddingStrategyType,
    "SERVING_OFF",
  );
});

test("contains a partial campaign when initial suspension confirmation fails", async () => {
  const calls = [];
  let suspendCalls = 0;
  const fetcher = async (url, init) => {
    const body = JSON.parse(String(init.body));
    const service = new URL(url).pathname.split("/").at(-1);
    calls.push(`${service}.${body.method}`);
    if (service === "campaigns" && body.method === "add") {
      return jsonResponse({ AddResults: [{ Id: 101 }] });
    }
    if (service === "campaigns" && body.method === "suspend") {
      suspendCalls += 1;
      return suspendCalls === 1
        ? jsonResponse({ SuspendResults: [{ Id: 101, Errors: [{ Code: 1 }] }] })
        : jsonResponse({ SuspendResults: [{ Id: 101 }] });
    }
    if (service === "campaigns" && body.method === "get") {
      return jsonResponse({ Campaigns: [{ Id: 101, State: "SUSPENDED" }] });
    }
    throw new Error(`Unexpected call ${service}.${body.method}`);
  };

  await assert.rejects(
    () => createSuspendedCampaign({ token: "secret", account: "moxstudio" }, projection(), fetcher),
    (error) => {
      assert.ok(error instanceof DirectWriteError);
      assert.equal(error.partial.campaign_id, "101");
      assert.equal(error.partial.containment, "SUSPENDED_CONFIRMED");
      return true;
    },
  );
  assert.equal(calls.includes("campaigns.resume"), false);
});

test("preserves a known Campaigns.add rejection without false reconciliation", async () => {
  await assert.rejects(
    () => createSuspendedCampaign(
      { token: "secret", account: "moxstudio" },
      projection(),
      async () => jsonResponse({
        AddResults: [{ Errors: [{ Code: 5001, Message: "Недельный бюджет ниже минимального" }] }],
      }),
    ),
    (error) => {
      assert.ok(error instanceof DirectWriteError);
      assert.equal(error.partial.rejected, true);
      assert.equal(error.partial.containment, undefined);
      assert.deepEqual(error.partial.api_errors, [{
        code: 5001,
        message: "Недельный бюджет ниже минимального",
        details: "",
      }]);
      assert.match(error.message, /Недельный бюджет ниже минимального/u);
      return true;
    },
  );
});

test("marks a lost Campaigns.add response for reconciliation before any retry", async () => {
  await assert.rejects(
    () => createSuspendedCampaign(
      { token: "secret", account: "moxstudio" },
      projection(),
      async () => {
        throw new Error("connection lost after request");
      },
    ),
    (error) => {
      assert.ok(error instanceof DirectWriteError);
      assert.equal(error.partial.add_attempted, true);
      assert.equal(error.partial.containment, "RECONCILIATION_REQUIRED");
      return true;
    },
  );
});

test("rejects any projection that permits resume before calling Direct", async () => {
  const unsafe = projection();
  unsafe.safety.resume_allowed = true;
  let called = false;
  await assert.rejects(
    () => createSuspendedCampaign(
      { token: "secret", account: "moxstudio" },
      unsafe,
      async () => {
        called = true;
        return jsonResponse({});
      },
    ),
    /safety-контракт/u,
  );
  assert.equal(called, false);
});
