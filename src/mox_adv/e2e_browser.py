"""Playwright-local goal event exercise bound to exact synthetic evidence."""

from __future__ import annotations

import contextlib
import http.server
import threading
from collections.abc import Iterator
from functools import partial
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from mox_adv.e2e_evidence import ReadOnlyEgressRecorder
from mox_adv.goal_evidence import GoalEventEvidence
from mox_adv.runtime_resources import runtime_resource

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Route, WebSocketRoute

PAGE = runtime_resource("fixtures", "goal-test-page.html")
READ_ONLY_CHROMIUM_ARGS = (
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-quic",
    "--disable-sync",
    "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
    "--metrics-recording-only",
    "--no-first-run",
)


class _QuietFileHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args


@contextlib.contextmanager
def _serve_test_page(counter_id: str) -> Iterator[str]:
    handler = partial(_QuietFileHandler, directory=str(PAGE.parent))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        query = urlencode({"counter": counter_id})
        yield (f"http://127.0.0.1:{server.server_port}/{PAGE.name}?{query}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def exercise_goal_event(
    *,
    counter_id: str,
    event: str,
    trigger_selector: str,
    configured_selector: str,
    egress: ReadOnlyEgressRecorder,
) -> GoalEventEvidence:
    """Trigger and locally intercept exactly one counter-bound event."""

    from playwright.sync_api import sync_playwright

    with _serve_test_page(counter_id) as page_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=READ_ONLY_CHROMIUM_ARGS,
        )
        context = browser.new_context(service_workers="block")
        configure_read_only_browser_context(
            context,
            egress=egress,
            counter_id=counter_id,
            event=event,
        )
        page = context.new_page()
        page.goto(page_url, wait_until="domcontentloaded")
        relation = page.evaluate(
            """selectors => {
                const configured = document.querySelector(selectors.configured);
                const trigger = document.querySelector(selectors.trigger);
                return Boolean(configured && trigger && configured.contains(trigger));
            }""",
            {
                "configured": configured_selector,
                "trigger": trigger_selector,
            },
        )
        if relation is not True:
            raise AssertionError(
                "The configured selector does not contain the user trigger."
            )
        page.locator(trigger_selector).click()
        page.wait_for_function(
            "selected => window.__goalEvents.includes(selected)",
            arg=event,
        )
        page.locator(trigger_selector).click()
        page.wait_for_timeout(50)
        browser_events = page.evaluate("window.__goalEvents")
        context.close()
        browser.close()
    intercepted = egress.browser_event(counter_id, event)
    if intercepted is None or browser_events != [event]:
        raise AssertionError("Playwright did not prove exactly one bound goal event.")
    return GoalEventEvidence(
        event=event,
        selector=configured_selector,
        trigger_selector=trigger_selector,
        counter_id=counter_id,
        http_method=intercepted["http_method"],
        request_url=intercepted["url"],
        emitted_count=1,
        intercepted_locally=True,
        real_network_requests=0,
    )


def _browser_route(
    egress: ReadOnlyEgressRecorder,
    counter_id: str,
    event: str,
):
    def route_request(route: Route) -> None:
        disposition = egress.record_browser_request(
            route.request.method,
            route.request.url,
            expected_counter_id=counter_id,
            expected_event=event,
        )
        if disposition == "LOCAL":
            route.continue_()
            return
        if disposition == "INTERCEPTED_EVENT":
            route.fulfill(status=204, body="")
            return
        route.abort()

    return route_request


def configure_read_only_browser_context(
    context: BrowserContext,
    *,
    egress: ReadOnlyEgressRecorder,
    counter_id: str,
    event: str,
) -> None:
    """Install HTTP and WebSocket routes before any page is created."""

    context.route("**/*", _browser_route(egress, counter_id, event))
    context.route_web_socket(
        "**/*",
        _blocked_websocket_route(egress),
    )


def _blocked_websocket_route(egress: ReadOnlyEgressRecorder):
    def block(websocket: WebSocketRoute) -> None:
        egress.block_browser_websocket(websocket.url)
        # A routed WebSocket remains local unless connect_to_server() is called.

    return block
