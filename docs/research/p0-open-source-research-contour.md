# P0: open-source модули и agent skills для исследовательского контура

**Ticket:** [GitHub Wayfinder #96](https://github.com/ElJeskos/MOX-ADV/issues/96)  
**Дата среза:** 21.08.2026  
**Режим:** evidence-only; кандидаты не устанавливались, не запускались и не интегрировались; внешние записи и production API-вызовы не выполнялись.

## 1. Короткий ответ

Безусловно принять как базовые компоненты следует только **официальный API-first контур Яндекса**, **Lighthouse** и **axe-core**. `askads/mcp-yandex-wordstat` заслуживает адаптации за небольшой прозрачный read-only transport, но не прямого включения: репозиторий очень молодой и малопопулярный, а `raw_request` и override API host расширяют поверхность egress. У навыков `keyword-research` / `competitor-analysis` обнаружены два одноимённых источника: provider-bound варианты OpenSEO и standalone-навыки [`aaron-he-zhu/aaron-marketing-skills`](https://github.com/aaron-he-zhu/aaron-marketing-skills). OpenSEO вместе с его skills полезен как reference, а пару Aaron и Anthropic `campaign-plan` стоит адаптировать к контрактам MOX-ADV; landing-page skill — только reference. `SEOSiri-Official/keyword-cluster-mcp` следует отклонить: 0 stars/0 forks, незакреплённые зависимости и несколько существенных расхождений между заявлениями и кодом.

Рекомендация ниже отделена от evidence: сначала приведены наблюдаемые факты по каждому кандидату, затем decision matrix.

## 2. Продуктовая и trust boundary

Исследование исходит из локальных документов [`CONTEXT.md`](../../CONTEXT.md), [`ADR-0001`](../adr/0001-agent-owns-safe-work.md), [`p0-yandex-campaign-creation-contour.md`](./p0-yandex-campaign-creation-contour.md) и [`yandex-direct-metrica-capabilities.md`](./yandex-direct-metrica-capabilities.md). Для MOX-ADV исследование и синтез — Agent-Owned Work, но authority не расширяется молча; Direct/Metrica разрешены только через официальные API, кабинеты браузера исключены. P0 уже требует отдельного read-only measurement contour, exact-bound credentials, post-call readback и отсутствия `Campaigns.resume` в create transaction.

Практические критерии отбора:

1. Любой сетевой модуль должен иметь явный allowlist назначения, read-only профиль и отдельный credential scope.
2. Любой результат сохраняется как provenance-bearing typed evidence; Markdown совет или model prose не является фактом API.
3. Любая скрытая запись (project context, saved keywords, telemetry, локальный report) считается side effect и должна быть либо отключена, либо вынесена в отдельный bounded action.
4. Web-аудит выполняется только над разрешённым URL в изолированном browser profile; authenticated target требует отдельного решения о передаче cookies/headers.

## 3. Сводка первичных метрик

GitHub stars/forks получены 21.08.2026 из first-party GitHub REST repository resources; npm downloads — first-party npm downloads API за окно 21.07–19.08.2026; skills installs — счётчик официальной страницы каталога Skills.sh на дату среза (это marketplace counter, не доказательство уникальных активных пользователей).

| Source | Репутация источника | Popularity / installs на 21.08.2026 |
|---|---|---:|
| Yandex Direct, Metrica, Cloud Wordstat APIs | Вендор платформы, primary specification | n/a |
| [`askads/mcp-yandex-wordstat`](https://github.com/askads/mcp-yandex-wordstat) | Маленькая сторонняя GitHub organization; один npm maintainer | **4 stars / 0 forks**; npm **1,124 downloads / 30 days** ([GitHub API](https://api.github.com/repos/askads/mcp-yandex-wordstat), [npm API](https://api.npmjs.org/downloads/point/last-month/mcp-yandex-wordstat)) |
| [`SEOSiri-Official/keyword-cluster-mcp`](https://github.com/SEOSiri-Official/keyword-cluster-mcp) | Молодая сторонняя organization / один названный архитектор | **0 / 0**; PyPI не публикует usable download count (`-1`) ([GitHub API](https://api.github.com/repos/SEOSiri-Official/keyword-cluster-mcp), [PyPI JSON](https://pypi.org/pypi/seosiri-keyword-cluster-mcp/json)) |
| [`GoogleChrome/lighthouse`](https://github.com/GoogleChrome/lighthouse) | Официальный GoogleChrome project | **30,683 / 9,753**; npm **17,353,834 / 30 days** ([GitHub API](https://api.github.com/repos/GoogleChrome/lighthouse), [npm API](https://api.npmjs.org/downloads/point/last-month/lighthouse)) |
| [`dequelabs/axe-core`](https://github.com/dequelabs/axe-core) | Deque, профильный accessibility vendor | **7,422 / 916**; npm **271,102,285 / 30 days** ([GitHub API](https://api.github.com/repos/dequelabs/axe-core), [npm API](https://api.npmjs.org/downloads/point/last-month/axe-core)) |
| [`every-app/open-seo`](https://github.com/every-app/open-seo) | Молодой, но крупный community repo | **12,943 / 1,477** ([GitHub API](https://api.github.com/repos/every-app/open-seo)) |
| OpenSEO `keyword-research` / `competitor-analysis` | Те же maintainer и repo | **2.6K / 2.5K Skills.sh installs** ([keyword](https://skills.sh/every-app/open-seo/keyword-research), [competitor](https://skills.sh/every-app/open-seo/competitor-analysis)) |
| [`aaron-he-zhu/aaron-marketing-skills`](https://github.com/aaron-he-zhu/aaron-marketing-skills) `keyword-research` / `competitor-analysis` | Крупный standalone skill bundle; индивидуальный maintainer | parent repo **2,612 / 346**; skills **937 / 787 installs** ([GitHub API](https://api.github.com/repos/aaron-he-zhu/aaron-marketing-skills), [marketplace](https://www.skills.sh/aaron-he-zhu/aaron-marketing-skills)) |
| [`autonnel/autonnel-skills`](https://github.com/autonnel/autonnel-skills) landing audit | Неизвестный индивидуальный maintainer, новый repo | **0 / 0**, но **21.1K Skills.sh installs** ([GitHub API](https://api.github.com/repos/autonnel/autonnel-skills), [marketplace](https://www.skills.sh/autonnel/autonnel-skills)) |
| Anthropic `campaign-plan` | Официальная Anthropic organization | parent repo **23,587 / 2,845**; skill **2.7K installs** ([GitHub API](https://api.github.com/repos/anthropics/knowledge-work-plugins), [marketplace](https://skills.sh/anthropics/knowledge-work-plugins/campaign-plan)) |

**Popularity caveat.** 4 stars у `askads` и 0 stars у SEOSiri — явно низкая популярность, несмотря на наличие package releases. У landing audit 21.1K marketplace installs при 0 stars/0 forks и возрасте repo около двух недель — счётчик резко непропорционален repository trust; его следует считать **подозрительным/неверифицированным сигналом распространения**, а не доверием. Даже большие marketplace/npm counters не заменяют source review и pinning.

## 4. Evidence по кандидатам

### 4.1 Официальный API-first Yandex baseline

**Identity / license / reputation.** Это не один OSS repository, а набор first-party contracts: [Yandex Cloud WordstatService](https://yandex.cloud/en/docs/search-api/api-ref/grpc/Wordstat/), [Wordstat REST structure](https://yandex.com/support2/wordstat/en/content/api-structure), [Direct API v5 overview](https://yandex.com/dev/direct/doc/en/concepts/overview), [Direct Reports](https://yandex.com/dev/direct/doc/en/reports), [Metrica Reports API](https://yandex.com/dev/metrika/en/stat/) и [Metrica authorization](https://yandex.com/dev/metrika/en/intro/authorization). API terms are vendor terms, не OSS-лицензия; внутренний adapter MOX-ADV остаётся собственным кодом.

**Reproducibility / network / credentials.** Wordstat предоставляет `GetTop`, `GetDynamics`, `GetRegionsDistribution`, `GetRegionsTree`; REST использует HTTPS `POST` и JSON. Cloud service-account API key отправляется как `Authorization: Api-Key`, для него документирован scope `yc.search-api.execute`, и запрос привязывается к `folderId` ([WordstatService](https://yandex.cloud/en/docs/search-api/api-ref/grpc/Wordstat/), [API key](https://yandex.cloud/en/docs/iam/concepts/authorization/api-key)). Direct использует HTTPS/POST, OAuth 2.0 bearer token пользователя и JSON management responses; Reports возвращает TSV и может отвечать 201/202 до готовности ([overview](https://yandex.com/dev/direct/doc/en/concepts/overview), [token](https://yandex.com/dev/direct/doc/en/concepts/auth-token), [report flow](https://yandex.com/dev/direct/doc/en/how-to)). Metrica read требует `metrika:read`; write scopes отличаются и не нужны исследовательскому контуру ([authorization](https://yandex.com/dev/metrika/en/intro/authorization)). Egress полностью ограничим official Yandex hosts.

**Side effects / Yandex specificity.** Wordstat и report/get calls read-only, хотя семантическое чтение Wordstat/Direct передаётся через POST. Direct и Metrica также имеют write methods, поэтому безопасен не «POST/GET guard», а exact operation allowlist. Это единственный кандидат, нативно соответствующий российскому/Yandex спросу, фактическим search queries Direct и goal/report semantics Metrica.

**Output contract.** Wordstat возвращает method-specific JSON; Direct management — documented JSON objects, Reports — typed TSV columns; Metrica Reports — JSON/CSV и goal metrics parameterized by goal ID ([Wordstat structure](https://yandex.com/support2/wordstat/en/content/api-structure), [Direct report specification](https://yandex.com/dev/direct/doc/en/spec), [Metrica parametrization](https://yandex.com/dev/metrika/en/stat/param)). Schema evolution остаётся vendor-controlled, поэтому adapter должен сохранять API version, request projection, response hash, observation time и raw payload рядом с canonical MOX-ADV envelope.

**Tests / caveats.** Вендор даёт Sandbox для Direct, но account eligibility, quota, currency и Cloud billing остаются runtime preflight; production calls в этом исследовании не выполнялись ([Direct quick start](https://yandex.com/dev/direct/doc/en/best-practice/quick-start)). Baseline не даёт clustering/CRO reasoning сам по себе.

### 4.2 `askads/mcp-yandex-wordstat`

**Identity / license / release.** TypeScript stdio MCP server `io.github.askads/mcp-yandex-wordstat`; MIT; author Aleksandr Kovalko, npm maintainer `gistrec`. `package.json` и MCP manifest фиксируют version **2.3.0**, Node `>=20`, npm artifact имеет integrity hash и git head; latest опубликован 18.08.2026 ([package](https://github.com/askads/mcp-yandex-wordstat/blob/main/package.json), [manifest](https://github.com/askads/mcp-yandex-wordstat/blob/main/server.json), [npm metadata](https://registry.npmjs.org/mcp-yandex-wordstat), [LICENSE](https://github.com/askads/mcp-yandex-wordstat/blob/main/LICENSE)). Popularity низкая: 4/0.

**Reproducibility.** Есть `package-lock.json`, versioned npm tarball, build/typecheck/source tests и dist smoke test; `prepublishOnly` запускает typecheck+tests. Последний GitHub CI run для release head успешен ([workflow run](https://github.com/askads/mcp-yandex-wordstat/actions/runs/32190350731)). Использование `npx -y` без version pin всё же нерепродуцируемо; нужен exact npm version+integrity.

**Network / credentials / side effects.** `WORDSTAT_API_KEY` (secret) и `WORDSTAT_FOLDER_ID` передаются в Yandex Cloud Search API; client проверяет same-origin, retries 429/5xx/network и cache-ит region tree in-memory. Все domain tools read-only ([manifest](https://github.com/askads/mcp-yandex-wordstat/blob/main/server.json), [client](https://github.com/askads/mcp-yandex-wordstat/blob/main/src/client.ts)). Но по умолчанию включена отдельная telemetry: сервер пишет installation UUID в `~/.config/mcp-yandex-wordstat/instance-id` и отправляет на `usage.gistrec.cloud` event/tool name и версии среды; opt-out — `ASKADS_TELEMETRY=0` ([telemetry source](https://github.com/askads/mcp-yandex-wordstat/blob/main/src/telemetry.ts)). Дополнительно manifest разрешает `WORDSTAT_API_BASE` override, а toolset включает `raw_request`; same-origin guard защищает key от перехода на второй origin, но оператор всё ещё может целиком заменить base host. MOX-ADV должен отключить telemetry, удалить override/raw tool и жёстко allowlist official origin.

**Yandex specificity / output.** Нативно мапит top/related queries, dynamics, regions и region tree на Cloud Wordstat v2; input normalization есть. Client return type — `unknown`, ответы преимущественно pass-through provider JSON; собственного versioned domain envelope и compatibility policy нет ([client](https://github.com/askads/mcp-yandex-wordstat/blob/main/src/client.ts), [tools contract](https://github.com/askads/mcp-yandex-wordstat/blob/main/docs/TOOLS.md)).

**Caveats.** Очень молодой single-maintainer package; npm 1,124 downloads не компенсируют 4 stars. API key — Cloud service account secret, его нельзя смешивать с Direct OAuth/Metrica credential. Полезен код transport/retry/SSRF guard, но не готовый trust boundary.

### 4.3 `SEOSiri-Official/keyword-cluster-mcp`

**Identity / license / reputation.** Python package `seosiri-keyword-cluster-mcp` 1.0.0, MIT, attributed Momenul Ahmad/SEOSiri; repo создан 03.08.2026 и имеет 0 stars/0 forks ([repo API](https://api.github.com/repos/SEOSiri-Official/keyword-cluster-mcp), [PyPI](https://pypi.org/pypi/seosiri-keyword-cluster-mcp/json), [LICENSE](https://github.com/SEOSiri-Official/keyword-cluster-mcp/blob/main/LICENSE)).

**Reproducibility / tests.** PyPI wheel/sdist имеют SHA-256, но dependencies заданы широкими lower bounds (`mcp>=1.0.0`, `requests>=2.28.0`, FastAPI/Uvicorn), lockfile отсутствует, README предлагает `uv run --github ...` без commit pin. Один test file содержит 13 happy-path assertions, последний CI green ([pyproject](https://github.com/SEOSiri-Official/keyword-cluster-mcp/blob/main/pyproject.toml), [tests](https://github.com/SEOSiri-Official/keyword-cluster-mcp/blob/main/tests/test_keyword_cluster.py), [CI run](https://github.com/SEOSiri-Official/keyword-cluster-mcp/actions/runs/30796002260)). Нет adversarial/property/schema tests и coverage report.

**Network / credentials / side effects.** stdio Python server почти полностью local and credential-free; RAG indexing пишет только в process-local SQLite `:memory:`. Однако bundled Cloudflare Worker проксирует любой path/method/body и исходные headers, включая `Authorization`, на hard-coded `https://hubappapi.seosiri.com/keyword-cluster`, с permissive CORS `*` ([server](https://github.com/SEOSiri-Official/keyword-cluster-mcp/blob/main/src/main_server.py), [worker](https://github.com/SEOSiri-Official/keyword-cluster-mcp/blob/main/worker.js)). Local server импортирует `requests`, FastAPI и Uvicorn, но фактически их не использует; credential model для edge backend не документирован.

**Yandex specificity / output.** Yandex data и morphology отсутствуют. Все tools возвращают JSON **как string**, без shared JSON Schema. Clustering — first-match token overlap; intent — небольшой English substring list; «embedding» — 384-bin sum-of-character-code hash, а response отдаёт только первые 10 dimensions; «Parquet buffer» в действительности возвращает исходный JSON с label `COLUMNS_OPTIMIZED` и не создаёт Parquet ([source](https://github.com/SEOSiri-Official/keyword-cluster-mcp/blob/main/src/main_server.py)).

**Material caveats (HIGH).** README/PyPI говорит о 10 tools, source/spec — 13; `get_live_keyword_throughput_metrics` не измеряет throughput; «semantic» и «LSI» claims не подтверждаются реализацией; output не соответствует названию Parquet. Это не просто низкая популярность, а contract/reputation mismatch.

### 4.4 Lighthouse

**Identity / license / reputation.** Официальный `GoogleChrome/lighthouse`, Apache-2.0, 30,683 stars/9,753 forks; npm 17.35M downloads/30 days ([repo API](https://api.github.com/repos/GoogleChrome/lighthouse), [LICENSE](https://github.com/GoogleChrome/lighthouse/blob/main/LICENSE), [npm downloads](https://api.npmjs.org/downloads/point/last-month/lighthouse)). Mature Google-maintained project, встроен в Chrome ecosystem.

**Reproducibility / tests.** Repo документирует lint, unit, smoke, type and docs tests; CI badges и coverage присутствуют. Для воспроизводимости нужен pinned Lighthouse+Chrome version, URL state, viewport, locale, throttling and isolated host. Официальная variability guide требует несколько последовательных запусков; median из пяти runs вдвое стабильнее одного, concurrent runs запрещены из-за contention ([README](https://github.com/GoogleChrome/lighthouse), [variability](https://github.com/GoogleChrome/lighthouse/blob/main/docs/variability.md)).

**Network / credentials / side effects.** Lighthouse запускает/подключает Chrome, navigates target URL и тем самым загружает все first/third-party resources и выполняет page JS. Credentials не обязательны; authenticated audit может использовать существующую browser session или `extra-headers`, что делает cookies/headers чувствительными. CLI по умолчанию очищает cache и некоторые storage APIs; `--disable-storage-reset` меняет это, а passive gathering отдельно минимизирует destructive behavior ([CLI flags](https://github.com/GoogleChrome/lighthouse), [settings types](https://github.com/GoogleChrome/lighthouse/blob/main/types/lhr/settings.d.ts), [auth recipe](https://github.com/GoogleChrome/lighthouse/blob/main/docs/recipes/auth/README.md)). Reports могут записываться на диск; `--save-assets` дополнительно пишет traces/screenshots/devtools logs.

**Yandex specificity / output.** Не Yandex-specific; полезен для landing performance/SEO/best practices. Canonical programmatic output — Lighthouse Result (`result.lhr`); CLI поддерживает JSON/HTML/CSV, optional traces. JSON содержит audit/category evidence и config, но scores являются lab observations, не conversion lift и не production field data ([programmatic docs](https://github.com/GoogleChrome/lighthouse/blob/main/docs/readme.md), [CLI](https://github.com/GoogleChrome/lighthouse)).

**Caveats.** Навигация потенциально вызывает site-side analytics, A/B allocation, personalization и другие GET/page-load effects; не использовать кабинеты, authenticated admin pages или URL с action semantics. Один performance score не является воспроизводимым фактом.

### 4.5 axe-core

**Identity / license / reputation.** `dequelabs/axe-core`, MPL-2.0 (file-level copyleft; bundled third-party licenses отдельно), 7,422 stars/916 forks, npm 271.1M downloads/30 days; actively supported by Deque ([repo API](https://api.github.com/repos/dequelabs/axe-core), [LICENSE](https://github.com/dequelabs/axe-core/blob/develop/LICENSE), [README](https://github.com/dequelabs/axe-core), [npm downloads](https://api.npmjs.org/downloads/point/last-month/axe-core)).

**Reproducibility / tests.** Developer guide содержит unit/integration/API/TypeScript suites и `npm test`; project mature. Pin exact version, browser, DOM state, viewport and ruleset/tags. Dynamic DOM, iframes and load timing остаются input variability ([developer guide](https://github.com/dequelabs/axe-core/blob/develop/doc/developer-guide.md)).

**Network / credentials / side effects.** Core library injects/runs analysis in existing document, читает DOM/style/accessibility-relevant state и сам не требует credentials или external API. Navigation/credentials belong to outer browser harness; returning node HTML/selectors means report may contain page data and must be treated as sensitive. `axe.run()` cleans internal caches; application writes are not part of its contract ([API](https://github.com/dequelabs/axe-core/blob/develop/doc/API.md), [types](https://github.com/dequelabs/axe-core/blob/develop/axe.d.ts)).

**Yandex specificity / output.** Не Yandex-specific. Typed `AxeResults`: `passes`, `violations`, `incomplete`, `inapplicable`; each result includes rule id, impact, help URL, tags and nodes/selectors/HTML. `incomplete` explicitly requires manual review ([API](https://github.com/dequelabs/axe-core/blob/develop/doc/API.md)).

**Caveats.** README claims automated detection on average 57% of WCAG issues; axe is not a complete accessibility audit, and no-violation result is not compliance ([README](https://github.com/dequelabs/axe-core)). MPL obligations should be preserved if source files are modified; unmodified npm dependency is straightforward.

### 4.6 `every-app/open-seo` application

**Identity / license / reputation.** MIT TypeScript app, version 0.1.6, 12,943 stars/1,477 forks. Popular but repo created only 27.02.2026; maintainer is `every-app`, not Google/DataForSEO/Yandex ([repo API](https://api.github.com/repos/every-app/open-seo), [LICENSE](https://github.com/every-app/open-seo/blob/main/LICENSE), [package](https://github.com/every-app/open-seo/blob/main/package.json)).

**Reproducibility / tests.** pnpm version and lockfile are pinned; CI uses frozen lockfile, formatting, dead-code, type/lint, Vitest, worker build guard, website build and Docker build. E2E scripts exist but main CI excerpt does not run Playwright E2E ([package](https://github.com/every-app/open-seo/blob/main/package.json), [CI](https://github.com/every-app/open-seo/blob/main/.github/workflows/ci.yml)). Published Docker default `latest` is not reproducible; docs recommend a version tag.

**Network / credentials.** Core SEO evidence egresses to paid **DataForSEO** via base64 `login:password`; optional AI egresses to OpenRouter; GSC integration stores Google OAuth tokens encrypted with `BETTER_AUTH_SECRET`. Self-host app also emits anonymized telemetry unless `OPENSEO_TELEMETRY_DISABLED=1`/`DO_NOT_TRACK=1` ([self-host docs](https://github.com/every-app/open-seo/blob/main/docs/SELF_HOSTING_DOCKER.md), [.env](https://github.com/every-app/open-seo/blob/main/.env.example)). This is not Yandex-specific and introduces vendor costs and data transfer outside Yandex.

**Side effects / credentials.** App persists projects, research logs, saved keywords, competitors/key pages and OAuth state. Docker mode is `local_noauth` with injected `admin@localhost`; official docs warn never to expose it without a protected reverse proxy ([self-host docs](https://github.com/every-app/open-seo/blob/main/docs/SELF_HOSTING_DOCKER.md)). Package includes deployment/database migration/telemetry scripts, so whole-app inclusion is much broader than read-only research.

**Output / caveats.** MCP tools expose useful metrics but app does not provide a MOX-ADV/Yandex schema; DataForSEO estimates and GSC first-party facts must be separated. Large popularity is meaningful ecosystem evidence, not permission to add DataForSEO/OpenRouter/GSC egress.

### 4.7 OpenSEO agent skill `keyword-research`

**Identity / license.** Source is [`.agents/skills/keyword-research/SKILL.md`](https://github.com/every-app/open-seo/blob/main/.agents/skills/keyword-research/SKILL.md), inherited under repo MIT; 2.6K Skills.sh installs ([marketplace](https://skills.sh/every-app/open-seo/keyword-research)). Static Markdown skill, no standalone release/version or dedicated maintainer.

**Procedure / network / credentials.** Requires OpenSEO `projectId`, calls project context, DataForSEO-backed keyword/SERP tools and optional GSC. It correctly says not to invent missing metrics and asks before `save_keywords`, but it also instructs automatic durable writes to project context, competitor/key-page collections and research log ([SKILL.md](https://github.com/every-app/open-seo/blob/main/.agents/skills/keyword-research/SKILL.md)). Thus it is not read-only even though external SEO calls are research calls.

**Output / Yandex / tests.** Output is Markdown recommendation plus table `Keyword | Intent | Volume | KD | CPC | Priority | Notes`, not JSON Schema. It uses generic/Google/DataForSEO semantics, not Wordstat regions/operators or Direct query facts. No dedicated skill behavior tests were found in the repository tree; generic repo CI only verifies sync/format/type code paths.

**Material value.** Reusable pattern: seeds → first-party demand → hydrate metrics → inspect ambiguous SERPs → filter business fit → evidence/inference separation. For MOX-ADV replace DataForSEO/GSC with Wordstat + Direct search-query reports + Metrica, remove writes from research phase, and produce a typed envelope.

### 4.8 OpenSEO agent skill `competitor-analysis`

**Identity / license.** [`.agents/skills/competitor-analysis/SKILL.md`](https://github.com/every-app/open-seo/blob/main/.agents/skills/competitor-analysis/SKILL.md), MIT via parent repo; 2.5K marketplace installs ([marketplace](https://skills.sh/every-app/open-seo/competitor-analysis)).

**Procedure / egress / side effects.** Calls DataForSEO domain/keyword/backlink/SERP APIs and optional GSC; persistently upserts competitor context and a research-log entry without a separate confirmation. Useful guardrails require separation of evidence/inference, refuse copying, and prevent national metrics from masquerading as local evidence ([SKILL.md](https://github.com/every-app/open-seo/blob/main/.agents/skills/competitor-analysis/SKILL.md)).

**Output / Yandex / tests.** Markdown snapshot and table `Area | Competitor pattern | Evidence | OpenSEO opportunity`; no machine contract, confidence/provenance schema or Yandex specificity. No dedicated skill tests found. Backlink/traffic estimates remain third-party observations, not Direct/Metrica facts.

### 4.9 `aaron-he-zhu/aaron-marketing-skills`: `keyword-research` и `competitor-analysis`

**Identity / license / trust.** Standalone Markdown skills [`keyword-research`](https://github.com/aaron-he-zhu/aaron-marketing-skills/blob/main/seo-geo/survey/keyword-research/SKILL.md) и [`competitor-analysis`](https://github.com/aaron-he-zhu/aaron-marketing-skills/blob/main/seo-geo/survey/competitor-analysis/SKILL.md) входят в Apache-2.0 repo с 2,612 stars/346 forks. Skills.sh показывает 937/787 installs. Репозиторий содержит generated machine contracts, eval cases и общие architecture/provenance tests; это сильнее prose-only skills, но не доказывает качество конкретного маркетингового результата.

**Procedure / egress / side effects.** Навыки маркируют метрики как Measured/User-provided/Estimated, требуют evidence для каждого вывода и задают явные completion/handoff contracts. Одновременно они предлагают unofficial Google Autocomplete helper, keyless Firecrawl connector и optional SEO/Search Console integrations, а результаты автоматически пишут в собственные `memory/` paths. Конкретный egress и credential model определяются подключённым connector, не самим skill.

**Output / Yandex / caveats.** `keyword-research` использует generic `Opportunity = (Volume × Intent Value) / Difficulty`; `competitor-analysis` требует SEO/backlink/traffic-share evidence. Ни один не знает Wordstat operators, Yandex regions, Direct search-query facts, Metrica goals или русскую морфологию. Для MOX-ADV полезны contracts, evidence labels и порядок исследования, но connectors, scoring и storage нельзя переносить без изменений.

### 4.10 `landing-page-conversion-audit`

**Identity / license / trust.** [`autonnel/autonnel-skills/landing-page-conversion-audit/SKILL.md`](https://github.com/autonnel/autonnel-skills/blob/main/landing-page-conversion-audit/SKILL.md), Apache-2.0 via parent repo; individual maintainer, 0 stars/0 forks, 21.1K marketplace installs ([repo API](https://api.github.com/repos/autonnel/autonnel-skills), [LICENSE](https://github.com/autonnel/autonnel-skills/blob/main/LICENSE), [marketplace](https://skills.sh/autonnel/autonnel-skills/landing-page-conversion-audit)). Install count is disproportionate to repository trust and not independently verifiable.

**Reproducibility / network / credentials.** Это только prompt Markdown без lockfile/runtime/tests. Он требует «fetch and read rendered DOM», но не объявляет browser tool, allowlist, credential model, consent или capture schema. Следовательно egress зависит от host agent: target page и её third parties; authenticated page may leak session through browser profile.

**Side effects / output.** Skill сам не содержит executable write, но рекомендует downstream Autonnel deployment and server-side tracking. Output shape хорошо ограничен: Verdict; до семи ranked fixes with effort/confidence; A/B tests; not-a-problem; could-not-check ([SKILL.md](https://github.com/autonnel/autonnel-skills/blob/main/landing-page-conversion-audit/SKILL.md)).

**Yandex / caveats.** Не упоминает `yclid` и Metrica goal evidence; measurement list ориентирован на Facebook/TikTok/Google/Bing. В тексте есть несосланные generic numeric claims (70–90% mobile, 10–30% loss) и promotional path к Autonnel. Нет тестов, schema или evidence provenance. Полезна только структура qualitative CRO review после замены measurement section официальными Yandex facts, Lighthouse и axe.

### 4.11 Anthropic `campaign-plan`

**Identity / license / reputation.** Официальный [`anthropics/knowledge-work-plugins/marketing/skills/campaign-plan/SKILL.md`](https://github.com/anthropics/knowledge-work-plugins/blob/main/marketing/skills/campaign-plan/SKILL.md), parent repo Apache-2.0, 23,587 stars/2,845 forks, skill 2.7K installs ([repo API](https://api.github.com/repos/anthropics/knowledge-work-plugins), [LICENSE](https://github.com/anthropics/knowledge-work-plugins/blob/main/LICENSE), [marketplace](https://skills.sh/anthropics/knowledge-work-plugins/campaign-plan)). Source reputation высокая.

**Reproducibility / egress / credentials.** Static prompt, поэтому deterministic execution не гарантируется model/version/context. Сам skill не требует credential и не выполняет writes, но предлагает использовать connected product analytics and repository connectors; фактический egress определяется host/connector, не skill. Для воспроизводимости нужно pin commit SHA and model/runtime, record inputs and final structured output.

**Output / side effects / Yandex.** Defines ten-section Markdown brief: overview, audience, messages, channel strategy, calendar, assets, metrics, budget, risks, next steps. Нет JSON Schema и Yandex-specific campaign contract; generic benchmark ranges/budget percentages не снабжены primary citations. Skill заканчивается вопросами дальнейшей генерации и упоминает stakeholder approvals, что нельзя автоматически переносить на MOX-ADV: routine safe synthesis remains agent-owned, а human gate нужен только для Critical Decision/Material Uncertainty ([SKILL.md](https://github.com/anthropics/knowledge-work-plugins/blob/main/marketing/skills/campaign-plan/SKILL.md), [`ADR-0001`](../adr/0001-agent-owns-safe-work.md)).

**Tests.** Отдельных executable tests для semantic quality/contract `campaign-plan` в source identity не найдено; repo popularity и official maintainer не заменяют validation на Yandex payload/readiness rules.

## 5. Proposed classification (recommendation, не evidence)

| Candidate | Класс | Почему / обязательная граница |
|---|---|---|
| Official Yandex API-first baseline | **ADOPT** | Единственный authoritative source для Wordstat/Direct/Metrica. Реализовать собственные allowlisted read adapters и canonical evidence envelopes; browser cabinets запрещены. |
| `askads/mcp-yandex-wordstat` | **ADAPT** | Переиспользовать mapping/retry/tests как reference implementation; pin 2.3.0+integrity, отключить telemetry, удалить `raw_request` и base override, добавить typed MOX envelope. Не давать Direct/Metrica token. |
| `SEOSiri-Official/keyword-cluster-mcp` | **REJECT** | Contract mismatches, misleading semantic/Parquet claims, 0 popularity, no lock, edge credential forwarding. Если нужна clustering logic — написать небольшую deterministic реализацию с русской morphology и golden tests. |
| Lighthouse | **ADOPT** | Pinned Node module/CLI in isolated audit harness at the accepted `1920×1080` desktop viewport; public/allowlisted landing URLs only; five sequential runs/median; JSON LHR stored as evidence. |
| axe-core | **ADOPT** | Pinned library in the same isolated `1920×1080` audit harness; retain all four result groups and manual-review flag; never claim compliance from automation alone. |
| OpenSEO whole app | **REFERENCE** | Architecture and tests useful, но app adds paid DataForSEO, optional OpenRouter/GSC, telemetry, auth/database/deploy surface and non-Yandex state. Do not integrate wholesale. |
| OpenSEO `keyword-research` / `competitor-analysis` | **REFERENCE** | Keep provider-bound tool orchestration, evidence/inference and local-vs-national guardrails as examples; do not port implicit project writes or the DataForSEO/GSC contract. |
| Aaron `keyword-research` / `competitor-analysis` | **ADAPT** | Use machine contracts, evidence labels and workflow skeleton; replace unofficial/third-party connectors, generic scoring and `memory/` writes with official Yandex sources and typed MOX evidence. |
| `landing-page-conversion-audit` | **REFERENCE** | Borrow compact ranked output only; low trust/disproportionate installs, no tests/tool contract, promotional and non-Yandex measurement advice prevent adoption. |
| Anthropic `campaign-plan` | **ADAPT** | Strong official source and useful brief skeleton; map to `Campaign Strategy`/`Campaign Draft`, remove uncited benchmarks/routine approvals, add typed Yandex-safe publish projection. |

## 6. Proposed MOX-ADV evidence contracts

### 6.1 Common envelope

```json
{
  "schema_version": "research-evidence-v1",
  "candidate": "official-yandex-wordstat|lighthouse|axe-core|...",
  "source_url": "https://...",
  "source_version": "api-version/package-version/commit",
  "observed_at": "RFC3339",
  "request_scope": {"account": null, "url": null, "region_ids": []},
  "credential_profile": "READ_ONLY_PROFILE_NAME_OR_NONE",
  "egress_hosts": ["allowlisted.example"],
  "raw_artifact_sha256": "...",
  "facts": [],
  "inferences": [],
  "warnings": [],
  "side_effects": []
}
```

### 6.2 Candidate-specific payloads

- **Wordstat:** phrase, exact operators, region/device/period, popular/related rows with counts, source method and folder billing attribution.
- **Direct/Metrica:** report type/fields/date/attribution/goal IDs, freshness window, raw TSV/JSON hash; never merge platform estimates with observed conversions.
- **Keyword cluster:** algorithm/version, normalization language, input keyword IDs, cluster IDs, similarity basis and deterministic golden-test hash. No marketing label such as “semantic” without an actual model/metric.
- **Lighthouse:** full LHR plus Chrome/Lighthouse versions, run settings and all run IDs; aggregate points to representative run rather than combining audits from different runs.
- **axe:** full `violations/incomplete/passes/inapplicable`, rule-set version and DOM/URL observation; `manual_review_required=true` whenever incomplete exists and generally for full WCAG assessment.
- **Skills:** generated Markdown may be retained as an inference artifact, but downstream decisions consume typed facts and explicit recommendation fields, not free-form prompt output.

## 7. Material risks and next validation

1. **HIGH — provider/schema drift.** Wordstat Cloud API is new, and third-party mapping may drift; add contract fixtures against official schemas before any adapter acceptance.
2. **HIGH — browser side effects/data exposure.** Lighthouse/axe harness navigation can fire analytics and load third parties; enforce URL/host allowlist, clean profile, no cabinet/admin pages, bounded artifacts and secret redaction.
3. **HIGH — third-party data conflation.** OpenSEO/DataForSEO/GSC estimates must never be labeled Yandex demand or campaign fact.
4. **MEDIUM — supply chain.** Pin package version, lockfile/integrity and commit; never use `npx -y` latest, Docker `latest`, `uv --github` HEAD, or unpinned skills in production research.
5. **MEDIUM — semantic validity.** Clustering needs a separate benchmark on Russian commercial queries, operators, inflection and stop-words. None of the reviewed candidates proves that quality.
6. **MEDIUM — marketplace counters.** Skills.sh installs lack a public unique-user/replay methodology in the reviewed primary page; retain them only as dated popularity signals.
7. **LOW — license integration.** Preserve Apache/MIT notices; for modified axe-core MPL-covered files comply with MPL-2.0 source obligations. Final legal review remains appropriate before redistribution.

## 8. Validation notes

- Read all four required local documents and ticket #96.
- Inspected official repository metadata, LICENSE/package/skill manifests, relevant source, test/CI files, package registries, marketplace pages and official Yandex API docs.
- No candidate was installed, executed or called; no credentials were used; no browser cabinet was accessed; no branch/commit/issue/PR was created.
- Единственный артефакт этой работы — `docs/research/p0-open-source-research-contour.md`; runtime сначала сохранил его как root `research.md`, после проверки файл перенесён в принятую `docs/research/` convention. Другие dirty-tree изменения не затрагивались.
- Residual uncertainty: package/marketplace popularity is a point-in-time counter; no live Yandex account capability or candidate runtime behavior was tested.
