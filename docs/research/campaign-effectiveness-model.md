# Какая модель эффективности должна управлять рекламными кампаниями?

**Исследовательский бриф для MOX-ADV**
**Дата доступа ко всем источникам:** 18.08.2026
**Статус:** исследование для последующего продуктового решения; без реализации

## 1. Краткий ответ

Кампанией должна управлять не плоская таблица KPI и не автоматически выбранная «лучшая метрика», а утверждённая оператором иерархия:

1. **Бизнес-результат:** инкрементальная прибыль или маржинальная ценность, которую реклама создаёт сверх сценария без рекламы.
2. **Жёсткие ограничения:** бюджет, допустимые CPA/CAC или минимальный ROAS, темп расхода, операционная ёмкость, юридические и брендовые ограничения.
3. **Одна основная цель оптимизации:** максимизация ценности конверсий, числа однородных конечных конверсий либо — только для действительно охватных/трафиковых кампаний — охвата, показов или визитов.
4. **Опережающие и диагностические показатели:** показы, клики, CTR, CPC, визиты, engagement rate, отказы, глубина, скорость страницы, промежуточные события.
5. **Качество измерения:** полнота тегирования и CRM-импорта, задержка конверсий, окна и модель атрибуции, дедупликация, invalid traffic, сопоставимость данных.
6. **Причинная проверка:** incrementality/lift-эксперименты для крупных решений о бюджете и реальной отдаче.

