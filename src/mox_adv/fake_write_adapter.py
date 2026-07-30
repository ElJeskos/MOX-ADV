"""Deterministic in-memory adapter for write-path tests and simulation."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Mapping, Optional

from mox_adv.commands import HighLevelCommand


class AdapterTimeout(TimeoutError):
    """The fake write outcome requires readback reconciliation."""


class FakeWriteAdapter:
    """A fake adapter with no socket, URL, or HTTP transport dependency."""

    is_fake = True

    def __init__(
        self,
        initial_state: Optional[Mapping[str, Any]] = None,
        write_delay_seconds: float = 0,
        timeout_after_write: bool = False,
        timeout_readback: Any = "__USE_STATE__",
        current_fingerprints: Optional[Mapping[str, str]] = None,
    ) -> None:
        self._state: Dict[str, Any] = dict(initial_state or {})
        self._fingerprints = dict(current_fingerprints or {})
        self._lock = threading.Lock()
        self.write_calls = 0
        self.write_delay_seconds = write_delay_seconds
        self.timeout_after_write = timeout_after_write
        self.timeout_readback = timeout_readback
        self._timed_out = False

    def apply(self, target_key: str, command: HighLevelCommand) -> None:
        if not command.dry_run:
            raise ValueError("Fake adapter accepts only a verified dry-run command.")
        with self._lock:
            self.write_calls += 1
        if self.write_delay_seconds:
            time.sleep(self.write_delay_seconds)
        if self.timeout_after_write:
            self._timed_out = True
            raise AdapterTimeout("Fake adapter injected a write timeout.")
        with self._lock:
            self._state[target_key] = command.target_value

    def readback(self, target_key: str) -> Any:
        if self._timed_out and self.timeout_readback != "__USE_STATE__":
            return self.timeout_readback
        with self._lock:
            return self._state.get(target_key)

    def current_fingerprint(self, target_key: str) -> str:
        with self._lock:
            try:
                return self._fingerprints[target_key]
            except KeyError as error:
                raise ValueError(
                    "Trusted current fingerprint is unavailable."
                ) from error

    def set_current_fingerprint(self, target_key: str, fingerprint: str) -> None:
        with self._lock:
            self._fingerprints[target_key] = fingerprint
