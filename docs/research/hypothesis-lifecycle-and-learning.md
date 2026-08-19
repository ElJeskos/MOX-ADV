# Как Автономный оператор кампаний должен развивать и проверять гипотезы

**Репозиторий:** ElJeskos/MOX-ADV

**Дата проверки ключевых источников:** 19.08.2026

**Статус:** исследовательская рекомендация; спецификация решения, не проект реализации

## 1. Краткий ответ

Автономный оператор кампаний не должен хранить гипотезу как редактируемую заметку или сразу превращать сигнал в изменение рекламы. Нужны три связанные, но разные машины состояний:

1. **исследование:** `SIGNAL_RECORDED → DIAGNOSED → FORECASTED`;
2. **проверка неизменяемой ревизии гипотезы:** `DRAFT → ELIGIBLE → PREREGISTERED → SELECTED → RAMPING → ACTIVE → AWAITING_MATURITY → ANALYSIS_READY → EVALUATED`;
3. **результат:** `RETAINED | REJECTED | INSUFFICIENT_DATA | INVALIDATED | UNSAFE`.

`REFINED` не переписывает старый результат: система создаёт новую ревизию со ссылкой на завершённую. `TRANSFER_CANDIDATE` — не отдельная универсальная истина, а квалификация локального `RETAINED`-результата для новой проверки в другой кампании.

До первого назначения traffic детерминированный статистический модуль выбирает и замораживает control или заранее допустимую базу, estimand, primary metric, MDE, power/precision, multiplicity family, объём или sequential boundaries, attribution/maturity и правила success, no-go, safety stop и invalidation. После freeze содержательное изменение создаёт новую ревизию; выбирать метрику, сегмент или момент остановки по уже увиденному результату запрещено.

Сохранённое знание может изменить приоритет следующей гипотезы, диапазон прогноза и draft-протокол. Оно **не может напрямую** менять production code, Campaign Effectiveness Profile, Gate 0, protective policy, Mandate, класс автономности или настройки кампании. Любой write остаётся новым типизированным планом и заново проходит текущие policy, reservation, execution и readback.

## 2. Что уже утверждено и здесь не переоткрывается

Нормативный источник — `requirements-autonomous-campaign-operator.md`; связанные решения зафиксированы в Wayfinder-карте.

- Человек утверждает бизнес-цель, Campaign Effectiveness Profile, допустимую финансовую экспозицию, hard limits и полномочия. Он не выбирает статистический метод или порядок эксперимента.
- Модель предлагает диагноз, операционную гипотезу, typed plan и объяснение. Детерминированные модули отвечают за данные, расчёты, eligibility, статистическую оценку, policy, исполнение, readback, reconciliation, rollback и audit.
- Причинная проверка отделена от прогноза и обычного сравнения «до/после»; по умолчанию используется предзарегистрированный одновременный randomized control/treatment.
- До запуска фиксируются механизм, одна primary decision metric, guardrails, допустимый риск и срок наблюдения.
- Результат принимается только на достаточном объёме зрелых данных и при сравнении с control либо заранее допустимой базой.
- Отрицательный исход не удаляется и не повторяется без нового основания.
- Результат одной кампании становится только кандидатом для target validation и репликации.
- Операционный runtime уже содержит долговечное `WAIT_MATURITY`; изменение Campaign Effectiveness Profile, policy, Mandate или существенного входного snapshot требует revalidation.

## 3. Три машины состояний вместо одного комбинаторного enum

### 3.1. Исследование сигнала

| Стадия | Смысл | Guard следующего перехода | Артефакт |
|---|---|---|---|
| `SIGNAL_RECORDED` | Monitoring Cycle зафиксировал отклонение, возможность или противоречие | Есть provenance, `as_of`, campaign scope, data-quality и maturity labels | Наблюдение, не causal claim |
| `DIAGNOSED` | Сформированы конкурирующие объяснения | Проверены tracking, freshness/maturity, manual reconciliation, budget cap, learning phase, auction/seasonality, collision и policy causes | Ranked diagnosis с неопределённостью |
| `FORECASTED` | Оценены ожидаемый диапазон эффекта, downside, стоимость, traffic и срок | Прогноз закреплён за Profile и baseline snapshot и явно не назван доказательством | Decision value и feasibility |

