from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

from playwright.sync_api import APIRequestContext, sync_playwright

from mox_adv.ui_server import build_server

DIRECT_MODULE = {
    "module_id": "YANDEX_DIRECT",
    "module_version": "1.0.0",
}
PAIRED_SCOPE = {
    "organization": "sim-organization",
    "connection": "sim-connection",
    "account": "sim-direct-account",
    "campaign": "sim-campaign",
    "counter": "sim-pilot-counter",
    "goal": "sim-primary-goal",
}
PAIRED_PROGRESS_BEFORE_APPROVAL = [
    {"id": "direct", "label": "Директ", "status": "PASSED"},
    {"id": "metrika", "label": "Метрика", "status": "PASSED"},
    {"id": "analytics", "label": "Анализ", "status": "PASSED"},
    {"id": "recommend", "label": "Решение", "status": "PASSED"},
    {"id": "apply", "label": "Применение", "status": "SKIPPED"},
]
PAIRED_PROGRESS_AFTER_APPROVAL = [
    *PAIRED_PROGRESS_BEFORE_APPROVAL[:-1],
    {"id": "apply", "label": "Применение", "status": "PASSED"},
]


def _post_json(
    request: APIRequestContext,
    path: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = request.post(path, data=payload)
    if response.status != 201:
        raise AssertionError(f"{path} returned {response.status}: {response.text()}")
    value = response.json()
    if not isinstance(value, dict):
        raise TypeError(f"{path} did not return a JSON object")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AssertionError(
            f"The public run did not persist required module evidence: {path.name}"
        )
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} does not contain a JSON object")
    return value


def _get_json(
    request: APIRequestContext,
    path: str,
) -> dict[str, Any]:
    response = request.get(path)
    if response.status != 200:
        raise AssertionError(f"{path} returned {response.status}: {response.text()}")
    value = response.json()
    if not isinstance(value, dict):
        raise TypeError(f"{path} did not return a JSON object")
    return value


