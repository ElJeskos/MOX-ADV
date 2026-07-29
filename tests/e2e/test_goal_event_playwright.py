from __future__ import annotations

import contextlib
import http.server
import threading
import unittest
from collections.abc import Iterator
from functools import partial
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Route, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "fixtures" / "goal-test-page.html"


class QuietFileHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args


@contextlib.contextmanager
def serve_test_page() -> Iterator[str]:
    handler = partial(QuietFileHandler, directory=str(PAGE.parent))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/{PAGE.name}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class GoalEventPlaywrightTests(unittest.TestCase):
    def test_each_selected_event_is_intercepted_once_without_external_egress(
        self,
    ) -> None:
        scenarios = (
            ("form_started", "#lead-name"),
            ("primary_cta_clicked", "#primary-cta"),
            ("lead_submitted", "#lead-submit"),
        )
        with serve_test_page() as page_url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for selected_event, selector in scenarios:
                with self.subTest(event=selected_event):
                    context = browser.new_context()
                    intercepted_events: list[str] = []
                    external_requests: list[str] = []
                    context.route(
                        "**/*",
                        route_recorder(intercepted_events, external_requests),
                    )
                    page = context.new_page()
                    page.goto(page_url, wait_until="domcontentloaded")
                    page.locator(selector).click()
                    page.wait_for_function(
                        "event => window.__goalEvents.includes(event)",
                        arg=selected_event,
                    )
                    page.locator(selector).click()
                    page.wait_for_timeout(50)

                    self.assertEqual([selected_event], intercepted_events)
                    self.assertEqual(
                        [selected_event],
                        page.evaluate("window.__goalEvents"),
                    )
                    self.assertEqual([], external_requests)
                    context.close()
            browser.close()


def route_recorder(
    intercepted_events: list[str],
    external_requests: list[str],
):
    def route_request(route: Route) -> None:
        parsed = urlparse(route.request.url)
        if parsed.hostname == "mc.yandex.ru":
            event = parse_qs(parsed.query).get("event", [""])[0]
            intercepted_events.append(event)
            route.fulfill(status=204, body="")
            return
        if parsed.hostname == "127.0.0.1":
            route.continue_()
            return
        external_requests.append(route.request.url)
        route.abort()

    return route_request


if __name__ == "__main__":
    unittest.main()
