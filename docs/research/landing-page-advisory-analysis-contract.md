# Контракт advisory-анализа посадочной страницы

**Ticket:** [«Определить контракт advisory-анализа посадочной страницы»](https://github.com/ElJeskos/MOX-ADV/issues/92), часть карты [«Развитие P0 „Стратегия и создание кампании“: карта нерешённых решений»](https://github.com/ElJeskos/MOX-ADV/issues/89)  
**Режим:** исследование и продуктовое решение; без реализации и без изменения сайта  
**Рекомендуемый канонический документ для handoff:** `docs/research/landing-page-advisory-analysis-contract.md`

## Summary

Развитому P0 нужен не «балл качества лендинга», а воспроизводимый advisory-отчёт по восьми независимым областям: соответствие предложения, CTA/квалифицированное действие, формы, готовность измерения, техническая доступность, производительность, accessibility и наблюдаемое поведение Метрики. Каждый вывод должен быть типизирован как **наблюдаемый факт**, **детерминированная автоматическая проверка** или **LLM-гипотеза**, иметь ссылку на сохранённое evidence, время и параметры получения; рекомендации никогда не блокируют создание кампании и не участвуют в viability score — это уже зафиксировано ответами Q21–22 и картой [«Развитие P0 „Стратегия и создание кампании“: карта нерешённых решений»](https://github.com/ElJeskos/MOX-ADV/issues/89).

Зрелые OSS-примитивы следует использовать там, где у них есть проверяемые правила: Lighthouse — для лабораторной производительности и ограниченного набора platform-аудитов, axe-core — для автоматически обнаружимой части accessibility. Offer/message match и CRO — продуктово-специфическая экспертная проверка: она полезна только как объяснимая, проверяемая гипотеза, но не как объективный pass/fail.

## Findings

### 1. Нормативная продуктовая граница

1. **Landing-анализ advisory-only.** Обнаруженные проблемы показываются как рекомендации, после чего путь кампании продолжается; анализ находится на отдельной вкладке аналитики (`to-questionnaire-reklamnyy-modul-mvp.md`, Q21–22). Карта [«Развитие P0 „Стратегия и создание кампании“: карта нерешённых решений»](https://github.com/ElJeskos/MOX-ADV/issues/89) дополнительно фиксирует: landing audit не блокирует путь и сам по себе не снижает viability score.
2. **Агент выполняет безопасное исследование сам.** ADR-0001 запрещает превращать доступные факты и рутинный анализ в форму для оператора; человеку передаётся подготовленное evidence, а не пустой опросник (`docs/adr/0001-agent-owns-safe-work.md`).
3. **Контракт должен продолжать текущую модель evidence/confidence.** Текущий `sites/p0-production/app/P0Client.tsx` уже различает высокую уверенность, гипотезу агента и недостаток данных, показывает цитаты и реальные подключения. Landing-вкладка должна развивать эту семантику, а не вводить непрозрачный итоговый score.
4. **Поведенческие метрики — диагностика, не результат кампании.** Принятый research уже отделяет landing visits, bounce, duration, depth и form start от квалифицированного бизнес-результата (`docs/research/campaign-effectiveness-model.md`, раздел 4). Это согласуется с официальной семантикой Метрики: visit, pageview, bounce rate, page depth и duration — разные агрегаты поведения, а goal visits параметризуются конкретным `goal_id` ([Reports API](https://yandex.com/dev/metrika/en/stat/), [behavior metrics](https://yandex.com/dev/metrika/en/stat/metrics/expenses_visits/behaviour), [parameterization](https://yandex.com/dev/metrika/en/stat/param)).

### 2. Что действительно дают Lighthouse и axe-core

1. **Lighthouse — лабораторный аудит конкретного прогона, не факт реального пользовательского опыта.** PSI прямо разделяет field data и lab data: lab формируется Lighthouse в контролируемой среде и полезен для отладки, но может не отражать реальные bottleneck; field data показывает агрегированный реальный опыт ([PageSpeed Insights](https://developers.google.com/speed/docs/insights/v5/about)). Lighthouse имеет категории Performance, Accessibility, Best Practices и SEO и может запускаться на публичных и аутентифицированных страницах ([Lighthouse overview](https://developer.chrome.com/docs/lighthouse)).
2. **Performance score нельзя трактовать как стабильную характеристику бизнеса или конверсии.** Google рекомендует мыслить распределением прогонов; в score входят метрики, тогда как Opportunities/Diagnostics влияют лишь косвенно ([performance scoring](https://developer.chrome.com/docs/lighthouse/performance/performance-scoring)). Поэтому контракт хранит отдельные метрики, условия и версии, а score показывает только как вторичный снимок.
3. **Lighthouse accessibility score — агрегат применимых автоматических аудитов.** Он является взвешенным средним, а отдельные accessibility-аудиты обычно pass/fail; частичное прохождение элемента не даёт частичного балла аудиту ([accessibility scoring](https://developer.chrome.com/docs/lighthouse/accessibility/scoring)). Это не декларация WCAG-conformance.
4. **axe-core — более подходящий основной primitive для автоматической accessibility-диагностики.** Он публикует правила с WCAG 2.0/2.1/2.2 A/AA/AAA и best-practice tags и различает failures и `needs review`/incomplete ([axe-core README](https://github.com/dequelabs/axe-core/blob/develop/README.md), [rule descriptions](https://github.com/dequelabs/axe-core/blob/develop/doc/rule-descriptions.md)). Версия ruleset и tags являются частью evidence: результаты разных версий нельзя молча склеивать.
5. **Ни axe, ни Lighthouse не доказывают доступность страницы.** W3C прямо указывает, что инструменты не проверяют все аспекты, могут давать ложные или вводящие в заблуждение результаты и только помогают оценке; WCAG требует сочетания автоматического тестирования и человеческой оценки ([Selecting evaluation tools](https://www.w3.org/WAI/test-evaluate/tools/selecting/), [Understanding conformance](https://www.w3.org/WAI/WCAG22/Understanding/conformance)). ACT rules и WCAG techniques информативны; основание conformance — сами success criteria ([ACT rules](https://www.w3.org/WAI/WCAG22/Understanding/understanding-act-rules.html), [WCAG techniques](https://www.w3.org/WAI/WCAG22/Understanding/understanding-techniques)).

**Решение:** запускать Lighthouse и axe-core как независимые источники. Не усреднять их scores, не выдавать `axe: 0 violations` за «WCAG AA», не дублировать все axe findings из Lighthouse; в UI Lighthouse отвечает прежде всего за performance/platform diagnostics, axe — за rule-level accessibility findings.

### 3. Field и lab performance должны быть разведены

1. **Field evidence:** запрашивать CrUX/PSI для точного URL и отдельно помечать origin fallback. CrUX агрегирует реальные Chrome experiences в распределения URL- или origin-level и включает данные только при выполнении eligibility-критериев ([CrUX methodology](https://developer.chrome.com/docs/crux/methodology), [CrUX API](https://developer.chrome.com/docs/crux/api)). Отсутствие URL-level данных означает `insufficient field coverage`, а не плохую производительность; origin aggregate нельзя приписывать конкретной посадочной.
2. **Lab evidence:** выполнять контролируемый Lighthouse-прогон на точном финальном URL с зафиксированными Lighthouse/Chrome version, form factor, locale, throttling, cache state, timestamp и redirect chain. Для снижения случайности рекомендуемый контракт — три прогона на mobile profile и медиана метрик; desktop — дополнительный профиль, если он материален для кампании. Это продуктовая мера воспроизводимости, а не заявление Lighthouse о статистической гарантии.
3. **Показывать отдельно:** field Core Web Vitals distributions/percentiles и coverage scope; lab LCP, CLS, TBT и прочие доступные метрики конкретной версии Lighthouse; opportunities как рекомендации. Не заменять field INP лабораторным TBT и не сравнивать разные сущности как одну метрику.

### 4. Метрика доказывает конфигурацию и наблюдаемое поведение, но не причинность

1. **Counter/goal readiness.** Management API позволяет получить доступные счётчики с уровнем permission и status, список и конкретную конфигурацию целей ([counters](https://yandex.com/dev/metrika/en/management/openapi/counter/counters), [goals](https://yandex.com/dev/metrika/en/management/openapi/goal/goals), [goal](https://yandex.com/dev/metrika/en/management/openapi/goal/goal)). `metrika:read` достаточно для чтения, но владелец токена должен иметь доступ к счётчику ([Metrica API FAQ](https://yandex.com/dev/metrika/en/faq)). Наличие goal object доказывает только конфигурацию; оно не доказывает, что событие реально отправляется, соответствует квалифицированному действию или попадает без дублей.
2. **Техническое присутствие.** Публичный browser-run может наблюдать загрузку тега и вызовы/события, но без безопасного завершения квалифицированного действия это не доказательство рабочей конверсии. Контракт запрещает отправлять форму, создавать лид, звонок, заказ или иное внешнее действие только ради аудита.
3. **Историческое наблюдение.** Reporting API возвращает агрегаты по dimensions/metrics; Logs API может вернуть session fields, включая pageviews, bounce и достигнутые goal IDs ([Reports API](https://yandex.com/dev/metrika/en/stat/), [Logs visits fields](https://yandex.com/dev/metrika/en/logs/fields/visits)). Для exact landing URL контракт показывает sample size и точный сегмент/период: visits, goal visits/conversion rate по утверждённому goal ID, bounce rate, average duration и page depth; при наличии — разрыв clicks→visits из согласованного Direct-среза.
4. **Семантика bounce не универсальна.** В Метрике bounce — одностраничный визит короче настроенного порога (по умолчанию 15 секунд) без non-bounce event; изменение настройки меняет смысл показателя ([Metrica glossary](https://yandex.com/support/metrica/en/general/glossary)). Следовательно, высокий/низкий bounce без counter settings, объёма и контекста не является объективным CRO-вердиктом.
5. **Малый объём не поддерживает вывод.** Яндекс предупреждает, что формально корректный агрегат на одном визите не даёт разумного вывода ([statistical accuracy](https://yandex.com/support/metrica/en/reports/false-data)). Контракт не изобретает универсальный порог; он всегда показывает `n`, период и возвращает `INSUFFICIENT_EVIDENCE`, когда нет достаточного объёма для заявленной интерпретации.
6. **Свежесть.** Session data может обновляться по мере поступления событий; в документации Metrica Pro указано, что в среднем 99% сессий завершается в течение трёх дней ([working with data](https://yandex.com/support/metrica/en/pro/data-work)). Базовый advisory-срез поэтому исключает последние три календарных дня, фиксирует дату доступа и не называет наблюдаемую связь причинным эффектом лендинга.

### 5. CRO-ревью необходимо, но только как гипотеза

Offer/message match, убедительность оффера, заметность CTA, ожидаемое трение формы и возможное объяснение bounce не имеют универсального машинно-проверяемого эталона. Автоматически можно доказать наличие текста, DOM-элемента, ссылки, числа полей, HTML-атрибутов и фактического перехода; вывод «обещание достаточно убедительно» или «форма отпугивает аудиторию» остаётся LLM-гипотезой.

Каждая CRO-гипотеза обязана содержать:

- точный claim без языка факта: «возможно», «гипотеза», «стоит проверить»;
- Campaign Strategy context: offer, audience, ad message, qualified action;
- 1–3 evidence refs: screenshot region, DOM/text quote, CTA/form inventory, Metrica segment;
- counter-evidence или альтернативное объяснение;
- confidence `LOW | MEDIUM | HIGH` и причину;
- рекомендуемое проверяемое изменение и метрику будущей проверки;
- запрет превращения одной гипотезы в universal best practice без эксперимента.

Это продолжает принятую модель Operational Hypothesis из `CONTEXT.md`: тестируемое утверждение не является policy rule и не расширяет authority.

## Recommended contract

### 6. Вход и неизменяемая идентичность запуска

Один `LandingAdvisoryRun` логически связывает:

- `run_id`, `contract_version`, время начала/окончания;
- исходный URL, финальный URL и redirect chain;
- immutable revision Campaign Strategy: offer/product, audience, message, qualified action, exclusions;
- counter ID и candidate primary goal ID либо явное `NOT_CONNECTED`;
- tool/browser versions и параметры каждого collector;
- факт, что формы и иные внешние действия не отправлялись;
- ссылки/hash на минимальный evidence packet;
- общий статус покрытия, но **не landing score**.

Повторный запуск создаёт новую ревизию и не переписывает прошлое. Сравнение допустимо только при показанном diff URL/strategy/tool versions/settings.

### 7. Единая модель утверждения

Каждый finding хранит следующие обязательные поля:

| Поле | Контракт |
|---|---|
| `kind` | `OBSERVED_FACT` · `DETERMINISTIC_CHECK` · `LLM_HYPOTHESIS` |
| `area` | одна из восьми областей ниже |
| `statement` | короткий проверяемый вывод |
| `status` | `ISSUE_OBSERVED` · `NO_ISSUE_FOUND` · `INSUFFICIENT_EVIDENCE` · `NOT_APPLICABLE` |
| `advisory_priority` | `HIGH` · `MEDIUM` · `LOW`; это порядок просмотра, не blocker |
| `evidence_refs` | минимум одна адресуемая ссылка на артефакт/фрагмент |
| `method` | правило, tool+version или LLM rubric+version |
| `confidence` | `HIGH` для прямого факта; для checks зависит от applicability; для гипотезы обязательно обоснование |
| `limitations` | что данным не доказано |
| `recommendation` | необязательная безопасная рекомендация; никаких автоматических изменений сайта |

`NO_ISSUE_FOUND` означает только «исследованные правила не нашли проблему», а не «область качественна». Термин `critical` не использовать в landing-вкладке, чтобы advisory priority не выглядела campaign gate.

### 8. Рубрика восьми областей

| Область | Наблюдаемые факты | Детерминированные проверки | Только LLM-гипотезы |
|---|---|---|---|
| **Offer/message match** | title/H1/видимый above-the-fold текст, цена/условия, цитаты strategy/ad message | присутствует ли заявленный продукт/бренд/обязательное условие; ведёт ли ad URL на ожидаемый final URL | понятность, убедительность и семантическое соответствие обещания намерению аудитории |
| **CTA и qualified action** | inventory видимых buttons/links, label, destination/action, положение на screenshot | CTA существует, интерактивен, имеет доступное имя, не ведёт на ошибку; заявленное действие технически представлено | заметность, ясность микрокопии, соответствие CTA квалифицированному результату |
| **Forms** | form/control inventory, labels, types, required, autocomplete, action/method; screenshots empty/error state если безопасно | programmatic labels; duplicate IDs; browser constraint validation; HTTPS action; required/type/autocomplete consistency; submit **не выполнять** | лишнее трение, разумность порядка/числа полей, доверие и ожидание после отправки. HTML даёт стандартные labels, required и constraint validation, но не подтверждает бизнес-корректность формы ([HTML forms](https://www.w3.org/TR/html/sec-forms.html), [MDN constraint validation](https://developer.mozilla.org/en-US/docs/Web/HTML/Guides/Constraint_validation)) |
| **Measurement readiness** | counter/goal API objects и permissions; загрузившийся tag; observed event names без конверсии | final URL входит в counter site scope/filters; candidate goal существует и его type/conditions сопоставимы с действием; нет конфигурационного противоречия | «эта цель означает qualified lead» без подтверждённой бизнес-семантики; качество дедупликации/CRM без evidence |
| **Technical reachability** | DNS/browser navigation, HTTP/redirect chain, final status, HTTPS/certificate browser result, console/network failures, rendered DOM | конечный документ загружается без auth/interstitial/5xx; нет redirect loop; critical resources не blocked/mixed; CTA targets reachable безопасным GET. `robots.txt` — инструкция cooperative crawlers, а не security или пользовательская недоступность ([MDN robots.txt](https://developer.mozilla.org/en-US/docs/Web/Security/Practical_implementation_guides/Robots_txt)) | влияние отдельной ошибки на конверсию, если оно не наблюдалось |
| **Performance** | CrUX URL/origin distributions и coverage; три Lighthouse lab runs и median | наличие/отсутствие field coverage; повторяемые lab metric/diagnostic thresholds текущей версии Lighthouse | ожидаемый прирост конверсии от улучшения скорости |
| **Accessibility** | axe violations/incomplete/inapplicable, Lighthouse accessibility audits, screenshots/DOM refs | только исходы конкретных axe/Lighthouse rules с version/tags; небольшой ручной smoke-check keyboard/focus помечается observed fact | WCAG-conformance, полная доступность и влияние на конверсию без полноценной human evaluation |
| **Observed Metrica behavior** | exact segment, dates, attribution/settings, visits, selected goal outcomes, bounce, duration, depth, sample size | корректность параметризации goal/URL/period; availability/freshness status | причины поведения, causal effect лендинга, намерение пользователя |

### 9. Минимальный evidence packet

Пакет считается полным, если сохранены либо явно помечены `UNAVAILABLE/NOT_APPLICABLE`:

1. **Manifest:** run/contract versions, strategy revision, exact URL/final URL, timestamps, locale, viewport, browser/tool versions, hashes и collector errors.
2. **Browser snapshot:** full-page screenshot и above-the-fold screenshot; DOM/text snapshot после стабилизации; CTA/form inventory; console errors и failed/blocked network requests; redirect/final HTTP metadata. Секреты, cookies, tokens и введённые персональные данные не сохраняются.
3. **Performance:** raw Lighthouse JSON для трёх mobile runs + computed median; CrUX/PSI raw response с явным scope `URL | ORIGIN | NONE`. Desktop run — только если профиль трафика/кампании делает его материальным.
4. **Accessibility:** raw axe JSON с `violations`, `incomplete`, `passes`, `inapplicable`, axe version и selected WCAG tags; Lighthouse accessibility section как дополнительный источник.
5. **Measurement configuration:** read-only counter summary (ID, status, permission, site/filter-relevant fields), goal object (ID, name/type/conditions) и browser evidence загрузки тега; никаких write API или cabinet evidence.
6. **Behavior slice:** raw Metrica Reporting API request/response для exact landing segment и утверждённого goal ID за последний доступный 28-дневный период, заканчивающийся не позже `today−3 days`, плюс предыдущий сопоставимый период при наличии. Хранятся sample size, filters, dimensions, metrics, attribution/model settings и API sampling/accuracy metadata, если возвращаются.
7. **Findings ledger:** все findings по схеме раздела 7 и evidence refs до конкретного node/screenshot crop/API cell, а не только ссылки на главную страницу.

Почему пакет минимален: без strategy revision невозможно оценить match; без rendered evidence — динамические CTA/forms; без raw OSS results — воспроизвести checks; без counter/goal config — отличить «цель существует» от догадки; без sample size/segment — поведенческие числа вводят в заблуждение.

### 10. Компактная отдельная вкладка аналитики

**Заголовок:** URL, время/ревизия, `Advisory — не влияет на запуск и viability`, coverage `8/8 | partial`, кнопка «Повторить анализ» как новый run.

**Первый экран:**

- не более трёх приоритетных рекомендаций;
- три раздельных счётчика `Факты / Автопроверки / Гипотезы`, а не один score;
- восемь компактных строк областей со status, advisory priority и одной фразой;
- отдельный мини-блок Метрики: период, visits `n`, goal ID/name, goal visits/rate, bounce/duration/depth и badge `описательно, не причинно`.

**Раскрытие области:** findings с постоянными badges `ФАКТ`, `ПРОВЕРКА`, `ГИПОТЕЗА`; screenshot crop/цитата/metric; метод и limitation; рекомендация. В drawer «Доказательства» — raw artifacts, tool versions, request parameters и errors.

**Запрещённые UX-паттерны:** общий процент «качества лендинга», красный blocker, вычитание из campaign viability, claim «WCAG compliant», смешивание origin CrUX с URL data, «низкий bounce = хороший лендинг», CRO-тезис без badge гипотезы, скрытая отправка формы или изменение сайта.

### 11. Детерминированный итог запуска

Landing run завершается одним техническим status:

- `COMPLETE` — все обязательные collectors дали evidence или корректный `NOT_APPLICABLE`;
- `PARTIAL` — страница исследована, но, например, нет CrUX/Метрики или один collector упал;
- `UNREACHABLE` — браузер не получил пригодный rendered document;
- `FAILED` — внутренний сбой не позволил сформировать проверяемый packet.

Любой status остаётся advisory. Даже `UNREACHABLE` показывает очень приоритетную рекомендацию и evidence, но **не меняет campaign eligibility, publish readiness или viability score**. Если иной production safety-контракт независимо проверяет URL перед внешней записью, его gate является отдельной технической проверкой publish contour и не должен ссылаться на landing quality score.

## Confidence and limitations

- **Высокая уверенность:** product boundary advisory-only; разведение facts/checks/hypotheses; lab/field semantics; ограничения automated accessibility; read-only возможности counters/goals/reports Метрики. Они подтверждены repository decisions и первичными документами Google/Chrome, Deque, W3C и Яндекса.
- **Средне-высокая:** предложенный минимальный evidence packet и UI — продуктовая рекомендация, выведенная из требований воспроизводимости, но не внешний стандарт.
- **Средняя:** три Lighthouse mobile runs, 28-дневный завершённый Metrica window и `today−3 days` — консервативная operational policy. Она должна быть versioned и может калиброваться, не меняя семантику источников.
- **Ограничение:** автоматический аудит одной rendered state не покрывает все responsive states, consent variants, авторизацию, многошаговые процессы, assistive technologies и реальные пользовательные задачи.
- **Ограничение:** без безопасного test lead или production history нельзя доказать end-to-end срабатывание цели; API goal object и загруженный tag — только readiness evidence.
- **Ограничение:** Metrica behavior наблюдательно, зависит от сегмента, настройки bounce, атрибуции, traffic mix, объёма и свежести; оно не устанавливает причинность.
- **Ограничение:** CRO-гипотезы требуют последующей проверки на фактическом исходе; их confidence не превращает мнение модели в факт.

## Sources

### Kept — authoritative/primary

- [«Определить контракт advisory-анализа посадочной страницы»](https://github.com/ElJeskos/MOX-ADV/issues/92) и [«Развитие P0 „Стратегия и создание кампании“: карта нерешённых решений»](https://github.com/ElJeskos/MOX-ADV/issues/89) — непосредственный scope и принятые product invariants.
- `CONTEXT.md`, `docs/adr/0001-agent-owns-safe-work.md`, `to-questionnaire-reklamnyy-modul-mvp.md`, `sites/p0-production/app/P0Client.tsx` — канонические repository/product sources.
- `docs/research/campaign-effectiveness-model.md`, `docs/research/yandex-direct-metrica-capabilities.md`, `docs/research/p0-yandex-campaign-creation-contour.md` — существующие решения по metric roles, API boundary и P0 measurement readiness.
- [Lighthouse overview](https://developer.chrome.com/docs/lighthouse), [performance scoring](https://developer.chrome.com/docs/lighthouse/performance/performance-scoring), [accessibility scoring](https://developer.chrome.com/docs/lighthouse/accessibility/scoring), [Lighthouse source/docs](https://github.com/GoogleChrome/lighthouse/blob/main/docs/understanding-results.md) — официальные semantics и raw result structure.
- [PageSpeed Insights](https://developers.google.com/speed/docs/insights/v5/about), [CrUX methodology](https://developer.chrome.com/docs/crux/methodology), [CrUX API](https://developer.chrome.com/docs/crux/api) — field/lab и URL/origin coverage.
- [axe-core README](https://github.com/dequelabs/axe-core/blob/develop/README.md), [axe rule descriptions](https://github.com/dequelabs/axe-core/blob/develop/doc/rule-descriptions.md) — официальный OSS source/rule mapping и incomplete semantics.
- [W3C accessibility evaluation](https://www.w3.org/WAI/test-evaluate/tools/selecting/), [WCAG conformance](https://www.w3.org/WAI/WCAG22/Understanding/conformance), [ACT rules](https://www.w3.org/WAI/WCAG22/Understanding/understanding-act-rules.html) — нормативная/первичная граница автоматической проверки.
- [Yandex Metrica counters](https://yandex.com/dev/metrika/en/management/openapi/counter/counters), [goals](https://yandex.com/dev/metrika/en/management/openapi/goal/goals), [Reports API](https://yandex.com/dev/metrika/en/stat/), [Logs visits](https://yandex.com/dev/metrika/en/logs/fields/visits), [behavior metrics](https://yandex.com/dev/metrika/en/stat/metrics/expenses_visits/behaviour), [glossary](https://yandex.com/support/metrica/en/general/glossary), [statistical accuracy](https://yandex.com/support/metrica/en/reports/false-data) — конфигурация, наблюдаемое поведение и ограничения интерпретации.
- [W3C HTML forms](https://www.w3.org/TR/html/sec-forms.html) и [MDN constraint validation](https://developer.mozilla.org/en-US/docs/Web/HTML/Guides/Constraint_validation) — platform semantics формы; MDN использован как официальная browser-platform документация, не как CRO authority.

### Dropped

- SEO/CRO blogs, vendor landing-page graders и «conversion benchmark» compilations — не primary sources и смешивают рекомендации с недоказанной причинностью.
- Lighthouse/axe issue discussions, когда тот же claim подтверждён стабильной официальной документацией — нестабильны и не нужны для решения.
- Любые данные browser cabinets Direct/Metrica — запрещены repository boundary; использованы только официальные API docs.
- Универсальные пороги «достаточного числа визитов» и обещания uplift от скорости/accessibility/CRO — нет надёжного общего основания для contract-level deterministic claim.

## Gaps

1. Перед реализацией нужно выбрать versioned schema/retention/redaction policy для raw evidence и проверить, какие counter fields безопасно сохранять.
2. Нужен отдельный implementation ticket на разрешённый browser collector и read-only Metrica adapter; этот research не выполнял live URL, Lighthouse, axe или production API calls.
3. Если продукт захочет заявлять WCAG conformance, потребуется отдельный human-led WCAG-EM scope; текущий контракт намеренно этого не делает.
4. Семантику «candidate goal соответствует qualified action» необходимо связать с утверждённой Campaign Strategy; одного технического goal ID недостаточно.
