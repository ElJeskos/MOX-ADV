# Как устроен операционный цикл Автономного оператора кампаний?

**Дата доступа к официальным источникам:** 19 августа 2026 г.

**Метод:** нормативные требования и код репозитория сопоставлены с локальными claim-to-source matrices предыдущих исследований; ключевые ограничения повторно проверены по официальной документации Yandex Direct и Yandex Metrica. Вторичные источники не использовались.

## Summary

Канонический runtime следует моделировать не одним огромным enum, а **детерминированным workflow одного Monitoring Cycle плюс ортогональные версии входного состояния**. Happy path: `OBSERVE → VALIDATE → DIAGNOSE → PLAN → POLICY_CHECK → RESERVE → EXECUTE → READBACK → WAIT_MATURITY → EVALUATE → RETAIN | REJECT | INCONCLUSIVE | COMPENSATE | ESCALATE → COMPLETE`; исключения переводят только затронутую кампанию в `BLOCKED`, `RECONCILING`, `UNKNOWN_RESULT` или `CONTAINED`, не останавливая безопасное наблюдение остальных кампаний.

Безопасное продолжение после сбоя обеспечивает не история диалога, а durable checkpoint: stage/cursor цикла, immutable входные версии, активный Mandate и его атомарно расходуемые лимиты, предрегистрация гипотезы, `ExecutionLedger`, before/intended/observed state и append-only events. После рестарта для незавершённых writes сначала выполняется reconciliation через readback; слепой повтор запрещён.

`Monitoring Cycle` — короткая, завершаемая попытка продвинуть долговечное состояние кампании, а не процесс, который неделями висит в памяти. Ожидание зрелости, решения человека или reconciliation хранится в durable campaign-control aggregate; очередное событие запускает новый цикл с новым snapshot и продвигает ту же гипотезу либо execution. Read-only циклы разных кампаний могут идти независимо, а writes сериализуются по общим collision resources и атомарным account-level лимитам.

## Findings

### 1. Граница решения

Это решение конкретизирует уже принятый bounded loop из [`ad-management-workflow-patterns.md`](ad-management-workflow-patterns.md), Campaign Effectiveness Profile из [`campaign-effectiveness-model.md`](campaign-effectiveness-model.md), экспериментальный протокол из [`safe-campaign-experimentation.md`](safe-campaign-experimentation.md) и Yandex capability boundary из [`yandex-direct-metrica-capabilities.md`](yandex-direct-metrica-capabilities.md).

