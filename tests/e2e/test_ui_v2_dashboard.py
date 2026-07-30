from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from playwright.sync_api import Page, sync_playwright

import mox_adv.ui_service as ui_service_module
from mox_adv.control_state import AuthenticatedPrincipal, ExecutionStatus
from mox_adv.fake_write_adapter import FakeWriteAdapter
from mox_adv.paired_cycle import execute_paired_direct_test_action
from mox_adv.ui_server import build_server
from mox_adv.ui_service import UiRunService
from tests.e2e.test_release_distributions import _exclusive_dashboard_port

BOUNDED_AUTONOMY_SCENARIO = {
    "impressions": 10_000,
    "clicks": 100,
    "spend_rub": 12_000,
    "visits": 100,
    "conversions": 10,
    "weekly_budget_rub": 20_000,
    "baseline_spend_rub": 10_000,
    "baseline_conversions": 10,
}
BOUNDED_AUTONOMY_TARGET = (
    "sim-organization:sim-connection:sim-direct-account:"
    "sim-campaign:DECREASE_SEARCH_BID"
)


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


class NoProviderContactReader:
    def __init__(self) -> None:
        self.calls = 0

    def collect_snapshot(self, **_kwargs: Any) -> None:
        self.calls += 1
        raise AssertionError("TEST /api/runs contacted a production provider")


class TrustedBoundedTestRunService(UiRunService):
    """Select bounded autonomy only inside the injected E2E composition."""

    mandate_id: str | None = None

    def run(self, mode: str, **kwargs: Any) -> dict[str, Any]:
        if mode == "test":
            if self.mandate_id is None:
                raise AssertionError("The E2E Mandate has not been activated.")
            kwargs["operating_mode"] = "BOUNDED_AUTONOMY"
            kwargs["mandate_id"] = self.mandate_id
        return super().run(mode, **kwargs)


