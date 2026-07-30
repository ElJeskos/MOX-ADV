# MOX-ADV release distributions

## Release set

MOX-ADV publishes three user-facing distributions.

`mox-adv-metrika` is the independently installable headless Metrika module.

`mox-adv-direct` is the independently installable headless Direct module.

`mox-adv-paired` installs the two exact standalone editions and adds only the existing paired composition and Dashboard.

`mox-adv-core` is an internal shared runtime and is not a fourth user-facing module.

Every artifact in one release set has the same exact semantic version.

The standalone distributions pin `mox-adv-core` to that exact version, and the paired distribution pins both standalone distributions to that exact version.

Mixed release-set versions in one virtual environment are unsupported.

Use separate virtual environments when two customers or deployments need different release versions.

## Compatibility contract

| Surface | Release 1.0.x contract | Compatibility rule |
| --- | --- | --- |
| User distributions | `mox-adv-direct`, `mox-adv-metrika`, and `mox-adv-paired` | All installed MOX-ADV distributions in one environment use the same exact version. |
| Internal runtime | `mox-adv-core` | The version must exactly match each installed standalone distribution. |
| HTTP/JSON API | `1.0.0` | Patch releases must remain backward-compatible with the published v1 OpenAPI document. |
| Request and result schemas | `module-request-v1` and `module-result-v1` | Existing required fields, operations, response statuses, and response fields cannot be removed or narrowed in a patch release. |
| Python | CPython `>=3.9` on supported macOS and Linux hosts | Every target Python and operating-system combination must pass the clean-wheel release E2E suite before publication. |
| Durable analysis replay | `analysis-replay-v1` | Release 1.0.x reads and replays the same SQLite state across a patch upgrade and rollback. |
| Decision records | `module-decision-record-v1` | Records remain customer-owned external state and are not removed by package operations. |
| Support diagnostics | `support-diagnostics-v1` | Fields contain compatibility and readiness metadata but never credential values. |

The release pipeline must compare the candidate OpenAPI document with the previously published document before publication.

Run the repository compatibility checker with the immutable published baseline and the candidate document.

```shell
baseline_file="$(mktemp)"
trap 'rm -f "$baseline_file"' EXIT
git show 0d8ea21:openapi/module-api-v1.openapi.json > "$baseline_file"
python3 scripts/check_module_openapi_compatibility.py \
  "$baseline_file" \
  openapi/module-api-v1.openapi.json
```

Commit `0d8ea21` is the immutable Module API v1 baseline for release 1.0.0.

A breaking API change requires a new API major version and cannot ship as a 1.0.x patch.

A durable-state schema change requires an explicit migration, backup, compatibility, and rollback design and cannot silently reuse the `analysis-replay-v1` name.

## Clean installation

Install each customer deployment in its own virtual environment.

The examples use a local release wheelhouse so installation does not resolve an unintended package from the network.

The paired wheelhouse must contain the verified `playwright==1.59.0` Python distribution and its transitive dependencies in addition to the four MOX-ADV release artifacts.

The Chromium provisioning command may download a browser, so an offline deployment must pre-populate the supported Playwright browser cache or use its approved internal artifact mirror.

Install and start standalone Metrika.

```shell
python3 -m venv .venv-metrika
.venv-metrika/bin/python -m pip install \
  --no-index \
  --find-links ./wheelhouse \
  mox-adv-metrika==1.0.0
mkdir -p -m 700 ./customer-state/metrika
.venv-metrika/bin/mox-adv-metrika serve \
  --environment PRODUCTION \
  --state-dir ./customer-state/metrika \
  --bind 127.0.0.1 \
  --port 8801
```

Install and start standalone Direct.

```shell
python3 -m venv .venv-direct
.venv-direct/bin/python -m pip install \
  --no-index \
  --find-links ./wheelhouse \
  mox-adv-direct==1.0.0
mkdir -p -m 700 ./customer-state/direct
.venv-direct/bin/mox-adv-direct serve \
  --environment PRODUCTION \
  --state-dir ./customer-state/direct \
  --bind 127.0.0.1 \
  --port 8802
```

