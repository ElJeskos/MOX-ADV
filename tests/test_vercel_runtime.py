from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from api.index import handler
from mox_adv.vercel_runtime import (
    PRODUCTION_READ_JSON_VARIABLE,
    VercelStateStore,
    build_vercel_runtime,
)
from tests.test_yandex_read import RecordingHttpClient


def vercel_environment() -> dict[str, str]:
    return {
        "YANDEX_DIRECT_OAUTH_TOKEN": "direct-token",
        "YANDEX_DIRECT_CLIENT_LOGIN": "payplaine-direct",
        "YANDEX_METRICA_OAUTH_TOKEN": "metrika-token",
        "YANDEX_METRICA_COUNTER_IDS": "67890",
        PRODUCTION_READ_JSON_VARIABLE: json.dumps(
            {
                "schema_version": "mox-adv-production-read-v1",
                "organization": "payplaine",
                "connection": "yandex-production",
                "direct_account": None,
                "direct_client_login": None,
                "campaign_id": "12345",
                "metrika_counter_id": None,
                "metrika_goal_id": "54321",
                "currency": "RUB",
                "lookback_days": 1,
            }
        ),
    }


class MemoryBlobResult:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def __bytes__(self) -> bytes:
        return self.content


class MemoryBlobClient:
    def __init__(self) -> None:
        self.content: bytes | None = None

    def get(self, *_args: object, **_kwargs: object) -> MemoryBlobResult:
        if self.content is None:
            raise FileNotFoundError
        return MemoryBlobResult(self.content)

    def put(
        self,
        _path: str,
        content: bytes,
        **_kwargs: object,
    ) -> None:
        self.content = content


class VercelRuntimeTests(unittest.TestCase):
    def test_dashboard_import_does_not_require_browser_e2e_dependencies(
        self,
    ) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = "src:."
        process = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import importlib.abc, sys\n"
                    "class BlockE2ERunner(importlib.abc.MetaPathFinder):\n"
                    "    def find_spec(self, fullname, path, target=None):\n"
                    "        if fullname == 'mox_adv.e2e_runner':\n"
                    "            raise ModuleNotFoundError(fullname)\n"
                    "        return None\n"
                    "sys.meta_path.insert(0, BlockE2ERunner())\n"
                    "import mox_adv.ui_dashboard\n"
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, process.returncode, process.stderr)

    def test_private_snapshot_shares_campaign_state_between_instances(
        self,
    ) -> None:
        client = MemoryBlobClient()
        store = VercelStateStore(token="test-token", client=client)
        with (
            tempfile.TemporaryDirectory() as first_temporary,
            tempfile.TemporaryDirectory() as second_temporary,
        ):
            first_root = Path(first_temporary)
            second_root = Path(second_temporary)
            self.assertFalse(store.restore(first_root))
            first_runtime = build_vercel_runtime(
                environment=vercel_environment(),
                scratch_root=first_root,
                http_client=RecordingHttpClient(),
            )
            current = first_runtime.dashboard.campaign_store.load()
            created = first_runtime.dashboard.campaign_store.create_new(
                expected_revision=int(current["revision"]),
            )
            store.persist(first_root)

            second_runtime_before_restore = build_vercel_runtime(
                environment=vercel_environment(),
                scratch_root=second_root,
                http_client=RecordingHttpClient(),
            )
            self.assertEqual(
                1,
                second_runtime_before_restore.dashboard.campaign_store.catalog()[
                    "total"
                ],
            )
            self.assertTrue(store.restore(second_root))
            second_runtime = build_vercel_runtime(
                environment=vercel_environment(),
                scratch_root=second_root,
                http_client=RecordingHttpClient(),
            )
            self.assertEqual(
                2,
                second_runtime.dashboard.campaign_store.catalog()["total"],
            )
            second_runtime.dashboard.campaign_store.delete(
                str(created["draft_id"]),
                expected_revision=int(created["revision"]),
            )
            store.persist(second_root)

            self.assertTrue(store.restore(first_root))
            restored_runtime = build_vercel_runtime(
                environment=vercel_environment(),
                scratch_root=first_root,
                http_client=RecordingHttpClient(),
            )
            self.assertEqual(
                1,
                restored_runtime.dashboard.campaign_store.catalog()["total"],
            )

    def test_runtime_uses_ephemeral_state_and_environment_yandex_bindings(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = build_vercel_runtime(
                environment=vercel_environment(),
                scratch_root=Path(temporary),
                http_client=RecordingHttpClient(),
            )

            status = runtime.service.status()
            self.assertTrue(status["production_mode"]["ready"])
            catalog = runtime.service.production_campaign_catalog()
            self.assertEqual(1, catalog["total"])
            self.assertEqual("READ_ONLY", catalog["access"])
            self.assertTrue((Path(temporary) / "runs").is_dir())
            self.assertEqual(
                0o600,
                (Path(temporary) / "bindings" / ".env").stat().st_mode & 0o777,
            )

    def test_vercel_handler_restores_route_and_accepts_same_origin_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = build_vercel_runtime(
                environment=vercel_environment(),
                scratch_root=Path(temporary),
                http_client=RecordingHttpClient(),
            )
            from http.server import ThreadingHTTPServer

            with patch("api.index._RUNTIME", runtime):
                server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
                thread = threading.Thread(
                    target=server.serve_forever,
                    daemon=True,
                )
                thread.start()
                try:
                    connection = http.client.HTTPConnection(
                        "127.0.0.1",
                        server.server_port,
                        timeout=5,
                    )
                    connection.request(
                        "GET",
                        "/api/index?__mox_path=/campaign",
                        headers={"Host": "mox-adv.vercel.app"},
                    )
                    response = connection.getresponse()
                    self.assertEqual(200, response.status)
                    self.assertIn(
                        "Публичная демонстрация",
                        response.read().decode("utf-8"),
                    )
                    connection.close()

                    mutation = http.client.HTTPConnection(
                        "127.0.0.1",
                        server.server_port,
                        timeout=5,
                    )
                    mutation.request(
                        "POST",
                        "/api/index?__mox_path=/api/campaigns",
                        body=json.dumps({"expected_revision": 0}),
                        headers={
                            "Content-Type": "application/json",
                            "Host": "mox-adv.vercel.app",
                            "Origin": "https://mox-adv.vercel.app",
                        },
                    )
                    mutation_response = mutation.getresponse()
                    self.assertEqual(201, mutation_response.status)
                    self.assertEqual(
                        2,
                        json.loads(mutation_response.read())["total"],
                    )
                    mutation.close()
                finally:
                    server.shutdown()
                    thread.join(timeout=5)
                    server.server_close()


if __name__ == "__main__":
    unittest.main()
