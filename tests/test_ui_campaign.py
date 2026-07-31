from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import Any

from mox_adv.campaign_lifecycle import CampaignDraftSafetyBindings
from mox_adv.ui_campaign import (
    DashboardCampaignRejected,
    DashboardCampaignStore,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads(
    (ROOT / "config" / "gate0-policy.json").read_text(encoding="utf-8")
)


def campaign_store(path: Path) -> DashboardCampaignStore:
    return DashboardCampaignStore(
        path,
        policy=POLICY,
        campaign_safety=CampaignDraftSafetyBindings(
            allowed_landing_hosts=("allowlisted.example",),
            prohibited_phrases=("guaranteed results",),
            prepared_media_references=(
                "prepared-media-1",
                "prepared-media-2",
            ),
        ),
    )


def editable_value(current: dict[str, Any]) -> dict[str, Any]:
    return {
        "campaign": current["campaign"],
        "business_goal": current["business_goal"],
        "goal_settings": current["goal_settings"],
        "ad_groups": current["ad_groups"],
    }


class DashboardCampaignStoreTests(unittest.TestCase):
    def test_version_one_draft_is_upgraded_on_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.sqlite3"
            store = campaign_store(path)
            current = store.load()
            legacy = {
                key: value
                for key, value in current.items()
                if key
                not in {
                    "ad_groups",
                    "created_at",
                    "goal_settings",
                    "revision",
                    "safety",
                    "updated_at",
                }
            }
            legacy["schema_version"] = "dashboard-campaign-v1"
            with closing(sqlite3.connect(path)) as connection:
                with connection:
                    connection.execute(
                        "UPDATE campaign_drafts SET payload_json = ? "
                        "WHERE draft_id = ?",
                        (
                            json.dumps(legacy, ensure_ascii=False),
                            current["draft_id"],
                        ),
                    )

            upgraded = campaign_store(path).load()

            self.assertEqual("dashboard-campaign-v2", upgraded["schema_version"])
            self.assertEqual(1, len(upgraded["goal_settings"]["goals"]))
            self.assertEqual(1, len(upgraded["ad_groups"]))
            self.assertEqual(
                {"A", "B"},
                {
                    ad["pilot_role"]
                    for ad in upgraded["ad_groups"][0]["ads"]
                },
            )

    def test_operator_can_list_select_edit_and_delete_campaigns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = campaign_store(Path(temporary) / "campaign.sqlite3")
            initial = store.load()

            created = store.create_new(expected_revision=0)
            catalog = store.catalog()

            self.assertEqual(2, catalog["total"])
            self.assertEqual(created["draft_id"], catalog["selected"]["draft_id"])
            self.assertTrue(catalog["items"][0]["selected"])

            value = editable_value(created)
            value["campaign"]["name"] = "Весенняя лидогенерация"
            saved = store.save(
                value,
                expected_revision=0,
                draft_id=str(created["draft_id"]),
            )
            self.assertEqual(1, saved["revision"])

            store.select(str(initial["draft_id"]))
            after_delete = store.delete(
                str(initial["draft_id"]),
                expected_revision=0,
            )

            self.assertEqual(1, after_delete["total"])
            self.assertEqual(
                "Весенняя лидогенерация",
                after_delete["selected"]["campaign"]["name"],
            )
            with self.assertRaisesRegex(
                DashboardCampaignRejected,
                "единственную кампанию",
            ):
                store.delete(
                    str(created["draft_id"]),
                    expected_revision=1,
                )

    def test_saved_goal_becomes_analysis_and_lifecycle_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = campaign_store(Path(temporary) / "campaign.sqlite3")
            current = store.load()
            value = editable_value(current)
            value["campaign"]["name"] = "Заявки на консультацию"
            value["business_goal"]["meaning"] = (
                "Получать заявки на консультацию"
            )
            value["business_goal"]["target_cpa_rub"] = 900

            saved = store.save(value, expected_revision=0)

            self.assertEqual(1, saved["revision"])
            self.assertFalse(saved["safety"]["external_write_sent"])
            self.assertEqual(
                {
                    "business_goal": {
                        "event": "lead_submitted",
                        "meaning": "Получать заявки на консультацию",
                    },
                    "target_kpi": {
                        "name": "CPA_RUB",
                        "target_maximum": 900,
                    },
                },
                store.analysis_context(),
            )
            self.assertEqual(
                "Заявки на консультацию",
                store.campaign_draft_payload()["name"],
            )
            self.assertEqual(
                "Получать заявки на консультацию",
                store.goal_candidate_payload()["business_meaning"],
            )

    def test_multiple_goals_groups_and_ads_persist_with_pilot_projection(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = campaign_store(Path(temporary) / "campaign.sqlite3")
            current = store.load()
            value = editable_value(current)
            value["goal_settings"]["attribution_model"] = "LSCCD"
            value["goal_settings"]["goals"].append(
                {
                    "id": "goal-form-started",
                    "name": "Начато заполнение формы",
                    "event": "form_started",
                    "site_location": "#lead-form",
                    "type": "ACTION",
                    "source": "METRIKA",
                    "value_mode": "FIXED",
                    "value_rub": 250,
                    "primary": False,
                }
            )
            value["ad_groups"][0]["name"] = "Консультации"
            value["ad_groups"][0]["ads"][0]["titles"].append(
                "Ответим сегодня"
            )
            value["ad_groups"][0]["ads"].append(
                {
                    "id": "group-primary-ad-extra",
                    "pilot_role": None,
                    "titles": ["Третий вариант объявления"],
                    "texts": ["Подберём решение под вашу задачу"],
                    "href": "https://allowlisted.example/lead",
                    "display_url_path": "solution",
                    "image_references": ["prepared-media-1"],
                    "sitelinks": [],
                    "callouts": ["Без навязчивых звонков"],
                }
            )

            saved = store.save(value, expected_revision=0)
            projected = store.campaign_draft_payload()

            self.assertEqual(2, len(saved["goal_settings"]["goals"]))
            self.assertEqual(3, len(saved["ad_groups"][0]["ads"]))
            self.assertEqual("LSCCD", saved["goal_settings"]["attribution_model"])
            self.assertEqual("Консультации", projected["groups"][0]["name"])
            self.assertEqual(
                ["A", "B"],
                [
                    ad["variant_id"]
                    for ad in projected["groups"][0]["ads"]
                ],
            )

    def test_stale_revision_and_target_above_gate_zero_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = campaign_store(Path(temporary) / "campaign.sqlite3")
            initial = store.load()
            value = editable_value(initial)
            store.save(value, expected_revision=0)

            with self.assertRaisesRegex(
                DashboardCampaignRejected,
                "изменился",
            ):
                store.save(value, expected_revision=0)

            latest = store.load()
            unsafe = editable_value(latest)
            unsafe["business_goal"]["target_cpa_rub"] = (
                int(POLICY["mandate"]["kpi"]["target_maximum"]) + 1
            )
            with self.assertRaisesRegex(
                DashboardCampaignRejected,
                "Целевой CPA",
            ):
                store.save(unsafe, expected_revision=1)


if __name__ == "__main__":
    unittest.main()
