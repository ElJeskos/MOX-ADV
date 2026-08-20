"""Local-only HTTP server for the MOX-ADV operator UI."""

from __future__ import annotations

import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from mox_adv.control_state import ControlRejected
from mox_adv.p0_production import P0ProductionError
from mox_adv.ui_campaign import DashboardCampaignRejected
from mox_adv.ui_dashboard import DashboardApplication
from mox_adv.ui_service import UiRunRejected, UiRunService
from mox_adv.ui_workflows import DashboardWorkflowRejected

ASSET_ROOT = Path(__file__).with_name("ui")
_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/overview": ("index.html", "text/html; charset=utf-8"),
    "/strategy": ("index.html", "text/html; charset=utf-8"),
    "/cycle": ("index.html", "text/html; charset=utf-8"),
    "/autopilot": ("index.html", "text/html; charset=utf-8"),
    "/rules": ("index.html", "text/html; charset=utf-8"),
    "/history": ("index.html", "text/html; charset=utf-8"),
    "/campaign": ("index.html", "text/html; charset=utf-8"),
    "/workflows": ("index.html", "text/html; charset=utf-8"),
    "/control": ("index.html", "text/html; charset=utf-8"),
    "/prototype/mox-adv": ("prototype.html", "text/html; charset=utf-8"),
    "/assets/app.css": ("app.css", "text/css; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/assets/p0-app.js": ("p0-app.js", "text/javascript; charset=utf-8"),
    "/assets/prototype.css": ("prototype.css", "text/css; charset=utf-8"),
    "/assets/prototype.js": ("prototype.js", "text/javascript; charset=utf-8"),
}


