from __future__ import annotations

import json
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from mox_adv.e2e_browser import (
    READ_ONLY_CHROMIUM_ARGS,
    configure_read_only_browser_context,
    exercise_goal_event,
)
from mox_adv.e2e_evidence import ReadOnlyEgressRecorder

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "config" / "gate0-policy.json"
COUNTER_ID = "999001"


class GoalEventPlaywrightTests(unittest.TestCase):
    def test_each_selected_event_is_intercepted_once_without_external_egress(
        self,
    ) -> None:
        scenarios = (
            ("form_started", "#lead-name"),
            ("primary_cta_clicked", "#primary-cta"),
            ("lead_submitted", "#lead-submit"),
        )
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        for selected_event, selector in scenarios:
            with self.subTest(event=selected_event):
                recorder = ReadOnlyEgressRecorder(policy)
                evidence = exercise_goal_event(
                    counter_id=COUNTER_ID,
                    event=selected_event,
                    trigger_selector=selector,
                    configured_selector="#lead-form",
                    egress=recorder,
                )

                self.assertEqual(1, evidence.emitted_count)
                self.assertEqual(COUNTER_ID, evidence.counter_id)
                self.assertEqual("POST", evidence.http_method)
                self.assertEqual(1, len(recorder.browser_interceptions))
                self.assertEqual(0, recorder.blocked_non_read_attempts)
                self.assertEqual(0, evidence.real_network_requests)

    def test_external_websocket_is_blocked_before_server_connection(self) -> None:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        recorder = ReadOnlyEgressRecorder(policy)
        websocket_url = "wss://external.invalid/socket"

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=READ_ONLY_CHROMIUM_ARGS,
            )
            context = browser.new_context(service_workers="block")
            configure_read_only_browser_context(
                context,
                egress=recorder,
                counter_id=COUNTER_ID,
                event="lead_submitted",
            )
            page = context.new_page()
            created_url = page.evaluate(
                """url => {
                    window.__blockedSocket = new WebSocket(url);
                    return window.__blockedSocket.url;
                }""",
                websocket_url,
            )
            page.wait_for_timeout(50)
            context.close()
            browser.close()

        self.assertEqual(websocket_url, created_url)
        self.assertEqual(
            (websocket_url,),
            recorder.browser_websocket_attempts,
        )
        self.assertEqual(1, recorder.blocked_non_read_attempts)


if __name__ == "__main__":
    unittest.main()
