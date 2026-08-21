import assert from "node:assert/strict";
import test from "node:test";

import { normalizePublicHttpsUrl } from "../lib/site-url.ts";

test("adds HTTPS to a bare public domain", () => {
  assert.equal(normalizePublicHttpsUrl("mox-studio.ru").toString(), "https://mox-studio.ru/");
  assert.equal(normalizePublicHttpsUrl("mox-studio.ru/services").toString(), "https://mox-studio.ru/services");
});

test("upgrades an explicitly entered HTTP address", () => {
  assert.equal(normalizePublicHttpsUrl("http://mox-studio.ru/").toString(), "https://mox-studio.ru/");
});

test("rejects unsafe URL components and private hosts", () => {
  assert.throws(() => normalizePublicHttpsUrl("https://user:pass@example.ru"), /credentials/u);
  assert.throws(() => normalizePublicHttpsUrl("https://example.ru/?access_token=fixture-only"), /Credential-bearing/u);
  assert.throws(() => normalizePublicHttpsUrl("https://example.ru/?session_id=fixture-only"), /Credential-bearing/u);
  assert.throws(() => normalizePublicHttpsUrl("https://example.ru:8443"), /нестандартного порта/u);
  assert.throws(() => normalizePublicHttpsUrl("https://127.0.0.1"), /частные адреса/u);
  assert.throws(() => normalizePublicHttpsUrl("https://169.254.1.1"), /частные адреса/u);
  assert.throws(() => normalizePublicHttpsUrl("https://[fe80::1]"), /частные адреса/u);
  assert.throws(() => normalizePublicHttpsUrl("https://[::ffff:127.0.0.1]"), /частные адреса/u);
});
