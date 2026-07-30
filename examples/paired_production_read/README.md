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
