import assert from "node:assert/strict";
import test from "node:test";

import { devServerConfig } from "../lib/dev-server.ts";

test("dev server ignores mutable Wrangler runtime state", () => {
  for (const seatbeltSandbox of [false, true]) {
    const config = devServerConfig(seatbeltSandbox);
    assert.ok(config?.watch?.ignored?.includes("**/.wrangler/**"));
  }
});
