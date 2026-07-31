# OKF Log

## 2026-07-30

- **Product decision**: Added a versioned local campaign editor whose saved business goal and target KPI feed subsequent analysis and safe lifecycle simulations.
- **Campaign goals**: Expanded the local campaign editor with strategy, payment, attribution, a policy-bound counter, and up to 30 valued priority goals.
- **Advertisements**: Kept groups and responsive ads inside the campaign page, with one pilot group and A/B pair projecting into the Gate 0 lifecycle.
- **Navigation**: Recorded `Вебвизор` as a disabled last navigation item with no route until implementation.
- **Contract**: Added the campaign name to `CampaignDraftV1`.
- **Decision history**: Split the Dashboard history page into decision-journal and decision-outcome tabs, with three recent entries by default and server-side pages of ten when expanded.
- **Outcome evidence**: Linked immutable post-change observations to their source decisions and required an explicit pending state when no observation exists.

## 2026-07-29

- **Migration**: Replaced the legacy v0.1 metadata and body-citation model with OKF v0.2 `generated`, `verified`, `sources`, and lifecycle metadata.
- **Curation**: Rebuilt product, architecture, implementation, acceptance, and runbook concepts from `requirements-v2-prototype.md` version `2.0-prototype`.
- **Decision**: Excluded legacy claims about `BOUNDED_AUTONOMY`, long-lived Mandates, and the former delivery-gate model because they are not part of the current prototype requirements.
- **Integration**: Added repository routing, development dependency declaration, base conformance validation, and stricter repository policy checks.
- **Initialization**: Created the OKF v0.2 bundle scaffold with the `okf-setup` process.
- **Supersession**: `requirements-v2-prototype.md` version `2.0-prototype` is the sole normative source; `requirements.md` version 2.7 and its derived OKF statements are stale and nonnormative.
- **Decision**: Merged Gate 0A and Gate 0B into one Gate 0 readiness boundary after Yandex Direct access became available.
- **Historical update**: Previously synchronized the OKF readiness model with now-superseded `requirements.md` version 2.7.
- **Update**: Aligned concept metadata, indexes, citations, and agent integration with the official OKF v0.1 article and pinned specification.
- **Decision**: Kept the bundle on declared version 0.1; migration to the current upstream v0.2 remains a separate explicit change.
- **Initialization**: Created the OKF bundle scaffold.
- **Historical creation**: Seeded product, architecture, implementation, and runbook concepts from now-superseded `requirements.md` version 2.6.
- **Creation**: Added a live-source map, agent integration path, and repository-local validation target.
