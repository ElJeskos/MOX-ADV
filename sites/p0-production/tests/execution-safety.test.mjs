import assert from "node:assert/strict";
import test from "node:test";
import JSONbigFactory from "json-bigint";

import { buildPublishProjection } from "../lib/campaign-draft.ts";
import { fingerprintDirectProjection } from "../lib/campaign-fanout.ts";
import {
  executeSafeSingleCampaign,
  mustHoldAccountLock,
} from "../lib/execution-safety.ts";

const JSONbig = JSONbigFactory({ useNativeBigInt: true });

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
      strategy_revision_id: "campaign-strategy-r7",
      draft_id: "draft-control-1",
      draft_revision_id: "draft-control-1-r3",
      capability_profile_id: "direct-v501-unified-search-explicit-text",
      capability_profile_version: "1.0.0",
      playbook_release_id: "release-1",
      playbook_release_version: "1.0.0",
      playbook_rule_id: "rule-1",
      playbook_rule_version: "1.0.0",
      campaign_name: "ИННОПРОМ",
      group_name: "Заявка на участие",
      keyword: "иннопром стать участником",
      negative_keywords: "бесплатно, вакансии, билет",
      ad_title: "Участие в ИННОПРОМ",
      ad_text: "Подайте заявку на участие.",
    },
  );
}

function authority(publishFingerprint) {
  return {
    direct_account_binding: {
      source_kind: "YANDEX_DIRECT_API_V501",
      account: "moxstudio",
      client_id: "direct-client-1",
      verified: true,
    },
    direct_capability_snapshot: {
      schema_version: "direct-account-capability-snapshot-v1",
      snapshot_id: "direct-capability:moxstudio:1",
      observed_at: "2026-08-22T00:40:00.000Z",
      source: "YANDEX_DIRECT_API_V501",
      account: "moxstudio",
      api_version: "v501",
      archived: "NO",
      currency: "RUB",
      edit_campaigns_grant: "YES",
      available_campaign_types: ["UNIFIED_CAMPAIGN"],
      restrictions: [],
      conditional_capabilities: [],
    },
    capability_profile: {
      profile_id: "direct-v501-unified-search-explicit-text",
      profile_version: "1.0.0",
      api_version: "v501",
      campaign_type: "UNIFIED_CAMPAIGN",
      ad_group_type: "UNIFIED_AD_GROUP",
      criteria: ["EXPLICIT_KEYWORDS"],
      ad_type: "TEXT_AD",
      search_strategy: "WB_MAXIMUM_CLICKS",
      network_strategy: "SERVING_OFF",
      conditional_enabled: [],
      conditional_not_enabled: ["AUTOTARGETING", "SITELINKS", "PRODUCT_GALLERY", "NETWORK"],
    },
    publish_fingerprint: publishFingerprint,
    publication_blockers: [],
  };
}

class MemoryExecutionJournal {
  constructor() {
    this.records = new Map();
    this.locks = new Map();
    this.saved = [];
    this.released = [];
    this.held = [];
  }

  async acquire(identity) {
    const owner = this.locks.get(identity.account);
    if (owner && owner !== identity.execution_id) throw new Error("ACCOUNT_WRITE_LOCKED");
    this.locks.set(identity.account, identity.execution_id);
    return structuredClone(this.records.get(identity.execution_id) ?? null);
  }

  async save(record) {
    const copy = structuredClone(record);
    this.records.set(record.execution_id, copy);
    this.saved.push(copy);
  }

  async release(identity) {
    if (this.locks.get(identity.account) === identity.execution_id) this.locks.delete(identity.account);
    this.released.push(structuredClone(identity));
  }

  async hold(identity) {
    this.locks.set(identity.account, identity.execution_id);
    this.held.push(structuredClone(identity));
  }
}

