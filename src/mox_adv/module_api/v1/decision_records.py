"""Captured decision records for public module environment denials."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Protocol, Tuple

from mox_adv.environment import (
    PRODUCTION_WRITE_FORBIDDEN,
    ExecutionEnvironment,
)
from mox_adv.module_api.v1.campaign_creation_contracts import (
    CampaignCreationOutcomeV1,
)
from mox_adv.module_api.v1.contracts import (
    MODULE_STATUSES,
    ContractValidationError,
    GoalLifecycleOutcomeV1,
    MetricValueV1,
    ModuleAssessmentV1,
    ModuleHypothesisV1,
    ModuleIdentityV1,
    ModuleProvenanceV1,
    ModuleRecommendationV1,
    ModuleRequestV1,
    ModuleStatus,
)
from mox_adv.module_api.v1.impact_contracts import ImpactEvaluationOutcomeV1

MODULE_DECISION_RECORD_SCHEMA_VERSION = "module-decision-record-v1"


@dataclass(frozen=True)
class ModuleDecisionRecordReceiptV1:
    """Typed identity and opaque reference returned by a Decision Record store."""

    decision_id: str
    reference: str


@dataclass(frozen=True)
class ModuleDecisionFactsV1:
    """Closed analysis facts stored behind an opaque Decision Record reference."""

    metrics: Tuple[MetricValueV1, ...]
    assessment: ModuleAssessmentV1
    recommendations: Tuple[ModuleRecommendationV1, ...]
    provenance: Tuple[ModuleProvenanceV1, ...]
    hypotheses: Tuple[ModuleHypothesisV1, ...] = ()
    lifecycle_outcome: GoalLifecycleOutcomeV1 | None = None
    campaign_creation_outcome: CampaignCreationOutcomeV1 | None = None
    impact_outcome: ImpactEvaluationOutcomeV1 | None = None

    def as_dict(self) -> Dict[str, Any]:
        value = {
            "metrics": [item.as_dict() for item in self.metrics],
            "assessment": self.assessment.as_dict(),
            "recommendations": [item.as_dict() for item in self.recommendations],
            "hypotheses": [item.as_dict() for item in self.hypotheses],
            "provenance": [item.as_dict() for item in self.provenance],
        }
        if self.lifecycle_outcome is not None:
            value["lifecycle_outcome"] = self.lifecycle_outcome.as_dict()
        if self.campaign_creation_outcome is not None:
            value["campaign_creation_outcome"] = (
                self.campaign_creation_outcome.as_dict()
            )
        if self.impact_outcome is not None:
            value["impact_outcome"] = self.impact_outcome.as_dict()
        return value


@dataclass(frozen=True)
class ModuleDecisionV1:
    """Typed, closed payload for one non-execution module decision."""

    outcome: ModuleStatus
    reason_codes: Tuple[str, ...]
    facts: ModuleDecisionFactsV1

    def __post_init__(self) -> None:
        if self.outcome not in MODULE_STATUSES:
            raise ContractValidationError("Decision outcome is unsupported.")
        if any(not code for code in self.reason_codes):
            raise ContractValidationError("Decision reason codes must be non-empty.")


class ModuleDecisionRecordStoreV1(Protocol):
    """Persist a blocked module decision and return its opaque reference."""

    def record_production_write_block(
        self,
        module: ModuleIdentityV1,
        request: ModuleRequestV1,
        trusted_environment: ExecutionEnvironment,
    ) -> ModuleDecisionRecordReceiptV1: ...

    def record_module_decision(
        self,
        module: ModuleIdentityV1,
        request: ModuleRequestV1,
        decision: ModuleDecisionV1,
    ) -> ModuleDecisionRecordReceiptV1: ...


class InMemoryDecisionRecordStoreV1:
    """Thread-safe test and embedded-runtime decision record store."""

    def __init__(self) -> None:
        self._records: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def record_production_write_block(
        self,
        module: ModuleIdentityV1,
        request: ModuleRequestV1,
        trusted_environment: ExecutionEnvironment,
    ) -> ModuleDecisionRecordReceiptV1:
        record: Dict[str, Any] = {
            "schema_version": MODULE_DECISION_RECORD_SCHEMA_VERSION,
            "module": module.as_dict(),
            "idempotency_key": request.idempotency_key,
            "environment": request.environment,
            "requested_environment": request.environment,
            "trusted_environment": trusted_environment.value,
            "operation_kind": request.operation.kind,
            "operation_type": request.operation.operation_type,
            "outcome": "BLOCKED",
            "reason_code": PRODUCTION_WRITE_FORBIDDEN,
        }
        return self._store(record)

    def record_module_decision(
        self,
        module: ModuleIdentityV1,
        request: ModuleRequestV1,
        decision: ModuleDecisionV1,
    ) -> ModuleDecisionRecordReceiptV1:
        record: Dict[str, Any] = {
            "schema_version": MODULE_DECISION_RECORD_SCHEMA_VERSION,
            "module": module.as_dict(),
            "idempotency_key": request.idempotency_key,
            "environment": request.environment,
            "operation_kind": request.operation.kind,
            "operation_type": request.operation.operation_type,
            "outcome": decision.outcome,
            "reason_codes": list(decision.reason_codes),
            "facts": decision.facts.as_dict(),
        }
        return self._store(record)

    def _store(
        self,
        record: Mapping[str, Any],
    ) -> ModuleDecisionRecordReceiptV1:
        canonical = json.dumps(
            record,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        decision_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        reference = "decision-records/" + decision_id + ".json"
        stored = copy.deepcopy(dict(record))
        stored["decision_id"] = decision_id
        with self._lock:
            self._records[reference] = stored
        return ModuleDecisionRecordReceiptV1(
            decision_id=decision_id,
            reference=reference,
        )

    def read(self, reference: str) -> Mapping[str, Any]:
        with self._lock:
            try:
                return copy.deepcopy(self._records[reference])
            except KeyError as error:
                raise KeyError("Decision record does not exist.") from error


class DirectoryDecisionRecordStoreV1:
    """Persist canonical module decisions immutably below one run directory."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record_production_write_block(
        self,
        module: ModuleIdentityV1,
        request: ModuleRequestV1,
        trusted_environment: ExecutionEnvironment,
    ) -> ModuleDecisionRecordReceiptV1:
        return self._store(
            {
                "schema_version": MODULE_DECISION_RECORD_SCHEMA_VERSION,
                "module": module.as_dict(),
                "idempotency_key": request.idempotency_key,
                "environment": request.environment,
                "requested_environment": request.environment,
                "trusted_environment": trusted_environment.value,
                "operation_kind": request.operation.kind,
                "operation_type": request.operation.operation_type,
                "outcome": "BLOCKED",
                "reason_code": PRODUCTION_WRITE_FORBIDDEN,
            }
        )

    def record_module_decision(
        self,
        module: ModuleIdentityV1,
        request: ModuleRequestV1,
        decision: ModuleDecisionV1,
    ) -> ModuleDecisionRecordReceiptV1:
        return self._store(
            {
                "schema_version": MODULE_DECISION_RECORD_SCHEMA_VERSION,
                "module": module.as_dict(),
                "idempotency_key": request.idempotency_key,
                "environment": request.environment,
                "operation_kind": request.operation.kind,
                "operation_type": request.operation.operation_type,
                "outcome": decision.outcome,
                "reason_codes": list(decision.reason_codes),
                "facts": decision.facts.as_dict(),
            }
        )

    def read(self, reference: str) -> Mapping[str, Any]:
        prefix = "decision-records/"
        if not reference.startswith(prefix):
            raise KeyError("Decision record reference is invalid.")
        name = reference[len(prefix) :]
        if "/" in name or not name.endswith(".json") or len(name) != 64 + len(".json"):
            raise KeyError("Decision record reference is invalid.")
        path = self.root / name
        try:
            content = path.read_bytes()
            value = json.loads(content.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise KeyError("Decision record does not exist.") from error
        if not isinstance(value, dict):
            raise KeyError("Decision record is invalid.")
        canonical = self._canonical(value)
        if content != canonical:
            raise KeyError("Decision record is not canonical.")
        return copy.deepcopy(value)

    def _store(
        self,
        record: Mapping[str, Any],
    ) -> ModuleDecisionRecordReceiptV1:
        canonical_record = dict(record)
        decision_id = hashlib.sha256(
            json.dumps(
                canonical_record,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        canonical_record["decision_id"] = decision_id
        content = self._canonical(canonical_record)
        path = self.root / (decision_id + ".json")
        with self._lock:
            try:
                descriptor = os.open(
                    path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o400,
                )
            except FileExistsError:
                if path.read_bytes() != content:
                    raise RuntimeError(
                        "Immutable module Decision Record contains different content."
                    ) from None
            else:
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
                except BaseException:
                    try:
                        path.unlink()
                    except OSError:
                        pass
                    raise
        return ModuleDecisionRecordReceiptV1(
            decision_id=decision_id,
            reference="decision-records/" + path.name,
        )

    @staticmethod
    def _canonical(value: Mapping[str, Any]) -> bytes:
        return (
            json.dumps(
                value,
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
