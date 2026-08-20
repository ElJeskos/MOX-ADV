from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from mox_adv.control_state import AuthenticatedPrincipal
from mox_adv.ui_server import build_server
from mox_adv.ui_service import UiRunService
from tests.test_yandex_read import (
    DIRECT_TOKEN,
    METRIKA_TOKEN,
    RecordingHttpClient,
    build_test_production_reader,
    prepare_production_read_inputs,
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


def fill_autopilot_safe_scenario(page: Page) -> None:
    page.locator("#scenario-spend").fill("12000")
    page.locator("#scenario-conversions").fill("10")
    page.locator("#scenario-budget").fill("20000")
    page.locator(".advanced-metrics summary").click()
    page.locator("#scenario-baseline-spend").fill("10000")
    page.locator("#scenario-baseline-conversions").fill("10")


class UiV2DashboardTests(unittest.TestCase):
    def test_temporary_public_demo_accepts_tunnel_origin_and_keeps_full_ui(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            server = build_server(
                port=0,
                runs_root=Path(temporary),
                authenticator=StubDashboardAuthenticator(),
                public_demo=True,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection(
                    "127.0.0.1",
                    server.server_port,
                    timeout=5,
                )
                body = json.dumps({"expected_revision": 0})
                connection.request(
                    "POST",
                    "/api/campaigns",
                    body=body,
                    headers={
                        "Content-Type": "application/json",
                        "Host": "client-demo.lhr.life",
                        "Origin": "https://client-demo.lhr.life",
                    },
                )
                response = connection.getresponse()
                self.assertEqual(201, response.status)
                self.assertEqual(2, json.loads(response.read())["total"])
                connection.close()

                rejected = http.client.HTTPConnection(
                    "127.0.0.1",
                    server.server_port,
                    timeout=5,
                )
                rejected.request(
                    "POST",
                    "/api/campaigns",
                    body=json.dumps({"expected_revision": 0}),
                    headers={
                        "Content-Type": "application/json",
                        "Host": "client-demo.lhr.life",
                        "Origin": "https://unrelated.example",
                    },
                )
                rejected_response = rejected.getresponse()
                self.assertEqual(403, rejected_response.status)
                rejected_response.read()
                rejected.close()

                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    page.goto(
                        f"http://127.0.0.1:{server.server_port}/campaign",
                        wait_until="networkidle",
                    )
                    page.get_by_text(
                        "Публичная демонстрация",
                        exact=True,
                    ).wait_for()
                    self.assertTrue(
                        page.locator("#campaign-source-direct").is_visible()
                    )
                    page.get_by_role(
                        "button",
                        name="Новая кампания",
                    ).click()
                    page.wait_for_function(
                        "() => document.querySelectorAll("
                        "'#campaign-list tr').length === 3"
                    )
                    self.assertEqual(3, page.locator("#campaign-list tr").count())
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_operator_launches_selected_test_campaign_from_campaign_page(
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
                    page_errors: list[str] = []
                    page.on(
                        "pageerror",
                        lambda error: page_errors.append(str(error)),
                    )
                    base_url = f"http://127.0.0.1:{server.server_port}"
                    page.goto(f"{base_url}/campaign", wait_until="networkidle")

                    with page.expect_response(
                        lambda response: (
                            response.request.method == "POST"
                            and response.url == f"{base_url}/api/campaigns"
                        )
                    ) as create_response:
                        page.get_by_role(
                            "button",
                            name="Новая кампания",
                            exact=True,
                        ).click()
                    selected_draft_id = create_response.value.json()["selected"][
                        "draft_id"
                    ]
                    launch = page.get_by_role(
                        "button",
                        name="Запустить тестовую кампанию",
                        exact=True,
                    )
                    self.assertTrue(launch.is_visible())
                    page.get_by_label(
                        "Название кампании",
                        exact=True,
                    ).fill("Отдельная тестовая кампания")
                    self.assertTrue(launch.is_disabled())
                    self.assertEqual(
                        "Сначала сохраните изменения",
                        page.locator("#campaign-launch-title").inner_text(),
                    )
                    page.get_by_role(
                        "button",
                        name="Сохранить",
                        exact=True,
                    ).click()
                    page.get_by_text(
                        "Черновик сохранён. Реальная кампания не изменена.",
                        exact=True,
                    ).wait_for()
                    self.assertEqual(
                        "ЧЕРНОВИК",
                        page.locator("#campaign-status-badge").inner_text(),
                    )

                    with page.expect_response(
                        lambda response: (
                            response.request.method == "POST"
                            and response.url.endswith(
                                f"/api/campaigns/{selected_draft_id}/launch"
                            )
                        )
                    ) as response_info:
                        launch.click()
                    response = response_info.value
                    self.assertTrue(response.ok)
                    result = response.json()
                    self.assertEqual("APPLIED", result["status"])
                    self.assertFalse(result["external_write_sent"])
                    self.assertEqual(
                        selected_draft_id,
                        result["exact_diff"]["after"]["draft_id"],
                    )
                    self.assertEqual(
                        1,
                        response.request.post_data_json["expected_revision"],
                    )

                    page.get_by_role(
                        "heading",
                        name="Тестовая кампания запущена",
                        exact=True,
                    ).wait_for()
                    launch_status = page.locator("#campaign-launch-status")
                    self.assertIn("8 из 8 этапов", launch_status.inner_text())
                    self.assertIn(
                        "Внешних изменений нет",
                        launch_status.inner_text(),
                    )
                    self.assertIn(result["run_id"], launch_status.inner_text())
                    self.assertEqual(
                        "ТЕСТ ЗАПУЩЕН",
                        page.locator("#campaign-status-badge").inner_text(),
                    )

                    page.reload(wait_until="networkidle")
                    page.get_by_role(
                        "heading",
                        name="Тестовая кампания запущена",
                        exact=True,
                    ).wait_for()
                    self.assertIn(result["run_id"], launch_status.inner_text())
                    self.assertEqual(
                        "ТЕСТ ЗАПУЩЕН",
                        page.locator("#campaign-status-badge").inner_text(),
                    )
                    self.assertEqual([], page_errors)
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_operator_verifies_and_approves_selected_test_goal(self) -> None:
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
                    base_url = f"http://127.0.0.1:{server.server_port}"
                    request = playwright.request.new_context(base_url=base_url)
                    draft = request.get("/api/campaigns").json()["selected"]
                    draft_id = draft["draft_id"]

                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 1100})
                    page.goto(f"{base_url}/campaign", wait_until="networkidle")

                    page.get_by_role(
                        "heading",
                        name="Проверка цели Метрики",
                    ).wait_for(timeout=2000)
                    verify = page.get_by_role(
                        "button",
                        name="Проверить тестовую цель",
                        exact=True,
                    )
                    self.assertTrue(verify.is_enabled())

                    with page.expect_response(
                        lambda response: (
                            response.request.method == "POST"
                            and response.url
                            == (f"{base_url}/api/campaigns/{draft_id}/goal/technical")
                        )
                    ) as technical_response:
                        verify.click()
                    technical = technical_response.value.json()
                    self.assertEqual(
                        "AWAITING_SEMANTIC_DECISION",
                        technical["status"],
                    )
                    self.assertEqual("VERIFIED", technical["technical_status"])
                    self.assertEqual(
                        1,
                        technical["technical_evidence"]["emitted_count"],
                    )
                    self.assertFalse(technical["external_write_sent"])

                    page.get_by_role(
                        "heading",
                        name="Симуляция технической проверки завершена",
                    ).wait_for()
                    lifecycle = page.locator("#campaign-goal-lifecycle")
                    self.assertIn(
                        "1 смоделированное событие",
                        lifecycle.inner_text(),
                    )
                    self.assertIn(
                        "Симуляция доставки подтверждена",
                        lifecycle.inner_text(),
                    )
                    self.assertIn("SIMULATED", lifecycle.inner_text())

                    with page.expect_response(
                        lambda response: (
                            response.request.method == "POST"
                            and response.url
                            == (f"{base_url}/api/campaigns/{draft_id}/goal/decision")
                        )
                    ) as decision_response:
                        page.get_by_role(
                            "button",
                            name="Подтвердить смысл цели",
                            exact=True,
                        ).click()
                    decision = decision_response.value.json()
                    self.assertEqual("APPROVED", decision["status"])
                    self.assertEqual("APPROVE", decision["semantic_decision"])
                    self.assertFalse(decision["external_write_sent"])

                    page.get_by_role(
                        "heading",
                        name="Смысл тестовой цели подтверждён",
                    ).wait_for()
                    self.assertIn(
                        "Период обучения",
                        lifecycle.inner_text(),
                    )
                    run_id = lifecycle.locator("#campaign-goal-run-id").inner_text()
                    self.assertEqual(technical["run_id"], run_id)

                    page.reload(wait_until="networkidle")
                    page.get_by_role(
                        "heading",
                        name="Смысл тестовой цели подтверждён",
                    ).wait_for()
                    self.assertEqual(
                        run_id,
                        page.locator("#campaign-goal-run-id").inner_text(),
                    )
                    request.dispose()
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_stale_campaign_revision_cannot_launch(self) -> None:
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
                    page.goto(f"{base_url}/campaign", wait_until="networkidle")

                    catalog = page.request.get(f"{base_url}/api/campaigns").json()
                    draft_id = catalog["selected"]["draft_id"]
                    draft = page.request.get(
                        f"{base_url}/api/campaigns/{draft_id}"
                    ).json()
                    changed_campaign = dict(draft["campaign"])
                    changed_campaign["name"] = "Изменено в другой вкладке"
                    updated = page.request.put(
                        f"{base_url}/api/campaigns/{draft_id}",
                        data={
                            "expected_revision": draft["revision"],
                            "campaign": changed_campaign,
                            "business_goal": draft["business_goal"],
                            "goal_settings": draft["goal_settings"],
                            "ad_groups": draft["ad_groups"],
                        },
                    )
                    self.assertTrue(updated.ok)

                    with page.expect_response(
                        lambda response: (
                            response.request.method == "POST"
                            and response.url.endswith(f"/{draft_id}/launch")
                        )
                    ) as launch_response:
                        page.get_by_role(
                            "button",
                            name="Запустить тестовую кампанию",
                            exact=True,
                        ).click()
                    self.assertEqual(400, launch_response.value.status)
                    page.get_by_role(
                        "heading",
                        name="Тестовый запуск не завершён",
                        exact=True,
                    ).wait_for()
                    self.assertEqual(
                        "NOT_LAUNCHED",
                        page.request.get(
                            f"{base_url}/api/campaigns/{draft_id}/launch"
                        ).json()["launch_status"],
                    )
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_operator_switches_to_real_direct_campaigns_in_read_only_mode(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configuration_path, environment_path = prepare_production_read_inputs(root)
            http_client = RecordingHttpClient()
            reader = build_test_production_reader(
                root,
                configuration_path=configuration_path,
                environment_path=environment_path,
                http_client=http_client,
            )
            server = build_server(
                port=0,
                runs_root=root / "runs",
                authenticator=StubDashboardAuthenticator(),
            )
            server.service = UiRunService(
                root / "runs",
                production_reader=reader,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    page_errors: list[str] = []
                    page.on(
                        "pageerror",
                        lambda error: page_errors.append(str(error)),
                    )
                    base_url = f"http://127.0.0.1:{server.server_port}"
                    page.goto(f"{base_url}/campaign", wait_until="networkidle")

                    page.get_by_role(
                        "tab",
                        name="Яндекс Директ",
                        exact=False,
                    ).click()
                    page.get_by_role(
                        "button",
                        name="Открыть Read only campaign",
                    ).wait_for()

                    self.assertEqual("1", page.locator("#campaign-count").inner_text())
                    self.assertEqual(
                        "ТОЛЬКО ЧТЕНИЕ",
                        page.locator("#campaign-status-badge").inner_text(),
                    )
                    self.assertTrue(page.locator("#campaign-editor").is_hidden())
                    self.assertTrue(
                        page.locator("#campaign-inspector-actions").is_hidden()
                    )
                    self.assertTrue(page.locator("#new-campaign").is_hidden())
                    self.assertTrue(
                        page.locator("#refresh-direct-campaigns").is_visible()
                    )
                    self.assertTrue(
                        page.locator("#direct-campaign-inspector").is_visible()
                    )
                    self.assertEqual(
                        "12345",
                        page.locator("#direct-campaign-id").inner_text(),
                    )
                    self.assertIn(
                        "Режим только для чтения",
                        page.locator("#direct-campaign-inspector").inner_text(),
                    )
                    self.assertEqual([], page_errors)
                    self.assertEqual(1, len(http_client.calls))
                    request = json.loads(
                        bytes(http_client.calls[0]["body"]).decode("utf-8")
                    )
                    self.assertEqual("get", request["method"])
                    self.assertEqual(
                        {},
                        request["params"]["SelectionCriteria"],
                    )
                    self.assertNotIn(
                        DIRECT_TOKEN,
                        page.locator("body").inner_text(),
                    )
                    self.assertNotIn(
                        METRIKA_TOKEN,
                        page.locator("body").inner_text(),
                    )

                    page.get_by_role(
                        "tab",
                        name="Тестовые",
                        exact=False,
                    ).click()
                    self.assertTrue(page.locator("#campaign-editor").is_visible())
                    self.assertTrue(page.locator("#new-campaign").is_visible())
                    self.assertTrue(
                        page.locator("#campaign-inspector-actions").is_visible()
                    )
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_operator_configures_campaign_goals_and_ads_on_one_page(
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
                    page.goto(f"{base_url}/campaign", wait_until="networkidle")

                    self.assertTrue(
                        page.get_by_role(
                            "heading",
                            name="Рекламные кампании",
                            exact=True,
                        ).is_visible()
                    )
                    page.get_by_role(
                        "button",
                        name="Новая кампания",
                    ).click()
                    editor = page.locator("#campaign-editor")
                    editor.get_by_label("Название кампании").fill(
                        "Заявки на консультацию"
                    )
                    editor.get_by_label("Недельный бюджет, ₽").fill("700")
                    editor.get_by_label("Бизнес-цель").fill(
                        "Получать заявки на консультацию"
                    )
                    editor.get_by_label("Целевой CPA, ₽").fill("900")
                    editor.get_by_label("Модель атрибуции").select_option("AUTO")
                    first_goal = editor.locator(".campaign-goal-item").first
                    first_goal.get_by_label("Название цели").fill("Отправлена заявка")
                    first_goal.get_by_label("Селектор на сайте").fill(
                        "#consultation-form"
                    )
                    editor.get_by_role(
                        "button",
                        name="Добавить цель",
                    ).click()
                    second_goal = editor.locator(".campaign-goal-item").nth(1)
                    second_goal.get_by_label("Название цели").fill(
                        "Начато заполнение формы"
                    )
                    second_goal.get_by_label("Событие").fill("form_started")
                    second_goal.get_by_label("Ценность, ₽").fill("250")

                    ad_workspace = editor.locator("#campaign-ad-workspace")
                    ad_workspace.get_by_label("Название группы").fill("Консультации")
                    first_ad = ad_workspace.locator(".campaign-ad-editor")
                    first_ad.get_by_label("Заголовок 1").fill(
                        "Консультация специалиста"
                    )
                    first_ad.get_by_role(
                        "button",
                        name="Добавить заголовок",
                    ).click()
                    first_ad.get_by_label("Заголовок 2").fill("Ответим сегодня")
                    first_ad.get_by_label("Текст 1").fill(
                        "Оставьте заявку — разберём вашу задачу"
                    )
                    first_ad.get_by_label(
                        "Отображаемая ссылка",
                    ).fill("consultation")
                    first_ad.get_by_label("Уточнения").fill(
                        "Без навязчивых звонков\nОтвет в день обращения"
                    )
                    ad_workspace.get_by_role(
                        "button",
                        name="Добавить объявление",
                    ).click()
                    third_ad = ad_workspace.locator(".campaign-ad-editor")
                    third_ad.get_by_label("Заголовок 1").fill(
                        "Третий вариант объявления"
                    )
                    page.get_by_role(
                        "button",
                        name="Сохранить",
                    ).click()
                    page.get_by_text(
                        "Черновик сохранён. Реальная кампания не изменена.",
                        exact=True,
                    ).wait_for()

                    page.reload(wait_until="networkidle")
                    self.assertEqual(
                        "Заявки на консультацию",
                        editor.get_by_label("Название кампании").input_value(),
                    )
                    self.assertEqual(
                        "Получать заявки на консультацию",
                        editor.get_by_label("Бизнес-цель").input_value(),
                    )
                    self.assertEqual(
                        "900",
                        editor.get_by_label("Целевой CPA, ₽").input_value(),
                    )
                    self.assertEqual(
                        "Отправлена заявка",
                        editor.locator(".campaign-goal-item")
                        .first.get_by_label("Название цели")
                        .input_value(),
                    )
                    self.assertEqual(
                        2,
                        editor.locator(".campaign-goal-item").count(),
                    )
                    self.assertEqual(
                        3,
                        editor.locator(".campaign-ad-tab").count(),
                    )
                    editor.locator(".campaign-ad-tab").first.click()
                    self.assertEqual(
                        "Консультация специалиста",
                        editor.locator(".campaign-ad-editor")
                        .get_by_label("Заголовок 1")
                        .input_value(),
                    )
                    self.assertEqual(
                        "ЧЕРНОВИК",
                        page.locator(".campaign-status-badge").inner_text(),
                    )
                    self.assertEqual(2, page.locator("#campaign-list tr").count())

                    page.get_by_role(
                        "button",
                        name="Редактировать Заявки с сайта",
                    ).click()
                    page.get_by_role("button", name="Удалить", exact=True).click()
                    page.get_by_role(
                        "button",
                        name="Удалить кампанию",
                    ).click()
                    page.get_by_text(
                        "Кампания удалена из локального списка.",
                        exact=True,
                    ).wait_for()
                    self.assertEqual(1, page.locator("#campaign-list tr").count())
                    self.assertEqual(
                        "Заявки на консультацию",
                        editor.get_by_label("Название кампании").input_value(),
                    )

                    page.get_by_role(
                        "link",
                        name="Запуск цикла",
                        exact=True,
                    ).click()
                    page.get_by_role(
                        "button",
                        name="Получить предложение",
                    ).click()
                    page.locator("#campaign-goal-summary").wait_for(
                        state="visible",
                    )
                    goal_summary = page.locator("#campaign-goal-summary").inner_text()
                    self.assertIn(
                        "Получать заявки на консультацию",
                        goal_summary,
                    )
                    self.assertIn("≤ 900 ₽", goal_summary.replace("\xa0", " "))
                    self.assertIn(
                        "Учитывается при выборе решения",
                        goal_summary,
                    )

                    webvisor = page.locator(".main-nav .nav-disabled")
                    self.assertEqual("Вебвизор", webvisor.inner_text())
                    self.assertEqual(
                        "SPAN", webvisor.evaluate("(node) => node.tagName")
                    )
                    self.assertEqual("true", webvisor.get_attribute("aria-disabled"))
                    self.assertEqual(
                        "none",
                        webvisor.evaluate(
                            "(node) => getComputedStyle(node).pointerEvents"
                        ),
                    )
                    current_url = page.url
                    webvisor.evaluate("(node) => node.click()")
                    self.assertEqual(current_url, page.url)
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

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
                    self.assertEqual(8, page.locator(".main-nav > *").count())
                    self.assertEqual(
                        0,
                        page.get_by_role("link", name="Стратегия").count(),
                    )
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
                        "Кампания": (
                            "/campaign",
                            "Рекламные кампании",
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

                    webvisor = page.locator(".main-nav .nav-disabled")
                    self.assertEqual("Вебвизор", webvisor.inner_text())
                    self.assertTrue(
                        webvisor.evaluate("(node) => node.matches(':last-child')")
                    )
                    self.assertIsNone(webvisor.get_attribute("href"))
                    self.assertEqual(
                        "none",
                        webvisor.evaluate(
                            "(node) => getComputedStyle(node).pointerEvents"
                        ),
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

                    campaign_catalog = request.get("/api/campaigns").json()
                    selected_campaign = campaign_catalog["selected"]
                    campaign = request.post(
                        "/api/workflows/campaign",
                        data={
                            "draft_id": selected_campaign["draft_id"],
                            "expected_revision": selected_campaign["revision"],
                        },
                    )
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

    def test_operator_uses_campaign_history_control_and_evidence_pages(
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
                        name="Кампания",
                        exact=True,
                    ).click()
                    self.assertEqual(
                        0,
                        page.locator(".workflow-layout").count(),
                    )
                    self.assertEqual(
                        0,
                        page.get_by_role(
                            "heading",
                            name="Безопасная симуляция черновика",
                            exact=True,
                        ).count(),
                    )

                    page.get_by_role(
                        "link",
                        name="История",
                        exact=True,
                    ).click()
                    self.assertEqual(
                        "true",
                        page.get_by_role(
                            "tab",
                            name="История решений",
                            exact=True,
                        ).get_attribute("aria-selected"),
                    )
                    page.get_by_role(
                        "tab",
                        name="Исход решений",
                        exact=True,
                    ).click()
                    self.assertIn(
                        "Выберите «Посмотреть исход»",
                        page.locator("#decision-outcome").inner_text(),
                    )
                    self.assertEqual(
                        0,
                        page.get_by_label("Сценарий наблюдения").count(),
                    )

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

    def test_history_has_tabs_compact_default_pagination_and_linked_outcome(
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
                    base_url = f"http://127.0.0.1:{server.server_port}"
                    request = playwright.request.new_context(base_url=base_url)
                    for _ in range(11):
                        response = request.post(
                            "/api/runs",
                            data={"mode": "test"},
                        )
                        self.assertTrue(response.ok)

                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    page.goto(
                        f"{base_url}/cycle",
                        wait_until="domcontentloaded",
                    )
                    page.get_by_role(
                        "button",
                        name="Получить предложение",
                    ).click()
                    page.get_by_text(
                        "Предложение готово и ещё не применено",
                        exact=True,
                    ).wait_for()
                    page.get_by_role(
                        "button",
                        name="Согласиться и применить",
                    ).click()
                    page.get_by_role(
                        "heading",
                        name="Предложение применено",
                    ).wait_for()

                    latest = request.get("/api/test-history?page=1&page_size=1").json()[
                        "items"
                    ][0]
                    linked = request.post(
                        "/api/workflows/impact",
                        data={
                            "fixture": "IMPACT_CPA_IMPROVED_KEEP",
                            "source_run_id": latest["run_id"],
                        },
                    )
                    self.assertTrue(linked.ok)

                    page.get_by_role(
                        "link",
                        name="История",
                        exact=True,
                    ).click()
                    decisions_tab = page.get_by_role(
                        "tab",
                        name="История решений",
                        exact=True,
                    )
                    outcomes_tab = page.get_by_role(
                        "tab",
                        name="Исход решений",
                        exact=True,
                    )
                    self.assertEqual(
                        "true", decisions_tab.get_attribute("aria-selected")
                    )
                    self.assertEqual(
                        "false", outcomes_tab.get_attribute("aria-selected")
                    )
                    self.assertEqual(
                        3,
                        page.locator("#decision-history article").count(),
                    )

                    page.get_by_role(
                        "button",
                        name="Показать весь журнал",
                    ).click()
                    self.assertEqual(
                        10,
                        page.locator("#decision-history article").count(),
                    )
                    self.assertIn(
                        "Страница 1 из 2",
                        page.locator("#history-page-status").inner_text(),
                    )
                    page.get_by_role(
                        "button",
                        name="Следующая страница",
                    ).click()
                    self.assertEqual(
                        3,
                        page.locator("#decision-history article").count(),
                    )
                    self.assertIn(
                        "Страница 2 из 2",
                        page.locator("#history-page-status").inner_text(),
                    )
                    page.get_by_role(
                        "button",
                        name="Предыдущая страница",
                    ).click()

                    page.locator("#decision-history article").first.get_by_role(
                        "button",
                        name="Посмотреть исход",
                    ).click()
                    self.assertEqual(
                        "true", outcomes_tab.get_attribute("aria-selected")
                    )
                    outcome = page.locator("#decision-outcome")
                    page.get_by_role(
                        "heading",
                        name="Сравнение до и после",
                    ).wait_for()
                    self.assertIn(
                        "принятое решение",
                        outcome.inner_text().lower(),
                    )
                    self.assertIn("До изменения", outcome.inner_text())
                    self.assertIn("После изменения", outcome.inner_text())
                    self.assertIn("1 000 ₽", outcome.inner_text())
                    self.assertIn("750 ₽", outcome.inner_text())
                    self.assertIn("4", outcome.inner_text())
                    self.assertIn("6", outcome.inner_text())
                    self.assertIn("Сохранить изменение", outcome.inner_text())

                    request.dispose()
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_blocked_approval_is_never_presented_as_applied(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            server = build_server(port=0, runs_root=Path(temporary))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    base_url = f"http://127.0.0.1:{server.server_port}"
                    page.goto(f"{base_url}/cycle", wait_until="networkidle")

                    for selector, value in {
                        "#scenario-impressions": "10000",
                        "#scenario-clicks": "200",
                        "#scenario-visits": "150",
                        "#scenario-conversions": "10",
                        "#scenario-spend": "5000",
                        "#scenario-budget": "5500",
                    }.items():
                        page.locator(selector).fill(value)

                    page.get_by_role(
                        "button",
                        name="Получить предложение",
                    ).click()
                    page.get_by_text(
                        "Предложение готово и ещё не применено",
                        exact=True,
                    ).wait_for()

                    with page.expect_response(
                        lambda response: (
                            response.url == f"{base_url}/api/control-plane/approvals"
                            and response.request.post_data is not None
                            and "apply_latest" in response.request.post_data
                        )
                    ) as response_info:
                        page.get_by_role(
                            "button",
                            name="Согласиться и применить",
                        ).click()

                    payload = response_info.value.json()
                    self.assertEqual("BLOCKED", payload["execution"]["status"])
                    page.get_by_role(
                        "heading",
                        name="Предложение заблокировано",
                    ).wait_for()
                    self.assertEqual(
                        "ЗАБЛОКИРОВАНО",
                        page.locator("#run-status").inner_text(),
                    )
                    self.assertIn(
                        "Лимит денежных изменений превышен",
                        page.locator("#safety-copy").inner_text(),
                    )
                    self.assertNotIn(
                        "применено",
                        page.locator(".workspace").inner_text().casefold(),
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
                    latest_reason = page.locator(
                        "#decision-history article"
                    ).first.inner_text()
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
