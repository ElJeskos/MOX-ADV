from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from mox_adv.control_state import AuthenticatedPrincipal
from mox_adv.ui_server import build_server


class StubDashboardAuthenticator:
    @staticmethod
    def authenticate() -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            identity="sviridov",
            authentication="authenticated_macos_user",
        )

    @classmethod
    def elevated_reauthenticate(cls) -> AuthenticatedPrincipal:
        return cls.authenticate()


class UiV2DashboardTests(unittest.TestCase):
    def test_operator_can_see_every_v2_control_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            server = build_server(
                port=0,
                runs_root=Path(temporary),
                authenticator=StubDashboardAuthenticator(),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 1100})
                    page.goto(
                        f"http://127.0.0.1:{server.server_port}",
                        wait_until="networkidle",
                    )

                    self.assertEqual(
                        [
                            "OBSERVE",
                            "RECOMMEND",
                            "APPROVAL REQUIRED",
                            "BOUNDED AUTONOMY",
                        ],
                        [
                            value.strip()
                            for value in page.locator(
                                "#operating-modes button"
                            ).all_inner_texts()
                        ],
                    )
                    self.assertTrue(
                        page.get_by_role(
                            "heading",
                            name="Полномочия и аварийная остановка",
                        ).is_visible()
                    )
                    self.assertTrue(
                        page.get_by_role(
                            "heading",
                            name="Campaign и Goal lifecycle",
                        ).is_visible()
                    )
                    self.assertTrue(
                        page.get_by_role(
                            "heading",
                            name="Impact evaluation",
                        ).is_visible()
                    )
                    self.assertTrue(
                        page.get_by_role(
                            "heading",
                            name="Evidence и готовность Gate",
                        ).is_visible()
                    )
                    self.assertEqual(
                        14,
                        page.locator("#capability-matrix [data-capability]").count(),
                    )
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_localhost_api_runs_safe_workflows_and_returns_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            server = build_server(port=0, runs_root=root)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    request = playwright.request.new_context(
                        base_url=f"http://127.0.0.1:{server.server_port}"
                    )

                    control = request.get("/api/control-plane")
                    self.assertTrue(control.ok)
                    self.assertEqual(
                        4,
                        len(control.json()["operating_modes"]),
                    )
                    selected = request.post(
                        "/api/control-plane/mode",
                        data={"mode": "RECOMMEND"},
                    )
                    self.assertTrue(selected.ok)
                    self.assertEqual("RECOMMEND", selected.json()["selected"])

                    hostile = request.post(
                        "/api/control-plane/mode",
                        headers={
                            "Content-Type": "text/plain",
                            "Origin": "https://attacker.example",
                        },
                        data=json.dumps({"mode": "BOUNDED_AUTONOMY"}),
                    )
                    self.assertEqual(403, hostile.status)
                    self.assertEqual(
                        "CROSS_ORIGIN_REQUEST_REJECTED",
                        hostile.json()["reason_code"],
                    )

                    campaign = request.post("/api/workflows/campaign")
                    self.assertTrue(campaign.ok)
                    campaign_run = campaign.json()
                    self.assertEqual("APPLIED", campaign_run["status"])
                    internal_result = request.get(
                        "/api/evidence-runs/" + campaign_run["run_id"] + "/result.json"
                    )
                    self.assertEqual(404, internal_result.status)

                    evidence = request.post("/api/evidence/run")
                    self.assertTrue(evidence.ok)
                    self.assertEqual(14, len(evidence.json()["capabilities"]))
                    run_id = evidence.json()["run_id"]
                    markdown_report = request.get(
                        f"/api/evidence-runs/{run_id}/report.md"
                    )
                    self.assertEqual(404, markdown_report.status)
                    html_report = request.get(
                        f"/api/evidence-runs/{run_id}/acceptance-report.html"
                    )
                    self.assertTrue(html_report.ok)
                    self.assertIn(
                        "text/html",
                        html_report.headers["content-type"],
                    )
                    request.dispose()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_operator_controls_modes_safety_workflows_and_evidence_in_browser(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            server = build_server(
                port=0,
                runs_root=Path(temporary),
                authenticator=StubDashboardAuthenticator(),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 1100})
                    page.goto(
                        f"http://127.0.0.1:{server.server_port}",
                        wait_until="networkidle",
                    )

                    page.get_by_role("button", name="RECOMMEND", exact=True).click()
                    page.get_by_text(
                        "Proposal создаётся без применения",
                        exact=False,
                    ).wait_for()
                    page.reload(wait_until="networkidle")
                    self.assertEqual(
                        "true",
                        page.get_by_role(
                            "button",
                            name="RECOMMEND",
                            exact=True,
                        ).get_attribute("aria-pressed"),
                    )

                    page.get_by_role(
                        "button",
                        name="Аварийно остановить",
                    ).click()
                    page.get_by_text("Kill switch активирован", exact=False).wait_for()
                    page.locator("#kill-release-confirmation").fill("RELEASE")
                    page.get_by_role(
                        "button",
                        name="Снять блокировку",
                    ).click()
                    page.locator("#control-plane-message").get_by_text(
                        "Kill switch снят",
                        exact=False,
                    ).wait_for()

                    page.get_by_role(
                        "button",
                        name="Запустить безопасную симуляцию",
                    ).click()
                    page.get_by_text(
                        "Campaign lifecycle завершён: APPLIED",
                        exact=True,
                    ).wait_for(timeout=15_000)
                    self.assertEqual(
                        8,
                        page.locator("#campaign-workflow-steps .workflow-step").count(),
                    )

                    page.get_by_role(
                        "button",
                        name="Проверить технически",
                    ).click()
                    page.get_by_text(
                        "Техническая проверка VERIFIED",
                        exact=False,
                    ).wait_for(timeout=15_000)
                    self.assertFalse(
                        page.get_by_role(
                            "button",
                            name="Подтвердить смысл",
                        ).is_disabled()
                    )
                    page.get_by_role("button", name="Отклонить").click()
                    page.get_by_text(
                        "Goal lifecycle завершён: REJECTED",
                        exact=True,
                    ).wait_for(timeout=15_000)
                    self.assertEqual(
                        7,
                        page.locator("#goal-workflow-steps .workflow-step").count(),
                    )

                    page.get_by_label("Сценарий наблюдения").select_option(
                        "IMPACT_CPA_WORSE_ROLLBACK"
                    )
                    page.get_by_role("button", name="Оценить результат").click()
                    page.locator("#impact-result").get_by_text(
                        "ROLLBACK CHANGE",
                        exact=True,
                    ).wait_for()

                    page.get_by_role(
                        "button",
                        name="Запустить полный тестовый контур",
                    ).click()
                    page.get_by_text(
                        "Полный тестовый контур завершён",
                        exact=False,
                    ).wait_for(timeout=30_000)
                    self.assertEqual(
                        14,
                        page.locator("#capability-matrix [data-capability]").count(),
                    )
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_operator_approves_exact_test_proposal_before_fake_execution(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            server = build_server(port=0, runs_root=Path(temporary))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 1100})
                    page.goto(
                        f"http://127.0.0.1:{server.server_port}",
                        wait_until="networkidle",
                    )
                    self.assertTrue(
                        page.get_by_role(
                            "button",
                            name="Подтвердить точный proposal",
                        ).is_disabled()
                    )
                    page.get_by_role("tab", name="Тестовый").click()
                    page.get_by_role(
                        "button",
                        name="APPROVAL REQUIRED",
                    ).click()
                    page.get_by_role(
                        "button",
                        name="Запустить тестовый цикл",
                    ).click()
                    page.get_by_text(
                        "Ожидает точного Approval",
                        exact=False,
                    ).wait_for()
                    first_proposal = page.locator(
                        "#approval-facts dd"
                    ).first.inner_text()
                    self.assertEqual(
                        "Не выполняется",
                        page.locator('[data-step="apply"] .step-state').inner_text(),
                    )

                    page.get_by_role(
                        "button",
                        name="Подтвердить точный proposal",
                    ).click()
                    page.get_by_text(
                        "Точный Approval выдан",
                        exact=False,
                    ).wait_for(timeout=15_000)
                    self.assertEqual(
                        "AVAILABLE",
                        page.locator("#approval-state").inner_text(),
                    )
                    self.assertNotIn(
                        "readback",
                        page.locator("#execution-line").inner_text(),
                    )

                    page.get_by_role(
                        "button",
                        name="Запустить тестовый цикл",
                    ).click()
                    page.locator("#approval-state").get_by_text(
                        "Ожидает решения",
                        exact=True,
                    ).wait_for(timeout=15_000)
                    second_proposal = page.locator(
                        "#approval-facts dd"
                    ).first.inner_text()
                    self.assertNotEqual(first_proposal, second_proposal)
                    self.assertTrue(
                        page.get_by_role(
                            "button",
                            name="Применить подтверждённое",
                        ).is_disabled()
                    )
                    self.assertFalse(
                        page.get_by_role(
                            "button",
                            name="Подтвердить точный proposal",
                        ).is_disabled()
                    )

                    page.get_by_role(
                        "button",
                        name="Подтвердить точный proposal",
                    ).click()
                    page.get_by_text(
                        "Точный Approval выдан",
                        exact=False,
                    ).wait_for(timeout=15_000)
                    page.locator("#revoke-approval").click()
                    page.get_by_text(
                        "Approval отозван",
                        exact=False,
                    ).wait_for(timeout=15_000)
                    self.assertEqual(
                        "REVOKED",
                        page.locator("#approval-state").inner_text(),
                    )

                    page.get_by_role(
                        "button",
                        name="Подтвердить точный proposal",
                    ).click()
                    page.get_by_text(
                        "Точный Approval выдан",
                        exact=False,
                    ).wait_for(timeout=15_000)
                    page.get_by_role(
                        "button",
                        name="Применить подтверждённое",
                    ).click()
                    page.get_by_text(
                        "Точный Approval использован",
                        exact=False,
                    ).wait_for(timeout=15_000)
                    self.assertIn(
                        "readback",
                        page.locator("#execution-line").inner_text(),
                    )
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_operator_runs_bounded_test_cycle_with_active_mandate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            server = build_server(port=0, runs_root=Path(temporary))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 1100})
                    page.goto(
                        f"http://127.0.0.1:{server.server_port}",
                        wait_until="networkidle",
                    )
                    page.get_by_role("tab", name="Тестовый").click()
                    page.get_by_role(
                        "button",
                        name="Выдать тестовый Mandate",
                    ).click()
                    page.get_by_text("Mandate активирован", exact=False).wait_for()
                    page.get_by_role(
                        "button",
                        name="BOUNDED AUTONOMY",
                    ).click()

                    values = {
                        "scenario-impressions": "5000",
                        "scenario-clicks": "100",
                        "scenario-conversions": "3",
                        "scenario-visits": "100",
                        "scenario-spend": "4000",
                        "scenario-budget": "10000",
                        "scenario-baseline-spend": "3000",
                        "scenario-baseline-conversions": "3",
                    }
                    for element_id, value in values.items():
                        page.locator(f"#{element_id}").fill(value)

                    page.get_by_role(
                        "button",
                        name="Запустить тестовый цикл",
                    ).click()
                    page.locator("#execution-line").get_by_text(
                        "readback",
                        exact=False,
                    ).wait_for(timeout=15_000)
                    self.assertIn(
                        "Уменьшить поисковую ставку",
                        page.locator("#decision-title").inner_text(),
                    )
                    self.assertIn(
                        "readback",
                        page.locator("#execution-line").inner_text(),
                    )
                    self.assertIn(
                        "1 / 1",
                        page.locator("#mandate-facts").inner_text(),
                    )
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()


if __name__ == "__main__":
    unittest.main()
