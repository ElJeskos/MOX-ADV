import assert from "node:assert/strict";
import test from "node:test";

import { mustHoldAccountLock } from "../lib/execution-safety.ts";

test("releases single-writer lock after verified non-serving containment", () => {
  assert.equal(mustHoldAccountLock({ campaign_id: "713721517", containment: "NON_SERVING_CONFIRMED" }), false);
});

test("holds single-writer lock only while external state is ambiguous", () => {
  assert.equal(mustHoldAccountLock({ containment: "RECONCILIATION_REQUIRED" }), true);
  assert.equal(mustHoldAccountLock({ campaign_id: "1", containment: "MANUAL_RECONCILIATION_REQUIRED" }), true);
});
