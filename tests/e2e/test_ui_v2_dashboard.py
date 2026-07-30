from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

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


def fill_autopilot_safe_scenario(page: Page) -> None:
    page.locator("#scenario-spend").fill("12000")
    page.locator("#scenario-conversions").fill("10")
    page.locator("#scenario-budget").fill("20000")
    page.locator(".advanced-metrics summary").click()
    page.locator("#scenario-baseline-spend").fill("10000")
    page.locator("#scenario-baseline-conversions").fill("10")


class UiV2DashboardTests(unittest.TestCase):
    def test_dashboard_uses_separate_desktop_pages_without_operating_modes(
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
                    page = browser.new_page(viewport={"width": 1280, "height": 900})
                    base_url = f"http://127.0.0.1:{server.server_port}"
                    page.goto(f"{base_url}/overview", wait_until="networkidle")

                    self.assertTrue(
                        page.get_by_role(
                            "heading",
                            name="Управление рекламой",
                        ).is_visible()
                    )
                    self.assertEqual(7, page.locator(".main-nav a").count())
                    self.assertEqual(0, page.locator("#operating-modes").count())

                    expected_pages = {
                        "Запуск цикла": (
                            "/cycle",
                            "Получить предложение",
                        ),
                        "Автопилот": ("/autopilot", "Автопилот"),
                        "Правила": ("/rules", "Правила автопилота"),
                        "История": (
                            "/history",
                            "Что было решено и почему",
                        ),
                        "Сценарии": (
                            "/workflows",
                            "Кампания и цель Метрики",
                        ),
                        "Контроль": ("/control", "Аварийная остановка"),
                    }
                    for link_name, (path, heading) in expected_pages.items():
                        page.get_by_role("link", name=link_name, exact=True).click()
                        self.assertEqual(f"{base_url}{path}", page.url)
                        self.assertTrue(
                            page.get_by_role(
                                "heading",
                                name=heading,
                                exact=True,
                            ).first.is_visible()
                        )
                        self.assertEqual(
                            page.evaluate("window.innerWidth"),
                            page.evaluate("document.documentElement.scrollWidth"),
                        )

                    visible_text = page.locator("body").inner_text()
                    for forbidden in (
                        "Approval Required",
                        "Bounded Autonomy",
                        "OBSERVE",
                        "RECOMMEND",
                    ):
                        self.assertNotIn(forbidden, visible_text)
                    self.assertLessEqual(
                        page.locator(".main-nav").evaluate(
                            "(node) => node.getBoundingClientRect().right"
                        ),
                        page.locator(".service-state").evaluate(
                            "(node) => node.getBoundingClientRect().left"
                        ),
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
                        "/api/evidence-runs/"
                        + campaign_run["run_id"]
                        + "/result.json"
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

    def test_operator_uses_safety_workflows_and_evidence_on_their_pages(
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
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    base_url = f"http://127.0.0.1:{server.server_port}"

                    page.goto(f"{base_url}/control", wait_until="networkidle")
                    page.get_by_role(
                        "button",
                        name="Аварийно остановить",
                    ).click()
                    page.locator("#control-plane-message").get_by_text(
                        "Kill switch активирован",
                        exact=False,
                    ).wait_for()
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
                        "link",
                        name="Сценарии",
                        exact=True,
                    ).click()
                    page.get_by_role(
                        "button",
                        name="Запустить безопасную симуляцию",
                    ).click()
                    page.get_by_text(
                        "Проверка кампании завершена успешно.",
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
                        "Техническая проверка завершена.",
                        exact=False,
                    ).wait_for(timeout=15_000)
                    page.get_by_role("button", name="Отклонить").click()
                    page.get_by_text(
                        "Проверка цели завершена: цель отклонена.",
                        exact=True,
                    ).wait_for(timeout=15_000)

                    page.get_by_role(
                        "link",
                        name="История",
                        exact=True,
                    ).click()
                    page.get_by_label("Сценарий наблюдения").select_option(
                        "IMPACT_CPA_WORSE_ROLLBACK"
                    )
                    page.get_by_role("button", name="Оценить результат").click()
                    page.locator("#impact-result").get_by_text(
                        "Откатить изменение",
                        exact=True,
                    ).wait_for()

                    page.get_by_role(
                        "link",
                        name="Контроль",
                        exact=True,
                    ).click()
                    page.get_by_role(
                        "button",
                        name="Проверить весь тестовый цикл",
                    ).click()
                    page.get_by_text(
                        "Самопроверка завершена.",
                        exact=False,
                    ).wait_for(timeout=30_000)
                    self.assertTrue(
                        page.locator("#evidence-report-download").is_visible()
                    )
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_operator_edits_and_accepts_manual_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            server = build_server(port=0, runs_root=Path(temporary))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    page.goto(
                        f"http://127.0.0.1:{server.server_port}/cycle",
                        wait_until="networkidle",
                    )

                    page.get_by_role(
                        "button",
                        name="Получить предложение",
                    ).click()
                    page.get_by_text(
                        "Предложение готово и ещё не применено",
                        exact=True,
                    ).wait_for()
                    self.assertEqual("10", page.locator("#proposal-step").input_value())
                    self.assertEqual("+10%", page.locator("#change-value").inner_text())

                    page.locator("#proposal-step").fill("5")
                    page.get_by_role(
                        "button",
                        name="Сохранить правки",
                    ).click()
                    page.get_by_text(
                        "Правки сохранены. Предложение обновлено.",
                        exact=True,
                    ).wait_for()
                    self.assertEqual("+5%", page.locator("#change-value").inner_text())

                    page.get_by_role(
                        "button",
                        name="Согласиться и применить",
                    ).click()
                    page.get_by_role(
                        "heading",
                        name="Предложение применено",
                    ).wait_for()
                    self.assertFalse(page.locator("#proposal-review").is_visible())
                    self.assertIn(
                        "2 000 ₽ → 2 100 ₽",
                        page.locator("#execution-line")
                        .inner_text()
                        .replace("\N{NO-BREAK SPACE}", " "),
                    )
                    self.assertEqual(1, page.locator(".report-actions a").count())
                    self.assertIn(
                        "HTML",
                        page.locator(".report-actions a").inner_text(),
                    )
                    page.get_by_role(
                        "link",
                        name="История",
                        exact=True,
                    ).click()
                    latest_reason = (
                        page.locator("#decision-history article").first.inner_text()
                    )
                    self.assertNotIn("Approval", latest_reason)
                    self.assertIn(
                        "Предложение подтверждено пользователем",
                        latest_reason,
                    )
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_autopilot_runs_and_applies_on_schedule_without_mode_switch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            server = build_server(port=0, runs_root=Path(temporary))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    page.goto(
                        f"http://127.0.0.1:{server.server_port}/cycle",
                        wait_until="networkidle",
                    )
                    fill_autopilot_safe_scenario(page)

                    page.get_by_role(
                        "link",
                        name="Автопилот",
                        exact=True,
                    ).click()
                    page.get_by_label("Периодичность").select_option("60")
                    page.get_by_role(
                        "button",
                        name="Включить автопилот",
                    ).click()
                    page.get_by_text(
                        "Циклы будут запускаться и применяться автоматически.",
                        exact=False,
                    ).wait_for()
                    page.get_by_text("Следующий запуск:", exact=False).wait_for()

                    page.get_by_role(
                        "link",
                        name="История",
                        exact=True,
                    ).click()
                    latest = page.locator("#decision-history article").first
                    latest.wait_for(timeout=10_000)
                    latest_text = latest.inner_text()
                    self.assertIn("По расписанию", latest_text)
                    self.assertIn("Уменьшить поисковую ставку", latest_text)
                    self.assertIn("Применено", latest_text)
                    self.assertEqual(0, page.locator("#operating-modes").count())
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()


if __name__ == "__main__":
    unittest.main()
