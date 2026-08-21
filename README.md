# MOX-ADV prototype bootstrap

This repository currently provides the safe local bootstrap slice for the MOX-ADV modular monolith.
The executable slice only processes the approved local fixture and cannot send an external write.

## Local run

Install the package in an isolated environment.

```shell
python3 -m venv .venv
.venv/bin/python -m pip install --editable .
```

Run the approved fixture.

```shell
.venv/bin/mox-adv run-fixture --run-id bootstrap-001
```

The command creates `runs/bootstrap-001/result.json`, `runs/bootstrap-001/report.md`, and `runs/bootstrap-001/events.jsonl`.
Every artifact contains the run schema and approved Gate 0 policy version.
The hidden SQLite journal in the run directory is the transactional source for the monotonic event sequence and SHA-256 hash chain.
A run identifier is single-use, so rerunning the same identifier leaves the completed run unchanged.

## Local operator UI

Start the local operator interface.

```shell
.venv/bin/mox-adv ui
```

The command opens `http://127.0.0.1:8878` and keeps the server bound to loopback.
Test mode runs one linked Direct and Metrika fixture, calculates metrics, creates a typed recommendation, applies the exact change to a sealed fake adapter, verifies readback, and writes a standalone HTML report under `runs/ui-*/`.
The test lab lets the operator enter impressions, clicks, spend, visits, conversions, weekly budget, and baseline values while the analytics layer derives CTR, CPC, conversion rate, CPA, and budget utilization.
The test autopilot supports intervals from five minutes to one day, editable deterministic trigger thresholds, an immediate first run when enabled, and a decision history that records which trigger matched and why.
Editable trigger values can only tighten the approved Gate 0 thresholds.
Test automation settings and the decision ledger are stored in `runs/ui-test-automation.sqlite3`.
The dashboard exposes exactly one report download action, and it produces a standalone HTML file.
The main mode reads real production data through three allowlisted operations: Direct Reports `get`, Direct Campaigns `get`, and Metrika Statistics `get`.
The main dashboard streams confirmed backend stage transitions so the operator sees Direct, Metrika, analytics, recommendation, and the disabled execution boundary as they complete.
The current production reader accepts a unified campaign whose search strategy exposes a real weekly spend limit.
It reads the campaign time zone from Direct and queries Metrika with the matching UTC offset so daily rows use the same calendar boundary.
It calculates metrics, creates a recommendation, and writes JSON and standalone HTML reports under `runs/ui-*/`.
Because the read-only APIs do not establish a trusted optimization baseline or change author, the main report marks this first snapshot as partial and routes the recommendation to human review instead of proposing a financial change.
The main mode does not create an approval, invoke an executor, expose a write-capable transport method, or permit write requests.
If any trusted binding or read credential is missing, the main mode fails closed and does not fall back to fixture data.

The P0 production candidate is developed and validated separately under `sites/p0-production/`. Its `mox-adv.p0.application` query/command contract is the single authority for P0 state transitions, revisions, evidence lineage, Campaign Strategy, Recommendation Set, Campaign Drafts and external outcomes; rendering surfaces consume the contract's workflow truth table. The module is intentionally absent from the Integrated Prototype until its production refinement and E2E acceptance are complete; every module at `/prototype/mox-adv` remains a browser-only Test Scenario. Following the project-wide AI-first rule, the candidate researches permitted sources and prepares business artifacts autonomously, then creates one real campaign only after an exact Human Decision Gate and requires an explicit `SUSPENDED` readback before child writes; it never calls `Campaigns.resume`.

Copy the non-secret configuration template to the local user configuration directory and replace the campaign and goal identifiers.
The Direct client login and the single Metrika counter ID come from `.env`.

```shell
mkdir -p ~/.config/mox-adv
cp config/production-read.example.json ~/.config/mox-adv/production-read.json
```

Copy the local binding template, fill all four original Yandex variables, and restrict the file to the current user.
The dashboard reads only `YANDEX_DIRECT_OAUTH_TOKEN`, `YANDEX_DIRECT_CLIENT_LOGIN`, `YANDEX_METRICA_OAUTH_TOKEN`, and `YANDEX_METRICA_COUNTER_IDS` directly from `.env`; it does not import the file into the process environment.
The current linked analysis accepts exactly one positive counter ID in `YANDEX_METRICA_COUNTER_IDS` and fails closed if the variable contains a list.
The repository ignores `.env` and `.env.*`, while `.env.example` remains tracked without values.
The Metrika token must have the `metrika:read` scope.

```shell
cp .env.example .env
chmod 600 .env
```

Use `Ctrl+C` in the terminal to stop the UI.

## Temporary client demo

Start the complete Dashboard and publish it through an on-demand HTTPS tunnel.

```shell
scripts/mox-adv-demo-site
```

