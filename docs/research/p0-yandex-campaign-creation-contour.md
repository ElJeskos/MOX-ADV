# P0: минимальный настоящий контур создания кампании Яндекс Директа

**Ticket:** [P0 · Исследовать продуктовый и API-контур создания кампании](https://github.com/ElJeskos/MOX-ADV/issues/84)<br>
**Репозиторий:** `ElJeskos/MOX-ADV`<br>
**Дата среза репозитория:** 20.08.2026<br>
**Дата свежей проверки официальной документации:** 20.08.2026<br>
**Режим:** исследование и проектное решение; production API-запросы и внешние записи не выполнялись.

## Короткое решение

Минимальный настоящий P0 следует реализовывать как **одну поисковую `UNIFIED_CAMPAIGN`, одну `UNIFIED_AD_GROUP`, одну явную ключевую фразу и одно простое `TEXT_AD` без изображений, автотаргетинга, сетей и расширений**. Для холодного старта рекомендуется Search `WB_MAXIMUM_CLICKS` с `WeeklySpendLimit` и `BidCeiling`, Network `SERVING_OFF`. Сразу после `Campaigns.add`, пока дочерних объектов ещё нет, P0 обязан вызвать `Campaigns.suspend` и подтвердить `State=SUSPENDED`; полагаться на состояние draft `OFF` нельзя, потому что после успешной модерации, наступления `StartDate` и наличия средств показы могут начаться автоматически. Успешный результат P0 — `CREATED → SUSPENDED_CONFIRMED → MODERATION_PENDING/ACCEPTED → READY_TO_LAUNCH` без расхода денег.

Метрика в P0 нужна как **read-only preflight измеримости** существующих счётчика и основной цели и как сохранённая связь для следующего модуля; создавать цель, публиковать `reachGoal`, ждать статистику или включать конверсионную стратегию в транзакцию создания кампании не нужно. Если цель или событие ещё не проверены, можно создать безопасно приостановленную кампанию, но нельзя объявлять её готовой к расходу.

Это не небольшое включение уже готового production-кода: текущий репозиторий содержит полноценную fake-saga и реальный строго read-only транспорт, но **не содержит production Direct adapter**, использует внутренние payload-формы, не совпадающие с Direct v501, моделирует модерацию синхронно и затем автоматически возобновляет кампанию. Эти разрывы являются P0-blocker до любой реальной записи.

---

## 1. Scope и метод

Исследование сопоставляет три слоя:

1. принятую продуктовую основу карты [«MVP MOX-ADV вокруг AI-агента»](https://github.com/ElJeskos/MOX-ADV/issues/76) и решений [«Сформировать структуру целевого mock-прототипа»](https://github.com/ElJeskos/MOX-ADV/issues/77) / [«Создать и принять единый интерактивный mock-прототип»](https://github.com/ElJeskos/MOX-ADV/issues/78);
2. текущие локальные contracts, policy, fake lifecycle, production read path и тесты;
3. актуальные официальные reference-страницы Direct API v5/v501 и Metrica API.

### Проверка источников

Ключевые method schemas и lifecycle-страницы были заново открыты 20.08.2026 непосредственно в официальной документации Яндекса: `Campaigns.add` и `add-unified-campaign`, совместимость стратегий, `Campaigns.suspend`, campaign state/status, `AdGroups.add`, `Ads.add/get/moderate`, `Keywords.add`, Metrica goals и OAuth scopes. Production API-запросы и обращения к кабинетам не выполнялись. Account-specific eligibility и фактические ограничения конкретного рекламодателя остаются непроверенными до отдельного read-only preflight.

---

## 2. Принятая продуктовая основа и текущая граница real/Test Scenario

### 2.1 Что уже принято владельцем

**Факт (продукт).** Существующий Dashboard сохраняется и расширяется, а не заменяется. P0-путь начинается с опроса AI-агента `Бизнес → Модель → Цель → Стратегия`, затем показывает редактируемую стратегию, Campaign Draft, подтверждение и состояние созданной кампании. Полный редактор, Goal Lifecycle, группы и объявления остаются частью продукта. Все текущие действия публичного прототипа — Test Scenario без API-записей; целевой viewport — `1920×1080`. См. resolution issues 77 и 78.

**Следствие.** Настоящий P0 должен заменить только мок создания, не ломая старые поверхности Dashboard и не превращая весь Dashboard в новый runtime. UI может показывать более богатый Draft, чем первый реальный adapter поддерживает, но перед подтверждением обязан явно показать, какой **тонкий publish projection** реально уйдёт в Direct.

### 2.2 Что реально работает сейчас

| Контур | Текущее состояние | Репозиторное доказательство |
|---|---|---|
| Локальные Campaign Drafts | Реальное SQLite-хранение, revisions, optimistic concurrency; внешней записи нет | `src/mox_adv/ui_campaign.py` (`DashboardCampaignStore`), `tests/test_ui_campaign.py` |
| Campaign preview / simulation | Реальная orchestration поверх fake Direct adapter; артефакты честно помечены `SIMULATION` | `src/mox_adv/ui_workflows.py`, `tests/test_ui_workflows.py` |
| Campaign creation saga | Durable fake saga: campaign → group → ads → keyword → moderate → readback → resume → full readback | `src/mox_adv/campaign_lifecycle.py`, `tests/test_campaign_lifecycle.py` |
| Direct production read | Реальные allowlisted `Campaigns.get` и Reports `get`; только одна Unified campaign | `src/mox_adv/yandex_read.py` (`YandexReadOnlyTransport`), `tests/test_yandex_read.py` |
| Metrica production read | Реальный allowlisted Statistics `get`; один counter/goal | те же файлы |
| Direct production write | **Отсутствует**: connector protocol есть, но фактический adapter только `FakeDirectManagementAdapter` | `src/mox_adv/direct_management.py` |
| Write authorization | Production writes выключены, pilot bindings пусты; HTTP guard требует `pilot_armed` и `production_write_authorized=true` | `config/gate0-policy.json`, `src/mox_adv/egress.py` |
| Metrica goal lifecycle | Полный fake lifecycle; policy содержит документированную API matrix, но production goal/site executors не встроены в P0 | `src/mox_adv/goal_lifecycle.py`, `tests/test_goal_lifecycle.py`, `tests/test_ui_workflows.py` |

### 2.3 Production/read/write boundary

**Факт (repository).** `YandexReadOnlyTransport._ALLOWED` допускает ровно три операции: Direct Reports `get`, Direct Campaigns `get` и Metrica Statistics `get`. Любой другой method/path/verb отклоняется до HTTP. README отдельно обещает `write_requests_allowed=false` и отсутствие executor invocation.

**Факт (repository).** `DirectManagementConnectorV1` разрешает non-fake adapter только если одновременно заполнены pilot bindings, присутствует точно связанная approval authority, включён durable dispatch guard и `record.production_write_authorized == true`. В текущем policy это значение `false`, а pilot targets `null`.

**Рекомендация.** Не ослаблять существующую read-only границу. Реальный P0 write transport должен быть отдельным adapter/credential profile `DIRECT_PILOT_WRITE` и вызываться только из exact-bound creation saga; dashboard production-read токены из `.env` никогда не должны получить write-методы.

---

## 3. Официальные API-факты и выбранный P0-профиль

### 3.1 Общие факты API

1. Direct API v5 работает через HTTPS/JSON и предназначен для добавления и изменения кампаний, объявлений и ключевых фраз, управления ставками и получения статистики. Direct transport использует HTTP `POST`, а семантический method передаётся в JSON; поэтому `POST + method=get` остаётся чтением. [1][2]
2. Для `UNIFIED_CAMPAIGN` используется production URL v501. В `Campaigns.add` обязательны `Name`, `StartDate` и type-specific `UnifiedCampaign`; внутри `UnifiedCampaign.BiddingStrategy` обязательны стратегии Search и Network. `WB_MAXIMUM_CLICKS` требует `WeeklySpendLimit`, допускает `BidCeiling`, а совместимая Network-стратегия `SERVING_OFF` отключает сети. [3][11][13]
3. `Campaigns`, `AdGroups`, `Ads` и `Keywords` имеют отдельные add/get/update/control methods; типы родительских и дочерних объектов должны быть совместимы. Официальный launch guide задаёт порядок создания структуры и последующую модерацию. [3][4][5][6][7]
4. `Campaigns.add` не принимает произвольное поле `state`. До модерации кампания имеет `Status=DRAFT` и обычно `State=OFF`, но это не защитный stop: после приёмки объявления, наступления даты старта и при наличии средств показ может начаться. Явный безопасный барьер — `Campaigns.suspend` с последующим readback `State=SUSPENDED`. [3][7][14][25]
5. Add/update/control calls возвращают warnings/errors на уровне элементов; пакет нельзя считать атомарным. После записи нужен per-item разбор ответа и отдельный `get` readback. [3][8][25]
6. Модерация объявлений асинхронна и управляется платформой. `Ads.moderate` принимает только ads со `Status=DRAFT`; фактические `State`, `Status` и `StatusClarification` читаются через `Ads.get`. Возможны `DRAFT`, `MODERATION`, `PREACCEPTED`, `ACCEPTED`, `REJECTED`; отправка на модерацию не равна разрешению показа. [5][9][10]
7. При автоматической стратегии конкретные keyword bids меняет Яндекс; переданные `Bid`/`ContextBid` не применяются. Значит P0 не должен отправлять ставки ключевой фразы при `WB_MAXIMUM_CLICKS`. [6][11][12]
8. Денежные значения Direct передаются в micros (`рубли × 1 000 000`). Для выбранной стратегии `WeeklySpendLimit` обязателен, `BidCeiling` опционален; campaign-level `DailyBudget` относится к ручной стратегии и в этом срезе не нужен. [3][13][14]
9. В актуальном production reference `UNIFIED_CAMPAIGN` однозначно присутствует в add/get/update schemas; некоторые campaign types доступны только для статистики. [14][15]
10. Direct API не предоставляет универсальную transaction/rollback или client idempotency key. `Changes` и повторные `get` помогают обнаружить состояние, но не возвращают старую версию; rollback требует локального snapshot и компенсирующих операций. [16][17]
11. Metrica Management API отдельно предоставляет список целей через `GET /management/v1/counter/{counterId}/goals`, а `metrika:read` достаточно для чтения доступного счётчика. Наличие цели доказывает существование объекта, но не факт поступления нужного бизнес-события с сайта/CRM. [18][24]

### 3.2 Fact / Recommendation / Product decision

#### Тип кампании

- **Факт:** `UNIFIED_CAMPAIGN` поддерживается текущим Direct reference и уже является единственным типом repository policy, draft validation и production reader. [13][14]
- **Рекомендация:** P0 поддерживает только `UNIFIED_CAMPAIGN`.
- **Продуктовое решение следующего grilling:** не требуется выбирать технический тип; UI должен говорить «Поисковая кампания Яндекс Директа», не заставляя владельца понимать API enum.

#### Размещения и стратегия

- **Факт:** совместимость Search/Network strategy задаётся campaign-specific `BiddingStrategy`; ручные keyword bids несовместимы с автоматическими стратегиями. [11][12]
- **Рекомендация:** для первого холодного P0 использовать Search `WB_MAXIMUM_CLICKS` + Network `SERVING_OFF`, с обязательным `WeeklySpendLimit` и консервативным `BidCeiling`. Эта официально совместимая пара прямо выражает принятые недельный бюджет и максимальный финансовый шаг, не требует уже обученной Metrica goal и содержит меньше agent-chosen экономических параметров, чем `AVERAGE_CPC`. Переход на `AVERAGE_CPA`/maximize conversions относится к P1 после проверки цели и накопления сигнала. [11][13]
- **Важно:** это осознанно заменяет repository policy `HIGHEST_POSITION`. Выбранная стратегия подтверждена текущей общей schema; перед production-write остаётся только account-specific read-only preflight валютных минимумов и ограничений, а не повторный продуктовый выбор.
- **Продуктовое решение:** владелец выбирает бизнес-бюджет и приемлемую стоимость результата; точный API strategy enum, `BidCeiling` и fallback выбирает агент.

#### Campaign fields

- **Факт:** real `Campaigns.add` ожидает documented v501 Unified object (`Name`, `StartDate`, optional `TimeZone` и type-specific `UnifiedCampaign`), а не внутренние поля `type/state/strategy/geography/schedule/WeeklySpendLimit` верхнего уровня. Поле `state` в add отсутствует. [3][13]
- **Рекомендация:** минимальная проекция содержит `Name`, `StartDate`, account-compatible `TimeZone` и `UnifiedCampaign.BiddingStrategy`; сразу после получения campaign ID выполняются `Campaigns.suspend` и `Campaigns.get`. Только подтверждённый `State=SUSPENDED` разрешает создавать дочерние объекты. `Campaigns.resume` не входит в P0.
- **Продуктовое решение:** название кампании, дата желаемого старта и бизнес-бюджет; технические defaults не спрашивать.

#### Группа

- **Факт:** группа создаётся после campaign ID; Unified group использует compatible subtype, campaign binding и targeting fields. Региональный таргетинг Direct принадлежит group payload (`RegionIds`), а не текущему generic campaign field. [4][7]
- **Рекомендация:** ровно одна `UNIFIED_AD_GROUP`: `Name`, `CampaignId`, непустые numeric `RegionIds`, optional `NegativeKeywords` и обязательная структура `UnifiedAdGroup: {"OfferRetargeting":"NO"}`. Autotargeting и audience targets не создаются. Region IDs получать из `Dictionaries.get`/проверенной конфигурации, не угадывать по строке `RU`.
- **Продуктовое решение:** география на языке бизнеса; агент переводит её в RegionIds и показывает итог человеку.

#### Объявление

- **Факт:** `Ads.add` принимает ad-group-bound type-specific payload; text ad имеет title/text/href и может иметь дополнительные assets. Тип после создания не меняется. [5][21]
- **Рекомендация:** одно `TEXT_AD` через `TextAd` с `Title`, `Text`, `Href` и технически обязательным deprecated-полем `Mobile: "NO"`; без image, video, sitelinks, callouts и creative upload. Остальные варианты богатого Dashboard Draft остаются локальными и помечаются «не публикуются в первом P0».
- **Продуктовое решение:** какой пользовательский вариант текста является первым публикуемым объявлением и какой landing page считать окончательным.

#### Ключевая фраза

- **Факт:** `Keywords.add` создаёт критерий после получения ad group ID; criteria можно читать, приостанавливать, возобновлять и удалять. [6][22]
- **Рекомендация:** одна явная phrase, без autotargeting; минус-фразы сохранять на уровне группы. В `Keywords.add` передаются только `Keyword` и `AdGroupId`: `Bid`, `ContextBid` и `KeywordBids.set` не используются при `WB_MAXIMUM_CLICKS`.
- **Продуктовое решение:** пользователь подтверждает смысловой сегмент/фразу, но match operators и API normalization выбирает агент и показывает readback.

#### Модерация и безопасное состояние

- **Факт:** `Ads.moderate` — асинхронная platform-controlled операция; `MODERATION` не означает `ACCEPTED`. [9][10]
- **Рекомендация:** кампания явно переводится в `SUSPENDED` до создания группы и остаётся там после `Ads.moderate`. P0 job опрашивает `Ads.get` с bounded backoff и завершает одним из состояний `MODERATION_PENDING`, `READY_TO_LAUNCH`, `REJECTED_NEEDS_EDIT` или `MIXED_REVIEW`. `Campaigns.resume` не входит в P0 create transaction.
- **Продуктовое решение:** только пользовательские тексты финальных статусов и ожидаемое «что будет дальше»; вопрос «можно ли автоматически включить показы» не задавать — в P0 нельзя.

---

## 4. Рекомендуемый тонкий технический срез

### 4.1 Publish projection

Из богатого Dashboard draft публикуется только:

- один allowlisted Direct account;
- одна `UNIFIED_CAMPAIGN`;
- Search `WB_MAXIMUM_CLICKS`, Network `SERVING_OFF`;
- один `WeeklySpendLimit` и один защитный `BidCeiling`;
- обязательный `Campaigns.suspend` сразу после создания и readback `State=SUSPENDED` до дочерних writes;
- одна группа;
- один набор RegionIds;
- одна ключевая фраза и набор минус-фраз;
- одно text ad;
- один HTTPS landing URL с детерминированными UTM;
- existing Metrica counter ID и primary goal ID как measurement binding, но не как write payload конверсионной стратегии.

**Не публикуются в P0:** второе объявление, изображения, видео, sitelinks, callouts, autotargeting categories, audiences, multiple groups/keywords/goals, SEO content, strategy switching и any campaign resume.

### 4.2 Preflight

1. Зафиксировать immutable `draft_revision`, exact publish projection, account, policy version и approval binding.
2. Проверить write credential/account binding отдельным `DIRECT_PILOT_WRITE` profile, не читая production-read `.env` как write authority.
3. Read-only проверить отсутствие уже завершённого execution key и отсутствие доказанного дубликата.
4. Нормализовать name, RegionIds, dates/time zone, micros и URL; проверить landing page и prohibited copy.
5. Read-only проверить существующие Metrica counter/goal IDs и сохранить статус `MEASUREMENT_BOUND` или `MEASUREMENT_UNVERIFIED`.
6. Записать durable dispatch intent до первого HTTP write.

### 4.3 Ordered API flow

1. `Campaigns.add` — одна Unified campaign с Search `WB_MAXIMUM_CLICKS`, Network `SERVING_OFF`; разобрать per-item `Id`, warnings и errors и немедленно сохранить ID.
2. `Campaigns.suspend` — остановить campaign ID до создания любого способного к показу дочернего объекта.
3. `Campaigns.get` — подтвердить `Id`, `Type=UNIFIED_CAMPAIGN`, strategy/budget, `State=SUSPENDED`, status и time zone. Без этого шага продолжение запрещено.
4. `AdGroups.add` — одна Unified group с campaign ID, `RegionIds`, negative keywords и `OfferRetargeting=NO`.
5. `AdGroups.get` — подтвердить parent ID, type, region/negative keyword projection и status.
6. `Keywords.add` — одна phrase без bid fields.
7. `Keywords.get` — подтвердить normalized phrase, group ID, state/status.
8. `Ads.add` — одно `TextAd` с `Mobile=NO`.
9. `Ads.get` — подтвердить type, copy, final URL, group ID и `Status=DRAFT`.
10. `Ads.moderate` — отправить exact ad ID через `SelectionCriteria.Ids`.
11. `Ads.get` polling — bounded exponential backoff с persisted next-poll time; фиксировать `Status`, `State`, `StatusClarification`.
12. `Campaigns.get` + `AdGroups.get` + `Keywords.get` + `Ads.get` — итоговый full readback, включая сохранённый `State=SUSPENDED`.
13. Завершить `READY_TO_LAUNCH` только если объявление принято и кампания явно suspended; иначе сохранить честный pending/rejected/unknown result.

`Campaigns.resume` отсутствует. Запуск — отдельное будущее high-level действие с новой authority/readiness проверкой.

### 4.4 State machine

```text
LOCAL_DRAFT
  → APPROVED_PROJECTION
  → DISPATCHING_CAMPAIGN
  → CAMPAIGN_CREATED
  → SUSPEND_DISPATCHED
  → SUSPENDED_CONFIRMED
  → GROUP_CREATED
  → KEYWORD_CREATED
  → AD_CREATED_DRAFT
  → MODERATION_SUBMITTED
  → MODERATION_PENDING ───────────────┐
       ├─ ACCEPTED → READY_TO_LAUNCH  │
       ├─ REJECTED → NEEDS_EDIT       │
       └─ timeout → PENDING_EXTERNAL  │
                                      │
unknown transport result → RECONCILIATION_REQUIRED
partial definite failure → COMPENSATING → COMPENSATED | MANUAL_RECONCILIATION
```

Ни одно состояние P0 не переходит в `ON`.

### 4.5 Failure, retry и readback

- Parse HTTP-level error, top-level API error и per-item warnings/errors отдельно.
- После каждого add сохранять external ID **до** следующего write.
- Повторять безопасно только reads и подтверждённо неотправленные writes.
- Timeout после отправки write означает `UNKNOWN_RESULT`; blind retry запрещён.
- Для unknown `add` сначала reconcile через catalog/get и сравнение ожидаемой object graph. Имя кампании не является уникальным idempotency key, поэтому неоднозначный результат требует ручного reconciliation, а не второй кампании.
- Retry для quota/transient failures — bounded backoff с jitter и persisted attempt schedule; не создавать параллельные writes для одного execution key.
- Partial success в массиве — сохранить каждый успешный ID, прекратить движение вперёд и компенсировать только объекты текущего run в обратном порядке зависимостей.
- Delete не считать универсальным rollback: если состояние запрещает delete или результат неизвестен, оставить campaign suspended и эскалировать.
- Итоговый успех требует readback фактического типа и canonical поля каждого объекта, а не только наличия ID.

---

## 5. Current-to-target gap table

| Severity | Разрыв | Сейчас | Нужно до real P0 |
|---|---|---|---|
| **BLOCKER** | Production Direct adapter отсутствует | Только `FakeDirectManagementAdapter`; non-fake protocol не реализует HTTP/JSON mapping | Отдельный guarded v501 adapter для пяти P0 methods + get readbacks |
| **BLOCKER** | Production write выключен | `production_write_authorized=false`, pilot bindings `null` | Exact account/single-writer/credential binding и отдельное явно принятое включение; не менять в research |
| **BLOCKER** | Payload не соответствует v501 | generic `type/state/strategy/geography/schedule`; snake_case child payloads | Method-specific serializers по текущим `Campaigns/AdGroups/Ads/Keywords` schemas |
| **BLOCKER** | Безопасное состояние смоделировано несуществующим add-полем | fake передаёт `state: SUSPENDED`; connector допускает `campaigns_suspend` только из fake-state `ON`; saga затем вызывает `resume` | Реальный `Campaigns.add → suspend → get(State=SUSPENDED)` до child writes; no resume in P0 |
| **BLOCKER** | Неверная moderation semantics | fake требует немедленный `MODERATION`, затем вызывает `Campaigns.resume` и считает `APPLIED` | Асинхронный polling, accepted/rejected/pending states; campaign остаётся suspended |
| **BLOCKER** | Strategy/budget contracts противоречат друг другу | policy/draft = `HIGHEST_POSITION`; editor = maximize-* labels; reader fixture = `AVERAGE_CPC` + `WeeklySpendLimit` | Один publish enum `WB_MAXIMUM_CLICKS`, `WeeklySpendLimit` + `BidCeiling`, честное UI explanation |
| **BLOCKER** | Full readback только fake-shaped | сравниваются lowercase/internal keys и ad state `MODERATION` | Parse actual Direct response fields/types/statuses and compare canonical projection |
| **HIGH** | География находится не там и не в том формате | campaign `geography: ["RU"]` | group `RegionIds` из validated dictionary/config |
| **HIGH** | Rich editor silently collapses data | до 20 groups/50 ads/20 keywords, но `_campaign_draft` берёт одну группу, первую phrase и A/B | Явный publish projection preview с unsupported-field disclosure |
| **HIGH** | P0 slice и schema расходятся | schema/validator требуют 2 ads и prepared media | P0 schema revision: 1 publish ad without media; migration/compatibility decision before code |
| **HIGH** | Existing reader не покрывает object graph | production read получает campaign + reports + Metrica stats | Management readback для group/ad/keyword/moderation under exact write authority |
| **HIGH** | Unknown add cannot be reliably reconciled | fake adapter remembers idempotent result in memory | Durable dispatch + API reconciliation/manual gate; no blind retry |
| **HIGH** | Metrica binding synthetic in draft | Dashboard counter is simulation ID; production config expects numeric goal/counter | Read-only counter/goal selection and exact binding; no goal write in P0 |
| **MEDIUM** | Assets are local references, not Direct resources | `prepared-media-*` strings | Exclude assets from first P0; asset upload is separate later slice |
| **MEDIUM** | Schedule is generic | days/start/end hardcoded then passed through | Compile to current Direct time-targeting schema or omit optional restriction for first slice |
| **MEDIUM** | Credential source split unfinished | dashboard `.env` intentionally read-only; Keychain write profile declared only in policy | Wire write credential to separate protected provider without broadening dashboard reader |
| **MEDIUM** | Compensation assumes delete always works | fake deletes all current-run objects | State-aware compensation; suspended containment + manual reconciliation fallback |

---

## 6. Роль Метрики в P0

### Факты

- Direct campaign object creation and ad moderation are separate from Metrica goal CRUD. [3][9][18]
- Conversion-based strategies need valid goal/data conditions, while a click-oriented bootstrap strategy does not require P0 to create a Metrica goal. [11][18]
- Existing MOX-ADV production mode can read one counter/goal statistics binding but cannot list goals through its strict three-operation transport.
- Current fake Goal Lifecycle includes goal creation and site event publishing, but both are separate high-risk workflows with separate authorities.

### Рекомендация

P0 does only:

1. accept/select one existing counter and one existing primary goal;
2. `getGoals`/`getGoal` readback to prove IDs, names/types/status;
3. retain the business meaning and instrumentation verification status;
4. block any later `resume`/conversion strategy if measurement remains unverified.

P0 does **not**:

- create/edit/delete a Metrica goal;
- publish `reachGoal` to the website;
- upload offline conversions;
- wait for conversions or reports before declaring the suspended object graph created;
- use a conversion-based bidding strategy;
- claim that a goal is technically or semantically valid merely because its ID exists.

If the business has no suitable existing goal, P0 may end as `SUSPENDED_CONFIRMED + MEASUREMENT_SETUP_REQUIRED`; goal/site setup becomes its own authorized slice before launch.

---

## 7. Facts and questions for the next product grilling

The next ticket should receive these facts first, so the owner is not asked technical/API/safety questions.

### Facts to present

1. The first real P0 can publish only one Search campaign, one group, one phrase and one plain text ad; rich assets and extra variants stay as local drafts.
2. Confirmation creates real Direct objects, immediately suspends the campaign, confirms that stop through readback, and only then sends the ad to moderation; it does not start spend.
3. Moderation may remain pending or reject the ad; the Dashboard must show that external state honestly.
4. A real campaign can be created safely even if measurement is not ready, but it remains suspended and cannot be promoted as launch-ready.
5. One existing Metrica counter and primary goal should be selected before the future launch; P0 does not silently edit the site or create a goal.
6. The first strategy is a conservative click-oriented bootstrap, not a promise to optimize CPA immediately; target CPA remains the business goal and becomes an optimization control only after measurement readiness.
7. Extra groups, keywords, ad variants, images, networks and autotargeting are visible as future/local capabilities, not silently discarded.

### Product questions only

1. **What should the main confirmation promise say?** Suggested options for wording: “Создать и отправить на модерацию” versus “Подготовить реальную кампанию к запуску”. The behavior remains suspended either way.
2. **Which single business offer/segment is the first real publish slice?** The owner names the offer/audience outcome; the agent chooses API targeting details.
3. **Which one landing page is final for the first campaign?** The owner confirms the business page and what qualified action should happen there.
4. **Which one ad message should be the first published variant?** The owner chooses among understandable copy options; unsupported assets are disclosed.
5. **What business geography and operating window are acceptable?** The owner answers in business terms; the agent maps to RegionIds/time targeting.
6. **Which existing Metrica goal corresponds to a qualified result from the owner’s perspective?** Ask for business meaning, not a goal ID or API type. The agent inspects and binds the technical object.
7. **After rejection, should the product return directly to the editable Draft or open a focused “Исправить замечания” step?** This is a UX/product route decision.
8. **What outcome should the P0 completion screen emphasize:** real object created, moderation passed, or measurement ready? Recommended product hierarchy: object created → moderation state → next blocked step.

Do **not** ask the owner to choose campaign API type, strategy enum, micros, Direct method order, retry policy, moderation polling, credential profile, RegionIds, payload schema or whether P0 may auto-resume; these are agent-owned decisions.

---

## 8. Explicit non-goals

- Starting impressions or spending money.
- Conversion-based bidding or automated CPA optimization.
- P1 changes to budgets, bids or ad variants.
- Metrica goal creation, site instrumentation or CRM/offline conversions.
- Multiple groups, phrases, ads or goals in real Direct.
- Images, video, creatives, sitelinks, callouts and asset upload.
- Network placements, autotargeting, audiences, retargeting and experiments.
- Universal rollback, archive lifecycle or cleanup of foreign/existing objects.
- Browser cabinet work; only official Direct/Metrica APIs are in scope.
- Replacing existing Dashboard navigation or implementing the P0 module in this research ticket.

---

## 9. Risks and unresolved checks

1. **Live account capability check.** Current schemas were freshly verified, but OAuth access, advertiser restrictions, currency minimums and availability in the actual account were not tested; perform a read-only `Clients.get`/dictionary preflight before implementation.
2. **Suspension reconciliation.** If `Campaigns.add` returns an ambiguous transport outcome, no child objects may be created until the campaign is found and `State=SUSPENDED` is confirmed; duplicate-safe automatic reconciliation is not guaranteed by Direct.
3. **No universal add idempotency.** An ambiguous timeout can require manual reconciliation; the product needs an honest `RECONCILIATION_REQUIRED` state.
4. **Moderation latency has no P0 SLA.** The state machine must tolerate pending external work rather than hold one synchronous HTTP request.
5. **Measurement semantics remain human-owned.** API can prove a goal object exists, not that it means “qualified lead”; next grilling must confirm business meaning.
6. **Existing dirty working tree.** This research did not inspect or modify unrelated uncommitted user changes; repository claims refer only to files read during this task.

---

## 10. Numbered primary sources

[1] [Direct API overview](https://yandex.com/dev/direct/doc/en/concepts/overview)<br>
[2] [Direct interaction format](https://yandex.com/dev/direct/doc/en/concepts/format)<br>
[3] [Campaigns.add](https://yandex.com/dev/direct/doc/en/campaigns/add)<br>
[4] [AdGroups.add](https://yandex.com/dev/direct/doc/en/adgroups/add)<br>
[5] [Ads object and lifecycle](https://yandex.com/dev/direct/doc/en/objects/ad)<br>
[6] [Keywords.add](https://yandex.com/dev/direct/doc/en/keywords/add)<br>
[7] [Official campaign launch guide](https://yandex.com/dev/direct/doc/en/best-practice/launch-campaign)<br>
[8] [Campaigns.update response, budgets and limits](https://yandex.com/dev/direct/doc/en/campaigns/update)<br>
[9] [Ads.moderate](https://yandex.com/dev/direct/doc/en/ads/moderate)<br>
[10] [Ads.get](https://yandex.com/dev/direct/doc/en/ads/get)<br>
[11] [Campaign bidding strategies](https://yandex.com/dev/direct/doc/en/objects/campaign-strategies)<br>
[12] [Direct errors, including automatic-strategy bid restrictions](https://yandex.com/dev/direct/doc/en/concepts/errors-list)<br>
[13] [Campaigns.add: UnifiedCampaign strategy and budget fields](https://yandex.com/dev/direct/doc/en/campaigns/add-unified-campaign)<br>
[14] [Campaign object and supported campaign types](https://yandex.com/dev/direct/doc/en/objects/campaign)<br>
[15] [Full current Direct API index](https://yandex.com/dev/direct/doc/en/llms.txt)<br>
[16] [Changes.checkCampaigns](https://yandex.com/dev/direct/doc/en/changes/checkCampaigns)<br>
[17] [Direct API optimization/readback guidance](https://yandex.com/dev/direct/doc/en/optimize)<br>
[18] [Metrica Goals Management API](https://yandex.com/dev/metrika/en/management/openapi/goal/goals)<br>
[19] [Metrica Reports API](https://yandex.com/dev/metrika/en/stat/)<br>
[20] [Current Metrica API index](https://yandex.com/dev/metrika/en/llms.txt)<br>
[21] [Ads.add](https://yandex.com/dev/direct/doc/en/ads/add)<br>
[22] [Keywords.get](https://yandex.com/dev/direct/doc/en/keywords/get)<br>
[23] [Direct restrictions and points](https://yandex.com/dev/direct/doc/en/concepts/units)<br>
[24] [Metrica authorization/scopes](https://yandex.com/dev/metrika/en/intro/authorization)<br>
[25] [Campaigns.suspend](https://yandex.com/dev/direct/doc/en/campaigns/suspend)<br>
[26] [Campaign status and state](https://yandex.com/dev/direct/doc/en/objects/campaign#status)

## 11. Repository evidence consulted

- `README.md`
- `CONTEXT.md`
- `config/gate0-policy.json`
- `config/production-read.example.json`
- `schemas/campaign-draft-v1.schema.json`
- `schemas/goal-candidate-v1.schema.json`
- `src/mox_adv/campaign_lifecycle.py`
- `src/mox_adv/direct_management.py`
- `src/mox_adv/egress.py`
- `src/mox_adv/ui_campaign.py`
- `src/mox_adv/yandex_read.py`
- `tests/test_campaign_lifecycle.py`
- `tests/test_goal_lifecycle.py`
- `tests/test_trust_boundary.py`
- `tests/test_ui_campaign.py`
- `tests/test_ui_workflows.py`
- `tests/test_yandex_read.py`
- `docs/research/yandex-direct-metrica-capabilities.md`
- `docs/research/yandex-read-id-discovery.md`
- `requirements-v2-prototype.md`
