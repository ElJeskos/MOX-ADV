"""Production P0 module: real business context to a suspended Direct campaign.

The module exposes one small interface to the Dashboard. It owns persistence,
site analysis, production-context reads, publish projection, write readiness,
and the guarded Direct creation sequence. No Test Scenario data enters this
module.
"""

from __future__ import annotations

import copy
import html
import ipaddress
import json
import re
import socket
import sqlite3
import subprocess
import sys
import threading
import uuid
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from mox_adv.egress import (
    CredentialProfile,
    EgressAuthority,
    HttpEgressGuard,
)
from mox_adv.yandex_read import (
    HttpClient,
    UrllibHttpClient,
    YandexProductionReader,
)

_MAX_SITE_BYTES = 5_000_000
_MAX_TEXT = 20_000
_MAX_REDIRECTS = 3
_MAX_SITE_PAGES = 6
_SITE_RESEARCH_TERMS = (
    "about",
    "product",
    "service",
    "solution",
    "particip",
    "partner",
    "price",
    "tariff",
    "registration",
    "become",
    "visitor",
    "client",
    "case",
    "faq",
    "contact",
    "о-компании",
    "о-нас",
    "продукт",
    "услуг",
    "решени",
    "участи",
    "партнер",
    "тариф",
    "цен",
    "регистра",
    "посетител",
    "клиент",
    "контакт",
)
_SITE_RESEARCH_SKIP_TERMS = (
    "privacy",
    "policy",
    "cookie",
    "personal-data",
    "login",
    "logout",
    "sign-in",
    "javascript:",
    "mailto:",
    "tel:",
    ".pdf",
    ".doc",
    ".xls",
    ".zip",
)
_PROXY_SYNTHETIC_NETWORK = ipaddress.ip_network("198.18.0.0/15")
_REGION_IDS = {
    "россия": 225,
    "рф": 225,
    "москва": 213,
    "санкт-петербург": 2,
    "санкт петербург": 2,
}


