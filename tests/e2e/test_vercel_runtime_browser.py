from __future__ import annotations

import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from api.index import handler
from mox_adv.vercel_runtime import build_vercel_runtime
from tests.test_vercel_runtime import vercel_environment
from tests.test_yandex_read import RecordingHttpClient


class VercelRuntimeBrowserTests(unittest.TestCase):
    def test_public_vercel_runtime_keeps_dashboard_and_yandex_surface(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = build_vercel_runtime(
                environment=vercel_environment(),
                scratch_root=Path(temporary),
                http_client=RecordingHttpClient(),
            )
            with patch("api.index._RUNTIME", runtime):
                server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
                thread = threading.Thread(
                    target=server.serve_forever,
                    daemon=True,
                )
                thread.start()
                try:
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True)
                        page = browser.new_page(
                            viewport={"width": 1440, "height": 1000}
                        )
                        page_errors: list[str] = []
                        page.on(
                            "pageerror",
                            lambda error: page_errors.append(str(error)),
                        )
                        page.goto(
                            "http://127.0.0.1:"
                            f"{server.server_port}/campaign",
                            wait_until="networkidle",
                        )
                        page.get_by_text(
                            "Публичная демонстрация",
                            exact=True,
                        ).wait_for()
                        before = page.locator("#campaign-list tr").count()
                        page.get_by_role(
                            "button",
                            name="Новая кампания",
                        ).click()
                        page.wait_for_function(
                            "expected => document.querySelectorAll("
                            "'#campaign-list tr').length === expected",
                            arg=before + 1,
                        )
                        page.get_by_role(
                            "button",
                            name="Удалить",
                            exact=True,
                        ).click()
                        page.get_by_role(
                            "button",
                            name="Удалить кампанию",
                        ).click()
                        page.get_by_text(
                            "Кампания удалена из локального списка.",
                            exact=True,
                        ).wait_for()
                        page.locator("#campaign-source-direct").click()
                        page.get_by_text(
                            "Получено кампаний: 1. "
                            "Доступ остаётся только для чтения.",
                            exact=True,
                        ).wait_for()
                        self.assertEqual([], page_errors)
                        browser.close()
                finally:
                    server.shutdown()
                    thread.join(timeout=5)
                    server.server_close()


if __name__ == "__main__":
    unittest.main()