The standalone servers expose `POST /v1/runs`, `GET /healthz`, `GET /diagnostics`, and `GET /openapi.json` on loopback only.

An integrator sends a `ModuleRequestV1` JSON object to `POST /v1/runs` and receives a `ModuleResultV1` JSON object.

The published request and result details are available from the running module at `/openapi.json`.

Use the customer-owned [`examples/reference_client`](../examples/reference_client/README.md) implementation for complete Direct and Metrika request examples instead of copying provider-specific code into the customer ecosystem.

Standalone modules do not install a Dashboard, webhook consumer, queue, CRM connector, or non-technical onboarding UI.

Install and start the paired edition.

```shell
python3 -m venv .venv-paired
.venv-paired/bin/python -m pip install \
  --no-index \
  --find-links ./wheelhouse \
  mox-adv-paired==1.0.0
.venv-paired/bin/python -m playwright install chromium
.venv-paired/bin/mox-adv-paired ui \
  --port 8878 \
  --runs-dir ./customer-state/paired-runs \
  --no-open
```

The existing paired Dashboard remains available at `http://127.0.0.1:8878/`.

The paired wheel depends on the released standalone wheels and does not contain copied Direct or Metrika provider implementation.

The paired release pins the Playwright version that passed its visual contract, and a Playwright upgrade requires a new MOX-ADV patch release with the same browser regression evidence.

## External configuration and state

Keep configuration, environment files, durable state, and run artifacts outside the virtual environment.

The package manager owns only files inside the virtual environment.

MOX-ADV package installation, upgrade, rollback, and uninstall never remove an external state or configuration path.

The standalone state directory must be accessible only to its owner.

The state directory contains `analysis-replays.sqlite3` and the `decision-records` directory after requests are processed.

Stop the module before copying, restoring, or moving its durable state.

Do not copy a live SQLite database.

Production provider-owned reads require both the non-secret configuration path and the provider-specific environment-file path.

```shell
.venv-metrika/bin/mox-adv-metrika serve \
  --environment PRODUCTION \
  --state-dir ./customer-state/metrika \
  --configuration ./customer-config/metrika-production-read.json \
  --environment-file ./customer-secrets/.env.metrika-read \
  --bind 127.0.0.1 \
  --port 8801
```

Metrika resolves only Metrika read credentials, and Direct resolves only Direct read credentials.

Production write credentials are not part of any release configuration.

Every production write attempt is blocked before credential resolution and HTTP egress.

## Support diagnostics

Run diagnostics with the same trusted environment, state path, and optional provider-read paths that the service will use.

```shell
.venv-metrika/bin/mox-adv-metrika diagnostics \
  --environment PRODUCTION \
  --state-dir ./customer-state/metrika
```

The command writes one `support-diagnostics-v1` JSON object to standard output.

The object identifies the edition, distribution version, exact core version, API version, OpenAPI SHA-256 digest, Python version and supported range, trusted environment, provider-read readiness, durable-state schema and health, and production write policy.

An existing protected state directory without a replay database reports `status = READY` and `integrity = NOT_INITIALIZED` without creating the database.

An initialized replay database reports `integrity = OK` only after the read-only SQLite quick check and expected-schema check succeed.

`write_credentials` must be an empty list in production diagnostics.

Credential names may be reported as readiness checks, but credential values, tokens, client-login values, and environment-file contents must never appear.

The same redacted object is available from `GET /diagnostics` while a standalone server is running.

Support should collect the diagnostics JSON, the exact command line with secret values removed, the operating-system version, and the failing request correlation or idempotency key.

Support should never request a token or a copy of an environment file.

## Patch upgrade

Back up the external configuration and stopped durable state before changing the package environment.

Keep the previous wheelhouse available until the release is accepted.

Upgrade the user-facing distribution by exact version, which also resolves the matching exact core version.

```shell
.venv-metrika/bin/python -m pip install \
  --no-index \
  --find-links ./wheelhouse \
  --upgrade \
  mox-adv-metrika==1.0.1
```

