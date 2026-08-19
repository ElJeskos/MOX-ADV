# Как должен быть устроен Campaign Effectiveness Profile?

**Дата проверки источников:** 19 августа 2026 г.

**Статус:** нормативная исследовательская рекомендация для спецификации; без реализации

## 1. Решение

`Campaign Effectiveness Profile` — не изменяемая на месте таблица KPI, а **неизменяемая утверждённая ревизия полного контракта эффективности одной кампании**. Она отвечает на семь разных вопросов:

1. какой один бизнес-результат считается главным;
2. какой один сигнал разрешено использовать как текущую оптимизационную цель;
3. какие ограничения и защитные показатели нельзя обменивать на улучшение результата;
4. какие показатели служат только диагностикой;
5. какие источники подтверждают каждую величину, при каких семантике, качестве, свежести и зрелости;
6. как разрешаются конфликты показателей и источников;
7. какая именно ревизия управляла каждым уже принятым решением.

Канонический приоритет фиксирован и не настраивается произвольными весами:

```text
Gate 0 Boundary и Mandate
→ качество и сопоставимость данных
→ hard constraints и guardrails
→ business outcome
→ primary optimization objective
→ diagnostic signals
```

Внутри профиля нет непрозрачного `effectiveness score`. Улучшение CTR, CPC, визитов или platform ROAS не компенсирует нарушение ограничения, ухудшение зрелого бизнес-результата либо ненадёжность измерения.

Утверждённая ревизия полностью материализована: account-level default только создаёт первоначальный snapshot. Изменение default не меняет действующую кампанию. Любое изменение содержимого профиля создаёт новую ревизию и требует утверждения человека как критическое решение. `Decision Record` навсегда ссылается на конкретные `revision_id` и `content_digest`; последующие ревизии и исправления данных создают новые записи, но не переписывают старое решение.

## 2. Граница профиля

Профиль определяет **смысл эффективности и пригодность измерения**, но не выдаёт полномочия на действие.

- `Gate 0 Boundary` задаёт системные пределы, которые нельзя ослабить.
- `Mandate` задаёт срок, бюджет, scope и классы разрешённых действий.
- `Campaign Effectiveness Profile` задаёт цель, target bands, campaign-level ограничения, guardrails, источники и правила оценки.
- `Hypothesis Registration` фиксирует конкретный эксперимент, статистический метод, MDE, stopping rule и observation window.

Runtime применяет пересечение ограничений. Профиль может быть строже Gate 0 и Mandate, но не может расширить их. Статистические методы конкретной гипотезы остаются контрактом тикета «Как система должна развивать и проверять гипотезы?», а продуктовые значения cadence, grace period и допустимого расхождения ручной сверки — контрактом тикета «Как человек сверяет бизнес-конверсии до подключения CRM?». Текущий документ определяет обязательные поля, состояния и последствия этих значений, не подменяя последующие решения.

## 3. Канонические артефакты

Нужны три разных артефакта, а не одна mutable-запись.

### 3.1. `AccountEffectivenessDefaultRevision`

Неизменяемый шаблон аккаунта. Содержит versioned-каталоги источников, metric definitions, value models, quality/maturity policies, diagnostics и guardrail templates. Он не участвует в runtime-решении напрямую.

### 3.2. `CampaignEffectivenessProfileRevision`

Неизменяемый, утверждённый и полностью разрешённый snapshot для одной кампании. В нём нет runtime-наследования и незаполненных значений «взять из default».

### 3.3. `ProfileActivationEvent`

Append-only событие `ACTIVATED`, `DEACTIVATED` или `REPLACED`, задающее, какая ревизия действует с какого момента. Статус `superseded` выводится из событий, а не достигается редактированием старой ревизии.

`ProfileDraft` может редактироваться до утверждения, но runtime никогда не использует draft. Утверждение создаёт новую immutable revision и отдельное activation event.

## 4. Точный логический контракт ревизии

