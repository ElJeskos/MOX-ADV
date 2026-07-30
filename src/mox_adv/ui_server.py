"""Local-only HTTP server for the MOX-ADV operator UI."""

from __future__ import annotations

import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mox_adv.control_state import ControlRejected
from mox_adv.ui_dashboard import DashboardApplication
from mox_adv.ui_service import UiRunRejected, UiRunService
from mox_adv.ui_workflows import DashboardWorkflowRejected

ASSET_ROOT = Path(__file__).with_name("ui")
_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/assets/app.css": ("app.css", "text/css; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


class UiRequestHandler(BaseHTTPRequestHandler):
    """Serve a narrow local UI and JSON API."""

    server: UiHttpServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
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
            self._send_json(HTTPStatus.OK, self.server.service.status())
            return
        if path == "/api/test-automation":
            self._send_json(
                HTTPStatus.OK,
                self.server.service.automation(),
            )
            return
        if path == "/api/test-history":
            self._send_json(
                HTTPStatus.OK,
                {"items": self.server.service.decision_history()},
            )
            return
        if path == "/api/control-plane":
            self._send_json(
                HTTPStatus.OK,
                self.server.dashboard.control_overview(),
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
        if path not in {
            "/api/runs",
            "/api/runs/stream",
            "/api/control-plane/mode",
            "/api/control-plane/kill-switch",
            "/api/control-plane/mandates",
            "/api/control-plane/approvals",
            "/api/workflows/campaign",
            "/api/workflows/goal",
            "/api/workflows/impact",
            "/api/evidence/run",
        }:
            self._send_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Route not found.")
            return
        if not self._allow_json_mutation():
            return
        try:
            if path == "/api/runs/stream":
                self._stream_production_run(self._read_json())
                return
            if path == "/api/runs":
                payload = self._read_json()
                mode = str(payload.get("mode", ""))
                operating_mode = payload.get("operating_mode")
                mandate_id = None
                if operating_mode == "BOUNDED_AUTONOMY":
                    mandate_id = next(
                        (
                            str(item["mandate_id"])
                            for item in self.server.dashboard.control_overview()[
                                "mandates"
                            ]
                            if item["status"] == "ACTIVE"
                        ),
                        None,
                    )
                if mode == "test":
                    if operating_mode is None:
                        report = self.server.service.run(
                            mode,
                            scenario=payload.get("scenario"),
                            rules=payload.get("rules"),
                            recommendation_rules=payload.get("recommendation_rules"),
                        )
                    else:
                        report = self.server.service.run(
                            mode,
                            scenario=payload.get("scenario"),
                            rules=payload.get("rules"),
                            recommendation_rules=payload.get("recommendation_rules"),
                            operating_mode=str(operating_mode),
                            mandate_id=mandate_id,
                        )
                else:
                    if operating_mode is None:
                        report = self.server.service.run(mode)
                    else:
                        report = self.server.service.run(
                            mode,
                            operating_mode=str(operating_mode),
                            mandate_id=mandate_id,
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
            elif path == "/api/workflows/campaign":
                result = self.server.dashboard.run_campaign_simulation()
            elif path == "/api/workflows/goal":
                payload = self._read_json()
                action = str(payload.get("action", ""))
                if action == "technical":
                    result = self.server.dashboard.run_goal_technical_simulation()
                elif action == "semantic_decision":
                    result = self.server.dashboard.decide_pending_goal_simulation(
                        str(payload.get("semantic_decision", ""))
                    )
                else:
                    raise ValueError("GOAL_WORKFLOW_ACTION_INVALID")
            elif path == "/api/workflows/impact":
                payload = self._read_json()
                result = self.server.dashboard.run_impact_fixture(
                    str(payload.get("fixture", ""))
                )
            else:
                result = self.server.dashboard.run_full_evidence()
            self._send_json(HTTPStatus.CREATED, result)
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
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                "INVALID_REQUEST",
                str(error) or "Request body must be a valid JSON object.",
            )
            return

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/test-automation":
            self._send_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Route not found.")
            return
        if not self._allow_json_mutation():
            return
        try:
            settings = self.server.service.configure_automation(self._read_json())
        except UiRunRejected as error:
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
        self._send_json(HTTPStatus.OK, settings)

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
        allowed_hosts = {
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        }
        origin = self.headers.get("Origin")
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
) -> UiHttpServer:
    server = UiHttpServer(("127.0.0.1", port), UiRequestHandler)
    server.service = UiRunService(runs_root)
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
) -> None:
    server = build_server(port=port, runs_root=runs_root)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"MOX-ADV UI: {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
