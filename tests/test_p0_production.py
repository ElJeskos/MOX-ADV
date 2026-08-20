from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mox_adv.p0_production import (
    HttpsSiteReader,
    P0ProductionError,
    P0ProductionModule,
    P0ProductionStore,
    YandexDirectP0CampaignCreator,
)
from mox_adv.yandex_read import HttpResponse


class FakeContextReader:
    def __init__(self, duplicates=None):
        self.duplicates = list(duplicates or [])

    def read(self):
        return {
            "environment": "PRODUCTION",
            "test_scenario": False,
            "direct": {
                "ready": True,
                "account": "real-account",
                "campaigns_total": 4,
            },
            "metrika": {"ready": True, "counter_connected": True},
            "performance": {
                "period_start": "2026-08-01",
                "period_end": "2026-08-07",
                "display_metrics": {"ctr_percent": "1.00"},
            },
        }

    def duplicate_campaigns(self, name):
        return list(self.duplicates)


class FakeSiteReader:
    def read(self, url):
        return {
            "url": url,
            "fetched_at": "2026-08-20T10:00:00+00:00",
            "title": "Реальный продукт",
            "description": "Реальная ценность продукта",
            "headings": ["Реальный продукт для бизнеса"],
            "forms_detected": 1,
            "text_excerpt": "Реальный текст сайта.",
        }


class RichSiteReader:
    def read(self, url):
        return {
            "url": url,
            "fetched_at": "2026-08-20T10:00:00+00:00",
            "title": "ИННОПРОМ",
            "description": "Главная промышленная выставка России",
            "headings": ["Объединяем промышленность на одной площадке"],
            "forms_detected": 1,
            "text_excerpt": "Промышленная платформа для производителей и байеров.",
            "pages": [
                {
                    "url": url,
                    "title": "ИННОПРОМ",
                    "headings": ["Объединяем промышленность на одной площадке"],
                    "forms_detected": 0,
                    "text_excerpt": (
                        "Промышленная платформа для производителей и байеров "
                        "со всего мира. Найдите новых покупателей, поставщиков, "
                        "деловых партнеров и инвесторов."
                    ),
                },
                {
                    "url": url + "terms-of-participation-2026",
                    "title": "Условия участия",
                    "headings": ["Стать участником"],
                    "forms_detected": 1,
                    "text_excerpt": (
                        "Заполните короткую форму, и менеджер ИННОПРОМ свяжется "
                        "с вами, чтобы уточнить детали участия."
                    ),
                },
                {
                    "url": url + "registration-visitor-2026",
                    "title": "Регистрация для посетителей",
                    "headings": ["Получение билета посетителя"],
                    "forms_detected": 1,
                    "text_excerpt": "Посетители регистрируются отдельно для получения билета.",
                },
            ],
        }


class FakeCreator:
    def __init__(self, ready=True):
        self.ready = ready
        self.projections = []

    def readiness(self):
        return {
            "ready": self.ready,
            "blockers": [] if self.ready else ["write blocked"],
        }

    def create(self, projection):
        if not self.ready:
            raise P0ProductionError("P0_WRITE_NOT_READY", "write blocked")
        self.projections.append(projection)
        return {
            "execution_id": "p0-real-1",
            "campaign_id": "123",
            "campaign_state": "SUSPENDED",
            "moderation_status": "MODERATION",
            "spend_started": False,
            "status": "MODERATION_PENDING",
            "steps": ["CAMPAIGN_CREATED", "SUSPENDED_CONFIRMED"],
        }


class StubCredential:
    def __init__(self, present):
        self.present = present

    def exists(self):
        return self.present

    def get(self):
        return "secret"


class StubSiteResponse:
    def __init__(self, url, html):
        self.url = url
        self.body = html.encode("utf-8")
        self.headers = {"Content-Type": "text/html; charset=utf-8"}

    def read(self, _maximum):
        return self.body

    def geturl(self):
        return self.url

    def close(self):
        return None


class StubSiteOpener:
    def __init__(self, pages):
        self.pages = dict(pages)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request.full_url, timeout))
        return StubSiteResponse(request.full_url, self.pages[request.full_url])


class StubHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def perform(self, **request):
        self.requests.append(request)
        return self.responses.pop(0)


class P0ProductionModuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = P0ProductionStore(Path(self.temp.name) / "p0.sqlite3")
        self.creator = FakeCreator()
        self.module = P0ProductionModule(
            store=self.store,
            context_reader=FakeContextReader(),
            site_reader=FakeSiteReader(),
            creator=self.creator,
        )

    def tearDown(self):
        self.temp.cleanup()

    def apply(self, action, revision, *, value=None, **extra):
        payload = {
            "action": action,
            "expected_revision": revision,
            **extra,
        }
        if value is not None:
            payload["value"] = value
        return self.module.apply(payload)

    def test_overview_is_production_only_and_contains_real_context(self):
        overview = self.module.overview()
        self.assertEqual("P0_PRODUCTION", overview["module"])
        self.assertEqual("PRODUCTION", overview["environment"])
        self.assertFalse(overview["test_scenario"])
        self.assertEqual("real-account", overview["context"]["direct"]["account"])
        self.assertNotIn("simulation", json.dumps(overview, ensure_ascii=False).lower())

    def test_analysis_researches_public_facts_before_asking_the_owner(self):
        module = P0ProductionModule(
            store=self.store,
            context_reader=FakeContextReader(),
            site_reader=RichSiteReader(),
            creator=self.creator,
        )
        result = module.analyze_site(url="https://expo.example/", expected_revision=0)
        model = result["state"]["business_model"]

        self.assertTrue(model["audience"])
        self.assertTrue(model["qualified_result"])
        self.assertTrue(model["exclusions"])
        self.assertEqual([], model["missing_questions"])
        self.assertGreaterEqual(model["research"]["pages_analyzed"], 3)
        self.assertIn("DIRECT_REAL_ACCOUNT", model["research"]["sources"])
        self.assertIn(
            "terms-of-participation",
            model["field_evidence"]["qualified_result"]["source_url"],
        )
        self.assertNotIn("посетител", model["qualified_result"].casefold())
        for field in (
            "product",
            "audience",
            "value",
            "qualified_result",
            "exclusions",
        ):
            self.assertIn(field, model["field_evidence"])
            self.assertIn(
                model["field_evidence"][field]["confidence"],
                {"HIGH", "MEDIUM"},
            )

    @patch(
        "mox_adv.p0_production.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    def test_full_revision_path_compiles_one_real_publish_projection(self, _resolver):
        result = self.apply(
            "analyze_site",
            0,
            url="https://example.com/landing",
        )
        self.assertEqual(
            "REAL_SITE_AND_CONNECTED_DATA_RESEARCH",
            result["state"]["business_model"]["source"],
        )
        self.assertEqual(
            ["Кто фактически принимает решение о покупке?"],
            result["state"]["business_model"]["missing_questions"],
        )
        self.assertTrue(result["state"]["business_model"]["assumptions"])

        result = self.apply(
            "save_business_model",
            result["revision"],
            value={
                "product": "Реальный продукт",
                "audience": "Руководитель компании",
                "value": "Экономия времени",
                "qualified_result": "Отправленная квалифицированная заявка",
                "exclusions": "Соискатели и информационные запросы",
            },
        )
        self.assertEqual([], result["state"]["business_model"]["missing_questions"])
        self.assertEqual([], result["state"]["business_model"]["assumptions"])
        self.assertTrue(
            result["state"]["business_model"]["research"]["initial_assumptions"]
        )
        self.assertTrue(
            all(
                item["confidence"] == "OWNER_CONFIRMED"
                for item in result["state"]["business_model"]["field_evidence"].values()
            )
        )

        result = self.apply(
            "save_strategy",
            result["revision"],
            value={
                "goal": "Получать квалифицированные заявки",
                "geography": "Москва",
                "period_start": "2026-09-01",
                "period_end": "2026-10-01",
                "landing_page": "https://example.com/landing",
                "weekly_budget_rub": 50000,
                "target_cpa_rub": 10000,
                "message": "Реальный продукт для бизнеса",
            },
        )
        result = self.apply(
            "save_draft",
            result["revision"],
            value={
                "campaign_name": "MOX · Реальный продукт · Поиск",
                "group_name": "Москва · Поиск",
                "keyword": "реальный продукт для бизнеса",
                "negative_keywords": ["вакансии", "бесплатно"],
                "ad_title": "Реальный продукт для бизнеса",
                "ad_text": "Узнайте условия и отправьте квалифицированную заявку.",
            },
        )
        projection = result["state"]["draft"]["publish_projection"]
        self.assertEqual([213], projection["direct"]["ad_group"]["RegionIds"])
        self.assertEqual(
            "WB_MAXIMUM_CLICKS",
            projection["direct"]["campaign"]["UnifiedCampaign"]["BiddingStrategy"]["Search"]["BiddingStrategyType"],
        )
        self.assertEqual(
            "SERVING_OFF",
            projection["direct"]["campaign"]["UnifiedCampaign"]["BiddingStrategy"]["Network"]["BiddingStrategyType"],
        )
        self.assertTrue(projection["safety"]["must_end_suspended"])
        self.assertFalse(projection["safety"]["resume_allowed"])

        with self.assertRaises(P0ProductionError) as error:
            self.apply(
                "confirm_creation",
                result["revision"],
                confirmation="CREATE",
            )
        self.assertEqual("P0_CONFIRMATION_REQUIRED", error.exception.reason_code)

        result = self.apply(
            "confirm_creation",
            result["revision"],
            confirmation="CREATE_SUSPENDED_CAMPAIGN",
        )
        self.assertEqual("SUSPENDED", result["state"]["campaign"]["campaign_state"])
        self.assertFalse(result["state"]["campaign"]["spend_started"])
        self.assertEqual(1, len(self.creator.projections))

    def test_duplicate_campaign_blocks_creation_until_separate_campaign_confirmed(self):
        module = P0ProductionModule(
            store=self.store,
            context_reader=FakeContextReader(["Existing real campaign"]),
            site_reader=FakeSiteReader(),
            creator=self.creator,
        )
        revision = self.store.save_section(
            "draft",
            {
                "duplicate_candidates": ["Existing real campaign"],
                "duplicate_override": False,
                "publish_projection": {"direct": {}},
            },
            expected_revision=0,
        )
        with self.assertRaises(P0ProductionError) as error:
            module.confirm_creation(
                confirmation="CREATE_SUSPENDED_CAMPAIGN",
                expected_revision=revision.revision,
            )
        self.assertEqual("P0_DUPLICATE_CONFIRMATION_REQUIRED", error.exception.reason_code)
        result = module.confirm_distinct_campaign(expected_revision=revision.revision)
        self.assertTrue(result["state"]["draft"]["duplicate_override"])
        result = module.confirm_creation(
            confirmation="CREATE_SUSPENDED_CAMPAIGN",
            expected_revision=result["revision"],
        )
        self.assertEqual("SUSPENDED", result["state"]["campaign"]["campaign_state"])

    def test_revision_conflict_fails_closed(self):
        self.apply("analyze_site", 0, url="https://example.com/")
        with self.assertRaises(P0ProductionError) as error:
            self.apply("reset", 0)
        self.assertEqual("P0_REVISION_CONFLICT", error.exception.reason_code)

    def test_site_reader_researches_relevant_first_party_pages(self):
        opener = StubSiteOpener(
            {
                "https://example.com/": (
                    '<html><head><title>Product</title></head><body>'
                    '<a href="/about">About</a>'
                    '<a href="/terms-of-participation">Participate</a>'
                    '<a href="https://external.example/services">External</a>'
                    '<a href="/privacy-policy">Privacy</a>'
                    "</body></html>"
                ),
                "https://example.com/about": (
                    "<html><h1>For manufacturers and buyers</h1></html>"
                ),
                "https://example.com/terms-of-participation": (
                    "<html><h1>Fill out the form to participate</h1><form></form></html>"
                ),
            }
        )
        reader = HttpsSiteReader(
            resolver=lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
            opener=opener,
        )
        result = reader.read("https://example.com/")

        self.assertEqual(3, result["research"]["pages_analyzed"])
        self.assertEqual(1, result["forms_detected"])
        self.assertEqual(
            {
                "https://example.com/",
                "https://example.com/about",
                "https://example.com/terms-of-participation",
            },
            {page["url"] for page in result["pages"]},
        )
        self.assertNotIn(
            "https://external.example/services",
            [request[0] for request in opener.requests],
        )

    def test_site_reader_rejects_private_targets_before_http(self):
        reader = HttpsSiteReader(
            resolver=lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))]
        )
        with self.assertRaises(P0ProductionError) as error:
            reader.read("https://localhost/")
        self.assertEqual("SITE_PRIVATE_ADDRESS_DENIED", error.exception.reason_code)

    def test_creator_readiness_requires_explicit_policy_bindings_and_keychain(self):
        policy_path = Path(__file__).resolve().parents[1] / "config" / "gate0-policy.json"
        policy = json.loads(policy_path.read_text())
        creator = YandexDirectP0CampaignCreator(
            policy=policy,
            direct_account="real-account",
            store=self.store,
            credential=StubCredential(False),
            http_client=StubHttp([]),
        )
        readiness = creator.readiness()
        self.assertFalse(readiness["ready"])
        self.assertEqual(4, len(readiness["blockers"]))

    def test_guarded_creator_ends_with_suspended_readback_and_no_resume(self):
        policy_path = Path(__file__).resolve().parents[1] / "config" / "gate0-policy.json"
        policy = json.loads(policy_path.read_text())
        policy["record"]["production_write_authorized"] = True
        policy["bindings"]["pilot"]["direct_account"] = "real-account"
        policy["bindings"]["pilot"]["single_writer"] = "p0-single-writer"

        def response(result):
            return HttpResponse(
                status=200,
                headers={},
                body=json.dumps({"result": result}).encode(),
            )

        http = StubHttp(
            [
                response({"AddResults": [{"Id": 101}]}),
                response({"SuspendResults": [{}]}),
                response({"Campaigns": [{"Id": 101, "State": "SUSPENDED"}]}),
                response({"AddResults": [{"Id": 201}]}),
                response({"AddResults": [{"Id": 301}]}),
                response({"AddResults": [{"Id": 401}]}),
                response({"ModerateResults": [{}]}),
                response({"Ads": [{"Id": 401, "Status": "MODERATION"}]}),
                response({"Campaigns": [{"Id": 101, "State": "SUSPENDED"}]}),
            ]
        )
        creator = YandexDirectP0CampaignCreator(
            policy=policy,
            direct_account="real-account",
            store=self.store,
            credential=StubCredential(True),
            http_client=http,
        )
        projection = {
            "direct": {
                "campaign": {
                    "Name": "Real campaign",
                    "StartDate": "2026-09-01",
                    "UnifiedCampaign": {
                        "BiddingStrategy": {
                            "Search": {
                                "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
                                "WbMaximumClicks": {"WeeklySpendLimit": 50_000_000_000},
                            },
                            "Network": {"BiddingStrategyType": "SERVING_OFF"},
                        }
                    },
                },
                "ad_group": {
                    "Name": "Moscow",
                    "RegionIds": [213],
                    "UnifiedAdGroup": {"OfferRetargeting": "NO"},
                },
                "keyword": {"Keyword": "real product"},
                "ad": {
                    "TextAd": {
                        "Title": "Real product",
                        "Text": "Real text",
                        "Href": "https://example.com/",
                        "Mobile": "NO",
                    }
                },
            }
        }
        result = creator.create(projection)
        self.assertEqual("SUSPENDED", result["campaign_state"])
        self.assertEqual("MODERATION_PENDING", result["status"])
        self.assertFalse(result["spend_started"])
        methods = [json.loads(item["body"])["method"] for item in http.requests]
        self.assertEqual(
            ["add", "suspend", "get", "add", "add", "add", "moderate", "get", "get"],
            methods,
        )
        self.assertNotIn("resume", methods)


if __name__ == "__main__":
    unittest.main()
