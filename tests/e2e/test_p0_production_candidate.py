from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "sites" / "p0-production"
VIEWPORT = {"width": 1920, "height": 1080}
ACCEPTANCE_ARTIFACT = (
    SOURCE / "tests" / "fixtures" / "production-candidate-acceptance.json"
)


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _copy_candidate(target: Path) -> None:
    ignored = shutil.ignore_patterns(
        "node_modules",
        "dist",
        ".next",
        ".wrangler",
        ".vinext",
        ".env",
        ".env.*",
        "tsconfig.tsbuildinfo",
    )
    shutil.copytree(SOURCE, target, ignore=ignored)
    (target / "node_modules").symlink_to(SOURCE / "node_modules", target_is_directory=True)
    (target / ".env.local").write_text(
        "P0_E2E_FIXTURE_SCENARIO=mixed-correction\n",
        encoding="utf-8",
    )


def _wait_until_ready(base_url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, _ = process.communicate(timeout=5)
            raise AssertionError(f"P0 fixture server exited early:\n{stdout}")
        try:
            with urlopen(base_url, timeout=2) as response:  # noqa: S310 - loopback fixture only
                if response.status == 200:
                    return
        except (URLError, TimeoutError):
            time.sleep(0.25)
    raise AssertionError("P0 fixture server did not become ready within 90 seconds")


@contextmanager
def production_candidate_server():
    with tempfile.TemporaryDirectory(prefix="mox-p0-e2e-") as temporary:
        target = Path(temporary) / "candidate"
        _copy_candidate(target)
        port = _available_port()
        base_url = f"http://localhost:{port}"
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("YANDEX_")
        }
        environment["P0_E2E_FIXTURE_SCENARIO"] = "mixed-correction"
        process = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(port)],
            cwd=target,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            _wait_until_ready(base_url, process)
            yield base_url
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()


def assert_no_horizontal_overflow(test: unittest.TestCase, page: Page) -> None:
    dimensions = page.evaluate(
        """() => ({
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth,
          innerWidth: window.innerWidth,
          innerHeight: window.innerHeight,
        })"""
    )
    test.assertEqual(VIEWPORT["width"], dimensions["innerWidth"])
    test.assertEqual(VIEWPORT["height"], dimensions["innerHeight"])
    test.assertLessEqual(dimensions["scrollWidth"], dimensions["clientWidth"])


