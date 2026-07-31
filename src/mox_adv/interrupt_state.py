"""Independently writable durable revoke and kill-switch signals."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator


class InterruptStateUnavailable(RuntimeError):
    pass


class DurableInterruptState:
    """A sidecar database that can preempt an execution-state transaction."""

    def __init__(self, control_path: Path) -> None:
        self.path = Path(str(control_path) + ".interrupts.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._connect() as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS interrupt_signals ("
                    "kind TEXT NOT NULL, scope TEXT NOT NULL, active INTEGER NOT NULL, "
                    "reason TEXT NOT NULL, updated_at TEXT NOT NULL, "
                    "PRIMARY KEY(kind, scope))"
                )
        except sqlite3.Error as error:
            raise InterruptStateUnavailable from error
        with suppress(OSError):
            os.chmod(self.path, 0o600)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=0.25)
        try:
            connection.execute("PRAGMA busy_timeout = 250")
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def engage(
        self,
        kind: str,
        scope: str,
        reason: str,
        now: datetime,
    ) -> None:
        self._set(kind, scope, True, reason, now)

    def release(
        self,
        kind: str,
        scope: str,
        reason: str,
        now: datetime,
    ) -> None:
        self._set(kind, scope, False, reason, now)

    def any_active(self, kind: str, scopes: Iterable[str]) -> bool:
        values = tuple(scopes)
        if not values:
            return False
        placeholders = ",".join("?" for _ in values)
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT 1 FROM interrupt_signals "
                    f"WHERE kind = ? AND active = 1 "
                    f"AND scope IN ({placeholders}) LIMIT 1",
                    (kind,) + values,
                ).fetchone()
        except sqlite3.Error as error:
            raise InterruptStateUnavailable from error
        return row is not None

    def _set(
        self,
        kind: str,
        scope: str,
        active: bool,
        reason: str,
        now: datetime,
    ) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO interrupt_signals "
                    "(kind, scope, active, reason, updated_at) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(kind, scope) DO UPDATE SET "
                    "active = excluded.active, reason = excluded.reason, "
                    "updated_at = excluded.updated_at",
                    (kind, scope, int(active), reason, now.isoformat()),
                )
        except sqlite3.Error as error:
            raise InterruptStateUnavailable from error


def kill_switch_scopes(
    organization: str,
    connection: str,
    campaign: str,
) -> tuple[str, ...]:
    return (
        "global",
        "organization:" + organization,
        "connection:" + connection,
        "campaign:" + campaign,
    )
