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

The command performs one provider-owned Metrika read, one provider-owned Direct read, one normalized customer-evidence analysis, one deliberately invalid evidence request that returns a typed validation error, and one high-level Direct planning request.
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
The client never automatically retries an `EXECUTE` request after a timeout or lost response.
The operator must reconcile an uncertain write result through the trusted server-side workflow.

The standalone HTTP host uses `HttpJsonModuleAdapterV1.for_durable_host(...)` with an operator-owned SQLite path so successful read results and in-flight ownership survive restarts.
Claims do not expire automatically: this prevents a slow provider read from being duplicated after an arbitrary lease timeout.
After a host crash, an operator must reconcile the provider operation and then call `recover_abandoned_claim(...)` before retrying that key.
The recovery fingerprint is public and reproducible from the original validated request:

```python
from mox_adv.module_api.v1 import (
    ModuleRequestV1,
    SqliteAnalysisReplayStoreV1,
    analysis_request_fingerprint_v1,
)

request = ModuleRequestV1.from_dict(original_payload)
store = SqliteAnalysisReplayStoreV1(replay_path)
released = store.recover_abandoned_claim(
    module_id="YANDEX_METRIKA",
    idempotency_key=request.idempotency_key,
    request_fingerprint=analysis_request_fingerprint_v1(request),
)
```

An operator should record the reconciliation evidence and the boolean `released` result in the host runbook or audit log.
The in-memory replay store is intended only for explicit embedded and test compositions.

The request builders in `requests.py` contain placeholder stored-connection and scope identifiers.
Replace those identifiers with values provisioned by the module operator, without adding credentials or raw provider payloads.
