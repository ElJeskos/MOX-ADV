"""Durable idempotency bindings for successful module analysis responses."""

from __future__ import annotations

import copy
import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Protocol, Tuple


class AnalysisReplayConflictError(ValueError):
    """An idempotency key is already bound to another canonical request."""


class AnalysisReplayPendingError(RuntimeError):
    """Another adapter currently owns the provider read for this key."""


@dataclass(frozen=True)
class StoredAnalysisResponseV1:
    status_code: int
    body: Dict[str, Any]


class AnalysisReplayStoreV1(Protocol):
    def bind_or_read(
        self,
        *,
        module_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        claim_token: str,
    ) -> Optional[StoredAnalysisResponseV1]: ...

    def store_response(
        self,
        *,
        module_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        claim_token: str,
        response: StoredAnalysisResponseV1,
    ) -> None: ...

    def release_claim(
        self,
        *,
        module_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        claim_token: str,
    ) -> None: ...


class InMemoryAnalysisReplayStoreV1:
    """Process-local replay store for tests and embedded compositions."""

    def __init__(self) -> None:
        self._records: Dict[
            Tuple[str, str],
            Tuple[str, Optional[str], Optional[StoredAnalysisResponseV1]],
        ] = {}
        self._lock = threading.Lock()

    def bind_or_read(
        self,
        *,
        module_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        claim_token: str,
    ) -> Optional[StoredAnalysisResponseV1]:
        key = (module_id, idempotency_key)
        with self._lock:
            record = self._records.get(key)
            if record is None:
                self._records[key] = (
                    request_fingerprint,
                    claim_token,
                    None,
                )
                return None
            bound_fingerprint, owner_token, response = record
            if bound_fingerprint != request_fingerprint:
                raise AnalysisReplayConflictError(
                    "idempotency_key is already bound to a different request"
                )
            if response is not None:
                return copy.deepcopy(response)
            if owner_token is None:
                self._records[key] = (
                    request_fingerprint,
                    claim_token,
                    None,
                )
                return None
            if owner_token == claim_token:
                return None
            raise AnalysisReplayPendingError(
                "another adapter owns this analysis request"
            )

    def store_response(
        self,
        *,
        module_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        claim_token: str,
        response: StoredAnalysisResponseV1,
    ) -> None:
        key = (module_id, idempotency_key)
        with self._lock:
            record = self._records.get(key)
            if (
                record is None
                or record[0] != request_fingerprint
                or record[1] != claim_token
            ):
                raise AnalysisReplayConflictError(
                    "analysis response does not match its idempotency binding"
                )
            self._records[key] = (
                request_fingerprint,
                None,
                copy.deepcopy(response),
            )

    def release_claim(
        self,
        *,
        module_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        claim_token: str,
    ) -> None:
        key = (module_id, idempotency_key)
        with self._lock:
            record = self._records.get(key)
            if (
                record is not None
                and record[0] == request_fingerprint
                and record[1] == claim_token
                and record[2] is None
            ):
                self._records[key] = (
                    request_fingerprint,
                    None,
                    None,
                )


class SqliteAnalysisReplayStoreV1:
    """Persist replayable analysis responses across adapter restarts."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._initialize()

    def bind_or_read(
        self,
        *,
        module_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        claim_token: str,
    ) -> Optional[StoredAnalysisResponseV1]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT
                    request_fingerprint,
                    status_code,
                    body_json,
                    owner_token
                FROM module_analysis_replays
                WHERE module_id = ? AND idempotency_key = ?
                """,
                (module_id, idempotency_key),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO module_analysis_replays (
                        module_id,
                        idempotency_key,
                        request_fingerprint,
                        status_code,
                        body_json,
                        owner_token
                    ) VALUES (?, ?, ?, NULL, NULL, ?)
                    """,
                    (
                        module_id,
                        idempotency_key,
                        request_fingerprint,
                        claim_token,
                    ),
                )
                connection.commit()
                return None
            (
                bound_fingerprint,
                status_code,
                body_json,
                owner_token,
            ) = row
            if bound_fingerprint != request_fingerprint:
                raise AnalysisReplayConflictError(
                    "idempotency_key is already bound to a different request"
                )
            if status_code is None or body_json is None:
                if owner_token == claim_token or owner_token is None:
                    connection.execute(
                        """
                        UPDATE module_analysis_replays
                        SET owner_token = ?
                        WHERE module_id = ? AND idempotency_key = ?
                        """,
                        (
                            claim_token,
                            module_id,
                            idempotency_key,
                        ),
                    )
                    connection.commit()
                    return None
                raise AnalysisReplayPendingError(
                    "another adapter owns this analysis request"
                )
            body = json.loads(body_json)
            if not isinstance(body, dict):
                raise RuntimeError("Stored analysis replay body is malformed.")
            return StoredAnalysisResponseV1(
                status_code=int(status_code),
                body=body,
            )

    def store_response(
        self,
        *,
        module_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        claim_token: str,
        response: StoredAnalysisResponseV1,
    ) -> None:
        body_json = json.dumps(
            response.body,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT request_fingerprint, owner_token
                FROM module_analysis_replays
                WHERE module_id = ? AND idempotency_key = ?
                """,
                (module_id, idempotency_key),
            ).fetchone()
            if (
                row is None
                or row[0] != request_fingerprint
                or row[1] != claim_token
            ):
                raise AnalysisReplayConflictError(
                    "analysis response does not match its idempotency binding"
                )
            connection.execute(
                """
                UPDATE module_analysis_replays
                SET
                    status_code = ?,
                    body_json = ?,
                    owner_token = NULL
                WHERE module_id = ? AND idempotency_key = ?
                """,
                (
                    response.status_code,
                    body_json,
                    module_id,
                    idempotency_key,
                ),
            )
            connection.commit()

    def release_claim(
        self,
        *,
        module_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        claim_token: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE module_analysis_replays
                SET owner_token = NULL
                WHERE
                    module_id = ?
                    AND idempotency_key = ?
                    AND request_fingerprint = ?
                    AND owner_token = ?
                    AND status_code IS NULL
                    AND body_json IS NULL
                """,
                (
                    module_id,
                    idempotency_key,
                    request_fingerprint,
                    claim_token,
                ),
            )
            connection.commit()

    def recover_abandoned_claim(
        self,
        *,
        module_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> bool:
        """Release a claim only after an operator reconciles the stopped owner."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE module_analysis_replays
                SET owner_token = NULL
                WHERE
                    module_id = ?
                    AND idempotency_key = ?
                    AND request_fingerprint = ?
                    AND owner_token IS NOT NULL
                    AND status_code IS NULL
                    AND body_json IS NULL
                """,
                (
                    module_id,
                    idempotency_key,
                    request_fingerprint,
                ),
            )
            connection.commit()
            return cursor.rowcount == 1

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS module_analysis_replays (
                    module_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    status_code INTEGER,
                    body_json TEXT,
                    owner_token TEXT,
                    PRIMARY KEY (module_id, idempotency_key)
                )
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self._path), timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()
