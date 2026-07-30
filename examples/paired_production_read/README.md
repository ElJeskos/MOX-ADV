# Split paired production configuration

The paired Dashboard reads three independent JSON files and never falls back to the removed combined Yandex configuration.
Copy each example to the corresponding path under `config/`, replace the stored identifiers, and keep OAuth values only in the provider-specific environment files.

- `paired-production-read.example.json` becomes `config/paired-production-read.json`.
- `direct-production-read.example.json` becomes `config/direct-production-read.json`.
- `metrika-production-read.example.json` becomes `config/metrika-production-read.json`.

The Direct and Metrika files must name the same campaign because that identifier is the explicit link between the two provider observations.
The paired file owns only cross-provider context, period selection, and the read-only baseline.
It contains no provider credentials.

The default `.env.direct-read` names are:

```dotenv
YANDEX_DIRECT_OAUTH_TOKEN=replace-with-read-only-direct-token
YANDEX_DIRECT_CLIENT_LOGIN=replace-with-direct-client-login
```

The default `.env.metrika-read` name is:

```dotenv
YANDEX_METRIKA_OAUTH_TOKEN=replace-with-read-only-metrika-token
```

Production composition exposes only the three allowlisted read operations.
Changing actions remain available only through an explicitly trusted TEST composition.

## One-shot migration from the retired combined files

Run the migration once from the repository root when `config/yandex-production-read.json` and `.env` still contain the retired combined production-read configuration.

```shell
python3 scripts/migrate_yandex_production_read.py
```

The command validates the complete legacy JSON schema and all three required Yandex environment values before writing anything.
It refuses to start a new transaction if any split output already exists without its marker, preserves the legacy `.env` permissions on both provider-specific environment files, and keeps both legacy inputs unchanged.
If the process is interrupted after its transaction marker is durable, rerunning the same command verifies completed files and safely installs only the missing outputs.
Recovery refuses changed legacy inputs or mismatched outputs and never overwrites them.
The command never removes an installed output during error handling, so an external replacement cannot be deleted by rollback.
After success, the durable marker remains as a transaction receipt and makes repeated verification of the same migration idempotent.
An abrupt operating-system termination can leave a mode-preserving hidden transaction temporary file; recovery does not scan and delete such paths because it cannot prove that another process has not replaced them.
There is no runtime fallback to the retired combined files.