function jsonResponse(result) {
  return new Response(JSONbig.stringify({ result }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function successfulFetcher(expected, journal, calls, options = {}) {
  let campaignGets = 0;
  let adGets = 0;
  return async (url, init) => {
    const body = JSONbig.parse(String(init.body));
    const service = new URL(url).pathname.split("/").at(-1);
    const operation = `${service}.${body.method}`;
    if (body.method !== "get") {
      assert.equal(journal.records.get("execution-1")?.pending_dispatch?.operation, operation);
    }
    calls.push(operation);
    if (operation === "campaigns.add") return jsonResponse({ AddResults: [{
      Id: 90071992547409931n,
      ...(options.campaignWarnings ? { Warnings: options.campaignWarnings } : {}),
    }] });
    if (operation === "campaigns.suspend") return jsonResponse({ SuspendResults: [{ Id: 90071992547409931n }] });
    if (operation === "campaigns.get") {
      campaignGets += 1;
      return jsonResponse({ Campaigns: [{
        Id: 90071992547409931n,
        Name: expected.direct.campaign.Name,
        Type: "UNIFIED_CAMPAIGN",
        Status: campaignGets < 3 ? "DRAFT" : "MODERATION",
        State: "SUSPENDED",
        StartDate: expected.direct.campaign.StartDate,
        EndDate: expected.direct.campaign.EndDate,
        UnifiedCampaign: expected.direct.campaign.UnifiedCampaign,
      }] });
    }
    if (operation === "adgroups.add") return jsonResponse({ AddResults: [{ Id: 90071992547409932n }] });
    if (operation === "adgroups.get") return jsonResponse({ AdGroups: [{
      Id: 90071992547409932n,
      CampaignId: 90071992547409931n,
      Type: "UNIFIED_AD_GROUP",
      ...expected.direct.ad_group,
    }] });
    if (operation === "keywords.add") return jsonResponse({ AddResults: [{ Id: 90071992547409933n }] });
    if (operation === "keywords.get") return jsonResponse({ Keywords: [{
      Id: 90071992547409933n,
      AdGroupId: 90071992547409932n,
      Keyword: options.keywordValue ?? expected.direct.keyword.Keyword,
      Status: "ACCEPTED",
      State: "ON",
    }] });
    if (operation === "ads.add") return jsonResponse({ AddResults: [{ Id: 90071992547409934n }] });
    if (operation === "ads.moderate") return jsonResponse({ ModerateResults: [{ Id: 90071992547409934n }] });
    if (operation === "ads.get") {
      adGets += 1;
      return jsonResponse({ Ads: [{
        Id: 90071992547409934n,
        CampaignId: 90071992547409931n,
        AdGroupId: 90071992547409932n,
        Type: "TEXT_AD",
        Status: adGets === 1 ? "DRAFT" : "MODERATION",
        State: "OFF",
        StatusClarification: null,
        TextAd: expected.direct.ad.TextAd,
      }] });
    }
    throw new Error(`Unexpected Direct call ${operation}`);
  };
}

test("persists every mutation intent before Direct and releases the account writer after exact graph readback", async () => {
  const expected = projection();
  const publishFingerprint = await fingerprintDirectProjection(expected);
  const journal = new MemoryExecutionJournal();
  const calls = [];

  const result = await executeSafeSingleCampaign({
    execution_id: "execution-1",
    config: { token: "secret", account: "moxstudio" },
    projection: expected,
    authority: authority(publishFingerprint),
    journal,
    fetcher: successfulFetcher(expected, journal, calls),
    now: () => "2026-08-22T00:41:00.000Z",
  });

  assert.equal(result.status, "MODERATION_PENDING");
  assert.equal(result.campaign_id, "90071992547409931");
  assert.equal(result.ad_id, "90071992547409934");
  assert.equal(journal.locks.has("moxstudio"), false);
  assert.equal(journal.released.length, 1);
  assert.equal(journal.held.length, 0);
  assert.deepEqual(
    journal.saved.filter((record) => record.pending_dispatch).map((record) => record.pending_dispatch.operation),
    ["campaigns.add", "campaigns.suspend", "adgroups.add", "keywords.add", "ads.add", "ads.moderate"],
  );
  assert.equal(calls.includes("campaigns.resume"), false);
  assert.equal(journal.records.get("execution-1").status, "MODERATION_PENDING");
});

test("holds the account writer after an ambiguous add and forbids blind restart or a competing execution", async () => {
  const expected = projection();
  const publishFingerprint = await fingerprintDirectProjection(expected);
  const journal = new MemoryExecutionJournal();
  let dispatches = 0;
  const input = {
    execution_id: "execution-1",
    config: { token: "secret", account: "moxstudio" },
    projection: expected,
    authority: authority(publishFingerprint),
    journal,
    now: () => "2026-08-22T00:41:00.000Z",
  };

  await assert.rejects(
    () => executeSafeSingleCampaign({
      ...input,
      fetcher: async () => {
        dispatches += 1;
        throw new Error("connection lost after dispatch");
      },
    }),
    (error) => {
      assert.equal(error.code, "P0_DIRECT_OUTCOME_AMBIGUOUS");
      assert.equal(error.partial.account_lock, "HELD_FOR_RECONCILIATION");
      return true;
    },
  );
  assert.equal(dispatches, 1);
  assert.equal(journal.records.get("execution-1").pending_dispatch.operation, "campaigns.add");
  assert.equal(journal.records.get("execution-1").status, "RECONCILIATION_REQUIRED");
  assert.equal(journal.locks.get("moxstudio"), "execution-1");

  let restartCalls = 0;
  await assert.rejects(
    () => executeSafeSingleCampaign({
      ...input,
      fetcher: async () => {
        restartCalls += 1;
        throw new Error("must not retry");
      },
    }),
    (error) => error.code === "P0_RECONCILIATION_REQUIRED",
  );
  assert.equal(restartCalls, 0);

  await assert.rejects(
    () => executeSafeSingleCampaign({
      ...input,
      execution_id: "execution-2",
      fetcher: async () => {
        restartCalls += 1;
        throw new Error("must not dispatch while locked");
      },
    }),
    (error) => error.code === "P0_ACCOUNT_WRITE_LOCKED",
  );
  assert.equal(restartCalls, 0);
});

test("bounded restart reconciliation confirms an ambiguous suspend by exact known campaign ID", async () => {
  const expected = projection();
  const publishFingerprint = await fingerprintDirectProjection(expected);
  const journal = new MemoryExecutionJournal();
  let firstCalls = 0;
  const input = {
    execution_id: "execution-1",
    config: { token: "secret", account: "moxstudio" },
    projection: expected,
    authority: authority(publishFingerprint),
    journal,
    now: () => "2026-08-22T00:41:00.000Z",
  };

  await assert.rejects(
    () => executeSafeSingleCampaign({
      ...input,
      fetcher: async (url, init) => {
        firstCalls += 1;
        const body = JSONbig.parse(String(init.body));
        if (body.method === "add") return jsonResponse({ AddResults: [{ Id: 90071992547409931n }] });
        throw new Error(`lost ${new URL(url).pathname}.${body.method}`);
      },
    }),
    (error) => error.code === "P0_DIRECT_OUTCOME_AMBIGUOUS",
  );
  assert.equal(firstCalls, 2);
  assert.equal(journal.records.get("execution-1").pending_dispatch.operation, "campaigns.suspend");
  assert.equal(journal.records.get("execution-1").provider_ids.campaign_id, "90071992547409931");

  const restartCalls = [];
  const result = await executeSafeSingleCampaign({
    ...input,
    fetcher: successfulFetcher(expected, journal, restartCalls),
    now: () => "2026-08-22T00:42:00.000Z",
  });
  assert.equal(result.status, "MODERATION_PENDING");
  assert.equal(restartCalls.includes("campaigns.add"), false);
  assert.equal(restartCalls.includes("campaigns.suspend"), false);
  assert.equal(restartCalls.filter((operation) => operation === "campaigns.get").length, 4);
});

test("holds the writer when bounded official get retries cannot establish the graph", async () => {
  const expected = projection();
  const publishFingerprint = await fingerprintDirectProjection(expected);
  const journal = new MemoryExecutionJournal();
  const calls = [];
  const baseFetcher = successfulFetcher(expected, journal, calls);
  let failedReads = 0;

  await assert.rejects(
    () => executeSafeSingleCampaign({
      execution_id: "execution-1",
      config: { token: "secret", account: "moxstudio" },
      projection: expected,
      authority: authority(publishFingerprint),
      journal,
      fetcher: async (url, init) => {
        const body = JSONbig.parse(String(init.body));
        const service = new URL(url).pathname.split("/").at(-1);
        if (`${service}.${body.method}` === "keywords.get") {
          failedReads += 1;
          throw new Error("readback unavailable");
        }
        return baseFetcher(url, init);
      },
      now: () => "2026-08-22T00:41:00.000Z",
    }),
    (error) => {
      assert.equal(error.code, "P0_DIRECT_READBACK_AMBIGUOUS");
      assert.equal(error.partial.account_lock, "HELD_FOR_RECONCILIATION");
      return true;
    },
  );
  assert.equal(failedReads, 2);
  assert.equal(journal.records.get("execution-1").status, "RECONCILIATION_REQUIRED");
  assert.equal(journal.locks.get("moxstudio"), "execution-1");
});

test("keeps an ambiguous child add intent even after confirming parent containment", async () => {
  const expected = projection();
  const publishFingerprint = await fingerprintDirectProjection(expected);
  const journal = new MemoryExecutionJournal();
  const calls = [];
  const baseFetcher = successfulFetcher(expected, journal, calls);

  await assert.rejects(
    () => executeSafeSingleCampaign({
      execution_id: "execution-1",
      config: { token: "secret", account: "moxstudio" },
      projection: expected,
      authority: authority(publishFingerprint),
      journal,
      fetcher: async (url, init) => {
        const body = JSONbig.parse(String(init.body));
        const service = new URL(url).pathname.split("/").at(-1);
        if (`${service}.${body.method}` === "adgroups.add") {
          assert.equal(journal.records.get("execution-1").pending_dispatch.operation, "adgroups.add");
          return new Response("temporarily unavailable", { status: 503 });
        }
        return baseFetcher(url, init);
      },
      now: () => "2026-08-22T00:41:00.000Z",
    }),
    (error) => {
      assert.equal(error.code, "P0_DIRECT_HTTP_FAILED");
      assert.equal(error.partial.campaign_id, "90071992547409931");
      assert.equal(error.partial.containment, "NON_SERVING_CONFIRMED");
      assert.equal(error.partial.account_lock, "HELD_FOR_RECONCILIATION");
      return true;
    },
  );

  assert.equal(journal.records.get("execution-1").pending_dispatch.operation, "adgroups.add");
  assert.equal(journal.records.get("execution-1").status, "RECONCILIATION_REQUIRED");
  assert.equal(journal.locks.get("moxstudio"), "execution-1");
});

test("classifies a failed pre-dispatch journal write as system-owned without touching Direct or holding the account", async () => {
  const expected = projection();
  const publishFingerprint = await fingerprintDirectProjection(expected);
  const journal = new MemoryExecutionJournal();
  const originalSave = journal.save.bind(journal);
  let rejectedIntent = false;
  journal.save = async (record) => {
    if (!rejectedIntent && record.pending_dispatch) {
      rejectedIntent = true;
      throw new Error("durable storage unavailable");
    }
    return originalSave(record);
  };
  let networkCalls = 0;

  await assert.rejects(
    () => executeSafeSingleCampaign({
      execution_id: "execution-1",
      config: { token: "secret", account: "moxstudio" },
      projection: expected,
      authority: authority(publishFingerprint),
      journal,
      fetcher: async () => {
        networkCalls += 1;
        throw new Error("must not reach Direct");
      },
      now: () => "2026-08-22T00:41:00.000Z",
    }),
    (error) => {
      assert.equal(error.code, "P0_EXECUTION_JOURNAL_FAILED");
      assert.equal(error.partial.dispatch_not_attempted, true);
      assert.equal(error.partial.account_lock, "RELEASED");
      return true;
    },
  );
  assert.equal(networkCalls, 0);
  assert.equal(journal.records.get("execution-1").status, "SYSTEM_FAILED");
  assert.equal(journal.locks.has("moxstudio"), false);

  journal.save = originalSave;
  const retryCalls = [];
  const retried = await executeSafeSingleCampaign({
    execution_id: "execution-1",
    config: { token: "secret", account: "moxstudio" },
    projection: expected,
    authority: authority(publishFingerprint),
    journal,
    fetcher: successfulFetcher(expected, journal, retryCalls),
    now: () => "2026-08-22T00:42:00.000Z",
  });
  assert.equal(retried.status, "MODERATION_PENDING");
  assert.equal(retryCalls.filter((operation) => operation === "campaigns.add").length, 1);
});

test("retains the durable dispatch intent when checkpointing a known provider ID fails", async () => {
  const expected = projection();
  const publishFingerprint = await fingerprintDirectProjection(expected);
  const journal = new MemoryExecutionJournal();
  const originalSave = journal.save.bind(journal);
  let rejectedCheckpoint = false;
  journal.save = async (record) => {
    if (!rejectedCheckpoint && record.status === "CAMPAIGN_CREATED") {
      rejectedCheckpoint = true;
      throw new Error("checkpoint unavailable");
    }
    return originalSave(record);
  };
  let networkCalls = 0;

  await assert.rejects(
    () => executeSafeSingleCampaign({
      execution_id: "execution-1",
      config: { token: "secret", account: "moxstudio" },
      projection: expected,
      authority: authority(publishFingerprint),
      journal,
      fetcher: async () => {
        networkCalls += 1;
        return jsonResponse({ AddResults: [{ Id: 90071992547409931n }] });
      },
      now: () => "2026-08-22T00:41:00.000Z",
    }),
    (error) => {
      assert.equal(error.code, "P0_EXECUTION_JOURNAL_FAILED");
      assert.equal(error.partial.account_lock, "HELD_FOR_RECONCILIATION");
      return true;
    },
  );
  assert.equal(networkCalls, 1);
  assert.equal(journal.records.get("execution-1").pending_dispatch.operation, "campaigns.add");
  assert.equal(journal.records.get("execution-1").status, "RECONCILIATION_REQUIRED");
  assert.equal(journal.locks.get("moxstudio"), "execution-1");
});

test("fails account, capability, fingerprint, completeness and publication blockers before journal claim or network", async () => {
  const expected = projection();
  const publishFingerprint = await fingerprintDirectProjection(expected);
  const baseAuthority = authority(publishFingerprint);
  const cases = [
    ["P0_PUBLICATION_BLOCKED", (projectionValue, authorityValue) => { authorityValue.publication_blockers = [{ code: "EVIDENCE_GAP" }]; }],
    ["P0_CAPABILITY_OR_ACCOUNT_MISMATCH", (projectionValue, authorityValue) => { authorityValue.direct_account_binding.account = "other-account"; }],
    ["P0_CAPABILITY_OR_ACCOUNT_MISMATCH", (projectionValue, authorityValue) => { authorityValue.capability_profile.network_strategy = "NETWORK_DEFAULT"; }],
    ["P0_PROJECTION_INCOMPLETE", (projectionValue) => { projectionValue.direct.campaign.TimeZone = "Europe/Moscow"; }],
    ["P0_PROJECTION_FINGERPRINT_MISMATCH", (projectionValue, authorityValue) => { authorityValue.publish_fingerprint = `sha256:${"0".repeat(64)}`; }],
  ];

  for (const [code, mutate] of cases) {
    const projectionValue = structuredClone(expected);
    const authorityValue = structuredClone(baseAuthority);
    mutate(projectionValue, authorityValue);
    const journal = new MemoryExecutionJournal();
    let networkCalls = 0;
    await assert.rejects(
      () => executeSafeSingleCampaign({
        execution_id: "execution-1",
        config: { token: "secret", account: "moxstudio" },
        projection: projectionValue,
        authority: authorityValue,
        journal,
        fetcher: async () => {
          networkCalls += 1;
          throw new Error("must fail before network");
        },
      }),
      (error) => error.code === code,
    );
    assert.equal(networkCalls, 0);
    assert.equal(journal.saved.length, 0);
    assert.equal(journal.locks.size, 0);
  }
});

test("classifies silent provider alteration as a system-owned failure and releases only after containment", async () => {
  const expected = projection();
  const publishFingerprint = await fingerprintDirectProjection(expected);
  const journal = new MemoryExecutionJournal();
  const calls = [];

  await assert.rejects(
    () => executeSafeSingleCampaign({
      execution_id: "execution-1",
      config: { token: "secret", account: "moxstudio" },
      projection: expected,
      authority: authority(publishFingerprint),
      journal,
      fetcher: successfulFetcher(expected, journal, calls, { keywordValue: "silently altered" }),
      now: () => "2026-08-22T00:41:00.000Z",
    }),
    (error) => {
      assert.equal(error.code, "P0_DIRECT_GRAPH_MISMATCH");
      assert.equal(error.partial.containment, "NON_SERVING_CONFIRMED");
      assert.equal(error.partial.account_lock, "RELEASED");
      return true;
    },
  );
  assert.equal(journal.records.get("execution-1").status, "SYSTEM_FAILED");
  assert.equal(journal.locks.has("moxstudio"), false);
});

test("releases the account writer after a definite per-item provider rejection", async () => {
  const expected = projection();
  const publishFingerprint = await fingerprintDirectProjection(expected);
  const journal = new MemoryExecutionJournal();

  await assert.rejects(
    () => executeSafeSingleCampaign({
      execution_id: "execution-1",
      config: { token: "secret", account: "moxstudio" },
      projection: expected,
      authority: authority(publishFingerprint),
      journal,
      fetcher: async (url, init) => {
        const body = JSONbig.parse(String(init.body));
        const service = new URL(url).pathname.split("/").at(-1);
        assert.equal(journal.records.get("execution-1").pending_dispatch.operation, `${service}.${body.method}`);
        return jsonResponse({ AddResults: [{ Errors: [{ Code: 5001, Message: "Недельный бюджет ниже минимального" }] }] });
      },
      now: () => "2026-08-22T00:41:00.000Z",
    }),
    (error) => {
      assert.equal(error.code, "P0_DIRECT_ITEM_FAILED");
      assert.equal(error.partial.account_lock, "RELEASED");
      assert.deepEqual(error.partial.provider_issues, [{
        operation: "Campaigns.add",
        severity: "ERROR",
        code: 5001,
        message: "Недельный бюджет ниже минимального",
        details: "",
      }]);
      return true;
    },
  );
  assert.equal(journal.locks.has("moxstudio"), false);
  assert.equal(journal.records.get("execution-1").status, "PROVIDER_REJECTED");
  assert.equal(journal.records.get("execution-1").pending_dispatch, null);

  let retryCalls = 0;
  await assert.rejects(
    () => executeSafeSingleCampaign({
      execution_id: "execution-1",
      config: { token: "secret", account: "moxstudio" },
      projection: expected,
      authority: authority(publishFingerprint),
      journal,
      fetcher: async () => {
        retryCalls += 1;
        throw new Error("definite rejection must not be retried blindly");
      },
    }),
    (error) => error.code === "P0_EXECUTION_ALREADY_TERMINAL",
  );
  assert.equal(retryCalls, 0);
});

test("restart continues only from exact known provider IDs without duplicating parent or completed children", async () => {
  const expected = projection();
  const publishFingerprint = await fingerprintDirectProjection(expected);
  const journal = new MemoryExecutionJournal();
  const identity = {
    execution_id: "execution-1",
    account: "moxstudio",
    publish_fingerprint: publishFingerprint,
    capability_profile_id: "direct-v501-unified-search-explicit-text",
    capability_profile_version: "1.0.0",
  };
  journal.records.set("execution-1", {
    schema_version: "p0-direct-single-campaign-execution-v1",
    ...identity,
    status: "AD_GROUP_CREATED",
    lock_state: "HELD",
    provider_ids: {
      campaign_id: "90071992547409931",
      ad_group_id: "90071992547409932",
      keyword_id: null,
      ad_ids: [],
    },
    completed_steps: ["CAMPAIGN_CREATED", "NON_SERVING_CONFIRMED", "AD_GROUP_CREATED"],
    pending_dispatch: null,
    result: {},
    created_at: "2026-08-22T00:40:00.000Z",
    updated_at: "2026-08-22T00:40:30.000Z",
  });
  journal.locks.set("moxstudio", "execution-1");
  const calls = [];

  const result = await executeSafeSingleCampaign({
    execution_id: "execution-1",
    config: { token: "secret", account: "moxstudio" },
    projection: expected,
    authority: authority(publishFingerprint),
    journal,
    fetcher: successfulFetcher(expected, journal, calls),
    now: () => "2026-08-22T00:41:00.000Z",
  });

  assert.equal(result.campaign_id, "90071992547409931");
  assert.equal(result.ad_group_id, "90071992547409932");
  assert.equal(calls.includes("campaigns.add"), false);
  assert.equal(calls.includes("campaigns.suspend"), false);
  assert.equal(calls.includes("adgroups.add"), false);
  assert.equal(calls.filter((operation) => operation === "keywords.add").length, 1);
  assert.equal(calls.filter((operation) => operation === "ads.add").length, 1);
});

test("preserves per-item Direct warnings without losing native 64-bit IDs", async () => {
  const expected = projection();
  const publishFingerprint = await fingerprintDirectProjection(expected);
  const journal = new MemoryExecutionJournal();
  const calls = [];
  const warning = { Code: 1001, Message: "Название было нормализовано", Details: "Provider normalization" };

  const result = await executeSafeSingleCampaign({
    execution_id: "execution-1",
    config: { token: "secret", account: "moxstudio" },
    projection: expected,
    authority: authority(publishFingerprint),
    journal,
    fetcher: successfulFetcher(expected, journal, calls, { campaignWarnings: [warning] }),
    now: () => "2026-08-22T00:41:00.000Z",
  });

  assert.deepEqual(result.provider_issues, [{
    operation: "Campaigns.add",
    severity: "WARNING",
    code: 1001,
    message: "Название было нормализовано",
    details: "Provider normalization",
  }]);
  assert.equal(journal.records.get("execution-1").provider_ids.campaign_id, "90071992547409931");
});

test("releases single-writer lock after verified non-serving containment", () => {
  assert.equal(mustHoldAccountLock({ campaign_id: "713721517", containment: "NON_SERVING_CONFIRMED" }), false);
});

test("holds single-writer lock only while external state is ambiguous", () => {
  assert.equal(mustHoldAccountLock({ containment: "RECONCILIATION_REQUIRED" }), true);
  assert.equal(mustHoldAccountLock({ campaign_id: "1", containment: "MANUAL_RECONCILIATION_REQUIRED" }), true);
});
