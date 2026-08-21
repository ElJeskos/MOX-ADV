import assert from "node:assert/strict";
import test from "node:test";

import {
  verifyDirectAccountBinding,
  verifyMetrikaCounterBinding,
  YandexContextError,
} from "../lib/yandex-context.ts";

function json(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

test("verifies the exact Direct advertiser login through the official clients API", async () => {
  const requests = [];
  const result = await verifyDirectAccountBinding(
    { token: "fixture-only", expectedAccount: "owner-account" },
    async (input, init) => {
      requests.push({ input: String(input), init });
      return json({ result: { Clients: [{ Login: "owner-account", ClientId: "9007199254740993" }] } });
    },
    () => "2026-08-21T10:00:00.000Z",
  );
  assert.equal(requests.length, 1);
  assert.equal(requests[0].input, "https://api.direct.yandex.com/json/v501/clients");
  assert.equal(requests[0].init.method, "POST");
  assert.equal(requests[0].init.headers["Client-Login"], "owner-account");
  assert.deepEqual(result, {
    authority: "VERIFIED",
    access: "YANDEX_DIRECT_API_V501",
    account: "owner-account",
    client_id: "9007199254740993",
    binding: { expected_account: "owner-account", api_account: "owner-account", matched: true },
    observed_at: "2026-08-21T10:00:00.000Z",
  });
  assert.doesNotMatch(JSON.stringify(result), /fixture-only/u);
});

test("rejects a Direct response bound to another account", async () => {
  await assert.rejects(
    verifyDirectAccountBinding(
      { token: "fixture-only", expectedAccount: "owner-account" },
      async () => json({ result: { Clients: [{ Login: "other-account", ClientId: "42" }] } }),
      () => "2026-08-21T10:00:00.000Z",
    ),
    (error) => error instanceof YandexContextError && error.code === "DIRECT_ACCOUNT_BINDING_MISMATCH",
  );
});

test("verifies exact Metrika counter and goal authority through management APIs", async () => {
  const urls = [];
  const result = await verifyMetrikaCounterBinding(
    { token: "fixture-only", expectedCounterId: "424242", expectedGoalId: "1717" },
    async (input) => {
      const url = String(input);
      urls.push(url);
      if (url.endsWith("/counter/424242")) return json({ counter: { id: 424242, name: "Owner", time_zone_name: "Europe/Moscow" } });
      if (url.endsWith("/counter/424242/goals")) return json({ goals: [{ id: 1717, name: "Lead" }] });
      throw new Error(`Unexpected URL ${url}`);
    },
    () => "2026-08-21T10:00:00.000Z",
  );
  assert.deepEqual(urls, [
    "https://api-metrika.yandex.net/management/v1/counter/424242",
    "https://api-metrika.yandex.net/management/v1/counter/424242/goals",
  ]);
  assert.deepEqual(result, {
    authority: "VERIFIED",
    access: "YANDEX_METRIKA_MANAGEMENT_AND_REPORTS_API",
    counter_id: "424242",
    goal_id: "1717",
    time_zone: "Europe/Moscow",
    binding: { expected_counter_id: "424242", api_counter_id: "424242", matched: true },
    goal_binding: { expected_goal_id: "1717", api_goal_id: "1717", matched: true },
    observed_at: "2026-08-21T10:00:00.000Z",
  });
  assert.doesNotMatch(JSON.stringify(result), /fixture-only/u);
});

test("rejects missing Metrika goal authority and mismatched counter identity", async (t) => {
  await t.test("goal unavailable", async () => {
    await assert.rejects(
      verifyMetrikaCounterBinding(
        { token: "fixture-only", expectedCounterId: "424242", expectedGoalId: "1717" },
        async (input) => String(input).endsWith("/goals")
          ? json({ goals: [] })
          : json({ counter: { id: 424242 } }),
        () => "2026-08-21T10:00:00.000Z",
      ),
      (error) => error instanceof YandexContextError && error.code === "METRIKA_GOAL_BINDING_MISMATCH",
    );
  });
  await t.test("counter mismatch", async () => {
    await assert.rejects(
      verifyMetrikaCounterBinding(
        { token: "fixture-only", expectedCounterId: "424242", expectedGoalId: "1717" },
        async () => json({ counter: { id: 999999 } }),
        () => "2026-08-21T10:00:00.000Z",
      ),
      (error) => error instanceof YandexContextError && error.code === "METRIKA_COUNTER_BINDING_MISMATCH",
    );
  });
});
