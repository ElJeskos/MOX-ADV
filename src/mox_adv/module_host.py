"""Small production HTTP host for the versioned standalone module contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

from mox_adv.module_api.v1 import HttpJsonModuleAdapterV1

MAX_REQUEST_BYTES = 1_048_576


class DuplicateJsonKeyError(ValueError):
    """A wire JSON object contains two values for the same field."""


def _closed_json_object(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for name, item in pairs:
        if name in value:
            raise DuplicateJsonKeyError("Duplicate JSON field: " + name)
        value[name] = item
    return value


class ModuleHttpServerV1(ThreadingHTTPServer):
    """Bind one adapter and redacted diagnostics to a loopback HTTP server."""

    adapter: HttpJsonModuleAdapterV1
    diagnostics: Dict[str, Any]
    openapi_document: Dict[str, Any]


class ModuleHttpRequestHandlerV1(BaseHTTPRequestHandler):
    """Serve only the stable module, health, diagnostics, and contract routes."""

    server: ModuleHttpServerV1
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_json(HTTPStatus.OK, {"status": "ready"})
            return
        if self.path == "/diagnostics":
            self._send_json(HTTPStatus.OK, self.server.diagnostics)
            return
        if self.path == "/openapi.json":
            self._send_json(HTTPStatus.OK, self.server.openapi_document)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"})

    def do_POST(self) -> None:
        if self.path != "/v1/runs":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"})
            return
        content_type = self.headers.get_content_type()
        if content_type != "application/json":
            self._send_json(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                {"error": "CONTENT_TYPE_MUST_BE_APPLICATION_JSON"},
            )
            return
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            content_length = -1
        if content_length < 0 or content_length > MAX_REQUEST_BYTES:
            self._send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"error": "REQUEST_SIZE_INVALID"},
            )
            return
        try:
            payload = json.loads(
                self.rfile.read(content_length).decode("utf-8"),
                object_pairs_hook=_closed_json_object,
            )
        except (UnicodeError, json.JSONDecodeError, DuplicateJsonKeyError):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "INVALID_JSON"},
            )
            return
        if not isinstance(payload, Mapping):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "JSON_OBJECT_REQUIRED"},
            )
            return
        response = self.server.adapter.handle(payload)
        self._send_json(response.status_code, response.body)

    def _send_json(
        self,
        status: int,
        payload: Mapping[str, Any],
    ) -> None:
        body = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def build_module_server_v1(
    *,
    bind: str,
    port: int,
    adapter: HttpJsonModuleAdapterV1,
    diagnostics: Mapping[str, Any],
    openapi_document: Mapping[str, Any],
) -> ModuleHttpServerV1:
    """Create a server without starting its request loop."""

    server = ModuleHttpServerV1((bind, port), ModuleHttpRequestHandlerV1)
    server.adapter = adapter
    server.diagnostics = dict(diagnostics)
    server.openapi_document = dict(openapi_document)
    return server
