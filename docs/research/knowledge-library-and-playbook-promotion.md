# Как хранить знания о гипотезах и повышать их до playbook

**Репозиторий:** ElJeskos/MOX-ADV  
**Тикет:** [Как хранить знания о гипотезах и повышать их до playbook?](https://github.com/ElJeskos/MOX-ADV/issues/64)  
**Статус:** исследовательская рекомендация; планирование/спецификация, не реализация  
**Нормативный локальный контекст:** [`CONTEXT.md`](../../CONTEXT.md), [`requirements-autonomous-campaign-operator.md`](../../requirements-autonomous-campaign-operator.md), [`hypothesis-lifecycle-and-learning.md`](hypothesis-lifecycle-and-learning.md) (решение #58), [`safe-campaign-experimentation.md`](safe-campaign-experimentation.md), [`autonomous-campaign-operator-cycle.md`](autonomous-campaign-operator-cycle.md)

## 1. Краткая рекомендация

MOX-ADV следует хранить не «список победителей», а **неизменяемый `KnowledgeClaimAggregate`**: стабильную identity утверждения и append-only цепочку версий, которая связывает исходное наблюдение, конкретную immutable-ревизию Hypothesis Preregistration, версию Campaign Effectiveness Profile (CEP) и causal context, зарегистрированный результат/disposition, границы применимости, causal status, репликации, противоречия и решения promotion/demotion. Старые факты и оценки не переписываются: новая информация создаёт новый evidence item, reassessment и новую materialized status-version с provenance.

Уровень знания и причинный статус должны быть независимы. Лестница — `OBSERVATION → LOCAL_RESULT → TRANSFER_CANDIDATE → TARGET_REPLICATED → PLAYBOOK_ELIGIBLE`; `CONTRADICTED`, `QUARANTINED` и `RETIRED` — ортогональные состояния пригодности, а не «нижние уровни». Наблюдаемая корреляция может продвигаться как полезный локальный сигнал, но никогда не получает causal status или causal playbook только из-за количества наблюдений.

Playbook — immutable rule revision, включённая по digest в immutable release manifest. Активация меняет только то, какие знания можно использовать для приоритизации и создания **draft** preregistration/typed proposal. Она никогда не меняет CEP, Gate 0, policy, Mandate, класс автономности или право на write: каждое применение снова проходит текущие target validation, policy, reservation, execution и readback.

## 2. Сначала факты из первичных источников

Ниже — внешние факты; схема и пороги в последующих разделах являются **предлагаемым решением MOX-ADV**, а не требованиями этих источников.

1. W3C PROV различает entity, activity и agent, связывает происхождение через generation, derivation, attribution и invalidation и допускает специализации/ревизии сущностей. Это даёт стандартный словарь для трассировки версии знания к данным, вычислению и субъекту решения. [W3C PROV-O](https://www.w3.org/TR/prov-o/) · [W3C PROV-DM](https://www.w3.org/TR/prov-dm/)
2. Регистрация OSF является timestamped read-only версией плана; при withdrawal содержимое удаляется, но остаётся tombstone с базовыми metadata и обоснованием отзыва. Это first-party registry precedent для immutable preregistration и видимого отзыва вместо переписывания истории. [OSF Registrations](https://help.osf.io/article/330-welcome-to-registrations) · [OSF Advanced Actions on Registrations](https://help.osf.io/article/113-advanced-actions-registrations)
3. Git идентифицирует содержимое объектов content-addressed hash и хранит commit как ссылку на tree, parent(s) и metadata. Это precedent для immutable revisions и release manifests, но не готовая бизнес-модель MOX-ADV. [Git — Git Objects](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects)
4. OCI image manifest/index ссылаются на компоненты descriptors с digest; digest проверяет загруженное содержимое. Это precedent для immutable manifest, pinning и проверяемого rollback на прежний digest. [OCI Image Manifest](https://github.com/opencontainers/image-spec/blob/main/manifest.md) · [OCI Descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)
5. Semantic Versioning определяет `MAJOR.MINOR.PATCH`, запрещает изменять содержимое опубликованной версии и требует выпускать новую версию для изменений. SemVer применим к совместимости playbook contract, но не выражает силу доказательства. [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html)
6. in-toto Attestation задаёт statement, связывающий immutable subject по digest с predicate и `predicateType`; authentication добавляется envelope-слоем. Это подходящий precedent для machine-verifiable promotion/release attestations. [in-toto Statement](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md) · [in-toto Attestation Framework](https://github.com/in-toto/attestation/blob/main/spec/README.md)
7. Google Ads рекомендует заранее определить hypothesis/success metrics, не менять несинхронно base и сохранять результаты; power зависит от объёма, variability, split, duration и ожидаемого uplift. [Google Ads Experiments](https://support.google.com/google-ads/answer/7281575?hl=en) · [Google Ads Campaign Guidance](https://support.google.com/google-ads/answer/15911255?hl=en)
8. Microsoft ExP трактует sample-ratio mismatch как сигнал проблемы assignment/pipeline и отделяет validity/safety alerts от эффекта treatment; cross-product A/B требует совместимых assignment/join/analysis данных. Это поддерживает отдельные validity, causal и applicability dimensions. [Microsoft ExP — Alerting](https://www.microsoft.com/en-us/research/articles/alerting-in-microsofts-experimentation-platform-exp/) · [Microsoft — A/B Testing Across Products](https://www.microsoft.com/en-us/research/articles/a-b-testing-across-products/)
9. Direct предупреждает, что статистика обычно стабилизируется в течение нескольких дней и может исправляться ретроспективно. Поэтому knowledge status должен зависеть от pinned data revision и уметь переоцениваться без переписывания исходного результата. [Yandex Direct — Updated statistics](https://yandex.com/dev/direct/doc/en/actual)

## 3. Предлагаемое решение MOX-ADV

### 3.1. Канонический persisted aggregate

**Aggregate root:** `KnowledgeClaimAggregate`.

**Стабильная identity утверждения (`claim_id`)** вычисляется из канонического смыслового ключа:

```text
mechanism
× treatment_contrast
× estimand_and_primary_outcome
× comparator_class
× eligible_population_class
× causal_context_signature
× measurement_regime_class
```

Изменение механизма, contrast, estimand или outcome создаёт новый `claim_id`. Уточнение scope/effect modifiers, добавление репликации, новая версия данных или новый engine создают новую `claim_version`, но не меняют предыдущие версии. Конкретная проверка имеет отдельную `hypothesis_revision_id`; конкретный результат — `result_id`; материализованная оценка знания — `assessment_id`; правило — `rule_revision_id`; release — `playbook_release_id` и content digest.

Минимальная схема:

| Группа | Обязательные поля |
|---|---|
| Identity | `claim_id`, `claim_version`, `canonical_claim_text`, `mechanism_id`, `created_at`, `supersedes_claim_version?`, `content_digest` |
| Observation | `observation_id`, immutable facts/signal, campaign/account scope, `as_of`, data-quality/maturity labels, source snapshot IDs/digests; всегда `causal_status=NONE|ASSOCIATIONAL` |
| Hypothesis | `hypothesis_revision_id`, `preregistration_digest`, treatment/comparator, estimand, assignment/analysis unit, primary metric/MDE, guardrails, stopping/invalidation/maturity rules, registration timestamp |
| Context | `source_campaign_id`, immutable `cep_revision_id`, objective/conversion/attribution regime, audience/geo/channel/inventory/device, bidding/budget regime, season/external events, declared effect modifiers, context fingerprint |
| Authority snapshots | `mandate_revision_id`, `gate0_revision_id`, `policy_revision_id`, `statistical_decision_policy_id`; только provenance, не наследуемое разрешение |
| Result | `result_id`, locked dataset digest/watermarks, engine/code/config versions, effect + interval/CS, precision/power, primary/guardrail outcomes, validity checks, deviations, maturity, disposition (`RETAINED`, `REJECTED`, `INSUFFICIENT_DATA`, `INVALIDATED`, `UNSAFE`) и reason |
| Evidence classification | `evidence_level`, отдельный `causal_status`, `validity_status`, `applicability_scope`, supported/unsupported contexts, transport assumptions, heterogeneity assessment |
| Relations | `derived_from`, `replicates`, `contradicts`, `refines`, `supersedes_assessment`, `invalidates`, `source_evidence_ids` |
| Governance | machine evaluation, `promotion_decision_id`, promoter/demoter actor or service identity, rule/policy version, reason codes, timestamp, signature/attestation |
| Current projection | `assessment_id`, `knowledge_state`, `active_for_suggestion`, `reassessment_due`, reason; это пересоздаваемая проекция, не источник истории |
| Audit | append-only events, previous-event digest, request/correlation IDs, actor, inputs/outputs and hashes |

**Инварианты identity:**

- `Observation`, `HypothesisPreregistrationRevision`, `CEPRevision`, `ExperimentResult` и `Assessment` — разные immutable entities; aggregate связывает, но не сливает их.
- Один result ссылается ровно на одну preregistration revision, один frozen protocol digest, один locked dataset revision и один engine bundle.
- CEP/policy/Mandate после теста не подставляются задним числом. Новые версии вызывают reassessment применимости/совместимости.
- Materialized «current level» можно перестроить из событий; удалить отрицательный результат или contradiction нельзя.

### 3.2. Evidence vocabulary: две оси вместо одного вводящего в заблуждение score

#### Уровень переносимости/повторяемости

| Уровень | Значение | Что разрешает |
|---|---|---|
| `E0 OBSERVATION` | Наблюдение, after-change association, diagnostic или exploratory signal | Диагностика и draft новой hypothesis; не causal language |
| `E1 LOCAL_RESULT` | Завершённый scoped result любой disposition с зафиксированными validity/context | Локальное знание; retained result может влиять на ranking/forecast |
| `E2 TRANSFER_CANDIDATE` | Валидный `RETAINED` causal result, правдоподобный механизм, declared effect modifiers и target-eligibility predicate | Только preregistered target validation; не auto-apply |
| `E3 TARGET_REPLICATED` | Независимая валидная target replication поддержала claim в заранее объявленном target context; source и target effects совместимы с frozen heterogeneity rule | Использование в подтверждённых source/target scopes; план следующей репликации |
| `E4 PLAYBOOK_ELIGIBLE` | Claim повторен по заранее объявленной replication matrix, включая минимально необходимые context strata, без unresolved material contradiction; machine-reproducible applicability predicate существует | Включение rule revision в candidate release; не write authority |

#### Причинный статус (обязательное независимое поле)

`NONE → ASSOCIATIONAL → QUASI_EXPERIMENTAL → RANDOMIZED_CAUSAL_LOCAL → RANDOMIZED_CAUSAL_REPLICATED`.

Только валидный design соответствующего класса может изменить causal status. Количество корреляционных наблюдений, прогнозная точность, human approval или включение в release не повышают его до causal. `QUASI_EXPERIMENTAL` не может породить causal transfer/playbook rule без независимой randomized replication; оно может породить только явно маркированную operational heuristic для предложения проверки.

#### Состояние пригодности

`ACTIVE | STALE | QUARANTINED | CONTRADICTED | RETIRED`.

Оно ортогонально evidence level: например, бывший `E4` может стать `CONTRADICTED`, сохранив исторический уровень и причины прошлой promotion. `RETIRED` означает «не использовать для новых предложений», а не «ложно» и не удаляет историю.

### 3.3. Переходы, guards и authority

| From → To/state | Механические guards | Кто/что принимает решение |
|---|---|---|
| — → `E0` | Provenance, scope, `as_of`, data quality/maturity записаны; causal label не выше `ASSOCIATIONAL` | Deterministic ingestion/validation service |
| `E0` → `E1` | Есть immutable preregistration/result envelope и terminal disposition; result связан с locked data/engine/context | Statistical evaluator; модель не голосует |
| `E1 RETAINED` → `E2` | `validity=PASS`; `causal_status=RANDOMIZED_CAUSAL_LOCAL`; primary success и guardrails допустимы; mechanism/effect modifiers/applicability и target predicate полны; нет unresolved contradiction | Deterministic Knowledge Evaluator по versioned Promotion Policy; attestation записывается автоматически |
| `E2` → `E3` | Новая preregistered target revision; target не является повторным анализом source data; mature valid result retained; frozen replication/heterogeneity rule выполнен | Statistical evaluator выпускает result; Knowledge Evaluator проверяет promotion |
| `E3` → `E4` | Выполнена заранее опубликованная replication matrix: требуемое число независимых campaigns/contexts и critical strata задаются Promotion Policy, а не подбираются после результатов; каждый result causal-valid; нет material unresolved contradiction; applicability predicate testable | Knowledge Evaluator формирует candidate; **Knowledge Steward** утверждает eligibility attestation |
| `E4` → active playbook rule | Immutable rule revision и release manifest прошли schema/lint/scenario/reproducibility/compatibility checks; все evidence digests доступны; human approval записан | Knowledge Steward активирует release; runtime только переключает signed active pointer |
| Любой → `QUARANTINED` | Source retracted/invalidated; data/engine bug; digest/provenance missing; policy/profile incompatibility влияет на безопасное использование; reassessment pending | Deterministic dependency monitor, fail-closed |
| Любой → `CONTRADICTED` | Валидное новое causal evidence по overlapping applicability scope пересекает frozen contradiction boundary; это отдельный result, не простое `p>0.05` | Statistical evaluator + Knowledge Evaluator; human adjudication только при несовместимых scopes/estimands |
| Любой → `STALE` | CEP/context/measurement/data/policy/engine compatibility predicate больше не подтверждён, но falsification не установлена | Dependency monitor |
| Любой → `RETIRED` | Claim obsolete, superseded, prohibited или больше не operationally meaningful; reason обязателен | Knowledge Steward; автоматический hard-policy conflict сначала `QUARANTINED`, затем steward review |
| `QUARANTINED/STALE` → предыдущий active state | Причина закрыта, все affected assessments детерминированно пересчитаны на pinned исправленных inputs, checks пройдены | Dependency monitor + Knowledge Evaluator; release activation всё равно Steward |

**Guarded promotion monotonic only in history, not in current use.** Старый promotion event неизменяем; новая assessment-version может понизить current state. Никакое понижение не стирает evidence и не превращает `INVALIDATED` в `REJECTED`.

## 4. Contradiction и механические основания для repeat

### 4.1. Contradiction

Contradiction создаётся как relation между двумя result envelopes и содержит overlapping scope, одинаковость/различие estimand, direction/practical-effect boundary, validity и возможные effect modifiers.

- Валидный opposite/no-go causal result в пересекающемся scope → `CONTRADICTED`, affected rules немедленно `QUARANTINED`, новые применения запрещены.
- Несовпадение в другом заранее объяснимом context → не глобальное опровержение; scope делится, claim/rule получает новую revision и более узкий applicability predicate.
- `INSUFFICIENT_DATA` не противоречит claim.
- `INVALIDATED` не является отрицательным evidence.
- `UNSAFE` противоречит пригодности treatment в данном safety context независимо от primary success и блокирует promotion.
- Observational association противоположного знака создаёт reassessment signal, но само не демотирует causal claim; оно может вызвать targeted replication.

### 4.2. Repeat допускается только при истинном `NoveltyBasis`

Новая hypothesis revision после `REJECTED`, `INSUFFICIENT_DATA`, `INVALIDATED` или `UNSAFE` обязана содержать один или несколько кодов, immutable evidence refs и machine-checkable changed fields:

1. `IDENTIFICATION_DEFECT_FIXED` — закрыта root cause assignment/SRM, join, contamination, collision или tracking failure.
2. `PRECISION_FEASIBILITY_CHANGED` — после `INSUFFICIENT_DATA` документированно вырос eligible traffic/window или снизилась variance; новый power calculation достижим.
3. `MECHANISM_CHANGED` — изменён causal mechanism или material treatment contrast; diff не пуст.
4. `TARGET_CONTEXT_CHANGED` — новый target и заранее указанный effect modifier; это target validation, не стирание source result.
5. `EXTERNAL_REGIME_CHANGED` — проверяемо изменились conversion definition, attribution regime, product/price/landing, platform capability или auction regime, участвующие в механизме.
6. `INDEPENDENT_CAUSAL_CONTRADICTION` — появилось независимое валидное causal evidence и заранее сформулирована heterogeneity hypothesis.
7. `ESTIMAND_OR_BUSINESS_DECISION_CHANGED` — активирована новая human-approved CEP revision; старый result остаётся связан со старым estimand.
8. `SAFETY_HAZARD_FIXED` — после `UNSAFE` подтверждены containment/mitigation и текущая authorization; hard limit не ослабляется автоматически.
9. `ENGINE_OR_DATA_DEFECT_FIXED` — affected result был quarantined/invalidated, fix version и reproducibility check записаны.

Недостаточно: прошло время; изменился prompt/seed; добавили budget после powered `REJECTED`; нашли post-hoc metric/segment; сменили stopping rule после просмотра; объявили «рынок другой» без modifier; ослабили policy/guardrail; повторили идентичный treatment в идентичном scope. Повтор создаёт новую preregistration revision и никогда не изменяет прошлый disposition.

## 5. Playbook/rule library: release, versioning, activation и rollback

### 5.1. Объекты

`RuleRevision` immutable и содержит:

- `rule_id`, SemVer и content digest;
- human-readable mechanism/intent;
- required minimum evidence/causal status;
- exact applicability predicate и required target facts;
- proposal template и preregistration defaults, но не готовый API write;
- mandatory exclusions, contraindications, guardrails, required target validation/ramp;
- evidence/result/assessment digests;
- compatible CEP schema, Statistical Decision Policy, Gate 0/policy schema и runtime contract ranges;
- owner, created/approved timestamps, supersedes relation.

`PlaybookReleaseManifest` immutable и content-addressed: release SemVer, ordered set of exact `rule_revision_id@digest`, required evaluator/runtime schema versions, source evidence digests, checks, approval attestation and previous release digest.

### 5.2. Версии

- **PATCH:** только editorial/non-semantic metadata; executable predicate/template digest не меняется. Если меняется machine behavior — это не PATCH.
- **MINOR:** backward-compatible добавление rule или сужение безопасной применимости/default validation; всё равно новая immutable revision/release.
- **MAJOR:** несовместимое изменение rule schema, semantics, applicability interpretation или удаление/замена contract.
- Evidence level и confidence не кодируются в SemVer; они остаются typed assessment fields.

### 5.3. Lifecycle и atomic activation

`DRAFT → CANDIDATE → APPROVED → ACTIVE → DEPRECATED | WITHDRAWN`.

1. Knowledge Evaluator создаёт candidate manifest.
2. Deterministic checks воспроизводят assessments из pinned evidence, проверяют digests, schema, predicates, отсутствие quarantined dependencies и обязательные сценарии.
3. Knowledge Steward подписывает approval с reason/scope.
4. Runtime атомарно меняет `active_release_pointer` на exact digest и пишет activation event.
5. In-flight proposal/workflow не получает новую rule молча: он остаётся pinned к старому digest и перед следующим write заново проходит current policy/profile/mandate checks; несовместимость отменяет старое разрешение.

### 5.4. Rollback

Rollback — новый audit event, который атомарно указывает active pointer на ранее **уже утверждённый** manifest digest. Он не удаляет bad release и не откатывает фактические campaign writes. Если rule уже породил action plans, каждый затронутый plan/experiment проходит отдельную dependency evaluation; фактическая компенсация остаётся новым policy-checked write по runtime-решению.

Автоматический rollback active release допустим только при failed integrity/signature/schema/runtime-compatibility check или newly quarantined dependency; это fail-closed техническая операция на предыдущий approved digest. Содержательный спор/contradiction переводит release/rule в `QUARANTINED`, запрещает новые uses и требует Steward решения о revised release.

## 6. Reassessment при изменении зависимостей

| Изменение | Поведение |
|---|---|
| Data revised/late | Новый immutable data revision; dependency index находит results. Original result/Decision Record не меняется. Recompute создаёт новый assessment; до него affected knowledge/rules `QUARANTINED`, если revision пересекает registered dataset или maturity/decision boundary. |
| Statistical engine/code/config | Любая версия/bug связывается с точным bundle digest. Bug impact query перечисляет affected results; они quarantined, воспроизводятся исправленной версией, после чего создаются superseding assessments. Старые outputs остаются audit facts. |
| CEP revision | Не пересчитывать старый estimand как будто он был предзарегистрирован. Applicability к активной кампании становится `STALE`; нужен новый target assessment/preregistration. Изменение цели — критическое human decision по локальным требованиям. |
| Gate 0/policy/Mandate | Knowledge truth не переписывается. Compatibility текущего use пересчитывается; conflict немедленно запрещает suggestion/use. Evidence никогда не ослабляет boundary и не создаёт Mandate. Mandate не является долговременной зависимостью truth, только provenance прошлой authorization. |
| Measurement/attribution/source schema | Context fingerprint меняется; affected claims stale/quarantined до comparability check. Несопоставимые режимы нельзя агрегировать как replication. |
| Source evidence withdrawn/invalidated | Сохранить withdrawal/invalidation relation и provenance; все зависимые assessments/rules quarantined. Если support остаётся достаточным по Promotion Policy, новая assessment может восстановить уровень без withdrawn item; иначе demote. |
| New contradicting evidence | Создать contradiction edge, пересчитать overlapping applicability. Affected active release fail-closed для новых suggestions; split scope или retirement только новой rule revision/release. |

## 7. Непереходимая граница полномочий

**Инвариант:** evidence, evidence level, KnowledgeClaim, RuleRevision и PlaybookRelease никогда напрямую не изменяют и не расширяют:

- Mandate, его budget/quota/TTL или action classes;
- Gate 0 Boundary;
- protective/statistical policy;
- Campaign Effectiveness Profile;
- autonomy level;
- campaign settings, execution authority или API credentials.

Допустимый поток только такой:

```text
active knowledge/rule
  → rank candidate / draft hypothesis / draft preregistration / typed proposal
  → current target data + active CEP
  → target validation as required
  → current Gate 0 + policy + active Mandate
  → reservation → execution → readback → audit
```

Даже `E4 + ACTIVE playbook` означает «правило можно предложить в указанном scope», а не «правило разрешено выполнить». Harm evidence может запустить только уже заранее разрешённый safety pause/rollback; новое durable prohibition или любое ослабление остаётся отдельной policy revision.

## 8. Проверки и сценарии приёмки решения

| Сценарий | Ожидаемый результат |
|---|---|
| CPA после ручной правки улучшился | `E0 ASSOCIATIONAL`; можно draft hypothesis, нельзя causal promotion |
| Валидный randomized local test retained | `E1 RANDOMIZED_CAUSAL_LOCAL`; при заполненных transport guards — `E2`, но target write не разрешён |
| Десять похожих before/after наблюдений | Остаются associational; количество не создаёт causal status |
| Target replication retained в заранее объявленном context | `E3`; source и target envelopes сохраняются отдельно |
| Post-hoc удачные сегменты создают «replication matrix» | Promotion запрещён; matrix/strata должны быть frozen до confirmatory replications |
| Валидная target replication противоположна source | Contradiction edge; overlapping rule quarantined; проверить modifier/split scope, не удалять source |
| Result invalidated из-за SRM | Не contradiction и не rejection; repeat только `IDENTIFICATION_DEFECT_FIXED` |
| Powered rejected test просто получает больший budget | Repeat запрещён без нового mechanism/context/independent causal evidence |
| Поздние данные изменили effect через decision boundary | Новый assessment; dependent rule quarantined/possibly demoted; старый result audit сохранён |
| Найден баг engine | Все results по bundle digest найдены и quarantined; rerun создаёт superseding assessments |
| CEP сменил primary outcome | Старое знание исторически валидно в старом context, но stale для нового target; новая preregistration |
| Policy стала строже | Rule truth не переписана, но compatibility false и новые uses запрещены |
| Серия побед предлагает увеличить Mandate | Запрет: только critical human authority process может изменить Mandate |
| Bad playbook release активирован | Pointer возвращается на previous approved digest; bad release и activation/rollback events остаются |
| In-flight plan pinned к rolled-back rule | Не переписывать plan; до write обязательна current revalidation, несовместимый plan отменяется |

Минимальные specification checks будущей реализации: schema and digest validation; append-only mutation rejection; deterministic replay of assessment; dependency impact query; causal/level cross-field constraints; novelty predicate tests; promotion guard tests; contradiction overlap tests; signed release manifest verification; atomic pointer swap/rollback; stale in-flight plan revalidation; no-direct-authority property test.

## 9. Claim-to-source matrix

| Claim ID | С sourced fact | Direct source | Использование в предлагаемом решении |
|---|---|---|---|
| S1 | Provenance связывает entities, activities, agents, derivation/revision/invalidation | [W3C PROV-O](https://www.w3.org/TR/prov-o/) · [PROV-DM](https://www.w3.org/TR/prov-dm/) | Typed entities/relations и actor/service audit |
| S2 | Preregistration is timestamped/read-only; withdrawal removes content but preserves a visible metadata tombstone and justification | [OSF Registrations](https://help.osf.io/article/330-welcome-to-registrations) · [Advanced Actions](https://help.osf.io/article/113-advanced-actions-registrations) | Immutable preregistration and visible retire/withdraw history |
| S3 | Content-addressed objects/commits preserve exact content and ancestry | [Git Objects](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects) | Digests, immutable revisions, ancestry |
| S4 | Manifest descriptors pin components by digest | [OCI Manifest](https://github.com/opencontainers/image-spec/blob/main/manifest.md) · [Descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md) | Playbook release manifest and exact rollback target |
| S5 | Published SemVer version contents are immutable; changes require new version | [SemVer 2.0.0](https://semver.org/spec/v2.0.0.html) | Rule/release compatibility versioning |
| S6 | Attestation statements bind digest-named subjects to typed predicates; envelopes provide authentication | [in-toto Statement](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md) · [Framework](https://github.com/in-toto/attestation/blob/main/spec/README.md) | Promotion/release attestation |
| S7 | Experiment hypothesis/metrics should be set before test; power depends on design/data | [Google Experiments](https://support.google.com/google-ads/answer/7281575?hl=en) · [Campaign Guidance](https://support.google.com/google-ads/answer/15911255?hl=en) | Preregistration/result envelope; no universal replication count in this ticket |
| S8 | SRM/pipeline validity and cross-context assignment/join compatibility are separate concerns from outcome | [Microsoft Alerting](https://www.microsoft.com/en-us/research/articles/alerting-in-microsofts-experimentation-platform-exp/) · [Cross-product A/B](https://www.microsoft.com/en-us/research/articles/a-b-testing-across-products/) | Separate validity, causal status and applicability |
| S9 | Direct statistics may stabilize and be revised retrospectively | [Yandex Direct updated statistics](https://yandex.com/dev/direct/doc/en/actual) | Data revision dependency and reassessment |

**Не sourced, а product proposal MOX-ADV:** название aggregate; точные поля и identities; уровни `E0–E4`; роли Knowledge Evaluator/Knowledge Steward; promotion/demotion guards; contradiction boundary; rule/release lifecycle; SemVer interpretation; automatic quarantine/rollback policy. Они должны оцениваться как проектное решение, а не как следствие стандарта.

## 10. Существенный новый продуктовый выбор

Выявлен один действительно новый выбор, который нельзя скрыть в реализации:

> **Кто имеет право активировать и содержательно демотировать playbook release?**

Рекомендованный безопасный default: deterministic Knowledge Evaluator автоматически вычисляет уровни, quarantine и candidate manifest, но named human **Knowledge Steward** утверждает `E4` eligibility и каждую activation/retirement/revised release; технический integrity rollback может быть автоматическим только на предыдущий approved digest. Это не изменение Campaign Effectiveness Profile и не расширение Mandate, однако active library влияет на поток автономно создаваемых гипотез, поэтому silent fully-automatic activation создаёт новый product-governance риск.

Роль, SLA и возможность делегировать approval по low-risk rule classes требуют отдельного утверждения владельца продукта. До него система должна работать fail-closed: candidate knowledge доступно для review/target testing, но новый release не становится active автоматически.

Порог `E4` (число независимых campaigns, обязательные strata и heterogeneity boundary) **не является универсальной константой**. Его должен задавать versioned Promotion Policy по rule family/risk class и проверять deterministic evaluator; произвольное число в этом документе было бы ложной точностью.

## 11. Уверенность и пробелы

**Высокая уверенность:** immutable preregistration/result/provenance; разделение evidence level, causal status и usability state; target replication до playbook; append-only contradiction/demotion; digest-pinned releases; no-direct-authority invariant; reassessment вместо переписывания истории.

**Средне-высокая:** предложенная `E0–E4` лестница и aggregate boundary согласуются с локальными решениями и первичными provenance/experimentation precedents, но являются доменной конструкцией MOX-ADV, а не внешним стандартом.

**Средняя:** Knowledge Steward approval boundary и SemVer rules. Это рекомендуемый governance design, требующий product confirmation.

**Пробелы/следующие решения:**

1. Product owner должен утвердить Knowledge Steward role/delegation и activation SLA.
2. Promotion Policy должна определить risk-class-specific replication matrix, independence, heterogeneity/contradiction thresholds и минимальные context strata; универсальные числа источниками не подтверждаются.
3. Нужен отдельный implementation design для durable store, signatures/keys, append-only enforcement, dependency index и retention; этот документ намеренно не выбирает БД или event platform.
4. Нужен capability check фактических Yandex experiment primitives и доступных assignment-level данных; без проверяемого assignment causal promotion остаётся запрещённым.
5. Следует формально определить stable identifiers/privacy retention для audience/context fingerprints до реализации.

## 12. Источники: kept/dropped

### Kept

- [W3C PROV-O](https://www.w3.org/TR/prov-o/) и [PROV-DM](https://www.w3.org/TR/prov-dm/) — стандарт provenance, revision и invalidation.
- [OSF Registrations](https://help.osf.io/article/330-welcome-to-registrations) и [Advanced Actions](https://help.osf.io/article/113-advanced-actions-registrations) — first-party registry behavior для read-only preregistration и видимого withdrawal tombstone.
- [Git Objects](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects), [OCI Image Spec](https://github.com/opencontainers/image-spec), [SemVer](https://semver.org/spec/v2.0.0.html), [in-toto Attestation](https://github.com/in-toto/attestation/blob/main/spec/README.md) — официальные specifications/materials для immutable content, manifests, versions и attestations.
- Официальная Google Ads experimentation documentation — preregistration/design/power precedent.
- First-party Microsoft experimentation research — validity и cross-context evidence.
- Официальная Yandex Direct documentation — retrospective data revision.

### Dropped

- Блоги о «лучших knowledge bases», vendor comparisons и SEO-материалы — не первичные источники и не нужны для решения.
- Универсальные evidence pyramids из evidence-based medicine — population/intervention и publication model не совпадают с рекламным online experimentation; уровни MOX-ADV должны быть явно доменными.
- Произвольные правила «три успешных теста = playbook» — нет доверенного универсального основания; threshold зависит от риска, contexts, precision и heterogeneity.
- Database/event-sourcing product documentation — преждевременно для planning decision и могло бы молча превратить спецификацию в implementation choice.