Прогноз нужен для приоритизации, а не для подтверждения собственной гипотезы. Ошибка прогноза также сохраняется как сигнал к калибровке, но не меняет исход эксперимента.

### 3.2. Проверка одной неизменяемой ревизии

Identity ревизии:

`mechanism × treatment contrast × eligible population × causal context/effect modifiers × estimand/primary outcome × comparator × measurement regime`.

Она навсегда закрепляет ссылки на версии Campaign Effectiveness Profile, исходного data snapshot, Statistical Decision Policy, protective policy, Mandate и statistical engine.

| Состояние | Смысл | Обязательный guard |
|---|---|---|
| `DRAFT` | Определены механизм, treatment, population и outcome | Treatment обратим или компенсируем; указан comparator; сформулирован проверяемый механизм |
| `ELIGIBLE` | Пройдены gates до статистического freeze | Policy, observability, readback, rollback, budget, power feasibility, maturity и interference известны; unknown не считается pass |
| `PREREGISTERED` | Полный протокол заморожен до данных treatment | Схема валидна; protocol hash, timestamp и engine/config versions записаны до assignment |
| `SELECTED` | Гипотеза получила reservation | Пройдены portfolio priority, collision graph, cumulative exposure/budget, TTL и актуальность authority versions |
| `RAMPING` | На малой доле проверяются доставка и безопасность | Оцениваются только delivery, readback, assignment/SRM, tracking и hard guardrails; использование ramp data заранее определено |
| `ACTIVE` | Идёт confirmatory assignment/exposure | Treatment, comparator, split, eligibility, primary metric, attribution и planned looks не меняются |
| `AWAITING_MATURITY` | Новое exposure остановлено, outcomes дозревают | Когорты получают одинаковое зарегистрированное attribution/maturity window; guardrails продолжают работать |
| `ANALYSIS_READY` | Объём/precision и maturity достигнуты | Пройдены SRM, completeness, assignment integrity, collision и preregistration-consistency checks; dataset locked |
| `EVALUATED` | Frozen decision rule применён детерминированно | Записаны effect и CI/CS, MDE, primary и guardrail outcomes, multiplicity, deviations и evidence grade |

`Monitoring Cycle` не остаётся открытым на недели: он продвигает durable state до следующего ожидания. `RAMPING`, `AWAITING_MATURITY`, pause и reconciliation переживают сбой через checkpoint, а не через LLM-контекст.

### 3.3. Взаимоисключающие dispositions

| Результат | Точное значение | Последствие |
|---|---|---|
| `RETAINED` | Frozen success rule выполнен на mature comparable data, guardrails допустимы | Сохранить scoped evidence; deployment остаётся отдельным typed plan |
| `REJECTED` | Валидный тест не поддержал practically useful effect либо выполнил зарегистрированный no-go rule | Сохранить отрицательное scoped knowledge; идентичный silent retry запрещён |
| `INSUFFICIENT_DATA` | Maximum window/feasibility исчерпаны, а precision не отделяет полезный эффект от отсутствия/вреда | Не объявлять «нулевой эффект»; допустима новая powered revision |
| `INVALIDATED` | Causal/сравнительный вывод испорчен SRM, contamination, tracking failure, changed treatment/metric, непредусмотренным peeking или collision | Не считать treatment проигравшим; повтор только после root-cause closure |
| `UNSAFE` | Safety, policy, budget или harm boundary потребовала stop/rollback | Success inference запрещён; новый запуск проходит отдельную safety revalidation |

Разделение обязательно: `REJECTED ≠ INSUFFICIENT_DATA ≠ INVALIDATED ≠ UNSAFE`. Иначе система превращает сломанный тест в отрицательное знание или бесконечно повторяет уже опровергнутую идею.

### 3.4. Уточнение и перенос