class P0ProductionError(RuntimeError):
    """Fail-closed product error safe to show in the Dashboard."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class P0ContextReader(Protocol):
    def read(self) -> Mapping[str, Any]: ...

    def duplicate_campaigns(self, name: str) -> list[str]: ...


class P0SiteReader(Protocol):
    def read(self, url: str) -> Mapping[str, Any]: ...


class P0CampaignCreator(Protocol):
    def readiness(self) -> Mapping[str, Any]: ...

    def create(self, projection: Mapping[str, Any]) -> Mapping[str, Any]: ...


class P0BusinessResearcher(Protocol):
    def research(
        self,
        site: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class P0Revision:
    revision: int
    updated_at: str
    value: Mapping[str, Any]


class P0ProductionStore:
    """Durable singleton state and execution journal for the first business."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS p0_state (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    revision INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    value_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS p0_execution (
                    execution_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    projection_json TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );
                """
            )
            row = connection.execute(
                "SELECT singleton FROM p0_state WHERE singleton = 1"
            ).fetchone()
            if row is None:
                now = self._timestamp()
                connection.execute(
                    "INSERT INTO p0_state(singleton, revision, updated_at, value_json) "
                    "VALUES (1, 0, ?, ?)",
                    (now, self._serialize(self._empty_value())),
                )
            connection.commit()

    def load(self) -> P0Revision:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT revision, updated_at, value_json FROM p0_state "
                "WHERE singleton = 1"
            ).fetchone()
        if row is None:
            raise P0ProductionError("P0_STATE_MISSING", "Состояние P0 не найдено.")
        value = json.loads(str(row["value_json"]))
        if not isinstance(value, Mapping):
            raise P0ProductionError("P0_STATE_INVALID", "Состояние P0 повреждено.")
        return P0Revision(
            revision=int(row["revision"]),
            updated_at=str(row["updated_at"]),
            value=copy.deepcopy(dict(value)),
        )

    def save_section(
        self,
        section: str,
        value: Mapping[str, Any] | None,
        *,
        expected_revision: int,
    ) -> P0Revision:
        if section not in {
            "site_analysis",
            "business_model",
            "strategy",
            "draft",
            "campaign",
        }:
            raise P0ProductionError("P0_SECTION_INVALID", "Раздел P0 некорректен.")
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision, value_json FROM p0_state WHERE singleton = 1"
            ).fetchone()
            if row is None:
                raise P0ProductionError("P0_STATE_MISSING", "Состояние P0 не найдено.")
            revision = int(row["revision"])
            if revision != expected_revision:
                raise P0ProductionError(
                    "P0_REVISION_CONFLICT",
                    "P0 изменился в другой вкладке. Обновите страницу.",
                )
            document = json.loads(str(row["value_json"]))
            document[section] = copy.deepcopy(dict(value)) if value is not None else None
            next_revision = revision + 1
            now = self._timestamp()
            connection.execute(
                "UPDATE p0_state SET revision = ?, updated_at = ?, value_json = ? "
                "WHERE singleton = 1",
                (next_revision, now, self._serialize(document)),
            )
            connection.commit()
        return P0Revision(next_revision, now, document)

    def reset(self, *, expected_revision: int) -> P0Revision:
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision FROM p0_state WHERE singleton = 1"
            ).fetchone()
            if row is None or int(row["revision"]) != expected_revision:
                raise P0ProductionError(
                    "P0_REVISION_CONFLICT",
                    "P0 изменился в другой вкладке. Обновите страницу.",
                )
            next_revision = expected_revision + 1
            now = self._timestamp()
            value = self._empty_value()
            connection.execute(
                "UPDATE p0_state SET revision = ?, updated_at = ?, value_json = ? "
                "WHERE singleton = 1",
                (next_revision, now, self._serialize(value)),
            )
            connection.commit()
        return P0Revision(next_revision, now, value)

    def begin_execution(self, projection: Mapping[str, Any]) -> str:
        execution_id = "p0-" + uuid.uuid4().hex
        now = self._timestamp()
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                "SELECT execution_id FROM p0_execution WHERE status IN "
                "('DISPATCHING', 'CAMPAIGN_CREATED', 'SUSPENDED_CONFIRMED', "
                "'OBJECT_GRAPH_CREATED', 'RECONCILIATION_REQUIRED', "
                "'MANUAL_RECONCILIATION') LIMIT 1"
            ).fetchone()
            if active is not None:
                raise P0ProductionError(
                    "P0_SINGLE_WRITER_BUSY",
                    "Предыдущее создание кампании ещё требует завершения или сверки.",
                )
            connection.execute(
                "INSERT INTO p0_execution(execution_id, status, created_at, "
                "updated_at, projection_json, result_json) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    execution_id,
                    "DISPATCHING",
                    now,
                    now,
                    self._serialize(projection),
                    self._serialize({"steps": []}),
                ),
            )
            connection.commit()
        return execution_id

    def record_execution(
        self,
        execution_id: str,
        *,
        status: str,
        result: Mapping[str, Any],
    ) -> None:
        with self._lock, closing(self._connect()) as connection:
            changed = connection.execute(
                "UPDATE p0_execution SET status = ?, updated_at = ?, result_json = ? "
                "WHERE execution_id = ?",
                (status, self._timestamp(), self._serialize(result), execution_id),
            ).rowcount
            connection.commit()
        if changed != 1:
            raise P0ProductionError(
                "P0_EXECUTION_MISSING",
                "Журнал создания кампании не найден.",
            )

    @staticmethod
    def _empty_value() -> dict[str, Any]:
        return {
            "site_analysis": None,
            "business_model": None,
            "strategy": None,
            "draft": None,
            "campaign": None,
        }

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _serialize(value: Mapping[str, Any]) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()


class _SiteHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.headings: list[str] = []
        self.text: list[str] = []
        self.forms = 0
        self.links: list[str] = []
        self._capture_title = False
        self._capture_heading = False
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        if lowered == "title":
            self._capture_title = True
        if lowered in {"h1", "h2"}:
            self._capture_heading = True
        if lowered == "form":
            self.forms += 1
        if lowered == "a":
            values = {str(key).lower(): value for key, value in attrs}
            href = _clean_text(str(values.get("href") or ""), 2048)
            if href and len(self.links) < 500:
                self.links.append(href)
        if lowered == "meta":
            values = {str(key).lower(): value for key, value in attrs}
            name = (values.get("name") or values.get("property") or "").lower()
            if name in {"description", "og:description"} and values.get("content"):
                self.description = _clean_text(str(values["content"]), 1000)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "title":
            self._capture_title = False
        if lowered in {"h1", "h2"}:
            self._capture_heading = False
        if lowered in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        value = _clean_text(data, 2000)
        if not value:
            return
        if self._capture_title:
            self.title = _clean_text((self.title + " " + value).strip(), 500)
        if self._capture_heading and len(self.headings) < 20:
            self.headings.append(value)
        if len(" ".join(self.text)) < _MAX_TEXT:
            self.text.append(value)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        return None


class HttpsSiteReader:
    """Research a small first-party HTTPS site surface with SSRF protection."""

    def __init__(
        self,
        *,
        resolver: Callable[..., Any] = socket.getaddrinfo,
        opener: Any | None = None,
    ) -> None:
        self._resolver = resolver
        self._opener = opener or build_opener(_NoRedirect())

    def read(self, url: str) -> Mapping[str, Any]:
        entry_page, links = self._fetch_page(url)
        pages = [entry_page]
        failed_pages: list[str] = []
        entry_host = _site_host(str(entry_page["url"]))
        candidates = self._research_links(str(entry_page["url"]), links)
        attempted: set[str] = set()
        while candidates and len(pages) < _MAX_SITE_PAGES:
            candidate = candidates.pop(0)
            if candidate in attempted:
                continue
            attempted.add(candidate)
            try:
                page, page_links = self._fetch_page(candidate)
            except P0ProductionError:
                failed_pages.append(candidate)
                continue
            page_host = _site_host(str(page["url"]))
            if not _is_first_party_host(entry_host, page_host):
                continue
            if any(item["url"] == page["url"] for item in pages):
                continue
            pages.append(page)
            discovered = self._research_links(str(page["url"]), page_links)
            candidates = [item for item in discovered if item not in attempted] + candidates

        combined_text = _clean_text(
            " ".join(str(page.get("text_excerpt", "")) for page in pages),
            _MAX_TEXT,
        )
        result = copy.deepcopy(entry_page)
        result.update(
            {
                "forms_detected": sum(int(page.get("forms_detected", 0)) for page in pages),
                "text_excerpt": combined_text[:8000],
                "pages": pages,
                "research": {
                    "pages_analyzed": len(pages),
                    "links_discovered": len(links),
                    "failed_pages": failed_pages[:5],
                    "scope": "FIRST_PARTY_PUBLIC_HTTPS",
                },
            }
        )
        return result

    def _fetch_page(self, url: str) -> tuple[dict[str, Any], list[str]]:
        current = _validated_public_https_url(url, self._resolver)
        for redirect_index in range(_MAX_REDIRECTS + 1):
            request = Request(
                current,
                headers={
                    "User-Agent": "MOX-ADV-P0/1.0",
                    "Accept": "text/html,application/xhtml+xml",
                },
                method="GET",
            )
            try:
                response = self._opener.open(request, timeout=8)
            except Exception as error:
                code = getattr(error, "code", None)
                headers = getattr(error, "headers", None)
                location = headers.get("Location") if headers is not None else None
                if code in {301, 302, 303, 307, 308} and location:
                    if redirect_index >= _MAX_REDIRECTS:
                        raise P0ProductionError(
                            "SITE_REDIRECT_LIMIT",
                            "Сайт перенаправляет запрос слишком много раз.",
                        ) from error
                    current = _validated_public_https_url(
                        urljoin(current, str(location)),
                        self._resolver,
                    )
                    continue
                raise P0ProductionError(
                    "SITE_READ_FAILED",
                    "Не удалось безопасно прочитать страницу сайта.",
                ) from error
            try:
                content_type = str(response.headers.get("Content-Type", ""))
                if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                    raise P0ProductionError(
                        "SITE_CONTENT_UNSUPPORTED",
                        "Страница сайта не вернула HTML.",
                    )
                raw = response.read(_MAX_SITE_BYTES + 1)
                final_url = str(response.geturl())
            finally:
                response.close()
            if len(raw) > _MAX_SITE_BYTES:
                raise P0ProductionError(
                    "SITE_TOO_LARGE",
                    "HTML страницы превышает безопасный размер анализа.",
                )
            final_url = _validated_public_https_url(final_url, self._resolver)
            encoding = "utf-8"
            match = re.search(
                r"charset=([A-Za-z0-9._-]+)",
                content_type,
                re.IGNORECASE,
            )
            if match:
                encoding = match.group(1)
            try:
                document = raw.decode(encoding, errors="replace")
            except LookupError:
                document = raw.decode("utf-8", errors="replace")
            parser = _SiteHTMLParser()
            parser.feed(document)
            body_text = _clean_text(" ".join(parser.text), _MAX_TEXT)
            if not parser.title and not parser.headings and not body_text:
                raise P0ProductionError(
                    "SITE_CONTENT_EMPTY",
                    "На странице не найден текст для анализа.",
                )
            return (
                {
                    "url": final_url,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "title": parser.title,
                    "description": parser.description,
                    "headings": parser.headings[:10],
                    "forms_detected": parser.forms,
                    "text_excerpt": body_text[:6000],
                },
                parser.links,
            )
        raise AssertionError("redirect loop must return or raise")

    @staticmethod
    def _research_links(base_url: str, links: list[str]) -> list[str]:
        base_host = _site_host(base_url)
        ranked: dict[str, int] = {}
        for href in links:
            lowered = href.casefold()
            if any(term in lowered for term in _SITE_RESEARCH_SKIP_TERMS):
                continue
            candidate = urljoin(base_url, href)
            parsed = urlparse(candidate)
            candidate_host = _site_host(candidate)
            if parsed.scheme != "https" or not _is_first_party_host(base_host, candidate_host):
                continue
            normalized = parsed._replace(query="", fragment="").geturl()
            if normalized.rstrip("/") == base_url.rstrip("/"):
                continue
            haystack = (parsed.path + " " + parsed.query).casefold()
            score = sum(3 for term in _SITE_RESEARCH_TERMS if term in haystack)
            if candidate_host != base_host:
                score += 6
            if score == 0:
                continue
            if "terms" in haystack and "particip" in haystack:
                score += 10
            if "услов" in haystack and "участ" in haystack:
                score += 10
            if "become" in haystack or "стать-участ" in haystack:
                score += 8
            if "list" in haystack or "participants" in haystack or "partner-country" in haystack:
                score -= 4
            score -= min(parsed.path.count("/"), 4)
            ranked[normalized] = max(score, ranked.get(normalized, -100))
        return [item[0] for item in sorted(ranked.items(), key=lambda item: (-item[1], item[0]))]


class YandexP0ContextReader:
    """Read the connected account, campaign catalog, and real performance facts."""

    def __init__(
        self,
        reader: YandexProductionReader,
        policy: Mapping[str, Any],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.reader = reader
        self.policy = policy
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._catalog_names: list[str] = []

    def read(self) -> Mapping[str, Any]:
        readiness = self.reader.readiness(self.policy)
        catalog_readiness = self.reader.campaign_catalog_readiness(self.policy)
        context: dict[str, Any] = {
            "environment": "PRODUCTION",
            "test_scenario": False,
            "direct": {
                "ready": bool(catalog_readiness["ready"]),
                "access": "REAL_API_READ",
                "blockers": list(catalog_readiness["blockers"]),
            },
            "metrika": {
                "ready": bool(readiness["ready"]),
                "access": "REAL_API_READ",
                "blockers": list(readiness["blockers"]),
            },
            "campaign_catalog": None,
            "performance": None,
        }
        if catalog_readiness["ready"]:
            catalog = self.reader.list_campaigns(policy=self.policy)
            active = [
                item
                for item in catalog["items"]
                if item["state"] in {"ON", "SUSPENDED", "OFF"}
                and item["status"] != "ARCHIVED"
            ]
            self._catalog_names = [str(item["name"]) for item in catalog["items"]]
            context["direct"].update(
                {
                    "account": catalog["account"],
                    "fetched_at": catalog["fetched_at"],
                    "campaigns_total": catalog["total"],
                    "active_campaigns": len(active),
                }
            )
            context["campaign_catalog"] = {
                "total": catalog["total"],
                "active": [
                    {
                        "campaign_id": item["campaign_id"],
                        "name": item["name"],
                        "state": item["state"],
                        "status": item["status"],
                    }
                    for item in active[:20]
                ],
            }
        if readiness["ready"]:
            snapshot = self.reader.collect_snapshot(
                policy=self.policy,
                observation_id="p0-context-" + uuid.uuid4().hex,
                generated_at=self.clock(),
            ).as_dict()
            context["metrika"].update(
                {
                    "counter_connected": True,
                    "goal_connected": True,
                    "fetched_at": snapshot["generated_at"],
                }
            )
            context["performance"] = {
                "period_start": snapshot["period_start"],
                "period_end": snapshot["period_end"],
                "campaign_state": snapshot["campaign"]["state"],
                "display_metrics": snapshot["display_metrics"],
                "data_quality_gaps": snapshot["data_quality_gaps"],
                "financial_recommendations_allowed": snapshot[
                    "financial_recommendations_allowed"
                ],
            }
        return context

    def duplicate_campaigns(self, name: str) -> list[str]:
        if not self._catalog_names:
            catalog = self.reader.list_campaigns(policy=self.policy)
            self._catalog_names = [str(item["name"]) for item in catalog["items"]]
        expected = _name_tokens(name)
        if not expected:
            return []
        candidates: list[str] = []
        for candidate in self._catalog_names:
            actual = _name_tokens(candidate)
            if not actual:
                continue
            overlap = len(expected & actual) / max(1, len(expected | actual))
            contained = expected <= actual or actual <= expected
            if overlap >= 0.5 or (contained and len(expected & actual) >= 2):
                candidates.append(candidate)
        return candidates[:5]


class UnavailableP0CampaignCreator:
    """Fail-closed creator used until a guarded production adapter is wired."""

    def __init__(self, blockers: list[str] | None = None) -> None:
        self.blockers = blockers or ["Production Direct adapter не настроен."]

    def readiness(self) -> Mapping[str, Any]:
        return {"ready": False, "blockers": list(self.blockers)}

    def create(self, projection: Mapping[str, Any]) -> Mapping[str, Any]:
        raise P0ProductionError(
            "P0_WRITE_NOT_READY",
            "; ".join(self.blockers),
        )


class MacOSKeychainCredential:
    """Resolve one secret without exposing it to argv, logs, or artifacts."""

    def __init__(self, service: str = "MOX_ADV_DIRECT_PILOT_WRITE") -> None:
        self.service = service

    def exists(self) -> bool:
        if sys.platform != "darwin":
            return False
        result = subprocess.run(
            ["security", "find-generic-password", "-s", self.service],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0

    def get(self) -> str:
        if sys.platform != "darwin":
            raise P0ProductionError(
                "P0_WRITE_CREDENTIAL_MISSING",
                "Write credential доступен только из macOS Keychain.",
            )
        result = subprocess.run(
            ["security", "find-generic-password", "-s", self.service, "-w"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        try:
            secret = result.stdout.decode("utf-8").strip()
        finally:
            result.stdout = b""
        if result.returncode != 0 or not secret:
            raise P0ProductionError(
                "P0_WRITE_CREDENTIAL_MISSING",
                "Credential DIRECT_PILOT_WRITE не найден в macOS Keychain.",
            )
        return secret


class YandexDirectP0CampaignCreator:
    """Guarded v501 adapter for one suspended Search campaign projection."""

    def __init__(
        self,
        *,
        policy: Mapping[str, Any],
        direct_account: str,
        store: P0ProductionStore,
        credential: MacOSKeychainCredential | None = None,
        http_client: HttpClient | None = None,
    ) -> None:
        self.policy = policy
        self.direct_account = direct_account
        self.store = store
        self.credential = credential or MacOSKeychainCredential()
        self.http = http_client or UrllibHttpClient()
        self.guard = HttpEgressGuard(policy)

    def readiness(self) -> Mapping[str, Any]:
        pilot = self.policy.get("bindings", {}).get("pilot", {})
        record = self.policy.get("record", {})
        checks = [
            {
                "id": "production_write_authorized",
                "ready": record.get("production_write_authorized") is True,
                "label": "Production write явно разрешён политикой",
            },
            {
                "id": "direct_account_bound",
                "ready": pilot.get("direct_account") == self.direct_account,
                "label": "Pilot привязан к текущему аккаунту Директа",
            },
            {
                "id": "single_writer_bound",
                "ready": bool(pilot.get("single_writer")),
                "label": "Single writer зафиксирован",
            },
            {
                "id": "write_credential",
                "ready": self.credential.exists(),
                "label": "Credential DIRECT_PILOT_WRITE хранится в Keychain",
            },
        ]
        blockers = [item["label"] for item in checks if not item["ready"]]
        return {"ready": not blockers, "checks": checks, "blockers": blockers}

    def create(self, projection: Mapping[str, Any]) -> Mapping[str, Any]:
        readiness = self.readiness()
        if not readiness["ready"]:
            raise P0ProductionError(
                "P0_WRITE_NOT_READY",
                "; ".join(readiness["blockers"]),
            )
        execution_id = self.store.begin_execution(projection)
        result: dict[str, Any] = {"execution_id": execution_id, "steps": []}
        campaign_id: str | None = None
        try:
            campaign_id = self._add_id(
                "Campaigns",
                "add",
                {"Campaigns": [projection["direct"]["campaign"]]},
                "AddResults",
            )
            result["campaign_id"] = campaign_id
            result["steps"].append("CAMPAIGN_CREATED")
            self.store.record_execution(execution_id, status="CAMPAIGN_CREATED", result=result)

            self._action(
                "Campaigns",
                "suspend",
                {"SelectionCriteria": {"Ids": [int(campaign_id)]}},
                "SuspendResults",
            )
            campaign = self._get_campaign(campaign_id)
            if campaign.get("State") != "SUSPENDED":
                raise P0ProductionError(
                    "P0_SUSPEND_NOT_CONFIRMED",
                    "Директ не подтвердил остановленное состояние кампании.",
                )
            result["steps"].append("SUSPENDED_CONFIRMED")
            self.store.record_execution(execution_id, status="SUSPENDED_CONFIRMED", result=result)

            group_payload = copy.deepcopy(dict(projection["direct"]["ad_group"]))
            group_payload["CampaignId"] = int(campaign_id)
            group_id = self._add_id(
                "AdGroups", "add", {"AdGroups": [group_payload]}, "AddResults"
            )
            keyword_payload = copy.deepcopy(dict(projection["direct"]["keyword"]))
            keyword_payload["AdGroupId"] = int(group_id)
            keyword_id = self._add_id(
                "Keywords", "add", {"Keywords": [keyword_payload]}, "AddResults"
            )
            ad_payload = copy.deepcopy(dict(projection["direct"]["ad"]))
            ad_payload["AdGroupId"] = int(group_id)
            ad_id = self._add_id("Ads", "add", {"Ads": [ad_payload]}, "AddResults")
            result.update(
                {
                    "ad_group_id": group_id,
                    "keyword_id": keyword_id,
                    "ad_id": ad_id,
                }
            )
            result["steps"].append("OBJECT_GRAPH_CREATED")
            self.store.record_execution(execution_id, status="OBJECT_GRAPH_CREATED", result=result)

            self._action(
                "Ads",
                "moderate",
                {"SelectionCriteria": {"Ids": [int(ad_id)]}},
                "ModerateResults",
            )
            ad = self._get_ad(ad_id)
            campaign = self._get_campaign(campaign_id)
            if campaign.get("State") != "SUSPENDED":
                raise P0ProductionError(
                    "P0_SUSPEND_LOST",
                    "Остановленное состояние кампании потеряно после модерации.",
                )
            moderation = str(ad.get("Status", "UNKNOWN"))
            result.update(
                {
                    "campaign_state": "SUSPENDED",
                    "moderation_status": moderation,
                    "spend_started": False,
                }
            )
            result["steps"].append("MODERATION_SUBMITTED")
            final_status = (
                "READY_TO_LAUNCH"
                if moderation == "ACCEPTED"
                else "REJECTED_NEEDS_EDIT"
                if moderation == "REJECTED"
                else "MODERATION_PENDING"
            )
            self.store.record_execution(execution_id, status=final_status, result=result)
            result["status"] = final_status
            return result
        except P0ProductionError:
            result["status"] = (
                "RECONCILIATION_REQUIRED" if campaign_id is None else "MANUAL_RECONCILIATION"
            )
            self.store.record_execution(
                execution_id,
                status=str(result["status"]),
                result=result,
            )
            raise
        except Exception as error:
            result["status"] = (
                "RECONCILIATION_REQUIRED" if campaign_id is None else "MANUAL_RECONCILIATION"
            )
            self.store.record_execution(
                execution_id,
                status=str(result["status"]),
                result=result,
            )
            raise P0ProductionError(
                "P0_DIRECT_WRITE_FAILED",
                "Директ не завершил безопасное создание. Требуется сверка журнала.",
            ) from error

    def _add_id(
        self,
        service: str,
        operation: str,
        params: Mapping[str, Any],
        result_key: str,
    ) -> str:
        result = self._call(service, operation, params)
        rows = result.get(result_key)
        if not isinstance(rows, list) or len(rows) != 1:
            raise P0ProductionError(
                "P0_DIRECT_RESPONSE_INVALID",
                f"{service}.{operation} вернул неожиданный результат.",
            )
        row = rows[0]
        if not isinstance(row, Mapping) or row.get("Errors") or not row.get("Id"):
            raise P0ProductionError(
                "P0_DIRECT_ITEM_FAILED",
                f"{service}.{operation} отклонил объект.",
            )
        return str(row["Id"])

    def _action(
        self,
        service: str,
        operation: str,
        params: Mapping[str, Any],
        result_key: str,
    ) -> None:
        result = self._call(service, operation, params)
        rows = result.get(result_key)
        if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("Errors"):
            raise P0ProductionError(
                "P0_DIRECT_ACTION_FAILED",
                f"{service}.{operation} не подтверждён.",
            )

    def _get_campaign(self, campaign_id: str) -> Mapping[str, Any]:
        result = self._call(
            "Campaigns",
            "get",
            {
                "SelectionCriteria": {"Ids": [int(campaign_id)]},
                "FieldNames": ["Id", "Name", "Type", "Status", "State"],
                "UnifiedCampaignFieldNames": ["BiddingStrategy"],
            },
        )
        rows = result.get("Campaigns")
        if not isinstance(rows, list) or len(rows) != 1:
            raise P0ProductionError(
                "P0_DIRECT_READBACK_FAILED",
                "Campaigns.get не подтвердил созданную кампанию.",
            )
        return rows[0]

    def _get_ad(self, ad_id: str) -> Mapping[str, Any]:
        result = self._call(
            "Ads",
            "get",
            {
                "SelectionCriteria": {"Ids": [int(ad_id)]},
                "FieldNames": [
                    "Id",
                    "CampaignId",
                    "AdGroupId",
                    "Type",
                    "Status",
                    "State",
                    "StatusClarification",
                ],
                "TextAdFieldNames": ["Title", "Text", "Href", "Mobile"],
            },
        )
        rows = result.get("Ads")
        if not isinstance(rows, list) or len(rows) != 1:
            raise P0ProductionError(
                "P0_DIRECT_READBACK_FAILED",
                "Ads.get не подтвердил созданное объявление.",
            )
        return rows[0]

    def _call(
        self,
        service: str,
        operation: str,
        params: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        path = "/json/v501/" + service.lower()
        url = "https://api.direct.yandex.com" + path
        self.guard.authorize(
            "POST",
            url,
            version="v501",
            service=service,
            operation=operation,
            authority=EgressAuthority(
                credential_profile=CredentialProfile.DIRECT_PILOT_WRITE,
                trusted_target=self.direct_account,
            ),
            pilot_armed=True,
        )
        response = self.http.perform(
            method="POST",
            url=url,
            headers={
                "Authorization": "Bearer " + self.credential.get(),
                "Client-Login": self.direct_account,
                "Accept": "application/json",
                "Accept-Language": "ru",
                "Content-Type": "application/json; charset=utf-8",
            },
            body=json.dumps(
                {"method": operation, "params": params},
                separators=(",", ":"),
            ).encode("utf-8"),
            timeout_seconds=30,
        )
        if response.status != 200:
            raise P0ProductionError(
                "P0_DIRECT_HTTP_FAILED",
                f"Яндекс Директ вернул HTTP {response.status}.",
            )
        try:
            payload = json.loads(response.body.decode("utf-8"))
            if not isinstance(payload, Mapping) or payload.get("error"):
                raise ValueError
            result = payload["result"]
            if not isinstance(result, Mapping):
                raise TypeError
            return result
        except (KeyError, TypeError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            raise P0ProductionError(
                "P0_DIRECT_RESPONSE_INVALID",
                "Ответ Яндекс Директа не соответствует P0-контракту.",
            ) from error


class EvidenceBusinessResearcher:
    """Infer a reviewable business model from crawled first-party evidence."""

    _AUDIENCE_TERMS = (
        "для производител",
        "для компан",
        "для бизнес",
        "производител",
        "байер",
        "покупател",
        "руководител",
        "предпринимател",
        "профессионал",
        "участник",
        "decision-maker",
        "manufacturer",
        "buyer",
        "companies",
        "business",
        "professional",
        "participant",
        "customer",
    )
    _AUDIENCE_STRONG_TERMS = (
        "руководител",
        "лидер",
        "заказчик",
        "инвестор",
        "покупател",
        "байер",
        "decision-maker",
        "manufacturer",
        "buyer",
        "investor",
    )
    _VALUE_TERMS = (
        "найдите",
        "получите",
        "помога",
        "возможност",
        "эконом",
        "увелич",
        "привлеч",
        "объедин",
        "доступ",
        "выход на",
        "новых покупател",
        "деловых партнер",
        "find new",
        "opportunit",
        "access to",
        "increase",
        "save",
        "connect",
    )
    _RESULT_TERMS = (
        "заполните короткую форму",
        "заполните форму",
        "оставьте заявку",
        "отправьте заявку",
        "менеджер свяж",
        "стать участник",
        "забронировать",
        "получить консультац",
        "зарегистрир",
        "become a participant",
        "fill out the form",
        "submit an application",
        "contact you",
        "book",
        "register",
    )
    _RESULT_STRONG_TERMS = (
        "заполните короткую форму",
        "оставьте заявку",
        "отправьте заявку",
        "менеджер свяж",
        "стать участник",
        "become a participant",
        "fill out the form",
        "submit an application",
        "contact you",
    )

    def research(
        self,
        site: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        pages = self._pages(site)
        evidence = self._evidence(pages)

        product_quote = self._product_quote(pages)
        audience_quote = self._best_audience_quote(evidence)
        value_quote = self._best_quote(evidence, self._VALUE_TERMS)
        result_quote = self._best_result_quote(evidence)

        product = _clean_text(product_quote["text"] if product_quote else "", 500)
        audience = self._audience_value(audience_quote)
        value = self._value_value(
            value_quote["text"] if value_quote else str(site.get("description", ""))
        )
        qualified_result = self._qualified_result(result_quote, pages)
        exclusions, exclusion_quote = self._exclusions(evidence, qualified_result)

        facts = {
            "product": (product, product_quote, "HIGH" if product_quote else "LOW"),
            "audience": (audience, audience_quote, "MEDIUM" if audience_quote else "LOW"),
            "value": (value, value_quote, "MEDIUM" if value else "LOW"),
            "qualified_result": (
                qualified_result,
                result_quote,
                "HIGH" if result_quote and any(int(page.get("forms_detected", 0)) for page in pages) else "MEDIUM" if qualified_result else "LOW",
            ),
            "exclusions": (
                exclusions,
                exclusion_quote,
                "MEDIUM" if exclusions else "LOW",
            ),
        }
        questions = {
            "product": "Какое предложение нужно рекламировать в первом P0?",
            "audience": "Кто фактически принимает решение о покупке?",
            "value": "Какая подтверждённая ценность важнее всего покупателю?",
            "qualified_result": "Какой фактический результат считается квалифицированным?",
            "exclusions": "Какие обращения и аудитории нужно исключить?",
        }
        missing_questions = [questions[name] for name, (answer, _, _) in facts.items() if not answer]
        assumptions = [
            f"{name}: вывод агента требует подтверждения владельца"
            for name, (answer, _, confidence) in facts.items()
            if answer and confidence == "MEDIUM"
        ]
        sources = ["PUBLIC_FIRST_PARTY_SITE"]
        direct = context.get("direct")
        metrika = context.get("metrika")
        if isinstance(direct, Mapping) and direct.get("ready") is True:
            sources.append("DIRECT_REAL_ACCOUNT")
        if isinstance(metrika, Mapping) and metrika.get("ready") is True:
            sources.append("METRIKA_REAL_COUNTER")

        return {
            "product": product,
            "audience": audience,
            "value": value,
            "qualified_result": qualified_result,
            "exclusions": exclusions,
            "source": "REAL_SITE_AND_CONNECTED_DATA_RESEARCH",
            "assumptions": assumptions,
            "missing_questions": missing_questions,
            "research": {
                "agent": "EVIDENCE_FIRST_RESEARCH_V1",
                "pages_analyzed": len(pages),
                "sources": sources,
                "completed_fields": [name for name, (answer, _, _) in facts.items() if answer],
            },
            "field_evidence": {
                name: self._field_evidence(reference, confidence)
                for name, (_, reference, confidence) in facts.items()
            },
        }

    @staticmethod
    def _pages(site: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        raw = site.get("pages")
        if isinstance(raw, list):
            pages = [item for item in raw if isinstance(item, Mapping)]
            if pages:
                return pages
        return [site]

    @staticmethod
    def _evidence(pages: list[Mapping[str, Any]]) -> list[dict[str, str]]:
        evidence: list[dict[str, str]] = []
        seen: set[str] = set()
        for page in pages:
            url = str(page.get("url", ""))
            values = [
                str(page.get("description", "")),
                *[str(item) for item in page.get("headings", []) if isinstance(item, str)],
            ]
            body = str(page.get("text_excerpt", ""))
            values.extend(re.split(r"(?<=[.!?])\s+|\s*[|•]\s*", body))
            for value in values:
                quote = _clean_text(value, 1000)
                key = quote.casefold()
                if len(quote) < 12 or key in seen:
                    continue
                seen.add(key)
                evidence.append({"text": quote, "url": url})
        return evidence

    @staticmethod
    def _product_quote(pages: list[Mapping[str, Any]]) -> dict[str, str] | None:
        first = pages[0]
        title = _clean_text(str(first.get("title", "")), 500)
        if title:
            for separator in (" | ", " — ", " – ", " - "):
                if separator in title:
                    title = title.split(separator, 1)[0].strip()
                    break
            if title:
                return {"text": title, "url": str(first.get("url", ""))}
        headings = first.get("headings")
        if isinstance(headings, list) and headings:
            return {
                "text": _clean_text(str(headings[0]), 500),
                "url": str(first.get("url", "")),
            }
        return None

    @classmethod
    def _best_audience_quote(
        cls,
        evidence: list[dict[str, str]],
    ) -> dict[str, str] | None:
        ranked: list[tuple[int, int, dict[str, str]]] = []
        for item in evidence:
            lowered = item["text"].casefold()
            score = sum(1 for term in cls._AUDIENCE_TERMS if term in lowered)
            score += 4 * sum(
                1 for term in cls._AUDIENCE_STRONG_TERMS if term in lowered
            )
            if lowered.startswith(("список ", "регистрация ", "list of ")):
                score -= 4
            if len(item["text"]) < 35 or len(item["text"]) > 700:
                score -= 2
            if score > 0:
                ranked.append((score, -len(item["text"]), item))
        return max(ranked, default=(0, 0, None), key=lambda item: (item[0], item[1]))[2]

    @classmethod
    def _best_result_quote(
        cls,
        evidence: list[dict[str, str]],
    ) -> dict[str, str] | None:
        ranked: list[tuple[int, int, dict[str, str]]] = []
        for item in evidence:
            lowered = item["text"].casefold()
            score = sum(1 for term in cls._RESULT_TERMS if term in lowered)
            score += 5 * sum(
                1 for term in cls._RESULT_STRONG_TERMS if term in lowered
            )
            if any(term in lowered for term in ("посетител", "visitor", "индивидуальн", "делегат", "билет")):
                score -= 5
            if len(item["text"]) < 30 or len(item["text"]) > 800:
                score -= 2
            if score > 0:
                ranked.append((score, -len(item["text"]), item))
        return max(ranked, default=(0, 0, None), key=lambda item: (item[0], item[1]))[2]

    @staticmethod
    def _best_quote(
        evidence: list[dict[str, str]],
        terms: tuple[str, ...],
    ) -> dict[str, str] | None:
        ranked: list[tuple[int, int, dict[str, str]]] = []
        for item in evidence:
            lowered = item["text"].casefold()
            score = sum(1 for term in terms if term in lowered)
            if score:
                ranked.append((score, -len(item["text"]), item))
        return max(ranked, default=(0, 0, None), key=lambda item: (item[0], item[1]))[2]

    @staticmethod
    def _audience_value(quote: dict[str, str] | None) -> str:
        if not quote:
            return ""
        text = quote["text"]
        match = re.search(
            r"(?:среди участников[^–—:]*[–—:]|объединя(?:ет|ющий|ющее)|including)\s*(.+)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            text = match.group(1)
        return _clean_text(text, 1000)

    @staticmethod
    def _value_value(value: str) -> str:
        text = _clean_text(value, 1000)
        words = text.split()
        if len(words) >= 4 and words[0:2] == words[2:4]:
            text = " ".join(words[2:])
        elif len(words) >= 2 and words[0].casefold() == words[1].casefold():
            text = " ".join(words[1:])
        return _clean_text(text, 1000)

    @classmethod
    def _qualified_result(
        cls,
        quote: dict[str, str] | None,
        pages: list[Mapping[str, Any]],
    ) -> str:
        if quote:
            lowered = quote["text"].casefold()
            if "менеджер" in lowered and "форм" in lowered:
                return "Отправленная форма с контактами, после которой менеджер связывается для уточнения деталей"
            if "участ" in lowered or "participant" in lowered:
                return "Отправленная заявка на участие через форму сайта"
            if "регистра" in lowered or "register" in lowered:
                return "Завершённая регистрация на сайте"
            if "консультац" in lowered or "contact you" in lowered:
                return "Отправленная заявка, после которой представитель связывается с клиентом"
            return "Выполненное целевое действие на сайте: " + _clean_text(quote["text"], 700)
        if any(int(page.get("forms_detected", 0)) for page in pages):
            return "Отправленная форма с контактными данными на сайте"
        return ""

    @staticmethod
    def _exclusions(
        evidence: list[dict[str, str]],
        qualified_result: str,
    ) -> tuple[str, dict[str, str] | None]:
        markers = {
            "посетител": "посетители без намерения оставить коммерческую заявку",
            "visitor": "посетители без намерения оставить коммерческую заявку",
            "вакан": "соискатели и запросы о работе",
            "career": "соискатели и запросы о работе",
            "пресс": "СМИ без коммерческого запроса",
            "media": "СМИ без коммерческого запроса",
            "бесплат": "запросы только на бесплатные материалы или посещение",
            "free ticket": "запросы только на бесплатные материалы или посещение",
        }
        values: list[str] = []
        reference: dict[str, str] | None = None
        for item in evidence:
            lowered = item["text"].casefold()
            for marker, label in markers.items():
                if marker in lowered and label not in values:
                    values.append(label)
                    reference = reference or item
        if not values and qualified_result:
            values.append("информационные обращения без намерения выполнить целевое действие")
        return _clean_text("; ".join(values), 1000), reference

    @staticmethod
    def _field_evidence(
        reference: dict[str, str] | None,
        confidence: str,
    ) -> dict[str, Any]:
        return {
            "confidence": confidence,
            "source_url": reference["url"] if reference else "",
            "quote": reference["text"] if reference else "",
        }


class P0ProductionModule:
    """Deep interface used by the Dashboard and tests."""

    def __init__(
        self,
        *,
        store: P0ProductionStore,
        context_reader: P0ContextReader,
        site_reader: P0SiteReader,
        creator: P0CampaignCreator,
        business_researcher: P0BusinessResearcher | None = None,
    ) -> None:
        self.store = store
        self.context_reader = context_reader
        self.site_reader = site_reader
        self.creator = creator
        self.business_researcher = business_researcher or EvidenceBusinessResearcher()

    def overview(self) -> dict[str, Any]:
        revision = self.store.load()
        try:
            context = dict(self.context_reader.read())
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            context = {
                "environment": "PRODUCTION",
                "test_scenario": False,
                "error": str(error),
                "direct": {"ready": False, "blockers": [str(error)]},
                "metrika": {"ready": False, "blockers": [str(error)]},
            }
        return {
            "module": "P0_PRODUCTION",
            "environment": "PRODUCTION",
            "test_scenario": False,
            "revision": revision.revision,
            "updated_at": revision.updated_at,
            "state": copy.deepcopy(dict(revision.value)),
            "context": context,
            "write_readiness": dict(self.creator.readiness()),
        }

    def apply(self, value: Mapping[str, Any]) -> dict[str, Any]:
        """Apply one typed Dashboard action through the module interface."""

        if not isinstance(value, Mapping):
            raise P0ProductionError("P0_ACTION_INVALID", "Действие P0 некорректно.")
        action = str(value.get("action", ""))
        revision = value.get("expected_revision")
        if isinstance(revision, bool) or not isinstance(revision, int):
            raise P0ProductionError(
                "P0_REVISION_REQUIRED",
                "Для изменения P0 нужна текущая ревизия.",
            )
        if action == "analyze_site":
            return self.analyze_site(
                url=str(value.get("url", "")),
                expected_revision=revision,
            )
        if action == "save_business_model":
            return self.save_business_model(
                _mapping(value.get("value"), "Модель бизнеса"),
                expected_revision=revision,
            )
        if action == "save_strategy":
            return self.save_strategy(
                _mapping(value.get("value"), "Campaign Strategy"),
                expected_revision=revision,
            )
        if action == "save_draft":
            return self.save_draft(
                _mapping(value.get("value"), "Campaign Draft"),
                expected_revision=revision,
            )
        if action == "confirm_distinct_campaign":
            return self.confirm_distinct_campaign(expected_revision=revision)
        if action == "confirm_creation":
            return self.confirm_creation(
                confirmation=str(value.get("confirmation", "")),
                expected_revision=revision,
            )
        if action == "reset":
            return self.reset(expected_revision=revision)
        raise P0ProductionError(
            "P0_ACTION_INVALID",
            "Действие P0 не поддерживается production-модулем.",
        )

    def analyze_site(self, *, url: str, expected_revision: int) -> dict[str, Any]:
        site = dict(self.site_reader.read(_bounded_text(url, "Сайт", 2048)))
        try:
            context = dict(self.context_reader.read())
        except (OSError, RuntimeError, TypeError, ValueError):
            context = {
                "environment": "PRODUCTION",
                "direct": {"ready": False},
                "metrika": {"ready": False},
            }
        model = dict(self.business_researcher.research(site, context))
        first = self.store.save_section(
            "site_analysis",
            site,
            expected_revision=expected_revision,
        )
        second = self.store.save_section(
            "business_model",
            model,
            expected_revision=first.revision,
        )
        return self._revision_payload(second)

    def save_business_model(
        self,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        normalized = _closed_text_mapping(
            value,
            {
                "product": 500,
                "audience": 1000,
                "value": 1000,
                "qualified_result": 1000,
                "exclusions": 1000,
            },
            "Модель бизнеса",
        )
        current = self.store.load()
        existing = current.value.get("business_model")
        research = dict(existing.get("research", {})) if isinstance(existing, Mapping) else {}
        if isinstance(existing, Mapping) and existing.get("assumptions"):
            research["initial_assumptions"] = list(existing["assumptions"])
        evidence = copy.deepcopy(dict(existing.get("field_evidence", {}))) if isinstance(existing, Mapping) else {}
        for name in normalized:
            item = dict(evidence.get(name, {})) if isinstance(evidence.get(name), Mapping) else {}
            item["owner_confirmed"] = True
            item["confidence"] = "OWNER_CONFIRMED"
            evidence[name] = item
        normalized.update(
            {
                "source": "REAL_SITE_RESEARCH_PLUS_OWNER_CONFIRMATION",
                "assumptions": [],
                "missing_questions": [],
                "research": research,
                "field_evidence": evidence,
            }
        )
        revision = self.store.save_section(
            "business_model", normalized, expected_revision=expected_revision
        )
        return self._revision_payload(revision)

    def save_strategy(
        self,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        expected = {
            "goal",
            "geography",
            "period_start",
            "period_end",
            "landing_page",
            "weekly_budget_rub",
            "target_cpa_rub",
            "message",
        }
        if set(value) != expected:
            raise P0ProductionError(
                "P0_STRATEGY_INVALID",
                "Campaign Strategy содержит неизвестные или отсутствующие поля.",
            )
        landing_page = _validated_public_https_url(str(value["landing_page"]), socket.getaddrinfo)
        period_start = _iso_date(value["period_start"], "Дата начала")
        period_end = _iso_date(value["period_end"], "Дата окончания")
        if period_end < period_start:
            raise P0ProductionError(
                "P0_STRATEGY_INVALID",
                "Дата окончания должна быть не раньше даты начала.",
            )
        geography = _bounded_text(value["geography"], "География", 200)
        if geography.casefold() not in _REGION_IDS:
            raise P0ProductionError(
                "P0_GEOGRAPHY_UNSUPPORTED",
                "Первый P0 поддерживает Россию, Москву или Санкт-Петербург.",
            )
        normalized = {
            "goal": _bounded_text(value["goal"], "Цель", 1000),
            "geography": geography,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "landing_page": landing_page,
            "weekly_budget_rub": _positive_int(value["weekly_budget_rub"], "Недельный бюджет", maximum=10_000_000),
            "target_cpa_rub": _positive_int(value["target_cpa_rub"], "Целевой CPA", maximum=10_000_000),
            "message": _bounded_text(value["message"], "Основное сообщение", 1000),
            "source": "OWNER_APPROVED_REAL_BUSINESS_INPUT",
        }
        revision = self.store.save_section(
            "strategy", normalized, expected_revision=expected_revision
        )
        return self._revision_payload(revision)

    def save_draft(
        self,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        revision = self.store.load()
        if revision.revision != expected_revision:
            raise P0ProductionError(
                "P0_REVISION_CONFLICT",
                "P0 изменился в другой вкладке. Обновите страницу.",
            )
        strategy = revision.value.get("strategy")
        model = revision.value.get("business_model")
        if not isinstance(strategy, Mapping) or not isinstance(model, Mapping):
            raise P0ProductionError(
                "P0_PREREQUISITE_MISSING",
                "Сначала подтвердите модель бизнеса и Campaign Strategy.",
            )
        expected = {
            "campaign_name",
            "group_name",
            "keyword",
            "negative_keywords",
            "ad_title",
            "ad_text",
        }
        if set(value) != expected or not isinstance(value["negative_keywords"], list):
            raise P0ProductionError(
                "P0_DRAFT_INVALID",
                "Campaign Draft содержит неизвестные или отсутствующие поля.",
            )
        negative_keywords = [
            _bounded_text(item, "Минус-фраза", 100)
            for item in value["negative_keywords"]
        ]
        if not negative_keywords or len(negative_keywords) > 50:
            raise P0ProductionError(
                "P0_DRAFT_INVALID",
                "Укажите от одной до 50 минус-фраз.",
            )
        normalized = {
            "campaign_name": _bounded_text(value["campaign_name"], "Название кампании", 255),
            "group_name": _bounded_text(value["group_name"], "Название группы", 255),
            "keyword": _bounded_text(value["keyword"], "Ключевая фраза", 4096),
            "negative_keywords": negative_keywords,
            "ad_title": _bounded_text(value["ad_title"], "Заголовок объявления", 56),
            "ad_text": _bounded_text(value["ad_text"], "Текст объявления", 81),
            "source": "OWNER_REVIEWED_PUBLISH_PROJECTION",
        }
        duplicate_reader = getattr(self.context_reader, "duplicate_campaigns", None)
        duplicates = (
            list(duplicate_reader(normalized["campaign_name"]))
            if duplicate_reader is not None
            else []
        )
        normalized["duplicate_candidates"] = duplicates
        normalized["duplicate_override"] = not duplicates
        projection = self._build_projection(model, strategy, normalized)
        normalized["publish_projection"] = projection
        saved = self.store.save_section(
            "draft", normalized, expected_revision=expected_revision
        )
        return self._revision_payload(saved)

    def confirm_distinct_campaign(self, *, expected_revision: int) -> dict[str, Any]:
        revision = self.store.load()
        if revision.revision != expected_revision:
            raise P0ProductionError(
                "P0_REVISION_CONFLICT",
                "P0 изменился в другой вкладке. Обновите страницу.",
            )
        draft = revision.value.get("draft")
        if not isinstance(draft, Mapping) or not draft.get("duplicate_candidates"):
            raise P0ProductionError(
                "P0_DUPLICATE_CONFIRMATION_INVALID",
                "Похожая кампания не найдена или Draft ещё не готов.",
            )
        updated = copy.deepcopy(dict(draft))
        updated["duplicate_override"] = True
        saved = self.store.save_section(
            "draft", updated, expected_revision=expected_revision
        )
        return self._revision_payload(saved)

    def confirm_creation(
        self,
        *,
        confirmation: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        if confirmation != "CREATE_SUSPENDED_CAMPAIGN":
            raise P0ProductionError(
                "P0_CONFIRMATION_REQUIRED",
                "Точное подтверждение создания остановленной кампании отсутствует.",
            )
        revision = self.store.load()
        if revision.revision != expected_revision:
            raise P0ProductionError(
                "P0_REVISION_CONFLICT",
                "P0 изменился в другой вкладке. Обновите страницу.",
            )
        draft = revision.value.get("draft")
        if not isinstance(draft, Mapping) or not isinstance(
            draft.get("publish_projection"), Mapping
        ):
            raise P0ProductionError(
                "P0_DRAFT_MISSING",
                "Campaign Draft не готов к созданию.",
            )
        if draft.get("duplicate_candidates") and draft.get("duplicate_override") is not True:
            raise P0ProductionError(
                "P0_DUPLICATE_CONFIRMATION_REQUIRED",
                "Найдена похожая кампания. Сначала подтвердите создание отдельной.",
            )
        result = dict(self.creator.create(draft["publish_projection"]))
        campaign = {
            "source": "YANDEX_DIRECT_API",
            "created_at": datetime.now(timezone.utc).isoformat(),
            **result,
        }
        saved = self.store.save_section(
            "campaign", campaign, expected_revision=expected_revision
        )
        return self._revision_payload(saved)

    def reset(self, *, expected_revision: int) -> dict[str, Any]:
        return self._revision_payload(
            self.store.reset(expected_revision=expected_revision)
        )

    @staticmethod
    def _build_projection(
        model: Mapping[str, Any],
        strategy: Mapping[str, Any],
        draft: Mapping[str, Any],
    ) -> dict[str, Any]:
        weekly = int(strategy["weekly_budget_rub"])
        bid_ceiling_rub = min(max(weekly // 100, 100), 3000)
        return {
            "schema_version": "p0-direct-projection-v1",
            "business": {
                "product": model["product"],
                "audience": model["audience"],
                "qualified_result": model["qualified_result"],
                "goal": strategy["goal"],
                "target_cpa_rub": strategy["target_cpa_rub"],
            },
            "safety": {
                "must_end_suspended": True,
                "resume_allowed": False,
                "network_serving": False,
            },
            "direct": {
                "campaign": {
                    "Name": draft["campaign_name"],
                    "StartDate": strategy["period_start"],
                    "EndDate": strategy["period_end"],
                    "UnifiedCampaign": {
                        "BiddingStrategy": {
                            "Search": {
                                "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
                                "WbMaximumClicks": {
                                    "WeeklySpendLimit": weekly * 1_000_000,
                                    "BidCeiling": bid_ceiling_rub * 1_000_000,
                                },
                            },
                            "Network": {"BiddingStrategyType": "SERVING_OFF"},
                        }
                    },
                },
                "ad_group": {
                    "Name": draft["group_name"],
                    "RegionIds": [_REGION_IDS[str(strategy["geography"]).casefold()]],
                    "NegativeKeywords": {"Items": list(draft["negative_keywords"])},
                    "UnifiedAdGroup": {"OfferRetargeting": "NO"},
                },
                "keyword": {"Keyword": draft["keyword"]},
                "ad": {
                    "TextAd": {
                        "Title": draft["ad_title"],
                        "Text": draft["ad_text"],
                        "Href": strategy["landing_page"],
                        "Mobile": "NO",
                    }
                },
            },
        }

    @staticmethod
    def _revision_payload(revision: P0Revision) -> dict[str, Any]:
        return {
            "revision": revision.revision,
            "updated_at": revision.updated_at,
            "state": copy.deepcopy(dict(revision.value)),
        }


def _validated_public_https_url(url: str, resolver: Callable[..., Any]) -> str:
    value = url.strip()
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as error:
        raise P0ProductionError("SITE_URL_INVALID", "Адрес сайта некорректен.") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise P0ProductionError(
            "SITE_URL_INVALID",
            "P0 принимает только публичный HTTPS-адрес без credentials и fragment.",
        )
    try:
        literal_address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal_address = None
    if literal_address is not None and not literal_address.is_global:
        raise P0ProductionError(
            "SITE_PRIVATE_ADDRESS_DENIED",
            "Локальные и частные адреса запрещены для анализа сайта.",
        )
    try:
        addresses = resolver(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except OSError as error:
        raise P0ProductionError(
            "SITE_DNS_FAILED",
            "Не удалось разрешить публичный адрес сайта.",
        ) from error
    if not addresses:
        raise P0ProductionError("SITE_DNS_FAILED", "Адрес сайта не найден.")
    for item in addresses:
        try:
            address = ipaddress.ip_address(item[4][0])
        except (IndexError, TypeError, ValueError) as error:
            raise P0ProductionError("SITE_DNS_FAILED", "DNS-ответ сайта некорректен.") from error
        proxy_synthetic = (
            isinstance(address, ipaddress.IPv4Address)
            and address in _PROXY_SYNTHETIC_NETWORK
            and literal_address is None
        )
        if not address.is_global and not proxy_synthetic:
            raise P0ProductionError(
                "SITE_PRIVATE_ADDRESS_DENIED",
                "Локальные и частные адреса запрещены для анализа сайта.",
            )
    normalized = parsed._replace(path=parsed.path or "/").geturl()
    return normalized


def _site_host(url: str) -> str:
    host = (urlparse(url).hostname or "").casefold().rstrip(".")
    return host.removeprefix("www.")


def _is_first_party_host(base_host: str, candidate_host: str) -> bool:
    return candidate_host == base_host or candidate_host.endswith("." + base_host)


def _clean_text(value: str, maximum: int) -> str:
    cleaned = html.unescape(re.sub(r"\s+", " ", value)).strip()
    return cleaned[:maximum]


def _bounded_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise P0ProductionError("P0_INPUT_INVALID", f"{label}: ожидается текст.")
    normalized = _clean_text(value, maximum + 1)
    if not normalized or len(normalized) > maximum:
        raise P0ProductionError(
            "P0_INPUT_INVALID",
            f"{label}: укажите от 1 до {maximum} символов.",
        )
    return normalized


def _name_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zа-яё0-9]+", value.casefold())
        if len(token) > 1 and token not in {"mox", "мох", "поиск", "рся", "new"}
    }


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise P0ProductionError("P0_INPUT_INVALID", f"{label}: ожидается объект.")
    return value


def _closed_text_mapping(
    value: Mapping[str, Any],
    fields: Mapping[str, int],
    label: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != set(fields):
        raise P0ProductionError(
            "P0_INPUT_INVALID",
            f"{label} содержит неизвестные или отсутствующие поля.",
        )
    return {
        name: _bounded_text(value[name], name, maximum)
        for name, maximum in fields.items()
    }


def _positive_int(value: Any, label: str, *, maximum: int) -> int:
    if isinstance(value, bool):
        raise P0ProductionError("P0_INPUT_INVALID", f"{label}: ожидается число.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise P0ProductionError("P0_INPUT_INVALID", f"{label}: ожидается число.") from error
    if parsed < 1 or parsed > maximum:
        raise P0ProductionError(
            "P0_INPUT_INVALID",
            f"{label}: допустимо значение от 1 до {maximum}.",
        )
    return parsed


def _iso_date(value: Any, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise P0ProductionError(
            "P0_INPUT_INVALID",
            f"{label}: используйте формат YYYY-MM-DD.",
        ) from error