Google, Meta, Yandex и Microsoft прямо связывают выбранную оптимизационную цель с тем, за какое действие система будет назначать ставки и искать аудиторию; следовательно, подмена покупки кликом, визитом или поверхностным engagement меняет не только отчёт, но и поведение доставки рекламы ([G1](https://support.google.com/google-ads/answer/2472725), [M1](https://www.facebook.com/business/help/355670007911605), [Y1](https://yandex.com/support/direct/en/strategies/priority-goals), [MS1](https://learn.microsoft.com/es-es/advertising/campaign-management-service/conversiongoal?view=bingads-13)).

**Рекомендация для MOX-ADV — явный вывод (inference):** канонический **Campaign Effectiveness Profile** должен хранить эту иерархию для одной кампании. Он может быть первоначально заполнен account-level default, но должен стать самостоятельной, версионируемой и утверждённой оператором конфигурацией кампании. Значения по умолчанию не должны незаметно менять действующую кампанию.

---

## 2. Предлагаемая иерархия метрик

### Уровень A. Бизнес-результат — «зачем существует кампания»

Предпочтительный порядок:

1. **Инкрементальная прибыль / contribution margin;**
2. **инкрементальная ценность или выручка** с поправкой на маржу, возвраты и качество клиента;
3. **LTV или ожидаемая прибыль клиента**, если оценка подтверждена последующими данными;
4. **квалифицированная продажа, лид или иное конечное действие**, если финансовая ценность пока недоступна;
5. для не-performance кампаний — доказанный brand/search/conversion lift.

MRC классифицирует traffic/visitation как показатель, не являющийся прямой мерой продаж, а ROI/ROAS связывает с бизнес-результатом. При этом обычный математический ROAS необходимо отличать от причинно установленной отдачи: атрибуция показывает, чему засчитали результат, тогда как incrementality оценивает отличие от контрфактического сценария ([S1, разделы 2.1.6–2.1.9](https://mediaratingcouncil.org/sites/default/files/Standards/MRC%20Outcomes%20and%20Data%20Quality%20Standards%20%28Final%29.pdf)). Google Conversion Lift аналогично различает attributed conversions и дополнительные конверсии treatment против control, а также обычный ROAS и incremental ROAS ([G4](https://support.google.com/google-ads/answer/14102450?hl=en)).

**Вывод (inference):** атрибутированная выручка и platform ROAS пригодны для ежедневного управления, но не должны называться доказанной дополнительной прибылью без эксперимента или другой обоснованной причинной модели.

### Уровень B. Жёсткие ограничения — «что нельзя нарушить»

Профиль должен поддерживать независимо:

- общий и периодический бюджет;
- допустимый темп расхода и срок кампании;
- максимальный CPA/CAC либо минимальный ROAS;
- минимальную маржу или ограничение на субсидирование продаж;
- объём, который бизнес способен обработать;
- географию, расписание, инвентарь, brand safety, legal/privacy;
- при необходимости — максимальный CPC/ставку как технический guardrail.

Автостратегии фактически решают задачу «максимизировать результат в бюджете», дополняемую целевым CPA или ROAS. Google отдельно различает максимизацию конверсий/ценности без target и с target CPA/ROAS; Microsoft описывает Maximize Conversion Value как максимизацию совокупной ценности в бюджете с опциональным Target ROAS ([G1](https://support.google.com/google-ads/answer/2472725), [MS2](https://learn.microsoft.com/ru-ru/advertising/campaign-management-service/maxconversionvaluebiddingscheme?view=bingads-13)).

**Вывод (inference):** бюджет, CPA и ROAS нельзя одновременно трактовать как три равноправных цели. Бюджет и один экономический порог должны быть ограничениями, а максимизируемая величина — целью.

### Уровень C. Основная оптимизационная цель — «какой сигнал получает алгоритм»

Для одной кампании должен быть выбран **один основной тип результата**:

| Ситуация | Предпочтительная цель |
|---|---|
| Покупки/сделки имеют разную ценность | Максимизация conversion value; при необходимости target ROAS |
| Конверсии экономически близки | Максимизация числа конечных конверсий; при необходимости target CPA |
| Лиды сильно различаются по качеству | Qualified lead, closed-won или прогнозируемая ценность из CRM |
| Редкая конечная продажа | Ближайшее достаточно частое событие, чья связь с продажей эмпирически подтверждена |
| Цель действительно состоит в трафике | Landing-page visits/clicks с явным признанием, что это не продажи |
| Awareness/video | Reach, viewable impressions, frequency, video views или lift, а не performance-конверсии |

Google рекомендует conversion bidding для прямых действий, click bidding — для трафика, impressions — для осведомлённости; Meta определяет performance goal как результат, по которому система участвует в аукционе, и отдельно предлагает conversions, conversion value, landing-page views и clicks ([G1](https://support.google.com/google-ads/answer/2472725), [M1](https://www.facebook.com/business/help/355670007911605)).

При неодинаковой экономической ценности действий следует передавать реальные или обоснованные относительные значения. Yandex рекомендует задавать ценность каждой цели как бизнес-прибыль либо относительный приоритет и использовать динамическую ценность для e-commerce; Microsoft поддерживает revenue и variable value, а Google и Meta предлагают value-based optimization ([Y1](https://yandex.com/support/direct/en/strategies/priority-goals), [MS1](https://learn.microsoft.com/es-es/advertising/campaign-management-service/conversiongoal?view=bingads-13), [G1](https://support.google.com/google-ads/answer/2472725), [M1](https://www.facebook.com/business/help/355670007911605)).

### Уровень D. Опережающие и диагностические показатели

Сюда относятся:

- delivery: spend, impressions, reach, frequency, viewability;
- аукцион: CPM, CPC, доля показов;
- креатив: CTR, video completion, reactions;
- переход: clicks → received/landing-page visits;
- сайт: загрузка, engagement, bounce, глубина, ошибки формы;
- воронка: product view, add-to-cart, checkout, form start;
- качество: qualified-lead rate, approval rate, cancellation/refund rate.

Они объясняют, **где** возникла проблема, но по умолчанию не определяют, **успешна ли** кампания. MRC относит CPC, CTR, VTR и bounce rate к производным efficiency metrics, а interactions требует определять и эмпирически связывать с результатом; реакции и взаимодействия могут иметь как положительный, так и отрицательный смысл ([S1, разделы 2.1.5 и 2.1.8.1](https://mediaratingcouncil.org/sites/default/files/Standards/MRC%20Outcomes%20and%20Data%20Quality%20Standards%20%28Final%29.pdf)).

### Уровень E. Качество измерения и атрибуции

Обязательный отдельный слой:

- источник истины для каждой конверсии;
- primary/biddable против secondary/observation-only;
- count rule: одна конверсия или все;
- click/view/engaged-view window;
- модель атрибуции;
- CRM/offline import и его задержка;
- дедупликация browser/server событий;
- валюта, налог, маржа, возвраты;
- полнота, свежесть и статус тегов;
- consent/privacy;
- сопоставимость моделей и окон между кампаниями.

Google указывает, что primary conversions попадают в основной столбец и влияют на bidding, тогда как secondary используются для наблюдения; Microsoft `ExcludeFromBidding` аналогично исключает цель из bidding, сохраняя её в All Conversions ([G2](https://support.google.com/google-ads/answer/1722022), [MS1](https://learn.microsoft.com/es-es/advertising/campaign-management-service/conversiongoal?view=bingads-13)). MRC требует проверять CRM/sales datasets на полноту, свежесть, гранулярность, систематические пропуски и качество, даже если данные предоставляет сам рекламодатель ([S1, раздел 2.1.7.1](https://mediaratingcouncil.org/sites/default/files/Standards/MRC%20Outcomes%20and%20Data%20Quality%20Standards%20%28Final%29.pdf)).

---

## 3. Правила разрешения конфликтов

### 3.1 Лексикографический приоритет

**Жёсткое ограничение → бизнес-результат → основная оптимизационная цель → диагностика.**

Пример: рост CTR не оправдывает нарушение CAC; снижение CPC не компенсирует падение прибыли; больше лидов не является улучшением, если падает доля квалифицированных и итоговая ценность.

### 3.2 CPA против ROAS

- При близкой ценности всех конверсий допустим CPA.
- При разной ценности CPA может вознаграждать дешёвые, но малодоходные действия — тогда приоритет у conversion value/ROAS.
- При известной марже лучше оптимизировать не валовую выручку, а маржинальную ценность.
- Если ценность приблизительна, профиль обязан маркировать её как proxy и хранить метод расчёта.

Value-based bidding официально предназначен для ситуаций, когда ценность конверсий различается ([G1](https://support.google.com/google-ads/answer/2472725), [MS2](https://learn.microsoft.com/ru-ru/advertising/campaign-management-service/maxconversionvaluebiddingscheme?view=bingads-13)).

### 3.3 ROAS против объёма

Повышение target ROAS или ужесточение CPA обычно ограничивает доступный объём аукционов; чрезмерно агрессивные targets могут снизить объём. Google рекомендует начинать с исторически достижимых CPA/ROAS и использовать симуляторы trade-off между target, бюджетом, числом и ценностью конверсий ([G3](https://support.google.com/google-ads/answer/10970825?hl=en)).

**Вывод (inference):** оператор должен выбрать одну из политик:

- максимизировать ценность при минимальном ROAS;
- максимизировать конверсии при максимальном CPA;
- достичь минимального объёма, затем максимизировать экономическую эффективность.

Нельзя автоматически объявлять более высокий средний ROAS победой, если он достигнут резким сокращением инкрементальной прибыли или объёма.

### 3.4 Платформенные показатели против независимых данных

При расхождении приоритет:

1. проверка одинаковых окон, часовых поясов, counting rules и attribution model;
2. CRM/заказы как источник факта результата;
3. platform attribution для оперативного bidding;
4. controlled lift/incrementality для крупных бюджетных решений.

Meta прямо предупреждает, что результаты ad sets с разными attribution models нельзя корректно сравнивать в общей таблице; Yandex указывает, что отчёт для контроля стратегии должен использовать ту же модель атрибуции, что и стратегия ([M2](https://www.facebook.com/business/help/460276478298895), [Y2](https://yandex.com/support/direct/en/statistics/attribution-model)).

### 3.5 Конфликт target KPI с диагностикой

Если основная метрика улучшилась при ухудшении CTR, CPC или числа показов, вариант не следует отвергать только из-за диагностики. Yandex прямо отмечает: при оптимизации конверсий вспомогательные показы и клики могут различаться и оценивать эксперимент следует по целевой метрике ([Y3](https://yandex.com/support/direct/en/campaigns/experiments)).

Исключение: диагностический показатель является заранее заданным guardrail — например, недопустимая частота, качество лида, отказ страницы или brand-safety нарушение.

---

## 4. Роль визитов и поведения на посадочной странице

### 4.1 Визит — более качественный сигнал доставки, чем исходящий клик

Клик может не завершиться загрузкой страницы из-за задержки, отказа пользователя или технической ошибки. MRC рекомендует при наличии данных использовать **Received Click**, измеренный на ресурсе рекламодателя, и отдельно показывать дальнейшие post-click activity и conversions ([S1, раздел 2.1.5](https://mediaratingcouncil.org/sites/default/files/Standards/MRC%20Outcomes%20and%20Data%20Quality%20Standards%20%28Final%29.pdf)).

Поэтому clicks → landing visits — важный технический диагностический переход.

### 4.2 Но визит не равен бизнес-результату

MRC прямо относит digital visitation к показателям, не являющимся прямой мерой продаж ([S1, раздел 2.1.6](https://mediaratingcouncil.org/sites/default/files/Standards/MRC%20Outcomes%20and%20Data%20Quality%20Standards%20%28Final%29.pdf)). Meta и Google допускают оптимизацию landing-page views/clicks именно как отдельную трафиковую цель, отличную от conversions/value ([M1](https://www.facebook.com/business/help/355670007911605), [G1](https://support.google.com/google-ads/answer/2472725)).

**Следствие:** visits можно сделать основной целью только если:

- сама бизнес-задача — посещаемость;
- конечное действие невозможно надёжно измерить;
- либо это временный proxy для разреженной воронки, связь которого с конечным исходом проверена.

### 4.3 Поведение на странице — прежде всего диагностика

Engaged session, bounce, dwell time, scroll depth, page depth, form start и add-to-cart полезны для:

- выявления несоответствия объявления и посадочной;
- обнаружения технических проблем;
- локализации потерь воронки;
- формирования гипотез A/B-теста;
- раннего мониторинга при задержанных продажах.

Но они уязвимы для оптимизации «ради метрики»: длительность может вырасти из-за запутанного интерфейса, глубина — из-за лишних шагов, а низкий bounce — из-за нецелевого взаимодействия.

**Рекомендация (inference):** engagement, bounce, scroll depth и duration не должны становиться основной performance-целью без доказанной out-of-sample связи с квалифицированной продажей или маржинальной ценностью. Даже тогда их следует маркировать как **proxy optimization target** с датой пересмотра и параллельным контролем конечных результатов.

### 4.4 Что не должно становиться целью performance-оптимизации

Если бизнес ожидает продажи или квалифицированные лиды, не следует без отдельного обоснования оптимизировать:

- spend или освоение бюджета;
- impressions/reach;
- CTR и clicks;
- visits;
- bounce rate, session duration, scroll depth;
- add-to-cart или form start;
- platform optimization score;
- составной «эффективностный балл», скрывающий trade-offs.

Исключение — когда соответствующая величина и есть явно утверждённый результат кампании, например охватная кампания или покупка трафика.

---

## 5. Задержанные и редкие конверсии

### 5.1 Задержка

Оценивать следует только когорты, для которых прошёл обычный conversion cycle и завершился импорт. Google рекомендует исключать последние незрелые дни из исторической оценки и ждать один-два conversion cycles после изменений; Yandex предупреждает о существенной задержке CPA/ROI при цикле более двух недель ([G3](https://support.google.com/google-ads/answer/10970825?hl=en), [Y2](https://yandex.com/support/direct/en/statistics/attribution-model)).

Профиль должен задавать:

- expected conversion lag;
- reporting/import lag;
- maturity cutoff;
- окно атрибуции;
- минимальный срок перед решением;
- источник окончательной ценности.

### 5.2 Разреженный сигнал

При малом числе конечных событий:

1. улучшить измерение и импортировать offline/CRM outcomes;
2. объединять данные только между кампаниями с действительно одинаковой целью;
3. передавать conversion values;
4. временно использовать более частое нижневоронковое событие, если оно предсказывает конечный результат;
5. не дробить бюджет на множество ad sets/campaigns;
6. увеличивать горизонт оценки и показывать неопределённость.

Google заявляет, что Smart Bidding использует и межкампанийные/query-level данные при малом числе конверсий, но рекомендует строить стратегию на достаточной истории; Meta сообщает, что стабильный выход из learning обычно происходит примерно после 50 результатов за неделю; Yandex для A/B-тестов рекомендует не менее 10 конверсий в неделю на вариант и не менее двух бюджетных периодов ([G3](https://support.google.com/google-ads/answer/10970825?hl=en), [M3](https://www.facebook.com/business/help/112167992830700), [Y3](https://yandex.com/support/direct/en/campaigns/experiments)).

Эти пороги являются **рекомендациями/заявлениями конкретных платформ**, а не универсальным статистическим стандартом.

### 5.3 Существенные изменения и обучение

Не следует принимать решения по кратковременному шуму сразу после смены цели, бюджета, креатива или посадочной. Meta указывает, что существенные изменения могут вернуть ad set в learning и что в learning CPA обычно менее стабилен; Yandex требует учитывать 7–14 дней обучения в экспериментах ([M3](https://www.facebook.com/business/help/112167992830700), [Y3](https://yandex.com/support/direct/en/campaigns/experiments)).

---

## 6. Что настраивается для кампании, а что может быть account default

### Обязательно отдельно для каждой кампании

- бизнес-результат и его единица;
- тип кампании: performance, traffic, awareness, experiment;
- основная оптимизационная цель;
- конкретные biddable conversion actions;
- вторичные диагностические actions;
- значения конверсий и метод расчёта;
- budget, pacing и срок;
- target CPA/ROAS или иная граница;
- guardrails и правило разрешения конфликтов;
- источник истины и maturity lag;
- attribution model/windows, применяемые при оценке;
- landing-page diagnostics;
- минимальный объём/период до решения;
- экспериментальная гипотеза и primary experiment metric;
- операторское утверждение и версия.

Meta задаёт performance goal и attribution model на уровне ad set; Yandex позволяет выбрать цели и их ценности в стратегии кампании; Microsoft поддерживает campaign conversion goals, а Google позволяет применять campaign-specific conversion goals вместо account defaults. Это подтверждает необходимость кампанийного слоя, даже если платформы по-разному называют сущности ([M1](https://www.facebook.com/business/help/355670007911605), [M2](https://www.facebook.com/business/help/460276478298895), [Y1](https://yandex.com/support/direct/en/strategies/priority-goals), [MS1](https://learn.microsoft.com/es-es/advertising/campaign-management-service/conversiongoal?view=bingads-13)).

### Допустимо как account-level default

- валюта и часовой пояс;
- каталог доступных conversion actions;
- стандартные источники CRM/analytics;
- правила дедупликации и consent;
- корпоративная модель маржи/LTV;
- рекомендуемые attribution windows;
- шаблон guardrails;
- стандартный maturity policy;
- шаблоны профилей по типу кампании;
- общие quality thresholds.

### Семантика наследования — рекомендация (inference)

1. Default используется **только для инициализации** нового профиля.
2. После утверждения профиль хранит snapshot эффективных значений.
3. Изменение default не переписывает кампании автоматически.
4. Система показывает происхождение каждого поля: default / campaign override / platform import.
5. Любая смена biddable goal, value model, window или conflict policy требует нового operator approval.
6. Должна быть явная операция «обновить из default» с diff и журналом.

---

## 7. Рекомендуемый состав Campaign Effectiveness Profile

```yaml
identity:
  campaign_id:
  profile_version:
  status: draft | approved | superseded
  initialized_from_account_default_version:
  approved_by:
  approved_at:

business_outcome:
  outcome_type: incremental_profit | margin_value | revenue | qualified_lead | traffic | awareness_lift
  outcome_definition:
  value_unit:
  source_of_truth:
  incrementality_required: true | false

hard_constraints:
  total_budget:
  period_budget:
  pacing:
  max_cpa_or_cac:
  min_roas:
  min_margin:
  operational_capacity:
  legal_brand_safety_constraints:

optimization:
  objective_type: conversion_value | conversions | qualified_leads | visits | reach | views
  bid_strategy:
  primary_conversion_actions:
  conversion_value_method:
  target:
  proxy_status: none | temporary | validated
  proxy_expiry_or_review_date:

diagnostics:
  secondary_conversion_actions:
  delivery_metrics:
  click_and_visit_metrics:
  landing_page_metrics:
  funnel_metrics:
  quality_metrics:
  guardrail_thresholds:

measurement:
  attribution_model:
  click_window:
  view_window:
  counting_method:
  timezone_currency:
  expected_conversion_lag:
  reporting_lag:
  cohort_maturity_rule:
  crm_offline_import:
  deduplication:
  tracking_health_thresholds:
  invalid_traffic_and_viewability_notes:

decision_policy:
  priority_order:
  minimum_observation_period:
  minimum_mature_conversions:
  uncertainty_requirement:
  conflict_resolution_rule:
  experiment_required_when:
  rollback_or_pause_conditions:

audit:
  change_log:
  assumptions:
  known_gaps:
  next_review_at:
```

**Не рекомендуется:** вычислять единый непрозрачный «effectiveness score». Если продукту нужен статус, он должен быть правилом над явно показанными уровнями, например: `constraint_breached`, `insufficient_mature_data`, `on_target`, `measurement_unreliable`.

---

## 8. Пограничные случаи

| Случай | Рекомендованное решение |
|---|---|
| Нет денежных values | Использовать конечную однородную конверсию; отдельно хранить допущение об одинаковой ценности |
| Есть только лиды | Передавать qualified/closed-won outcome из CRM; до накопления данных — лид как временный proxy |
| Возвраты и отмены приходят поздно | Оценивать зрелые когорты по net value, а не по моментальной gross revenue |
| Несколько типов конверсий | Не суммировать как равные; назначить values либо оставить вторичные события observation-only |
| Микро- и макроконверсия происходят в одной сессии | Не давать обеим полную экономическую ценность, иначе возникает двойной счёт |
| Длинный B2B-цикл | Использовать stage-weighted expected value, регулярно калибруемый по фактическим closed-won |
| Новый продукт без истории | Более мягкий target, длинный период обучения, proxy с expiry и эксперимент |
| Сильная сезонность/промо | Отмечать event period; не сравнивать напрямую с обычным периодом без поправки |
| Awareness-кампания | Не навязывать CPA/ROAS; использовать reach/frequency/viewability и lift |
| Platform ROAS растёт, CRM profit падает | Проверить attribution/value import; приоритет у зрелого CRM business outcome |
| Разные модели атрибуции | Не ранжировать кампании напрямую до нормализации модели и окон |
| Очень мало данных | Возвращать `insufficient evidence`, а не ложный статус победы/поражения |

---

## 9. Матрица «тезис → источник»

| Тезис | Тип подтверждения | Источник |
|---|---|---|
| Стратегия ставок должна соответствовать цели: conversions, value, clicks или impressions | Официальная документация Google | [G1 — Google Ads, Determine a bid strategy based on your goals](https://support.google.com/google-ads/answer/2472725) |
| Primary conversions влияют на bidding, secondary предназначены для наблюдения | Официальная документация Google | [G2 — About conversion measurement](https://support.google.com/google-ads/answer/1722022) |
| Нужно учитывать conversion cycle, reporting lag и зрелость когорт | Официальная документация Google; vendor guidance | [G3 — How our bidding algorithms learn](https://support.google.com/google-ads/answer/10970825?hl=en) |
| Атрибуция не равна incrementality; iROAS отличается от обычного ROAS | Официальная документация Google | [G4 — Conversion Lift](https://support.google.com/google-ads/answer/14102450?hl=en) |
| Performance goal определяет, за какой результат система оптимизирует аукцион | Официальная документация Meta | [M1 — About performance goals](https://www.facebook.com/business/help/355670007911605) |
| Attribution model/window меняют credit и delivery; разные модели нельзя напрямую сравнивать | Официальная документация Meta | [M2 — About attribution models and attribution settings](https://www.facebook.com/business/help/460276478298895) |
| После значительных изменений результаты нестабильны; ориентир Meta — около 50 результатов в неделю | Официальная рекомендация Meta, не универсальный стандарт | [M3 — About the learning phase](https://www.facebook.com/business/help/112167992830700) |
| Целям Yandex можно назначать бизнес-ценность и относительный приоритет | Официальная документация Yandex | [Y1 — Conversions](https://yandex.com/support/direct/en/strategies/priority-goals) |
| Модель атрибуции влияет на обучение и отчётность; длинный цикл задерживает CPA/ROI | Официальная документация Yandex | [Y2 — Attribution model](https://yandex.com/support/direct/en/statistics/attribution-model) |
| В эксперименте выбирается primary metric; auxiliary metrics могут расходиться; нужны обучение и достаточные данные | Официальная рекомендация Yandex | [Y3 — A/B experiments](https://yandex.com/support/direct/en/campaigns/experiments) |
| Conversion goal включает attribution, window, count type, revenue и исключение из bidding | Официальная API-документация Microsoft | [MS1 — ConversionGoal](https://learn.microsoft.com/es-es/advertising/campaign-management-service/conversiongoal?view=bingads-13) |
| Maximize Conversion Value максимизирует ценность в бюджете и допускает Target ROAS | Официальная API-документация Microsoft | [MS2 — MaxConversionValueBiddingScheme](https://learn.microsoft.com/ru-ru/advertising/campaign-management-service/maxconversionvaluebiddingscheme?view=bingads-13) |
| Traffic/visitation не является прямой мерой продаж; CRM и attribution требуют контроля качества; incrementality требует контрфактической логики | Признанный отраслевой стандарт | [S1 — MRC Outcomes and Data Quality Standards, Final, September 2022](https://mediaratingcouncil.org/sites/default/files/Standards/MRC%20Outcomes%20and%20Data%20Quality%20Standards%20%28Final%29.pdf) |

---

## 10. Уверенность и нерешённые вопросы

### Уверенность

- **Высокая:** разделение business outcome, constraints, optimization target, diagnostics и measurement quality; первичные документы всех четырёх платформ подтверждают, что оптимизируемый сигнал меняет delivery.
- **Высокая:** визиты и landing behavior обычно являются диагностикой, а не прямой мерой продаж; это прямо закреплено MRC.
- **Высокая:** value-based optimization предпочтительнее простого количества, когда ценность результатов различается.
- **Высокая:** attribution и incrementality нельзя считать взаимозаменяемыми.
- **Средняя:** рекомендуемая семантика snapshot-наследования account default — продуктовый вывод, а не отраслевой стандарт.
- **Средняя:** один основной scalar objective плюс guardrails — evidence-backed проектная рекомендация, но интерфейсы платформ иногда допускают несколько conversion goals и внутреннюю агрегацию values.

### Нерешённые продуктовые вопросы

1. Будет ли MOX-ADV хранить **incremental profit** как основной outcome либо первоначально ограничится attributed value?
2. Какая финансовая величина доступна: revenue, gross margin, contribution margin или LTV?
3. Должны ли targets быть единичными числами, диапазонами или функциями объёма?
4. Как описывать stage-weighted value для B2B и кто утверждает вероятности?
5. Нужен ли отдельный режим для awareness, чтобы не применять к нему performance-иерархию механически?
6. Какой минимальный контракт качества данных блокирует автоматические решения?
7. Какие изменения профиля требуют повторного approval и нового периода оценки?
8. Как представлять неопределённость при малом числе конверсий: confidence interval, credible interval или простой статус sufficiency?
9. Нужна ли нормализация к единой независимой attribution view при сравнении платформ?
10. Как часто пересматривать доказанность proxy-метрик и автоматически прекращать их использование?

## Итоговая рекомендация

**Campaign Effectiveness Profile должен отвечать не на вопрос «какие метрики показывать», а на пять отдельных вопросов:**

1. Какой бизнес-результат требуется создать?
2. Какие ограничения нельзя нарушать?
3. Какой единственный основной сигнал получает bidding?
4. Какие показатели только объясняют происходящее?
5. Насколько данным и атрибуции можно доверять?

Такой профиль позволяет разрешать конфликты предсказуемо, не превращать визиты и engagement в суррогат прибыли и сохранять ответственность оператора за смысл оптимизации.
