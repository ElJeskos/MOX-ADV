import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const clientSource = await readFile(new URL("../app/P0Client.tsx", import.meta.url), "utf8");
const styles = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");

test("operator UI permanently labels landing analysis advisory and non-blocking with honest evidence disclosure", () => {
  assert.match(clientSource, /ПОСАДОЧНАЯ СТРАНИЦА · ТОЛЬКО РЕКОМЕНДАЦИИ/u);
  assert.match(clientSource, /РЕКОМЕНДАЦИИ · НЕ БЛОКИРУЮТ/u);
  assert.match(clientSource, /не меняют допустимость, готовность к публикации, оценку, место, пороги, калибровку или отпечаток публикации/u);
  assert.match(clientSource, /Недостаточно доказательств/u);
  assert.match(clientSource, /Недостаток доказательств раскрыт явно/u);
  assert.match(clientSource, /Lighthouse:.*\/5 последовательных запусков для компьютера/u);
  assert.match(clientSource, /Незавершённые проверки axe-core/u);
  assert.match(clientSource, /Все подробности · типы доказательств, состояния и версии инструментов/u);
  assert.match(clientSource, /landingAdvisoryPriorities\(run\)/u);
});

test("advisory has a visually permanent boundary and a three-column priority surface before details", () => {
  assert.match(styles, /\.landing-advisory \{[^}]*border: 2px solid/u);
  assert.match(styles, /\.advisory-priorities ol \{[^}]*grid-template-columns: repeat\(3,/u);
  assert.match(clientSource, /Приоритеты · максимум 3/u);
  assert.ok(clientSource.indexOf("advisory-priorities") < clientSource.indexOf("advisory-details"));
});
