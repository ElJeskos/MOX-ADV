# Evidence-контракт аналитики для Campaign Drafts

**Ticket:** [«Определить evidence-контракт аналитики компании, продуктов, конкурентов и текущего Директа»](https://github.com/ElJeskos/MOX-ADV/issues/90)<br>
**Срез исследования:** 2026-08-21<br>
**Назначение:** исследовательское решение и нормативный контракт артефакта; не реализация.<br>
**Нормативные слова:** **MUST / MUST NOT / SHOULD / MAY** имеют обязательный / запрещающий / рекомендуемый / разрешающий смысл.

## Summary

Рекомендация набора Campaign Drafts должна строиться не из одного «аналитического отчёта» и не из произвольного LLM-score, а из версионированного object graph, где каждый нормализованный claim ссылается на неизменяемый Evidence Record. Eligibility, blockers, дубли и suppression вычисляются отдельно от сравнительного rank; confidence раскладывается на качество источника, свежесть, согласованность, покрытие и остаточную неопределённость, причём hard blocker нельзя скрыть средним баллом.

Разрешённый контур: first-party сайт и материалы владельца; публичные страницы конкурентов и публичные объявления только через разрешённые публичные интерфейсы/API с зафиксированными условиями и без авторизации/обхода; Wordstat для спроса, но не цены; собственные Direct/Metrica только через официальные API. Совпадение запросов означает лишь overlap-risk, а доказанная каннибализация требует отдельного дизайна измерения; до запуска стоимость клика/кампании остаётся `unavailable`, если нет свежего first-party исторического наблюдения сопоставимого scope.

---

## 1. Итоговое решение и non-goals

### 1.1 Нормативное решение

1. Агент **MUST** выпускать один `RecommendationSet` на конкретный `analysis_snapshot_id`; он содержит краткую сводку, раскрываемые claims/evidence, eligibility/suppression, rank и набор полных `CampaignDraft`.
2. Одна утверждённая **Campaign Strategy** **MUST** порождать много Campaign Drafts; каждый Draft соответствует ровно одной реальной кампании. Пакет — единица выбора, но не атомарная внешняя операция ([«Развитие P0 „Стратегия и создание кампании“: карта нерешённых решений»](https://github.com/ElJeskos/MOX-ADV/issues/89)).
3. Распространённая публично наблюдаемая конкурентная практика **MUST** становиться `control`; улучшения **MUST** оформляться отдельными hypotheses, а не приписываться конкурентам.
4. Слабый Draft **MAY** быть скрыт, но suppression record с причиной, rule/version, входными claim IDs и возможностью раскрытия **MUST** сохраняться.
5. Landing audit — только advisory: его вывод **MUST NOT** блокировать путь и **MUST NOT** сам по себе снижать viability rank; он может породить warning или гипотезу.
6. Рекомендация **MUST** отличать: документированный API-факт, first-party наблюдение, публичное наблюдение, вычисленный факт, inference и проектное решение.
7. Любая Material Uncertainty, способная изменить продукт/аудиторию/offer/goal/geography/budget/landing или пакет кампаний, **MUST** приводить к подготовленному Human Decision Gate, а не к пустой анкете (термины проекта: `CONTEXT.md`, ADR-0001).

### 1.2 Non-goals

- прогноз прибыли, конверсий или гарантированной эффективности до запуска;
- юридическая оценка допустимости конкретного scraping; контракт лишь требует документировать разрешённый способ и не обходить ограничения;
- оценка внутренних бюджетов, CPC, конверсий, targeting или стратегии конкурента без прямого доказательства;
- browser cabinets Direct/Metrica, авторизованные конкурентные поверхности, credential sharing, CAPTCHA bypass, paywall/login bypass;
- legacy Direct Live 4 forecast: актуальный Direct v5 отправляет forecasting/keyword selection к legacy v4, но это не подтверждает современную поддерживаемую capability ([официальная страница Direct](https://yandex.com/dev/direct/doc/en/best-practice/statistics)); без отдельного доказательства использовать запрещено;
- реализация API, UI, запуск, расходы или изменение внешних систем.

---

## 2. Source allowlist / denylist

### 2.1 Общие правила

- Каждый source connector **MUST** иметь `source_kind`, owner/scope, access mode, terms/policy URL и версию extractor.
- Источник вне allowlist **MUST NOT** влиять на eligibility/rank; он может сохраниться только как `unverified_lead`.
- Сам факт доступности URL **MUST NOT** считаться разрешением на автоматизированный сбор. Для каждого публичного канала фиксируется разрешённый интерфейс/API, его условия и robots/policy status; это не юридическое заключение.

| Область | Allowlist | Denylist / допустимый вес |
|---|---|---|
| **Компания / продукты (first-party)** | публичные страницы собственного домена; структурированные данные на них; предоставленные владельцем прайс-листы, каталоги, презентации, договорные ограничения и интервью/анкета; официальные бренд-аккаунты, подтверждённые владельцем | сторонние каталоги/агрегаторы не доказывают first-party facts; поисковый snippet — только lead; LLM memory запрещена как evidence |
| **Публичные конкуренты** | страницы на публичном competitor-owned домене без login; публичные каталоги/маркетплейсы только через их официально разрешённый публичный интерфейс/API; публично показанное объявление через разрешённый интерфейс с query/region/time locator; предоставленный пользователем исходный публичный материал | кабинеты, login/paywall, обход CAPTCHA/rate limits, brokered/private datasets без лицензии/provenance, вывод о budget/CPC/conversions/strategy/market share без прямого источника |
| **Baseline/control** | утверждённый текущий first-party вариант либо повторяемый наблюдаемый паттерн в заранее объявленной выборке независимых competitor entities | один конкурент ≠ «распространённая практика»; vendor best practice ≠ доказанный рыночный control; отсутствие наблюдения ≠ отсутствие практики |
| **Wordstat** | официальный [Wordstat API v1](https://yandex.com/support2/wordstat/en/content/api-structure): `/v1/topRequests`, `/v1/dynamics`, `/v1/regions`, `/v1/getRegionsTree`; официальный UI допустим только как вручную предоставленный артефакт, если автоматизация интерфейса отдельно не разрешена | неофициальные парсеры/перепродавцы; query count как прогноз кликов/расхода; любой «CPC forecast» из современного Wordstat |
| **Собственный Direct** | официальные Direct API v5/v501: Management `get`, Reports, Changes; OAuth + exact advertiser/`Client-Login` scope | browser cabinet; чужой account; write для аналитики; скриншот как замена API при доступном API |
| **Собственная Metrica** | Management Goals, Reports API, Logs API и разрешённые read scopes; exact counter/goal IDs | browser cabinet; несогласованные goal/attribution/window; персональные row-level данные сверх необходимого scope |
| **Исторические внутренние отчёты** | immutable export из собственного Direct/Metrica/CRM с generation time, account/counter scope, date window, metric definitions, currency, attribution, digest; подписанный/предоставленный владельцем отчёт как lower-tier first-party evidence | вручную изменённая таблица без исходника/формул; агрегат без периода/валюты/goal/attribution; отчёт другого бизнеса как собственный baseline |

**Документированный факт:** Direct API предназначен для управления объектами и статистики ([overview](https://yandex.com/dev/direct/doc/en/concepts/overview)); Reports поддерживает campaign/ad group/ad/criteria/search-query levels ([report types](https://yandex.com/dev/direct/doc/en/type)). Metrica Reports поддерживает параметризованные goal metrics и attribution ([parameters](https://yandex.com/dev/metrika/en/stat/param)).

**Проектное решение:** приведённая иерархия источников и запрет использовать неразрешённый источник в rank.

### 2.2 Консервативная граница публичного конкурентного анализа

Разрешённый claim формулируется только как наблюдение: «на URL X в момент T опубликован offer Y», «в публично показанном ad artifact A был headline H по query Q/region R». Нельзя превращать это в «конкурент таргетирует всю аудиторию Z», «тратит N», «имеет CPA M» или «использует стратегию S».

Официальный Yandex Search API документирован как средство получать результаты поиска в XML/HTML ([Search API overview](https://aistudio.yandex.ru/docs/en/search-api/concepts/)); официальная документация не подтверждает стабильный специализированный feed конкурентных объявлений. Поэтому ad extraction из search results **MUST** иметь отдельное доказательство, что конкретный формат действительно содержит рекламный блок и его обработка разрешена; иначе capability = `unknown/unsupported`, а реклама конкурента может войти только как предоставленный пользователем публичный artifact. Правила robots описывают доступ crawler к URL ([Yandex Webmaster](https://yandex.com/support/webmaster/en/controlling-robot/robots-txt)); они являются одним, но не единственным, policy check.

---

## 3. Типы наблюдаемых фактов и извлечение

### 3.1 Fact classes

- `quoted_fact`: дословный текст/число/enum из source.
- `structural_fact`: URL, title, hierarchy, schema.org field, API object relation.
- `metric_observation`: metric + numerator/denominator where applicable + period + dimensions + attribution + currency.
- `availability_fact`: объект/goal/campaign существует в exact scope.
- `absence_observation`: только «не найдено методом M в scope S во время T», никогда универсальное отсутствие.
- `derived_fact`: детерминированный transform перечисленных evidence IDs.
- `pattern_claim`: повторяемый признак по sample, обязательно с denominator и sampling frame.
- `inference`: гипотеза с альтернативами и uncertainty; не может стать hard fact.

### 3.2 Требования к extraction

1. **MUST** сохраняться атомарный claim: один subject–predicate–value, единицы и язык.
2. Для веба **MUST** храниться canonical URL, content timestamp если опубликован, observed time, selector/quote/context и immutable digest или WARC/object-store pointer.
3. Для API **MUST** храниться endpoint/service/method, semantic request digest (секреты удалены), account/client/counter/campaign IDs, response row/object locator, request ID если доступен.
4. Для метрики **MUST** храниться time zone, window, dimensions, filters, attribution, goal ID, currency/micros transform и completeness. Для Metrica Reports также сохраняются `sampled`, `sample_share`, `sample_size`, `sample_space`, `contains_sensitive_data` и `data_lag`; sampling или ограниченное раскрытие запрещают статус `complete_for_scope` ([response schema](https://yandex.com/dev/metrika/en/stat/openapi/data)).
5. LLM extraction **MUST** возвращать spans/locators и schema validation; claim без восстановимого span становится `unverified`.
6. Negative observation **MUST** включать coverage: какие URL/pages/queries/entities и сколько попыток проверено.
7. PII/secrets **MUST NOT** попадать в evidence payload; access scope хранится отдельно.

---

## 4. Каноническая нормализация и object graph

### 4.1 Идентификаторы и срезы

- Внутренний ID: `urn:mox:<type>:<uuid>`; immutable.
- External key: namespaced tuple, например `yandex-direct:<client_login>:campaign:<Id>`, `metrica:<counter_id>:goal:<goal_id>`.
- Web entity key: registrable domain + owner-confirmed entity mapping; URL отдельно.
- Query key: SHA-256 от `language|geo_set|normalized_query|operator_semantics`; исходная строка сохраняется.
- Snapshot: `analysis_snapshot_id`, `observed_at`, `valid/effective_from`, `effective_to|null`, `source_timezone`.
- Изменение нормализованного объекта создаёт revision, а не переписывает прошлый срез.

### 4.2 Нормализация

- Unicode NFKC, trim/collapse whitespace; original text сохраняется.
- Locale-aware lowercase используется только для matching key, не для display.
- URLs: lowercase scheme/host, default port removed, fragment removed, tracking params removed по versioned allow/deny rule; query params, меняющие продукт/offer, сохраняются. Redirect chain хранится.
- Деньги: integer micros + ISO 4217; никогда не сравнивать разные валюты без зафиксированного FX source/time.
- Время: UTC instant + source timezone; date windows half-open `[from,to)`.
- Geography: официальные Direct/Wordstat region IDs + display label + hierarchy snapshot; строки «Россия» не заменяют ID.
- Query: punctuation/whitespace normalization отдельно от Yandex match operators. Операторы, минус-слова, порядок и исходная фраза сохраняются; stemming/lemma — производный feature, не canonical truth.
- Offer/product/audience synonyms связываются typed alias edges; LLM semantic merge без rule/version и evidence запрещён.

### 4.3 Object graph

```text
Company --owns--> Product --has--> Offer --targets--> Audience
Offer --uses--> Landing
Query --member_of--> Cluster --expresses_intent_for--> Product/Offer
CurrentCampaign --contains--> AdGroup --contains--> Keyword/Ad
CurrentCampaign/AdGroup/Keyword/Ad --observed_by--> DirectMetricObservation
Landing/Goal --observed_by--> MetricaMetricObservation
Goal --measures--> QualifiedOutcome
EvidenceRecord --supports|contradicts--> Claim --about--> any object
Recommendation --selects|suppresses--> CampaignDraft
CampaignStrategy --fans_out_to--> CampaignDraft
CampaignDraft --covers--> Cluster --promotes--> Offer --targets--> Audience
CampaignDraft --uses--> Landing/Goal
CampaignDraft --compares_to--> ControlDraft
```

Обязательные object types: `company`, `product`, `offer`, `audience`, `landing`, `query`, `cluster`, `current_campaign`, `ad_group`, `keyword`, `ad`, `goal`, `recommendation`, `draft`. `current_campaign` всегда отделён от предлагаемого `draft`.

---

## 5. Provenance / Evidence Record

Минимальная схема:

```yaml
evidence_id: urn:mox:evidence:<uuid>
claim_links: [{claim_id: urn:mox:claim:<uuid>, relation: supports|contradicts}]
source_kind: first_party_web|owner_material|competitor_public_web|public_ad_artifact|wordstat_api|direct_management_api|direct_reports_api|metrica_management_api|metrica_reports_api|metrica_logs_api|internal_export
source_locator: {url|object_pointer|service, method, row_locator}
fetched_at: RFC3339
observed_at: RFC3339
effective_interval: {from, to|null, basis: published|report_window|unknown}
scope: {access: public|owner_authorized, account_id?, client_login?, counter_id?, campaign_id?, goal_id?}
extraction: {method: api_parser|dom_selector|ocr|manual_owner|llm_span, version, selector_or_jsonpath, request_digest?}
raw: {value?|sha256, immutable_pointer?}
normalized: {value, datatype, unit?, language?}
transforms: [{rule_id, version, input, output}]
freshness: {policy_id, age_seconds, status: fresh|aging|stale|unknown}
conflicts: [{claim_id, relation: contradicts|supersedes|scope_mismatch, resolution}]
quality_flags: []
```

`raw.value` MAY быть опущен ради лицензии/privacy, но digest + immutable pointer + access policy обязательны. Секреты и bearer tokens запрещены. Любой recommendation feature хранит список claim IDs, а claim — evidence IDs; «источник: интернет» недопустим.

---

## 6. Confidence без произвольного LLM-score

### 6.1 Компоненты

Каждый claim получает вектор, а не одно число:

- `source_quality`: `A` direct first-party API/owner primary; `B` first-party public page or immutable owner artifact; `C` permitted public competitor observation; `D` derived/inference; `U` unknown.
- `freshness`: `current`, `aging`, `stale`, `unknown` по predicate-specific TTL.
- `consistency`: `corroborated`, `single`, `conflicted`, `scope_mismatch`.
- `coverage`: `complete_for_scope`, `sampled_with_denominator`, `partial`, `unknown`; Metrica `sampled=true` либо `contains_sensitive_data=true` автоматически понижает coverage и сохраняет response flags.
- `uncertainty`: перечисленные причины: extraction ambiguity, attribution mismatch, insufficient sample, semantic mapping, platform lag и т. п.

TTL задаются registry по predicate, не универсально: live price/availability короче, company description длиннее; Direct последние 3 дня маркируются provisional, потому что статистика обычно стабилизируется за три дня и может исправляться позже ([Direct freshness](https://yandex.com/dev/direct/doc/en/actual)).

### 6.2 Tiers и rules

- `TIER_1_VERIFIED`: source A/B, fresh, scope-complete, no unresolved conflict; разрешает eligibility fact.
- `TIER_2_CORROBORATED`: минимум два независимых допустимых evidence records, приемлемая свежесть/coverage.
- `TIER_3_INDICATIVE`: single public observation или partial coverage; только rank/context/hypothesis.
- `TIER_4_INFERENCE`: derived/semantic/causal hypothesis; никогда не hard fact.
- `BLOCKED_UNKNOWN`: отсутствует обязательный fact либо конфликт material fields.

Hard gates проверяются до rank: unsupported Direct type, отсутствующий account binding, неизвестный product/offer/landing/geo/goal semantics, policy prohibition и unresolved material conflict **MUST NOT** компенсироваться высоким rank. Числовой `0–100` на карточке допустим только как versioned comparative score после eligibility; рядом обязательны vector/tier и blockers.

---

## 7. Дубли, покрытый спрос и каннибализация

### 7.1 Источники собственного покрытия

- Management API: `Campaigns.get`, `AdGroups.get`, `Keywords.get`, `Ads.get` для фактического object graph; `Keywords.get` возвращает параметры и состояние keywords/autotargeting ([официальный метод](https://yandex.com/dev/direct/doc/en/keywords/get)).
- Direct `SEARCH_QUERY_PERFORMANCE_REPORT`: группирует по `AdGroupId` и `Query`; доступны `CampaignId`, `AdId`, `Criteria/MatchedKeyword`, impressions/clicks/cost/conversions в допустимых сочетаниях ([report type](https://yandex.com/dev/direct/doc/en/type), [allowed fields](https://yandex.com/dev/direct/doc/en/fields-list)).
- Metrica: goal metrics/traffic/Direct dimensions при зафиксированных goal, attribution и dates ([dimensions/metrics](https://yandex.com/dev/metrika/en/stat/attrandmetr/dim_all), [Direct presets](https://yandex.com/dev/metrika/en/stat/presets/preset_direct)).

### 7.2 Классы результата

1. `EXACT_DUPLICATE` — deterministic: одинаковый advertiser scope и canonical publish signature (`product/offer/audience/landing/geo/placement/cluster` + materially identical active object projection). Это hard suppression, если нет explicit separate-campaign decision.
2. `NEAR_DUPLICATE` — deterministic versioned similarity: одинаковые core dimensions, query-set weighted Jaccard выше порога и landing/offer equivalence; requires review/suppression rule, не «доказанная каннибализация».
3. `ALREADY_COVERED_DEMAND` — query/cluster имеет observed impressions/clicks через существующие active keywords/autotargeting в выбранном historical window; сохраняются coverage numerator/denominator и campaign edges.
4. `OVERLAP_RISK` — общий eligible query/cluster/audience/geo/landing или пересечение search-query history. Это риск маршрутизации/бюджетного конфликта, не causal claim.
5. `CANNIBALIZATION_OBSERVED` — термин разрешён только при заранее определённом measurement design, contemporaneous alternatives/control, достаточном объёме, одинаковой атрибуции и наблюдаемом перераспределении с material adverse outcome. Даже тогда causal status хранится отдельно (`experimental|observational`).
6. `UNKNOWN` — недостаточный report window, zero impressions, autotargeting opacity, missing negatives, stale campaign state или несогласованная attribution.

Простое совпадение query **MUST NOT** считаться каннибализацией. Нулевые показы **MUST NOT** доказывать отсутствие спроса. `Query` в report — фактически наблюдавшийся запрос, Wordstat query count — внешний aggregate; их нельзя складывать как одну метрику.

---

## 8. Evidence → Recommendation Set

### 8.1 Eligibility gates

Draft eligible только если:

- утверждённая Campaign Strategy revision определяет offer, audience, qualified outcome/exclusions, goal, geography/period, landing, budget/target result cost/core message;
- существует publishable product/offer/landing relation;
- Direct account/type/child object projection документирован и account eligibility не опровергнута;
- нет exact duplicate без explicit exception;
- measurement status честно указан (`ready|setup_required|unknown`); отсутствие Metrica не блокирует безопасное создание, но блокирует claim «готово к запуску/оптимизации» — соответствует решению [«P0 · Принять продуктовые решения для стратегии и создания кампании»](https://github.com/ElJeskos/MOX-ADV/issues/85#issuecomment-5354891156);
- нет Material Uncertainty по business-defining fields.

### 8.2 Suppression

Suppression rule возвращает `rule_id/version`, `reason_code`, evidence/claim IDs, affected draft, reversibility и remediation. Причины: exact duplicate, unsupported projection, no distinct management rationale, materially stale core evidence, conflict, dominated variant, insufficient independent demand. Hidden drafts остаются auditable.

### 8.3 Control и hypotheses

- `control` может быть утверждённым текущим first-party baseline. Конкурентный паттерн получает статус `observed_common_control` только если он найден минимум у 3 независимых entities и не менее чем у 50% заранее объявленной подходящей выборки с denominator ≥5. Это стартовое project rule MVP, а не статистическое доказательство рынка; иначе статус — `indicative_pattern`.
- Sample frame, denominator, missing coverage и rule version обязательны. Конкурентный control не может иметь tier выше `TIER_2_CORROBORATED` только за счёт распространённости.
- Improvement Draft меняет одну named hypothesis family по сравнению с control, где возможно; заявляет mechanism, expected direction, primary metric, risks и future test.
- Публичная практика не доказывает эффективность; она доказывает только распространённость в наблюдённом sample.

### 8.4 Long-tail clustering

Query не равен кампании. Long-tail объединяется по `product + audience + offer + landing + geo + goal + economics + management action`; отдельный Draft нужен только при материально отличном управлении/сообщении/landing или достаточном самостоятельном спросе. Алгоритм хранит feature vector, version, thresholds, memberships и rejected edges. Exact Wordstat/API phrases сохраняются; semantic cluster — derived claim.

### 8.5 Explainable ranking и double-count protection

После gates rank вычисляется детерминированно из независимых families:

- business fit;
- demand evidence;
- distinctness / uncovered demand;
- measurement readiness;
- publishability;
- evidence completeness.

Каждый feature contribution содержит formula/version и claim IDs. Один Evidence Record может входить в одну family один раз; дубликаты/перепечатки объединяются по raw digest/canonical source; derived claims наследуют lineage и не создают новый независимый голос. Correlated Direct + Metrica metrics одной delivery event family не складываются как независимые подтверждения. Rank не является forecast результата.

---

## 9. Краткая сводка и раскрываемый artifact

### 9.1 Summary contract

В закрытом состоянии пользователь видит не более:

1. «Рекомендуем N кампаний; M скрыто»;
2. 2–4 главные причины;
3. control и improvement hypotheses;
4. blockers / Material Uncertainty отдельной строкой;
5. freshness/coverage badge;
6. Wordstat frequency и `prelaunch_cost: unavailable|historical_first_party`, не вымышленную цену.

### 9.2 Disclosure

Drill-down: recommendation → score contributions → claims → evidence record → raw pointer/quote/API locator/transforms/conflicts. Для suppression доступен тот же путь. UI **MUST** маркировать `documented API fact`, `observed`, `derived`, `hypothesis`, `unknown`; не показывает chain-of-thought, только Decision Record-grade rationale.

Data artifact должен включать summary, graph snapshot, recommendation list, suppressed list, evidence index, conflicts, uncertainty gates, versions и digests.

---

## 10. Missing, stale, conflict и Human Decision Gate

1. Missing low-risk fact → автономный поиск в allowlist, затем `unknown`; не превращать в обязательное поле оператора.
2. Stale metric → исключить из hard conclusion/rank family либо применить explicitly versioned decay; показывать `as_of`.
3. Conflict → не выбирать молча. Сначала проверить scope/time/units/attribution/supersession; хранить обе версии и resolution rule.
4. Material conflict по offer, audience, qualified outcome, goal, geo, budget, landing или права доступа → `BLOCKED_UNKNOWN` + Human Decision Gate.
5. Gate packet: decision owner, вопрос, recommended option, alternatives, evidence, confidence vector, consequences, reversible next step. Это соответствует ADR-0001: агент сам исследует разрешённые источники, а человеку передаёт только Critical Decision/Material Uncertainty.
6. Landing warning остаётся advisory и не создаёт Gate сам по себе.

---

## 11. Версия, воспроизводимость, acceptance checks и пример

### 11.1 Version manifest

Обязательны: `contract_version`, graph/schema version, normalizer version, extractor versions, clustering version, duplicate rules version, confidence policy version, ranking version, source policy/terms snapshots, API doc snapshot dates, model ID/prompt digest (если LLM использован), code/config commit digest, `analysis_snapshot_id`, input evidence Merkle/root digest.

Повторный run с теми же immutable inputs/versions должен воспроизводить gates, deterministic transforms, suppression и rank contributions; свободный текст summary может отличаться, но его cited claims — нет.

### 11.2 Acceptance checks

- schema validation; all IDs unique and referential integrity passes;
- every material recommendation claim has ≥1 allowed Evidence Record;
- every evidence locator can be resolved by authorized reviewer or has valid digest/pointer;
- no secret/PII leakage;
- all metrics have unit/window/scope/attribution/goal where applicable;
- Direct last 3 days marked provisional;
- no Wordstat-derived CPC/price;
- no competitor internal metric/strategy inference presented as fact;
- exact duplicate/overlap/unknown classes are distinct;
- blockers evaluated before score;
- suppression auditable;
- no evidence double counted across family;
- all external capability claims link to official docs;
- unresolved material conflicts create a Gate.

### 11.3 Компактный заполненный пример

```yaml
contract_version: "1.0.0"
analysis_snapshot_id: "urn:mox:snapshot:2026-08-20T10:00:00Z:8b1e"
strategy_revision_id: "urn:mox:strategy:7b3a:r4"
scope:
  company_id: "urn:mox:company:acme"
  direct_client_login: "owner-login"
  metrica_counter_id: 12345678
as_of: "2026-08-20T10:00:00Z"
objects:
  - {id: "urn:mox:product:p1", type: product, name: "Промышленный насос X"}
  - {id: "urn:mox:offer:o1", type: offer, product_id: "urn:mox:product:p1", value: "Подбор и поставка"}
  - {id: "urn:mox:landing:l1", type: landing, canonical_url: "https://owner.example/pump-x"}
  - {id: "urn:mox:cluster:c1", type: cluster, label: "купить насос X для производства", query_ids: ["urn:mox:query:q1"]}
claims:
  - id: "urn:mox:claim:offer"
    subject: "urn:mox:offer:o1"
    predicate: "published_value_proposition"
    value: "Подбор и поставка"
    evidence_ids: ["urn:mox:evidence:web1"]
    confidence: {source_quality: B, freshness: current, consistency: single, coverage: partial, tier: TIER_3_INDICATIVE}
  - id: "urn:mox:claim:demand"
    subject: "urn:mox:query:q1"
    predicate: "wordstat_top_count_last_30_days"
    value: {count: 120, region_ids: [225]}
    evidence_ids: ["urn:mox:evidence:ws1"]
    confidence: {source_quality: A, freshness: current, consistency: single, coverage: complete_for_scope, tier: TIER_1_VERIFIED}
evidence:
  - evidence_id: "urn:mox:evidence:web1"
    claim_links: [{claim_id: "urn:mox:claim:offer", relation: supports}]
    source_kind: first_party_web
    source_locator: {url: "https://owner.example/pump-x", selector: "main h1 + p"}
    fetched_at: "2026-08-20T09:00:00Z"
    observed_at: "2026-08-20T09:00:00Z"
    effective_interval: {from: null, to: null, basis: unknown}
    scope: {access: public}
    extraction: {method: dom_selector, version: "web-extractor/2.1", selector_or_jsonpath: "main h1 + p"}
    raw: {sha256: "sha256:111aaa", immutable_pointer: "evidence://sha256/111aaa"}
    normalized: {value: "Подбор и поставка", datatype: string, language: ru}
    transforms: [{rule_id: "text-nfkc", version: "1.0", input: "Подбор и  поставка", output: "Подбор и поставка"}]
    freshness: {policy_id: "web-offer/30d", age_seconds: 3600, status: fresh}
    conflicts: []
  - evidence_id: "urn:mox:evidence:ws1"
    claim_links: [{claim_id: "urn:mox:claim:demand", relation: supports}]
    source_kind: wordstat_api
    source_locator: {service: WordstatAPI, method: "/v1/topRequests", row_locator: "phrase=купить насос x;regions=225"}
    fetched_at: "2026-08-20T09:10:00Z"
    observed_at: "2026-08-20T09:10:00Z"
    effective_interval: {from: "2026-07-21", to: "2026-08-20", basis: report_window}
    scope: {access: owner_authorized}
    extraction: {method: api_parser, version: "wordstat-v1/1.0", selector_or_jsonpath: "$.topRequests[*]", request_digest: "sha256:222bbb"}
    raw: {sha256: "sha256:333ccc", immutable_pointer: "evidence://sha256/333ccc"}
    normalized: {value: 120, datatype: integer, unit: query_count_last_30_days}
    transforms: []
    freshness: {policy_id: "wordstat/7d", age_seconds: 3000, status: fresh}
    conflicts: []
recommendation_set:
  summary: "Сформировать control для кластера c1 и одну гипотезу улучшения; стоимость до запуска недоступна."
  blockers: []
  material_uncertainties: ["Wordstat count не является прогнозом кликов или CPC"]
  drafts:
    - draft_id: "urn:mox:draft:d1"
      role: control
      eligible: true
      strategy_revision_id: "urn:mox:strategy:7b3a:r4"
      product_id: "urn:mox:product:p1"
      offer_id: "urn:mox:offer:o1"
      landing_id: "urn:mox:landing:l1"
      cluster_ids: ["urn:mox:cluster:c1"]
      duplicate_status: {class: UNKNOWN, reason: "Direct report window missing", evidence_ids: []}
      measurement_status: setup_required
      prelaunch_cost: {status: unavailable, reason: "Wordstat API не является ценовым forecast"}
      score: {value: 68, version: "rank/1.0", comparative_only: true}
      contributions:
        - {family: business_fit, points: 30, claim_ids: ["urn:mox:claim:offer"]}
        - {family: demand_evidence, points: 20, claim_ids: ["urn:mox:claim:demand"]}
        - {family: evidence_completeness, points: 18, claim_ids: ["urn:mox:claim:offer", "urn:mox:claim:demand"]}
      rationale_claim_ids: ["urn:mox:claim:offer", "urn:mox:claim:demand"]
  suppressed:
    - draft_id: "urn:mox:draft:d2"
      rule_id: "suppress/no-distinct-management-rationale@1.0"
      reason_code: "NO_DISTINCT_VARIANT"
      claim_ids: ["urn:mox:claim:demand"]
versions:
  graph: "object-graph/1.0"
  normalizer: "canonical/1.0"
  confidence: "confidence/1.0"
  duplicate_rules: "duplicates/1.0"
  clustering: "cluster/1.0"
  rank: "rank/1.0"
input_root_digest: "sha256:444ddd"
```

Примечание: sample count и IDs вымышлены только для демонстрации схемы и прямо не являются бизнес-evidence.

---

## 12. Capability / limitation matrix

| Capability | Проверенный документированный факт | Contract consequence | Статус |
|---|---|---|---|
| Direct object inventory | `Campaigns.get`, `AdGroups.get`, `Keywords.get`, `Ads.get` доступны в v5; campaign discovery требует fields/scope ([Campaigns.get](https://yandex.com/dev/direct/doc/en/campaigns/get), [Keywords.get](https://yandex.com/dev/direct/doc/en/keywords/get)) | Строить current object graph только из API readback с external IDs | verified |
| Search-query history | `SEARCH_QUERY_PERFORMANCE_REPORT` группирует по `AdGroupId` и `Query`; `MatchedKeyword`, campaign/ad/criteria и metrics доступны в документированных сочетаниях ([types](https://yandex.com/dev/direct/doc/en/type), [fields](https://yandex.com/dev/direct/doc/en/fields-list)); этот report создаётся только offline ([mode](https://yandex.com/dev/direct/doc/en/mode)) | Основа `already_covered` и overlap, но не причинной каннибализации; сохранять offline report lifecycle | verified |
| Direct data freshness | статистика обычно стабилизируется за 3 дня и может корректироваться позже ([freshness](https://yandex.com/dev/direct/doc/en/actual)) | Последние 3 дня provisional; хранить report observation time и reread | verified |
| Direct/Metrica lag | Metrica data в Direct Reports может задерживаться на несколько часов ([restrictions](https://yandex.com/dev/direct/doc/en/restrictions)) | Не трактовать временное расхождение как conflict без lag window | verified |
| Metrica goals | Management API перечисляет goals по counter; наличие объекта не доказывает корректную instrumentation ([Goals](https://yandex.com/dev/metrika/en/management/openapi/goal/goals)) | Разделить goal existence, semantics и observed reaches | verified |
| Metrica dimensions/metrics | Reports API имеет goal-parametrized metrics, Direct/source/UTM dimensions и attribution parameters ([all fields](https://yandex.com/dev/metrika/en/stat/attrandmetr/dim_all), [parameters](https://yandex.com/dev/metrika/en/stat/param)) | Сравнивать только одинаковые goal/attribution/window/scope | verified |
| Metrica sampling/privacy | Reporting response явно возвращает `sampled`, `sample_share`, `sample_size`, `sample_space`, `contains_sensitive_data` и `data_lag` ([response schema](https://yandex.com/dev/metrika/en/stat/openapi/data)) | Сохранять flags; sampled/limited disclosure не может иметь complete coverage | verified |
| Metrica Logs current day | Logs request не принимает текущий день ([Logs API](https://yandex.com/dev/metrika/en/logs/openapi/createLogRequest)) | Current-day completeness = unknown | verified |
| Wordstat top demand | `/v1/topRequests` возвращает `topRequests[]` с `phrase` и `count` за последние 30 дней для запросов, содержащих заданную фразу, и похожих запросов ([Wordstat API v1](https://yandex.com/support2/wordstat/en/content/api-structure)) | Хранить исходную `phrase`, `regions`, `devices`, 30-day semantics и ответ; не трактовать выдачу как exact-match volume | verified |
| Wordstat dynamics | `/v1/dynamics` возвращает `date`, `count`, `share` по daily/weekly/monthly period для заданной фразы ([Wordstat API v1](https://yandex.com/support2/wordstat/en/content/api-structure)) | Хранить granularity/window/region/device и не экстраполировать без отдельной модели | verified |
| Wordstat regions | `/v1/getRegionsTree` даёт дерево official region IDs; `/v1/regions` — последние 30 дней `regionId`, `count`, `share`, `affinityIndex` ([Wordstat API v1](https://yandex.com/support2/wordstat/en/content/api-structure)) | Нормализовать только official IDs/hierarchy snapshot; affinity не подменяет абсолютный demand | verified |
| Wordstat price forecast | в полном перечне Wordstat v1 есть только region tree, top requests, dynamics и regional distribution; полей CPC/bid/budget нет ([Wordstat API v1](https://yandex.com/support2/wordstat/en/content/api-structure)) | `prelaunch_cost=unavailable`, кроме сопоставимых first-party historical observations; Live 4 запрещён без нового доказательства | unsupported |
| Public competitor pages | публичный direct fetch даёт наблюдение страницы; robots описывает crawler URL access ([Yandex robots](https://yandex.com/support/webmaster/en/controlling-robot/robots-txt)) | Требовать no-auth, policy/terms snapshot, rate limits, quote/digest; не делать internal inference | conditionally supported |
| Competitor ad feed | официальный Search API документирует web search XML/HTML, но не подтверждён стабильный специализированный ad feed ([Search API](https://aistudio.yandex.ru/docs/en/search-api/concepts/)) | Без channel-specific proof считать `unknown/unsupported`; допускается owner-provided public artifact | unknown |
| Competitor budgets/conversions/strategy | официального публичного источника не установлено | Запрет claims; оставлять unknown | unsupported |
| Prelaunch cannibalization proof | Direct/Metrica дают object/metric observations, но совпадение query не является causal experiment | Выдавать exact/near duplicate или overlap-risk; cannibalization только после measurement design | unsupported as automatic fact |
| Rollback/transactions | universal transaction/version rollback endpoint в Direct index не документирован ([Direct index](https://yandex.com/dev/direct/doc/en/llms.txt)) | Не относится к analytics write, но Draft handoff должен сохранять snapshot/readback contract | unsupported |

---

## Findings

1. **[BLOCKER] Wordstat нельзя использовать как оценку цены.** Официальный Wordstat API v1 документирует region tree, top requests, dynamics и regional distribution, но не CPC/budget forecast. Любая карточка Draft должна показывать `price unavailable`, если нет сопоставимых first-party historical observations; legacy Live 4 не возрождать. [Wordstat API v1](https://yandex.com/support2/wordstat/en/content/api-structure)
2. **[HIGH] Дубли и уже покрытый спрос вычислимы, каннибализация — нет.** Direct Search Query report и object reads позволяют связать query → keyword/criteria → ad group/campaign и метрики, но causal harm требует отдельного теста. [Report type](https://yandex.com/dev/direct/doc/en/type)
3. **[HIGH] Confidence должен быть вектором с hard gates.** API/first-party quality, freshness, consistency, coverage и uncertainty хранятся раздельно; unsupported projection или Material Uncertainty блокируют независимо от score.
4. **[HIGH] Публичный competitive control — sample claim, не performance claim.** Нужны независимые entities, denominator, locators и terms snapshots; observed prevalence не доказывает эффективность.
5. **[MEDIUM] Свежесть требует predicate-specific policy.** Direct последние три дня provisional; Metrica/Direct lag и attribution mismatches должны проверяться до объявления conflict. [Direct freshness](https://yandex.com/dev/direct/doc/en/actual)

## Sources

### Kept

- Local domain sources: `CONTEXT.md`, `docs/adr/0001-agent-owns-safe-work.md`, `to-questionnaire-reklamnyy-modul-mvp.md`, четыре обязательных research docs — термины, safety и принятый fan-out.
- [«Развитие P0 „Стратегия и создание кампании“: карта нерешённых решений»](https://github.com/ElJeskos/MOX-ADV/issues/89) — принятая Wayfinder map и standing rules.
- [«P0 · Принять продуктовые решения для стратегии и создания кампании»](https://github.com/ElJeskos/MOX-ADV/issues/85#issuecomment-5354891156) — production P0, duplicate gate, measurement semantics и suspended outcome.
- [Direct API report types](https://yandex.com/dev/direct/doc/en/type), [fields](https://yandex.com/dev/direct/doc/en/fields-list), [freshness](https://yandex.com/dev/direct/doc/en/actual) — primary evidence для current coverage.
- [Metrica dimensions/metrics](https://yandex.com/dev/metrika/en/stat/attrandmetr/dim_all), [parameters](https://yandex.com/dev/metrika/en/stat/param), [Goals](https://yandex.com/dev/metrika/en/management/openapi/goal/goals) — primary measurement contract.
- [Wordstat API v1](https://yandex.com/support2/wordstat/en/content/api-structure) — current primary source for `/v1/getRegionsTree`, `/v1/topRequests`, `/v1/dynamics` and `/v1/regions`, including response fields.
- [Yandex Search API](https://aistudio.yandex.ru/docs/en/search-api/concepts/) and [robots documentation](https://yandex.com/support/webmaster/en/controlling-robot/robots-txt) — conservative public-channel boundary.

### Dropped

- Semantica, SearchAPI.io, blogs, GitHub Wordstat wrappers — secondary/unofficial; used only as search leads and excluded from claims.
- Vendor SEO articles and inferred CPC tools — not primary and conflict with the explicit source policy.
- Legacy Direct v4/Live 4 forecast — current supported status not proven.
- Search snippets claiming ad extraction — official Yandex docs did not substantiate a stable ad feed.

## Gaps

1. No official dedicated public competitor-ad API/feed was confirmed. Until a channel-specific official contract proves it, treat automated competitor ad harvesting as unsupported; accept only permitted public observations with full locator or owner-provided artifacts.
2. Account-specific Direct eligibility, actual IDs, report availability and Metrica instrumentation were not tested; no credentials/API calls were used.
3. No single universal TTL/calibration is defensible from official docs; predicate-specific freshness policies require product data and validation runs.
4. Wordstat v1 methods and response fields are verified, but live quotas and account-specific availability still require implementation-time preflight; this does not authorize price forecasting.
