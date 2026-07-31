"""Single Vercel Python Function for the MOX-ADV Dashboard."""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from mox_adv.ui_server import UiRequestHandler
from mox_adv.vercel_runtime import VercelStateStore, build_vercel_runtime

_SCRATCH_ROOT = Path("/tmp/mox-adv-vercel")
_RUNTIME = build_vercel_runtime(scratch_root=_SCRATCH_ROOT)
_STATE_STORE = VercelStateStore.from_environment()
_STATE_LOCK = threading.Lock()
_ORIGINAL_PATH_QUERY = "__mox_path"
_MUTATING_METHODS = frozenset({"POST", "PUT", "DELETE"})


class handler(UiRequestHandler):
    """Bind the existing narrow HTTP surface to a Vercel Function request."""

    def _bind_runtime(self, runtime: object) -> None:
        self.server.public_demo = True
        self.server.service = runtime.service
        self.server.dashboard = runtime.dashboard

    def _dispatch(self, operation: Callable[[], None]) -> None:
        self.path = _restore_original_path(self.path)
        if not _STATE_STORE.enabled or not self.path.startswith("/api/"):
            self._bind_runtime(_RUNTIME)
            if self.path.startswith("/api/"):
                _RUNTIME.tick()
            operation()
            return
        with _STATE_LOCK:
            _STATE_STORE.restore(_SCRATCH_ROOT)
            runtime = build_vercel_runtime(scratch_root=_SCRATCH_ROOT)
            self._bind_runtime(runtime)
            automation_changed = runtime.tick()
            operation()
            if automation_changed or self.command in _MUTATING_METHODS:
                _STATE_STORE.persist(_SCRATCH_ROOT)

    def do_GET(self) -> None:
        self._dispatch(super().do_GET)

    def do_POST(self) -> None:
        self._dispatch(super().do_POST)

    def do_PUT(self) -> None:
        self._dispatch(super().do_PUT)

    def do_DELETE(self) -> None:
        self._dispatch(super().do_DELETE)


def _restore_original_path(value: str) -> str:
    parsed = urlsplit(value)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    original_path = next(
        (
            item_value
            for item_name, item_value in query
            if item_name == _ORIGINAL_PATH_QUERY
        ),
        parsed.path,
    )
    if not original_path.startswith("/"):
        original_path = "/" + original_path
    forwarded_query = [
        (item_name, item_value)
        for item_name, item_value in query
        if item_name != _ORIGINAL_PATH_QUERY
    ]
    return urlunsplit(
        (
            "",
            "",
            original_path,
            urlencode(forwarded_query, doseq=True),
            "",
        )
    )
