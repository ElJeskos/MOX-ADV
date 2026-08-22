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
