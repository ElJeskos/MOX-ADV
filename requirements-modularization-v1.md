# Normative modular product amendment

Version: `1.0`.
Date: 30 July 2026.
Status: approved scope baseline for the modularization workstream.
Audience: customer, product owner, architect, security reviewer, implementers, and technical integrators.

## Authority and compatibility

This amendment is normative for product editions, customer integration, environment authority, evidence classification, and modular acceptance.
For those subjects it supersedes conflicting statements in `requirements.md` version 2.7 and `requirements-v2-prototype.md` version 2.0-prototype.
The earlier documents remain normative for calculations, data-quality rules, attribution, policies, campaign and goal lifecycles, execution and reconciliation semantics, Decision Records, audit behavior, and paired acceptance behavior.
The existing paired product must reuse those behaviors rather than redesign them.
The terms `controlled production pilot`, `DIRECT_PILOT_WRITE`, `METRIKA_PILOT_WRITE`, and `PILOT_SITE_PUBLISH` grant no production authority after this amendment.
During migration, an implementation may recognize a legacy profile name only as an alias inside an explicitly selected test adapter.
Such an alias must fail closed before credential resolution or network egress in production.

## Product matrix

| Edition ID | Provider scope | Customer adapter | UI | Production capability | Approved test capability |
| --- | --- | --- | --- | --- | --- |
| `METRIKA_STANDALONE` | Yandex Metrika | HTTP/JSON | None (headless) | Read, analyze, and recommend only | Existing goal-analysis and goal-lifecycle behavior through explicit test resources |
| `DIRECT_STANDALONE` | Yandex Direct | HTTP/JSON | None (headless) | Read, analyze, and recommend only | Existing campaign planning and execution behavior through an explicit test adapter |
| `DIRECT_METRIKA_PAIRED` | Yandex Direct + Yandex Metrika | In-process | Existing MOX-ADV Dashboard at `http://127.0.0.1:8878` | Read, analyze, and recommend only | Existing paired closed-loop behavior through explicit test composition |

The standalone editions are integration modules for a customer's technical ecosystem.
They do not ship, import, expose, or modify the MOX-ADV Dashboard.
Each standalone edition must install and run without the other provider module.
The paired edition composes the same provider module interfaces and preserves the current Dashboard routes, navigation, controls, reports, operating modes, language, calculations, and behavior.
No standalone onboarding screens or destination-specific dashboards are part of this amendment.

## Integration contract matrix

| Consumer | Adapter | Request | Result | Transport boundary |
| --- | --- | --- | --- | --- |
| `CUSTOMER_ECOSYSTEM` | HTTP/JSON | `ModuleRequestV1` | `ModuleResultV1` | Versioned OpenAPI contract |
| `PAIRED_RUNTIME` | In-process | `ModuleRequestV1` | `ModuleResultV1` | Versioned Python interface without an HTTP hop |

`ModuleRequestV1` references a stored connection, environment, scope, period, objective, operation, idempotency key, and optional validated external evidence.
It never carries a raw OAuth token, arbitrary endpoint, or arbitrary Yandex HTTP payload.
`ModuleResultV1` returns run and module identity, status, normalized metrics, assessment, recommendations, provenance, warnings, typed errors, a Decision Record reference, and an optional proposal or execution result.
Provider-owned reads and customer-supplied typed evidence enter the same validation and calculation behavior.
HTTP/JSON and in-process adapters must invoke the same module interface and produce contract-equivalent results.
Queues, webhooks, CRM connectors, destination-specific connectors, and standalone visual onboarding are outside this amendment.

## Environment and credential matrix

| Credential profile | Environment | Resource boundary | Access | Availability |
| --- | --- | --- | --- | --- |
| `DIRECT_PROD_READ` | `PRODUCTION` | Allowlisted Direct accounts and reports | Read only | Standalone Direct and paired editions |
| `METRIKA_PROD_READ` | `PRODUCTION` | Allowlisted Metrika counters and goals | Read only | Standalone Metrika and paired editions |
| `DIRECT_TEST_WRITE` | `TEST` | Synthetic or provider-approved test campaign resources | Read and write | Standalone Direct and paired test composition only |
| `METRIKA_TEST_WRITE` | `TEST` | Explicit test counters and candidate goals | Read and write | Standalone Metrika and paired test composition only |
| `TEST_SITE_PUBLISH` | `TEST` | Explicit test pages and events | Write | Standalone Metrika and paired test composition only |

Production allows provider reads, deterministic calculations, analysis, proposals, recommendations, and Decision Records.
Every campaign, goal, or site-changing operation is forbidden in production regardless of Approval, Mandate, mode, caller, adapter selection, restart, or retry.
The production composition must not resolve, receive, or expose a write credential.
The trusted execution seam must reject a production write before credential resolution and before any HTTP request.
Write-capable behavior may run only when the environment is explicitly `TEST` and the selected adapter is approved for test resources.
An external host used by a provider-approved test resource does not make a production identity or production target writable.

## Gate matrix

| Gate | Purpose | Exit evidence | Production write allowed |
| --- | --- | --- | --- |
| `GATE_0` | Approve scope, contracts, credentials, ownership, and safety boundaries | Approved matrices and sign-offs in this amendment | No |
| `GATE_1` | Preserve the safe core and add the versioned module seam | Schemas, deterministic guards, contract tests, and adversarial tests | No |
| `GATE_2` | Prove standalone module behavior and write-capable lifecycles in test | Headless module tests, local contracts, test counters, and test adapters | No |
| `GATE_3` | Prove real provider reads and shadow decisions | Real read-only evidence, provenance, scheduled monitoring, and proposals | No |
| `GATE_4` | Prove the unchanged paired control loop without production writes | Paired Dashboard regression and complete test-contour closed-loop evidence | No |

