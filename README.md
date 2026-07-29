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
The optional `--keychain-service` argument makes the host launcher read one credential with the macOS `security` command and pass it through an ephemeral standard-input pipe.
The bootstrap validates and clears that channel without putting the credential in environment variables, command-line arguments, logs, artifacts, or Docker metadata.
The local fixture does not use the credential for an external request.
The container image does not include the macOS `security` utility.

## Safety boundary

The only executable profile in this slice is `SIMULATION`.
The fixture connector reads a local closed-schema JSON object with at most 1,000 records.
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