Ниже — логическая схема. Это не выбор базы данных или wire format.

```yaml
campaign_effectiveness_profile_revision:
  identity:
    profile_id: stable ID профиля одной кампании
    campaign_id: ID кампании Яндекс Директа
    advertiser_login: один advertiser login текущего scope
    revision_id: глобально уникальный ID ревизии
    revision_number: монотонный номер внутри profile_id
    schema_version: версия схемы контракта
    content_digest: hash канонического блока specification
    supersedes_revision_id: предыдущая ревизия либо null
    initialized_from_default_revision_id: ревизия account default либо null
    created_at: timestamp
    created_by: actor ID
    approved_at: timestamp
    approved_by: human actor ID
    approval_reason: краткая причина изменения

  scope:
    campaign_type: поддерживаемый тип кампании
    metrica_counter_ids: непустой набор разрешённых счётчиков
    timezone: IANA timezone
    currency: ISO 4217
    valid_campaign_lifecycle_states: состояния, в которых профиль применим

  business_outcome:
    metric_id: ровно одна главная бизнес-метрика
    outcome_tier: PROFIT_MARGIN | REVENUE | QUALIFIED_FINAL_OUTCOME | EXPLICIT_NON_PERFORMANCE
    definition: однозначное бизнес-определение результата
    direction: MAXIMIZE | MINIMIZE | KEEP_IN_RANGE
    value_model_revision_id: версия расчёта value либо null
    evaluation_window_id: окно оценки
    decision_statistic: какая оценка сравнивается с band
    target_bands:
      acceptable: числовой интервал
      desired: числовой интервал, являющийся подмножеством acceptable

  optimization_objective:
    metric_id: ровно один operational/bidding signal
    objective_type: CONVERSION_VALUE | FINAL_CONVERSIONS | QUALIFIED_LEADS | VISITS | REACH | VIEWS
    platform_goal_bindings: goal IDs и их versioned values
    direction: MAXIMIZE | MINIMIZE | KEEP_IN_RANGE
    target_bands:
      acceptable: числовой интервал
      desired: числовой интервал внутри acceptable
    proxy:
      status: NONE | TEMPORARY | VALIDATED
      business_outcome_metric_id: к чему относится proxy
      empirical_support_ref: доказательство связи либо null
      review_or_expiry_at: обязательно для TEMPORARY

  hard_constraints:
    - constraint_id
      metric_id
      predicate: типизированное сравнение с threshold/range
      observation_window_id
      consequence: BLOCK | CONTAIN | ESCALATE
      source: CAMPAIGN | ACCOUNT_TEMPLATE

  guardrails:
    - guardrail_id
      metric_id
      predicate
      observation_window_id
      maturity_requirement_id
      severity: WARNING | STOP_CHANGE | CONTAIN | ESCALATE
      preregistered_consequence

  diagnostics:
    - signal_id
      metric_id
      funnel_stage: DELIVERY | AUCTION | CREATIVE | LANDING | FUNNEL | OUTCOME_QUALITY
      expected_band
      anomaly_rule
      observation_window_id
      decision_power: DIAGNOSE_ONLY | GUARDRAIL
      interpretation_limits

  metric_definitions:
    - metric_id
      canonical_name
      semantic_definition
      unit
      aggregation
      numerator_metric_id: optional
      denominator_metric_id: optional
      counting_rule
      net_or_gross: optional
      segmentation_scope

  measurement_contract:
    source_bindings: [...]
    metric_source_priority: [...]
    comparability_rules: [...]
    freshness_and_maturity: [...]
    quality_gates: [...]
    manual_reconciliation_policy: {...}

  decision_policy:
    precedence: fixed canonical order
    insufficient_data_result: INSUFFICIENT_MATURE_DATA
    incompatible_data_result: INCOMPARABLE_DATA
    source_conflict_result: CONFLICTING_EVIDENCE
    proxy_success_result: PROVISIONAL_ONLY
    no_opaque_score: true

  provenance:
    field_origins: account-default revision или campaign decision для каждого effective field
    supporting_requirement_refs: нормативные требования
    supporting_decision_refs: предыдущие Wayfinder decisions
    known_assumptions: явные допущения
```

