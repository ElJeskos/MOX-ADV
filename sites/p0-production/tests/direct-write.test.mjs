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

function successfulFetcher(calls, adId = "401") {
  let campaignGetCalls = 0;
  return async (url, init) => {
    const rawBody = String(init.body);
    const body = JSON.parse(rawBody);
    const service = new URL(url).pathname.split("/").at(-1);
    calls.push({ service, method: body.method, params: body.params, rawBody });
    const key = `${service}.${body.method}`;
    const results = {
      "campaigns.add": { AddResults: [{ Id: 101 }] },
      "campaigns.suspend": { SuspendResults: [{ Id: 101 }] },
      "adgroups.add": { AddResults: [{ Id: 201 }] },
      "keywords.add": { AddResults: [{ Id: 301 }] },
      "ads.moderate": { ModerateResults: [{ Id: adId }] },
    };
    if (key === "campaigns.get") {
      campaignGetCalls += 1;
      const campaign = campaignGetCalls === 1
        ? { Id: 101, State: "SUSPENDED", Status: "DRAFT" }
        : { Id: 101, State: "SUSPENDED", Status: "MODERATION" };
      return jsonResponse({ Campaigns: [campaign] });
    }
    if (key === "ads.add") {
      return new Response(`{"result":{"AddResults":[{"Id":${adId}}]}}`, { headers: { "Content-Type": "application/json" } });
    }
    if (key === "ads.get") {
      return new Response(`{"result":{"Ads":[{"Id":${adId},"Status":"DRAFT","State":"OFF"}]}}`, { headers: { "Content-Type": "application/json" } });
    }
    return jsonResponse(results[key]);
  };
}

test("creates a real-shape Direct graph and ends owner-suspended after moderation", async () => {
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
    "NON_SERVING_CONFIRMED",
    "OBJECT_GRAPH_CREATED",
    "MODERATION_PENDING",
  ]);
  assert.equal(calls.some((call) => call.method === "resume"), false);
  assert.equal(calls.filter((call) => call.method === "suspend").length, 1);
  assert.deepEqual(
    calls.slice(0, 4).map((call) => `${call.service}.${call.method}`),
    ["campaigns.add", "campaigns.suspend", "campaigns.get", "adgroups.add"],
  );
  assert.equal(
    calls[0].params.Campaigns[0].UnifiedCampaign.BiddingStrategy.Network.BiddingStrategyType,
    "SERVING_OFF",
  );
});

test("preserves a Direct ad ID larger than JavaScript safe integer", async () => {
  const calls = [];
  const exactAdId = "1919036093096389375";
  const result = await createSuspendedCampaign(
    { token: "secret", account: "moxstudio" },
    projection(),
    successfulFetcher(calls, exactAdId),
  );
  assert.equal(result.ad_id, exactAdId);
  const moderate = calls.find((call) => call.service === "ads" && call.method === "moderate");
  assert.match(moderate.rawBody, new RegExp(exactAdId));
});

test("continues an owned draft without creating a duplicate campaign", async () => {
  const calls = [];
  const result = await createSuspendedCampaign(
    { token: "secret", account: "moxstudio" },
    projection(),
    successfulFetcher(calls),
    () => undefined,
    { campaignId: "101" },
  );
  assert.equal(result.campaign_id, "101");
  assert.equal(result.recovered_existing, true);
  assert.equal(calls.some((call) => call.service === "campaigns" && call.method === "add"), false);
});

test("continues an owned object graph without duplicating children", async () => {
  const calls = [];
  const result = await createSuspendedCampaign(
    { token: "secret", account: "moxstudio" },
    projection(),
    successfulFetcher(calls, "1919036093096389375"),
    () => undefined,
    { campaignId: "101", adGroupId: "201", keywordId: "301" },
  );
  assert.equal(result.campaign_id, "101");
  assert.equal(result.ad_group_id, "201");
  assert.equal(result.keyword_id, "301");
  assert.equal(result.ad_id, "1919036093096389375");
  assert.equal(calls.some((call) => call.method === "add"), false);
});

test("confirms non-serving containment after a downstream failure", async () => {
  const calls = [];
  const fetcher = async (url, init) => {
    const body = JSON.parse(String(init.body));
    const service = new URL(url).pathname.split("/").at(-1);
    calls.push(`${service}.${body.method}`);
    if (service === "campaigns" && body.method === "add") {
      return jsonResponse({ AddResults: [{ Id: 101 }] });
    }
    if (service === "campaigns" && body.method === "suspend") {
      return jsonResponse({ SuspendResults: [{ Id: 101 }] });
    }
    if (service === "campaigns" && body.method === "get") {
      return jsonResponse({ Campaigns: [{ Id: 101, State: "SUSPENDED", Status: "DRAFT" }] });
    }
    if (service === "adgroups" && body.method === "add") {
      return jsonResponse({ AddResults: [{ Errors: [{ Code: 5002, Message: "Группа отклонена" }] }] });
    }
    throw new Error(`Unexpected call ${service}.${body.method}`);
  };

  await assert.rejects(
    () => createSuspendedCampaign({ token: "secret", account: "moxstudio" }, projection(), fetcher),
    (error) => {
      assert.ok(error instanceof DirectWriteError);
      assert.equal(error.partial.campaign_id, "101");
      assert.equal(error.partial.containment, "NON_SERVING_CONFIRMED");
      return true;
    },
  );
  assert.equal(calls.includes("campaigns.resume"), false);
});

test("blocks every child write until Direct confirms explicit SUSPENDED state", async () => {
  const calls = [];
  const fetcher = async (url, init) => {
    const body = JSON.parse(String(init.body));
    const service = new URL(url).pathname.split("/").at(-1);
    calls.push(`${service}.${body.method}`);
    if (service === "campaigns" && body.method === "add") {
      return jsonResponse({ AddResults: [{ Id: 101 }] });
    }
    if (service === "campaigns" && body.method === "suspend") {
      return jsonResponse({ SuspendResults: [{ Id: 101 }] });
    }
    if (service === "campaigns" && body.method === "get") {
      return jsonResponse({ Campaigns: [{ Id: 101, State: "OFF", Status: "DRAFT" }] });
    }
    throw new Error(`Unexpected child write ${service}.${body.method}`);
  };

  await assert.rejects(
    () => createSuspendedCampaign({ token: "secret", account: "moxstudio" }, projection(), fetcher),
    (error) => {
      assert.ok(error instanceof DirectWriteError);
      assert.equal(error.code, "P0_EXPLICIT_SUSPEND_NOT_CONFIRMED");
      assert.equal(error.partial.containment, "NON_SERVING_CONFIRMED");
      return true;
    },
  );
  assert.deepEqual(calls, ["campaigns.add", "campaigns.suspend", "campaigns.get", "campaigns.get"]);
  assert.equal(calls.some((call) => call.startsWith("adgroups.")), false);
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
