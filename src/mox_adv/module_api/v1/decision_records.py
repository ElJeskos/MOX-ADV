"""Captured decision records for public module environment denials."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from typing import Any, Dict, Mapping, Protocol

from mox_adv.environment import PRODUCTION_WRITE_FORBIDDEN
from mox_adv.module_api.v1.contracts import (
    ModuleIdentityV1,
    ModuleRequestV1,
)


MODULE_DECISION_RECORD_SCHEMA_VERSION = "module-decision-record-v1"


class ModuleDecisionRecordStoreV1(Protocol):
    """Persist a blocked module decision and return its opaque reference."""

    def record_production_write_block(
        self,
        module: ModuleIdentityV1,
        request: ModuleRequestV1,
    ) -> str: ...


class InMemoryDecisionRecordStoreV1:
    """Thread-safe test and embedded-runtime decision record store."""

    def __init__(self) -> None:
        self._records: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def record_production_write_block(
        self,
        module: ModuleIdentityV1,
        request: ModuleRequestV1,
    ) -> str:
        record: Dict[str, Any] = {
            "schema_version": MODULE_DECISION_RECORD_SCHEMA_VERSION,
            "module": module.as_dict(),
            "idempotency_key": request.idempotency_key,
            "environment": request.environment,
            "operation_kind": request.operation.kind,
            "operation_type": request.operation.operation_type,
            "outcome": "BLOCKED",
            "reason_code": PRODUCTION_WRITE_FORBIDDEN,
        }
        canonical = json.dumps(
            record,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        decision_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        reference = "decision-records/" + decision_id + ".json"
        stored = dict(record)
        stored["decision_id"] = decision_id
        with self._lock:
            self._records[reference] = stored
        return reference

    def read(self, reference: str) -> Mapping[str, Any]:
        with self._lock:
            try:
                return copy.deepcopy(self._records[reference])
            except KeyError as error:
                raise KeyError("Decision record does not exist.") from error
