# Решение: объяснимый pre-launch viability score `0–100`

**Ticket:** [#93 «Спроектировать объяснимый viability score до запуска»](https://github.com/ElJeskos/MOX-ADV/issues/93)  
**Карта:** [#89](https://github.com/ElJeskos/MOX-ADV/issues/89)  
**Срез решения:** 2026-08-21  
**Статус:** implementation-ready decision brief, не код.

## Summary

`viability score` — это детерминированный сравнительный приоритет **уже eligible** Campaign Drafts, а не вероятность, прогноз CPA/конверсий/прибыли и не обещание эффективности. Hard eligibility проверяется до score; карточка показывает `score`, rank, интервал неопределённости, качество evidence, blockers и полный вклад полей.

Решение использует прозрачную взвешенную сумму семи размерностей, midpoint только как явно обозначенный вычислительный placeholder для необязательного отсутствующего evidence, interval bounds для неизвестного и консервативное скрытие лишь когда даже верхняя граница ниже versioned threshold. Landing audit остаётся advisory-only и полностью исключён из eligibility, формулы, threshold и калибровки.

---

## 1. Принятый контекст

Решение совместимо с:

- `CONTEXT.md`: Recommendation Set связывает одну Campaign Strategy, один Analytics Evidence Snapshot и eligible/suppressed/ranked Drafts; один Draft — одна будущая реальная кампания;
- `docs/adr/0001-agent-owns-safe-work.md`: агент самостоятельно доисследует устранимые gaps, а Human Decision Gate возникает только при Material Uncertainty;
- [resolution #90](https://github.com/ElJeskos/MOX-ADV/issues/90#issuecomment-5369315828): versioned evidence snapshot, claim → record → raw provenance, отдельные blockers/confidence, честный `UNAVAILABLE`;
- [resolution #91](https://github.com/ElJeskos/MOX-ADV/issues/91#issuecomment-5369104990): Wordstat — scoped lower bound спроса, cost — source-labelled range, отсутствие строки/источника не равно нулю;
- [resolution #94](https://github.com/ElJeskos/MOX-ADV/issues/94#issuecomment-5369542106): finite fan-out, exact publish projection/fingerprint, structural hidden reasons, `EVIDENCE_GAP` не превращается в «слабый» Draft;
- текущим `sites/p0-production/lib/campaign-fanout.ts`: Recommendation Set уже содержит immutable strategy/evidence lineage, visible/hidden dispositions и fingerprints, но числового score-контракта ещё нет.

### Нормативное утверждение

> `score=73` означает только: «по правилам `score_contract_version` этот eligible Draft имеет 73 из 100 сравнительных баллов на зафиксированных pre-launch inputs». Он **MUST NOT** называться шансом успеха, прогнозом результата, ожидаемым uplift или platform optimization score.

---

## 2. Hard eligibility отдельно от score

### 2.1 Порядок вычисления

```text
validate immutable inputs
→ evaluate hard gates
→ if ineligible: no score, terminal blocker/suppression
→ if eligible: compute seven dimensions, uncertainty interval and score
→ rank eligible candidates
→ apply conservative hidden-threshold rule
```

Hard blocker нельзя компенсировать высоким средним баллом — это уже принято в #90 и соответствует требованию прозрачного управления риском: NIST AI RMF требует документировать назначение, ограничения, измерение и мониторинг системы, а не скрывать риск агрегатом ([NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework)).

### 2.2 Hard gates

Draft получает `eligibility=INELIGIBLE`, `score=null`, `rank=null`, если выполнено хотя бы одно:

1. Strategy revision не `APPROVED`, superseded либо отсутствуют immutable `strategy_revision_id` / evidence snapshot lineage.
2. Не определены material Strategy facts: product/offer, audience, qualified outcome, exclusions, goal, geography/period, landing URL, budget, target result cost или core message.
3. Есть unresolved material conflict по product/offer/audience/goal/geography/budget/landing, который способен изменить publish projection.
4. Нет publishable product–offer–landing relation либо landing URL/домен запрещён policy. **Содержание landing audit при этом не учитывается.**
5. Direct account binding/currency/edit grant/campaign type или required child-object capability не подтверждены свежим API preflight; exact projection не проходит локальную schema/policy validation.
6. Exact duplicate / identical publish fingerprint уже существует без explicit exception.
7. Demand disposition из #91/#94 равен доказанному `NO_DEMAND`, `INSUFFICIENT_STANDALONE_CAPACITY` для несовместимого unpackable cluster либо нет уникальной publish phrase после deduplication. `UNAVAILABLE`/`EVIDENCE_GAP` не является no-demand.
8. Нарушены business/legal exclusions, Gate 0, Mandate или безопасный non-serving publish contract.

Blocker хранит `code`, `rule_id`, `rule_version`, `input_pointer`, `claim_ids`, `evidence_ids`, `observed_at`, `remediation`. После исправления создаётся новая Draft revision и полный пересчёт; прежний результат не переписывается.

---

## 3. Точные допустимые входы

Score **MUST** читать только immutable pre-launch данные, доступные до `scored_at`:

| Вход | Разрешённые поля |
|---|---|
| `CampaignStrategyRevision` | IDs/revision/status; product, offer, audience, qualified outcome, exclusions, goal, geography, period, landing URL, weekly/monthly budget, target result cost, core message |
| `CampaignDraftRevision` | axes/delivery key; variant/control/hypothesis; keyword clusters; exact editable fields; exact Direct publish projection; publish/treatment fingerprints |
| `AnalyticsEvidenceSnapshot` (#90) | atomic claims, source/provenance, confidence vector, conflicts, coverage, freshness, existing Direct inventory, measurement binding |
| `DemandCostSnapshot` (#91) | Wordstat lower-bound unique assigned rows and scope; `hasSearchVolume`; seasonality status; source-labelled cost envelope; comparability/sample metadata |
| `DirectCapabilitySnapshot` (#94) | account/currency/grants/restrictions, supported campaign/group/ad/criteria/placement/strategy fields, freshness and exact preflight result |
| `MeasurementReadinessSnapshot` | Metrica counter/goal API facts, goal↔qualified-outcome mapping, attribution/timezone/window contract, tagging/read access status |
| `ScorePolicy` | semantic version, weights, bins/mappings, cohort rule, missing policy, tie epsilon, hidden threshold, source TTL registry, hashes |

Запрещены как score inputs:

- любые impressions/clicks/cost/conversions/revenue/CPA/CTR/CR после запуска **оцениваемого** Draft;
- outcomes sibling Drafts, ставшие известными после общего `scored_at`;
- LLM memory, скрытая model confidence, chain of thought, нераскрываемый vendor/Direct optimization score;
- предполагаемые бюджеты/CPC/конверсии конкурентов;
- browser cabinets;
- landing audit findings, Lighthouse/axe/LLM landing оценки и любые производные от них;
- ручная оценка «кажется перспективным» без typed claim/evidence.

---

## 4. Формула `0–100`

### 4.1 Общая формула

Семь размерностей имеют значение `d_i ∈ [0,100]` и фиксированные веса, сумма которых равна 100:

```text
raw_score =
    0.18 × demand
  + 0.12 × cost
  + 0.20 × economics
  + 0.18 × offer_audience_fit
  + 0.12 × direct_feasibility
  + 0.10 × measurement
  + 0.10 × evidence_quality

score = round_half_up(raw_score, 0)       # integer 0…100
score_raw = round_half_up(raw_score, 4)   # audit/rank
```

Веса — прозрачная policy v1, а не обученные коэффициенты и не утверждение о причинной силе факторов. Любое изменение веса требует новой версии и параллельного backtest; исторические scores не пересчитываются молча.

### 4.2 Общие функции

- `bool_score(TRUE)=100`, `FALSE=0`, `UNKNOWN=50`.
- `mean_known_placeholders(...)` — обычное среднее subfeatures, где `UNKNOWN=50`, но неизвестное одновременно расширяет uncertainty interval; это **не imputation факта**.
- `midrank_percentile(x, cohort)` для `n>1`: `100 × (average_rank(x)-1)/(n-1)`; одинаковые значения получают одинаковый midrank. Для `n=1` результат `50`.
- Cohort фиксируется как все hard-eligible candidates одного `RecommendationSet`, Strategy revision, geo/currency, demand/cost snapshot и management profile. Его fingerprint хранится; скрытые eligible candidates входят в cohort, чтобы UI selection не менял score.

### 4.3 Размерности

#### A. Demand — 18%

```text
demand = mean(volume_rank, has_volume, seasonality_support)
```

- `volume_rank`: midrank percentile `log1p(cluster_observed_30d_count)` среди candidates с **сопоставимыми** endpoint/operator/region/device/batch scopes; unavailable/incomparable = `50`.
- `has_volume`: Direct `YES=100`, `NO=0`, `UNKNOWN=50`.
- `seasonality_support`: current complete-period share against same-calendar-period historical median: ratio `≥1.00 →100`, `0.75–<1 →75`, `0.50–<0.75 →50`, `<0.50 →25`; insufficient/unavailable = `50`.

Wordstat count остаётся `LOWER_BOUND_OBSERVED_TOP_ROWS`, не прогнозом показов/кликов. Доказанный no-demand обрабатывается gate, а не нулём в среднем.

#### B. Cost — 12%

Cost сравнивается только внутри одного source kind и сопоставимого scope:

```text
cost = 100 - midrank_percentile(cost_reference, comparable_cost_cohort)
```

`cost_reference`: midpoint scenario range для Live 4/KeywordBids либо weighted historical mean для own-history; `UNAVAILABLE/CONFLICTING/incomparable → 50`. Источники не усредняются. Более низкий reference cost получает больший сравнительный балл, но число остаётся наблюдаемым scenario/proxy/prior, не будущим CPC.

#### C. Economics — 20%

```text
planned_result_units = monthly_budget / target_result_cost
cost_to_target_ratio = cost_high / target_result_cost   # only if comparable cost exists

economics = mean(capacity_score, cost_ratio_score, consistency_score)
```

- `capacity_score`: `<3 →0`, `3–<5 →25`, `5–<10 →50`, `10–<20 →75`, `≥20 →100` planned target-cost units per month.
- `cost_ratio_score`: `≤0.05 →100`, `≤0.10 →80`, `≤0.20 →50`, `≤0.33 →20`, `>0.33 →0`, unavailable → `50`.
- `consistency_score`: 100, если positive budget/target cost/currency/period согласованы и standalone capacity rule пройден; unresolved non-material mismatch = 50; contradiction = 0 (material contradiction должен стать blocker).

Это арифметика ограничения: она не утверждает, что planned result units будут получены или что conversion rate достигнет нужного уровня.

#### D. Offer–audience fit — 18%

```text
offer_audience_fit = mean(
  product_offer_supported,
  audience_need_supported,
  offer_addresses_need,
  message_matches_approved_offer_and_audience
)
```

Каждый predicate: `100`, если есть non-conflicted eligible claim с evidence tier 1/2; `75` для tier 3 indicative; `50` для unknown/inference-only; `0` для явного противоречия. Ни один landing audit predicate сюда не входит.

#### E. Direct feasibility — 12%

```text
direct_feasibility = mean(
  account_and_currency_ready,
  campaign_and_group_type_supported,
  strategy_and_placement_supported,
  criteria_and_ad_projection_supported,
  limits_fit_projection,
  local_schema_policy_validation_passed
)
```

Каждый subfeature: `TRUE=100`, `UNKNOWN=50`, `FALSE=0`; material `FALSE` обычно является eligibility blocker. Это сохраняет различие между документированной schema capability, account-specific preflight и будущей moderation.

#### F. Measurement — 10%

```text
measurement = mean(
  metrica_counter_readable,
  goal_exists_and_active,
  goal_maps_to_qualified_outcome,
  landing_binding_observed,
  attribution_timezone_window_frozen,
  diagnostic_and_maturity_contract_frozen
)
```

`TRUE=100`, `UNKNOWN=50`, `FALSE=0`. `landing_binding_observed` означает только техническую привязку counter/URL, не качество landing и не landing audit.

#### G. Evidence quality — 10%

Для material claims, реально использованных шестью предыдущими dimensions, сначала считаются пять компонентов:

- source quality `A/B/C/D/U = 100/80/60/30/0`;
- freshness `current/aging/stale/unknown = 100/70/30/0`;
- consistency `corroborated/single/conflicted/scope_mismatch = 100/70/20/0`;
- coverage `complete/sampled_with_denominator/partial/unknown = 100/70/40/0`;
- uncertainty `max(0, 100 − 20 × material_uncertainty_reason_count)`.

`claim_quality` — среднее пяти компонентов; `evidence_quality` — среднее claim quality по уникальным material claims (не по числу ссылок, чтобы дубли evidence не повышали score). Если material claim set пуст, значение `0`.

---

## 5. Missing data и uncertainty

1. Агент сначала пытается устранить gap разрешёнными источниками по ADR-0001.
2. Отсутствующее необязательное значение — `UNKNOWN/UNAVAILABLE`, никогда `0`, fabricated mean или отрицательный факт.
3. В point score unknown получает policy midpoint `50`; карточка явно показывает missing reason, affected dimension и evidence-quality effect.
4. Для каждого unknown elementary subfeature вычисляются bounds: один прогон с unknown=`0`, второй с unknown=`100`:

```text
score_lower = floor(weighted_score(all unknown=0))
score_upper = ceil(weighted_score(all unknown=100))
uncertainty_width = score_upper - score_lower
```

5. Correlated unknowns с одним cause получают один `uncertainty_group_id`; UI не называет bounds статистическим confidence interval. Это deterministic sensitivity envelope.
6. Material unknown из hard gates даёт `BLOCKED_UNKNOWN`, а не score.
7. Conflict не заменяется midpoint: material conflict блокирует; non-material conflict получает заданный predicate score и раскрывается.
8. `EVIDENCE_GAP` сам по себе не является основанием скрыть Draft.

---

## 6. Rank, ties и hidden threshold

### Rank

Eligible candidates сортируются по:

1. `score_raw` descending;
2. `evidence_quality` descending;
3. `uncertainty_width` ascending.

Если после этого разница `score_raw ≤ 0.5`, evidence quality одинакова до 0.5 и interval bounds пересекаются, candidates получают один display rank (`competition ranking`: `1, 1, 3`). Stable `draft_id` задаёт только порядок карточек внутри tie и **не разрывает смысловую ничью**.

### Hidden threshold

Policy v1: `hidden_threshold=45`, но eligible Draft скрывается по score только если:

```text
score_upper < 45
AND evidence_quality >= 60
AND no unresolved EVIDENCE_GAP
```

Так слабость должна быть устойчивой даже при благоприятном разрешении unknown. При `score<45`, но `score_upper≥45` Draft остаётся видимым с `UNCERTAIN_NEAR_THRESHOLD`. Structural reasons из #94 (`EXACT_DUPLICATE`, `NO_MATERIAL_DELTA`, `NO_DEMAND`, capacity limit и т. п.) применяются отдельно и имеют приоритет. Hidden Draft сохраняет score/explanation и доступен в audited disclosure.

Threshold не означает «не сработает»; это versioned правило сокращения default canvas.

---

## 7. Объяснение и field-level delta

### 7.1 Обязательная карточка объяснения

```yaml
score: 68
score_raw: 67.8342
score_interval: {lower: 54, upper: 76, semantics: SENSITIVITY_ENVELOPE}
rank: 2
rank_tied: false
label: COMPARATIVE_PRELAUNCH_PRIORITY_NOT_A_FORECAST
contract_version: viability-score/1.0.0
input_fingerprint: sha256(...)
cohort_fingerprint: sha256(...)
dimensions:
  demand: {value: 72, weight: 0.18, weighted_points: 12.96, inputs: [...], missing: [...]}
  # остальные шесть аналогично
eligibility: {status: ELIGIBLE, blockers: []}
visibility: {status: VISIBLE, rule: score-hidden-v1}
landing_audit_used: false
```

Каждый subfeature раскрывается по цепочке `weighted contribution → normalized rule/bin/rank → input JSON Pointer → claim IDs → evidence IDs → raw locator/transforms/conflicts`.

### 7.2 Пересчёт после ручного изменения

Любое сохранённое изменение material Draft field создаёт новую `draft_revision_id`, projection fingerprint и score result. Delta считается не эвристикой, а полным double-run:

```text
field_delta = score(new_revision, same frozen snapshots/policy)
            - score(old_revision, same frozen snapshots/policy)
```

`ScoreDeltaExplanation` содержит:

- список changed JSON Pointers и old/new values (секреты redacted);
- old/new eligibility и blockers;
- old/new каждого elementary feature, dimension и weighted points;
- direct contribution delta каждой dimension;
- cohort-mediated deltas всех затронутых Drafts, если правка меняет comparable cohort/ranks;
- old/new total, interval, rank, tie и hidden state;
- unchanged snapshot/policy hashes.

Если edit меняет Strategy-owned field, старая Recommendation Set superseded и строится новая; нельзя показывать delta как локальную Draft-правку. Если во время edit обновился evidence snapshot/policy, UI обязан разделить `field_delta`, `evidence_delta` и `policy_delta`, а не приписывать всё пользователю.

---

## 8. Versioning и воспроизводимость

`score_contract_version` — SemVer:

- patch: текст/serialization без изменения numeric output;
- minor: новый optional output при идентичной формуле;
- major: веса, bins, mappings, missing/tie/threshold/cohort rules или admissible input semantics изменены.

Каждый `ScoreResult` хранит contract version/digest, implementation build SHA, input/snapshot/cohort fingerprints, `scored_at`, exact normalized features, rounding mode и decision trace. Старый result immutable; новая policy делает parallel rescore с `supersedes`, но не переписывает прежний rank. Recommendation Set нельзя сравнивать между major versions без явного migration report.

Policy release требует schema fixtures, golden vectors, monotonicity/property tests, leakage review, backtest report, owner и effective date. NIST AI RMF прямо ориентирует на lifecycle governance, измерение и документирование ограничений ([NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework)).

---

## 9. Leakage-safe calibration и backtest

### 9.1 Что означает calibration здесь

Score v1 не является вероятностью, поэтому probability calibration к нему неприменима. Calibration означает настройку policy weights/bins/threshold **только на прошлых frozen cohorts** так, чтобы порядок был полезным и стабильным относительно заранее определённой post-launch utility, без утверждения, что `70 = 70%`.

Если позже появится отдельный probabilistic forecast, его нужно выпускать отдельным полем/model version и оценивать calibration curve плюс proper scoring rules: Brier/log loss. Scikit-learn описывает calibration как соответствие предсказанной вероятности наблюдаемой частоте и предупреждает обучать calibrator на данных, независимых от fit ([Probability calibration](https://scikit-learn.org/stable/modules/calibration.html)); Brier/log loss являются proper losses для вероятностных прогнозов ([model evaluation](https://scikit-learn.org/stable/modules/model_evaluation.html)). Их нельзя применять к нынешнему ordinal viability score как будто он probability.

### 9.2 Freeze и dataset

Для каждого исторического случая сохраняются:

- scoring-time Strategy/Draft/evidence/capability/measurement snapshots и policy digest;
- `scored_at` до первого serving event;
- selection/launch decision и propensity, если известна;
- preregistered outcome definition, maturity window, attribution, guardrails;
- later outcomes отдельно, с event-time и ingestion-time.

Feature builder имеет strict `available_at ≤ scored_at`; post-launch tables физически/логически недоступны scoring replay. Любая feature с event/ingestion time позже cutoff — leakage failure. Standard CV нельзя использовать на ordered data, потому что обучение на будущем и оценка на прошлом неуместны; time-aware split сохраняет порядок ([scikit-learn TimeSeriesSplit](https://scikit-learn.org/stable/modules/cross_validation.html#time-series-split)).

### 9.3 Split protocol

1. Deduplicate exact projections and retries.
2. Group all sibling Drafts одной Strategy/Recommendation Set и advertiser/business family в одну partition.
3. Outer temporal rolling-origin split: train/calibration на прошлом, gap не меньше maximum outcome maturity + reporting lag, test — строго более поздний untouched period.
4. Weights/bins/threshold выбираются только во внутренних past folds; один final policy freeze — до просмотра outer test.
5. Все результаты публикуются по advertiser/geo/product/strategy slices и версиям source availability; малые slices маркируются insufficient.
6. Unlaunched/hidden Draft не считается failure. Selection bias показывается явно; предпочтителен безопасный preregistered randomized shortlist. Observational IPS/doubly-robust estimates допустимы только при записанной propensity и assumptions, отдельно от primary report.
7. Ни один backtest outcome автоматически не меняет production policy: новая major policy проходит governance/release.

### 9.4 Outcomes и метрики

До раскрытия test outcomes фиксируется ordinal relevance, например 0–3, из mature qualified-outcome evidence и guardrails. Она не подменяется CTR, если Strategy задаёт qualified result.

Primary ranking metrics:

- `NDCG@k` для качества верхней части shortlist; DCG/NDCG предназначен для ranking с graded relevance ([scikit-learn NDCG](https://scikit-learn.org/stable/modules/model_evaluation.html#discounted-cumulative-gain));
- pairwise concordance / Kendall `τ-b` для порядка и ties;
- top-k regret against observed eligible alternatives, только когда варианты действительно сопоставимо запущены;
- coverage, tie rate, hidden false-negative audit, score/interval stability и monotonicity.

Baselines: stable ID/random order, demand-only, equal known-dimension score и текущая released policy. Report обязательно показывает bootstrap uncertainty по **grouped Recommendation Sets**, а не по отдельным зависимым Drafts. Решение о promotion основывается на заранее заданных minimum effect/stability/guardrail criteria, не на одном лучшем retrospective run.

---

## 10. Проверочные сценарии

1. **Hard blocker не усредняется:** unsupported campaign type при максимальных остальных inputs → `INELIGIBLE`, `score=null`.
2. **Cost unavailable не ноль:** identical Drafts, у одного cost unavailable → cost=50, interval шире, evidence quality ниже; он не получает cost=0 и не скрывается только из-за gap.
3. **Wordstat row absent:** отсутствующая seed row → `null/UNKNOWN`, не demand=0.
4. **No-demand evidence:** verified `hasSearchVolume=NO` + принятое no-demand disposition → hard suppression, не low score.
5. **Landing audit isolation:** изменение любого advisory landing finding не меняет eligibility, seven dimensions, score, rank или hidden state; `landing_audit_used=false`.
6. **Manual message edit:** меняются только fit/Direct predicates, projection fingerprint и explainable deltas; demand/cost остаются идентичны, если cohort не изменён.
7. **Strategy edit:** budget/goal edit supersedes Recommendation Set; локальный Draft delta запрещён.
8. **Tie:** одинаковые raw score/evidence/overlapping bounds → общий rank; `draft_id` меняет только display order.
9. **Conservative hide:** point=40, bounds 32–51 → visible `UNCERTAIN_NEAR_THRESHOLD`; bounds 31–44, evidence≥60/no gap → hidden.
10. **Cohort stability:** UI shortlist/exclusion не меняет cohort fingerprint и scores.
11. **Source conflict:** two cost sources conflict → cost=50 + widened interval/disclosure; источники не усредняются.
12. **Determinism:** byte-equivalent normalized inputs + same policy/cohort → identical features, `score_raw`, rank and trace.
13. **Version isolation:** major policy update creates new result linked by `supersedes`; old result remains reproducible.
14. **Future leakage sentinel:** feature with `available_at > scored_at` makes backtest build fail.
15. **Sibling leakage:** Drafts одной Recommendation Set никогда не оказываются по разные стороны train/test.
16. **Probability-language lint:** UI/API не содержит `% success`, «прогноз», «ожидаемый CPA/uplift» для viability score.
17. **Bounds correctness:** replacing every unknown with 0/100 reproduces stored lower/upper bounds.
18. **Rank delta:** cohort-mediated score/rank changes перечислены отдельно от direct field delta.

---

## 11. Implementation-ready contract

```ts
type ScoreInputV1 = {
  score_contract_version: "viability-score/1.0.0";
  recommendation_set_id: string;
  strategy_revision_id: string;
  draft_revision_id: string;
  analytics_evidence_snapshot_id: string;
  demand_cost_snapshot_id: string;
  direct_capability_snapshot_id: string;
  measurement_snapshot_id: string;
  cohort_draft_revision_ids: string[]; // stable sorted, includes hidden eligible
  scored_at: string;                   // RFC3339
};

type ScoreResultV1 = {
  schema_version: "viability-score-result-v1";
  score_result_id: string;
  eligibility: {
    status: "ELIGIBLE" | "INELIGIBLE" | "BLOCKED_UNKNOWN";
    blockers: Array<{
      code: string; rule_id: string; rule_version: string;
      input_pointer: string; claim_ids: string[]; evidence_ids: string[];
      remediation: string;
    }>;
  };
  score: number | null;
  score_raw: number | null;
  score_lower: number | null;
  score_upper: number | null;
  rank: number | null;
  tied_draft_ids: string[];
  dimensions: Record<
    "demand" | "cost" | "economics" | "offer_audience_fit" |
    "direct_feasibility" | "measurement" | "evidence_quality",
    { value: number; weight: number; weighted_points: number;
      features: Array<{ rule: string; input_pointers: string[]; value: number;
        status: "KNOWN" | "UNKNOWN" | "CONFLICTING";
        claim_ids: string[]; evidence_ids: string[]; uncertainty_group_id?: string }> }
  > | null;
  visibility: {
    status: "VISIBLE" | "HIDDEN";
    reason: string | null;
    threshold_version: "score-hidden-v1";
  };
  explanation: {
    label: "COMPARATIVE_PRELAUNCH_PRIORITY_NOT_A_FORECAST";
    landing_audit_used: false;
  };
  fingerprints: {
    input: string; cohort: string; policy: string; implementation_build: string;
  };
  scored_at: string;
};
```

### Required invariants

- pure deterministic scorer: no network, clock, random, LLM or mutable global state;
- decimal/fixed-point arithmetic and explicit `round_half_up`;
- schema validation before scoring; stable sorting before hashing/ranking;
- score result content-addressed and immutable;
- no score for non-eligible Draft;
- sum(weights)=1 exactly; each dimension/feature bounded 0–100;
- every numeric contribution recoverable from trace;
- landing audit fields rejected/ignored by input schema and covered by isolation test;
- scorer has no read access to post-launch outcome storage;
- UI always shows non-prediction label, evidence quality and interval beside score.

---

## 12. Findings по текущей реализации

1. **HIGH — score отсутствует:** `sites/p0-production/lib/campaign-fanout.ts` формирует deterministic Recommendation Set, lineage, exact projection fingerprints и structural visibility, но не рассчитывает viability dimensions/rank/uncertainty. Следующий implementation slice должен добавить отдельный pure scorer, а не смешивать score с compiler.
2. **HIGH — текущий capacity hide не score threshold:** тот же файл скрывает после `MAX_DRAFTS_PER_DELIVERY_BUCKET=3` как `HIDDEN:CAPACITY_LIMIT`. Это допустимая structural reason из #94, но её нельзя переименовать в низкий viability score.
3. **MEDIUM — market evidence пока gap:** candidates имеют `market_evidence_status: "EVIDENCE_GAP"`; по принятой missing policy это не ноль и не автоматическое скрытие.
4. **MEDIUM — current tests/build contract:** `sites/p0-production/package.json` запускает `npm run build && node --test tests/*.test.mjs`; будущие scorer tests следует добавить в существующий test surface, включая golden vectors и leakage/isolation cases.

---

## 13. Применение к production-кандидату

Решение применено минимальным связным срезом к текущему `sites/p0-production`:

- `lib/campaign-viability.ts` реализует pure deterministic scorer семи dimensions, hard eligibility, midpoint + sensitivity bounds, rank/ties, conservative threshold, fingerprints и field-level delta;
- `lib/campaign-fanout.ts` выпускает `campaign-recommendation-set-v2` с versioned score contract и scoring каждого eligible Draft, сохраняя structural hidden/publish blockers отдельно;
- `lib/p0.ts` полностью пересчитывает cohort после сохранённой ручной правки и сохраняет объяснимый delta новой Draft revision;
- шаг **Draft** показывает `0–100`, rank, bounds, семь contributions, missing-data disclosure и явную метку «не прогноз эффективности»; landing audit не входит во вход scorer;
- `tests/campaign-viability.test.mjs` фиксирует determinism, midpoint вместо ложного нуля, hard-blocker separation, manual-edit delta и landing-advisory isolation.

Политика остаётся `UNCALIBRATED_POLICY_V1`; код не превращает индекс в probability или post-launch optimization objective.

---

## Sources

### Kept

- [GitHub issue #93](https://github.com/ElJeskos/MOX-ADV/issues/93) — точный вопрос и product constraints.
- [Wayfinder map #89](https://github.com/ElJeskos/MOX-ADV/issues/89) — five-step flow, score/rank/blocker/landing invariants.
- [Final resolution #90](https://github.com/ElJeskos/MOX-ADV/issues/90#issuecomment-5369315828) — production evidence/provenance and missing semantics.
- [Resolution #91](https://github.com/ElJeskos/MOX-ADV/issues/91#issuecomment-5369104990) — demand/cost admissible evidence and long-tail policy.
- [Resolution #94](https://github.com/ElJeskos/MOX-ADV/issues/94#issuecomment-5369542106) — fan-out, fingerprints, structural hidden reasons and current verification.
- [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework) — primary governance framework for documented purpose, measurement, lifecycle and risk controls.
- [scikit-learn: Probability calibration](https://scikit-learn.org/stable/modules/calibration.html) — authoritative implementation documentation distinguishing probability calibration and requiring independent calibration data.
- [scikit-learn: Cross-validation / TimeSeriesSplit](https://scikit-learn.org/stable/modules/cross_validation.html#time-series-split) — authoritative temporal-order validation guidance.
- [scikit-learn: Metrics and scoring / NDCG](https://scikit-learn.org/stable/modules/model_evaluation.html#discounted-cumulative-gain) — formal ranking metric behavior.

### Dropped

- SEO/blog explanations of generic “optimization scores” — opaque, not primary and commonly conflate ranking with performance prediction.
- Generic missing-data imputation guides — this decision does not statistically impute business facts; it uses explicit unknown states and sensitivity bounds.
- Vendor/browser-cabinet forecast surfaces — outside the repository boundary and not reproducible through permitted APIs.
- Brier-score commentary used directly for viability score — category error because the score is not a probability; retained only as a future separate-forecast note via official model-evaluation docs.

## Gaps and residual risks

- V1 weights/bins/threshold are governance priors, not empirically validated causal coefficients; release must label them `UNCALIBRATED_POLICY_V1` until leakage-safe historical cohorts exist.
- Outcomes exist only for launched/selected Drafts, so retrospective ranking evaluation has selection bias; safe randomized comparison or logged propensity is needed for strong conclusions.
- Cost and demand cohorts can be sparse or incomparable; midpoint and wide sensitivity envelope preserve honesty but reduce ranking resolution.
- Kendall `τ-b` implementation and grouped bootstrap details should be fixed in the future evaluation package before the first backtest.
- No claim is made that score predicts campaign performance.