class P0ProductionCandidateE2ETests(unittest.TestCase):
    def test_owner_completes_the_production_candidate_through_the_real_ui(
        self,
    ) -> None:
        with production_candidate_server() as base_url:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport=VIEWPORT)
                console_errors: list[str] = []
                page_errors: list[str] = []
                nonlocal_requests: list[str] = []
                page.on(
                    "console",
                    lambda message: console_errors.append(message.text)
                    if message.type == "error"
                    else None,
                )
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.on(
                    "request",
                    lambda request: nonlocal_requests.append(request.url)
                    if not request.url.startswith(base_url)
                    else None,
                )

                page.goto(base_url, wait_until="networkidle")

                self.assertEqual("Стратегия — MOX-ADV", page.title())
                self.assertTrue(
                    page.get_by_text(
                        "DETERMINISTIC PROVIDER FIXTURE · NO EXTERNAL NETWORK OR MONEY",
                        exact=True,
                    ).is_visible()
                )
                self.assertTrue(
                    page.get_by_text("API bindings подтверждены", exact=True).is_visible()
                )
                self.assertEqual(
                    0,
                    page.get_by_text("Preflight заблокирован", exact=True).count(),
                )
                step_buttons = page.get_by_label("Путь создания кампании").get_by_role(
                    "button"
                )
                self.assertEqual(5, step_buttons.count())
                self.assertEqual(
                    [
                        "Контекст",
                        "Модель бизнеса",
                        "Стратегия кампании",
                        "Рекламные кампании",
                        "Подтверждение",
                    ],
                    step_buttons.locator("strong").all_inner_texts(),
                )
                self.assertEqual([], console_errors)
                self.assertEqual([], page_errors)
                self.assertEqual([], nonlocal_requests)
                assert_no_horizontal_overflow(self, page)

                page.get_by_label("Публичный first-party сайт бизнеса").fill(
                    "https://owner.example/"
                )
                page.get_by_role(
                    "button",
                    name="Проверить Context и предложить цель",
                    exact=True,
                ).click()
                page.get_by_text(
                    "Одна provisional бизнес-цель",
                    exact=True,
                ).wait_for()
                page.get_by_role(
                    "button",
                    name="Подтвердить цель и продолжить анализ",
                    exact=True,
                ).click()
                page.get_by_role(
                    "heading",
                    name="Агент уже собрал модель бизнеса",
                    exact=True,
                ).wait_for()
                self.assertTrue(
                    page.get_by_role(
                        "heading",
                        name="Landing advisory",
                        exact=True,
                    ).is_visible()
                )
                self.assertTrue(
                    page.get_by_role(
                        "heading",
                        name="Краткая сводка аналитики",
                        exact=True,
                    ).is_visible()
                )
                self.assertTrue(page.get_by_text("67+ запросов", exact=True).is_visible())
                page.get_by_role(
                    "button",
                    name="Подтвердить вывод агента",
                    exact=True,
                ).click()
                page.get_by_role(
                    "heading",
                    name="Фиксированный Campaign Strategy questionnaire",
                    exact=True,
                ).wait_for()

                strategy_fields = page.locator("[data-strategy-field]")
                self.assertEqual(11, strategy_fields.count())
                self.assertEqual(
                    [
                        "business_goal",
                        "advertised_offer",
                        "target_audience",
                        "qualified_result",
                        "exclusions",
                        "geography",
                        "period",
                        "landing_page",
                        "weekly_budget",
                        "target_result_cost",
                        "core_message",
                    ],
                    strategy_fields.evaluate_all(
                        "elements => elements.map(element => element.dataset.strategyField)"
                    ),
                )
                page.locator("select[name='geography']").select_option("Москва")
                page.locator("input[name='period_start']").fill("2026-09-01")
                page.locator("input[name='period_end']").fill("2026-10-01")
                page.locator("input[name='weekly_budget']").fill("50000")
                page.locator("input[name='target_result_cost']").fill("10000")
                page.get_by_role(
                    "button",
                    name="Утвердить всю Campaign Strategy",
                    exact=True,
                ).click()
                page.get_by_role(
                    "heading",
                    name="Campaign Canvas",
                    exact=True,
                ).wait_for()
                cards = page.locator(".draft-card-shell")
                self.assertGreaterEqual(cards.count(), 2)
                stale_page = browser.new_page(viewport=VIEWPORT)
                stale_console_errors: list[str] = []
                stale_page.on(
                    "console",
                    lambda message: stale_console_errors.append(message.text)
                    if message.type == "error"
                    else None,
                )
                stale_page.on(
                    "pageerror",
                    lambda error: page_errors.append(str(error)),
                )
                stale_page.on(
                    "request",
                    lambda request: nonlocal_requests.append(request.url)
                    if not request.url.startswith(base_url)
                    else None,
                )
                stale_page.goto(base_url, wait_until="networkidle")
                stale_page.get_by_role(
                    "heading",
                    name="Campaign Canvas",
                    exact=True,
                ).wait_for()
                page.get_by_label("Фильтр variant").select_option("IMPROVEMENT")
                self.assertGreaterEqual(page.locator(".draft-card-shell").count(), 1)
                page.get_by_label("Фильтр variant").select_option("ALL")
                page.get_by_label("Сортировка Drafts").select_option("SCORE")
                page.get_by_text(
                    "Показать hidden Drafts с suppression reasons",
                    exact=True,
                ).click()
                self.assertGreaterEqual(page.locator(".draft-card-shell").count(), 2)

                first_open = page.get_by_role(
                    "button",
                    name=re.compile(r"^Открыть Draft "),
                ).first
                first_open.focus()
                first_open.press("Enter")
                drawer = page.get_by_role("dialog", name="Точная будущая Direct projection")
                drawer.wait_for()
                self.assertEqual(
                    "Закрыть drawer",
                    page.evaluate("document.activeElement?.getAttribute('aria-label')"),
                )
                page.keyboard.press("Escape")
                self.assertEqual(0, drawer.count())
                self.assertTrue(
                    first_open.evaluate("element => document.activeElement === element")
                )

                first_open.press("Enter")
                drawer.wait_for()
                ad_text = drawer.locator("textarea[name='ad_text']")
                original_ad_text = ad_text.input_value()
                ad_text.fill(f"{original_ad_text} Уточнение для участия.")
                drawer.get_by_role(
                    "button",
                    name="Сохранить material revision",
                    exact=True,
                ).click()
                drawer.get_by_text(
                    "Создана новая immutable Draft revision",
                    exact=False,
                ).wait_for()
                drawer.get_by_role("button", name="Закрыть drawer").click()

                stale_page.locator(
                    "button[aria-label^='Добавить в shortlist:']:not([disabled])"
                ).first.click()
                stale_conflict = stale_page.locator(".notice.error")
                stale_conflict.wait_for()
                self.assertIn("другой вкладке", stale_conflict.inner_text())
                self.assertEqual(1, len(stale_console_errors))
                self.assertIn("409 (Conflict)", stale_console_errors[0])
                stale_page.close()

                shortlist_buttons = page.locator(
                    "button[aria-label^='Добавить в shortlist:']:not([disabled])"
                )
                self.assertGreaterEqual(shortlist_buttons.count(), 2)
                shortlist_labels = shortlist_buttons.evaluate_all(
                    "elements => elements.slice(0, 2).map(element => element.getAttribute('aria-label'))"
                )
                shortlist = page.get_by_label("Persistent shortlist summary")
                page.get_by_role(
                    "button",
                    name=shortlist_labels[0],
                    exact=True,
                ).click()
                shortlist.get_by_text("ORDERED SHORTLIST · 1", exact=True).wait_for()
                page.get_by_role(
                    "button",
                    name=shortlist_labels[1],
                    exact=True,
                ).click()
                shortlist.get_by_text("ORDERED SHORTLIST · 2", exact=True).wait_for()
                shortlist.get_by_role(
                    "button",
                    name="Создать package review",
                    exact=True,
                ).click()
                page.get_by_role(
                    "heading",
                    name="Точный immutable package review",
                    exact=True,
                ).wait_for()
                self.assertTrue(
                    page.get_by_role(
                        "heading",
                        name="2 независимых Campaign Drafts",
                        exact=True,
                    ).is_visible()
                )
                page.get_by_label(
                    "Подтверждаю точный пакет и независимое исполнение кампаний"
                ).check()
                page.get_by_role(
                    "button",
                    name="Подтвердить authority пакета",
                    exact=True,
                ).click()
                page.get_by_text(
                    "Human Decision Gate подтверждён",
                    exact=True,
                ).wait_for()
                page.reload(wait_until="networkidle")
                page.get_by_text(
                    "Human Decision Gate подтверждён",
                    exact=True,
                ).wait_for()
                page.get_by_role(
                    "button",
                    name="Исполнить подтверждённый пакет",
                    exact=True,
                ).click()

                initial_execution = page.get_by_label(
                    "Package campaign executions"
                ).first
                initial_execution.get_by_text(
                    "Package verdict PENDING",
                    exact=False,
                ).wait_for()
                self.assertEqual(
                    2,
                    initial_execution.locator(".package-execution-item").count(),
                )
                initial_execution.get_by_role(
                    "button",
                    name="Проверить due item",
                    exact=True,
                ).first.click()
                initial_execution.get_by_text("DIRECT_ACCEPTED", exact=True).wait_for()
                initial_execution.get_by_role(
                    "button",
                    name="Проверить due item",
                    exact=True,
                ).click()
                page.wait_for_function(
                    "text => document.body.innerText.includes(text) || Boolean(document.querySelector('.notice.error'))",
                    arg="Package verdict PASS_WITH_PLATFORM_REJECTIONS",
                )
                self.assertEqual(
                    [],
                    page.locator(".notice.error").all_inner_texts(),
                    page.locator("body").inner_text(),
                )
                initial_execution.get_by_text(
                    "Package verdict PASS_WITH_PLATFORM_REJECTIONS",
                    exact=False,
                ).wait_for()
                rejected = initial_execution.locator(
                    ".package-execution-item",
                    has_text="REJECTED_NEEDS_EDIT",
                )
                rejected.get_by_text(
                    "Ad moderation outcomes · 1",
                    exact=True,
                ).click()
                rejected.get_by_text(
                    "Уточните формулировку обещания в тексте объявления.",
                    exact=True,
                ).wait_for()
                rejected.get_by_role(
                    "button",
                    name="Исправить отклонённый Draft",
                    exact=True,
                ).click()

                correction = page.get_by_label("Focused correction flows")
                correction.get_by_text("EDITING", exact=True).first.wait_for()
                correction.locator("textarea[name='ad_text']").fill(
                    "Подайте заявку на участие без гарантии результата."
                )
                correction.get_by_role(
                    "button",
                    name="Сохранить новую material correction revision",
                    exact=True,
                ).click()
                correction.get_by_text(
                    "PACKAGE_REVIEW_REQUIRED",
                    exact=True,
                ).first.wait_for()
                correction.get_by_role(
                    "button",
                    name="Проверить corrected package revision",
                    exact=True,
                ).click()
                correction.get_by_text(
                    "HUMAN_GATE_REQUIRED",
                    exact=True,
                ).first.wait_for()
                correction.get_by_text(
                    "Рекомендация · RESUBMIT_CORRECTED_REVISION",
                    exact=True,
                ).wait_for()
                correction.get_by_text(
                    "Подтверждаю recommendation, evidence, confidence, alternatives, consequences и новый exact corrected fingerprint",
                    exact=True,
                ).click()
                correction.get_by_role(
                    "button",
                    name="Создать новый Human Decision Gate",
                    exact=True,
                ).click()
                correction.get_by_text(
                    "READY_TO_RESUBMIT",
                    exact=True,
                ).first.wait_for()
                correction.get_by_role(
                    "button",
                    name="Повторно отправить confirmed correction revision",
                    exact=True,
                ).click()
                corrected_execution = correction.get_by_label(
                    "Package campaign executions"
                )
                page.wait_for_function(
                    "() => Boolean(document.querySelector('.package-corrections .package-executions')) || Boolean(document.querySelector('.notice.error'))"
                )
                self.assertEqual(
                    [],
                    page.locator(".notice.error").all_inner_texts(),
                    page.locator("body").inner_text(),
                )
                corrected_execution.get_by_text(
                    "Package verdict PENDING",
                    exact=False,
                ).wait_for()
                corrected_execution.get_by_role(
                    "button",
                    name="Проверить due item",
                    exact=True,
                ).click()
                page.wait_for_function(
                    "text => document.body.innerText.includes(text) || Boolean(document.querySelector('.notice.error'))",
                    arg="PASS_AFTER_CORRECTION",
                )
                self.assertEqual(
                    [],
                    page.locator(".notice.error").all_inner_texts(),
                    page.locator("body").inner_text(),
                )
                correction.get_by_text(
                    "PASS_AFTER_CORRECTION",
                    exact=True,
                ).last.wait_for()
                self.assertTrue(
                    correction.get_by_text(
                        "Initial package verdict",
                        exact=True,
                    ).is_visible()
                )
                self.assertTrue(
                    correction.get_by_text(
                        "Corrected terminal outcome",
                        exact=True,
                    ).is_visible()
                )
                page.reload(wait_until="networkidle")
                page.get_by_text(
                    "PASS_AFTER_CORRECTION",
                    exact=True,
                ).last.wait_for()

                self.assertTrue(
                    page.get_by_text("API bindings подтверждены", exact=True).is_visible(),
                    page.locator("body").inner_text(),
                )
                fixture_evidence = page.get_by_label(
                    "Deterministic provider fixture evidence"
                )
                fixture_evidence.locator("summary").click()
                observed_evidence = json.loads(
                    fixture_evidence.locator("pre").inner_text()
                )
                self.assertEqual("mixed-correction", observed_evidence["scenario"])
                self.assertTrue(observed_evidence["official_api_shape"])
                self.assertEqual(0, observed_evidence["external_network_requests"])
                self.assertFalse(observed_evidence["production_credentials_loaded"])
                self.assertFalse(observed_evidence["spend_started"])
                self.assertEqual(0, observed_evidence["operations"]["resume_calls"])
                self.assertNotIn(
                    "campaigns.resume",
                    observed_evidence["operations"]["mutations"],
                )
                self.assertIn(
                    "campaigns.suspend",
                    observed_evidence["operations"]["mutations"],
                )
                provider_calls = observed_evidence["calls"]
                self.assertGreater(len(provider_calls), 0)
                self.assertEqual(
                    len(provider_calls),
                    len({call["request_id"] for call in provider_calls}),
                )
                self.assertEqual(
                    len(provider_calls),
                    len({call["response_id"] for call in provider_calls}),
                )
                application_evidence = observed_evidence["application"]
                self.assertEqual(2, len(application_evidence["selected_drafts"]))
                self.assertEqual(
                    "PASS_WITH_PLATFORM_REJECTIONS",
                    application_evidence["package"]["verdict"],
                )
                self.assertEqual(
                    ["DIRECT_ACCEPTED", "REJECTED_NEEDS_EDIT"],
                    [
                        item["status"]
                        for item in application_evidence["package"]["items"]
                    ],
                )
                self.assertTrue(
                    all(
                        item["campaign_state"] == "SUSPENDED"
                        for item in application_evidence["package"]["items"]
                    )
                )
                self.assertEqual(
                    "PASS_AFTER_CORRECTION",
                    application_evidence["corrections"][0]["terminal_outcome"],
                )
                self.assertEqual(
                    ["SUSPENDED"],
                    application_evidence["corrections"][0]["campaign_states"],
                )
                self.assertEqual(
                    {
                        "all-success",
                        "mixed-provider-outcomes",
                        "pending-and-preaccepted",
                        "unknown-and-reconciliation",
                        "system-failure",
                        "correction",
                    },
                    {
                        item["scenario"]
                        for item in observed_evidence["contract_coverage"]
                    },
                )
                acceptance = {
                    "schema_version": "p0-production-candidate-acceptance-v1",
                    "viewport": VIEWPORT,
                    "ui": {
                        "five_steps": 5,
                        "accessible_labels": True,
                        "keyboard_drawer_path": True,
                        "horizontal_overflow": False,
                        "console_errors": console_errors,
                        "page_errors": page_errors,
                        "nonlocal_browser_requests": nonlocal_requests,
                    },
                    "fixture": observed_evidence,
                }
                if os.environ.get("UPDATE_P0_E2E_ACCEPTANCE") == "1":
                    ACCEPTANCE_ARTIFACT.write_text(
                        json.dumps(
                            acceptance,
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                expected_acceptance = json.loads(
                    ACCEPTANCE_ARTIFACT.read_text(encoding="utf-8")
                )
                self.assertEqual(expected_acceptance, acceptance)

                self.assertEqual([], console_errors)
                self.assertEqual([], page_errors)
                self.assertEqual([], nonlocal_requests)
                assert_no_horizontal_overflow(self, page)
                browser.close()


if __name__ == "__main__":
    unittest.main()
