from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from examples.reference_client.client import ModuleHttpClientV1
from examples.reference_client.requests import (
    direct_customer_evidence,
    direct_execute_proposal,
    direct_plan_intent,
    direct_provider_read,
    metrika_provider_read,
)
from mox_adv.control_state import AuthenticatedPrincipal, DurableControlState
from mox_adv.direct_action import DirectActionRuntimeV1
from mox_adv.environment import ExecutionEnvironment
from mox_adv.fake_write_adapter import FakeWriteAdapter
from mox_adv.module_api.v1 import HttpJsonModuleAdapterV1
from mox_adv.modules.direct import DirectModuleV1
from mox_adv.modules.metrika import MetrikaModuleV1
from mox_adv.monitoring import MonitoringStore
from mox_adv.proposal_store import ImmutableProposalStore
from tests.e2e.test_standalone_direct_module import (
    ActionAuthorizedDirectReader,
    RecordingAuthorizedDirectReader,
)
from tests.e2e.test_standalone_metrika_module import (
    RecordingAuthorizedMetrikaReader,
)

ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = ROOT / "openapi" / "module-api-v1.openapi.json"


class _ModuleApiServer:
    def __init__(self, adapter: HttpJsonModuleAdapterV1) -> None:
        self._adapter = adapter
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                if self.path != "/v1/runs":
                    self.send_error(404)
                    return
                length = int(self.headers["Content-Length"])
                payload = json.loads(self.rfile.read(length))
                response = owner._adapter.handle(payload)
                body = json.dumps(response.body).encode("utf-8")
                self.send_response(response.status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )

    @property
    def base_url(self) -> str:
        address = self._server.server_address
        host = str(address[0])
        port = int(address[1])
        return f"http://{host}:{port}"

    def __enter__(self) -> "_ModuleApiServer":
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()


class _OneTransientFailureMetrikaReader(RecordingAuthorizedMetrikaReader):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def read_metrika_report(self, connection_id: str, query: Any) -> Any:
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("temporary provider failure")
        return super().read_metrika_report(connection_id, query)


