import assert from "node:assert/strict";
import test from "node:test";

import {
  P0_E2E_FIXTURE_SCENARIO,
  localP0E2EFixtureScenario,
} from "../lib/p0-e2e-boundary.ts";

test("deterministic provider fixture is available only for the exact localhost scenario", () => {
  assert.equal(
    localP0E2EFixtureScenario(
      "http://localhost:4173/api/p0",
      P0_E2E_FIXTURE_SCENARIO,
    ),
    P0_E2E_FIXTURE_SCENARIO,
  );
  assert.equal(
    localP0E2EFixtureScenario(
      "http://127.0.0.1:4173/api/p0",
      P0_E2E_FIXTURE_SCENARIO,
    ),
    P0_E2E_FIXTURE_SCENARIO,
  );
  assert.equal(
    localP0E2EFixtureScenario(
      "https://production.example/api/p0",
      P0_E2E_FIXTURE_SCENARIO,
    ),
    null,
  );
  assert.equal(
    localP0E2EFixtureScenario(
      "http://localhost:4173/api/p0",
      "unknown-scenario",
    ),
    null,
  );
  assert.equal(
    localP0E2EFixtureScenario(
      "http://localhost:4173/api/p0",
      undefined,
    ),
    null,
  );
});