Gate order remains `GATE_0` through `GATE_4`.
No gate transition can authorize production write.
Unavailable provider test APIs reduce the applicable write evidence to local contract and approved test-adapter evidence; they do not justify a production exception.

## Capability and evidence matrix

The capability identifiers remain unchanged so existing Decision Records, reports, and Dashboard projections remain compatible.
An edition is accepted against only the capabilities listed for that edition.
Evidence types are `LOCAL_CONTRACT`, `TEST_COUNTER`, `REAL_READ_ONLY`, `SIMULATED`, `TEST_CONTOUR`, and `DASHBOARD_REGRESSION`.
`TEST_CONTOUR` proves execution semantics only against explicit test resources or test adapters and never proves production write.

| Capability | Applicable editions | Required evidence |
| --- | --- | --- |
| `CAMPAIGN_LIFECYCLE` | `DIRECT_STANDALONE` + `DIRECT_METRIKA_PAIRED` | LOCAL_CONTRACT + TEST_CONTOUR |
| `GOAL_LIFECYCLE` | `METRIKA_STANDALONE` + `DIRECT_METRIKA_PAIRED` | TEST_COUNTER + TEST_CONTOUR |
| `SOURCE_INTEGRATION` | `METRIKA_STANDALONE` + `DIRECT_STANDALONE` + `DIRECT_METRIKA_PAIRED` | REAL_READ_ONLY + TEST_CONTOUR |
| `INTEGRATED_ANALYTICS` | `DIRECT_METRIKA_PAIRED` | REAL_READ_ONLY + TEST_CONTOUR |
| `LLM_ANALYSIS` | `METRIKA_STANDALONE` + `DIRECT_STANDALONE` + `DIRECT_METRIKA_PAIRED` | SIMULATED + REAL_READ_ONLY |
| `APPROVAL_REQUIRED` | `DIRECT_STANDALONE` + `DIRECT_METRIKA_PAIRED` | SIMULATED + TEST_CONTOUR |
| `BOUNDED_AUTONOMY` | `DIRECT_STANDALONE` + `DIRECT_METRIKA_PAIRED` | SIMULATED + TEST_CONTOUR |
| `MONITORING_AND_ALERTING` | `METRIKA_STANDALONE` + `DIRECT_STANDALONE` + `DIRECT_METRIKA_PAIRED` | SIMULATED + REAL_READ_ONLY |
| `IMPACT_EVALUATION` | `METRIKA_STANDALONE` + `DIRECT_STANDALONE` + `DIRECT_METRIKA_PAIRED` | SIMULATED + TEST_CONTOUR |
| `OPERATIONAL_MODES` | `METRIKA_STANDALONE` + `DIRECT_STANDALONE` + `DIRECT_METRIKA_PAIRED` | SIMULATED + TEST_CONTOUR |
| `TOOL_CONTRACT` | `METRIKA_STANDALONE` + `DIRECT_STANDALONE` + `DIRECT_METRIKA_PAIRED` | SIMULATED + LOCAL_CONTRACT |
| `ORIGINAL_INTEGRATION_COVERAGE` | `METRIKA_STANDALONE` + `DIRECT_STANDALONE` + `DIRECT_METRIKA_PAIRED` | LOCAL_CONTRACT + TEST_COUNTER + TEST_CONTOUR |
| `SAFETY_CORE` | `METRIKA_STANDALONE` + `DIRECT_STANDALONE` + `DIRECT_METRIKA_PAIRED` | SIMULATED + LOCAL_CONTRACT + TEST_CONTOUR |
| `CLOSED_LOOP_CONTROL` | `DIRECT_METRIKA_PAIRED` | TEST_CONTOUR + DASHBOARD_REGRESSION |

Existing evidence and acceptance results remain historically valid for the behavior they exercised.
New release evidence must use the environment classifications in this amendment.
No new result may classify a production write as accepted evidence.

## Acceptance matrix

| ID | Acceptance statement | Required evidence |
| --- | --- | --- |
| `AS-001` | Exactly three editions are defined with the product boundaries in the product matrix | Scope validator output |
| `AS-002` | Each standalone edition installs, starts, and returns a result without the other provider or Dashboard | Clean-environment package and E2E evidence |
| `AS-003` | The paired edition preserves the existing Dashboard and current business behavior | Dashboard Playwright and visual regression evidence |
| `AS-004` | HTTP/JSON and in-process adapters use one versioned request/result contract | OpenAPI compatibility and in-process contract tests |
| `AS-005` | Every production write attempt is rejected before write credential resolution and HTTP | Parameterized E2E evidence with zero write requests |
| `AS-006` | Existing write-capable behavior remains executable only through approved test composition | Test-contour lifecycle and closed-loop evidence |
| `AS-007` | Existing calculations, policies, execution semantics, Decision Records, and paired acceptance behavior remain unchanged | Legacy regression suite and contract-equivalence evidence |
| `AS-008` | Product, gate, capability, evidence, credential, and acceptance matrices remain internally consistent | Scope validator and required sign-offs |

## Required sign-offs

These approvals are scope approvals for this amendment.
They do not substitute for final release acceptance.

| Sign-off | Status | Evidence |
| --- | --- | --- |
| `CUSTOMER_REQUIREMENTS` | `APPROVED` | Customer confirmation of the revised ticket plan on 30 July 2026 |
| `PRODUCT` | `APPROVED` | Three-edition product matrix and inherited-behavior boundary |
| `ARCHITECTURE` | `APPROVED` | One deep module contract with HTTP/JSON and in-process adapters |
| `SECURITY` | `APPROVED` | Read-only production and test-only write authority matrix |