- **Уточнение (`REFINED`)** — отношение между ревизиями. Старая сохраняет terminal disposition, новая получает `derived_from`, `novelty_basis` и начинает с `DRAFT`. Это не post-hoc rescue.
- **Кандидат на перенос (`TRANSFER_CANDIDATE`)** — квалификация `RETAINED`-результата с правдоподобным механизмом и описанными effect modifiers. Она разрешает только target validation, а не auto-apply.
- Только причинный evidence grade может стать кандидатом на причинный перенос. Результат по квазиэкспериментальной или исторической базе остаётся локальным operational evidence до независимой randomized replication.

## 4. Как система выбирает comparator

Comparator выбирается до power calculation и замораживается в протоколе.

1. **Concurrent randomized control:** текущее подтверждённое production state — default.
2. **Concurrent active control:** другая заранее утверждённая практика, если вопрос состоит в выборе между допустимыми вариантами.
3. **Randomized cluster/geo/switchback design:** если user/auction split не устраняет spillover из shared budget, bidding loop, inventory или географии.
4. **Заранее утверждённая квазиэкспериментальная база:** synthetic/matched control, interrupted time series или иной protocol с pre-trend/comparability и sensitivity checks, когда настоящий randomized control технически недоступен.
5. **Простой historical before/after baseline:** только для диагностики, прогноза, variance/maturity estimate и exploratory evidence; он не подтверждает causal transfer.

Таким образом, требование «control либо заранее утверждённая база» сохраняется, но evidence grade остаётся явным. Заранее выбранная база не становится рандомизацией только из-за preregistration.

Если используемый Yandex primitive не позволяет проверить assignment/exposure либо comparator, гипотеза не может получить causal `RETAINED`; допустим только ограниченный operational или exploratory вывод.

## 5. Алгоритм выбора и freeze статистического правила

### 5.1. Версионируемая Statistical Decision Policy

Система использует версионируемую техническую **Statistical Decision Policy**, которая задаёт поддерживаемые test families, стандартные диапазоны error/precision, multiplicity control, maturity computation, calibration и invalidation rules. Это не per-experiment выбор пользователя и не вывод LLM. Человек задаёт бизнес-цель, допустимый downside и финансовую экспозицию; детерминированный модуль выбирает точный статистический protocol внутри них.

### 5.2. Детерминированный выбор

1. **Закрепить decision problem.** Из активного Campaign Effectiveness Profile взять business outcome, одну primary decision metric, допустимые guardrails и единицу бизнес-решения.
2. **Определить estimand и causal contrast.** Зафиксировать population, randomization unit, analysis unit, eligibility, direction и treatment/control contrast.
3. **Выбрать comparator** по иерархии раздела 4 и записать evidence grade.
4. **Определить MDE.** Система выводит минимальный practically useful effect из profile targets, стоимости изменения, downside и business decision; это не «эффект, который легче получить значимым».
5. **Оценить baseline, variance и delay.** Использовать pinned pre-experiment history или A/A, а не outcomes treatment. Учесть variance на unit of randomization, clustering/design effect, eligibility, attrition и maturity curve.
6. **Выбрать test family.** Учитываются тип метрики, assignment, clusters/interference, доступный traffic, maximum duration и необходимость раннего решения:
   - `fixed-horizon` по умолчанию, если срок и объём предсказуемы;
   - заранее спроектированный `group-sequential` с planned looks и alpha-spending, если ожидание дорого;
   - `anytime-valid` CI/CS или e-process только при time-uniform guarantees и отдельной калибровке;
   - safety stop всегда независим от success rule.
7. **Рассчитать N/precision/window.** Входы: baseline, variance, MDE, α/error budget, power `1−β` или требуемая precision, allocation, arms, clusters, multiplicity, attrition и доля mature outcomes. Window покрывает релевантные бизнес-циклы и conversion tail.
8. **Определить multiplicity family.** Treatment arms, planned looks и confirmatory segments объявляются заранее. Post-hoc metrics/segments остаются exploratory.
9. **Разделить четыре правила:** success, reject/no-go, safety abort и invalidation. Maximum window без precision ведёт в `INSUFFICIENT_DATA`, не в `REJECTED`.
10. **Проверить калибровку.** Формулы или симуляция покрывают ожидаемые distributions, clustering, missingness и looks; новый assignment/measurement primitive сначала проходит A/A.
11. **Freeze до assignment.** Канонический protocol получает digest, timestamp и версии engine/config. Analysis job принимает только protocol digest и locked dataset.

