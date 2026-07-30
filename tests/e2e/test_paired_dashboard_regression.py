from __future__ import annotations

import hashlib
import struct
import tempfile
import threading
import unittest
import zlib
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from mox_adv.ui_server import ASSET_ROOT, build_server

PRE_MIGRATION_ASSET_DIGESTS = {
    "index.html": "b02dc8fa6b726b459900e0514e0a7b780945dbf6a45191eafe5356aca89a779c",
    "app.css": "8a6bcca58b6dffd7799404501b3ceab3164cc22c91b8710c4bd3ed7884ec468f",
    "app.js": "86a583ab9307580baad06812c5abe41db837be6a141e98b52ed08db9e80b8651",
}
PRE_MIGRATION_SCREENSHOT_DIGESTS = {
    "test_initial": (
        "42172f967fc2774cce956e56d356e393e"
        "8ba386d33f75c672f292c68ac86efa5"
    ),
    "production_initial": (
        "3338402fc327ef34ad3dc663723b5fe8"
        "f67efa408dd48510d328a79da4b14663"
    ),
    "test_result": (
        "6be4b864fc4a7afb52f773dbfaa532c2"
        "0a1f251bcfe1b3e88ac2f11c10b5fe93"
    ),
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


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def _png_rgb(value: bytes) -> tuple[int, int, bytes]:
    width, height = _png_dimensions(value)
    offset = 8
    compressed = bytearray()
    color_type = -1
    bit_depth = -1
    interlace = -1
    while offset < len(value):
        length = struct.unpack(">I", value[offset : offset + 4])[0]
        kind = value[offset + 4 : offset + 8]
        payload = value[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            (
                _,
                _,
                bit_depth,
                color_type,
                _,
                _,
                interlace,
            ) = struct.unpack(">IIBBBBB", payload)
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break
    if bit_depth != 8 or color_type not in {2, 6} or interlace != 0:
        raise AssertionError("Unexpected Playwright PNG pixel format.")
    bytes_per_pixel = 3 if color_type == 2 else 4
    stride = width * bytes_per_pixel
    encoded = zlib.decompress(bytes(compressed))
    rows = []
    previous = bytearray(stride)
    position = 0
    for _ in range(height):
        filter_type = encoded[position]
        position += 1
        row = bytearray(encoded[position : position + stride])
        position += stride
        for index in range(stride):
            left = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            above = previous[index]
            upper_left = (
                previous[index - bytes_per_pixel]
                if index >= bytes_per_pixel
                else 0
            )
            if filter_type == 1:
                row[index] = (row[index] + left) & 0xFF
            elif filter_type == 2:
                row[index] = (row[index] + above) & 0xFF
            elif filter_type == 3:
                row[index] = (row[index] + ((left + above) // 2)) & 0xFF
            elif filter_type == 4:
                row[index] = (
                    row[index] + _paeth(left, above, upper_left)
                ) & 0xFF
            elif filter_type != 0:
                raise AssertionError("Unexpected Playwright PNG row filter.")
        rows.append(row)
        previous = row
    rgb = bytearray()
    for row in rows:
        for index in range(0, stride, bytes_per_pixel):
            rgb.extend(row[index : index + 3])
    return width, height, bytes(rgb)


def _visual_digest(value: bytes) -> str:
    width, height, pixels = _png_rgb(value)
    signature = bytearray()
    columns = 36
    rows = 25
    for block_y in range(rows):
        start_y = block_y * height // rows
        end_y = (block_y + 1) * height // rows
        for block_x in range(columns):
            start_x = block_x * width // columns
            end_x = (block_x + 1) * width // columns
            sums = [0, 0, 0]
            count = (end_y - start_y) * (end_x - start_x)
            for y in range(start_y, end_y):
                for x in range(start_x, end_x):
                    offset = (y * width + x) * 3
                    for channel in range(3):
                        sums[channel] += pixels[offset + channel]
            signature.extend(
                min(15, (total // count) // 16)
                for total in sums
            )
    return hashlib.sha256(signature).hexdigest()


def _stable_screenshot(
    page: Page,
) -> bytes:
    style = (
        "*,*::before,*::after{"
        "animation:none!important;"
        "transition:none!important;"
        "caret-color:transparent!important;"
        "}"
    )
    page.screenshot(
        animations="disabled",
        caret="hide",
        style=style,
        full_page=False,
    )
    page.wait_for_timeout(100)
    return page.screenshot(
        animations="disabled",
        caret="hide",
        style=style,
        full_page=False,
    )


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
                    origin = f"http://127.0.0.1:{server.server_port}"
                    for route in EXISTING_ROUTES:
                        response = page.goto(
                            origin + route,
                            wait_until="networkidle",
                        )
                        self.assertIsNotNone(response)
                        self.assertTrue(response.ok)
                        self.assertEqual(
                            route.removeprefix("/"),
                            page.locator(
                                ".main-nav a[aria-current='page']"
                            ).get_attribute("data-page-link"),
                        )

                    page.goto(origin + "/cycle", wait_until="networkidle")
                    initial = _stable_screenshot(page)
                    visual_digests = {
                        "test_initial": _visual_digest(initial),
                    }

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

                    page.get_by_role("tab", name="Основной").click()
                    page.locator("#mode-name").get_by_text(
                        "Реальные данные",
                        exact=True,
                    ).wait_for()
                    production = _stable_screenshot(page)
                    visual_digests["production_initial"] = _visual_digest(
                        production
                    )
                    self.assertTrue(
                        page.get_by_role(
                            "button",
                            name="Получить предложение",
                        ).is_disabled()
                    )

                    page.get_by_role("tab", name="Тестовый").click()
                    page.locator("#mode-name").get_by_text(
                        "Тестовые данные",
                        exact=True,
                    ).wait_for()
                    page.get_by_role(
                        "button",
                        name="Получить предложение",
                    ).click()
                    page.get_by_text(
                        "Предложение готово и ещё не применено",
                        exact=True,
                    ).wait_for()
                    page.locator("#report-run-id").evaluate(
                        "(element) => {"
                        " element.textContent = 'ui-reference-run';"
                        " }"
                    )
                    result = _stable_screenshot(page)
                    visual_digests["test_result"] = _visual_digest(result)

                    self.assertEqual((1440, 1000), _png_dimensions(result))
                    self.assertEqual(
                        PRE_MIGRATION_SCREENSHOT_DIGESTS,
                        visual_digests,
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
