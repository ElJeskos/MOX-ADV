from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from mox_adv.ui_server import build_server
from mox_adv.ui_service import UiRunService
from mox_adv.yandex_read import HttpResponse
from tests.test_yandex_read import (
    DIRECT_TOKEN,
    METRIKA_TOKEN,
    RecordingHttpClient,
    build_test_production_reader,
    prepare_production_read_inputs,
)


class ZeroConversionHttpClient(RecordingHttpClient):
    def perform(self, **kwargs: object) -> HttpResponse:
        response = super().perform(**kwargs)
        if "api-metrika.yandex.net" not in str(kwargs["url"]):
            return response
        payload = json.loads(response.body.decode("utf-8"))
        payload["data"][0]["metrics"][1] = 0.0
        return HttpResponse(
            status=response.status,
            headers=response.headers,
            body=json.dumps(payload).encode("utf-8"),
        )


class UiBrowserTests(unittest.TestCase):
    def test_operator_can_run_real_reader_from_dotenv_and_download_report(
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
            server = build_server(port=0, runs_root=root / "runs")
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
                    browser_requests: list[tuple[str, str]] = []
                    page_errors: list[str] = []
                    page.on(
                        "request",
                        lambda request: browser_requests.append(
                            (request.method, request.url)
                        ),
                    )
                    page.on(
                        "pageerror",
                        lambda error: page_errors.append(str(error)),
                    )
                    base_url = f"http://127.0.0.1:{server.server_port}"
                    page.goto(base_url, wait_until="networkidle")

                    page.get_by_role("tab", name="Основной").click()
                    page.get_by_role(
                        "button",
                        name="Запустить read-only анализ",
                    ).click()
                    page.get_by_role(
                        "heading",
                        name="Read-only анализ завершён",
                    ).wait_for()

                    self.assertTrue(page.locator("#report").is_visible())
                    self.assertFalse(page.locator("#blocked-panel").is_visible())
                    self.assertIn(
                        "executor отключён",
                        page.locator("#safety-copy").inner_text(),
                    )
                    self.assertEqual([], page_errors)
                    self.assertEqual(3, len(http_client.calls))
                    self.assertEqual(
                        ["POST", "POST", "GET"],
                        [str(call["method"]) for call in http_client.calls],
                    )
                    self.assertTrue(
                        all(
                            url == base_url or url.startswith(base_url + "/")
                            for _, url in browser_requests
                        ),
                        browser_requests,
                    )
                    self.assertNotIn(
                        DIRECT_TOKEN,
                        page.locator("body").inner_text(),
                    )
                    self.assertNotIn(
                        METRIKA_TOKEN,
                        page.locator("body").inner_text(),
                    )
                    with page.expect_download() as download_info:
                        page.get_by_role(
                            "link",
                            name="Скачать отчёт HTML",
                        ).click()
                    report_path = root / "production-read-only-report.html"
                    download_info.value.save_as(report_path)
                    report_text = report_path.read_text(encoding="utf-8")
                    self.assertIn("Отчёт<br>read-only анализа", report_text)
                    self.assertIn(
                        "Три разрешённых запроса чтения",
                        report_text,
                    )
                    self.assertIn(
                        'External write</dt><dd class="safe">Запрещён',
                        report_text,
                    )
                    self.assertNotIn(DIRECT_TOKEN, report_text)
                    self.assertNotIn(METRIKA_TOKEN, report_text)
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_operator_sees_unavailable_cpa_without_currency_suffix(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configuration_path, environment_path = prepare_production_read_inputs(root)
            reader = build_test_production_reader(
                root,
                configuration_path=configuration_path,
                environment_path=environment_path,
                http_client=ZeroConversionHttpClient(),
            )
            server = build_server(port=0, runs_root=root / "runs")
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
                    page.goto(
                        f"http://127.0.0.1:{server.server_port}",
                        wait_until="networkidle",
                    )
                    page.get_by_role(
                        "button",
                        name="Запустить read-only анализ",
                    ).click()
                    page.locator("#report").wait_for(state="visible")

                    cpa = page.locator(".metric").filter(has_text="CPA")
                    self.assertEqual("Недоступно", cpa.locator("strong").inner_text())
                    self.assertEqual("", cpa.locator("small").inner_text())
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_main_mode_shows_readiness_blockers_before_operator_runs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configuration_path, environment_path = prepare_production_read_inputs(root)
            content = environment_path.read_text(encoding="utf-8")
            environment_path.write_text(
                content.replace(
                    "YANDEX_DIRECT_CLIENT_LOGIN=payplaine-direct",
                    "YANDEX_DIRECT_CLIENT_LOGIN=",
                ),
                encoding="utf-8",
            )
            environment_path.chmod(0o600)
            http_client = RecordingHttpClient()
            reader = build_test_production_reader(
                root,
                configuration_path=configuration_path,
                environment_path=environment_path,
                http_client=http_client,
            )
            server = build_server(port=0, runs_root=root / "runs")
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
                    page.goto(
                        f"http://127.0.0.1:{server.server_port}",
                        wait_until="networkidle",
                    )
                    page.get_by_role("tab", name="Основной").click()

                    page.get_by_role(
                        "heading",
                        name="Требуется настройка",
                    ).wait_for(timeout=2000)

                    self.assertTrue(page.locator("#blocked-panel").is_visible())
                    self.assertTrue(
                        page.get_by_role(
                            "button",
                            name="Запустить read-only анализ",
                        ).is_disabled()
                    )
                    self.assertIn(
                        "YANDEX_DIRECT_CLIENT_LOGIN",
                        page.locator("#blocked-panel").inner_text(),
                    )
                    self.assertEqual([], http_client.calls)
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_main_mode_stays_disabled_after_server_readiness_rejection(
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
            server = build_server(port=0, runs_root=root / "runs")
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
                    page.goto(
                        f"http://127.0.0.1:{server.server_port}",
                        wait_until="networkidle",
                    )
                    run_button = page.get_by_role(
                        "button",
                        name="Запустить read-only анализ",
                    )
                    self.assertFalse(run_button.is_disabled())

                    content = environment_path.read_text(encoding="utf-8")
                    environment_path.write_text(
                        content.replace(
                            "YANDEX_DIRECT_CLIENT_LOGIN=payplaine-direct",
                            "YANDEX_DIRECT_CLIENT_LOGIN=",
                        ),
                        encoding="utf-8",
                    )
                    environment_path.chmod(0o600)
                    run_button.click()
                    page.get_by_role(
                        "heading",
                        name="Требуется настройка",
                    ).wait_for()

                    self.assertTrue(run_button.is_disabled())
                    self.assertIn(
                        "YANDEX_DIRECT_CLIENT_LOGIN",
                        page.locator("#blocked-panel").inner_text(),
                    )
                    self.assertEqual([], http_client.calls)
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_operator_can_run_test_mode_and_download_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            server = build_server(port=0, runs_root=Path(temporary))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    page.goto(
                        f"http://127.0.0.1:{server.server_port}",
                        wait_until="networkidle",
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
                    page.get_by_role(
                        "button",
                        name="Подтвердить точный proposal",
                    ).click()
                    page.get_by_text(
                        "Точный Approval выдан",
                        exact=False,
                    ).wait_for()
                    page.get_by_role(
                        "button",
                        name="Применить подтверждённое",
                    ).click()
                    page.get_by_text(
                        "Точный Approval использован",
                        exact=False,
                    ).wait_for()
                    page.get_by_role(
                        "heading",
                        name="Цикл завершён",
                    ).wait_for()

                    self.assertTrue(page.locator("#report").is_visible())
                    self.assertFalse(page.locator("#empty-state").is_visible())
                    self.assertEqual(5, page.locator("#pipeline .is-done").count())
                    self.assertEqual(
                        "95.00",
                        page.locator(".metric")
                        .filter(has_text="Бюджет")
                        .locator("strong")
                        .inner_text(),
                    )
                    self.assertIn(
                        "Увеличить недельный бюджет",
                        page.locator("#decision-title").inner_text(),
                    )
                    execution_text = page.locator("#execution-line").inner_text()
                    self.assertIn(
                        "2 000 ₽ → 2 200 ₽",
                        execution_text.replace("\N{NO-BREAK SPACE}", " "),
                    )
                    self.assertIn(
                        "sealed fake",
                        page.locator("#safety-copy").inner_text(),
                    )
                    with page.expect_download() as download_info:
                        page.get_by_role(
                            "link",
                            name="Скачать отчёт HTML",
                        ).click()
                    self.assertEqual(
                        1,
                        page.locator("#report .report-actions a").count(),
                    )
                    self.assertTrue(
                        download_info.value.suggested_filename.endswith(".html")
                    )
                    report_path = Path(temporary) / "downloaded-report.html"
                    download_info.value.save_as(report_path)
                    report_text = report_path.read_text(encoding="utf-8")
                    self.assertIn("<!doctype html>", report_text)
                    self.assertIn("<title>Отчёт MOX-ADV</title>", report_text)
                    self.assertIn(
                        "Использование бюджета",
                        report_text,
                    )
                    self.assertIn("95.00%", report_text)
                    self.assertIn("APPLIED", report_text)
                    self.assertIn(
                        "Внешний write-запрос не отправлялся",
                        report_text,
                    )
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_operator_sees_each_confirmed_read_only_stage_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configuration_path, environment_path = prepare_production_read_inputs(root)
            reader = build_test_production_reader(
                root,
                configuration_path=configuration_path,
                environment_path=environment_path,
                http_client=RecordingHttpClient(),
            )
            server = build_server(port=0, runs_root=root / "runs")
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
                    browser_requests: list[tuple[str, str]] = []
                    page.on(
                        "request",
                        lambda request: browser_requests.append(
                            (request.method, request.url)
                        ),
                    )
                    base_url = f"http://127.0.0.1:{server.server_port}"
                    page.goto(
                        base_url,
                        wait_until="networkidle",
                    )
                    page.get_by_role("tab", name="Основной").click()
                    page.get_by_role(
                        "button",
                        name="RECOMMEND",
                        exact=True,
                    ).click()
                    page.get_by_role(
                        "button",
                        name="Запустить read-only анализ",
                    ).click()
                    seen_states: list[list[str]] = []
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        current = page.locator(
                            "#pipeline .step-state"
                        ).all_inner_texts()
                        if not seen_states or current != seen_states[-1]:
                            seen_states.append(current)
                        if page.locator("#report").is_visible():
                            break
                        time.sleep(0.025)

                    expected_progress = [
                        [
                            "В работе",
                            "Ожидает",
                            "Ожидает",
                            "Ожидает",
                            "Ожидает",
                        ],
                        [
                            "Готово",
                            "В работе",
                            "Ожидает",
                            "Ожидает",
                            "Ожидает",
                        ],
                        [
                            "Готово",
                            "Готово",
                            "В работе",
                            "Ожидает",
                            "Ожидает",
                        ],
                        [
                            "Готово",
                            "Готово",
                            "Готово",
                            "В работе",
                            "Ожидает",
                        ],
                        [
                            "Готово",
                            "Готово",
                            "Готово",
                            "Готово",
                            "Не выполняется",
                        ],
                    ]
                    for expected in expected_progress:
                        self.assertIn(expected, seen_states)

                    self.assertTrue(page.locator("#report").is_visible())
                    self.assertFalse(page.locator("#blocked-panel").is_visible())
                    self.assertEqual(4, page.locator("#pipeline .is-done").count())
                    self.assertEqual(1, page.locator("#pipeline .is-skipped").count())
                    self.assertEqual(
                        "Не выполняется",
                        page.locator('[data-step="apply"] .step-state').inner_text(),
                    )
                    self.assertIn(
                        "executor отключён",
                        page.locator("#safety-copy").inner_text(),
                    )
                    self.assertIn(
                        "не применено",
                        page.locator("#execution-line").inner_text(),
                    )
                    with page.expect_download() as download_info:
                        page.get_by_role(
                            "link",
                            name="Скачать отчёт HTML",
                        ).click()
                    report_path = Path(temporary) / "main-read-only-report.html"
                    download_info.value.save_as(report_path)
                    report_text = report_path.read_text(encoding="utf-8")
                    self.assertIn("Отчёт<br>read-only анализа", report_text)
                    self.assertIn(
                        "Реальные read-only данные Яндекса",
                        report_text,
                    )
                    self.assertIn(
                        "Три разрешённых запроса чтения",
                        report_text,
                    )
                    self.assertIn("Executor</dt><dd>Отключён", report_text)
                    self.assertIn(
                        'External write</dt><dd class="safe">Запрещён',
                        report_text,
                    )
                    self.assertNotIn(">APPLIED<", report_text)
                    self.assertNotIn(
                        "Без автоматического совпадения",
                        report_text,
                    )
                    self.assertTrue(browser_requests)
                    self.assertTrue(
                        any(
                            url == base_url + "/api/runs/stream"
                            for _, url in browser_requests
                        ),
                        browser_requests,
                    )
                    self.assertTrue(
                        all(
                            url == base_url or url.startswith(base_url + "/")
                            for _, url in browser_requests
                        ),
                        browser_requests,
                    )
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_operator_can_change_test_metrics_and_see_a_safe_decision(self) -> None:
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
                        name="RECOMMEND",
                        exact=True,
                    ).click()
                    page.get_by_label("Показы").fill("2000")
                    page.get_by_label("Клики").fill("20")
                    page.get_by_label("Расход, ₽", exact=True).fill("400")
                    page.get_by_label("Визиты").fill("24")
                    page.get_by_label("Конверсии", exact=True).fill("1")
                    page.get_by_label("Недельный бюджет, ₽").fill("2000")
                    page.get_by_role(
                        "button",
                        name="Запустить тестовый цикл",
                    ).click()
                    page.get_by_role(
                        "heading",
                        name="Цикл завершён",
                    ).wait_for()

                    self.assertIn(
                        "Сохранить текущие настройки",
                        page.locator("#decision-title").inner_text(),
                    )
                    self.assertIn(
                        "недостаточно",
                        page.locator("#decision-copy").inner_text().lower(),
                    )
                    self.assertIn(
                        "изменение не требуется",
                        page.locator("#execution-line").inner_text().lower(),
                    )
                    self.assertEqual(
                        "20.00",
                        page.locator(".metric")
                        .filter(has_text="Бюджет")
                        .locator("strong")
                        .inner_text(),
                    )
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_operator_can_enable_proactive_cycle_and_see_decision_history(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            server = build_server(port=0, runs_root=Path(temporary))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 1200})
                    page.goto(
                        f"http://127.0.0.1:{server.server_port}",
                        wait_until="networkidle",
                    )

                    page.get_by_role("tab", name="Тестовый").click()
                    page.get_by_role(
                        "button",
                        name="BOUNDED AUTONOMY",
                    ).click()
                    page.get_by_role(
                        "button",
                        name="Выдать тестовый Mandate",
                    ).click()
                    page.get_by_text("Mandate активирован", exact=False).wait_for()
                    page.locator("#scenario-impressions").fill("5000")
                    page.locator("#scenario-clicks").fill("100")
                    page.locator("#scenario-spend").fill("4000")
                    page.locator("#scenario-visits").fill("100")
                    page.locator("#scenario-conversions").fill("3")
                    page.locator("#scenario-budget").fill("10000")
                    page.locator("#scenario-baseline-spend").fill("3000")
                    page.locator("#scenario-baseline-conversions").fill("3")
                    page.get_by_label("Периодичность").select_option("60")
                    page.get_by_role(
                        "button",
                        name="Включить автопилот",
                    ).click()
                    page.get_by_text("Автопилот включён", exact=True).wait_for()
                    page.locator("#decision-history article").first.wait_for(
                        timeout=10_000
                    )

                    history_text = page.locator(
                        "#decision-history article"
                    ).first.inner_text()
                    self.assertIn("По расписанию", history_text)
                    self.assertIn("Расход растёт без роста конверсий", history_text)
                    self.assertIn("APPLIED", history_text)
                    self.assertIn(
                        "Следующий запуск",
                        page.locator("#automation-timing").inner_text(),
                    )
                    page.get_by_role(
                        "heading",
                        name="Цикл завершён",
                    ).wait_for()
                    self.assertTrue(page.locator("#report").is_visible())
                    with page.expect_download() as download_info:
                        page.locator("#decision-history article").first.get_by_role(
                            "link",
                            name="HTML-отчёт",
                        ).click()
                    self.assertTrue(
                        download_info.value.suggested_filename.endswith(".html")
                    )
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_operator_can_edit_recommendation_matrix_and_use_it_in_next_cycle(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            server = build_server(port=0, runs_root=Path(temporary))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 1200})
                    page.goto(
                        f"http://127.0.0.1:{server.server_port}",
                        wait_until="networkidle",
                    )

                    page.get_by_role("tab", name="Тестовый").click()
                    page.get_by_role(
                        "heading",
                        name="Справочник рекомендаций",
                    ).wait_for()
                    self.assertGreaterEqual(
                        page.locator("#recommendation-matrix tbody tr").count(),
                        7,
                    )
                    self.assertIn(
                        "больше данных",
                        page.locator("#recommendation-matrix tbody tr")
                        .nth(1)
                        .inner_text()
                        .lower(),
                    )
                    page.get_by_label("Целевой CPA, ₽").fill("800")
                    page.get_by_role(
                        "button",
                        name="Сохранить логику",
                    ).click()
                    page.get_by_text(
                        "Логика рекомендаций сохранена.",
                        exact=True,
                    ).wait_for()

                    page.reload(wait_until="networkidle")
                    page.get_by_role("tab", name="Тестовый").click()
                    page.get_by_role(
                        "button",
                        name="RECOMMEND",
                        exact=True,
                    ).click()
                    self.assertEqual(
                        "800",
                        page.get_by_label("Целевой CPA, ₽").input_value(),
                    )
                    page.get_by_label("Показы").fill("10000")
                    page.get_by_label("Клики").fill("100")
                    page.get_by_label("Расход, ₽", exact=True).fill("9000")
                    page.get_by_label("Визиты").fill("100")
                    page.get_by_label("Конверсии", exact=True).fill("10")
                    page.get_by_label("Недельный бюджет, ₽").fill("4000")
                    page.get_by_role(
                        "button",
                        name="Запустить тестовый цикл",
                    ).click()
                    page.get_by_role(
                        "heading",
                        name="Цикл завершён",
                    ).wait_for()

                    self.assertIn(
                        "Уменьшить недельный бюджет",
                        page.locator("#decision-title").inner_text(),
                    )
                    self.assertIn(
                        "не применено",
                        page.locator("#execution-line").inner_text().lower(),
                    )
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()


if __name__ == "__main__":
    unittest.main()