Google Ads прямо связывает experiment power с volume, variability, split, duration и expected uplift; поэтому универсальное правило «достаточно N конверсий» запрещено [G3]. NIST показывает, что performance threshold и acceptable risk определяют sample size/acceptance criterion, а sequential test должен проектироваться отдельно от fixed-sample [N1].

### 5.3. Минимальное содержимое preregistration

- mechanism и treatment contrast;
- comparator, assignment unit/split, analysis unit;
- eligible population и exclusions;
- estimand, одна primary metric, direction и MDE;
- guardrails и допустимый downside;
- α/error budget, power/precision и sidedness;
- baseline/variance source snapshot;
- fixed N/end rule либо sequential looks/boundaries;
- multiplicity family/correction;
- conversion action, attribution model/window и maturity rule;
- ramp, SRM, missing-data, collision и invalidation rules;
- maximum duration, business cycles, budget/loss limits;
- rollback/containment consequences;
- statistical-engine и analysis-code version.

После freeze разрешены только заранее предусмотренные адаптации. Иное изменение завершает текущую ревизию как `INVALIDATED` либо `INSUFFICIENT_DATA` по причине и создаёт новую preregistration.

## 6. Зрелость и поздние данные

Доступность, свежесть и зрелость — разные свойства.

- Yandex Direct сообщает, что статистика обычно стабилизируется в течение трёх дней и иногда исправляется ретроспективно [Y1].
- Offline conversions появляются в отчётах Метрики в течение трёх часов после upload, но это лишь processing readiness, а не завершение бизнесового conversion tail [Y2].
- Google рекомендует учитывать conversion delay, ждать conversion cycles и для конкретных PMax/Shopping experiments исключает ramp-период; эти числа являются product-specific guidance, а не универсальной константой [G4].

Поэтому `maturity_not_before` определяется по exposure cohort, attribution window, empirical conversion-delay quantile, reporting/import delay и reconciliation state. После stop-delivery readback продолжается до зарегистрированной зрелости; последние незрелые cohorts не смешиваются с mature analysis.

## 7. Какие новые основания разрешают повтор

Каждая новая ревизия после отрицательного/неполного исхода должна пройти механический novelty predicate и ссылаться на evidence.

### 7.1. Достаточные основания

1. **Устранена причина `INVALIDATED` или `INSUFFICIENT_DATA`:** исправлены assignment/SRM, tracking/join loss, maturity, contamination, collision либо power feasibility; указано, почему исправление восстанавливает идентифицируемость или precision.
2. **Материально изменён mechanism или treatment:** другая causal chain, а не новая формулировка того же предложения.
3. **Появился обоснованный target context:** другой campaign/population/geo/inventory/strategy с заранее названным effect modifier. Это новая target validation, а не стирание source rejection.
4. **Изменился внешний режим, участвующий в механизме:** conversion definition, attribution regime, product/price/landing experience, platform capability или auction regime. Нужны новая identity и revalidation Profile.
5. **Появился независимый противоречащий causal evidence:** репликация в сопоставимом контексте и заранее объяснённая heterogeneity.
6. **Изменился business decision/estimand:** только через новую утверждённую ревизию Campaign Effectiveness Profile или иное уже предусмотренное критическое решение; старый результат не пересчитывается задним числом.
7. **После `UNSAFE` устранён hazard:** подтверждены containment/mitigation и актуальная policy/mandate authorization. Ослабление hard limit не может быть автономным «новым основанием».

### 7.2. Недостаточные основания

- просто прошло время;
- LLM сменил prompt, temperature, seed или объяснение;
- после валидного powered rejection выделили больше бюджета без нового механизма;
- выбрали новую metric, segment или look после просмотра;
- заменили fixed horizon на optional stopping ради значимости;
- заявили «рынок изменился» без проверяемого effect modifier;
- автоматически ослабили guardrail/policy;
- повторили тот же treatment в том же scope без независимого противоречащего evidence.

