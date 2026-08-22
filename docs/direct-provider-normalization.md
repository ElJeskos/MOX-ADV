# Direct provider normalization for P0 readback

Ticket #111 compares the selected core Direct v501 projection semantically after official `get` readback. The comparison is deliberately narrow: every selected field must be present, while provider-only status/read metadata is preserved separately and does not become part of the approved projection.

## Supported core graph

The executor compares exactly one `UNIFIED_CAMPAIGN`, one `UNIFIED_AD_GROUP`, one explicit keyword criterion, and one `TEXT_AD`. The accepted capability profile has autotargeting, sitelinks/assets, Product Gallery, and Network disabled. Selecting an unknown field or an asset outside that profile is a pre-dispatch `P0_PROJECTION_INCOMPLETE` system failure; fields are never silently dropped.

## Normalization rules

- Direct IDs are decimal strings. Request serialization may use native `bigint`, but persistence and comparison never pass IDs through JavaScript `number`.
- Campaign/group names, keyword text, ad title, and ad text use Unicode NFKC, collapse whitespace runs to one space, and trim surrounding whitespace.
- `RegionIds` are an unordered provider set: IDs are converted to decimal strings and sorted numerically.
- `NegativeKeywords.Items` is an unordered provider set: entries receive the text normalization above and are sorted lexically.
- Strategy monetary integers are compared as canonical decimal strings so an official JSON integer and the approved safe integer remain equivalent without precision loss.
- Dates, URLs, campaign/group/ad types, placement flags, `OfferRetargeting`, and `Mobile` are exact values. No URL rewriting or inferred default is accepted.
- Object relationships (`CampaignId`, `AdGroupId`) and the final campaign `State=SUSPENDED` are exact.

Unknown, missing, or changed selected values produce `P0_DIRECT_GRAPH_MISMATCH`, are classified as system-owned, and cannot be converted into a provider rejection. The full supported graph is read once before moderation and again after submitting the exact ad ID.

## Terminal moderation readback

Ticket #113 repeats the same semantic graph read in a separate bounded moderation-poll command. Each attempt and its `next_poll_at` are persisted before the official `get` calls; one HTTP request performs one due item read and never waits for moderation to finish. `MODERATION` and `PREACCEPTED` remain pending. `StatusClarification`, provider issues, and the observation history remain durable.

A campaign is Direct-accepted only when the final readback still proves the complete supported graph and `State=SUSPENDED`, every published ad group has at least one final `ACCEPTED` ad, and every published ad has one visible terminal `ACCEPTED` or `REJECTED` outcome. An unknown status remains pending; a lost final suspension or semantic graph mismatch is system-owned and fails the package verdict.

## Confirmed correction readback

Ticket #114 keeps the initial package execution, item snapshot, provider responses, issues, moderation observations, content hash, and verdict immutable. Only an explicit `REJECTED_NEEDS_EDIT` provider-owned item with released account lock and fully accounted non-serving containment can open focused correction. Unknown, system-owned, or reconciliation-required outcomes cannot be reclassified as content rejection.

A material editable-field delta creates a new Draft revision, publish fingerprint, fixed-membership score/rank result, one-item package review, and exact Human Decision Gate. Resubmission updates the known suspended graph through the official update method only for object kinds present in the field-level delta, persists intent before every mutation, verifies the complete corrected graph semantically, and then submits the exact existing ad ID through `Ads.moderate`. Recovery is bounded to the corrected fingerprint and the known provider IDs. An ambiguous update or moderation write holds reconciliation; it is never routed back into content edit automatically.

The corrected execution uses the same asynchronous moderation and final suspension rules. Its internal one-item verdict can be `PENDING`, `PASS`, or `FAIL`, while the operator-facing successful terminal accounting is `PASS_AFTER_CORRECTION`. That outcome is stored beside—never over—the initial package verdict, and `initial_generation_passed` remains false.