Run diagnostics after installation and verify that `distribution_version` and `core_version` are both `1.0.1`.

Start the service with the unchanged external state directory.

Replay a previously completed safe idempotency request and verify that the returned `ModuleResultV1` is unchanged.

Only then resume normal traffic.

The paired edition is upgraded as one exact release set.

```shell
.venv-paired/bin/python -m pip install \
  --no-index \
  --find-links ./wheelhouse \
  --upgrade \
  mox-adv-paired==1.0.1
```

Do not upgrade only one provider inside a paired environment.

## Rollback

Stop the service before rollback.

Restore the external state backup only if the release notes declare that the newer release wrote a different durable-state schema.

Release 1.0.x keeps `analysis-replay-v1`, so a 1.0.1 to 1.0.0 rollback reuses the same stopped state directory.

Reinstall the previous exact user-facing version from the retained wheelhouse.

```shell
.venv-metrika/bin/python -m pip install \
  --no-index \
  --find-links ./wheelhouse \
  --upgrade \
  --force-reinstall \
  mox-adv-metrika==1.0.0
```

Run diagnostics and verify that `distribution_version` and `core_version` both match the rollback version.

Start the service with the unchanged external state directory and replay the same safe idempotency request before resuming traffic.

If the state schema reported by diagnostics is not supported by the rollback release, stop and restore the matching stopped backup instead of starting the old binary.

## Uninstall

Stop the service before uninstalling its distribution.

Uninstalling paired removes only paired composition and Dashboard files because pip deliberately leaves its standalone dependencies installed.

```shell
.venv-paired/bin/python -m pip uninstall mox-adv-paired
```

The Direct and Metrika standalone commands remain available after paired is removed.

Uninstall a standalone distribution only when no paired distribution in the same environment depends on it.

```shell
.venv-direct/bin/python -m pip uninstall mox-adv-direct
```

Removing Direct does not remove Metrika files, and removing Metrika does not remove Direct files.

Remove `mox-adv-core` only after every user-facing MOX-ADV distribution has been removed from that environment.

Package uninstall never deletes the customer-owned configuration, state, decision records, backups, or run artifacts.

Delete or archive those external paths only through the customer's separate data-retention process.

## Release verification

Build every artifact through the isolated release builder.

The builder uses a different temporary egg, build, and wheel tree for every artifact.

It validates pairwise-disjoint installed paths and exact dependency metadata before publishing the completed wheelhouse atomically.

Publication uses the operating system's atomic no-replace rename on supported macOS and Linux hosts.

If another process creates the requested output pathname before publication, or the filesystem cannot provide atomic no-replace semantics, the builder fails closed and leaves the staged candidate unpublished.

```shell
python3 scripts/build_release_distributions.py \
  --version 1.0.1 \
  --output-dir ./wheelhouse-1.0.1
```

The output directory must not already exist.

The resulting `release-manifest.json` records the exact wheel filenames and SHA-256 digests.

The manifest covers the four MOX-ADV artifacts only.

For an install-ready paired offline wheelhouse, download the declared platform-specific Playwright dependency set into the completed directory from the approved package index or mirror.

```shell
python3 -m pip download \
  --dest ./wheelhouse-1.0.1 \
  'playwright==1.59.0'
```

Provision Chromium through the approved Playwright browser mirror or cache described in the clean-install section.

Run the clean-wheel distribution and lifecycle acceptance tests on every supported target.

```shell
PYTHONPATH=src:. python3 -m unittest \
  tests.e2e.test_release_distributions \
  tests.e2e.test_release_lifecycle \
  tests.e2e.test_release_production_safety
```

The release suites verify isolated build ownership, clean installation, exact dependency metadata, diagnostics, secret redaction, production write blocking before credentials and HTTP, a durable 1.0.0 to 1.0.1 upgrade, a 1.0.1 to 1.0.0 rollback, byte-identical replay, uninstall isolation, the installed Dashboard visual states, and preservation of external configuration and state.