class ReferenceHttpClientE2ETests(unittest.TestCase):
    def test_calls_standalone_metrika_over_real_http_and_consumes_v1_result(
        self,
    ) -> None:
        reader = RecordingAuthorizedMetrikaReader()
        adapter = HttpJsonModuleAdapterV1(
            MetrikaModuleV1(
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
                provider_reader=reader,
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        )
        openapi = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))

        with _ModuleApiServer(adapter) as server:
            client = ModuleHttpClientV1.from_openapi(
                base_url=server.base_url,
                document=openapi,
            )
            result = client.invoke(metrika_provider_read())

        self.assertEqual("module-result-v1", result.schema_version)
        self.assertEqual("YANDEX_METRIKA", result.module_id)
        self.assertEqual("PARTIAL", result.status)
        self.assertEqual([], result.errors)
        self.assertEqual(1, len(reader.calls))

    def test_http_read_retry_replays_one_result_without_a_second_provider_read(
        self,
    ) -> None:
        reader = RecordingAuthorizedMetrikaReader()
        adapter = HttpJsonModuleAdapterV1(
            MetrikaModuleV1(
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
                provider_reader=reader,
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        )
        openapi = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
        payload = metrika_provider_read()

        with _ModuleApiServer(adapter) as server:
            client = ModuleHttpClientV1.from_openapi(
                base_url=server.base_url,
                document=openapi,
            )
            first = client.invoke(payload)
            retried = client.invoke(payload)

        self.assertEqual(first.body, retried.body)
        self.assertEqual(1, len(reader.calls))

    def test_http_read_idempotency_key_cannot_be_rebound(self) -> None:
        reader = RecordingAuthorizedMetrikaReader()
        adapter = HttpJsonModuleAdapterV1(
            MetrikaModuleV1(
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
                provider_reader=reader,
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        )
        openapi = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
        first_payload = metrika_provider_read()
        conflicting_payload = metrika_provider_read()
        conflicting_payload["objective"] = {
            "code": "GROW_VOLUME",
            "description": "A different request cannot reuse the first key.",
        }

        with _ModuleApiServer(adapter) as server:
            client = ModuleHttpClientV1.from_openapi(
                base_url=server.base_url,
                document=openapi,
            )
            client.invoke(first_payload)
            conflict = client.invoke(conflicting_payload)

        self.assertEqual("REJECTED", conflict.status)
        self.assertEqual(
            "CONTRACT_VALIDATION_FAILED",
            conflict.errors[0].code,
        )
        self.assertIn("idempotency_key", conflict.errors[0].message)
        self.assertEqual(1, len(reader.calls))

    def test_retryable_http_failure_reuses_the_key_and_caches_one_read_result(
        self,
    ) -> None:
        reader = _OneTransientFailureMetrikaReader()
        adapter = HttpJsonModuleAdapterV1(
            MetrikaModuleV1(
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
                provider_reader=reader,
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        )
        openapi = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
        payload = metrika_provider_read()

        with _ModuleApiServer(adapter) as server:
            client = ModuleHttpClientV1.from_openapi(
                base_url=server.base_url,
                document=openapi,
                max_attempts=2,
            )
            recovered = client.invoke(payload)
            replayed = client.invoke(payload)

        self.assertEqual("PARTIAL", recovered.status)
        self.assertEqual(recovered.body, replayed.body)
        self.assertEqual(2, reader.attempts)
        self.assertEqual(1, len(reader.calls))

    def test_calls_standalone_direct_provider_read_over_the_same_http_contract(
        self,
    ) -> None:
        reader = RecordingAuthorizedDirectReader()
        adapter = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
                provider_reader=reader,
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        )
        openapi = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))

        with _ModuleApiServer(adapter) as server:
            client = ModuleHttpClientV1.from_openapi(
                base_url=server.base_url,
                document=openapi,
            )
            result = client.invoke(direct_provider_read())

        self.assertEqual("YANDEX_DIRECT", result.module_id)
        self.assertEqual("PARTIAL", result.status)
        self.assertEqual(1, len(reader.report_calls))
        self.assertEqual(1, len(reader.state_calls))

    def test_submits_customer_evidence_and_consumes_provenance_and_typed_error(
        self,
    ) -> None:
        adapter = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                )
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        )
        openapi = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))

        with _ModuleApiServer(adapter) as server:
            client = ModuleHttpClientV1.from_openapi(
                base_url=server.base_url,
                document=openapi,
            )
            result = client.invoke(direct_customer_evidence())
            invalid = direct_customer_evidence()
            invalid["oauth_token"] = "must-not-cross-the-contract"
            rejected = client.invoke(invalid)

        provenance = result.body["provenance"]
        self.assertEqual("SUCCEEDED", result.status)
        self.assertEqual("CUSTOMER_EVIDENCE", provenance[0]["source_type"])
        self.assertEqual(
            "reference-direct-evidence-1",
            provenance[0]["evidence_id"],
        )
        self.assertEqual("REJECTED", rejected.status)
        self.assertEqual(
            "CONTRACT_VALIDATION_FAILED",
            rejected.errors[0].code,
        )
        self.assertFalse(rejected.errors[0].retryable)
        self.assertNotIn(
            "must-not-cross-the-contract",
            rejected.errors[0].message,
        )

    def test_production_direct_intent_returns_proposal_then_dry_run_only(
        self,
    ) -> None:
        now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        policy = json.loads(
            (ROOT / "config" / "gate0-policy.json").read_text(encoding="utf-8")
        )
        openapi = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            state = DurableControlState(Path(temporary) / "control.sqlite3")
            runtime = DirectActionRuntimeV1(
                policy=policy,
                state=state,
                proposal_store=ImmutableProposalStore(
                    Path(temporary) / "proposals"
                ),
                trigger_store=MonitoringStore(
                    Path(temporary) / "monitoring.sqlite3"
                ),
                test_adapter=None,
                environment=ExecutionEnvironment.PRODUCTION,
            )
            adapter = HttpJsonModuleAdapterV1(
                DirectModuleV1(
                    clock=lambda: now,
                    provider_reader=ActionAuthorizedDirectReader(),
                    action_runtime=runtime,
                ),
                environment=ExecutionEnvironment.PRODUCTION,
            )
            with _ModuleApiServer(adapter) as server:
                client = ModuleHttpClientV1.from_openapi(
                    base_url=server.base_url,
                    document=openapi,
                )
                planned = client.invoke(
                    direct_plan_intent(environment="PRODUCTION")
                )
                proposal_id = planned.body["proposal"]["proposal_id"]
                dry_run = client.invoke(
                    direct_execute_proposal(
                        proposal_id=proposal_id,
                        environment="PRODUCTION",
                    )
                )

        self.assertEqual("SUCCEEDED", planned.status)
        self.assertEqual("DRY_RUN", planned.body["proposal"]["status"])
        self.assertEqual("BLOCKED", dry_run.status)
        self.assertEqual(
            "PRODUCTION_WRITE_FORBIDDEN",
            dry_run.errors[0].code,
        )
        self.assertEqual("DRY_RUN", dry_run.body["proposal"]["status"])
        self.assertIsNone(dry_run.body["execution_result"])

    def test_test_direct_intent_executes_exactly_once_across_http_retry(
        self,
    ) -> None:
        now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        policy = json.loads(
            (ROOT / "config" / "gate0-policy.json").read_text(encoding="utf-8")
        )
        openapi = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            state = DurableControlState(Path(temporary) / "control.sqlite3")
            write_adapter = FakeWriteAdapter(
                initial_state={
                    (
                        "sim-organization:sim-connection:sim-direct-account:"
                        "campaign-7:INCREASE_WEEKLY_BUDGET"
                    ): 2_000_000_000
                }
            )
            runtime = DirectActionRuntimeV1(
                policy=policy,
                state=state,
                proposal_store=ImmutableProposalStore(
                    Path(temporary) / "proposals"
                ),
                trigger_store=MonitoringStore(
                    Path(temporary) / "monitoring.sqlite3"
                ),
                test_adapter=write_adapter,
                environment=ExecutionEnvironment.TEST,
            )
            adapter = HttpJsonModuleAdapterV1(
                DirectModuleV1(
                    clock=lambda: now,
                    provider_reader=ActionAuthorizedDirectReader(),
                    action_runtime=runtime,
                ),
                environment=ExecutionEnvironment.TEST,
            )
            with _ModuleApiServer(adapter) as server:
                client = ModuleHttpClientV1.from_openapi(
                    base_url=server.base_url,
                    document=openapi,
                )
                planned = client.invoke(direct_plan_intent(environment="TEST"))
                proposal_id = planned.body["proposal"]["proposal_id"]
                state.grant_approval(
                    proposal_id=proposal_id,
                    expires_at=now.replace(minute=15),
                    reason="Approve the exact reference-client TEST action.",
                    principal=AuthenticatedPrincipal(
                        identity="sviridov",
                        authentication="authenticated_macos_user",
                    ),
                    now=now,
                )
                execute = direct_execute_proposal(
                    proposal_id=proposal_id,
                    environment="TEST",
                )
                applied = client.invoke(execute)
                retried = client.invoke(execute)

        self.assertEqual("APPLIED", applied.body["execution_result"]["status"])
        self.assertTrue(applied.body["execution_result"]["applied"])
        self.assertEqual(
            "ALREADY_PROCESSED",
            retried.body["execution_result"]["status"],
        )
        self.assertEqual(1, write_adapter.write_calls)


if __name__ == "__main__":
    unittest.main()
