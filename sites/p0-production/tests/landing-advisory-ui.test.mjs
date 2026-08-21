import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const clientSource = await readFile(new URL("../app/P0Client.tsx", import.meta.url), "utf8");
const styles = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");

test("operator UI permanently labels landing analysis advisory and non-blocking with honest evidence disclosure", () => {
  assert.match(clientSource, /LANDING PAGE · ADVISORY ONLY/u);
  assert.match(clientSource, /ADVISORY · NON-BLOCKING/u);
  assert.match(clientSource, /не меняют eligibility, publish readiness, score, rank, thresholds, calibration или publish fingerprint/u);
  assert.match(clientSource, /Недостаточно доказательств/u);
  assert.match(clientSource, /Insufficient evidence раскрыто явно/u);
  assert.match(clientSource, /Lighthouse:.*\/5 sequential desktop runs/u);
  assert.match(clientSource, /axe incomplete/u);
  assert.match(clientSource, /Все details · evidence types, statuses и tool versions/u);
  assert.match(clientSource, /landingAdvisoryPriorities\(run\)/u);
});

test("advisory has a visually permanent boundary and a three-column priority surface before details", () => {
  assert.match(styles, /\.landing-advisory \{[^}]*border: 2px solid/u);
  assert.match(styles, /\.advisory-priorities ol \{[^}]*grid-template-columns: repeat\(3,/u);
  assert.match(clientSource, /Приоритеты · максимум 3/u);
  assert.ok(clientSource.indexOf("advisory-priorities") < clientSource.indexOf("advisory-details"));
});
