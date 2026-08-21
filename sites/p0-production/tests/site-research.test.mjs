import assert from "node:assert/strict";
import test from "node:test";

import {
  researchPublicFirstPartySite,
  SiteResearchError,
} from "../lib/site-research.ts";

function html(body, init = {}) {
  return new Response(`<!doctype html><title>Owner</title><h1>Стать участником</h1>${body}`, {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8", ...init.headers },
    ...init,
  });
}

function transport(routes, resolved = ["93.184.216.34"]) {
  const requests = [];
  return {
    requests,
    async resolveHostname(hostname) {
      requests.push({ kind: "resolve", hostname });
      return resolved;
    },
    async fetch(input, init) {
      const url = String(input);
      requests.push({ kind: "fetch", url, redirect: init?.redirect });
      const value = routes[url];
      if (!value) throw new Error(`Unexpected URL ${url}`);
      return typeof value === "function" ? value() : value;
    },
  };
}

test("researches a bounded public first-party HTTPS target with redirects handled manually", async () => {
  const adapter = transport({
    "https://www.owner.example/": new Response(null, {
      status: 301,
      headers: { location: "https://owner.example/" },
    }),
    "https://owner.example/": html('<p>Руководители компаний оставляют заявку.</p><a href="/participate">Участие</a>'),
    "https://owner.example/participate": html("<form></form><p>Отправьте заявку на участие.</p>"),
  });
  const result = await researchPublicFirstPartySite("https://www.owner.example/", {
    ...adapter,
    now: () => "2026-08-21T10:00:00.000Z",
    limits: { maximumPages: 2, maximumRedirects: 2, maximumTotalBytes: 100_000 },
  });
  assert.equal(result.url, "https://owner.example/");
  assert.equal(result.pages.length, 2);
  assert.equal(result.forms_detected, 1);
  assert.equal(result.research.scope, "FIRST_PARTY_PUBLIC_HTTPS");
  assert.equal(adapter.requests.filter((item) => item.kind === "fetch").every((item) => item.redirect === "manual"), true);
});

test("rejects private DNS results before contacting the target", async () => {
  const adapter = transport({ "https://owner.example/": html("<p>Never fetched</p>") }, ["10.0.0.8"]);
  await assert.rejects(
    researchPublicFirstPartySite("https://owner.example/", { ...adapter, now: () => "2026-08-21T10:00:00.000Z" }),
    (error) => error instanceof SiteResearchError && error.code === "SITE_TARGET_PRIVATE",
  );
  assert.equal(adapter.requests.some((item) => item.kind === "fetch"), false);
});

test("rejects a cross-party redirect before following it", async () => {
  const adapter = transport({
    "https://owner.example/": new Response(null, {
      status: 302,
      headers: { location: "https://evil.example/collect" },
    }),
    "https://evil.example/collect": html("<p>Never fetched</p>"),
  });
  await assert.rejects(
    researchPublicFirstPartySite("https://owner.example/", { ...adapter, now: () => "2026-08-21T10:00:00.000Z" }),
    (error) => error instanceof SiteResearchError && error.code === "SITE_REDIRECT_UNSAFE",
  );
  assert.equal(adapter.requests.some((item) => item.url === "https://evil.example/collect" && item.kind === "fetch"), false);
});

test("cancels an oversized streaming response at the configured byte limit", async () => {
  let cancelled = false;
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(new Uint8Array(700));
      controller.enqueue(new Uint8Array(700));
    },
    cancel() { cancelled = true; },
  });
  const adapter = transport({
    "https://owner.example/": new Response(stream, { headers: { "content-type": "text/html" } }),
  });
  await assert.rejects(
    researchPublicFirstPartySite("https://owner.example/", {
      ...adapter,
      now: () => "2026-08-21T10:00:00.000Z",
      limits: { maximumPages: 1, maximumRedirects: 1, maximumTotalBytes: 1_000 },
    }),
    (error) => error instanceof SiteResearchError && error.code === "SITE_RESPONSE_TOO_LARGE",
  );
  assert.equal(cancelled, true);
});

test("rejects credential-bearing, local and link-local URL literals before resolution", async () => {
  const adapter = transport({});
  for (const url of [
    "https://user:secret@owner.example/",
    "https://localhost/",
    "https://169.254.1.1/",
    "https://[fe80::1]/",
  ]) {
    await assert.rejects(researchPublicFirstPartySite(url, { ...adapter, now: () => "2026-08-21T10:00:00.000Z" }));
  }
  assert.deepEqual(adapter.requests, []);
});