### Обязательные инварианты схемы

1. Один профиль относится ровно к одной кампании.
2. В профиле ровно один `business_outcome.metric_id` и один `optimization_objective.metric_id`.
3. `desired` является подмножеством `acceptable`; hard stop не прячется внутри target band, а оформляется отдельным constraint/guardrail.
4. Все currency metrics используют валюту профиля либо явное versioned conversion rule.
5. Несколько conversion actions нельзя суммировать как равные, если профиль не содержит их versioned economic values.
6. Диагностический сигнал с `DIAGNOSE_ONLY` не может разрешить, отменить или признать успешным value-seeking action.
7. Временный proxy всегда имеет основание, срок пересмотра и более сильную outcome-метрику, которую он приближает.
8. Все metric/source/window/value IDs ссылаются на неизменяемые версии.
9. Полностью materialized approved revision не содержит динамических ссылок «latest».
10. Любое изменение content block меняет `content_digest` и требует новой revision.

## 5. Роли метрик и target bands

### 5.1. Главный бизнес-результат

Выбирается один outcome по утверждённой лестнице:

1. инкрементальная прибыль или маржинальная ценность;
2. net revenue/value с учётом доступных возвратов и качества;
3. квалифицированный лид, завершённая сделка или иная конечная конверсия;
4. явно non-performance outcome только для кампании, чья бизнес-задача действительно состоит в охвате или трафике.

