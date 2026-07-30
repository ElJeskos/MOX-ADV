# HTTP/JSON reference client

This example is a customer-owned, headless integration for the standalone Metrika and Direct modules.
It reads the published OpenAPI document and uses only Python's standard HTTP and JSON libraries.
It does not import provider implementations, the MOX-ADV Dashboard, webhooks, queues, or CRM connectors.

Each standalone module exposes the same `POST /v1/runs` operation at its own base URL.
Stored connection identifiers cross the contract, while OAuth tokens, provider endpoints, and trusted target configuration remain server-side.

Run the production read and dry-run flow with:

```bash
PYTHONPATH=. python3 -m examples.reference_client \
  --openapi openapi/module-api-v1.openapi.json \
  --metrika-url http://127.0.0.1:9001 \
  --direct-url http://127.0.0.1:9002
```

The command performs one provider-owned Metrika read, one provider-owned Direct read, one normalized customer-evidence analysis, and one high-level Direct planning request.
Production planning can return a proposal marked `DRY_RUN`, but the example never requests a production write.

TEST execution remains an explicit second step:

```bash
PYTHONPATH=. python3 -m examples.reference_client \
  --openapi openapi/module-api-v1.openapi.json \
  --metrika-url http://127.0.0.1:9101 \
  --direct-url http://127.0.0.1:9102 \
  --environment TEST \
  --execute-approved-test-proposal
```

The exact proposal must already have trusted server-side approval before the TEST execution request is accepted.
Repeating the same execution request preserves its idempotency key, and the durable Direct execution ledger prevents a second write.

The request builders in `requests.py` contain placeholder stored-connection and scope identifiers.
Replace those identifiers with values provisioned by the module operator, without adding credentials or raw provider payloads.
