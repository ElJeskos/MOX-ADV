from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from examples.reference_client.requests import metrika_provider_read
from mox_adv.module_api.v1 import (
    ModuleRequestV1,
    analysis_request_fingerprint_v1,
)
from mox_adv.module_api.v1.replay_store import (
    AnalysisReplayPendingError,
    SqliteAnalysisReplayStoreV1,
)


class SqliteAnalysisReplayStoreTests(unittest.TestCase):
    def test_claim_never_expires_without_explicit_operator_recovery(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "analysis-replays.sqlite3"
            first_process = SqliteAnalysisReplayStoreV1(path)
            restarted_process = SqliteAnalysisReplayStoreV1(path)
            request = ModuleRequestV1.from_dict(metrika_provider_read())
            binding = {
                "module_id": "YANDEX_METRIKA",
                "idempotency_key": request.idempotency_key,
                "request_fingerprint": analysis_request_fingerprint_v1(
                    request
                ),
            }

            self.assertIsNone(
                first_process.bind_or_read(
                    **binding,
                    claim_token="first-owner",
                )
            )
            with self.assertRaises(AnalysisReplayPendingError):
                restarted_process.bind_or_read(
                    **binding,
                    claim_token="second-owner",
                )

            self.assertTrue(
                restarted_process.recover_abandoned_claim(**binding)
            )
            self.assertIsNone(
                restarted_process.bind_or_read(
                    **binding,
                    claim_token="second-owner",
                )
            )


if __name__ == "__main__":
    unittest.main()