Большая выборка является основанием после `INSUFFICIENT_DATA`, но не после валидного `REJECTED`, где interval уже исключил зарегистрированный MDE.

## 8. Как отделить знание от кода, policy и исполнения

| Изменение | Смысл | Авторитетный контур | Может ли само выполнить campaign write? |
|---|---|---|---|
| Signal, diagnosis, draft hypothesis | Кандидат проверяемого знания | Модель предлагает; runtime валидирует и записывает | Нет |
| `RETAINED`/`REJECTED` evidence | Scoped экспериментальный результат | Statistical evaluator + audit | Нет |
| `TRANSFER_CANDIDATE` | Приоритет target validation | Knowledge layer | Нет |
| Typed campaign Action Plan | Предложение изменения | Модель предлагает; runtime заново вычисляет diff/eligibility/policy | Только после authorization/reservation/execution |
| Campaign Effectiveness Profile revision | Изменение цели и metric governance | Критическое решение человека; immutable revision | Не напрямую; активные планы revalidate |
| Gate 0 / protective policy revision | Изменение полномочий и safety governance | Отдельный policy process; ослабление требует человека | Не обходит runtime |
| Temporary pause/rollback | Исполнение заранее утверждённой защиты | Deterministic safety runtime | Да, только в ранее разрешённом классе/лимите |
| Production code/statistical engine | Engineering artifact | Отдельный SDLC, tests, review, release/versioning | Нет до deployment и policy authorization |

### No-direct-effect rule

Knowledge records могут влиять только на:

- ranking следующей гипотезы;
- prior/forecast range;
- список известных failure modes и effect modifiers;
- draft preregistration;
- необходимость replication или prohibition proposal.

Они не могут напрямую менять campaign settings, code, Campaign Effectiveness Profile, Statistical Decision Policy, Gate 0, Mandate, autonomy level или protective policy. `RETAINED` означает «проверяемое знание улучшено в данном scope», а не «изменение уже внедрено».

Обнаруженный вред может немедленно запустить уже утверждённый pause/rollback и создать предложение усилить policy. Durable prohibition или любое relaxation — policy revision, а не «самообучение».

## 9. Минимальный handoff в библиотеку знаний

Детальную модель хранения и promotion до playbook решает отдельный тикет «Как хранить знания о гипотезах и повышать их до playbook?». Этот lifecycle передаёт ему immutable result envelope:

- hypothesis revision и protocol digest;
- source scope/effect modifiers;
- comparator, treatment и estimand;
- effect estimate + CI/CS + MDE;
- evidence grade;
- validity, maturity, data-quality и guardrail outcomes;
- disposition и reason;
- mechanism statement;
- replication/transfer qualification;
- ссылки на Profile, policy, Mandate, data и engine versions.

Ни один уровень promotion сам по себе не расширяет execution authority.

## 10. Проверочные сценарии

| Сценарий | Правильный исход |
|---|---|
| CTR вырос, mature business outcome ещё не готов | `AWAITING_MATURITY`; CTR остаётся diagnostic |
| 50/50 assignment дал SRM из-за ошибки идентификаторов | `INVALIDATED`, не `REJECTED`; root-cause closure до новой revision |
| Valid test закончен, interval допускает и полезный, и вредный эффект | `INSUFFICIENT_DATA`, не «эффекта нет» |
| Treatment улучшил primary, но пересёк hard CPA/budget guardrail | `UNSAFE`/rollback по frozen rule; не `RETAINED` |
| Улучшение замечено только в post-hoc mobile segment | Exploratory signal → новая preregistration; не rescue текущего теста |
| Локальный causal result успешен в одной кампании | `RETAINED + TRANSFER_CANDIDATE`; target campaign требует своей проверки |
| Изменилась основная business outcome профиля во время теста | Старый write authorization недействителен; данные остаются историческими; новая revision/revalidation |
| Model предлагает изменить α после просмотра p-value | Запрет; текущий protocol неизменяем, предложение не исполняется |
| Найден баг statistical engine | Старый Decision Record не переписывается; engineering fix проходит SDLC, affected results получают reassessment |
| Policy автоматически хочет ослабить guardrail из-за серии побед | Запрет; evidence не расширяет полномочия |

