"""Persistent operator drafts for advertising campaigns and their goals."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlparse

from mox_adv.campaign_lifecycle import (
    CampaignDraftSafetyBindings,
    LifecycleRejected,
    validate_campaign_draft,
)
from mox_adv.goal_contracts import GoalLifecycleRejected, validate_candidate

_DASHBOARD_SCHEMA_VERSION = "dashboard-campaign-v2"
_STRATEGIES = frozenset(
    {
        "MAXIMIZE_CONVERSIONS",
        "MAXIMIZE_CLICKS",
        "MAXIMIZE_PROFIT",
    }
)
_PAYMENT_MODELS = frozenset({"CLICKS", "CONVERSIONS"})
_ATTRIBUTION_MODELS = frozenset({"AUTO", "LC", "LSCCD", "FCCD"})
_GOAL_TYPES = frozenset({"ACTION", "ECOMMERCE", "COMPOSITE", "OFFLINE"})
_GOAL_SOURCES = frozenset({"METRIKA", "AUTO", "OFFLINE"})
_GOAL_VALUE_MODES = frozenset({"FIXED", "DYNAMIC"})
_AUTOTARGETING_CATEGORIES = frozenset(
    {"EXACT", "ALTERNATIVE", "COMPETITOR", "BROADER", "ACCESSORY"}
)


class DashboardCampaignRejected(ValueError):
    """The campaign editor input is invalid or stale."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class DashboardCampaignLaunchHistory:
    """Index immutable campaign lifecycle results by local draft."""

    def __init__(self, runs_root: Path) -> None:
        self.runs_root = Path(runs_root)
        self._lock = RLock()
        self._launches = self._recover()

    def latest(self, draft_id: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._launches.get(draft_id)
            return self._copy(value) if value is not None else None

    def record(self, value: Mapping[str, Any]) -> None:
        candidate = self._candidate(value)
        if candidate is None:
            raise ValueError("CAMPAIGN_LAUNCH_RESULT_INVALID")
        draft_id = str(candidate["exact_diff"]["after"]["draft_id"])
        with self._lock:
            current = self._launches.get(draft_id)
            if current is None or self._order(candidate) >= self._order(current):
                self._launches[draft_id] = candidate

    def _recover(self) -> dict[str, dict[str, Any]]:
        launches: dict[str, dict[str, Any]] = {}
        artifacts = sorted(self.runs_root.glob("ui-campaign-*/campaign_workflow.json"))
        for artifact in artifacts:
            try:
                raw = json.loads(artifact.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            candidate = self._candidate(raw)
            if candidate is None:
                continue
            draft_id = str(candidate["exact_diff"]["after"]["draft_id"])
            current = launches.get(draft_id)
            if current is None or self._order(candidate) >= self._order(current):
                launches[draft_id] = candidate
        return launches

    @classmethod
    def _candidate(
        cls,
        value: Any,
    ) -> dict[str, Any] | None:
        if not isinstance(value, Mapping):
            return None
        try:
            exact_diff = value["exact_diff"]
            launched_draft = exact_diff["after"]
            completed_steps = value["completed_steps"]
            required_text = (
                value["workflow"],
                value["status"],
                value["execution_mode"],
                value["run_id"],
                value["requested_at"],
                launched_draft["draft_id"],
            )
        except (KeyError, TypeError):
            return None
        if (
            value["workflow"] != "CAMPAIGN_LIFECYCLE"
            or not isinstance(exact_diff, Mapping)
            or not isinstance(launched_draft, Mapping)
            or not all(isinstance(item, str) and item for item in required_text)
            or not isinstance(completed_steps, list)
            or not all(isinstance(item, str) for item in completed_steps)
            or not isinstance(value.get("external_write_sent"), bool)
            or value.get("detail") is not None
            and not isinstance(value.get("detail"), str)
        ):
            return None
        return cls._copy(value)

    @staticmethod
    def _copy(value: Mapping[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(value, ensure_ascii=False))

    @staticmethod
    def _order(value: Mapping[str, Any]) -> tuple[str, str]:
        return str(value["requested_at"]), str(value["run_id"])


class DashboardCampaignStore:
    """Versioned SQLite storage for local campaign drafts."""

    def __init__(
        self,
        path: Path,
        *,
        policy: Mapping[str, Any],
        campaign_safety: CampaignDraftSafetyBindings,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.policy = policy
        self.campaign_safety = campaign_safety
        self._initialize()

    def catalog(self) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            selected_id = self._selected_id(connection)
            rows = connection.execute(
                "SELECT draft_id, revision, payload_json, created_at, updated_at "
                "FROM campaign_drafts "
                "ORDER BY COALESCE(updated_at, created_at) DESC, created_at DESC"
            ).fetchall()
        items = [
            self._summary(
                self._view_from_row(row),
                selected=str(row["draft_id"]) == selected_id,
            )
            for row in rows
        ]
        selected = next(
            (
                self._view_from_row(row)
                for row in rows
                if str(row["draft_id"]) == selected_id
            ),
            None,
        )
        return {
            "items": items,
            "selected": selected,
            "total": len(items),
            "safety": {
                "editing_scope": "LOCAL_DRAFTS",
                "external_write_sent": False,
            },
        }

    def load(self, draft_id: str | None = None) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            target_id = draft_id or self._selected_id(connection)
            row = connection.execute(
                "SELECT draft_id, revision, payload_json, created_at, updated_at "
                "FROM campaign_drafts WHERE draft_id = ?",
                (target_id,),
            ).fetchone()
        if row is None:
            raise DashboardCampaignRejected(
                "CAMPAIGN_NOT_FOUND",
                "Кампания не найдена или уже удалена.",
            )
        return self._view_from_row(row)

    def create_new(self, *, expected_revision: int) -> dict[str, Any]:
        self._validate_revision(expected_revision)
        current = self.load()
        if int(current["revision"]) != expected_revision:
            raise DashboardCampaignRejected(
                "CAMPAIGN_REVISION_CONFLICT",
                "Выбранная кампания изменилась. Обновите страницу и повторите.",
            )
        payload = self._default_payload(
            draft_id="dashboard-campaign-" + uuid.uuid4().hex[:12]
        )
        created_at = datetime.now(timezone.utc).isoformat()
        encoded = self._encode(payload)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO campaign_drafts "
                "(draft_id, revision, payload_json, created_at, updated_at) "
                "VALUES (?, 0, ?, ?, NULL)",
                (str(payload["draft_id"]), encoded, created_at),
            )
            self._record_event(
                connection,
                draft_id=str(payload["draft_id"]),
                revision=0,
                event_type="CREATE",
                payload_json=encoded,
                created_at=created_at,
            )
            self._set_selected(connection, str(payload["draft_id"]))
            connection.commit()
        return self._view(
            payload,
            revision=0,
            created_at=created_at,
            updated_at=None,
        )

    def save(
        self,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        draft_id: str | None = None,
    ) -> dict[str, Any]:
        current = self.load(draft_id)
        payload = self._normalize_editor_value(
            value,
            draft_id=str(current["draft_id"]),
        )
        return self._save(
            payload,
            expected_revision=expected_revision,
        )

    def select(self, draft_id: str) -> dict[str, Any]:
        selected = self.load(draft_id)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._set_selected(connection, draft_id)
            connection.commit()
        return selected

    def delete(
        self,
        draft_id: str,
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        self._validate_revision(expected_revision)
        deleted_at = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision, payload_json FROM campaign_drafts WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
            if row is None:
                raise DashboardCampaignRejected(
                    "CAMPAIGN_NOT_FOUND",
                    "Кампания не найдена или уже удалена.",
                )
            if int(row["revision"]) != expected_revision:
                raise DashboardCampaignRejected(
                    "CAMPAIGN_REVISION_CONFLICT",
                    "Черновик кампании изменился. Обновите страницу и повторите.",
                )
            count = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM campaign_drafts"
                ).fetchone()["count"]
            )
            if count <= 1:
                raise DashboardCampaignRejected(
                    "CAMPAIGN_LAST_DELETE_REJECTED",
                    "Нельзя удалить единственную кампанию. Сначала создайте новую.",
                )
            selected_before = self._selected_id(connection)
            connection.execute(
                "DELETE FROM campaign_drafts WHERE draft_id = ?",
                (draft_id,),
            )
            self._record_event(
                connection,
                draft_id=draft_id,
                revision=expected_revision + 1,
                event_type="DELETE",
                payload_json=str(row["payload_json"]),
                created_at=deleted_at,
            )
            if selected_before == draft_id:
                replacement = connection.execute(
                    "SELECT draft_id FROM campaign_drafts "
                    "ORDER BY COALESCE(updated_at, created_at) DESC, "
                    "created_at DESC LIMIT 1"
                ).fetchone()
                self._set_selected(connection, str(replacement["draft_id"]))
            connection.commit()
        return self.catalog()

    def campaign_draft_payload(
        self,
        draft_id: str | None = None,
        *,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        value = self.load(draft_id)
        if expected_revision is not None:
            self._validate_revision(expected_revision)
            if int(value["revision"]) != expected_revision:
                raise DashboardCampaignRejected(
                    "CAMPAIGN_REVISION_CONFLICT",
                    "Кампания изменилась. Обновите страницу перед запуском.",
                )
        return self._campaign_draft(value)

    def goal_candidate_payload(
        self,
        draft_id: str | None = None,
        *,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        if draft_id is not None and (
            not isinstance(draft_id, str) or not draft_id.strip()
        ):
            raise DashboardCampaignRejected(
                "CAMPAIGN_DRAFT_ID_REQUIRED",
                "Выберите тестовую кампанию перед проверкой цели.",
            )
        value = self.load(draft_id)
        if expected_revision is not None:
            self._validate_revision(expected_revision)
            if int(value["revision"]) != expected_revision:
                raise DashboardCampaignRejected(
                    "CAMPAIGN_REVISION_CONFLICT",
                    "Кампания изменилась. Обновите страницу перед проверкой цели.",
                )
        return self._goal_candidate(value)

    def analysis_context(self) -> dict[str, Any]:
        value = self.load()
        primary_goal = self._primary_goal(value)
        return {
            "business_goal": {
                "event": str(primary_goal["event"]),
                "meaning": str(value["business_goal"]["meaning"]),
            },
            "target_kpi": {
                "name": "CPA_RUB",
                "target_maximum": int(value["business_goal"]["target_cpa_rub"]),
            },
        }

    def _save(
        self,
        payload: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        self._validate_revision(expected_revision)
        normalized = self._validate_payload(payload)
        updated_at = datetime.now(timezone.utc).isoformat()
        encoded = self._encode(normalized)
        draft_id = str(normalized["draft_id"])
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision, created_at FROM campaign_drafts WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
            if row is None:
                raise DashboardCampaignRejected(
                    "CAMPAIGN_NOT_FOUND",
                    "Кампания не найдена или уже удалена.",
                )
            current_revision = int(row["revision"])
            if current_revision != expected_revision:
                raise DashboardCampaignRejected(
                    "CAMPAIGN_REVISION_CONFLICT",
                    "Черновик кампании изменился. Обновите страницу и повторите.",
                )
            revision = current_revision + 1
            connection.execute(
                "UPDATE campaign_drafts "
                "SET revision = ?, payload_json = ?, updated_at = ? "
                "WHERE draft_id = ?",
                (
                    revision,
                    encoded,
                    updated_at,
                    draft_id,
                ),
            )
            self._record_event(
                connection,
                draft_id=draft_id,
                revision=revision,
                event_type="UPDATE",
                payload_json=encoded,
                created_at=updated_at,
            )
            self._set_selected(connection, draft_id)
            connection.commit()
        return self._view(
            normalized,
            revision=revision,
            created_at=str(row["created_at"]),
            updated_at=updated_at,
        )

    def _normalize_editor_value(
        self,
        value: Mapping[str, Any],
        *,
        draft_id: str,
    ) -> dict[str, Any]:
        if set(value) != {
            "campaign",
            "business_goal",
            "goal_settings",
            "ad_groups",
        }:
            raise DashboardCampaignRejected(
                "CAMPAIGN_EDITOR_INVALID",
                "Поля черновика кампании не соответствуют контракту.",
            )
        campaign = value.get("campaign")
        business_goal = value.get("business_goal")
        goal_settings = value.get("goal_settings")
        ad_groups = value.get("ad_groups")
        if (
            not isinstance(campaign, Mapping)
            or set(campaign)
            != {
                "name",
                "weekly_budget_rub",
                "keyword",
                "landing_page",
            }
            or not isinstance(business_goal, Mapping)
            or set(business_goal) != {"meaning", "target_cpa_rub"}
            or not isinstance(goal_settings, Mapping)
            or not isinstance(ad_groups, list)
        ):
            raise DashboardCampaignRejected(
                "CAMPAIGN_EDITOR_INVALID",
                "Поля кампании или цели не соответствуют контракту.",
            )
        goals = goal_settings.get("goals")
        if not isinstance(goals, list):
            raise DashboardCampaignRejected(
                "CAMPAIGN_EDITOR_INVALID",
                "Список целевых действий отсутствует.",
            )
        primary_goals = [
            goal
            for goal in goals
            if isinstance(goal, Mapping) and goal.get("primary") is True
        ]
        if len(primary_goals) != 1:
            raise DashboardCampaignRejected(
                "CAMPAIGN_PRIMARY_GOAL_REQUIRED",
                "Выберите одну основную цель кампании.",
            )
        primary_goal = primary_goals[0]
        return {
            "schema_version": _DASHBOARD_SCHEMA_VERSION,
            "draft_id": draft_id,
            "status": "DRAFT",
            "campaign": json.loads(json.dumps(dict(campaign), ensure_ascii=False)),
            "business_goal": json.loads(
                json.dumps(dict(business_goal), ensure_ascii=False)
            ),
            "metrika_goal": {
                "name": primary_goal.get("name"),
                "event": primary_goal.get("event"),
                "site_location": primary_goal.get("site_location"),
            },
            "goal_settings": json.loads(
                json.dumps(dict(goal_settings), ensure_ascii=False)
            ),
            "ad_groups": json.loads(json.dumps(ad_groups, ensure_ascii=False)),
        }

    def _validate_payload(self, value: Mapping[str, Any]) -> dict[str, Any]:
        if (
            set(value)
            != {
                "schema_version",
                "draft_id",
                "status",
                "campaign",
                "business_goal",
                "metrika_goal",
                "goal_settings",
                "ad_groups",
            }
            or value.get("schema_version") != _DASHBOARD_SCHEMA_VERSION
        ):
            raise DashboardCampaignRejected(
                "CAMPAIGN_EDITOR_INVALID",
                "Черновик кампании имеет неподдерживаемую схему.",
            )
        if value.get("status") != "DRAFT":
            raise DashboardCampaignRejected(
                "CAMPAIGN_STATUS_INVALID",
                "Редактор поддерживает только локальный черновик.",
            )
        target = value["business_goal"]["target_cpa_rub"]
        maximum = int(self.policy["mandate"]["kpi"]["target_maximum"])
        if (
            isinstance(target, bool)
            or not isinstance(target, int)
            or not 1 <= target <= maximum
        ):
            raise DashboardCampaignRejected(
                "CAMPAIGN_TARGET_KPI_INVALID",
                f"Целевой CPA должен быть от 1 до {maximum} ₽.",
            )
        self._validate_goal_settings(value)
        self._validate_ad_groups(value)
        draft = self._campaign_draft(value)
        candidate = self._goal_candidate(value)
        try:
            validate_campaign_draft(
                draft,
                self.policy,
                self.campaign_safety,
            )
            validate_candidate(candidate, self.policy)
        except (
            GoalLifecycleRejected,
            KeyError,
            LifecycleRejected,
            TypeError,
            ValueError,
        ) as error:
            raise DashboardCampaignRejected(
                "CAMPAIGN_EDITOR_INVALID",
                str(error),
            ) from error
        return json.loads(json.dumps(value, ensure_ascii=False))

    def _validate_goal_settings(self, value: Mapping[str, Any]) -> None:
        settings = value.get("goal_settings")
        if (
            not isinstance(settings, Mapping)
            or set(settings)
            != {
                "strategy",
                "payment_model",
                "attribution_model",
                "counter_id",
                "goals",
            }
            or settings.get("strategy") not in _STRATEGIES
            or settings.get("payment_model") not in _PAYMENT_MODELS
            or settings.get("attribution_model") not in _ATTRIBUTION_MODELS
            or settings.get("counter_id")
            != self.policy["bindings"]["simulation"]["test_counter"]
        ):
            raise DashboardCampaignRejected(
                "CAMPAIGN_GOAL_SETTINGS_INVALID",
                "Настройки стратегии или счётчика некорректны.",
            )
        if (
            settings["strategy"] == "MAXIMIZE_CLICKS"
            and settings["payment_model"] != "CLICKS"
        ):
            raise DashboardCampaignRejected(
                "CAMPAIGN_GOAL_SETTINGS_INVALID",
                "Для максимума кликов доступна только оплата за клики.",
            )
        goals = settings.get("goals")
        if not isinstance(goals, list) or not 1 <= len(goals) <= 30:
            raise DashboardCampaignRejected(
                "CAMPAIGN_GOALS_INVALID",
                "Добавьте от одной до 30 целей кампании.",
            )
        seen_ids: set[str] = set()
        primary_count = 0
        for goal in goals:
            if not isinstance(goal, Mapping) or set(goal) != {
                "id",
                "name",
                "event",
                "site_location",
                "type",
                "source",
                "value_mode",
                "value_rub",
                "primary",
            }:
                raise DashboardCampaignRejected(
                    "CAMPAIGN_GOALS_INVALID",
                    "Поля целевого действия не соответствуют контракту.",
                )
            goal_id = self._text(goal["id"], "ID цели", 64)
            if goal_id in seen_ids:
                raise DashboardCampaignRejected(
                    "CAMPAIGN_GOALS_INVALID",
                    "Идентификаторы целей должны быть уникальны.",
                )
            seen_ids.add(goal_id)
            self._text(goal["name"], "Название цели", 128)
            self._text(goal["event"], "Событие цели", 128)
            self._text(goal["site_location"], "Селектор цели", 500)
            if (
                goal["type"] not in _GOAL_TYPES
                or goal["source"] not in _GOAL_SOURCES
                or goal["value_mode"] not in _GOAL_VALUE_MODES
                or not isinstance(goal["primary"], bool)
            ):
                raise DashboardCampaignRejected(
                    "CAMPAIGN_GOALS_INVALID",
                    "Тип, источник или ценность цели некорректны.",
                )
            value_rub = goal["value_rub"]
            if goal["value_mode"] == "FIXED" and (
                isinstance(value_rub, bool)
                or not isinstance(value_rub, int)
                or not 1 <= value_rub <= 1_000_000_000
            ):
                raise DashboardCampaignRejected(
                    "CAMPAIGN_GOALS_INVALID",
                    "Для цели с ручной ценностью укажите сумму в рублях.",
                )
            if goal["value_mode"] == "DYNAMIC" and value_rub is not None:
                raise DashboardCampaignRejected(
                    "CAMPAIGN_GOALS_INVALID",
                    "Динамическая ценность должна поступать из Метрики.",
                )
            if goal["primary"]:
                primary_count += 1
                if goal["event"] != self.policy["conversion"]["primary"]["event"]:
                    raise DashboardCampaignRejected(
                        "CAMPAIGN_PRIMARY_GOAL_INVALID",
                        "Основная цель должна совпадать с Gate 0.",
                    )
        if primary_count != 1:
            raise DashboardCampaignRejected(
                "CAMPAIGN_PRIMARY_GOAL_REQUIRED",
                "Выберите одну основную цель кампании.",
            )

    def _validate_ad_groups(self, value: Mapping[str, Any]) -> None:
        groups = value.get("ad_groups")
        if not isinstance(groups, list) or not 1 <= len(groups) <= 20:
            raise DashboardCampaignRejected(
                "CAMPAIGN_AD_GROUPS_INVALID",
                "Добавьте от одной до 20 групп объявлений.",
            )
        seen_group_ids: set[str] = set()
        pilot_groups = 0
        for group in groups:
            if not isinstance(group, Mapping) or set(group) != {
                "id",
                "name",
                "selected_for_pilot",
                "keywords",
                "negative_keywords",
                "autotargeting",
                "ads",
            }:
                raise DashboardCampaignRejected(
                    "CAMPAIGN_AD_GROUPS_INVALID",
                    "Поля группы объявлений не соответствуют контракту.",
                )
            group_id = self._text(group["id"], "ID группы", 64)
            if group_id in seen_group_ids:
                raise DashboardCampaignRejected(
                    "CAMPAIGN_AD_GROUPS_INVALID",
                    "Идентификаторы групп должны быть уникальны.",
                )
            seen_group_ids.add(group_id)
            self._text(group["name"], "Название группы", 255)
            if not isinstance(group["selected_for_pilot"], bool):
                raise DashboardCampaignRejected(
                    "CAMPAIGN_AD_GROUPS_INVALID",
                    "Признак пилотной группы некорректен.",
                )
            if group["selected_for_pilot"]:
                pilot_groups += 1
            self._validate_text_list(
                group["keywords"],
                "Ключевые фразы",
                minimum=1,
                maximum=20,
                item_maximum=4096,
            )
            self._validate_text_list(
                group["negative_keywords"],
                "Минус-фразы",
                minimum=0,
                maximum=50,
                item_maximum=4096,
            )
            autotargeting = group["autotargeting"]
            if (
                not isinstance(autotargeting, Mapping)
                or set(autotargeting) != _AUTOTARGETING_CATEGORIES
                or not all(isinstance(item, bool) for item in autotargeting.values())
            ):
                raise DashboardCampaignRejected(
                    "CAMPAIGN_AD_GROUPS_INVALID",
                    "Категории автотаргетинга некорректны.",
                )
            self._validate_ads(group)
        if pilot_groups != 1:
            raise DashboardCampaignRejected(
                "CAMPAIGN_PILOT_GROUP_REQUIRED",
                "Выберите одну группу для безопасного пилотного запуска.",
            )

    def _validate_ads(self, group: Mapping[str, Any]) -> None:
        ads = group["ads"]
        if not isinstance(ads, list) or not 1 <= len(ads) <= 50:
            raise DashboardCampaignRejected(
                "CAMPAIGN_ADS_INVALID",
                "В группе должно быть от одного до 50 объявлений.",
            )
        seen_ids: set[str] = set()
        pilot_roles: set[str] = set()
        for ad in ads:
            if not isinstance(ad, Mapping) or set(ad) != {
                "id",
                "pilot_role",
                "titles",
                "texts",
                "href",
                "display_url_path",
                "image_references",
                "sitelinks",
                "callouts",
            }:
                raise DashboardCampaignRejected(
                    "CAMPAIGN_ADS_INVALID",
                    "Поля объявления не соответствуют контракту.",
                )
            ad_id = self._text(ad["id"], "ID объявления", 64)
            if ad_id in seen_ids:
                raise DashboardCampaignRejected(
                    "CAMPAIGN_ADS_INVALID",
                    "Идентификаторы объявлений должны быть уникальны.",
                )
            seen_ids.add(ad_id)
            role = ad["pilot_role"]
            if role not in {"A", "B", None}:
                raise DashboardCampaignRejected(
                    "CAMPAIGN_ADS_INVALID",
                    "Роль объявления в пилоте некорректна.",
                )
            if role is not None:
                if role in pilot_roles:
                    raise DashboardCampaignRejected(
                        "CAMPAIGN_ADS_INVALID",
                        "Варианты A и B должны быть уникальны.",
                    )
                pilot_roles.add(role)
            self._validate_text_list(
                ad["titles"],
                "Заголовки объявления",
                minimum=1,
                maximum=7,
                item_maximum=56,
            )
            self._validate_text_list(
                ad["texts"],
                "Тексты объявления",
                minimum=1,
                maximum=3,
                item_maximum=81,
            )
            self._validate_https_url(ad["href"], "Посадочная страница")
            display_path = ad["display_url_path"]
            if not isinstance(display_path, str) or len(display_path) > 20:
                raise DashboardCampaignRejected(
                    "CAMPAIGN_ADS_INVALID",
                    "Отображаемая ссылка не должна превышать 20 символов.",
                )
            self._validate_text_list(
                ad["image_references"],
                "Изображения",
                minimum=0,
                maximum=5,
                item_maximum=128,
            )
            if not set(ad["image_references"]).issubset(
                self.campaign_safety.prepared_media_references
            ):
                raise DashboardCampaignRejected(
                    "CAMPAIGN_ADS_INVALID",
                    "Выбрано неподготовленное изображение.",
                )
            if (
                group["selected_for_pilot"]
                and role in {"A", "B"}
                and not ad["image_references"]
            ):
                raise DashboardCampaignRejected(
                    "CAMPAIGN_PILOT_ADS_REQUIRED",
                    "Для вариантов A и B выберите подготовленное изображение.",
                )
            sitelinks = ad["sitelinks"]
            if not isinstance(sitelinks, list) or len(sitelinks) > 8:
                raise DashboardCampaignRejected(
                    "CAMPAIGN_ADS_INVALID",
                    "Допускается не более восьми быстрых ссылок.",
                )
            for sitelink in sitelinks:
                if not isinstance(sitelink, Mapping) or set(sitelink) != {
                    "title",
                    "href",
                }:
                    raise DashboardCampaignRejected(
                        "CAMPAIGN_ADS_INVALID",
                        "Быстрая ссылка некорректна.",
                    )
                self._text(sitelink["title"], "Быстрая ссылка", 30)
                self._validate_https_url(
                    sitelink["href"],
                    "Адрес быстрой ссылки",
                )
            self._validate_text_list(
                ad["callouts"],
                "Уточнения",
                minimum=0,
                maximum=50,
                item_maximum=25,
            )
        if group["selected_for_pilot"] and pilot_roles != {"A", "B"}:
            raise DashboardCampaignRejected(
                "CAMPAIGN_PILOT_ADS_REQUIRED",
                "В пилотной группе выберите варианты A и B.",
            )
        if not group["selected_for_pilot"] and pilot_roles:
            raise DashboardCampaignRejected(
                "CAMPAIGN_ADS_INVALID",
                "Роли A/B разрешены только в выбранной пилотной группе.",
            )

    @staticmethod
    def _text(value: Any, label: str, maximum: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise DashboardCampaignRejected(
                "CAMPAIGN_EDITOR_INVALID",
                f"{label}: заполните поле длиной до {maximum} символов.",
            )
        return value

    @classmethod
    def _validate_text_list(
        cls,
        value: Any,
        label: str,
        *,
        minimum: int,
        maximum: int,
        item_maximum: int,
    ) -> None:
        if (
            not isinstance(value, list)
            or not minimum <= len(value) <= maximum
            or not all(isinstance(item, str) for item in value)
            or len(value) != len(set(value))
        ):
            raise DashboardCampaignRejected(
                "CAMPAIGN_EDITOR_INVALID",
                f"{label}: количество или дубликаты значений некорректны.",
            )
        for item in value:
            cls._text(item, label, item_maximum)

    def _validate_https_url(self, value: Any, label: str) -> None:
        text = self._text(value, label, 2048)
        parsed = urlparse(text)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.hostname not in self.campaign_safety.allowed_landing_hosts
        ):
            raise DashboardCampaignRejected(
                "CAMPAIGN_EDITOR_INVALID",
                f"{label}: используйте разрешённый HTTPS-домен.",
            )

    def _campaign_draft(self, value: Mapping[str, Any]) -> dict[str, Any]:
        campaign = value["campaign"]
        goal = value["business_goal"]
        metrika = self._primary_goal(value)
        pilot_group = next(
            group for group in value["ad_groups"] if group["selected_for_pilot"]
        )
        pilot_ads = {
            ad["pilot_role"]: ad
            for ad in pilot_group["ads"]
            if ad["pilot_role"] in {"A", "B"}
        }
        weekly_micros = int(campaign["weekly_budget_rub"]) * 1_000_000
        landing_page = str(campaign["landing_page"])
        campaign_name = str(campaign["name"])
        media_references = sorted(
            {
                str(reference)
                for ad in pilot_ads.values()
                for reference in ad["image_references"]
            }
        )
        return {
            "schema_version": "campaign-draft-v1",
            "draft_id": str(value["draft_id"]),
            "name": campaign_name,
            "business_goal": {
                "event": str(metrika["event"]),
                "meaning": str(goal["meaning"]),
            },
            "primary_conversion": {"event": str(metrika["event"])},
            "campaign_type": "UNIFIED_CAMPAIGN",
            "strategy": {
                "placement": "SEARCH",
                "search": "HIGHEST_POSITION",
                "network": "SERVING_OFF",
            },
            "geography": ["RU"],
            "schedule": {
                "timezone": "Europe/Moscow",
                "days": ["MONDAY", "TUESDAY"],
                "start": "09:00",
                "end": "18:00",
            },
            "budget": {
                "currency": "RUB",
                "weekly_micros": weekly_micros,
            },
            "limits": {
                "maximum_weekly_micros": (
                    int(self.policy["limits"]["platform_weekly_spend_rub"]) * 1_000_000
                ),
                "maximum_bid_micros": 100_000_000,
            },
            "groups": [
                {
                    "name": str(pilot_group["name"]),
                    "keywords": [str(pilot_group["keywords"][0])],
                    "negative_keywords": [
                        str(item) for item in pilot_group["negative_keywords"]
                    ],
                    "audiences": [],
                    "ads": [
                        {
                            "variant_id": role,
                            "title": str(pilot_ads[role]["titles"][0]),
                            "text": str(pilot_ads[role]["texts"][0]),
                            "landing_page": str(pilot_ads[role]["href"]),
                            "utm": ("utm_source=yandex&utm_content=" + role.casefold()),
                            "media_reference": str(
                                pilot_ads[role]["image_references"][0]
                            ),
                        }
                        for role in ("A", "B")
                    ],
                }
            ],
            "landing_page": landing_page,
            "media_references": media_references,
        }

    def _goal_candidate(self, value: Mapping[str, Any]) -> dict[str, Any]:
        metrika = self._primary_goal(value)
        return {
            "schema_version": "goal-candidate-v1",
            "name": str(metrika["name"]),
            "event": str(metrika["event"]),
            "site_location": str(metrika["site_location"]),
            "type": "ACTION",
            "business_meaning": str(value["business_goal"]["meaning"]),
            "priority": 1,
            "duplicate_signals": [],
        }

    def _default_payload(self, *, draft_id: str) -> dict[str, Any]:
        primary = self.policy["conversion"]["primary"]
        landing_page = "https://allowlisted.example/lead"
        campaign_name = "Заявки с сайта"
        return {
            "schema_version": _DASHBOARD_SCHEMA_VERSION,
            "draft_id": draft_id,
            "status": "DRAFT",
            "campaign": {
                "name": campaign_name,
                "weekly_budget_rub": 500,
                "keyword": "консультация",
                "landing_page": landing_page,
            },
            "business_goal": {
                "meaning": "Получать заявки через форму на сайте",
                "target_cpa_rub": int(self.policy["mandate"]["kpi"]["target_maximum"]),
            },
            "metrika_goal": {
                "name": "Отправлена заявка",
                "event": str(primary["event"]),
                "site_location": "#lead-form",
            },
            "goal_settings": {
                "strategy": "MAXIMIZE_CONVERSIONS",
                "payment_model": "CLICKS",
                "attribution_model": "AUTO",
                "counter_id": str(
                    self.policy["bindings"]["simulation"]["test_counter"]
                ),
                "goals": [
                    {
                        "id": "goal-primary",
                        "name": "Отправлена заявка",
                        "event": str(primary["event"]),
                        "site_location": "#lead-form",
                        "type": "ACTION",
                        "source": "METRIKA",
                        "value_mode": "FIXED",
                        "value_rub": int(
                            self.policy["mandate"]["kpi"]["target_maximum"]
                        ),
                        "primary": True,
                    }
                ],
            },
            "ad_groups": [
                self._default_ad_group(
                    group_id="group-primary",
                    name="Основная группа",
                    keyword="консультация",
                    landing_page=landing_page,
                    selected_for_pilot=True,
                )
            ],
        }

    @staticmethod
    def _view(
        payload: Mapping[str, Any],
        *,
        revision: int,
        created_at: str,
        updated_at: str | None,
    ) -> dict[str, Any]:
        result = json.loads(json.dumps(payload, ensure_ascii=False))
        result.update(
            {
                "revision": revision,
                "created_at": created_at,
                "updated_at": updated_at,
                "safety": {
                    "editing_scope": "LOCAL_DRAFT",
                    "external_write_sent": False,
                },
            }
        )
        return result

    def _view_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return self._view(
            self._upgrade_payload(json.loads(str(row["payload_json"]))),
            revision=int(row["revision"]),
            created_at=str(row["created_at"]),
            updated_at=(
                str(row["updated_at"]) if row["updated_at"] is not None else None
            ),
        )

    def _upgrade_payload(self, value: Mapping[str, Any]) -> dict[str, Any]:
        payload = json.loads(json.dumps(value, ensure_ascii=False))
        if payload.get("schema_version") == _DASHBOARD_SCHEMA_VERSION:
            return payload
        if payload.get("schema_version") != "dashboard-campaign-v1":
            raise DashboardCampaignRejected(
                "CAMPAIGN_EDITOR_INVALID",
                "Черновик кампании имеет неподдерживаемую схему.",
            )
        campaign = payload["campaign"]
        metrika = payload["metrika_goal"]
        target = int(payload["business_goal"]["target_cpa_rub"])
        payload["schema_version"] = _DASHBOARD_SCHEMA_VERSION
        payload["goal_settings"] = {
            "strategy": "MAXIMIZE_CONVERSIONS",
            "payment_model": "CLICKS",
            "attribution_model": "AUTO",
            "counter_id": str(self.policy["bindings"]["simulation"]["test_counter"]),
            "goals": [
                {
                    "id": "goal-primary",
                    "name": str(metrika["name"]),
                    "event": str(metrika["event"]),
                    "site_location": str(metrika["site_location"]),
                    "type": "ACTION",
                    "source": "METRIKA",
                    "value_mode": "FIXED",
                    "value_rub": target,
                    "primary": True,
                }
            ],
        }
        payload["ad_groups"] = [
            self._default_ad_group(
                group_id="group-primary",
                name="Основная группа",
                keyword=str(campaign["keyword"]),
                landing_page=str(campaign["landing_page"]),
                selected_for_pilot=True,
            )
        ]
        return payload

    def _default_ad_group(
        self,
        *,
        group_id: str,
        name: str,
        keyword: str,
        landing_page: str,
        selected_for_pilot: bool,
    ) -> dict[str, Any]:
        return {
            "id": group_id,
            "name": name,
            "selected_for_pilot": selected_for_pilot,
            "keywords": [keyword],
            "negative_keywords": ["free"],
            "autotargeting": {
                "EXACT": True,
                "ALTERNATIVE": True,
                "COMPETITOR": False,
                "BROADER": True,
                "ACCESSORY": False,
            },
            "ads": [
                {
                    "id": group_id + "-ad-a",
                    "pilot_role": "A" if selected_for_pilot else None,
                    "titles": ["Консультация специалиста"],
                    "texts": ["Оставьте заявку на консультацию"],
                    "href": landing_page,
                    "display_url_path": "lead",
                    "image_references": ["prepared-media-1"],
                    "sitelinks": [],
                    "callouts": ["Ответим в день обращения"],
                },
                {
                    "id": group_id + "-ad-b",
                    "pilot_role": "B" if selected_for_pilot else None,
                    "titles": ["Разберём вашу задачу"],
                    "texts": ["Получите консультацию по вашей задаче"],
                    "href": landing_page,
                    "display_url_path": "consultation",
                    "image_references": ["prepared-media-2"],
                    "sitelinks": [],
                    "callouts": ["Без навязчивых звонков"],
                },
            ],
        }

    @staticmethod
    def _primary_goal(value: Mapping[str, Any]) -> Mapping[str, Any]:
        goals = value["goal_settings"]["goals"]
        return next(goal for goal in goals if goal["primary"])

    @staticmethod
    def _summary(value: Mapping[str, Any], *, selected: bool) -> dict[str, Any]:
        return {
            "draft_id": str(value["draft_id"]),
            "name": str(value["campaign"]["name"]),
            "status": str(value["status"]),
            "weekly_budget_rub": int(value["campaign"]["weekly_budget_rub"]),
            "target_cpa_rub": int(value["business_goal"]["target_cpa_rub"]),
            "keyword": str(value["campaign"]["keyword"]),
            "revision": int(value["revision"]),
            "created_at": str(value["created_at"]),
            "updated_at": value["updated_at"],
            "selected": selected,
        }

    @staticmethod
    def _encode(value: Mapping[str, Any]) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _validate_revision(revision: int) -> None:
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise DashboardCampaignRejected(
                "CAMPAIGN_REVISION_INVALID",
                "Версия кампании некорректна.",
            )

    @staticmethod
    def _record_event(
        connection: sqlite3.Connection,
        *,
        draft_id: str,
        revision: int,
        event_type: str,
        payload_json: str,
        created_at: str,
    ) -> None:
        connection.execute(
            "INSERT INTO campaign_draft_events "
            "(draft_id, revision, event_type, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (draft_id, revision, event_type, payload_json, created_at),
        )

    @staticmethod
    def _set_selected(
        connection: sqlite3.Connection,
        draft_id: str,
    ) -> None:
        connection.execute(
            "INSERT INTO campaign_store_state (key, value) "
            "VALUES ('selected_campaign_id', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (draft_id,),
        )

    @staticmethod
    def _selected_id(connection: sqlite3.Connection) -> str:
        row = connection.execute(
            "SELECT value FROM campaign_store_state WHERE key = 'selected_campaign_id'"
        ).fetchone()
        if row is not None:
            exists = connection.execute(
                "SELECT 1 FROM campaign_drafts WHERE draft_id = ?",
                (str(row["value"]),),
            ).fetchone()
            if exists is not None:
                return str(row["value"])
        fallback = connection.execute(
            "SELECT draft_id FROM campaign_drafts "
            "ORDER BY COALESCE(updated_at, created_at) DESC, created_at DESC "
            "LIMIT 1"
        ).fetchone()
        if fallback is None:
            raise DashboardCampaignRejected(
                "CAMPAIGN_NOT_FOUND",
                "Нет доступных кампаний.",
            )
        return str(fallback["draft_id"])

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS campaign_draft_versions (
                    revision INTEGER PRIMARY KEY,
                    draft_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS campaign_drafts (
                    draft_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS campaign_draft_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    draft_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS campaign_store_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            current_count = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM campaign_drafts"
                ).fetchone()["count"]
            )
            if current_count == 0:
                legacy = connection.execute(
                    "SELECT revision, draft_id, payload_json, updated_at "
                    "FROM campaign_draft_versions "
                    "ORDER BY revision DESC LIMIT 1"
                ).fetchone()
                if legacy is None:
                    draft_id = "dashboard-campaign-draft"
                    payload = self._default_payload(draft_id=draft_id)
                    revision = 0
                    created_at = datetime.now(timezone.utc).isoformat()
                    updated_at = None
                    event_type = "CREATE"
                else:
                    draft_id = str(legacy["draft_id"])
                    payload = json.loads(str(legacy["payload_json"]))
                    revision = int(legacy["revision"])
                    created_at = str(legacy["updated_at"])
                    updated_at = created_at
                    event_type = "MIGRATE"
                encoded = self._encode(payload)
                connection.execute(
                    "INSERT INTO campaign_drafts "
                    "(draft_id, revision, payload_json, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (draft_id, revision, encoded, created_at, updated_at),
                )
                self._record_event(
                    connection,
                    draft_id=draft_id,
                    revision=revision,
                    event_type=event_type,
                    payload_json=encoded,
                    created_at=created_at,
                )
                self._set_selected(connection, draft_id)
            else:
                selected_id = self._selected_id(connection)
                self._set_selected(connection, selected_id)
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection
