# Fan-out Campaign Strategy → Campaign Drafts и MVP-возможности Yandex Direct API v5

**Wayfinder:** [«Определить fan-out Strategy → Campaign Drafts и MVP-набор возможностей Директа»](https://github.com/ElJeskos/MOX-ADV/issues/94), часть карты [«Развитие P0 „Стратегия и создание кампании“: карта нерешённых решений»](https://github.com/ElJeskos/MOX-ADV/issues/89)  
**Режим:** research/decision contract; первичные внешние источники, принятые локальные контракты и read-only preflight подключённого аккаунта через официальный Direct API; browser cabinet не использовался.  
**Канонический артефакт:** `docs/research/campaign-draft-fan-out-and-direct-mvp.md`.

## 1. Короткое решение

Одна утверждённая immutable-ревизия `CampaignStrategyRevision` должна сначала породить конечный ledger leaf-кандидатов по осям `product × audience × offer × keyword_cluster`, затем **свернуть совместимые keyword clusters по уже принятому `delivery_key`**, и только после этого выпустить для каждого delivery bucket один control и не более двух однофакторных improvement-вариантов. Keyword cluster участвует в покрытии и объяснении, но сам по себе не создаёт кампанию: один `CampaignDraft` остаётся ровно одной будущей кампанией.

Control — наблюдаемая конкурентная норма только при достаточном первичном evidence; иначе честно маркированный `STRATEGY_BASELINE_FALLBACK`. Improvement — versioned Operational Hypothesis с одним материальным отличием от control, а не произвольная комбинация «всего лучшего». Каждая leaf-комбинация получает terminal disposition; рекурсивная генерация запрещена; одинаковые publish projections удаляются по fingerprint; слабые варианты скрываются, но не исчезают из audit.

Минимальный честно сравнимый Direct-профиль — только `UNIFIED_CAMPAIGN` v501, `UNIFIED_AD_GROUP`, search-only `WB_MAXIMUM_CLICKS`, Network `SERVING_OFF`, явные keywords, `TextAd` и, когда есть реальные релевантные назначения, одинаковый набор sitelinks. Autotargeting и дополнительные placements допускаются только как **conditional capability hypotheses** после account/sandbox preflight и в отдельных Drafts; conversion strategies, Network, portfolio strategies, responsive/image/video/shopping ads и смешение разных стратегий из MVP comparison исключаются. Любой выбранный Draft публикуется точной, хешированной object-graph projection и после `Campaigns.add` безусловно переводится в `SUSPENDED` до дочерних writes; `resume` отсутствует.

---

## 2. Нормативная база и уже принятые инварианты

### 2.1. Локальные решения, которые этот ticket не переоткрывает

1. `CONTEXT.md` определяет Campaign Strategy как утверждённую бизнес-конфигурацию, Recommendation Set — как объяснимый результат для одной Strategy и одного evidence snapshot, а Campaign Draft — как редактируемую проекцию **ровно одной реальной кампании** и поддерживаемых child objects.
2. Карта [«Развитие P0 „Стратегия и создание кампании“: карта нерешённых решений»](https://github.com/ElJeskos/MOX-ADV/issues/89) фиксирует пять шагов `Контекст → Модель → Strategy → Draft → Подтверждение`, shortlist пакета, независимое создание элементов пакета, отдельность blockers от score и non-serving финал.
3. [`docs/research/wordstat-cost-and-long-tail-packing.md`](wordstat-cost-and-long-tail-packing.md) уже принял:
   - `semantic_key = product/service × audience_need × intent × offer`;
   - `delivery_key = primary_goal × economics_profile × geography × landing_page × core_message × management_profile`;
   - одинаковый `delivery_key` обязан паковаться;
   - `KeywordsResearch.deduplicate` применяется до forecast/publish;
   - low-frequency compatible clusters не дробят бюджет и не порождают кампании.
4. [`docs/research/landing-page-advisory-analysis-contract.md`](landing-page-advisory-analysis-contract.md) делает landing audit advisory-only: он не блокирует Draft и не уменьшает viability score.
5. [`docs/research/p0-open-source-research-contour.md`](p0-open-source-research-contour.md) принимает official Yandex API-first boundary; браузерные кабинеты Direct/Metrica запрещены.
6. [`docs/research/knowledge-library-and-playbook-promotion.md`](knowledge-library-and-playbook-promotion.md) требует immutable hypotheses/evidence, scoped playbook use и запрещает знаниям расширять Mandate/authority.
7. Ticket [«Определить fan-out Strategy → Campaign Drafts и MVP-набор возможностей Директа»](https://github.com/ElJeskos/MOX-ADV/issues/94) прямо запрещает переоткрывать `one Draft = one campaign; one Strategy = many Drafts`.

### 2.2. Текущий production-кандидат — что уже есть и чего нет

Прочитаны `sites/p0-production/app/P0Client.tsx`, `lib/p0.ts`, `lib/campaign-draft.ts`, `lib/direct-write.ts`, `lib/direct-limits.ts`, `lib/ad-copy.ts` и API route.

| Severity | Наблюдение в текущем коде | Следствие для fan-out ticket |
|---|---|---|
| **BLOCKER** | `P0Document` содержит одиночные `strategy`, `draft`, `campaign`; `DraftStep` редактирует одну phrase, одну group и одно ad (`sites/p0-production/app/P0Client.tsx`, `sites/p0-production/lib/p0.ts`). | Нет Recommendation Set, canvas, shortlist, package confirmation и per-Draft result.
| **BLOCKER** | `DirectProjection` поддерживает ровно один `ad_group`, `keyword`, `ad`; sitelinks/autotargeting и массивы child objects отсутствуют (`sites/p0-production/lib/direct-write.ts`). | Exact projection не может выразить принятый fan-out/packing contract.
| **BLOCKER** | `ensureNonServing` принимает `State=OFF` как достаточный барьер и не вызывает `Campaigns.suspend`; explicit `SUSPENDED` обеспечивается лишь после `Ads.moderate` (`sites/p0-production/lib/direct-write.ts`). | Это слабее принятого контракта `add → suspend → readback SUSPENDED` **до** child writes и оставляет ненужное окно риска.
| **HIGH** | Strategy и Draft имеют только общий D1 `revision`; собственных immutable `strategy_revision_id`, `draft_revision_id`, input fingerprints и lineage нет (`sites/p0-production/lib/p0.ts`). | Нельзя доказать, из какой Strategy/evidence revision получен опубликованный Draft.
| **HIGH** | Deduplication кампаний — только case-insensitive campaign name; object-graph/publish fingerprint отсутствует (`sites/p0-production/lib/campaign-draft.ts`, `lib/p0.ts`). | Одинаковый payload под разными именами может быть создан дважды.
| **HIGH** | `buildPublishProjection` жёстко мапит три geography labels и генерирует `BidCeiling` как `weeklyBudget/100`; это локальная эвристика без связи с hypothesis/evidence (`sites/p0-production/lib/campaign-draft.ts`). | Fan-out обязан хранить источник каждого технического default и не выдавать эвристику за Strategy fact.
| **MEDIUM** | Текущий профиль уже правильно использует `UNIFIED_CAMPAIGN`, `UNIFIED_AD_GROUP`, `WB_MAXIMUM_CLICKS`, `SERVING_OFF`, explicit keyword, `TextAd`, micros и currency-dictionary minimum. | Это подходящий baseline substrate, но не готовый multi-Draft contract.
| **MEDIUM** | `save_strategy` обнуляет Draft, а business-model change обнуляет Strategy/Draft. | Fail-closed invalidation уже частично присутствует, но должна стать явной revision semantics, а не удалением lineage.

---

## 3. Что официально позволяет Direct API v5/v501

Этот раздел содержит **факты документации**, а не продуктовые решения MOX-ADV.

### 3.1. Campaign и placements

- Для unified performance campaign используется v501; `Campaigns.add` принимает common fields и `UnifiedCampaign`. Search и Network strategies задаются отдельно. [Campaigns.add](https://yandex.com/dev/direct/doc/en/campaigns/add) · [UnifiedCampaign add](https://yandex.com/dev/direct/doc/en/campaigns/add-unified-campaign)
- Для Search документированы `SearchResults`, `ProductGallery`, `DynamicPlaces`, `Maps`, `SearchOrganizationList`; для Network — `Network`, `Maps`. При создании campaign `DynamicPlaces` получает значение `SearchResults`; независимое управление обещано в будущем. [UnifiedCampaign add](https://yandex.com/dev/direct/doc/en/campaigns/add-unified-campaign)
- `WB_MAXIMUM_CLICKS` поддерживает weekly budget и optional bid ceiling; деньги передаются в currency × 1,000,000, а минимум нужно читать из Dictionaries/Currencies. Search `WB_MAXIMUM_CLICKS` совместим с Network `SERVING_OFF`. [UnifiedCampaign add](https://yandex.com/dev/direct/doc/en/campaigns/add-unified-campaign) · [strategy compatibility](https://yandex.com/dev/direct/doc/en/objects/campaign-strategies)
- Conversion-oriented `WB_MAXIMUM_CONVERSION_RATE`, `AVERAGE_CPA`, `PAY_FOR_CONVERSION`, CRR и related strategies документированы, но страница совместимости отдельно предупреждает, что часть таких стратегий включается только при выполнении условий. [strategy compatibility](https://yandex.com/dev/direct/doc/en/objects/campaign-strategies)
- `Campaigns.add` не имеет поля «создать сразу suspended». После approval и funding показы могут начаться не ранее StartDate; официальный stop — `Campaigns.suspend`, restart — `resume`. [launch guide](https://yandex.com/dev/direct/doc/en/best-practice/launch-campaign) · [Campaigns.suspend](https://yandex.com/dev/direct/doc/en/campaigns/suspend)

### 3.2. Groups, keywords и autotargeting

- Тип child group обязан соответствовать campaign; тип группы после создания не меняется. Для unified campaign используется `UNIFIED_AD_GROUP` и v501. Limits читаются из `Clients.get.Restrictions`. [Ad group object](https://yandex.com/dev/direct/doc/en/objects/adgroup)
- `AdGroups.add` поддерживает required `Name`, `CampaignId`, non-empty `RegionIds`, group negative keywords, tracking parameters и `UnifiedAdGroup.OfferRetargeting`. Region IDs должны приходить из Dictionaries, а не из строковых догадок. [AdGroups.add](https://yandex.com/dev/direct/doc/en/adgroups/add)
- `Keywords.add` создаёт explicit keywords и autotargeting criterion через special phrase `---autotargeting`; максимум один autotargeting на group. Новый `AutotargetingSettings` задаёт categories `Exact`, `Narrow`, `Alternative`, `Accessory`, `Broader` и brand options; старый `AutotargetingCategories` deprecated. [Keywords.add](https://yandex.com/dev/direct/doc/en/keywords/add)
- Unified migration page говорит, что UPC groups поддерживают keywords, autotargeting и retargeting. При этом общая best-practice autotargeting page всё ещё перечисляет только `TEXT_AD_GROUP` и `MOBILE_APP_AD_GROUP`. Это **официальная документационная несогласованность**, поэтому static schema knowledge недостаточно для guaranteed live support. [UPC migration](https://yandex.com/dev/direct/doc/en/unified-campaign-update) · [autotargeting guide](https://yandex.com/dev/direct/doc/en/best-practice/auto-targeting)
- Keywords/autotargeting имеют собственные `State`, `Status`, `ServingStatus`; `RARELY_SERVED` означает platform assessment низкой serving eligibility, а не нулевой market demand. [Keywords.get](https://yandex.com/dev/direct/doc/en/keywords/get) · [Ad group object](https://yandex.com/dev/direct/doc/en/objects/adgroup)

### 3.3. Ads и sitelinks

- `Ads.add` для `TextAd` поддерживает `Title`, optional `Title2`, `Text`, landing `Href`, `DisplayUrlPath`, `SitelinkSetId`, extensions и другие assets. В unified group запрещены `Mobile="YES"`, `VCardId`, `TurboPageId` и `PreferVCardOverBusiness="YES"`. [Ads.add](https://yandex.com/dev/direct/doc/en/ads/add) · [Ad group object](https://yandex.com/dev/direct/doc/en/objects/adgroup)
- Один `SitelinksSet` содержит 1–8 ссылок; один ad имеет не более одного set; set можно переиспользовать. Set immutable: для изменения создаётся новый. Review происходит только после назначения ad. [Sitelink object](https://yandex.com/dev/direct/doc/en/objects/sitelink)
- `Sitelinks.add` — API write: title required, `Href`/TurboPage target, optional description; одинаковые sets в одном request дедуплицируются платформой. [Sitelinks.add](https://yandex.com/dev/direct/doc/en/sitelinks/add)
- Ads moderation асинхронна; campaign/group/ad/criteria имеют разные state/status semantics. Submit to moderation не равно accepted и не равно serving. [Ad object](https://yandex.com/dev/direct/doc/en/objects/ad) · [Ads.moderate](https://yandex.com/dev/direct/doc/en/ads/moderate)

### 3.4. Restrictions и live eligibility

- Максимум 5 одновременных API requests на advertiser; points расходуются и на ошибки. [Restrictions and points](https://yandex.com/dev/direct/doc/en/concepts/units)
- `Clients.get` возвращает `Currency`, `Grants`, `Restrictions`, `Archived`, `AvailableCampaignTypes`, representatives/roles; среди limits есть campaigns/client, groups/campaign, ads/group и keywords/group. [Clients.get](https://yandex.com/dev/direct/doc/en/clients/get)
- Возможны no-rights/read-only, currency-not-set, no Direct account, no API access/IP restriction, unsupported campaign/type/field и invalid object status errors. [errors](https://yandex.com/dev/direct/doc/en/concepts/errors-list)
- Array writes имеют per-item warnings/errors и не являются общей транзакцией. Типы parent/child и object state проверяются платформой. [Campaigns.add](https://yandex.com/dev/direct/doc/en/campaigns/add) · [errors](https://yandex.com/dev/direct/doc/en/concepts/errors-list)

**Граница факта:** документация доказывает существование schema/method. Она не доказывает, что конкретный OAuth subject, advertiser, currency, campaign type, placement, strategy, goal, business profile или content пройдут live authorization, validation и moderation.

### 3.5. Read-only preflight подключённого аккаунта

21.08.2026 выполнены только официальные `Clients.get`, `Campaigns.get`, `AdGroups.get`, `Ads.get` и `Keywords.get` через Direct API v501; внешних записей и обращений к кабинету не было.

- advertiser активен: `Archived=NO`, `Type=CLIENT`, валюта `RUB`;
- `Grants.EDIT_CAMPAIGNS=YES`, `ForbiddenPlatform=NONE`;
- `AvailableCampaignTypes` включает `UNIFIED_CAMPAIGN` (а также документированные legacy-типы);
- live restrictions: 3000 campaigns всего, 1000 unarchived, 1000 groups/campaign, 50 ads/group, 200 keywords/group, 1000 ad extensions;
- в live scope `ON | SUSPENDED | OFF` наблюдены 5 Unified campaigns, 57 `UNIFIED_AD_GROUP`, 65 `TEXT_AD`, 210 keyword objects;
- в тех же группах наблюдены 57 criteria `Keyword="---autotargeting"`; это account-specific read evidence фактического использования autotargeting;
- наблюдены Search и Network strategy states, включая Search `WB_MAXIMUM_CLICKS` и channel-level `SERVING_OFF`.

Preflight подтверждает доступность выбранного account substrate и conditional autotargeting на чтении. Он не заменяет schema validation конкретного нового payload, moderation и per-write readback; sitelinks/новые placement combinations не считаются live-подтверждёнными только из-за лимита или документации.

---

## 4. Decision contract: детерминированные оси fan-out

### 4.1. Входы

Fan-out принимает только immutable inputs:

```yaml
FanOutInput:
  contract_version: campaign-fanout-v1
  strategy_revision_id: immutable approved revision
  analytics_evidence_snapshot_id: immutable snapshot
  demand_snapshot_id: Wordstat/Direct evidence snapshot
  playbook_release_digest: exact active curated release or NONE
  direct_capability_snapshot_id: read-only account preflight
  score_contract_version: optional; may be UNAVAILABLE
```

Если Strategy не `APPROVED`, evidence snapshot отсутствует либо capability snapshot устарел по configured TTL, Recommendation Set не генерируется как publishable: `BLOCKED_INPUT_INCOMPLETE`.

### 4.2. Канонические домены осей

Каждый axis member имеет stable ID, canonical label, evidence refs и status `APPROVED | INELIGIBLE | UNCERTAIN`.

```text
P = approved product/service units
A = approved audience/decision-role units
O = approved offer/value/terms units
K = eligible Demand Clusters from «Определить источник частотности, стоимости и правила long-tail packing»
```

Нормализация ID: Unicode NFKC → lower case → collapse whitespace → canonical business taxonomy ID. Исходная формулировка не теряется. LLM не может незаметно добавить новый product/audience/offer: неподтверждённая сущность становится `UNCERTAIN` и не входит в default shortlist.

Leaf universe конечен:

```text
L = P × A × O × K
```

Но blind Cartesian publication запрещена. Для каждого leaf вычисляется deterministic applicability:

```text
eligible(leaf) :=
  strategy_explicitly_allows(product, audience, offer)
  AND cluster.semantic_key compatible with (product, audience, offer)
  AND no business exclusion
  AND landing/geo/legal/capability hard eligibility passes
```

Каждый leaf получает ровно один terminal state:

- `ELIGIBLE_FOR_PACKING`;
- `INELIGIBLE_STRATEGY_CONFLICT`;
- `INELIGIBLE_SEMANTIC_MISMATCH`;
- `INELIGIBLE_HARD_BLOCKER`;
- `EVIDENCE_GAP`.

Так оси остаются проверяемыми, но бессмысленные cross-products не становятся кампаниями.

### 4.3. Packing до Draft generation

Для каждого eligible leaf вычисляется уже принятый `delivery_key`:

```text
primary_goal
× economics_profile
× geography
× landing_page
× core_message
× management_profile
```

`management_profile` в MVP:

```yaml
campaign_type: UNIFIED_CAMPAIGN
search_strategy: WB_MAXIMUM_CLICKS
network_strategy: SERVING_OFF
placements: SEARCH_RESULTS_BASELINE | CONDITIONAL_PRODUCT_GALLERY
criteria_mode: EXPLICIT_KEYWORDS | EXPLICIT_PLUS_AUTOTARGETING_CONDITIONAL
ad_type: TEXT_AD
measurement_binding: counter/goal readiness identity
schedule_legal_profile: canonical IDs
```

Все leaves с одинаковым exact `delivery_key` пакуются в один `DeliveryBucket`; его cluster IDs сортируются по stable ID. Разный keyword cluster при том же delivery key **не создаёт кампанию**. Split возможен только при различном delivery key и sufficiency contract из `wordstat-cost-and-long-tail-packing.md`.

### 4.4. Control

Для каждого DeliveryBucket создаётся ровно один control:

1. `COMPETITIVE_NORM_CONTROL`, если минимум два независимых eligible competitor evidence records наблюдают один и тот же versioned pattern (message structure/offer framing/extension pattern), source coverage не `UNAVAILABLE`, и pattern не требует копирования текста, trademark misuse или неподтверждённого claim.
2. Иначе `STRATEGY_BASELINE_FALLBACK`: буквальное, консервативное выражение approved Strategy message + qualified action. Оно **не называется конкурентной нормой**.

Control сохраняет:

```yaml
control_basis:
  kind: COMPETITIVE_NORM_CONTROL | STRATEGY_BASELINE_FALLBACK
  evidence_ids: []
  pattern_id: string
  unsupported_claims_removed: []
```

Нельзя брать «лучшего конкурента» по неизвестной эффективности, копировать его copy или считать распространённость causal evidence.

### 4.5. Improvement hypotheses

На один DeliveryBucket MVP допускает не более **двух** improvement Drafts, выбранных stable sort по:

1. hard eligibility;
2. exact applicability playbook/evidence;
3. evidence quality;
4. declared expected mechanism relevance;
5. stable `hypothesis_id` tie-breaker.

Каждая hypothesis обязана менять **ровно одну material treatment family** относительно control:

- `MESSAGE_OFFER`: value/terms/proof framing;
- `AUDIENCE_SPECIFICITY`: role-specific message while product/offer fixed;
- `QUALIFIED_ACTION`: CTA/qualification wording;
- `CRITERIA_AUTOTARGETING`: explicit keywords vs configured autotargeting;
- `PLACEMENT`: baseline search results vs one eligible placement regime;
- `EXTENSION`: sitelink structure, only when destinations are genuine.

Обязательные поля:

```yaml
OperationalHypothesisDraft:
  hypothesis_id: stable ID
  source: ANALYTICS_EVIDENCE | ACTIVE_PLAYBOOK
  mechanism: testable claim
  comparator_draft_key: exact control key
  changed_family: exactly one enum
  changed_fields: non-empty JSON pointers
  held_constant_fields: explicit list
  target_outcome: approved qualified outcome or diagnostic proxy label
  guardrails: []
  evidence_refs: []
  confidence: LOW | MEDIUM | HIGH
```

Hypothesis не повышает authority, не становится фактом и не обещает uplift. Комбинация двух improvements создаётся только в будущем отдельным preregistered factorial/sequence contract; MVP её не генерирует.

### 4.6. Draft identity

```text
DraftVariantKey =
  strategy_revision_id
  × delivery_key_fingerprint
  × sorted(cluster_ids)
  × variant_kind(control|hypothesis_id)
  × direct_capability_profile_id
```

Human-readable campaign name не является identity или idempotency key.

---

## 5. Deduplication, coverage, termination и hidden-weak

### 5.1. Четыре слоя deduplication

1. **Axis dedup:** canonical product/audience/offer IDs; исходные aliases сохраняются.
2. **Demand dedup:** unique assignment row→cluster и `KeywordsResearch.deduplicate` из принятого [«Определить источник частотности, стоимости и правила long-tail packing»](https://github.com/ElJeskos/MOX-ADV/issues/91). Provider output сохраняется; если method unavailable — `EVIDENCE_GAP`, а не silent local equivalence.
3. **Variant dedup:** если improvement `changed_fields` после normalization пуст, он получает `SUPPRESSED:NO_MATERIAL_DELTA`.
4. **Publish dedup:** canonical JSON projection без display-only metadata, с отсортированными arrays и normalized URLs/strings, хешируется SHA-256. Два Drafts с одинаковым `publish_fingerprint` схлопываются; winner — control, затем higher evidence quality, затем stable key. Остальные имеют `DUPLICATE_OF`.

Проверка существующего Direct account использует exact readback comparability vector/object graph, а не только имя кампании. Name collision остаётся отдельным validation error.

### 5.2. Coverage ledger

Recommendation Set считается полным только если существует двустороннее покрытие:

- каждый leaf из `L` имеет terminal disposition;
- каждый visible/hidden Draft перечисляет покрываемые leaf IDs и Demand Cluster IDs;
- каждый approved product, audience и offer либо присутствует хотя бы в одном eligible bucket, либо имеет явную reason code;
- каждый eligible cluster `PACKED | STANDALONE | HIDDEN | EVIDENCE_GAP` по [«Определить источник частотности, стоимости и правила long-tail packing»](https://github.com/ElJeskos/MOX-ADV/issues/91);
- каждый generated hypothesis указывает control comparator.

```yaml
coverage_summary:
  total_leafs: n
  eligible_leafs: n
  represented_leafs: n
  suppressed_leafs: n
  evidence_gap_leafs: n
  uncovered_leaf_ids: []   # must be empty for COMPLETE
  axis_member_dispositions: []
```

`COMPLETE` не означает «все варианты хороши»; только отсутствие необъяснённой потери.

### 5.3. Termination

Алгоритм завершится, потому что:

1. оси берутся из конечной approved Strategy/evidence revision;
2. каждый leaf оценивается один раз;
3. packing — one-pass group by immutable delivery key;
4. на bucket генерируется `1 control + min(2, eligible hypotheses)`;
5. hypotheses не создают новые axis members и не рекурсируют;
6. hard ceiling дополнительно равен live `Clients.get.Restrictions`, approved package exposure limit и configured UI canvas limit; превышение не отбрасывает хвост молча, а создаёт `SUPPRESSED:CAPACITY_LIMIT` после stable rank.

Termination condition:

```text
all leafs terminal
AND all buckets terminal
AND no unresolved duplicate set
AND generated_count <= effective_cap
```

### 5.4. Hidden-weak

Hidden — UI disposition, не удаление.

| Reason | Детерминированное условие |
|---|---|
| `HIDDEN:DUPLICATE_OR_OVERLAP` | После canonical/Direct dedup нет уникальной publish phrase или projection duplicate.
| `HIDDEN:NO_DEMAND` | Ровно условие из [«Определить источник частотности, стоимости и правила long-tail packing»](https://github.com/ElJeskos/MOX-ADV/issues/91): нет positive current rows, `hasSearchVolume=NO`, нет relevant seasonal demand.
| `HIDDEN:INSUFFICIENT_STANDALONE_CAPACITY` | Несовместимый delivery key и доступный forecast не поддерживает standalone budget/click capacity.
| `HIDDEN:HARD_INELIGIBLE` | Невалидный URL/geo/legal/type/required field или account capability denied.
| `HIDDEN:NO_MATERIAL_DELTA` | Improvement после compilation совпадает с control.
| `HIDDEN:DOMINATED_WITHIN_SAME_HYPOTHESIS` | Тот же mechanism/coverage, но хуже evidence completeness и тот же projection outcome; dominance vector сохранён.
| `EVIDENCE_GAP` | Demand/cost/capability source unavailable/conflicting; это не weak score и не zero.
| `DEFERRED_SEASONAL` | Сезонный спрос не пересекает Strategy window.

Viability score из [«Спроектировать объяснимый viability score до запуска»](https://github.com/ElJeskos/MOX-ADV/issues/93) может ранжировать уже eligible Drafts, но не переопределяет эти dispositions. Пока его contract не принят, fan-out не изобретает score threshold. Landing advisory findings никогда не являются hidden reason.

Control может быть hidden только из-за hard eligibility/no demand/capacity; низкий comparative score сам по себе не должен удалить единственный comparator из audit.

---

## 6. MVP-набор Direct: что включить и что оставить conditional

### 6.1. Guaranteed core после live preflight

«Guaranteed» ниже означает guaranteed **контрактом MOX после успешного account preflight**, а не универсально гарантированное Яндексом.

| Область | MVP choice | Почему честно сравнимо |
|---|---|---|
| Campaign | `UNIFIED_CAMPAIGN`, v501 | Один современный API type; не смешиваются разные object models.
| Placements | Search `SearchResults=YES`; `ProductGallery=NO`, Maps/SearchOrganizationList=NO; `DynamicPlaces` документированно наследует SearchResults при create; Network `SERVING_OFF` | Все content hypotheses получают один inventory regime.
| Strategy | Search `WB_MAXIMUM_CLICKS` + weekly budget; optional BidCeiling только по versioned policy; Network `SERVING_OFF` | Один actuator/optimization objective; conversion eligibility не смешивается с copy/segment comparison.
| Group | `UNIFIED_AD_GROUP`, `OfferRetargeting=NO`, exact `RegionIds`, group negatives, tracking params | Поддерживает text ads и criteria; scope видим в projection.
| Criteria | Explicit deduplicated keywords; без individual Bid/ContextBid при auto strategy | Phrase-based intent остаётся наблюдаемым; API не отклоняет bid change under automatic strategy.
| Ad | `TextAd`, `Mobile="NO"`, Title/Text/Href; optional Title2/DisplayUrlPath only if filled and shown | Минимальная редактируемая creative projection без hidden asset generation.
| Sitelinks | 1 set of 1–8 genuine links when landing/domain has valid distinct destinations; same extension policy across compared Drafts | Официальный create/assign/readback; не выдумываются несуществующие pages.
| Moderation/state | `Ads.moderate`; campaign remains `SUSPENDED` | Реальные objects, zero serving intent.

Sitelinks — capability core, но не required content: `NOT_APPLICABLE` честнее, чем четыре одинаковые/fabricated links. Если sitelinks используются как improvement hypothesis, control и treatment должны отличаться только extension family, а все URLs/claims должны быть evidence-backed.

### 6.2. Conditional capability hypotheses

1. **Autotargeting.** Допустим отдельный Draft `EXPLICIT_PLUS_AUTOTARGETING_CONDITIONAL` с exact categories/brand options и own campaign budget only after preflight confirms v501 unified add/get/suspend behavior. Нельзя считать default-enabled categories «настроенным экспериментом». Control criteria и treatment criteria должны быть read back; network остаётся off. Из-за противоречия official pages autotargeting не входит в unconditional core.
2. **Product Gallery / other search placements.** Допустим отдельный placement Draft только если `AvailableCampaignTypes`, ad/offer type and actual add/readback validate the placement. SearchResults и ProductGallery нельзя включить одновременно и назвать результат «placement test»: inventory treatment должен быть изолирован.
3. **Conversion strategies.** Schema существует, но eligibility зависит от goal/account/data conditions. Они не сравнимы с click bootstrap до measurement readiness и не входят в P0. Будущий strategy comparison требует отдельной hypothesis, одинаковой maturity/goal semantics и live preflight.

### 6.3. Явно не входит в MVP comparison

- Network/YAN serving;
- manual `HIGHEST_POSITION` alongside automatic click strategy;
- portfolio `Strategies` service;
- `AVERAGE_CPA`, pay-for-conversion, CRR/max-profit before verified eligibility and measurement;
- Responsive, image, builder, video, Shopping/Listing ads;
- audience/retargeting targets, bid modifiers, feeds;
- business profile provisioning (API can read/link published profile, but creation/verification is outside this exact contour);
- TurboPage/VCard fields, запрещённые/ deprecated для unified text ads;
- UI-only dynamic feed filters;
- any experiment provisioning claim: Direct API reference не даёт отдельный complete experiment lifecycle service.

Их исключение — не утверждение «API никогда не умеет», а решение о minimal comparability, lifecycle surface и account eligibility.

---

## 7. Exact publish projection

### 7.1. Принцип

Campaign Draft считается полным, только если **каждое редактируемое поле** либо:

- входит в exact provider projection;
- явно является business/evidence metadata и помечено `not_sent_to_direct`;
- блокирует publish как unsupported.

Silent subset запрещён.

### 7.2. Схема

```yaml
CampaignDraftRevision:
  draft_id: stable identity
  draft_revision_id: immutable
  status: GENERATED | EDITED | SHORTLISTED | APPROVED_FOR_PUBLISH | SUPERSEDED
  strategy_revision_id: immutable foreign key
  recommendation_set_id: immutable foreign key
  evidence_snapshot_ids: []
  delivery_key_fingerprint: sha256
  covered_leaf_ids: []
  demand_cluster_ids: []
  variant:
    kind: CONTROL | IMPROVEMENT
    control_basis: {}
    hypothesis: null | OperationalHypothesisDraft
  direct_capability_snapshot_id: string
  direct_projection:
    api_family: DIRECT_V5
    endpoint_version: v501
    account_binding: exact advertiser login/id
    campaign:
      Name: string
      StartDate: YYYY-MM-DD
      EndDate: YYYY-MM-DD | omitted
      TimeZone: documented value | omitted
      UnifiedCampaign:
        BiddingStrategy:
          Search:
            BiddingStrategyType: WB_MAXIMUM_CLICKS
            PlacementTypes: {}
            WbMaximumClicks:
              WeeklySpendLimit: micros
              BidCeiling: micros | omitted
          Network:
            BiddingStrategyType: SERVING_OFF
            PlacementTypes: {}
        CounterIds: [] | omitted
        PriorityGoals: [] | omitted
        TrackingParams: string | omitted
        AttributionModel: enum | omitted
        Settings: []
    sitelink_sets:
      - local_ref: sitelinks:primary
        Sitelinks: []
    ad_groups:
      - local_ref: group:<stable-id>
        Name: string
        RegionIds: []
        NegativeKeywords: {Items: []} | omitted
        TrackingParams: string | omitted
        UnifiedAdGroup: {OfferRetargeting: NO}
        criteria:
          - local_ref: keyword:<stable-id>
            Keyword: string
            AutotargetingSettings: null | exact object
        ads:
          - local_ref: ad:<stable-id>
            TextAd:
              Title: string
              Title2: string | omitted
              Text: string
              Href: https URL
              Mobile: NO
              DisplayUrlPath: string | omitted
              SitelinkSetRef: sitelinks:primary | omitted
  not_sent_to_direct:
    business_goal: ...
    target_cpa_business_constraint: ...
    rationale: ...
  compile_warnings: []
  unsupported_fields: []       # must be empty before approval
  publish_fingerprint: sha256(canonical direct_projection)
```

External IDs неизвестны до writes. Поэтому сохраняются две immutable проекции:

1. `compiled_projection` с local refs и hash — именно её утверждает пользователь;
2. `resolved_projection` с campaign/group/keyword/ad/sitelink IDs и mapping после каждого successful write.

Resolved projection не может менять content; только разрешать refs. Любой content diff требует новой DraftRevision и нового approval.

### 7.3. Compile validations

До shortlist/publish обязательны:

- exact account binding and credential role;
- current `AvailableCampaignTypes`, `Grants.EDIT_CAMPAIGNS`, `Archived=NO`, currency and restrictions;
- Dictionaries-derived RegionIds/currency minimum/time zone where needed;
- campaign/group/ad type compatibility;
- URL protocol/domain, text/word/negative/sitelink limits;
- all references resolvable;
- no deprecated/unsupported field;
- no unsupported projection field;
- Direct keyword dedup result captured;
- projected object counts ≤ live restrictions;
- package budget/exposure ≤ approved Strategy and Human Decision Gate;
- unique publish fingerprint against selected package, execution ledger and comparable account graph.

---

## 8. Связь со Strategy revisions

### 8.1. Immutable lineage

```text
CampaignStrategyRevision@approved
  + AnalyticsEvidenceSnapshot
  + DemandSnapshot
  + CapabilitySnapshot
  + PlaybookRelease
    → RecommendationSet
      → CampaignDraftRevision(s)
        → PackageApproval
          → independent PublishExecution(s)
```

Каждый объект immutable; «текущая версия» — materialized pointer, а не переписывание прошлого.

### 8.2. Что является Strategy-owned

Изменение любого поля ниже создаёт новую `CampaignStrategyRevision` и supersedes весь Recommendation Set:

- product/offer universe;
- audience;
- qualified outcome/exclusions/business goal;
- geography;
- campaign period;
- landing page;
- total/per-campaign economics, weekly budget/target result cost;
- core message;
- legal/schedule/placement business constraint.

Fan-out заново компилируется. Старые Drafts остаются audit-visible со status `SUPERSEDED_BY_STRATEGY_REVISION`; их нельзя publish.

### 8.3. Что может быть Draft-local

- campaign/group display names;
- keyword wording/operators within the same approved cluster/intent;
- group negative keywords consistent with exclusions;
- ad title/text/Title2/DisplayUrlPath within approved product/offer/message and evidence;
- sitelink titles/descriptions/URLs within approved landing/domain scope;
- technical ordering/group packing that does not change delivery key.

Draft-local edit создаёт новую `draft_revision_id`, пересчитывает fingerprint, eligibility, coverage and score/rank, но остаётся связан с той же Strategy revision. Если edit фактически меняет Strategy-owned meaning, UI обязан предложить/создать новую Strategy revision, а не сохранить «локальную правку».

### 8.4. Publish gate

PackageApproval фиксирует exact list `draft_revision_id + publish_fingerprint`, per-item budget exposure, account, Strategy revision and expiry. Перед каждым external write выполняется fresh comparison; любое расхождение даёт `APPROVAL_STALE`. Package не атомарен: каждый Draft имеет independent execution/result; failure одного не разрешает повтор/изменение другого.

---

## 9. Non-serving publish lifecycle

Рекомендуемый exact flow на каждый выбранный Draft:

1. Persist dispatch intent and execution key before HTTP write.
2. Optional `Sitelinks.add` for unassigned immutable sets; persist IDs. Их создание само по себе не даёт показов.
3. `Campaigns.add`; persist campaign ID immediately.
4. **Безусловно `Campaigns.suspend`**, даже если initial readback `OFF`.
5. `Campaigns.get`; require `State=SUSPENDED`. До этого child writes запрещены.
6. `AdGroups.add` for all projected groups; per-item errors parsed, IDs persisted.
7. `AdGroups.get` exact readback.
8. `Keywords.add` explicit/autotarget criteria; no Bid/ContextBid under automatic strategy.
9. `Keywords.get` exact phrase/settings/state/status readback.
10. `Ads.add`, resolving `SitelinkSetId`; then `Ads.get` exact content readback.
11. `Ads.moderate` only for exact approved ad IDs.
12. Async polling with persisted schedule; do not hold one synchronous request until acceptance.
13. Final full graph readback and require campaign `State=SUSPENDED`.
14. Terminal item state: `MODERATION_PENDING | READY_TO_LAUNCH | REJECTED_NEEDS_EDIT | RECONCILIATION_REQUIRED`; never `ON`.

`Campaigns.resume` is absent from service allowlist and projection. Ambiguous write timeout is not blindly retried: reconcile by exact object graph/execution record; if uniqueness cannot be proved, hold account write lock and require bounded reconciliation. Delete is not assumed to be universal rollback; containment is `SUSPENDED`.

---

## 10. Проверочные сценарии решения

| Scenario | Expected contract result |
|---|---|
| 3 clusters, same product/audience/offer/delivery key | One DeliveryBucket; one control + ≤2 improvements; clusters are children, not 3 campaigns.
| Same phrase discovered by two seeds | Unique assignment + Direct dedup; one publish criterion; coverage refs both source paths.
| Two products share keyword wording but different landing/economics | Different delivery keys and Drafts if standalone sufficiency passes; never silently pack.
| No reliable competitor evidence | `STRATEGY_BASELINE_FALLBACK`; no claim “competitive norm”.
| Improvement changes copy and autotargeting | Rejected `MULTIPLE_MATERIAL_FAMILIES`; split into separate hypotheses.
| Two hypotheses compile to same payload | One visible Draft; other `HIDDEN:NO_MATERIAL_DELTA`/`DUPLICATE_OF`.
| Wordstat quota failure | `EVIDENCE_GAP`; no zero frequency or weak label.
| Autotarget unified schema accepted in docs but denied by live account | Conditional Draft hidden `HARD_INELIGIBLE:CAPABILITY_DENIED`; core explicit-keyword Drafts remain.
| Sitelinks have no real distinct destinations | `NOT_APPLICABLE`; no fabricated links and no blocker.
| Strategy landing page edited after shortlist | New StrategyRevision; all old Drafts superseded; package approval stale.
| Draft ad text edited within message | New DraftRevision/fingerprint; same Strategy lineage; re-rank and re-approve.
| `Campaigns.add` returns OFF | Still call `suspend`; children blocked until readback is exactly `SUSPENDED`.
| Batch has 3 Drafts, second fails | First result retained, second failed/contained, third proceeds only per package execution policy; no fictitious atomic rollback.
| Moderation remains pending | Real campaign stays suspended; terminal P0 item is `MODERATION_PENDING`, not failure or launch.

---

## 11. Implementation handoff for current production module

Минимальный связный implementation slice после принятия этого decision contract:

1. Replace scalar `strategy/draft/campaign` state with immutable revision tables/objects plus Recommendation Set and coverage ledger.
2. Compile finite axes and delivery buckets; render control + at most two improvements as Draft cards with hidden reasons.
3. Change DirectProjection child fields to arrays and add local refs/sitelink sets, canonical fingerprint and unsupported-fields gate.
4. Add live `Clients.get` capability snapshot and Dictionaries-derived region/currency data; stop relying on three hard-coded region labels.
5. Extend Direct adapter with Sitelinks and full group/keyword/ad readback; preserve per-item results.
6. Change `ensureNonServing` so campaign creation always calls `Campaigns.suspend` and requires `SUSPENDED` before child writes.
7. Replace short synchronous moderation wait with durable pending state.
8. Package confirmation must pin exact Draft revisions/fingerprints and show independent outcomes.

This document does not authorize those writes or implementation changes; current Gate/Human Decision Gate still applies.

---

## 12. Sources

### Kept — local primary/accepted

- [«Определить fan-out Strategy → Campaign Drafts и MVP-набор возможностей Директа»](https://github.com/ElJeskos/MOX-ADV/issues/94) — exact question and non-reopen invariants.
- [«Развитие P0 „Стратегия и создание кампании“: карта нерешённых решений»](https://github.com/ElJeskos/MOX-ADV/issues/89) — accepted five-step map, package selection and standing rules.
- `CONTEXT.md` — canonical domain terms.
- `docs/research/landing-page-advisory-analysis-contract.md` — advisory-only landing boundary.
- `docs/research/wordstat-cost-and-long-tail-packing.md` — demand/cost/packing contract.
- `docs/research/p0-open-source-research-contour.md` — official API-only trust boundary.
- `docs/research/knowledge-library-and-playbook-promotion.md` — immutable hypothesis/playbook authority boundary.
- `sites/p0-production/app/P0Client.tsx`, `sites/p0-production/lib/p0.ts`, `campaign-draft.ts`, `direct-write.ts`, `direct-limits.ts`, `ad-copy.ts` — actual current production-candidate behavior.

### Kept — Yandex primary

- [Campaigns.add](https://yandex.com/dev/direct/doc/en/campaigns/add), [UnifiedCampaign fields/strategies/placements](https://yandex.com/dev/direct/doc/en/campaigns/add-unified-campaign), [Campaign object](https://yandex.com/dev/direct/doc/en/objects/campaign)
- [Strategy compatibility](https://yandex.com/dev/direct/doc/en/objects/campaign-strategies)
- [Campaigns.suspend](https://yandex.com/dev/direct/doc/en/campaigns/suspend), [official launch lifecycle](https://yandex.com/dev/direct/doc/en/best-practice/launch-campaign)
- [AdGroups.add](https://yandex.com/dev/direct/doc/en/adgroups/add), [Ad group object/status/types](https://yandex.com/dev/direct/doc/en/objects/adgroup)
- [Keywords.add](https://yandex.com/dev/direct/doc/en/keywords/add), [Keywords.get](https://yandex.com/dev/direct/doc/en/keywords/get), [autotargeting guide](https://yandex.com/dev/direct/doc/en/best-practice/auto-targeting), [UPC migration](https://yandex.com/dev/direct/doc/en/unified-campaign-update)
- [Ads.add](https://yandex.com/dev/direct/doc/en/ads/add), [Ad object/lifecycle](https://yandex.com/dev/direct/doc/en/objects/ad), [Ads.moderate](https://yandex.com/dev/direct/doc/en/ads/moderate)
- [Sitelink object](https://yandex.com/dev/direct/doc/en/objects/sitelink), [Sitelinks.add](https://yandex.com/dev/direct/doc/en/sitelinks/add)
- [Clients.get](https://yandex.com/dev/direct/doc/en/clients/get), [restrictions/points](https://yandex.com/dev/direct/doc/en/concepts/units), [errors](https://yandex.com/dev/direct/doc/en/concepts/errors-list)
- [KeywordsResearch.deduplicate](https://yandex.com/dev/direct/doc/en/keywordsresearch/deduplicate), [hasSearchVolume](https://yandex.com/dev/direct/doc/en/keywordsresearch/hasSearchVolume)

### Dropped

- SEO/agency/blog recommendations, benchmark compilations and cabinet screenshots — not primary sources and/or violate repository boundary.
- Google/Meta campaign patterns — irrelevant to exact Yandex publishability.
- Direct Help claims where the same API fact exists in Direct API reference; Help retained only when API reference itself links eligibility semantics not fully specified in schema.
- Standalone Smart/Dynamic/display campaign types — documentation/scope does not support a minimal comparable P0 contour.

---

## 13. Confidence and unresolved risks

### Confidence

- **High:** fan-out lineage, finite leaf ledger, delivery-key packing, publish fingerprint, no-silent-subset, revision invalidation and explicit `SUSPENDED` barrier follow accepted local invariants and observable API lifecycle.
- **High:** Unified campaign/group, explicit keywords, TextAd, sitelinks, placements fields, strategy compatibility, restrictions and per-item error semantics are directly documented.
- **Medium-high:** one control + at most two single-family improvements is a deliberate MOX-ADV product bound, not a Yandex requirement; it prevents combinatorial explosion while preserving useful choice.
- **Medium:** exact unified autotarget behavior across accounts because two current official pages are not aligned; capability remains conditional.

### Unresolved risks

1. **MEDIUM — live account eligibility проверена только read-only.** `Clients.get` и live inventory подтвердили Unified/Search/TextAd/keywords/autotargeting substrate, но новые sitelinks, placement combinations и каждый write payload всё равно требуют per-item validation/readback.
2. **BLOCKER — current code safety mismatch.** `State=OFF` is currently accepted before child writes; implementation must require explicit `SUSPENDED`.
3. **HIGH — no provider idempotency key/universal transaction.** Ambiguous `add` can require reconciliation; fingerprint/name cannot prove provider non-creation after timeout.
4. **HIGH — moderation/content/legal eligibility is external.** Exact schema-valid projection can still be rejected; no pre-launch score may promise acceptance.
5. **HIGH — [«Спроектировать объяснимый viability score до запуска»](https://github.com/ElJeskos/MOX-ADV/issues/93) пока не принят.** Fan-out therefore defines structural hiding only and must not invent score threshold/calibration.
6. **MEDIUM — competitor coverage can be absent.** Control must fall back honestly rather than fabricate “market norm”.
7. **MEDIUM — independent placement/autotarget tests need enough future traffic and budget.** API create eligibility alone does not make them statistically comparable or useful.
8. **MEDIUM — sitelink cleanup/reuse.** Sets are immutable and deletable only when unassigned; execution ledger must avoid orphan proliferation.
9. **MEDIUM — Direct schema/changelog drift.** Pin capability snapshot/API contract date and rerun fixtures before production publish.
