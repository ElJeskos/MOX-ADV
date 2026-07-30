from __future__ import annotations

import hashlib
import struct
import tempfile
import threading
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from mox_adv.ui_server import ASSET_ROOT, build_server

PRE_MIGRATION_ASSET_DIGESTS = {
    "index.html": "b02dc8fa6b726b459900e0514e0a7b780945dbf6a45191eafe5356aca89a779c",
    "app.css": "8a6bcca58b6dffd7799404501b3ceab3164cc22c91b8710c4bd3ed7884ec468f",
    "app.js": "86a583ab9307580baad06812c5abe41db837be6a141e98b52ed08db9e80b8651",
}
EXISTING_ROUTES = (
    "/overview",
    "/cycle",
    "/autopilot",
    "/rules",
    "/history",
    "/workflows",
    "/control",
)


def _png_dimensions(value: bytes) -> tuple[int, int]:
    if value[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("Playwright did not return a PNG screenshot.")
    return struct.unpack(">II", value[16:24])


class PairedDashboardRegressionTests(unittest.TestCase):
    def test_dashboard_assets_are_byte_identical_to_the_pre_migration_ui(
        self,
    ) -> None:
        actual = {
            name: hashlib.sha256((ASSET_ROOT / name).read_bytes()).hexdigest()
            for name in PRE_MIGRATION_ASSET_DIGESTS
        }

        self.assertEqual(PRE_MIGRATION_ASSET_DIGESTS, actual)

    def test_playwright_preserves_routes_russian_controls_and_visual_states(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            server = build_server(
                port=0,
                runs_root=Path(temporary) / "runs",
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(
                        viewport={"width": 1440, "height": 1000},
                        device_scale_factor=1,
                    )
                    page.goto(
                        f"http://127.0.0.1:{server.server_port}/cycle",
                        wait_until="networkidle",
                    )
                    initial = page.screenshot(
                        animations="disabled",
                        full_page=False,
                    )

                    self.assertEqual((1440, 1000), _png_dimensions(initial))
                    self.assertEqual(
                        [route.removeprefix("/") for route in EXISTING_ROUTES],
                        page.locator(".main-nav a").evaluate_all(
                            """
                            links => links.map(
                              link => new URL(link.href).pathname.slice(1)
                            )
                            """
                        ),
                    )
                    self.assertEqual("ru", page.locator("html").get_attribute("lang"))
                    self.assertEqual(
                        "Получить предложение",
                        page.locator("#control-title").inner_text(),
                    )
                    self.assertEqual(
                        ["Тестовый", "Основной"],
                        page.locator(".mode-button").all_inner_texts(),
                    )
                    body = page.locator("body").inner_text()
                    self.assertNotIn("Подключить модуль", body)
                    self.assertNotIn("Standalone", body)

                    page.get_by_role(
                        "button",
                        name="Получить предложение",
                    ).click()
                    page.get_by_text(
                        "Предложение готово и ещё не применено",
                        exact=True,
                    ).wait_for()
                    result = page.screenshot(
                        animations="disabled",
                        full_page=False,
                    )

                    self.assertEqual((1440, 1000), _png_dimensions(result))
                    self.assertNotEqual(
                        hashlib.sha256(initial).digest(),
                        hashlib.sha256(result).digest(),
                    )
                    self.assertTrue(page.locator("#report").is_visible())
                    self.assertEqual(4, page.locator("#pipeline .is-done").count())
                    self.assertIn(
                        "Увеличить недельный бюджет",
                        page.locator("#decision-title").inner_text(),
                    )
                    browser.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()


if __name__ == "__main__":
    unittest.main()
