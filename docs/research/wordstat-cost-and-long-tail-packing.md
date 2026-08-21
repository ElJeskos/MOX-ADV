# Источник частотности, стоимости и правило long-tail packing

**Ticket:** [«Определить источник частотности, стоимости и правила long-tail packing»](https://github.com/ElJeskos/MOX-ADV/issues/91)  
**Репозиторий:** `ElJeskos/MOX-ADV`  
**Дата проверки официальной документации:** 21.08.2026  
**Режим:** исследование и проектное решение; production API-запросы и обращения к браузерным кабинетам не выполнялись.

## 1. Короткое решение

Для Campaign Draft нельзя показывать одно число «частотность» и одно число «цена» без области применимости. Нужны три независимых слоя evidence:

1. **Спрос:** Wordstat `/v1/topRequests` — rolling 30-day discovery; `/v1/dynamics` — broad trend/seasonality; `/v1/regions` — географическое распределение; Direct v5 `KeywordsResearch.hasSearchVolume` — только дополнительный `YES/NO`, не числовая частотность.
2. **Pre-launch стоимость:** основной кандидат для произвольных новых фраз — только документированный legacy **Live 4** forecast после account-specific capability preflight. Обычные v4 `CreateNewForecast`/`GetForecast` явно отключены; Live 4 варианты всё ещё перечислены актуальной v5 best-practice страницей и не помечены отключёнными, но их фактическая доступность для токена в этом исследовании не проверялась.
3. **Прокси стоимости:** v5 `KeywordBids.get` даёт актуальные auction `Price` только для уже существующих keyword IDs/autotargetings; Direct Reports дают фактический исторический CPC собственного аккаунта. Ни один из этих источников не является универсальной ценой новой фразы.

Цена хранится диапазоном сценариев или эмпирическим диапазоном вместе с источником, датой, валютой, VAT, scope и sample size. Если сопоставимого источника нет, карточка говорит **«сопоставимой оценки цены нет»**, а не подставляет ноль, среднее по рынку или LLM-оценку.

Long-tail проходит двухуровневую обработку:

- **Demand Cluster** объединяет запросы одного продукта/потребности/намерения;
- несколько кластеров упаковываются в один Campaign Draft, пока совпадает `delivery_key = цель × экономика × география × посадочная × сообщение × управление`.

Запрос и даже keyword cluster сами по себе не создают кампанию. Split разрешён только при материальном различии `delivery_key` **и** доказанной достаточности агрегированного спроса для выделенного месячного бюджета. Совместимый слабый long-tail не скрывается — он пакуется в родительский Draft. Скрывается только кластер без уникального eligible demand либо несовместимый кластер, который нельзя упаковать и для которого standalone sufficiency не доказана. Причина и evidence остаются в audit trail.

---

## 2. Что именно подтверждают официальные API

### 2.1. Wordstat `/v1`

Официальный Wordstat API содержит четыре метода: `/v1/getRegionsTree`, `/v1/topRequests`, `/v1/dynamics`, `/v1/regions`. Запросы выполняются через HTTPS `POST` с JSON; доступ требует OAuth token, регистрации `ClientId` и одобрения доступа поддержкой Яндекс Директа. [W1][W2]

| Метод | Подтверждённая семантика | Ограничение для MOX-ADV |
|---|---|---|
| `/v1/getRegionsTree` | Возвращает поддерживаемые Wordstat region IDs | Не расходует дневную квоту. Это дерево Wordstat; связь с Direct `Dictionaries.get` должна быть явной, а не угаданной. |
| `/v1/topRequests` | Популярные запросы, содержащие заданную фразу, и похожие запросы; данные за последние 30 дней; строки `phrase + count` | Ответ не содержит отдельного cluster total и точной даты окончания rolling window. Нельзя выдавать сумму пересекающихся seed counts за уникальный спрос. |
| `/v1/dynamics` | `count` и `share` по дням/неделям/месяцам; daily — последние 60 дней, weekly/monthly — с 01.01.2018 | Dynamics поддерживает только оператор `+`; trend broad-фразы нельзя смешивать с operator-bounded 30-day count. |
| `/v1/regions` | Последние 30 дней: `count`, `share`, `affinityIndex` по городам/регионам | Запрос глобальный и расходует две единицы дневной квоты; это контекст географии, а не замена `topRequests` с точным region scope Draft. |

`topRequests` и `dynamics` расходуют по одной единице дневной квоты, `regions` — две, `getRegionsTree` — ноль. Числовые personal limits в публичной странице не указаны. Документированы общий service quota и personal quota на RPS/день; превышение personal quota возвращает `429` с `Time to refill`, общего — `503`. [W1][W2]

### 2.2. Операторы и сопоставимость

Wordstat поддерживает `!`, `+`, кавычки, `[]`, `()` и `|`. Критическая семантика: [W3]

- `!` фиксирует форму слова;
- `+` фиксирует stop word;
- кавычки фиксируют **число слов**, но не их порядок и не словоформу;
- `[]` фиксирует порядок слов;
- `()` и `|` группируют альтернативы;
- все операторы работают в Top queries и Regions;
- Dynamics поддерживает только `+`.

Следовательно, слово `exact` нельзя использовать для частотности без расшифровки. Канонические operator profiles:

| Profile | Что хранить | Что означает |
|---|---|---|
| `BROAD_CONTAINING` | исходная фраза, только обязательные `+` | Запросы, содержащие broad seed; discovery, не точный коммерческий спрос. |
| `FIXED_WORD_COUNT` | фактическая строка с кавычками | Та же длина фразы без дополнительных слов; порядок и словоформы могут отличаться. |
| `FIXED_ORDER_FORM` | фактическая комбинация `[]`, `!`, `+` | Строго зафиксированные свойства, указанные операторами; не универсальное «exact match». |
| `DYNAMICS_BROAD` | broad phrase, допускается только `+` | Сезонный trend; численно не складывается с operator-bounded profile. |

Два значения frequency сопоставимы только при совпадении endpoint, operator profile, region IDs, device, rolling/explicit window и batch snapshot. Counts — запросы/поисковые обращения, не уникальные пользователи, не гарантированные показы и не клики. [W1][W4]

### 2.3. Device, region и seasonality

`topRequests` и `dynamics` принимают `devices = all | desktop | phone | tablet` и список region IDs; значение по умолчанию — `all` и все регионы. `regions` принимает device, но не фильтр списка регионов. [W1]

Правила:

1. `all` хранится как самостоятельный total; его нельзя складывать с desktop/phone/tablet.
2. Каждый Draft получает frequency для своей бизнес-географии и выбранного device scope; значение «все регионы» недопустимо, если Draft таргетируется только на один регион.
3. Wordstat region IDs берутся из `getRegionsTree`. Direct publish `RegionIds` проверяются отдельно через Direct dictionary; одинаковые числа не считаются доказанной меж-API связью без validated mapping.
4. Seasonality считается только из `dynamics` и показывается как отдельный broad trend. Рекомендуемая нормализация — `share`, поскольку API уже даёт долю соответствующих запросов среди всех запросов Яндекса.
5. Для monthly trend используются только полные месяцы. Карточка хранит текущий полный период, median `share` для того же календарного месяца прошлых лет и отношение `current_share / historical_same_month_median`. Если истории недостаточно, показывается ряд без seasonality ratio.
6. Seasonality никогда не превращает broad count в «точную» частотность коммерческой фразы и не является гарантией будущего спроса.

### 2.4. Snapshot date

У `topRequests` и `regions` ответ не содержит `as_of`/`window_end`: документация говорит только «последние 30 дней». Поэтому MOX-ADV обязан хранить:

- `batch_started_at` и `batch_finished_at` в UTC;
- `requested_at` каждого вызова;
- `declared_window = rolling_last_30_days`;
- `source_window_end = undisclosed_by_api`.

Нельзя синтетически записывать точную дату среза как `requested_at - 1 day`. Для `dynamics` сохраняются фактические `fromDate`, `toDate`, period и даты точек. Карточка показывает дату сбора, а не вымышленную «дату данных».

---

## 3. Как получать честную cluster frequency

### 3.1. Нельзя суммировать seed frequency

Broad parent и его long-tail children пересекаются. Live 4 forecast прямо предупреждает: если keywords перекрываются и соответствуют одному search query, показы и клики могут быть случайно приписаны любой из них, поэтому совместный forecast отличается от отдельных calls. [F2]

Для Wordstat применяется такой детерминированный контракт:

1. Для каждого seed вызывается `topRequests` в одном operator/geo/device profile.
2. Каждая возвращённая строка получает normalized key: Unicode NFKC, lower case, единичные пробелы; исходная строка сохраняется.
3. Нерелевантные строки исключаются версионированным классификатором `product/service × audience need × intent × offer`; версия модели/правил и причины исключения сохраняются.
4. Одинаковая normalized row, найденная несколькими seeds, учитывается один раз.
5. Если строка подходит нескольким Demand Clusters, она назначается один раз: exact canonical seed match → большее число обязательных tokens → стабильный `cluster_id` как tie-breaker.
6. `cluster_observed_30d_count = sum(count)` только по уникальным назначенным строкам.
7. Поле маркируется `LOWER_BOUND_OBSERVED_TOP_ROWS`: документация не обещает, что `topRequests` возвращает исчерпывающий universe запросов.
8. Отдельно хранится `seed_matched_row_count`, только если в response присутствует строка, нормализованно совпадающая с canonical seed. Отсутствие строки означает `null`, не ноль.

Перед отправкой keywords в Direct или Live 4 pack прогоняется через v5 `KeywordsResearch.deduplicate`: официальный метод умеет объединять дубликаты и устранять пересечения добавлением negative keywords. [D1]

### 3.2. Дополнительный boolean signal

`KeywordsResearch.hasSearchVolume` в Direct v5 принимает до 10 000 keywords и region IDs и возвращает только `YES/NO` по all/mobile/tablet/desktop. Он назван approximate forecast of impressions, но числового объёма не даёт. Лимит — 20 requests за 60 секунд на advertiser. [D2]

Использование:

- `YES` подтверждает наличие некоторого прогнозируемого объёма, но не достаточность для отдельной кампании;
- `NO` усиливает отсутствие current demand;
- `NO` не заменяет seasonal check;
- timeout/quota/API denial даёт `UNKNOWN`, не `NO`.

---

## 4. Источники стоимости и их границы

### 4.1. Legacy Live 4 forecast: optional primary pre-launch source

Актуальная v5 best-practice страница по-прежнему отправляет budget forecast к API v4/Live 4. Обычные v4 `CreateNewForecast` и `GetForecast` на собственных страницах помечены **Disabled method**; official 2018 notice также говорит об их полном отключении. Но Live 4 `CreateNewForecast (Live)` и `GetForecast (Live)` не имеют такого предупреждения, а notice оставляет `CreateNewForecast (Live)` работающим в actual currency. [F1][F2][F3][F4][F5]

Это позволяет считать Live 4 **документированным optional capability**, но не гарантированной baseline-функцией. До использования нужен read-only capability preflight конкретного token/account. Browser budget forecast не является fallback: кабинеты вне scope.

Подтверждённые ограничения Live 4:

- `Currency` обязателен;
- не более 100 phrases на forecast;
- до пяти reports на user, хранение пять часов;
- асинхронная генерация, документация указывает среднее время до минуты; lifecycle имеет состояния `Done`, `Pending`, `Failed`;
- overlapping phrases могут получать случайное распределение показов/кликов;
- `GetForecast (Live)` возвращает monthly `Shows`, `Clicks`, CTR, CPC/cost и optional `AuctionBids` со старыми placement positions;
- input schema не содержит выбранного forecast period или device filter;
- старые placement positions нельзя молча приравнять современному traffic volume;
- actual expenses могут отличаться из-за изменения конкурентов, ставок, quality coefficients и CPA. [F2][F4][F6][F7]

Правило: Live 4 используется только после `capability_status=AVAILABLE`; response хранится как `LEGACY_LIVE4_SCENARIO`, а не как обещание цены или результата. Failure `UNAVAILABLE/UNAUTHORIZED` переводит cost в следующий источник без попытки browser cabinet.

### 4.2. `KeywordBids.get`: current auction proxy только для существующего keyword

Direct v5 `KeywordBids.get` принимает campaign/ad group/keyword IDs и возвращает `AuctionBids` с `TrafficVolume`, `Bid` и `Price` — platform-defined actual CPC для данного traffic volume. Читать можно и при manual, и при automatic strategy. Все суммы — currency × 1 000 000. [B1]

Он **не принимает новую phrase**. Поэтому его нельзя использовать как price lookup произвольного Draft. Допустимый случай:

- в allowlisted собственном аккаунте уже существует normalized-equivalent keyword;
- совпадают или явно сопоставлены campaign placement, geography, strategy state и другие delivery conditions;
- карточка хранит source `CampaignId/AdGroupId/KeywordId`, observation time и comparability vector.

Ограничения:

- `AuctionBids=null` для autotargeting, image-only group и `RARELY_SERVED`;
- нельзя запрашивать AuctionBids при Search `SERVING_OFF`;
- endpoint не принимает region/device — scope наследуется от существующих объектов;
- `Price` — текущий auction proxy, не фактический CPC будущей кампании;
- максимум 10 000 объектов с pagination.

### 4.3. Собственный исторический CPC: empirical prior

Direct Reports — единственный из рассматриваемых источников, который показывает реально понесённые расходы собственного аккаунта. `SEARCH_QUERY_PERFORMANCE_REPORT` группируется по `AdGroupId + Query`, поддерживает `MatchedKeyword`, `Clicks`, `Cost`, `AvgCpc`, `Date` и campaign/ad-group attributes; он создаётся только offline. [R1][R2][R3][R5]

Правила расчёта:

1. Фильтровать account, search placement, явный период и максимально сопоставимые product/intent/campaign/ad-group settings.
2. Привязать geography/strategy через readback campaign/group configuration, если report type не даёт нужный segment.
3. Считать aggregate CPC как `sum(Cost) / sum(Clicks)`, а не среднее от строк `AvgCpc`.
4. Хранить clicks, cost, active days, date range, attribution/report scope, currency, `IncludeVAT` и units.
5. Для day-level rows показывать empirical quantiles отдельно от weighted mean. Это описательная вариативность, не confidence interval и не прогноз.
6. Нулевые clicks не создают CPC=0; это `CPC_UNDEFINED_NO_CLICKS`.
7. Старые или scope-mismatched данные остаются видимым weak prior, но не получают искусственную поправку от LLM.

Monetary fields Reports возвращаются в валюте при `returnMoneyInMicros:false`, иначе в micros; VAT управляется `IncludeVAT`. [R4]

### 4.4. Детерминированный cost envelope

Источники не усредняются между собой. На карточке сохраняются все наблюдения, а compact range выбирается по приоритету:

1. успешный exact-scope `LEGACY_LIVE4_SCENARIO`;
2. exact normalized existing keyword через `KEYWORDBIDS_V5_CURRENT_PROXY`;
3. `DIRECT_HISTORY_OWN_EMPIRICAL`;
4. `UNAVAILABLE`.

Для Live 4/KeywordBids range — min/max `Price` только среди явно выбранных и экономически допустимых placement/traffic scenarios. Для history — empirical `P25–P75` day-level CPC плюс weighted mean и sample size. Это **scenario/empirical range**, не statistical confidence interval. Если несколько сильных источников конфликтуют, карточка получает `CONFLICTING_COST_EVIDENCE` и показывает их раздельно; усреднение запрещено.

---

## 5. Обязательные поля evidence в каждой Campaign Draft card

```yaml
market_evidence:
  contract_version: "demand-cost-v1"
  batch_started_at: "UTC timestamp"
  batch_finished_at: "UTC timestamp"

  frequency:
    status: AVAILABLE | PARTIAL | UNAVAILABLE | CONFLICTING
    source: YANDEX_WORDSTAT_V1
    method: /v1/topRequests
    request_fingerprint: "sha256(canonical request)"
    operator_profile: BROAD_CONTAINING | FIXED_WORD_COUNT | FIXED_ORDER_FORM
    canonical_phrases: []
    region_ids: []
    region_names: []
    devices: [all | desktop | phone | tablet]
    declared_window: rolling_last_30_days
    source_window_end: undisclosed_by_api
    collected_at: "UTC timestamp"
    observed_unique_count:
      value: 0
      semantics: LOWER_BOUND_OBSERVED_TOP_ROWS
    seed_matched_row_counts: []
    coverage:
      returned_rows: 0
      eligible_unique_rows: 0
      excluded_rows: 0
      exclusion_reason_counts: {}
    has_search_volume:
      source: DIRECT_V5_KEYWORDS_RESEARCH
      all_devices: YES | NO | UNKNOWN
      mobile_phones: YES | NO | UNKNOWN
      tablets: YES | NO | UNKNOWN
      desktops: YES | NO | UNKNOWN
    seasonality:
      source: /v1/dynamics
      operator_profile: DYNAMICS_BROAD
      period: monthly | weekly | daily
      from_date: YYYY-MM-DD
      to_date: YYYY-MM-DD
      latest_complete_share: null
      historical_same_period_median_share: null
      ratio: null
      status: AVAILABLE | INSUFFICIENT_HISTORY | UNAVAILABLE
    geo_evidence:
      source: /v1/regions
      rows: []

  cost:
    status: AVAILABLE | UNAVAILABLE | CONFLICTING
    compact_source: LEGACY_LIVE4_SCENARIO | KEYWORDBIDS_V5_CURRENT_PROXY | DIRECT_HISTORY_OWN_EMPIRICAL | null
    currency: RUB
    vat_mode: INCLUDED | EXCLUDED | NOT_APPLICABLE | UNKNOWN
    units: CURRENCY | MICROS
    observed_at: "UTC timestamp"
    period_from: null
    period_to: null
    range:
      low: null
      high: null
      kind: SCENARIO | EMPIRICAL_IQR | null
    weighted_historical_mean: null
    clicks_sample: null
    active_days_sample: null
    comparability:
      phrase: EXACT | CLUSTER | DIFFERENT | UNKNOWN
      geography: SAME | MAPPED | DIFFERENT | UNKNOWN
      placement: SAME | DIFFERENT | UNKNOWN
      strategy: SAME | DIFFERENT | UNKNOWN
      season: SAME | DIFFERENT | UNKNOWN
    observations: []
    missing_or_conflict_reasons: []

  packing:
    demand_cluster_ids: []
    delivery_key_fingerprint: "sha256(...)"
    disposition: PACKED | STANDALONE | HIDDEN | EVIDENCE_GAP
    reason_codes: []
```

Compact card обязательно показывает:

- `N+ запросов / последние 30 дней`, где `+` раскрывает lower-bound semantics;
- geography, device и operator profile;
- дата сбора и предупреждение, что Wordstat не сообщает точный end rolling window;
- CPC range с source badge (`Live 4 scenario`, `current existing keyword`, `own history`) либо «сопоставимой оценки нет»;
- currency/VAT, scope и sample size;
- evidence state и раскрываемые reasons.

Отсутствующая стоимость не равна нулю и сама по себе не делает спрос слабым. Как missing evidence влияет на viability score, решает отдельный ticket [«Спроектировать объяснимый viability score до запуска»](https://github.com/ElJeskos/MOX-ADV/issues/93).

---

## 6. Детерминированное clustering и packing

### 6.1. Два разных ключа

Каждый eligible query получает два versioned categorical keys:

```text
semantic_key = product_or_service × audience_need × intent × offer

delivery_key = primary_goal
             × economics_profile
             × geography
             × landing_page
             × core_message
             × management_profile
```

`management_profile` включает только materially different controls: campaign capability/type, placement regime, primary measurement goal, bidding/budget regime, schedule/legal restrictions. Keyword wording в него не входит.

- Одинаковый `semantic_key` → один Demand Cluster.
- Одинаковый `delivery_key` → кластеры обязаны паковаться в один Campaign Draft.
- Разный keyword cluster при одинаковом `delivery_key` не создаёт новую кампанию.
- Product/audience/offer различие создаёт split только если оно реально меняет один из delivery dimensions.

### 6.2. Pipeline

1. **Collect:** получить top rows для versioned seeds в одном scope.
2. **Classify:** назначить `semantic_key`, relevance и exclusions; сохранить model/rule version и explanation.
3. **Unique assignment:** учесть каждую normalized top row ровно в одном cluster.
4. **Direct deduplication:** применить `KeywordsResearch.deduplicate` к publish phrases, чтобы merge duplicates/eliminate overlaps происходили до forecast и Draft.
5. **Form delivery buckets:** сгруппировать Demand Clusters по exact `delivery_key`.
6. **Pack:** каждый bucket становится максимум одним Campaign Draft; long-tail живёт в groups/keyword set внутри него.
7. **Consider split:** split bucket запрещён. Новый Draft возможен только для другого `delivery_key` и только при `standalone_demand_sufficient=true`.
8. **Record disposition:** `PACKED`, `STANDALONE`, `HIDDEN` или `EVIDENCE_GAP` с reason codes.

### 6.3. Standalone demand sufficiency без произвольного frequency cutoff

Raw Wordstat count не переводится напрямую в clicks/spend: API не даёт CTR или auction participation для новой кампании. Поэтому универсальный порог вроде «100 запросов = отдельная кампания» запрещён.

Для candidate Draft должны быть заданы `provisional_monthly_budget` и один экономически допустимый planning scenario. Тогда:

```text
campaign_window_demand_positive :=
  observed_unique_30d_count > 0
  OR hasSearchVolume(allDevices) == YES
  OR (
    campaign window overlaps a historically positive seasonal period
    AND dynamics evidence is available
  )

spend_capacity_supported :=
  comparable forecast supplies clicks, CPC and total spend

standalone_demand_sufficient :=
  campaign_window_demand_positive
  AND spend_capacity_supported
  AND scenario_forecast_clicks > 0
  AND scenario_forecast_total_spend >= provisional_monthly_budget
```

Подходящий `spend_capacity_supported` сейчас может дать:

1. successful Live 4 report для deduplicated non-overlapping pack и exact geography/currency; либо
2. будущая versioned/calibrated own-account модель `Wordstat → delivered clicks/spend`, прошедшая отдельный backtest.

`KeywordBids.get` даёт CPC, но не volume/click forecast; historical CPC без сопоставимого volume также не доказывает capacity. Если capacity source отсутствует:

- cluster с тем же `delivery_key` **пакуется**, даже если он низкочастотный;
- materially different cluster получает `EVIDENCE_GAP`, а не выдуманный standalone Draft;
- отсутствие Live 4 не компенсируется browser cabinet или LLM price estimate.

### 6.4. Критерий скрытия слабого кластера

Cluster не удаляется; он скрывается из default canvas, оставаясь в evidence/audit report.

| Disposition | Детерминированное условие |
|---|---|
| `PACKED` | Есть eligible unique phrase/current-or-seasonal demand, `delivery_key` совместим с существующим Draft; standalone sufficiency не требуется. |
| `STANDALONE` | `delivery_key` materially differs **и** `standalone_demand_sufficient=true`. |
| `HIDDEN:DUPLICATE_OR_OVERLAP` | После normalized assignment и Direct deduplication не осталось уникальной publish phrase. |
| `HIDDEN:NO_DEMAND` | Wordstat не дал positive current rows, `hasSearchVolume=NO`, и dynamics не показывает релевантный сезонный спрос в campaign window. |
| `HIDDEN:INSUFFICIENT_STANDALONE_CAPACITY` | `delivery_key` несовместим с другими Drafts, capacity evidence доступно, но scenario spend/clicks не покрывают provisional budget. |
| `EVIDENCE_GAP:UNAVAILABLE` | Wordstat/forecast/quota/access unavailable или scopes несопоставимы. Это не «слабый» cluster и не получает нулевые frequency/cost; он не попадает в default shortlist до обновления evidence. |
| `DEFERRED_SEASONAL` | Current demand отсутствует, но dynamics подтверждает спрос в будущем периоде, который не совпадает с campaign window. Не смешивать с `NO_DEMAND`. |

Таким образом, десять совместимых low-frequency queries сохраняются в одном pack и могут дать более сильный aggregate lower bound, чем один broad high-frequency seed. Одновременно они не создают десять бюджетов и десять кампаний.

---

## 7. Quota, cache и failure policy

1. Cache key: endpoint + canonical JSON params + operator profile + region tree version. Rolling 30-day values имеют bounded TTL и общий batch timestamp.
2. `regions` вызывается после первичного relevance/demand pass, поскольку стоит две quota units.
3. Calls не запускаются безгранично параллельно: numeric quota не зашивается из догадки, а берётся из approved runtime config/observed responses.
4. `429` ставит job на паузу минимум на `Time to refill`; `503` означает service-wide retry with bounded backoff.
5. Quota/access failure даёт `UNAVAILABLE`, не count `0`.
6. Partial batch не смешивается с предыдущим snapshot без явного `PARTIAL` и per-call timestamps.
7. Live 4 reports удаляются после чтения либо естественно истекают; limit five reports учитывается в scheduler.
8. Ни один retry не создаёт browser-cabinet fallback.

---

## 8. Проверочные сценарии

| Сценарий | Ожидаемый результат |
|---|---|
| Десять low-frequency phrases одного продукта, offer, geo, landing и goal | Один Draft, десять phrases/groups после deduplication; frequency — сумма уникально назначенных top rows как lower bound. |
| Broad seed и дочерняя phrase встретились в двух responses | Строка учитывается один раз по deterministic assignment; broad + child seed counts не суммируются. |
| Два продукта имеют разные landing/economics, но второй не покрывает budget по Live 4 scenario | Первый Draft видим; второй `HIDDEN:INSUFFICIENT_STANDALONE_CAPACITY`, не смешивается с несовместимым Draft. |
| `KeywordBids.get` найден для existing exact keyword | Показывается current auction proxy с IDs/scope; он не объявляется ценой новой campaign. |
| `KeywordBids.AuctionBids=null` из-за `RARELY_SERVED` | Cost переходит к history/Live 4 или `UNAVAILABLE`; null не становится CPC=0. |
| Есть 90 days own history, но другая география | History сохраняется с `geography=DIFFERENT`; compact source может перейти к более слабому состоянию, без silent adjustment. |
| Wordstat current = no rows, hasSearchVolume=NO, но тот же месяц прошлых лет имеет demand и campaign запланирована на сезон | `DEFERRED_SEASONAL` или seasonal candidate, не `NO_DEMAND`. |
| Wordstat quota вернул 429 | `EVIDENCE_GAP:UNAVAILABLE` с retry time; Draft не получает нулевую frequency. |
| Live 4 token не поддерживается | Capability `UNAVAILABLE`; cost fallback к exact existing KeywordBids/history; browser cabinet не открывается. |
| Cost sources конфликтуют | `CONFLICTING_COST_EVIDENCE`, оба диапазона раскрываются; среднее не считается. |

---

## 9. Что передаётся следующим tickets

### В [«Спроектировать объяснимый viability score до запуска»](https://github.com/ElJeskos/MOX-ADV/issues/93)

- использовать `observed_unique_count` как lower bound, а не точную market size;
- учитывать `frequency.status`, cost comparability и conflict/missing states отдельно от numeric score;
- не превращать `UNAVAILABLE` в ноль;
- Draft hidden-threshold по score не должен переопределять cluster dispositions этого документа;
- price range — scenario/empirical uncertainty, не гарантия CPC/CPA.

### В [«Определить fan-out Strategy → Campaign Drafts и MVP-набор возможностей Директа»](https://github.com/ElJeskos/MOX-ADV/issues/94)

- fan-out получает готовые Demand Clusters и exact `delivery_key`;
- одинаковый `delivery_key` пакуется в один Draft;
- нужно назначить `provisional_monthly_budget` и planning scenario до проверки standalone capacity;
- один Draft остаётся одной publishable campaign; long-tail phrases являются children, а не отдельными campaigns;
- Direct API eligibility/capability различия входят в `management_profile` только если они меняют реальное управление/publish projection.

---

## 10. Primary sources

### Wordstat

- **[W1]** Wordstat API structure: methods, parameters, windows, devices, regions, method quota units — https://yandex.com/support2/wordstat/en/content/api-structure
- **[W2]** Wordstat API access and quota behavior — https://yandex.com/support2/wordstat/en/content/api-wordstat
- **[W3]** Wordstat operators and per-tab support — https://yandex.com/support2/wordstat/en/content/operators
- **[W4]** Yandex Direct Help: Wordstat use and monthly-impression interpretation — https://yandex.com/support/direct/en/keywords/wordstat

### Direct keyword preprocessing and volume

- **[D1]** `KeywordsResearch.deduplicate` — https://yandex.com/dev/direct/doc/en/keywordsresearch/deduplicate
- **[D2]** `KeywordsResearch.hasSearchVolume` — https://yandex.com/dev/direct/doc/en/keywordsresearch/hasSearchVolume

### Forecast and cost

- **[F1]** Current v5 best practice: forecast/keyword selection routed to v4/Live 4 — https://yandex.com/dev/direct/doc/en/best-practice/statistics
- **[F2]** `CreateNewForecast (Live)` — https://yandex.com/dev/direct/doc/dg-v4/live/CreateNewForecast.html
- **[F3]** Disabled non-Live `CreateNewForecast` — https://yandex.com/dev/direct/doc/dg-v4/reference/CreateNewForecast.html
- **[F4]** `GetForecast (Live)` — https://yandex.com/dev/direct/doc/dg-v4/live/GetForecast.html
- **[F5]** Official notice on disabled v4 forecast methods and retained currency-based Live method — https://yandex.com/blog/ya-direct-api/api-version-4-and-live-4-support-for-units-will-be-disabled
- **[F6]** Budget Forecast methodology and limitations — https://yandex.com/support/direct/en/impressions/budget-estimation
- **[F7]** Forecast report lifecycle/status — https://yandex.com/dev/direct/doc/dg-v4/reference/GetForecastList.html

### Bids and account history

- **[B1]** `KeywordBids.get` — https://yandex.com/dev/direct/doc/en/keywordbids/get
- **[R1]** Direct Reports service — https://yandex.com/dev/direct/doc/en/reports
- **[R2]** Report types and Search Query grouping — https://yandex.com/dev/direct/doc/en/type
- **[R3]** Allowed report fields — https://yandex.com/dev/direct/doc/en/fields-list
- **[R4]** Currency, micros and VAT in Reports — https://yandex.com/dev/direct/doc/en/money
- **[R5]** Search Query report is offline-only — https://yandex.com/dev/direct/doc/en/mode

## 11. Confidence и нерешённая operational проверка

- **Высокая уверенность:** Wordstat endpoint/operator semantics; rolling/explicit windows; device/region fields; method quota cost; absence of exact `as_of`; v5 `hasSearchVolume`; `KeywordBids.get` input/output/null constraints; Direct report fields and money semantics.
- **Высокая уверенность:** обычные v4 forecast methods disabled; Live 4 docs remain current-linked and unmarked as disabled.
- **Средняя уверенность:** фактическая Live 4 availability для конкретного production token/account. Она требует API-only capability preflight перед implementation handoff; до него feature optional и fail-closed.
- **Проектный вывод:** lower-bound unique-row frequency, source-separated cost envelope и delivery-key packing являются MOX-ADV contract, а не заявлениями Яндекса.