The command prints a temporary public URL that can be shared with a client.
The public page uses the same local Dashboard state and keeps every configured Yandex integration available, including the read-only Direct campaign view.
There is no separate login or isolated demo database, so every visitor shares the current local state.
The Python server remains bound to `127.0.0.1`; only the selected port is forwarded by the SSH tunnel.
Press `Ctrl+C` to stop both processes and invalidate the public URL.
A new URL is generated the next time the command starts.
If the free tunnel renews its address while running, the command prints the replacement URL.

## Vercel client demo

Link the repository to a Vercel project and create a private Blob store in the same region as the Python Function.

```shell
vercel link
vercel blob create-store mox-adv-state \
  --access private \
  --region iad1 \
  --yes \
  --environment production \
  --environment preview
```

Add `YANDEX_DIRECT_OAUTH_TOKEN`, `YANDEX_DIRECT_CLIENT_LOGIN`, `YANDEX_METRICA_OAUTH_TOKEN`, `YANDEX_METRICA_COUNTER_IDS`, and `MOX_ADV_PRODUCTION_READ_JSON` as encrypted Production and Preview variables.
The Blob integration injects `BLOB_READ_WRITE_TOKEN`; never commit or print any of these values.
Deploy the production version.

```shell
vercel --prod
```

The Vercel runtime restores the shared Dashboard snapshot from private Blob storage before API requests and stores a new snapshot after state-changing requests.
This preserves test campaigns, decision history, and other local file-backed state across Python Function instances.
All visitors use the same unauthenticated demonstration state.
The Yandex integration remains read-only and continues to reject external write requests.

## Docker run

Build the local image.

```shell
./scripts/mox-adv-host build
```

Run the fixture through the host launcher.

```shell
./scripts/mox-adv-host run-fixture --run-id docker-bootstrap-001
```

The launcher starts the container with no network, a read-only root filesystem, no Linux capabilities, and no privilege escalation.
The bootstrap does not require a credential and does not read macOS Keychain.
The optional `--credential-profile DIRECT_PROD_READ` argument resolves the exact Gate 0 Keychain binding, reads one credential with the macOS `security` command, and passes it through an ephemeral standard-input pipe.
The bootstrap validates and clears that channel without putting the credential in environment variables, command-line arguments, logs, artifacts, or Docker metadata.
The local fixture does not use the credential for an external request.
The container image does not include the macOS `security` utility.

## Read-only OBSERVE run

Run the linked Direct and Metrika fixture through the read-only connector contracts.

```shell
.venv/bin/mox-adv observe-fixture --run-id observe-001
```

The command validates trusted scope, period, UTC, attribution, freshness, watermarks, daily grain, and the snapshot fingerprint.
It creates the same three immutable run artifacts and includes the complete `IntegratedPerformanceSnapshot` in `result.json`.
The Russian report shows the calculated metrics and comparability status.
The OBSERVE path does not create a write-proposal and does not invoke an executor.
The fixture contains a read-only baseline, but its campaign identifier is removed before the decision-facing snapshot is created.
The internal `read_observe_snapshot` path accepts the versioned Direct Reports, Direct campaign-state, and Metrika read connectors with an explicit trusted scope.
Those connectors expose typed read queries and share no write-capable transport operation.

## Safety boundary

Both executable fixture paths use simulated evidence and have no external write egress.
The bootstrap and OBSERVE fixture connectors read local closed-schema JSON objects with at most 1,000 records.
The policy and executor both fail closed if an operation would gain external write egress.
No test contacts Yandex or another external service.

## Tests

Run the complete standard-library test suite.

```shell
PYTHONPATH=src python3 -m unittest discover -s tests
```

Run the opt-in real Docker smoke test when Docker is available.

```shell
MOX_ADV_RUN_DOCKER_TESTS=1 PYTHONPATH=src python3 -m unittest tests.test_docker_boundary
```

The integration test substitutes a temporary fake Keychain command and never reads a real credential.

## Final read-only E2E

Install the Playwright dependency and Chromium once.

```shell
python3 -m pip install --requirement requirements-e2e.txt
python3 -m playwright install chromium
```

Run the two prototype modules through the local E2E harness.

```shell
PYTHONPATH=src:. python3 -m mox_adv.cli readonly-e2e \
  --run-id readonly-e2e-1 \
  --runs-dir runs
```

Run the command again with a new run identifier and compare `stability-fingerprint.json`.
The analytics and optimization workflow uses linked local analytics, the deterministic model fixture, policy, Approval, Mandate, fake readback, monitoring, impact evaluation, idempotency, and the durable kill switch.
The campaign and goal workflow uses the fake campaign saga, fake compensation, candidate-goal lifecycle, Playwright local interception, technical verification, rejection, and fake cleanup rollback.
The Python process rejects non-loopback connection and connectionless socket operations.
Playwright routes HTTP requests, intercepts the Metrica event locally, and keeps every WebSocket route disconnected from an external server.
The external egress recorder accepts only an exact Direct Reports read through `DIRECT_PROD_READ`; the default E2E run does not load that credential or perform a real read.
Every write-class method and `reachGoal` remains fake or locally intercepted.
The final report contains exactly the fourteen normative capabilities and does not claim `CONTROLLED_PILOT` evidence.