class UiRequestHandler(BaseHTTPRequestHandler):
    """Serve a narrow local UI and JSON API."""

    server: UiHttpServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if path in _ASSETS:
            name, content_type = _ASSETS[path]
            self._send_bytes(
                HTTPStatus.OK,
                (ASSET_ROOT / name).read_bytes(),
                content_type,
            )
            return
        if path == "/favicon.ico":
            self._send_bytes(HTTPStatus.NO_CONTENT, b"", "image/x-icon")
            return
        if path == "/api/status":
            status = dict(self.server.service.status())
            status["public_demo"] = self.server.public_demo
            self._send_json(HTTPStatus.OK, status)
            return
        if path == "/api/test-automation":
            self._send_json(
                HTTPStatus.OK,
                self.server.service.automation(),
            )
            return
        if path == "/api/test-history":
            query = parse_qs(parsed_url.query)
            if "page" in query or "page_size" in query:
                try:
                    page = int(query.get("page", ["1"])[0])
                    page_size = int(query.get("page_size", ["10"])[0])
                    result = self.server.service.decision_history_page(
                        page=page,
                        page_size=page_size,
                    )
                except (IndexError, TypeError, ValueError, UiRunRejected) as error:
                    self._send_error(
                        HTTPStatus.BAD_REQUEST,
                        "INVALID_HISTORY_PAGE",
                        str(error) or "History page is invalid.",
                    )
                    return
                self._send_json(HTTPStatus.OK, result)
                return
            self._send_json(
                HTTPStatus.OK,
                {"items": self.server.service.decision_history()},
            )
            return
        if path.startswith("/api/test-history/") and path.endswith("/outcome"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                try:
                    outcome = self.server.service.decision_outcome(
                        unquote(parts[2])
                    )
                except UiRunRejected as error:
                    self._send_error(
                        HTTPStatus.NOT_FOUND,
                        error.reason_code,
                        str(error),
                    )
                    return
                self._send_json(HTTPStatus.OK, outcome)
                return
        if path == "/api/control-plane":
            self._send_json(
                HTTPStatus.OK,
                self.server.dashboard.control_overview(),
            )
            return
        if path == "/api/p0":
            try:
                result = self.server.dashboard.p0_overview()
            except P0ProductionError as error:
                self._send_error(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    error.reason_code,
                    str(error),
                )
                return
            self._send_json(HTTPStatus.OK, result)
            return
        if path == "/api/campaigns":
            self._send_json(
                HTTPStatus.OK,
                self.server.dashboard.campaign_catalog(),
            )
            return
        if path == "/api/yandex-direct/campaigns":
            try:
                catalog = self.server.service.production_campaign_catalog()
            except UiRunRejected as error:
                self._send_error(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    error.reason_code,
                    str(error),
                )
                return
            self._send_json(HTTPStatus.OK, catalog)
            return
        if path.startswith("/api/campaigns/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[3] == "goal":
                try:
                    result = self.server.dashboard.goal_lifecycle_overview(
                        unquote(parts[2])
                    )
                except DashboardCampaignRejected as error:
                    self._send_error(
                        HTTPStatus.NOT_FOUND,
                        error.reason_code,
                        str(error),
                    )
                    return
                self._send_json(HTTPStatus.OK, result)
                return
            if len(parts) == 4 and parts[3] == "launch":
                try:
                    result = self.server.dashboard.campaign_launch_overview(
                        unquote(parts[2])
                    )
                except DashboardCampaignRejected as error:
                    self._send_error(
                        HTTPStatus.NOT_FOUND,
                        error.reason_code,
                        str(error),
                    )
                    return
                self._send_json(HTTPStatus.OK, result)
                return
            if len(parts) == 3:
                self._send_json(
                    HTTPStatus.OK,
                    self.server.dashboard.campaign_overview(
                        unquote(parts[2])
                    ),
                )
                return
        if path == "/api/campaign":
            self._send_json(
                HTTPStatus.OK,
                self.server.dashboard.campaign_overview(),
            )
            return
        if path == "/api/evidence":
            self._send_json(
                HTTPStatus.OK,
                self.server.dashboard.evidence_overview(),
            )
            return
        if path.startswith("/api/evidence-runs/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                try:
                    artifact_path = self.server.dashboard.artifact_path(
                        parts[2],
                        parts[3],
                    )
                except (FileNotFoundError, ValueError):
                    self._send_error(
                        HTTPStatus.NOT_FOUND,
                        "ARTIFACT_NOT_FOUND",
                        "Evidence artifact is not available.",
                    )
                    return
                content_type = (
                    "application/json; charset=utf-8"
                    if artifact_path.suffix == ".json"
                    else (
                        "application/x-ndjson; charset=utf-8"
                        if artifact_path.suffix == ".jsonl"
                        else (
                            "text/html; charset=utf-8"
                            if artifact_path.suffix == ".html"
                            else "text/markdown; charset=utf-8"
                        )
                    )
                )
                self._send_bytes(
                    HTTPStatus.OK,
                    artifact_path.read_bytes(),
                    content_type,
                    {
                        "Content-Disposition": (
                            f'attachment; filename="{artifact_path.name}"'
                        )
                    },
                )
                return
        if path.startswith("/api/runs/"):
            parts = path.strip("/").split("/")
            try:
                if len(parts) == 3:
                    self._send_json(
                        HTTPStatus.OK,
                        self.server.service.load_report(parts[2]),
                    )
                    return
                if len(parts) == 4 and parts[3] == "report":
                    report_path = self.server.service.html_report_path(parts[2])
                    self._send_bytes(
                        HTTPStatus.OK,
                        report_path.read_bytes(),
                        "text/html; charset=utf-8",
                        {
                            "Content-Disposition": (
                                f'attachment; filename="{parts[2]}-report.html"'
                            )
                        },
                    )
                    return
            except UiRunRejected as error:
                self._send_error(
                    HTTPStatus.NOT_FOUND,
                    error.reason_code,
                    str(error),
                )
                return
        self._send_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Route not found.")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        campaign_select = (
            path.startswith("/api/campaigns/")
            and path.endswith("/select")
            and len(path.strip("/").split("/")) == 4
        )
        campaign_launch = (
            path.startswith("/api/campaigns/")
            and path.endswith("/launch")
            and len(path.strip("/").split("/")) == 4
        )
        campaign_goal_action = (
            path.startswith("/api/campaigns/")
            and len(path.strip("/").split("/")) == 5
            and path.strip("/").split("/")[3] == "goal"
            and path.strip("/").split("/")[4] in {"technical", "decision"}
        )
        if path not in {
            "/api/runs",
            "/api/runs/stream",
            "/api/control-plane/mode",
            "/api/control-plane/kill-switch",
            "/api/control-plane/mandates",
            "/api/control-plane/approvals",
            "/api/proposals/revise",
            "/api/p0",
            "/api/campaign",
            "/api/campaigns",
            "/api/workflows/campaign",
            "/api/workflows/goal",
            "/api/workflows/impact",
            "/api/evidence/run",
        } and not campaign_select and not campaign_launch and not (
            campaign_goal_action
        ):
            self._send_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Route not found.")
            return
        if not self._allow_json_mutation():
            return
        try:
            if path == "/api/runs/stream":
                self._stream_production_run(self._read_json())
                return
            if path == "/api/p0":
                result = self.server.dashboard.apply_p0_action(self._read_json())
                self._send_json(HTTPStatus.CREATED, result)
                return
            if path == "/api/runs":
                payload = self._read_json()
                mode = str(payload.get("mode", ""))
                if mode == "test":
                    report = self.server.service.run(
                        mode,
                        scenario=payload.get("scenario"),
                        rules=payload.get("rules"),
                        recommendation_rules=payload.get("recommendation_rules"),
                        operating_mode="APPROVAL_REQUIRED",
                    )
                else:
                    report = self.server.service.run(
                        mode,
                        operating_mode="RECOMMEND",
                    )
                self._send_json(HTTPStatus.CREATED, report)
                return
            if path == "/api/control-plane/mode":
                payload = self._read_json()
                result = self.server.dashboard.select_operating_mode(
                    str(payload.get("mode", ""))
                )
            elif path == "/api/control-plane/kill-switch":
                payload = self._read_json()
                action = str(payload.get("action", ""))
                scope = str(payload.get("scope", ""))
                if action == "engage":
                    result = self.server.dashboard.engage_kill_switch(scope)
                elif action == "release":
                    result = self.server.dashboard.release_kill_switch(
                        scope,
                        str(payload.get("confirmation", "")),
                    )
                else:
                    raise ValueError("KILL_SWITCH_ACTION_INVALID")
            elif path == "/api/control-plane/mandates":
                payload = self._read_json()
                action = str(payload.get("action", ""))
                if action == "issue":
                    result = self.server.dashboard.issue_test_mandate()
                elif action == "revoke":
                    result = self.server.dashboard.revoke_latest_mandate()
                else:
                    raise ValueError("MANDATE_ACTION_INVALID")
            elif path == "/api/control-plane/approvals":
                payload = self._read_json()
                action = str(payload.get("action", ""))
                if action == "grant_latest":
                    result = self.server.dashboard.grant_pending_proposal(
                        str(payload.get("run_id", ""))
                    )
                elif action == "revoke_latest":
                    result = self.server.dashboard.revoke_approval(
                        str(payload.get("approval_id", ""))
                    )
                elif action == "apply_latest":
                    result = self.server.dashboard.apply_approved_proposal(
                        str(payload.get("run_id", ""))
                    )
                else:
                    raise ValueError("APPROVAL_ACTION_INVALID")
            elif path == "/api/proposals/revise":
                payload = self._read_json()
                step = payload.get("relative_step_percent")
                if isinstance(step, bool) or not isinstance(step, int):
                    raise ValueError("PROPOSAL_REVISION_STEP_REQUIRED")
                result = self.server.dashboard.revise_pending_proposal(
                    str(payload.get("run_id", "")),
                    step,
                )
            elif path == "/api/campaign":
                payload = self._read_json()
                if payload.get("action") != "new":
                    raise ValueError("CAMPAIGN_ACTION_INVALID")
                revision = payload.get("expected_revision")
                if isinstance(revision, bool) or not isinstance(revision, int):
                    raise ValueError("CAMPAIGN_REVISION_REQUIRED")
                result = self.server.dashboard.create_campaign_draft(revision)
            elif path == "/api/campaigns":
                payload = self._read_json()
                revision = payload.get("expected_revision")
                if isinstance(revision, bool) or not isinstance(revision, int):
                    raise ValueError("CAMPAIGN_REVISION_REQUIRED")
                self.server.dashboard.create_campaign_draft(revision)
                result = self.server.dashboard.campaign_catalog()
            elif campaign_select:
                parts = path.strip("/").split("/")
                self._read_json()
                result = self.server.dashboard.select_campaign(
                    unquote(parts[2])
                )
            elif campaign_launch:
                parts = path.strip("/").split("/")
                payload = self._read_json()
                revision = payload.get("expected_revision")
                if isinstance(revision, bool) or not isinstance(revision, int):
                    raise ValueError("CAMPAIGN_REVISION_REQUIRED")
                result = self.server.dashboard.run_campaign_simulation(
                    unquote(parts[2]),
                    expected_revision=revision,
                )
            elif campaign_goal_action:
                parts = path.strip("/").split("/")
                payload = self._read_json()
                revision = payload.get("expected_revision")
                if isinstance(revision, bool) or not isinstance(revision, int):
                    raise ValueError("CAMPAIGN_REVISION_REQUIRED")
                draft_id = unquote(parts[2])
                if parts[4] == "technical":
                    result = (
                        self.server.dashboard.run_goal_technical_simulation(
                            draft_id,
                            expected_revision=revision,
                        )
                    )
                else:
                    result = (
                        self.server.dashboard.decide_pending_goal_simulation(
                            str(payload.get("semantic_decision", "")),
                            draft_id=draft_id,
                            expected_revision=revision,
                            run_id=str(payload.get("run_id", "")),
                        )
                    )
            elif path == "/api/workflows/campaign":
                payload = self._read_json()
                draft_id = payload.get("draft_id")
                if not isinstance(draft_id, str) or not draft_id.strip():
                    raise ValueError("CAMPAIGN_DRAFT_ID_REQUIRED")
                revision = payload.get("expected_revision")
                if isinstance(revision, bool) or not isinstance(revision, int):
                    raise ValueError("CAMPAIGN_REVISION_REQUIRED")
                result = self.server.dashboard.run_campaign_simulation(
                    draft_id,
                    expected_revision=revision,
                )
            elif path == "/api/workflows/goal":
                payload = self._read_json()
                action = str(payload.get("action", ""))
                draft_id = str(payload.get("draft_id", ""))
                revision = payload.get("expected_revision")
                if not draft_id:
                    raise ValueError("CAMPAIGN_DRAFT_ID_REQUIRED")
                if isinstance(revision, bool) or not isinstance(revision, int):
                    raise ValueError("CAMPAIGN_REVISION_REQUIRED")
                if action == "technical":
                    result = self.server.dashboard.run_goal_technical_simulation(
                        draft_id,
                        expected_revision=revision,
                    )
                elif action == "semantic_decision":
                    result = self.server.dashboard.decide_pending_goal_simulation(
                        str(payload.get("semantic_decision", "")),
                        draft_id=draft_id,
                        expected_revision=revision,
                        run_id=str(payload.get("run_id", "")),
                    )
                else:
                    raise ValueError("GOAL_WORKFLOW_ACTION_INVALID")
            elif path == "/api/workflows/impact":
                payload = self._read_json()
                source_run_id = payload.get("source_run_id")
                if source_run_id is not None and not isinstance(
                    source_run_id,
                    str,
                ):
                    raise ValueError("IMPACT_SOURCE_RUN_ID_INVALID")
                result = self.server.dashboard.run_impact_fixture(
                    str(payload.get("fixture", "")),
                    source_run_id=source_run_id,
                )
            else:
                result = self.server.dashboard.run_full_evidence()
            self._send_json(HTTPStatus.CREATED, result)
            return
        except P0ProductionError as error:
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                error.reason_code,
                str(error),
            )
            return
        except UiRunRejected as error:
            status = (
                HTTPStatus.OK
                if error.reason_code == "PRODUCTION_NOT_READY"
                else HTTPStatus.BAD_REQUEST
            )
            self._send_error(status, error.reason_code, str(error))
            return
        except ControlRejected as error:
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                error.reason_code,
                str(error),
            )
            return
        except DashboardWorkflowRejected as error:
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                "WORKFLOW_REJECTED",
                str(error),
            )
            return
        except DashboardCampaignRejected as error:
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                error.reason_code,
                str(error),
            )
            return
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                "INVALID_REQUEST",
                str(error) or "Request body must be a valid JSON object.",
            )
            return

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        campaign_update = (
            path.startswith("/api/campaigns/")
            and len(path.strip("/").split("/")) == 3
        )
        if path not in {"/api/test-automation", "/api/campaign"} and not (
            campaign_update
        ):
            self._send_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Route not found.")
            return
        if not self._allow_json_mutation():
            return
        try:
            payload = self._read_json()
            if path == "/api/test-automation":
                result = self.server.dashboard.configure_test_automation(payload)
            else:
                revision = payload.pop("expected_revision", None)
                if isinstance(revision, bool) or not isinstance(revision, int):
                    raise ValueError("CAMPAIGN_REVISION_REQUIRED")
                result = self.server.dashboard.save_campaign_draft(
                    payload,
                    revision,
                    (
                        unquote(path.strip("/").split("/")[2])
                        if campaign_update
                        else None
                    ),
                )
        except UiRunRejected as error:
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                error.reason_code,
                str(error),
            )
            return
        except DashboardCampaignRejected as error:
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                error.reason_code,
                str(error),
            )
            return
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                "INVALID_REQUEST",
                "Request body must be a valid JSON object.",
            )
            return
        self._send_json(HTTPStatus.OK, result)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        parts = path.strip("/").split("/")
        if not (
            path.startswith("/api/campaigns/")
            and len(parts) == 3
        ):
            self._send_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Route not found.")
            return
        if not self._allow_json_mutation():
            return
        try:
            payload = self._read_json()
            revision = payload.get("expected_revision")
            if isinstance(revision, bool) or not isinstance(revision, int):
                raise ValueError("CAMPAIGN_REVISION_REQUIRED")
            result = self.server.dashboard.delete_campaign_draft(
                unquote(parts[2]),
                revision,
            )
        except DashboardCampaignRejected as error:
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                error.reason_code,
                str(error),
            )
            return
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                "INVALID_REQUEST",
                "Request body must be a valid JSON object.",
            )
            return
        self._send_json(HTTPStatus.OK, result)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 2 or length > 16_384:
            raise ValueError("Invalid request length.")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise TypeError("Request body must be an object.")
        return value

    def _allow_json_mutation(self) -> bool:
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if self.server.public_demo:
            parsed_origin = urlparse(origin or "")
            public_host = parsed_origin.hostname or ""
            local_demo = public_host in {"127.0.0.1", "localhost"}
            tunnel_demo = public_host.endswith(
                (".trycloudflare.com", ".lhr.life", ".vercel.app")
            )
            if (
                parsed_origin.scheme not in {"http", "https"}
                or parsed_origin.netloc.casefold() != host.casefold()
                or not (local_demo or tunnel_demo)
            ):
                self.close_connection = True
                self._send_error(
                    HTTPStatus.FORBIDDEN,
                    "CROSS_ORIGIN_REQUEST_REJECTED",
                    "State-changing requests must come from the demo page.",
                )
                return False
            return self._allow_json_content_type()
        allowed_hosts = {
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        }
        allowed_origins = {f"http://{value}" for value in allowed_hosts}
        if host not in allowed_hosts or (
            origin is not None and origin not in allowed_origins
        ):
            self.close_connection = True
            self._send_error(
                HTTPStatus.FORBIDDEN,
                "CROSS_ORIGIN_REQUEST_REJECTED",
                "State-changing requests are accepted only from this local UI.",
            )
            return False
        return self._allow_json_content_type()

    def _allow_json_content_type(self) -> bool:
        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length == 0 and not content_type:
            return True
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            self.close_connection = True
            self._send_error(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "JSON_CONTENT_TYPE_REQUIRED",
                "State-changing requests require application/json.",
            )
            return False
        return True

    def _stream_production_run(self, payload: dict[str, Any]) -> None:
        if str(payload.get("mode", "")) != "production":
            raise UiRunRejected(
                "INVALID_MODE",
                "Streaming progress is available only for the production mode.",
            )
        operating_mode = payload.get("operating_mode")
        mandate_id = None
        if operating_mode == "BOUNDED_AUTONOMY":
            mandate_id = next(
                (
                    str(item["mandate_id"])
                    for item in self.server.dashboard.control_overview()["mandates"]
                    if item["status"] == "ACTIVE"
                ),
                None,
            )
        self._start_ndjson_stream()
        client_connected = True

        def send_event(event: dict[str, Any]) -> None:
            nonlocal client_connected
            if not client_connected:
                return
            try:
                self._send_ndjson_event(event)
            except (BrokenPipeError, ConnectionResetError):
                client_connected = False

        run_arguments: dict[str, Any] = {
            "progress_callback": lambda progress: send_event(
                {"type": "progress", **progress}
            )
        }
        if operating_mode is not None:
            run_arguments["operating_mode"] = str(operating_mode)
            run_arguments["mandate_id"] = mandate_id
        try:
            report = self.server.service.run("production", **run_arguments)
        except UiRunRejected as error:
            send_event(
                {
                    "type": "error",
                    "status": "BLOCKED",
                    "reason_code": error.reason_code,
                    "message": str(error),
                }
            )
            if client_connected:
                self._finish_ndjson_stream()
            return
        except (OSError, RuntimeError, ValueError) as error:
            send_event(
                {
                    "type": "error",
                    "status": "BLOCKED",
                    "reason_code": "RUN_FAILED",
                    "message": str(error) or "Production read-only run failed.",
                }
            )
            if client_connected:
                self._finish_ndjson_stream()
            return
        send_event({"type": "report", "report": report})
        if client_connected:
            self._finish_ndjson_stream()

    def _start_ndjson_stream(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type",
            "application/x-ndjson; charset=utf-8",
        )
        self.send_header("Cache-Control", "no-store, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; connect-src 'self'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.flush()

    def _send_ndjson_event(self, event: dict[str, Any]) -> None:
        body = (
            json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            + b"\n"
        )
        self.wfile.write(f"{len(body):X}\r\n".encode("ascii"))
        self.wfile.write(body)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def _finish_ndjson_stream(self) -> None:
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _send_json(self, status: HTTPStatus, value: Any) -> None:
        self._send_bytes(
            status,
            json.dumps(value, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _send_error(
        self,
        status: HTTPStatus,
        reason_code: str,
        message: str,
    ) -> None:
        self._send_json(
            status,
            {
                "status": "BLOCKED",
                "reason_code": reason_code,
                "message": message,
            },
        )

    def _send_bytes(
        self,
        status: HTTPStatus,
        body: bytes,
        content_type: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; connect-src 'self'; frame-ancestors 'none'",
        )
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        del format, args


class UiHttpServer(ThreadingHTTPServer):
    service: UiRunService
    dashboard: DashboardApplication
    public_demo: bool

    def start_test_automation(self) -> None:
        self._automation_stop = threading.Event()
        self._automation_thread = threading.Thread(
            target=self._automation_loop,
            name="mox-adv-test-automation",
            daemon=True,
        )
        self._automation_thread.start()

    def _automation_loop(self) -> None:
        while not self._automation_stop.wait(0.25):
            try:
                self.service.run_due_automation()
            except (OSError, RuntimeError, TypeError, ValueError):
                continue

    def server_close(self) -> None:
        if hasattr(self, "_automation_stop"):
            self._automation_stop.set()
        if hasattr(self, "_automation_thread"):
            self._automation_thread.join(timeout=2)
        super().server_close()


def build_server(
    *,
    port: int = 8878,
    runs_root: Path = Path("runs"),
    authenticator: Any | None = None,
    public_demo: bool = False,
    production_reader: Any | None = None,
) -> UiHttpServer:
    server = UiHttpServer(("127.0.0.1", port), UiRequestHandler)
    server.public_demo = public_demo
    server.service = UiRunService(
        runs_root,
        production_reader=production_reader,
    )
    server.dashboard = DashboardApplication(
        runs_root,
        server.service,
        authenticator=authenticator,
    )
    server.start_test_automation()
    return server


def serve_ui(
    *,
    port: int = 8878,
    runs_root: Path = Path("runs"),
    open_browser: bool = True,
    public_demo: bool = False,
) -> None:
    server = build_server(
        port=port,
        runs_root=runs_root,
        public_demo=public_demo,
    )
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"MOX-ADV UI: {url}")
    if public_demo:
        print("Temporary public-demo origin support is enabled.")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