class PairedClosedLoopE2ETests(unittest.TestCase):
    def test_dashboard_preserves_the_paired_closed_loop_through_module_contracts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runs_root = Path(temporary)
            server = build_server(port=0, runs_root=runs_root)
            thread = threading.Thread(
                target=server.serve_forever,
                daemon=True,
            )
            thread.start()
            try:
                with sync_playwright() as playwright:
                    request = playwright.request.new_context(
                        base_url=f"http://127.0.0.1:{server.server_port}"
                    )
                    pending = _post_json(
                        request,
                        "/api/runs",
                        {"mode": "test"},
                    )
                    source_run_id = str(pending["run_id"])
                    approval = _post_json(
                        request,
                        "/api/control-plane/approvals",
                        {
                            "action": "grant_latest",
                            "run_id": source_run_id,
                        },
                    )
                    applied = _post_json(
                        request,
                        "/api/control-plane/approvals",
                        {
                            "action": "apply_latest",
                            "run_id": source_run_id,
                        },
                    )
                    published_report = _get_json(
                        request,
                        f"/api/runs/{applied['run_id']}",
                    )
                    impact = _post_json(
                        request,
                        "/api/workflows/impact",
                        {"fixture": "IMPACT_CPA_IMPROVED_KEEP"},
                    )
                    request.dispose()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            self.assertEqual("ui-run-report-v1", pending["schema_version"])
            self.assertEqual("TEST", pending["mode"])
            self.assertEqual("APPROVAL_REQUIRED", pending["operating_mode"])
            self.assertEqual(
                {"direct": "LOCAL_FIXTURE", "metrika": "LOCAL_FIXTURE"},
                pending["sources"],
            )
            self.assertEqual(PAIRED_SCOPE, pending["scope"])
            self.assertEqual(
                {"start": "2026-07-21", "end": "2026-07-27"},
                pending["period"],
            )
            self.assertEqual(
                {
                    "budget_utilization_percent": "95.00",
                    "conversion_rate_percent": "12.00",
                    "cpa_rub": "158.33",
                    "cpc_rub": "19.00",
                    "cpl_rub": "NOT_APPLICABLE",
                    "ctr_percent": "1.00",
                    "pacing_percent": "95.00",
                },
                pending["metrics"],
            )
            self.assertEqual(
                {
                    "action": "INCREASE_WEEKLY_BUDGET",
                    "adapter": "NONE",
                    "after_micros": 2_200_000_000,
                    "approval_id": None,
                    "before_micros": 2_000_000_000,
                    "executor_invoked": False,
                    "external_write_sent": False,
                    "readback_micros": None,
                    "reason_code": "EXACT_APPROVAL_REQUIRED",
                    "relative_step_percent": 10,
                    "status": "PENDING_APPROVAL",
                    "write_calls": 0,
                },
                pending["execution"],
            )
            self.assertEqual(
                PAIRED_PROGRESS_BEFORE_APPROVAL,
                pending["steps"],
            )

            self.assertEqual(
                pending["recommendation"]["proposal_id"],
                approval["proposal_id"],
            )
            self.assertEqual("AVAILABLE", approval["status"])
            self.assertIsNone(approval["used_at"])
            self.assertIsNone(approval["execution_key"])
            self.assertRegex(
                approval["binding_hash"],
                r"^sha256:[0-9a-f]{64}$",
            )
            self.assertEqual(
                {
                    "action": "INCREASE_WEEKLY_BUDGET",
                    "current_value": 2_000_000_000,
                    "diff": {
                        "operation": "INCREASE_WEEKLY_BUDGET",
                        "relative_step_percent": 10,
                    },
                    "risk": "PERFORMANCE_MAY_NOT_IMPROVE",
                    "target_value": 2_200_000_000,
                },
                approval["change"],
            )

            self.assertEqual(source_run_id, applied["source_run_id"])
            self.assertEqual(applied, published_report)
            self.assertEqual(pending["scope"], applied["scope"])
            self.assertEqual(pending["period"], applied["period"])
            self.assertEqual(pending["metrics"], applied["metrics"])
            self.assertEqual(
                pending["recommendation"],
                applied["recommendation"],
            )
            self.assertEqual(
                {
                    "action": "INCREASE_WEEKLY_BUDGET",
                    "adapter": "SEALED_FAKE",
                    "after_micros": 2_200_000_000,
                    "approval_id": approval["approval_id"],
                    "before_micros": 2_000_000_000,
                    "executor_invoked": True,
                    "external_write_sent": False,
                    "readback_micros": 2_200_000_000,
                    "reason_code": None,
                    "relative_step_percent": 10,
                    "status": "APPLIED",
                    "write_calls": 1,
                },
                applied["execution"],
            )
            self.assertEqual(
                PAIRED_PROGRESS_AFTER_APPROVAL,
                applied["steps"],
            )
            self.assertEqual(
                {
                    "adapter": "SEALED_FAKE",
                    "approval": "SIMULATED_EXACT_APPROVAL",
                    "credential_loaded": False,
                    "executor_invoked": True,
                    "external_write_sent": False,
                    "read_requests": [],
                    "write_requests_allowed": False,
                },
                applied["safety"],
            )

            self.assertEqual(
                "dashboard-impact-workflow-v1",
                impact["schema_version"],
            )
            self.assertEqual("IMPACT_EVALUATION", impact["workflow"])
            self.assertEqual("OBSERVED_POST_CHANGE", impact["status"])
            self.assertEqual(
                "KEEP_CHANGE",
                impact["recommended_next_decision"],
            )
            self.assertEqual({"kind": "NONE"}, impact["authority_requirement"])
            self.assertEqual(
                [
                    "OBSERVED_ASSOCIATION_NOT_CAUSAL",
                    "DELAYED_CONVERSION_RISK",
                ],
                impact["risks"],
            )
            self.assertEqual(
                "OBSERVED_ASSOCIATION",
                impact["impact_report"]["effect_classification"],
            )
            self.assertEqual(
                {
                    "baseline": "1000",
                    "improvement": "250",
                    "improvement_percent": "25",
                    "post_change": "750",
                },
                impact["impact_report"]["metric_changes"]["cpa_rub"],
            )
            self.assertEqual(
                "KEEP_CHANGE",
                impact["impact_report"]["next_decision"],
            )

            applied_run = runs_root / str(applied["run_id"])
            direct_module_result = _read_json(applied_run / "direct-module-result.json")
            direct_decision = _read_json(applied_run / "direct-decision-record.json")
            self.assertEqual(DIRECT_MODULE, direct_module_result["module"])
            self.assertEqual("SUCCEEDED", direct_module_result["status"])
            self.assertEqual(
                {
                    "operation_type": "APPLY_OPTIMIZATION",
                    "status": "APPLIED",
                },
                {
                    "operation_type": direct_module_result["execution_result"][
                        "operation_type"
                    ],
                    "status": direct_module_result["execution_result"]["status"],
                },
            )
            self.assertEqual(
                "2200000000",
                direct_module_result["execution_result"]["provider_reference"],
            )
            self.assertEqual("YANDEX_DIRECT", direct_decision["module"]["module_id"])
            self.assertEqual("EXECUTE", direct_decision["operation_kind"])
            self.assertEqual(
                "APPLY_OPTIMIZATION",
                direct_decision["operation_type"],
            )
            self.assertEqual("SUCCEEDED", direct_decision["outcome"])
            self.assertEqual(
                direct_module_result["decision_record_ref"],
                "decision-records/" + direct_decision["decision_id"] + ".json",
            )

            impact_run = runs_root / str(impact["run_id"])
            impact_module_result = _read_json(impact_run / "impact-module-result.json")
            impact_decision = _read_json(impact_run / "impact-decision-record.json")
            self.assertEqual(DIRECT_MODULE, impact_module_result["module"])
            self.assertEqual("SUCCEEDED", impact_module_result["status"])
            self.assertEqual(
                impact["impact_report"],
                impact_module_result["impact_outcome"],
            )
            self.assertEqual("YANDEX_DIRECT", impact_decision["module"]["module_id"])
            self.assertEqual("ANALYZE", impact_decision["operation_kind"])
            self.assertEqual(
                "EVALUATE_IMPACT",
                impact_decision["operation_type"],
            )
            self.assertEqual("SUCCEEDED", impact_decision["outcome"])
            self.assertEqual(
                ["KEEP_CHANGE"],
                impact_decision["reason_codes"],
            )
            self.assertEqual(
                impact_module_result["impact_outcome"],
                impact_decision["facts"]["impact_outcome"],
            )
            self.assertEqual(
                impact_module_result["decision_record_ref"],
                "decision-records/" + impact_decision["decision_id"] + ".json",
            )


if __name__ == "__main__":
    unittest.main()