## 11. Матрица утверждений и первичных источников

| ID | Материальное утверждение | Источник |
|---|---|---|
| G1 | До запуска нужна ясная hypothesis и выбранные success metrics; по умолчанию тестируется одна переменная; base не меняется несинхронно; результаты сохраняются | [Google Ads — Test with confidence with the Experiments page](https://support.google.com/google-ads/answer/7281575?hl=en) |
| G2 | Google применяет jackknife к bucketed data и 95% CI; split выполняется до targeting; A/A требует идентичности; user-level buckets недоступны рекламодателю для точного воспроизведения | [Google Ads — The statistical methodology behind experiments](https://support.google.com/google-ads/answer/9232676?hl=en) |
| G3 | Experiment power зависит от volume, variability, split, duration, type и expected uplift и является оценкой, а не гарантией | [Google Ads — Build better experiments with Campaign Guidance](https://support.google.com/google-ads/answer/15911255?hl=en) |
| G4 | Перекрывающиеся experiments могут интерферировать; split нельзя менять после setup; длинный conversion delay и ramp влияют на срок и анализ | [Google Ads — Experiments FAQs](https://support.google.com/google-ads/answer/13826584?hl=en) |
| N1 | Testable objective связывает performance threshold и acceptable risk с sample size/acceptance criterion; fixed и sequential designs имеют разные заранее проектируемые структуры | [NIST Technical Note 2045](https://nvlpubs.nist.gov/nistpubs/TechnicalNotes/NIST.TN.2045.pdf) |
| M1 | SRM указывает на проблему assignment/pipeline; severity alerts и multiple-testing adjustment отделяют валидность/safety от treatment outcome | [Microsoft ExP — Alerting](https://www.microsoft.com/en-us/research/articles/alerting-in-microsofts-experimentation-platform-exp/) |
| M2 | Cross-context A/B требует совместимых randomization unit, assignment, joins и analysis data; join loss способен исказить вывод | [Microsoft Research — A/B Testing Across Products](https://www.microsoft.com/en-us/research/articles/a-b-testing-across-products/) |
| M3 | Выбор победителя из нескольких treatments повышает false positives и завышает effect estimate; independent validation устраняет selection bias | [Deng, Li, Guo — Statistical Inference in Two-Stage Online Controlled Experiments](https://www.exp-platform.com/Documents/p609-deng.pdf) |
| Y1 | Direct statistics обычно стабилизируется в течение трёх дней и может исправляться ретроспективно | [Yandex Direct API — How to get updated statistics](https://yandex.com/dev/direct/doc/en/actual) |
| Y2 | Offline conversions появляются в Metrica reports в течение трёх часов после upload | [Yandex Metrica API — Passing offline conversions](https://yandex.com/dev/metrika/en/management/offline-conv) |

Дополнительная методологическая и source matrix база: [`safe-campaign-experimentation.md`](safe-campaign-experimentation.md).

## 12. Уверенность и границы решения

**Высокая уверенность:** раздельные dispositions; immutable preregistration до assignment; deterministic rule selection; concurrent randomized control по умолчанию; explicit evidence grade; maturity ожидание; novelty predicate; no-direct-effect от знания к полномочиям.

**Средне-высокая:** точная иерархия comparator. Randomized concurrent design остаётся default; конкретная доступность cluster/geo/switchback и platform-native assignment зависит от поддерживаемых Yandex primitives.

**Сознательно оставлено следующим тикетам:**

- canonical knowledge object, evidence levels, promotion/demotion и playbook versioning — «Как хранить знания о гипотезах и повышать их до playbook?»;
- конкретные typed interfaces agent/runtime — «Где проходит interface между агентом и детерминированными модулями?»;
- durable storage, orchestration и engine deployment — «Какая runtime-архитектура исполняет долговечный операционный цикл?».

Нового существенного продуктового решения не выявлено. Значения α/power/precision, test family, maturity и multiplicity являются версионируемой технической политикой, которую система определяет и валидирует внутри уже утверждённых бизнес-рисков; они не требуют выбора статистики пользователем.