def _post_run(origin: str) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        origin + "/api/runs",
        data=json.dumps(
            {
                "mode": "test",
                "scenario": BOUNDED_AUTONOMY_SCENARIO,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = json.loads(response.read())
        if not isinstance(body, dict):
            raise TypeError("/api/runs did not return a JSON object")
        return response.status, body


def _start_server(server: Any) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _stop_server(server: Any, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()
    if thread.is_alive():
        raise AssertionError("Dashboard server did not stop cleanly")


def fill_autopilot_safe_scenario(page: Page) -> None:
    page.locator("#scenario-spend").fill("12000")
    page.locator("#scenario-conversions").fill("10")
    page.locator("#scenario-budget").fill("20000")
    page.locator(".advanced-metrics summary").click()
    page.locator("#scenario-baseline-spend").fill("10000")
    page.locator("#scenario-baseline-conversions").fill("10")


class UiV2DashboardTests(unittest.TestCase):
    def test_concurrent_bounded_runs_have_one_dispatch_and_stable_applied_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            default_server = build_server(
                port=0,
                runs_root=root / "default",
                authenticator=StubDashboardAuthenticator(),
            )
            default_thread = _start_server(default_server)
            try:
                with sync_playwright() as playwright:
                    request = playwright.request.new_context(
                        base_url=(
                            "http://127.0.0.1:"
                            + str(default_server.server_port)
                        )
                    )
                    default_run = request.post(
                        "/api/runs",
                        data={
                            "mode": "test",
                            "scenario": BOUNDED_AUTONOMY_SCENARIO,
                        },
                    )
                    self.assertEqual(201, default_run.status)
                    self.assertEqual(
                        "APPROVAL_REQUIRED",
                        default_run.json()["operating_mode"],
                    )
                    request.dispose()
            finally:
                _stop_server(default_server, default_thread)

            both_reserved = threading.Barrier(2)
            owner_at_dispatch = threading.Event()
            observer_finished = threading.Event()

            def after_reservation() -> None:
                both_reserved.wait(timeout=5)

            shared_adapter = FakeWriteAdapter(
                initial_state={BOUNDED_AUTONOMY_TARGET: 100_000_000}
            )
            original_apply = shared_adapter.apply

            def apply_after_observer_returns(
                target_key: str,
                command: Any,
            ) -> None:
                owner_at_dispatch.set()
                if not observer_finished.wait(timeout=5):
                    raise AssertionError(
                        "the concurrent observer did not return IN_FLIGHT"
                    )
                original_apply(target_key, command)

            def execute_with_shared_adapter(**kwargs: Any) -> Any:
                kwargs["test_adapter"] = shared_adapter
                return execute_paired_direct_test_action(**kwargs)

            fixed_now = datetime.now(timezone.utc) + timedelta(seconds=1)

            class FixedDateTime(datetime):
                @classmethod
                def now(cls, tz: Any = None) -> FixedDateTime:
                    if tz is None:
                        return cls.fromtimestamp(fixed_now.timestamp())
                    return cls.fromtimestamp(fixed_now.timestamp(), tz)

            provider = NoProviderContactReader()

            with _exclusive_dashboard_port():
                primary = build_server(
                    port=8878,
                    runs_root=root / "primary",
                    authenticator=StubDashboardAuthenticator(),
                    production_reader=provider,
                )
                observer = build_server(
                    port=0,
                    runs_root=root / "observer",
                    authenticator=StubDashboardAuthenticator(),
                    production_reader=provider,
                )
                primary_service = TrustedBoundedTestRunService(
                    root / "primary",
                    production_reader=provider,
                )
                observer_service = TrustedBoundedTestRunService(
                    root / "observer",
                    production_reader=provider,
                )
                primary.service = primary_service
                observer.service = observer_service
                primary_service.configure_bounded_autonomy(
                    primary.dashboard.control_state,
                    primary.dashboard.mandate_authority,
                )
                observer_service.configure_bounded_autonomy(
                    primary.dashboard.control_state,
                    primary.dashboard.mandate_authority,
                )
                primary_thread = _start_server(primary)
                observer_thread = _start_server(observer)
                try:
                    with sync_playwright() as playwright:
                        control = playwright.request.new_context(
                            base_url="http://127.0.0.1:8878"
                        )
                        selected = control.post(
                            "/api/control-plane/mode",
                            data={"mode": "BOUNDED_AUTONOMY"},
                        )
                        self.assertEqual(201, selected.status)
                        mandate = control.post(
                            "/api/control-plane/mandates",
                            data={"action": "issue"},
                        )
                        self.assertEqual(201, mandate.status)
                        mandate_id = str(mandate.json()["mandate_id"])
                        primary_service.mandate_id = mandate_id
                        observer_service.mandate_id = mandate_id
                        control.dispose()

                    authority = primary.dashboard.mandate_authority
                    control_state = primary.dashboard.control_state
                    original_reserve = authority.reserve_execution
                    original_register = control_state.register_prepared_change
                    registration_lock = threading.Lock()

                    def register_prepared_change(*args: Any, **kwargs: Any) -> Any:
                        with registration_lock:
                            return original_register(*args, **kwargs)

                    def reserve_then_wait(
                        *args: Any,
                        **kwargs: Any,
                    ) -> Any:
                        outcome = original_reserve(*args, **kwargs)
                        if outcome[0] == ExecutionStatus.RESERVED:
                            after_reservation()
                        return outcome

                    origins = (
                        "http://127.0.0.1:8878",
                        "http://127.0.0.1:" + str(observer.server_port),
                    )
                    with (
                        patch.object(
                            ui_service_module,
                            "datetime",
                            FixedDateTime,
                        ),
                        patch.object(
                            ui_service_module,
                            "execute_paired_direct_test_action",
                            side_effect=execute_with_shared_adapter,
                        ),
                        patch.object(
                            control_state,
                            "register_prepared_change",
                            side_effect=register_prepared_change,
                        ),
                        patch.object(
                            authority,
                            "reserve_execution",
                            side_effect=reserve_then_wait,
                        ),
                        patch.object(
                            shared_adapter,
                            "apply",
                            side_effect=apply_after_observer_returns,
                        ),
                        ThreadPoolExecutor(max_workers=2) as executor,
                    ):
                        futures = {
                            executor.submit(_post_run, origin)
                            for origin in origins
                        }
                        self.assertTrue(owner_at_dispatch.wait(timeout=5))
                        completed, pending = wait(
                            futures,
                            timeout=5,
                            return_when=FIRST_COMPLETED,
                        )
                        self.assertEqual(1, len(completed))
                        try:
                            first_response = next(iter(completed)).result()
                        finally:
                            observer_finished.set()
                        self.assertEqual(1, len(pending))
                        second_response = next(iter(pending)).result(timeout=5)

                    responses = (first_response, second_response)
                    self.assertEqual([201, 201], sorted(item[0] for item in responses))
                    reports = tuple(item[1] for item in responses)
                    self.assertCountEqual(
                        ["BLOCKED", "APPLIED"],
                        [report["execution"]["status"] for report in reports],
                        json.dumps(
                            [report["execution"] for report in reports],
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    )
                    observer_report = next(
                        report
                        for report in reports
                        if report["execution"]["status"] == "BLOCKED"
                    )
                    self.assertEqual(
                        "EXECUTION_IN_FLIGHT",
                        observer_report["execution"]["reason_code"],
                    )
                    self.assertEqual(
                        1,
                        sum(report["execution"]["write_calls"] for report in reports),
                    )
                    self.assertEqual(1, shared_adapter.write_calls)
                    for report in reports:
                        self.assertEqual("TEST", report["mode"])
                        self.assertEqual(
                            {
                                "direct": "LOCAL_FIXTURE",
                                "metrika": "LOCAL_FIXTURE",
                            },
                            report["sources"],
                        )
                        self.assertFalse(report["execution"]["external_write_sent"])
                        self.assertFalse(report["safety"]["external_write_sent"])
                        self.assertFalse(report["safety"]["credential_loaded"])
                        self.assertEqual([], report["safety"]["read_requests"])

                    with sync_playwright() as playwright:
                        control = playwright.request.new_context(
                            base_url="http://127.0.0.1:8878"
                        )
                        overview = control.get("/api/control-plane")
                        self.assertEqual(200, overview.status)
                        executions = overview.json()["executions"]
                        self.assertEqual(1, len(executions))
                        self.assertEqual("APPLIED", executions[0]["status"])
                        control.dispose()
                    self.assertEqual(0, provider.calls)
                finally:
                    observer_finished.set()
                    _stop_server(observer, observer_thread)
                    _stop_server(primary, primary_thread)

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