MRC отделяет traffic/visitation и interaction от прямого измерения продаж, а CRM/sales datasets рассматривает как источники outcome, требующие собственного контроля качества. Поэтому клик, CTR, визит и поведение страницы не повышаются до business outcome только из-за доступности данных ([MRC Outcomes and Data Quality Standards](https://mediaratingcouncil.org/sites/default/files/Standards/MRC%20Outcomes%20and%20Data%20Quality%20Standards%20%28Final%29.pdf), разделы 2.1.5–2.1.8).

### 5.2. Основная оптимизационная цель

Operational objective ровно один. Yandex Direct позволяет передавать несколько conversions, но требует указать их ценность для бизнеса; более высокая value означает более высокий приоритет. Для e-commerce с разной стоимостью рекомендуется dynamic value ([Yandex Direct — Conversions](https://yandex.com/support/direct/en/strategies/priority-goals)). Следовательно:

- при неодинаковой ценности outcomes используется conversion value;
- при однородных outcomes допустимо количество конечных конверсий;
- микроконверсии допускаются только как versioned proxy;
- один пользовательский путь не должен получать полную value одновременно за промежуточную и конечную конверсию.

### 5.3. Представление target range

Target не хранится одним перегруженным числом. Для каждой decision metric задаются два вложенных интервала:

- `acceptable` — результат, при котором кампания ещё соответствует утверждённому минимуму;
- `desired` — целевой диапазон внутри acceptable.

Примеры:

```text
MAXIMIZE margin: acceptable [100_000, +∞), desired [130_000, +∞)
MINIMIZE CPA:     acceptable (-∞, 2_000], desired (-∞, 1_600]
KEEP_IN_RANGE:    acceptable [0.8, 1.2], desired [0.95, 1.05]
```

Hard safety boundary остаётся отдельным predicate. Результат ниже acceptable означает `UNDERPERFORMING`, но не автоматически разрешает опасное изменение: новое действие всё равно проходит Mandate, policy и hypothesis checks.

## 6. Источники результата и качество данных

### 6.1. Авторитет задаётся для конкретной величины

У источника нет одного глобального ранга. CRM может быть авторитетна для факта и net value продажи, но не обязательно для рекламной атрибуции; Direct лучше знает delivery/cost, но его attributed conversion не доказывает факт закрытой сделки.

Для каждого `metric_id` профиль хранит ordered bindings с ролями:

- `AUTHORITATIVE_OUTCOME` — источник факта/ценности бизнес-результата;
- `AUTHORITATIVE_DELIVERY` — источник показов, кликов, расходов и platform state;
- `ATTRIBUTION` — источник связи outcome с рекламой;
- `CORROBORATING` — независимая проверка;
- `OPERATIONAL_PROXY` — временный сигнал для управления;
- `DIAGNOSTIC` — объясняющий сигнал.

Базовый порядок для факта business outcome до подключения CRM:

```text
CRM/internal system of record
→ принятая Manual Reconciliation
→ Metrica final/e-commerce/offline goal
→ Direct attributed projection
→ validated funnel proxy
→ diagnostic event
```

Более сильный источник не «заметает» серьёзное расхождение. Он определяет reportable fact, но конфликт переводит affected measurement scope в `CONFLICTING_EVIDENCE` и блокирует новые value-seeking writes до reconciliation.

### 6.2. Обязательный `SourceBinding`

```yaml
source_binding:
  binding_id:
  metric_id:
  role:
  source_type: DIRECT_REPORT | METRICA_GOAL | METRICA_ECOMMERCE | METRICA_OFFLINE | MANUAL | CRM | INTERNAL
  source_identity: advertiser/counter/goal/dataset identifiers
  semantics:
    attribution_model:
    click_view_windows:
    counting_rule:
    timezone:
    currency:
    net_or_gross:
    deduplication_rule_revision_id:
    value_model_revision_id:
  provenance:
    extractor_or_adapter_version:
    query_or_import_identity:
    event_time_field:
    source_updated_at_field:
    ingested_at_field:
    observed_at_field:
  freshness:
    maximum_source_lag:
    maximum_ingestion_lag:
    required_refresh_rule:
  maturity:
    empirical_conversion_lag_rule:
    platform_stabilization_rule:
    correction_horizon_rule:
  quality_gates:
    schema_validity:
    completeness:
    uniqueness_or_deduplication:
    match_coverage:
    value_validity:
    comparability:
    discrepancy_tolerance:
```

MRC требует раскрывать происхождение, collection parameters, cleaning, limitations, recency, granularity и completeness CRM/sales data, а также выполнять initial и periodic quality control даже для данных самого рекламодателя. Это прямо поддерживает отдельные provenance и quality gates, а не булев флаг «источник подключён» ([MRC](https://mediaratingcouncil.org/sites/default/files/Standards/MRC%20Outcomes%20and%20Data%20Quality%20Standards%20%28Final%29.pdf), разделы 2.1.7.1 и 5).

W3C PROV разделяет `Entity`, `Activity` и `Agent` и предусматривает derivation, attribution, generation/invalidation time и revision. Контракт MOX-ADV использует эту семантику как минимальную модель происхождения, не требуя RDF в реализации ([W3C PROV-O](https://www.w3.org/TR/prov-o/)).

### 6.3. Состояния пригодности данных

Для decision window runtime выводит одно из состояний:

| Состояние | Значение | Допустимое поведение |
|---|---|---|
| `MATURE_COMPARABLE` | Все required gates пройдены, cohort зрелый, semantics совпадают | Оценка outcome и гипотезы |
| `CURRENT_IMMATURE` | Источник работает, но conversion/correction tail не завершён | Наблюдение и guardrails; не final success/failure |
| `OBSERVATION_ONLY` | Данные годятся для диагностики, но не для business decision | Диагностика |
| `STALE` | Watermark или ingest отстаёт сверх profile threshold | Наблюдение ограничено; value-seeking writes blocked |
| `INCOMPLETE` | Не пройдены completeness/match/required-field gates | Measurement incident |
| `INCOMPARABLE` | Различаются goal, attribution, window, timezone, currency или counting rule | Не сравнивать и не агрегировать |
| `DISCREPANT` | Сопоставимые источники расходятся сверх tolerance | Measurement incident и блокировка affected scope |
| `UNAVAILABLE` | Required source недоступен | Fail closed для зависимых writes |

`MATURE_COMPARABLE` вычисляется детерминированно, а не утверждается моделью.

### 6.4. Свежесть и зрелость — разные свойства

Профиль хранит четыре времени: `event_through`, `source_updated_at`, `ingested_at`, `observed_at`. Свежий источник может содержать незрелую cohort, а зрелая cohort может быть прочитана устаревшим snapshot.

Минимальное правило:

```text
maturity_not_before = max(
  cohort_end + empirical_conversion_lag,
  source_reporting_ready_at,
  platform_stabilization_not_before,
  required_manual_verified_through
)
```

Google определяет conversion cycle как время от клика до конверсии плюс время импорта и рекомендует исключать ещё незавершённый хвост при оценке CPA/ROAS ([Google Ads — How bidding algorithms learn](https://support.google.com/google-ads/answer/10970825?hl=en)).

Для Yandex действуют platform floors, которые профиль может только ужесточить:

- Direct statistics обычно стабилизируется в течение трёх дней; последние три дня нужно перечитывать, а correction event может потребовать пересчёта более старого периода ([Yandex Direct — How to get updated statistics](https://yandex.com/dev/direct/doc/en/actual));
- offline conversions появляются в Metrica reports в течение трёх часов после upload, но это readiness, а не доказательство зрелости outcome ([Passing offline conversions](https://yandex.com/dev/metrika/en/management/offline-conv));
- Metrica связывает offline conversion с session в пределах 21 дней, поэтому поздний import и match coverage должны быть явными ([Tracking conversions](https://yandex.com/dev/metrika/en/management/conversion)).

Поздняя correction не переписывает старый Decision Record. Она создаёт новый data revision и при существенности — новый `REASSESSMENT` record со ссылкой на первоначальное решение.

## 7. Контракт ручной сверки до CRM

Профиль обязан поддерживать следующий блок:

```yaml
manual_reconciliation_policy:
  requirement: REQUIRED | NOT_REQUIRED_WHEN_STRONG_SOURCE_CURRENT
  affected_measurement_scope:
  cadence_rule:
  grace_period:
  maximum_unverified_span:
  required_record_fields:
    - period_start
    - period_end
    - verified_through
    - metrica_goal_ids
    - metrica_count_and_value
    - actual_count_and_value
    - actual_source_description_or_evidence_ref
    - attribution_and_counting_semantics
    - confirmed_at
    - confirmed_by
  discrepancy:
    absolute_tolerance:
    relative_tolerance:
    comparison_rule: breach if preregistered rule is met
  resume_requirement:
    accepted_resolution_event_type:
    required_actor:
```

Runtime выводит состояние так:

- `NOT_REQUIRED` — более сильный qualified source покрывает тот же scope и профиль явно разрешает exemption;
- `CURRENT` — latest record принят, покрывает требуемый period и ещё не наступил `due_at`;
- `DUE` — cadence истёк, но grace period ещё не истёк; показывается предупреждение, новые writes пока оцениваются по утверждённой policy;
- `OVERDUE` — grace period или maximum unverified span превышены;
- `DISCREPANT` — absolute/relative discrepancy rule нарушено; имеет приоритет над `DUE`.

`OVERDUE` и `DISCREPANT`:

1. не останавливают ingestion и безопасную диагностику;
2. блокируют новые value-seeking writes в affected scope;
3. не позволяют признать успех по неподтверждённому proxy;
4. не отменяют readback уже отправленной операции;
5. допускают только заранее разрешённый containment/compensation при непосредственной угрозе;
6. требуют отдельного resolution event, а не автоматического истечения ошибки.

Точные cadence, grace, tolerance, scope и resume confirmation являются продуктовым решением тикета [«Как человек сверяет бизнес-конверсии до подключения CRM?»](https://github.com/ElJeskos/MOX-ADV/issues/66). Этот профиль делает их обязательными versioned values; отсутствие значения запрещает утверждение профиля, пока ручная сверка required.

## 8. Разрешение конфликтов

Алгоритм един и воспроизводим.

1. **Проверить ревизию:** активна ли approved revision и совпадает ли digest.
2. **Проверить внешний safety:** Gate 0, Mandate, kill switch и platform capability. Любой запрет завершает проверку.
3. **Проверить данные:** semantics, provenance, freshness, maturity, completeness и reconciliation.
4. **Проверить hard constraints:** breach нельзя компенсировать никакой другой метрикой.
5. **Проверить guardrails:** preregistered consequence выполняется независимо от primary uplift.
6. **Оценить business outcome:** зрелый outcome имеет приоритет над operational objective.
7. **Оценить optimization objective:** он разрешает provisional operational choice только если не противоречит более сильному зрелому outcome и profile proxy policy.
8. **Использовать diagnostics:** только для локализации причины и следующей гипотезы.

Обязательные случаи:

| Конфликт | Результат |
|---|---|
| CTR вырос, mature margin упала | Не считать улучшением; outcome имеет приоритет |
| CPA улучшился, но нарушен budget/brand constraint | `BLOCKED_CONSTRAINT` |
| Conversion value растёт, manual reconciliation overdue | `MEASUREMENT_BLOCKED` |
| Metrica и CRM имеют разные windows | `INCOMPARABLE_DATA`, сначала нормализовать semantics |
| Сопоставимые CRM и Metrica расходятся сверх tolerance | `CONFLICTING_EVIDENCE`, stronger source определяет факт, writes blocked |
| Business outcome ещё незрелый, validated proxy улучшился | `PROVISIONAL_ONLY`, не final success |
| Diagnostic ухудшился, но не является guardrail | Не отменяет outcome; создаёт diagnostic signal |
| Данных мало | `INSUFFICIENT_MATURE_DATA`, а не «кампания неэффективна» |

## 9. Что приходит из account default, а что обязательно кампанийное

### Может быть шаблоном account-level

- currency и timezone;
- immutable каталог доступных Direct/Metrica/CRM source bindings;
- metric definitions и naming;
- standard attribution/counting/deduplication templates;
- versioned margin/LTV/value models;
- source-specific platform freshness floors;
- standard maturity и quality-gate templates;
- diagnostic bundles по типу кампании;
- guardrail templates;
- manual reconciliation policy templates;
- рекомендуемые target bands по классу кампании.

### Обязательно определяется или явно принимается для кампании

- campaign scope и применимость к её типу;
- главный business outcome и его definition;
- один primary optimization objective и точные platform goal bindings;
- values/weights conversion actions;
- acceptable и desired bands;
- campaign-effective hard constraints и guardrails;
- выбранные diagnostics;
- metric-specific source priority и роли источников;
- фактические attribution model, windows, counting, timezone и currency;
- maturity rules и quality thresholds;
- proxy status, empirical support и expiry;
- manual reconciliation requirement и effective policy;
- known assumptions и gaps.

### Семантика наследования

1. Default используется только при создании draft или явной операции `refresh from default`.
2. Draft показывает field-level diff и provenance каждого значения.
3. После approval все effective values копируются в campaign revision.
4. Изменение default только создаёт drift notification/candidate draft.
5. Никакого автоматического обновления действующей кампании нет.
6. Даже неизменённое inherited field указывает точный `default_revision_id`.

Так сохраняется удобство account-level стандарта без скрытого изменения смысла уже работающих кампаний.

## 10. Версионирование без ретроспективного изменения решений

### 10.1. Идентичность и активация

- `profile_id` стабилен для кампании.
- `revision_id` уникален и никогда не переиспользуется.
- `revision_number` монотонен внутри профиля, но решения ссылаются на `revision_id`, а не на «последнюю» версию.
- `content_digest` считается по canonical specification без mutable runtime state.
- Обычная activation не может иметь `effective_at` раньше момента записи/утверждения.
- Future activation допустима отдельным событием.

### 10.2. Что обязан закрепить `Decision Record`

```text
campaign_id
profile_revision_id + content_digest
account_default_revision_id (provenance only)
metric/value/source binding revision IDs
input data snapshot IDs и watermarks
attribution/counting/window semantics
Gate 0 Boundary version
policy version
Mandate version
Hypothesis Registration version
decision_time и observation_time
```

### 10.3. Изменение профиля

Любое content change создаёт draft → human approval → new revision → activation event. Это касается outcome, target, goal IDs/value, constraints, guardrails, source authority, attribution, counting, maturity, quality, reconciliation и conflict rules. Изменение профиля не является routine autonomous optimization.

При activation новой revision:

- неотправленные Action Plans и write-authorizations старой revision инвалидируются;
- `IN_FLIGHT` операции проходят readback/reconciliation, а не исчезают;
- старые observations, hypotheses, decisions и evaluations остаются привязаны к прежней revision;
- продолжение активной гипотезы требует явной revalidation; её прошлые данные не пересчитываются молча по новой цели.

### 10.4. Исправление истории

- Source correction создаёт новый data snapshot.
- Re-evaluation создаёт новый `Decision Record` с `reassessment_of`.
- Ошибка профиля исправляется новой revision; старый record может быть помечен отдельным invalidation/correction event, но его исходный payload и digest сохраняются.
- Schema migration создаёт новую materialized representation или read projection; оригинальные bytes/schema version/hash остаются доступными.

Так audit отвечает на два разных вопроса: «что система решила тогда на известных тогда фактах?» и «что мы считаем верным теперь после новых фактов?».

## 11. Минимальный интерфейс для последующих модулей

Профиль должен давать runtime и Dashboard небольшой, стабильный read-only interface:

```text
resolve_active_profile(campaign_id, at_time)
  -> exact approved ProfileRevision

assess_measurement(profile_revision, data_snapshot)
  -> source states, maturity, conflicts, eligible metric values

evaluate_effectiveness(profile_revision, measurement_assessment)
  -> constraint/guardrail verdict,
     business outcome band,
     optimization objective band,
     diagnostic signals,
     canonical status and reason codes
```

Интерфейс не позволяет caller самостоятельно переупорядочивать метрики, выбирать «лучший» источник или вычислять другой score. Это делает модуль глубоким: все правила семантики, качества, наследования и конфликтов остаются внутри одного deterministic evaluator.

Минимальные canonical statuses для Dashboard и Decision Trigger:

```text
MEASUREMENT_BLOCKED
INSUFFICIENT_MATURE_DATA
CONFLICTING_EVIDENCE
BLOCKED_CONSTRAINT
GUARDRAIL_BREACH
UNDERPERFORMING
WITHIN_ACCEPTABLE_BAND
ON_TARGET
OUTPERFORMING
PROVISIONAL_PROXY_ONLY
```

## 12. Пограничные сценарии

| Сценарий | Решение контракта |
|---|---|
| Account default изменил target CPA | Действующая campaign revision не меняется; создаётся drift candidate |
| Кампания использует три goals с разной ценностью | Хранятся versioned goal values; raw counts не суммируются |
| CRM подключили для части продуктов | Ручная сверка становится `NOT_REQUIRED` только в покрытом scope |
| CRM sales current, но Metrica attribution stale | Факт продаж доступен, attribution-dependent writes blocked |
| Direct исправил статистику пятидневной давности | Новый data revision и reassessment; старый Decision Record неизменен |
| Temporary add-to-cart proxy истёк | Профиль остаётся исторически валидным, но runtime блокирует dependent writes до новой approved revision/revalidation |
| Новый профиль активирован во время эксперимента | Новые writes старого плана запрещены; observation/readback продолжаются, hypothesis требует revalidation |
| Profit растёт, CTR падает | Кампания остаётся успешной, если CTR не был guardrail; diagnostic signal сохраняется |
| Revenue растёт, margin падает ниже hard floor | Constraint breach; revenue не компенсирует его |
| Человек подтвердил данные без period/source semantics | Record schema-invalid и не обновляет reconciliation state |

## 13. Матрица тезисов и источников

| Тезис | Источник |
|---|---|
| Traffic, visitation и interaction не являются прямой мерой продаж; outcome data требует quality, recency, granularity, completeness и disclosure | [MRC Outcomes and Data Quality Standards](https://mediaratingcouncil.org/sites/default/files/Standards/MRC%20Outcomes%20and%20Data%20Quality%20Standards%20%28Final%29.pdf) |
| CRM/sales data требуется initial и periodic quality control даже при получении от рекламодателя | [MRC, раздел 2.1.7.1](https://mediaratingcouncil.org/sites/default/files/Standards/MRC%20Outcomes%20and%20Data%20Quality%20Standards%20%28Final%29.pdf) |
| Yandex optimization goals имеют business value; higher value означает higher priority; e-commerce поддерживает dynamic value | [Yandex Direct — Conversions](https://yandex.com/support/direct/en/strategies/priority-goals) |
| Primary/biddable и secondary/observation-only signals должны различаться | [Google Ads — About conversion measurement](https://support.google.com/google-ads/answer/1722022) |
| Conversion cycle включает reporting/import delay; незрелый хвост следует исключать из оценки | [Google Ads — How bidding algorithms learn](https://support.google.com/google-ads/answer/10970825?hl=en) |
| Direct statistics обычно стабилизируется за три дня и может исправляться позднее | [Yandex Direct — Updated statistics](https://yandex.com/dev/direct/doc/en/actual) |
| Offline conversions появляются в Metrica reports в течение трёх часов после upload | [Yandex Metrica — Passing offline conversions](https://yandex.com/dev/metrika/en/management/offline-conv) |
| Metrica использует 21-day matching period для offline conversions | [Yandex Metrica — Tracking conversions](https://yandex.com/dev/metrika/en/management/conversion) |
| Provenance различает entity/activity/agent, derivation, attribution, times и revisions | [W3C PROV-O Recommendation](https://www.w3.org/TR/prov-o/) |
| Профиль campaign-specific, default только инициализирует snapshot; hierarchy hard constraint → outcome → objective → diagnostics | Принятое решение [«Какая модель эффективности должна управлять рекламными кампаниями?»](https://github.com/ElJeskos/MOX-ADV/issues/53) |
| Изменение profile revision инвалидирует старое write-разрешение; overdue reconciliation блокирует value-seeking writes | Принятое решение [«Как устроен операционный цикл Автономного оператора кампаний?»](https://github.com/ElJeskos/MOX-ADV/issues/56) |

## 14. Уверенность и оставшаяся граница

**Высокая уверенность:** разделение business outcome, objective, constraints, diagnostics и data quality; campaign-specific snapshot; per-metric source authority; freshness отдельно от maturity; pinned immutable revision в Decision Record; отсутствие opaque score.

**Средне-высокая уверенность:** конкретное разделение на Profile Revision и Activation Event и предложенные canonical states. Это архитектурный вывод из требований аудита/provenance и уже принятого durable runtime, а не готовая схема отраслевой платформы.

**Сознательно не решено здесь:** числовые cadence/grace/discrepancy/resume rules ручной сверки — уже выделены в HITL-тикет [«Как человек сверяет бизнес-конверсии до подключения CRM?»](https://github.com/ElJeskos/MOX-ADV/issues/66); статистический lifecycle гипотезы — в [«Как система должна развивать и проверять гипотезы?»](https://github.com/ElJeskos/MOX-ADV/issues/58). Нового продуктового выбора, требующего дополнительного Wayfinder ticket, исследование не выявило.
