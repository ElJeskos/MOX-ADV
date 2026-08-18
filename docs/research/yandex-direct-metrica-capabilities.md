# Какие возможности Яндекс Директа и Метрики доступны для комплексного обслуживания?

**Репозиторий:** `ElJeskos/MOX-ADV`
**Дата проверки официальной документации:** 18.08.2026
**Режим исследования:** только чтение; учетные данные не использовались, запросы к production API не отправлялись.

## 1. Executive answer

Официальные API Яндекса позволяют построить **замкнутый цикл управления большинством обычных объектов рекламного аккаунта**:

1. прочитать кампании, группы, объявления, ключевые слова/автотаргетинг, ставки, статусы и статистику;
2. создать или изменить поддерживаемые объекты;
3. отправить объявления на модерацию;
4. приостановить/возобновить показы на уровне кампании, объявления и большинства таргетингов;
5. получить статистику Директа и связанные данные Метрики;
6. создать/изменить цели Метрики и загружать офлайн-конверсии;
7. обнаруживать последующие изменения через `Changes` и делать readback через `get`.

Это прямо соответствует назначению Direct API v5: автоматизировать добавление и изменение кампаний, объявлений и ключевых слов, управление ставками и получение статистики ([Direct API overview](https://yandex.com/dev/direct/doc/en/concepts/overview)).

Однако **полностью автономный оператор без человеческих и platform-side зависимостей невозможен**:

- автоматические стратегии оставляют оператору цели, бюджет и ограничения, но сами назначают ставки; попытка изменить ставку при автоматической стратегии отклоняется ([стратегии](https://yandex.com/dev/direct/doc/en/objects/campaign-strategies), [ошибка 9601](https://yandex.com/dev/direct/doc/en/concepts/errors-list));
- создание и управление полноценными экспериментами не представлено отдельным сервисом в актуальном полном индексе Direct API; через Метрику можно лишь читать сегментированную статистику уже созданного эксперимента ([Direct API index](https://yandex.com/dev/direct/doc/en/llms.txt), [параметризация Метрики](https://yandex.com/dev/metrika/en/stat/param));
- некоторые типы кампаний доступны через API только в статистике;
- фильтры feed-based dynamic groups и отдельные video-настройки прямо отмечены как UI-only/unsupported;
- нет транзакций, универсальной истории версий или команды rollback; откат должен быть реализован MOX-ADV как snapshot + компенсирующие операции;
- статистика изменяется задним числом и обычно стабилизируется за три дня; данные Метрики в отчетах Директа могут задерживаться на несколько часов ([актуальность статистики](https://yandex.com/dev/direct/doc/en/actual), [ограничения отчетов](https://yandex.com/dev/direct/doc/en/restrictions));
- смена дневного бюджета разрешена не более трех раз за день на кампанию ([Campaigns.update](https://yandex.com/dev/direct/doc/en/campaigns/update));
- квоты и динамическая система points требуют кэширования, batching и ограничения параллелизма.

**Практический вывод для MOX-ADV:** реалистичен автономный оператор с ограниченной областью — прежде всего `UNIFIED_CAMPAIGN` одного аккаунта — при условии:

- локального versioned snapshot перед каждой записью;
- обязательного post-write readback;
- асинхронной state machine для модерации и отчетов;
- лимитов на частоту изменения бюджетов/стратегий;
- раздельных контуров «управление» и «измерение»;
- ручного или заранее подготовленного контура экспериментов;
- возможности остановки оператором-человеком.

---

## 2. Обозначения capability matrix

- **R** — production API документирует чтение.
- **W** — production API документирует создание/изменение или управляющее действие.
- **P** — частичная поддержка либо поддержка только для отдельных подтипов.
- **U** — отдельной production API-возможности не найдено или документация прямо сообщает об отсутствии поддержки.
- **UI** — явно требуется веб-интерфейс.
- **A** — документация противоречива или недостаточно однозначна.

## 3. Матрица read/write/unsupported

| Область | Read | Write/control | Unsupported, UI-only или существенное ограничение |
|---|---:|---:|---|
| **Кампании** | **R:** `Campaigns.get`, настройки, состояние, статус модерации, бюджет, стратегия, агрегированные показы/клики | **W:** `add`, `update`, `delete`, `suspend`, `resume`, `archive`, `unarchive` | Тип кампании после создания не меняется. `MCBANNER`, `CPM_DEALS`, `CPM_FRONTPAGE`, `CPM_PRICE` — только статистика через API. Есть неоднозначность по `SMART_CAMPAIGN` и `DYNAMIC_TEXT_CAMPAIGN`, см. ниже ([Campaign object](https://yandex.com/dev/direct/doc/en/objects/campaign)). |
| **Группы** | **R:** `AdGroups.get`, параметры, `Status`, `ServingStatus` | **W:** `add`, `update`, `delete` | Отдельных `suspend/resume` для группы в актуальном сервисе нет; приостановка выполняется через кампанию, объявления или критерии. Операции невозможны в архивной кампании ([Ad group](https://yandex.com/dev/direct/doc/en/objects/adgroup), [API index](https://yandex.com/dev/direct/doc/en/llms.txt)). |
| **Объявления** | **R:** содержание, тип/подтип, `State`, `Status`, `StatusClarification`, статусы модерации расширений | **W:** `add`, `update`, `delete`, `suspend`, `resume`, `archive`, `unarchive`, `moderate` | Тип объявления после создания не меняется. Нельзя выполнять операции в архивной кампании; тип должен соответствовать группе ([Ad object](https://yandex.com/dev/direct/doc/en/objects/ad)). |
| **Изображения, видео, creatives** | **R:** `AdImages.get`, `AdVideos.get`, `Creatives.get`; creative ID и preview/readback в объявлениях | **P:** загрузка изображений/видео; `Creatives.add` строит creative для video extension из `VideoId` | `Creatives.add` — не универсальный API редактора шаблонов: документирован именно video-extension creative, до 10 за вызов. Универсальных `Creatives.update/delete` в индексе нет ([Creatives.add](https://yandex.com/dev/direct/doc/en/creatives/add), [API index](https://yandex.com/dev/direct/doc/en/llms.txt)). |
| **Ключевые слова и автотаргетинг** | **R:** ID, текст, ставки, статус/состояние, настройки категорий, статистика за последние 28 дней | **W:** `add`, `update`, `delete`, `suspend`, `resume`; настройка автотаргетинга | До 10 000 объектов в `get`; статистика по большим наборам медленная; старое поле `AutotargetingCategories` deprecated ([Keywords.get](https://yandex.com/dev/direct/doc/en/keywords/get)). |
| **Audience targets / retargeting** | **R:** targets и retargeting lists | **W:** audience target — `add/delete/suspend/resume/setBids`; retargeting list — `add/update/delete` | Допустимость зависит от типа группы; для display-группы документировано ограничение не более одного audience target ([API index](https://yandex.com/dev/direct/doc/en/llms.txt), [ошибки API](https://yandex.com/dev/direct/doc/en/concepts/errors-list)). |
| **Dynamic/smart targets** | **R** | **W:** add/delete/suspend/resume/setBids для поддерживаемых target-сервисов | Фильтры dynamic feed group необходимо управлять через веб-интерфейс; это прямой UI-only разрыв ([Ad group](https://yandex.com/dev/direct/doc/en/objects/adgroup)). |
| **Ставки** | **R:** текущие ставки, auction bids/actual CPC, network coverage; чтение возможно и при автоматической стратегии | **W:** `KeywordBids.set/setAuto`, `AudienceTargets.setBids`, target-specific `setBids` | При автоматической стратегии ручное изменение ставки запрещено; часть auction/coverage полей возвращает `null` для autotargeting, rarely served или отключенной площадки ([KeywordBids.get](https://yandex.com/dev/direct/doc/en/keywordbids/get), [ошибка 9601](https://yandex.com/dev/direct/doc/en/concepts/errors-list)). |
| **Bid modifiers** | **R** | **W:** `add`, `set`, `delete` | Совместимость зависит от типа кампании; несовместимая корректировка возвращает «Not supported» ([BidModifiers](https://yandex.com/dev/direct/doc/en/bidmodifiers/bidmodifiers), [ошибка 3500](https://yandex.com/dev/direct/doc/en/concepts/errors-list)). |
| **Бюджеты** | **R:** daily/weekly/custom-period budgets, funds/balance | **W:** через campaign/strategy update | Дневной бюджет применим к ручной стратегии; не более трех изменений в сутки на кампанию. Денежные параметры передаются в micros, то есть сумма × 1 000 000 ([Campaigns.update](https://yandex.com/dev/direct/doc/en/campaigns/update), [Campaign object](https://yandex.com/dev/direct/doc/en/objects/campaign)). |
| **Стратегии кампании** | **R:** campaign-specific `BiddingStrategy` | **W:** смена стратегии и ее CPA/CPC/CRR/goal/budget settings | Совместимость жестко зависит от типа кампании и пары Search/Network; ряд conversion-стратегий доступен только при выполнении дополнительных условий ([Display strategies](https://yandex.com/dev/direct/doc/en/objects/campaign-strategies)). |
| **Portfolio strategies** | **R:** `Strategies.get` | **W:** `add`, `update`, `archive`, `unarchive` | Нет общей команды «заморозить внутреннее обучение» или управлять его состоянием; оператор задает внешние параметры стратегии ([API index](https://yandex.com/dev/direct/doc/en/llms.txt)). |
| **Цели Метрики** | **R:** список, конкретная цель, включая удаленные через `useDeleted` | **W:** `addGoal`, `editGoal`, `deleteGoal` | API предоставляет типы action/url/step/phone/email/file/search/social и др.; отдельного restore goal в актуальном индексе нет ([Goals](https://yandex.com/dev/metrika/en/management/openapi/goal/goals), [Metrica API index](https://yandex.com/dev/metrika/en/llms.txt)). |
| **Онлайн-конверсии** | **R:** агрегированные отчеты и Logs API | **P/W:** цели и Measurement Protocol/Data Import существуют, но фактический сбор с сайта требует корректной клиентской или серверной интеграции | Без изменения landing page оператор не может сам исправить отсутствующий tag/event instrumentation; это внешний precondition, а не функция Direct API ([Metrica API index](https://yandex.com/dev/metrika/en/llms.txt)). |
| **Офлайн-конверсии** | **R:** статусы и списки загрузок; результат в отчетах | **W:** CSV upload с `ClientId`, `UserId`, `yclid` или `PurchaseId`, `Target`, `DateTime`, опционально `Price/Currency` | Нет транзакционного «отменить весь импорт» в рассмотренном интерфейсе. Необходим идентификатор для привязки; окно атрибуции — 21 день ([Offline conversions](https://yandex.com/dev/metrika/en/management/offline-conv), [conversion attribution](https://yandex.com/dev/metrika/en/management/conversion)). |
| **Выручка/заказы** | **R:** `Revenue`, `PurchaseRevenue`, `Profit`, ROI в Direct Reports; e-commerce/goal metrics в Метрике | **W:** offline `Price/Currency`, CRM customer/order imports, e-commerce/Measurement Protocol при отдельной интеграции | Выручка в Direct Reports зависит от priority goals либо данных Метрики/e-commerce; качество полностью определяется instrumentation и linking IDs ([Report fields](https://yandex.com/dev/direct/doc/en/report-format), [Metrica API index](https://yandex.com/dev/metrika/en/llms.txt)). |
| **Отчеты Директа** | **R:** account/campaign/group/ad/criteria/custom/reach/search-query; расходы, показы, клики, запросы, Metrica conversions/revenue | — | Только TSV. Search Query report — только offline mode. Отчеты не являются write-интерфейсом ([Reports](https://yandex.com/dev/direct/doc/en/reports), [report types](https://yandex.com/dev/direct/doc/en/type), [mode](https://yandex.com/dev/direct/doc/en/mode)). |
| **Отчеты Метрики** | **R:** table, drilldown, by-time, comparison; JSON/CSV; Logs API для неагрегированных hits/visits | — | Ограничения совместимости dimensions/metrics, privacy threshold для чувствительных данных; Logs API не принимает текущий день ([Reports API](https://yandex.com/dev/metrika/en/stat/), [Logs request](https://yandex.com/dev/metrika/en/logs/openapi/createLogRequest)). |
| **Эксперименты** | **P/R:** Метрика умеет сегментировать отчет по ID уже существующего эксперимента Direct/Audience | **U/A:** отдельного Direct API сервиса создания, распределения трафика, запуска или остановки эксперимента в полном production index не найдено | Следует считать experiment provisioning UI/внешним precondition, пока Яндекс не документирует официальный write endpoint ([Direct API index](https://yandex.com/dev/direct/doc/en/llms.txt), [Metrica parametrization](https://yandex.com/dev/metrika/en/stat/param)). |
| **Модерация и статусы** | **R:** DRAFT/MODERATION/PREACCEPTED/ACCEPTED/REJECTED, `State`, разъяснения и статусы расширений | **W:** `Ads.moderate`; suspend/resume после результата | Модерация асинхронна и platform-controlled. После редактирования старая версия иногда продолжает показываться, но это не гарантированный rollback ([Ad object](https://yandex.com/dev/direct/doc/en/objects/ad)). |
| **Изменения/readback** | **R:** `Changes.checkCampaigns`, `Changes.check`, `get`, `ModifiedSince` для keywords | — | `checkCampaigns` сообщает `SELF`, `CHILDREN`, `STAT`, но не возвращает старое значение; для точного diff нужен повторный `get` и локальный snapshot ([checkCampaigns](https://yandex.com/dev/direct/doc/en/changes/checkCampaigns), [optimization guidance](https://yandex.com/dev/direct/doc/en/optimize)). |
| **Rollback** | **P:** архивные и удаленные состояния некоторых объектов можно прочитать; campaign/ad имеют `archive/unarchive` | **P:** компенсирующий `update`, `resume/suspend`, иногда `unarchive` | Универсального transaction/version/rollback endpoint в полном индексе нет. Удаление и архивирование имеют state-dependent запреты; `CONVERTED` read-only и не разархивируется ([API index](https://yandex.com/dev/direct/doc/en/llms.txt), [ошибки 8300–8304](https://yandex.com/dev/direct/doc/en/concepts/errors-list)). |

---

## 4. Типы кампаний и неоднозначность production reference

### 4.1 Однозначно представленные в актуальных v5 add/get/update schemas

Текущие страницы `Campaigns.add/get/update` и индекс reference устойчиво представляют:

- `TEXT_CAMPAIGN`;
- `UNIFIED_CAMPAIGN`;
- `MOBILE_APP_CAMPAIGN`;
- `CPM_BANNER_CAMPAIGN`.

Для нового автономного контура наиболее перспективен `UNIFIED_CAMPAIGN`: его схема включает search/network placement types, CPA/CPC/CRR, pay-for-conversion, multiple goals, maximum conversions/clicks, max profit и custom-period budgets ([Unified campaign update](https://yandex.com/dev/direct/doc/en/campaigns/update-unified-campaign)).

### 4.2 Документационная неоднозначность

Страница объекта Campaign дополнительно утверждает поддержку создания/редактирования:

- `SMART_CAMPAIGN`;
- `DYNAMIC_TEXT_CAMPAIGN`.

Но актуальный индекс add/update reference и фактическая общая `Campaigns.update` schema перечисляют только Text, Unified, Mobile App и CPM Banner ([Campaign object](https://yandex.com/dev/direct/doc/en/objects/campaign), [Campaigns.update](https://yandex.com/dev/direct/doc/en/campaigns/update), [Direct API index](https://yandex.com/dev/direct/doc/en/llms.txt)).

**Консервативная трактовка для MOX-ADV:** считать standalone Smart/Dynamic campaign management **неподтвержденным для новой реализации** и не включать в production write scope до проверки changelog/sandbox. Это именно неоднозначность документации, а не доказательство отсутствия legacy-support.

### 4.3 Только статистика

Официальная объектная страница прямо указывает statistics-only через API для:

- `MCBANNER_CAMPAIGN`;
- `CPM_DEALS_CAMPAIGN`;
- `CPM_FRONTPAGE_CAMPAIGN`;
- `CPM_PRICE`.

Для них автономный lifecycle «создать → изменить → остановить → восстановить» через Direct API недоступен ([Campaign object](https://yandex.com/dev/direct/doc/en/objects/campaign)).

---

## 5. Lifecycle coverage автономного оператора

| Этап | Покрытие | Комментарий |
|---|---|---|
| Discovery аккаунта, campaign IDs, counter/goal IDs | Полное | `Campaigns.get`, counters/goals Management API. |
| Создание draft hierarchy | Высокое | Кампания → группа → критерии → объявление; типы должны строго соответствовать друг другу ([campaign launch guide](https://yandex.com/dev/direct/doc/en/best-practice/launch-campaign)). |
| Добавление ассетов | Частичное | Изображения/видео доступны, но Creative Builder покрыт не полностью. |
| Конфигурация измерения | Частичное | Цели можно создать API, но событие должно реально поступать с сайта/CRM. |
| Модерация | Частичное | Оператор отправляет `Ads.moderate`, решение принимает платформа. |
| Запуск/остановка | Высокое | Campaign/ad/criteria suspend/resume; отдельного pause группы нет. |
| Управление ставками | Высокое для manual; низкое для auto | В automatic strategy конкретные ставки контролирует Яндекс. |
| Управление бюджетом | Среднее | Strategy budget доступен, но daily budget зависит от manual strategy и имеет лимит три изменения/сутки. |
| Оптимизация по KPI | Среднее | Оператор выбирает goal/CPA/CRR/budget; обучение и auction decisions остаются у Яндекса. |
| Эксперимент | Низкое | Чтение результата возможно, API write orchestration не подтвержден. |
| Наблюдение и reconciliation | Высокое | Reports + Metrica + Changes + повторные `get`. |
| Rollback | Низкое/среднее | Только компенсирующие операции по заранее сохраненному snapshot. |

Записи Direct API выполняются над массивами объектов и возвращают `Warnings`/`Errors` для отдельных элементов; следовательно, MOX-ADV должен обрабатывать **частичный успех**, а не предполагать атомарность всего запроса ([Campaigns.update response](https://yandex.com/dev/direct/doc/en/campaigns/update)).

---

## 6. Измерение, цели, конверсии и атрибуция

### 6.1 Данные Direct Reports

Reports API поддерживает статистику на уровнях аккаунта, кампании, группы, объявления, критерия и поискового запроса. Доступны, среди прочего:

- `Impressions`, `Clicks`, `Cost`, `Ctr`, `AvgCpc`;
- `Query`, `MatchedKeyword`, placement/device/region;
- `Conversions`, `ConversionRate`, `CostPerConversion`;
- `Revenue`, `Profit`, `GoalsRoi`;
- `PurchaseRevenue`, `PurchaseProfit`, `PurchaseGoalsRoi`;
- Метрика-показатели `Sessions`, `Bounces`, `BounceRate`, `AvgPageviews` ([allowed fields](https://yandex.com/dev/direct/doc/en/fields-list), [report content](https://yandex.com/dev/direct/doc/en/report-format)).

Можно запросить до 10 конкретных goal IDs; метрики тогда возвращаются раздельно по цели и attribution model ([report specification](https://yandex.com/dev/direct/doc/en/spec)).

### 6.2 Attribution models в Direct Reports

Актуальная report schema документирует:

- `FCCD` — first click, cross-device;
- `LC` — last click;
- `LSCCD` — last non-direct click, cross-device;
- `AUTO` — automatic attribution.

Default — `LC`. Можно запросить несколько моделей одновременно. Legacy `LSC`, `FC`, `LYDC`, `LYDCCD` автоматически заменяются ближайшими поддерживаемыми моделями с предупреждением ([report specification](https://yandex.com/dev/direct/doc/en/spec)).

### 6.3 Attribution models в Метрике

Reports API и Logs API Метрики предоставляют более широкий набор:

- first;
- last;
- last significant;
- last Yandex Direct click;
- соответствующие cross-device варианты;
- automatic.

Для параметризованных отчетов default — `lastsign` ([Metrica parametrization](https://yandex.com/dev/metrika/en/stat/param)); Logs API принимает эти модели при создании log request ([Logs request](https://yandex.com/dev/metrika/en/logs/openapi/createLogRequest)).

**Следствие:** сравнение Direct Reports и самостоятельного отчета Метрики корректно только при явно согласованных модели атрибуции, goal IDs, датах и валюте.

### 6.4 Офлайн-конверсии

Для загрузки требуются:

- `Target`;
- `DateTime`;
- хотя бы один из `ClientId`, `UserId`, `yclid`, `PurchaseId`;
- опционально `Price` и `Currency`.

`yclid` связывает конверсию с конкретным рекламным кликом; `ClientId/UserId` связывают ее с предшествующей сессией; `PurchaseId` — с сессией e-commerce purchase. Окно связывания — 21 день ([offline upload](https://yandex.com/dev/metrika/en/management/offline-conv), [attribution rules](https://yandex.com/dev/metrika/en/management/conversion)).

Офлайн-конверсии появляются в отчетах Метрики **в течение трех часов после загрузки** ([offline conversions](https://yandex.com/dev/metrika/en/management/offline-conv)). Повторная передача той же строки с новой revenue заменяет прежнее значение revenue, но документация не описывает это как универсальный rollback события ([Metrica FAQ](https://yandex.com/dev/metrika/en/faq)).

---

## 7. Задержки, корректировки и лимиты

### 7.1 Direct API

- Не более **5 одновременных API-запросов на рекламодателя**.
- Используется индивидуальный лимит points, зависящий от активности, показов, кликов и расходов.
- Points начисляются скользящими часовыми порциями; списываются за вызовы, объекты и ошибки.
- Ошибочные write-операции также расходуют points ([Restrictions and points](https://yandex.com/dev/direct/doc/en/concepts/units)).
- `get` часто возвращает не более **10 000 объектов**, после чего требуется pagination через `LimitedBy` ([Keywords.get](https://yandex.com/dev/direct/doc/en/keywords/get), [KeywordBids.get](https://yandex.com/dev/direct/doc/en/keywordbids/get)).
- `Campaigns.update` — не более 10 кампаний за вызов и не более трех изменений дневного бюджета на кампанию в сутки ([Campaigns.update](https://yandex.com/dev/direct/doc/en/campaigns/update)).

### 7.2 Direct Reports

- максимум **20 запросов за 10 секунд на пользователя**;
- максимум **5 offline reports** одновременно в очереди;
- готовый offline report хранится **5 часов**;
- search-query report создается только offline;
- стандартный row limit без `Page` — 1 000 000 ([report restrictions](https://yandex.com/dev/direct/doc/en/restrictions), [report mode](https://yandex.com/dev/direct/doc/en/mode), [report specification](https://yandex.com/dev/direct/doc/en/spec)).

Статистика обычно стабилизируется в течение **трех дней**, но более старые данные также могут корректироваться, например после фильтрации недействительных кликов. Яндекс рекомендует ежедневно перечитывать последние три дня либо использовать `Changes.check`/`DateRangeType=AUTO` ([data freshness](https://yandex.com/dev/direct/doc/en/actual)).

Данные Метрики могут появляться в Direct Reports с задержкой **до нескольких часов** из-за сопоставления данных счетчика и кампаний ([report restrictions](https://yandex.com/dev/direct/doc/en/restrictions)).

### 7.3 Metrica API

Общие документированные квоты:

- 30 запросов/с с одного IP;
- 10 запросов/с к Logs API;
- 3 параллельных запроса на пользователя;
- 5 000 запросов в сутки на пользователя;
- 200 запросов к Reports API за 5 минут на пользователя.

При превышении возвращается HTTP `420 Too Many Requests` ([Metrica quotas](https://yandex.com/dev/metrika/en/intro/quotas)).

Logs API принимает конечную дату не позднее вчерашнего дня: текущий день недоступен ([Logs request](https://yandex.com/dev/metrika/en/logs/openapi/createLogRequest)).

---

## 8. Platform-side automation и границы контроля оператора

| Автоматизация Яндекса | Что контролирует MOX-ADV | Что остается у платформы |
|---|---|---|
| Automatic bidding | Goal ID, CPA/CPC/CRR, weekly/custom budget, bid ceiling где доступен, placements | Конкретные ставки и участие в аукционе |
| Maximize conversions/clicks/profit | Выбор стратегии и ограничений | Обучение, exploration и распределение расходов |
| Manual strategy with optimization | Базовые ставки, расписание, modifiers | Яндекс может автоматически повышать/понижать CPC по вероятности конверсии |
| Autotargeting | Категории и brand options | Подбор запросов и фактический matching |
| Ad-group creative rotation | Набор вариантов объявлений | Автоматическое определение более привлекательного варианта |
| Moderation | Содержимое и момент отправки | Решение, PREACCEPTED/ACCEPTED/REJECTED и сроки |
| Site monitoring | Включение настройки | Автоматический `OFF_BY_MONITORING` при недоступности сайта |
| Attribution AUTO | Выбор AUTO | Алгоритм распределения источника |
| Statistics correction | Период перечитывания и локальная reconciliation | Фильтрация кликов и ретроспективные исправления |

Ручная стратегия также не означает абсолютного контроля: документация прямо указывает, что ставка может автоматически корректироваться в зависимости от вероятности конверсии ([Display strategies](https://yandex.com/dev/direct/doc/en/objects/campaign-strategies)).

### Главный control seam

Для автоматических стратегий оператор управляет **целевой функцией и guardrails**, но не непосредственным actuator-аукционом. Поэтому цикл MOX-ADV должен быть:

> измерить → проверить зрелость данных → изменить goal/target CPA/CRR/budget/placements → дать стратегии период стабилизации → оценить,

а не:

> измерить каждый час → постоянно переписывать keyword bids.

---

## 9. Unsupported, UI-only и ambiguous области

1. **Эксперименты:** в полном актуальном индексе Direct API нет сервиса experiment lifecycle. Метрика документирует только параметр `experiment_ab` для анализа уже существующего эксперимента. Это вывод по инвентарю официального reference, а не прямое заявление Яндекса «API отсутствует» ([Direct API index](https://yandex.com/dev/direct/doc/en/llms.txt), [Metrica parametrization](https://yandex.com/dev/metrika/en/stat/param)).

2. **Dynamic feed filters:** официально должны управляться в веб-интерфейсе ([Ad group](https://yandex.com/dev/direct/doc/en/objects/adgroup)).

3. **Video completion audience setting:** `Gather audience by completion rate` прямо не поддерживается API ([Ad group](https://yandex.com/dev/direct/doc/en/objects/adgroup)).

4. **Отдельные категории модерации:** `AdCategories` нельзя назначить, изменить или удалить API; несогласие решается через поддержку ([Ad object](https://yandex.com/dev/direct/doc/en/objects/ad)).

5. **Creative Builder:** API умеет создавать ограниченный video-extension creative, но не предоставляет полный CRUD всех UI-шаблонов ([Creatives.add](https://yandex.com/dev/direct/doc/en/creatives/add)).

6. **Forecast/Wordstat в v5:** официальная best-practice страница отправляет budget forecasting и keyword selection к legacy API v4, а не к v5 ([Statistics and analysis](https://yandex.com/dev/direct/doc/en/best-practice/statistics)).

7. **Smart/Dynamic campaign CRUD:** объектная страница и актуальная method schema расходятся; использовать только после отдельной production/sandbox верификации.

8. **Rollback:** отсутствует универсальный endpoint, а удаление/архивирование ограничено состоянием объектов и наличием средств/дочерних объектов ([ошибки Direct API](https://yandex.com/dev/direct/doc/en/concepts/errors-list)).

---

## 10. Implications and constraints для MOX-ADV

### 10.1 Рекомендуемый production scope

1. Один advertiser login и один счетчик Метрики.
2. Сначала только `UNIFIED_CAMPAIGN`.
3. Объявления: text/image/responsive/product types, реально присутствующие в выбранной группе.
4. Цели и отчеты Метрики — read; goal writes и offline imports включать отдельными permissions/feature flags.
5. Experiment IDs — только как заранее созданная конфигурация.
6. Не брать в автономный write scope statistics-only campaign types и неоднозначные standalone Smart/Dynamic campaigns.

### 10.2 Обязательный безопасный write protocol

Для каждой мутации:

1. получить свежий объект через `get`;
2. проверить ожидаемые `Id`, `Type`, `State`, `Status` и текущую стратегию;
3. сохранить полный локальный before-snapshot;
4. вычислить минимальный field-level diff;
5. проверить quota/budget-change allowance;
6. отправить write;
7. разобрать per-object warnings/errors;
8. повторно прочитать объект;
9. сравнить intended state с фактическим;
10. зафиксировать after-snapshot и `RequestId`;
11. перейти в ожидание, если изменение требует модерации или обучения.

### 10.3 Rollback policy

- `suspend/resume` предпочтительнее destructive delete.
- Archive применять только после отдельной проверки ограничений.
- Для update rollback — обратный `update` из before-snapshot.
- Созданные дочерние объекты удалять в обратном порядке зависимостей.
- Не считать продолжение показов старой версии объявления во время модерации механизмом rollback.
- Любой rollback после изменения стратегии считать новой оптимизационной интервенцией: внутреннее состояние обучения платформы официальным API не восстанавливается.

### 10.4 Measurement policy

- Не принимать решения по сегодняшним неполным данным Logs API.
- Для Direct Reports ежедневно перечитывать минимум последние три дня.
- После offline upload выдерживать до трех часов до оценки результата.
- Согласовывать attribution model между Direct и Metrica.
- Хранить отдельно event time, upload time, report observation time и decision time.
- Не выполнять быстрый автоматический rollback по единичному неполному дню.

### 10.5 Human-control gates

Рекомендуется обязательное подтверждение человека для:

- первой публикации нового campaign/ad type;
- изменения стратегии;
- крупного изменения бюджета;
- удаления целей или работающих объектов;
- загрузки офлайн-конверсий значительным объемом;
- действий после массового `REJECTED`;
- подключения experiment ID;
- операций в области неоднозначной документации.

---

## 11. Claim-to-source matrix

Все URL ниже были получены и проверены как доступные в ходе текущего исследования.

| Существенное утверждение | Официальный источник |
|---|---|
| Direct API поддерживает CRUD-подобные сервисы, OAuth и POST/HTTPS | https://yandex.com/dev/direct/doc/en/concepts/overview |
| Полный актуальный перечень сервисов и методов Direct API; отсутствие experiment service | https://yandex.com/dev/direct/doc/en/llms.txt |
| Типы кампаний, statistics-only типы, статусы и micros | https://yandex.com/dev/direct/doc/en/objects/campaign |
| Типы групп, UI-only dynamic filters, unsupported video audience setting | https://yandex.com/dev/direct/doc/en/objects/adgroup |
| Типы объявлений, moderation/state, previous-version behavior, неизменяемые категории | https://yandex.com/dev/direct/doc/en/objects/ad |
| Совместимость manual/automatic strategies | https://yandex.com/dev/direct/doc/en/objects/campaign-strategies |
| Campaign update schema, daily budget и лимит три изменения/сутки | https://yandex.com/dev/direct/doc/en/campaigns/update |
| Unified campaign strategies и budgets | https://yandex.com/dev/direct/doc/en/campaigns/update-unified-campaign |
| Запрет изменения ставок при automatic strategy и state-dependent ошибки | https://yandex.com/dev/direct/doc/en/concepts/errors-list |
| Direct points и параллелизм | https://yandex.com/dev/direct/doc/en/concepts/units |
| Рекомендуемый lifecycle создания и модерации | https://yandex.com/dev/direct/doc/en/best-practice/launch-campaign |
| Изменения кампаний `SELF/CHILDREN/STAT` | https://yandex.com/dev/direct/doc/en/changes/checkCampaigns |
| Рекомендации по cache/Changes | https://yandex.com/dev/direct/doc/en/optimize |
| Keywords/autotargeting readback и статистика за 28 дней | https://yandex.com/dev/direct/doc/en/keywords/get |
| Bid/auction/coverage readback | https://yandex.com/dev/direct/doc/en/keywordbids/get |
| Ограниченный `Creatives.add` | https://yandex.com/dev/direct/doc/en/creatives/add |
| Reports API endpoint и TSV | https://yandex.com/dev/direct/doc/en/reports |
| Report types и уровни группировки | https://yandex.com/dev/direct/doc/en/type |
| Goal IDs и attribution models Direct Reports | https://yandex.com/dev/direct/doc/en/spec |
| Поля расходов, конверсий и revenue | https://yandex.com/dev/direct/doc/en/fields-list |
| Семантика report metrics | https://yandex.com/dev/direct/doc/en/report-format |
| Online/offline report state machine | https://yandex.com/dev/direct/doc/en/mode |
| Reports quotas, retention и Metrica delay | https://yandex.com/dev/direct/doc/en/restrictions |
| Стабилизация статистики в течение трех дней | https://yandex.com/dev/direct/doc/en/actual |
| Forecast/keyword selection вынесены в legacy v4 | https://yandex.com/dev/direct/doc/en/best-practice/statistics |
| Metrica OAuth scopes | https://yandex.com/dev/metrika/en/intro/authorization |
| Полный перечень Metrica Management/Data Import/Reports/Logs методов | https://yandex.com/dev/metrika/en/llms.txt |
| Goal read schema и типы целей | https://yandex.com/dev/metrika/en/management/openapi/goal/goals |
| Offline conversion upload и задержка до трех часов | https://yandex.com/dev/metrika/en/management/offline-conv |
| 21-дневное окно и linking rules | https://yandex.com/dev/metrika/en/management/conversion |
| Возможности Reports API и privacy threshold | https://yandex.com/dev/metrika/en/stat/ |
| Metrica attribution models и experiment dimension | https://yandex.com/dev/metrika/en/stat/param |
| Квоты Metrica API | https://yandex.com/dev/metrika/en/intro/quotas |
| Logs API, attribution и запрет текущего дня | https://yandex.com/dev/metrika/en/logs/openapi/createLogRequest |
| Offline upload/revenue FAQ | https://yandex.com/dev/metrika/en/faq |

---

## 12. Confidence и unresolved gaps

### Уверенность

- **Высокая:** CRUD обычных Direct-объектов, ставки, статусы, отчеты, OAuth, quotas, цели Метрики и offline conversions.
- **Высокая:** отсутствие универсального rollback/transaction в актуальном перечне сервисов.
- **Средне-высокая:** experiments являются pre-provisioned/UI-side частью цикла; вывод основан на полном индексе API и наличии только read dimension в Метрике.
- **Средняя:** фактический production lifecycle legacy `SMART_CAMPAIGN` и `DYNAMIC_TEXT_CAMPAIGN` из-за противоречия между объектной страницей и текущими общими schemas.

### Неразрешенные пробелы

1. Не установлено, являются ли ссылки на standalone Smart/Dynamic CRUD устаревшими либо поддерживаются скрытым legacy-compatible путем.
2. Официальная документация не дает единого SLA свежести обычных online-событий Метрики; подтверждены только задержки offline upload и mapping в Direct Reports.
3. Не найден официальный write API полного experiment lifecycle; не исключены отдельные интерфейсы Yandex Audience вне исследованного Direct/Metrica production reference.
4. Eligibility conversion-based strategies частично зависит от условий аккаунта и истории данных; документация отсылает к Help, поэтому статически гарантировать включение стратегии нельзя.
5. Не документирован способ восстановления внутреннего learning state автоматической стратегии после компенсирующего изменения.
6. Не проверялись account-specific restrictions, доступные только через `Clients.get`, поскольку live API calls были исключены.
