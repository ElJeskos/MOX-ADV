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