Главное платформенное ограничение: Direct предоставляет изменяющие методы и readback, но не транзакционный rollback; `Changes.checkCampaigns` сообщает класс изменения, а точные значения нужно перечитать через `get`, поэтому MOX-ADV обязан хранить локальный before-snapshot и выполнять компенсирующую операцию из фактически наблюдённого состояния. Записи могут завершаться разными errors/warnings по отдельным объектам, то есть batch нельзя считать атомарным. [Direct `Changes.checkCampaigns`](https://yandex.com/dev/direct/doc/en/changes/checkCampaigns) · [Direct `Campaigns.update`](https://yandex.com/dev/direct/doc/en/campaigns/update) · [Direct API index](https://yandex.com/dev/direct/doc/en/llms.txt)

### 2. Составное входное состояние

Каждый запуск читает **один immutable `CycleInput`**, составленный из версионированных частей. Состояния не сворачиваются в один enum: policy принимает их одновременно и тем самым избегает комбинаторного взрыва.

| Регион | Минимальные состояния | Значение для переходов |
|---|---|---|
| `direct_state` | `READABLE`, `PLATFORM_PENDING`, `EXTERNALLY_CHANGED`, `UNSUPPORTED`, `UNAVAILABLE` | Фактические тип, стратегия, status/state, fingerprint и наличие незавершённой модерации. Модерация и часть platform lifecycle асинхронны. [Ad object/statuses](https://yandex.com/dev/direct/doc/en/objects/ad) |
| `metrica_state` | `READABLE`, `DELAYED`, `UNAVAILABLE`, `SCHEMA_DRIFT` | Доступность counter/goals и отчётных данных; сегодняшний день нельзя считать полным через Logs API. [Metrica Logs request](https://yandex.com/dev/metrika/en/logs/openapi/createLogRequest) |
| `campaign_state` | `ELIGIBLE`, `PAUSED_SAFE`, `IN_EXPERIMENT`, `COOLDOWN`, `LOCKED_BY_HUMAN`, `QUARANTINED`, `UNSUPPORTED` | Может ли кампания участвовать в новом решении и не конфликтует ли оно с активным изменением/экспериментом. |
| `data_state` | `UNAVAILABLE`, `STALE`, `IMMATURE`, `MATURE_COMPARABLE`, `INCOMPATIBLE`, `REVISED` | `MATURE_COMPARABLE` требуется для оценки; неполные данные допускают observation/diagnostics, но не финансовый write. Direct рекомендует перечитывать последние дни, потому что статистика обычно стабилизируется около трёх дней и может корректироваться позднее. [Direct data freshness](https://yandex.com/dev/direct/doc/en/actual) |
| `manual_reconciliation_state` | `CURRENT`, `DUE`, `OVERDUE`, `DISCREPANT`, `NOT_REQUIRED` | До CRM подтверждает доверие к business-conversion proxy. `OVERDUE` и `DISCREPANT` не останавливают ingestion, но блокируют новые решения, зависящие от неподтверждённого бизнес-результата. |
| `hypothesis_state` | `NONE`, `DRAFT`, `PREREGISTERED`, `ACTIVE`, `AWAITING_MATURITY`, `EVALUATED`, `REJECTED`, `INVALIDATED` | Только `PREREGISTERED` с primary metric, guardrails, horizon/maturity, stop rule и rollback plan может породить исполняемый Action Plan. |
| `mandate_state` | `ABSENT`, `ACTIVE`, `EXPIRED`, `REVOKED`, `EXHAUSTED`, `SUSPENDED_BY_BREACH` | Новый write допустим только при `ACTIVE` и достаточном остатке TTL/budget/quota. Reconciliation уже отправленного write продолжается при любом состоянии. |
| `execution_state` | `NONE`, `RESERVED`, `IN_FLIGHT`, `APPLIED_UNVERIFIED`, `VERIFIED`, `NO_CHANGE_VERIFIED`, `PARTIALLY_APPLIED`, `COMPENSATION_REQUIRED`, `FAILED`, `UNKNOWN_RESULT` | Имеет высший приоритет над запуском нового mutating cycle: для любого незавершённого исполнения сначала выполняется reconciliation. |

`CycleInput` также содержит `as_of`, границы cohort/data window, attribution model, Direct/Metrica watermarks, Campaign Effectiveness Profile version, Gate 0 Boundary version, policy version и ссылки на последние внешнее изменение/ручную сверку. Direct Reports и отдельный отчёт Метрики сопоставимы только при одинаковых goal IDs, датах и attribution semantics; набор поддерживаемых моделей задаётся явно. [Direct Reports specification](https://yandex.com/dev/direct/doc/en/spec) · [Metrica report parametrization](https://yandex.com/dev/metrika/en/stat/param)

### 3. Каноническая машина состояний одного Monitoring Cycle

```text
IDLE
  └─(schedule/change/maturity/mandate/manual-check event)→ OBSERVE
OBSERVE → VALIDATE
VALIDATE ─invalid/incompatible→ BLOCKED → COMPLETE
VALIDATE ─no Decision Trigger→ COMPLETE
VALIDATE ─eligible→ DIAGNOSE → PLAN → POLICY_CHECK
PLAN ─no action / insufficient evidence→ WAIT_MATURITY | COMPLETE
POLICY_CHECK ─denied→ BLOCKED | AWAITING_CRITICAL_DECISION → COMPLETE
POLICY_CHECK ─allowed→ RESERVE → EXECUTE → READBACK
READBACK ─verified/no-change→ WAIT_MATURITY | COMPLETE
READBACK ─partial→ RECONCILING → COMPENSATE | CONTAIN | ESCALATE
READBACK ─unknown→ UNKNOWN_RESULT → ESCALATE
WAIT_MATURITY ─window mature→ EVALUATE
WAIT_MATURITY ─guardrail breach→ SAFETY_CHECK → COMPENSATE | CONTAIN | ESCALATE
EVALUATE → RETAIN | REJECT | INCONCLUSIVE | COMPENSATE | ESCALATE
COMPENSATE → POLICY_CHECK(compensation) → RESERVE → EXECUTE → READBACK
RETAIN | REJECT | INCONCLUSIVE | CONTAINED | ESCALATED → COMPLETE → IDLE
```

`WAIT_MATURITY`, `AWAITING_CRITICAL_DECISION` и `RECONCILING` — состояния долговечного aggregate, а не незакрытая model-сессия. Текущий `Monitoring Cycle` фиксирует outcome и `next_due_at`, завершается, а следующий цикл продолжает с нового `CycleInput`. Поэтому длительное ожидание не удерживает lock и не сохраняет устаревший prompt.

#### Семантика состояний

1. **`OBSERVE`** — повторно читает Direct object state, Changes, Direct Reports и Метрику, затем создаёт новый immutable snapshot. Это read-only стадия; read retries bounded и не меняют объект.
2. **`VALIDATE`** — детерминированно проверяет trusted scope, типы, provenance, attribution, freshness, watermarks, campaign/profile compatibility, collision graph, cooldown, manual reconciliation и незавершённый ledger. Создаёт Decision Trigger только для нового `(snapshot_version, reason_code)`.
3. **`DIAGNOSE`** — модель получает очищенную проекцию проверенных фактов, предлагает возможные механизмы и недостающие данные; она не выбирает target и не исполняет API.
4. **`PLAN`** — модель формирует typed hypothesis/action intent. Runtime компилирует его в canonical Action Plan: exact targets, ordered atomic operations, expected fingerprint/diff, before-state, postconditions, observation/maturity window, stop conditions и compensation plan.
5. **`POLICY_CHECK`** — детерминированно проверяет Gate 0 Boundary, active Mandate, exact scope/action class, TTL, budget/quota reservation, monetary exposure, current fingerprint, kill switch, action frequency и platform constraints. Например, Direct запрещает ручное изменение ставки при автоматической стратегии, а дневной бюджет кампании можно менять не более трёх раз в сутки. [Campaign strategies](https://yandex.com/dev/direct/doc/en/objects/campaign-strategies) · [Direct errors, including strategy restrictions](https://yandex.com/dev/direct/doc/en/concepts/errors-list) · [`Campaigns.update`](https://yandex.com/dev/direct/doc/en/campaigns/update)
6. **`RESERVE`** — в одной локальной транзакции создаёт unique `execution_key`, резервирует mandate budget/quota и записывает pre-write audit event. Без durable commit переход к `EXECUTE` запрещён.
7. **`EXECUTE`** — единственный writer отправляет минимальный diff. Timeout не означает failure и не разрешает retry.
8. **`READBACK`** — разбирает per-object errors/warnings, повторно читает затронутые объекты и классифицирует `VERIFIED`, `FAILED`, `PARTIALLY_APPLIED` или `UNKNOWN_RESULT`. API `Changes` не заменяет точный readback. [Direct `Changes.checkCampaigns`](https://yandex.com/dev/direct/doc/en/changes/checkCampaigns)
9. **`WAIT_MATURITY`** — новые conflicting writes запрещены; разрешены polling, guardrail checks и emergency containment. Внутри state хранятся `not_before`, cohort cutoff и источник maturity. Данные Метрики в Direct Reports могут приходить через несколько часов, а Direct статистика ретроспективно корректируется, поэтому ранний неполный день не является основанием для обычного rollback. [Direct Reports restrictions](https://yandex.com/dev/direct/doc/en/restrictions) · [Direct data freshness](https://yandex.com/dev/direct/doc/en/actual)
10. **`EVALUATE`** — детерминированный evaluator проверяет preregistered decision rule на зрелых данных; модель только объясняет результат и предлагает следующую гипотезу. Выход ровно один: `RETAIN`, `ROLLBACK`, `REJECT`, `INCONCLUSIVE` или `ESCALATE`.
11. **`ROLLBACK`** — не rewind и не изменение прошлой записи, а новая bounded compensation с собственными policy check, execution key, readback и Decision Record. Внутреннее learning-state платформенной автостратегии восстановить нельзя, поэтому возврат внешних параметров не следует называть полным восстановлением платформы. [Campaign strategies](https://yandex.com/dev/direct/doc/en/objects/campaign-strategies) · [Direct API index](https://yandex.com/dev/direct/doc/en/llms.txt)
12. **`COMPLETE`** — атомарно закрывает цикл, выпускает lock и планирует следующий due event. Новый цикл всегда использует новый snapshot; старый план нельзя «продолжить» после изменения target/fingerprint/policy/mandate.

### 4. События и приоритет диспетчеризации

События являются durable facts с deduplication key; они будят workflow, но сами не разрешают write.

| Приоритет | Событие | Переход/действие |
|---:|---|---|
| 0 | `KILL_SWITCH_ON`, `BOUNDARY_BREACH`, `BUDGET_EXHAUSTED` | Запретить новые writes; незатронутые кампании продолжают observation. Если есть непосредственная угроза, выполнить только заранее разрешённый containment (`suspend` или compensation), иначе эскалировать. |
| 1 | `RECOVERY_STARTED`, `WRITE_TIMEOUT`, `READBACK_DUE` | Восстановить `RESERVED/IN_FLIGHT/APPLIED_UNVERIFIED/PARTIALLY_APPLIED`; выполнить readback до любого нового решения. |
| 2 | `EXTERNAL_CHANGE_DETECTED`, `HUMAN_EDIT_STARTED` | Инвалидировать старые fingerprints/plans, поставить конфликтующий объект в `LOCKED_BY_HUMAN`/`QUARANTINED`, собрать новый snapshot. |
| 3 | `MANDATE_REVOKED/EXPIRED`, `MANUAL_CHECK_OVERDUE/DISCREPANT` | Блокировать новый соответствующий Action Plan; не отменять readback и безопасное наблюдение. |
| 4 | `MODERATION_CHANGED`, `DATA_WATERMARK_ADVANCED`, `MATURITY_REACHED` | Продолжить platform wait или evaluation. Модерация является асинхронным platform-controlled lifecycle. [Ad object](https://yandex.com/dev/direct/doc/en/objects/ad) |
| 5 | `SCHEDULE_DUE`, `CHANGES_DETECTED`, `ANOMALY_DETECTED` | Начать `OBSERVE`, затем создать Decision Trigger только после validation. |
| 6 | `QUOTA_RESET`, `BACKOFF_EXPIRED` | Возобновить read/poll; write всё равно заново проходит policy/fingerprint/mandate checks. |

### 5. Поведение при обязательных fault-сценариях

| Сценарий | Каноническое поведение |
|---|---|
| **Ручная сверка просрочена** | `manual_reconciliation_state=OVERDUE`; продолжать Direct/Metrica ingestion и tracking-health диагностику. В затронутом measurement scope не начинать новые value-seeking writes и не признавать успех по proxy; активное изменение не расширять сверх уже зарезервированных срока/риска и по достижении stop boundary выполнить заранее утверждённый containment либо compensation. Создать один durable critical request. |
| **Ручная сверка расходится с Метрикой** | `DISCREPANT` + measurement incident; заморозить новые оптимизационные writes затронутого measurement scope, не «исправлять» Метрику моделью; сохранить обе величины/provenance, проверить goal/window/deduplication/attribution. При прямой угрозе — pre-authorized containment; возобновление только по явно записанному resolution event. |
| **Истёк срок Mandate** | После expiry запрещены новые optimization writes и новые reservations. `IN_FLIGHT` проходит readback/reconciliation. Допустимо только заранее утверждённое fail-safe containment; иначе `ESCALATE`. |
| **Исчерпан budget/quota** | Атомарная reservation не проходит, статус `EXHAUSTED`; не уменьшать requested delta молча и не заимствовать лимит другого scope. Наблюдение продолжается; возобновление — по новому Mandate или reset rule. |
| **Нарушено ограничение / stop condition** | Перейти в `SUSPENDED_BY_BREACH`; отменить неотправленные команды. Для отправленной — readback, затем deterministic `ROLLBACK/CONTAIN/ESCALATE` по preregistered rule. |
| **Данные незрелые/задержаны** | `WAIT_MATURITY`, не `REJECT`. Разрешены только safety guardrails, которые не требуют зрелого business outcome. Для offline conversions Метрика документирует появление данных в течение нескольких часов; время события, upload и observation следует хранить раздельно. [Metrica offline conversions](https://yandex.com/dev/metrika/en/management/offline-conv) |
| **Внешнее ручное изменение** | Инвалидировать plan по fingerprint, прекратить конфликтующие writes и прочитать фактическое состояние. Изменение через MOX-ADV проходит те же safety boundaries; out-of-band правка в кабинете не считается разрешённой задним числом, а обнаруживается как внешний факт и блокирует конфликтующий scope до нового snapshot и снятия human lock. |
| **Частичный batch success** | `PARTIALLY_APPLIED`; записать результат каждого объекта, readback каждого target и компенсировать только подтверждённо изменённые объекты в обратном порядке зависимостей. Не помечать весь batch success/failure. |
| **Неизвестный результат write** | `UNKNOWN_RESULT`; не повторять и не выполнять следующий write на объекте. Повторный readback/backoff; если состояние всё ещё неоднозначно — human escalation. |

### 6. Crash/restart semantics и минимальное durable state

Durable store должен быть источником истины workflow. Минимальный набор:

1. **`WorkflowInstance`** — `cycle_id`, account/campaign, current stage, stage version, `next_due_at`, retry/backoff budget, lock/lease owner и last durable event sequence.
2. **`CycleInputRef`** — hashes/IDs Direct/Metrica snapshots, watermarks, campaign fingerprint, Campaign Effectiveness Profile, policy/Gate 0 Boundary, Manual Reconciliation record, active Hypothesis и Mandate.
3. **`HypothesisRegistration`** — immutable contrast/mechanism, primary metric, guardrails, maturity rule, stopping rule, collision resources, expected effect and rollback/containment conditions.
4. **`MandateState`** — canonical Mandate, activation/revocation events, expiry, atomic daily/total monetary counters, action quotas и reservations.
5. **`ExecutionLedger`** — unique execution key; `RESERVED → IN_FLIGHT → APPLIED_UNVERIFIED → VERIFIED | NO_CHANGE_VERIFIED` либо `FAILED/PARTIALLY_APPLIED/COMPENSATION_REQUIRED/UNKNOWN_RESULT`; before-snapshot, intended diff/postconditions, request metadata, per-object outcomes, readback/after-snapshot и compensation link.
6. **`DecisionRecord` + append-only `WorkflowEvent`** — факты/Decision Triggers, model proposal reference, policy verdict/reason, execution/readback, evaluation и final outcome. Скрытые рассуждения модели не сохраняются.
7. **`CriticalRequest` / `Incident`** — affected scope, reason, requested product decision, safe fallback, dedup key и resolution event.

Правила восстановления:

- `RESERVED`, если доказано отсутствие отправки, можно отпустить или заново провести policy check; reservation не является разрешением повторить старый план после изменения входов.
- `IN_FLIGHT`/`APPLIED_UNVERIFIED` всегда переходят в `RECONCILING`; сначала readback, никогда новый POST/PUT «на всякий случай».
- `VERIFIED` не исполняется повторно: тот же execution key возвращает сохранённый outcome.
- `PARTIALLY_APPLIED` восстанавливается с per-step cursor; compensation строится от readback, а не от предположения.
- недоступность durable kill-switch/Mandate/ledger является fail-closed для writes, но не для read-only observation.
- после рестарта scheduler сначала разбирает recovery queue, затем due observation; это предотвращает наложение нового плана на неизвестное предыдущее состояние.

### 7. Инварианты

1. На один collision resource set (кампания, shared budget, bidding loop, goal/tracking scope или пересекающаяся аудитория) одновременно существует не более одного `IN_FLIGHT`, `APPLIED_UNVERIFIED`, `PARTIALLY_APPLIED` или `COMPENSATION_REQUIRED` write-workflow; account-level exposure резервируется атомарно.
2. Ни один write не отправляется до durable `RESERVED` и pre-write audit event.
3. Один execution key соответствует одному `(proposal version, target, exact diff, expected fingerprint, policy version, mandate version)`.
4. Любое изменение snapshot/fingerprint/profile/policy/mandate делает старое write-разрешение недействительным.
5. `ACTIVE` Mandate необходим для нового autonomous write; модель не создаёт, не расширяет и не активирует Mandate.
6. Kill switch и Gate 0 Boundary имеют приоритет над model proposal и Mandate.
7. Readback обязателен после каждого write; accepted API response не равен verified postcondition.
8. `UNKNOWN_RESULT` и неразрешённый `PARTIALLY_APPLIED` блокируют следующий write только в затронутом scope.
9. Незрелые/несопоставимые данные не дают `RETAIN`/`REJECT`; результат только `WAIT_MATURITY`, `INCONCLUSIVE` или measurement incident.
10. Новый change запрещён до observation window/cooldown предыдущего, кроме pre-authorized safety containment.
11. Rollback — новый auditable write, а не удаление истории.
12. Один `(snapshot_version, reason_code, policy_version)` не создаёт несколько активных proposals.

### 8. Модель против детерминированного runtime

| Модель предлагает | Runtime единолично определяет |
|---|---|
| Диагноз, альтернативные механизмы и недостающие данные | Получение/нормализацию данных, KPI, freshness/maturity и comparability |
| Typed Hypothesis и ожидаемое направление эффекта | Decision Trigger, eligibility, collision graph и preregistration validity |
| Typed intent из allowlisted action classes | Exact target/value/diff, platform compatibility и execution order |
| Краткое объяснение policy verdict и результата | Gate 0 Boundary, Mandate, limits, reservations, kill switch и authorization |
| Следующую кандидатную гипотезу | Idempotency, единственный writer, API call, per-object result и readback |
| Возможные причины inconclusive результата | Evaluation rule, stop/rollback/containment, audit и recovery |

Модель никогда не получает OAuth credentials, не выбирает произвольный endpoint, не подтверждает собственный план и не решает, что данные «уже достаточно зрелые» вне зарегистрированного правила.

## Sources

- Kept: [Yandex Direct API overview](https://yandex.com/dev/direct/doc/en/concepts/overview) — назначение и общий supported automation surface.
- Kept: [Yandex Direct API full index](https://yandex.com/dev/direct/doc/en/llms.txt) — инвентарь методов и отрицательная проверка отсутствия универсальной transaction/rollback primitive.
- Kept: [Campaigns.update](https://yandex.com/dev/direct/doc/en/campaigns/update) — object-level results и platform limits для budget changes.
- Kept: [Campaign strategies](https://yandex.com/dev/direct/doc/en/objects/campaign-strategies) и [Direct errors](https://yandex.com/dev/direct/doc/en/concepts/errors-list) — граница между оператором и platform automation.
- Kept: [Ad object/statuses](https://yandex.com/dev/direct/doc/en/objects/ad) — асинхронная модерация и state/readback.
- Kept: [Changes.checkCampaigns](https://yandex.com/dev/direct/doc/en/changes/checkCampaigns) — change detection без old-value rollback.
- Kept: [Direct data freshness](https://yandex.com/dev/direct/doc/en/actual) и [Reports restrictions](https://yandex.com/dev/direct/doc/en/restrictions) — ретроспективные корректировки и задержки данных.
- Kept: [Direct Reports specification](https://yandex.com/dev/direct/doc/en/spec), [Metrica report parametrization](https://yandex.com/dev/metrika/en/stat/param), [Metrica Logs request](https://yandex.com/dev/metrika/en/logs/openapi/createLogRequest) — attribution/comparability и неполнота текущего дня.
- Kept: [Metrica offline conversions](https://yandex.com/dev/metrika/en/management/offline-conv) — отдельная задержка offline outcome ingestion.
- Kept: локальные research-артефакты тикетов #52–#55 — уже проверенные claim-to-source matrices и принятые архитектурные предпосылки.
- Dropped: вторичные статьи, SEO-обзоры и непроверенные vendor comparisons — не нужны для решения и не являются первичными источниками.

## Gaps

1. **Нужен отдельный HITL product ticket:** «Как устроена периодическая ручная сверка бизнес-конверсий?» В нём владелец должен утвердить cadence по типу Campaign Effectiveness Profile, запись подтверждения (period, Метрика goal/value, фактический result/value, provenance, actor), допустимое расхождение, grace period, affected scope и условия автоматического возобновления. Текущий технический выбор безопасно параметризует эти значения, но не подменяет бизнес-решение.
2. Точные polling/backoff, freshness, maturity, cooldown, monetary limits, mandate TTL и guardrail thresholds являются Gate 0 parameters, а не универсальными числами.
3. API не предоставляет универсального способа восстановить внутреннее learning-state автоматической стратегии; компенсация возвращает только наблюдаемые внешние параметры.
4. Для campaign experiment provisioning официальный Direct write-interface не подтверждён; если он остаётся UI/pre-provisioned, `HypothesisRegistration` должен ссылаться на заранее созданный experiment ID, а оператор — лишь читать/оценивать его данные.
5. Реализация, схема БД и runtime deployment находятся за destination текущей Wayfinder-карты; это решение задаёт поведение, а не поставляет production код.
