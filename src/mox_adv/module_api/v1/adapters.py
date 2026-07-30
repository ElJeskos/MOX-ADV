"""Adapters that expose one module interface in-process and over HTTP/JSON."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Protocol

from mox_adv.environment import (
    ExecutionEnvironment,
    parse_execution_environment,
)
from mox_adv.module_api.v1.contracts import (
    ContractValidationError,
    ModuleIdentityV1,
    ModuleRequestV1,
    ModuleResultV1,
)
from mox_adv.module_api.v1.decision_records import (
    InMemoryDecisionRecordStoreV1,
    ModuleDecisionRecordStoreV1,
)
from mox_adv.module_api.v1.replay_store import (
    AnalysisReplayConflictError,
    AnalysisReplayPendingError,
    AnalysisReplayStoreV1,
    InMemoryAnalysisReplayStoreV1,
    SqliteAnalysisReplayStoreV1,
    StoredAnalysisResponseV1,
)


class ModuleV1(Protocol):
    """The provider-neutral deep module interface."""

    identity: ModuleIdentityV1

    def invoke(self, request: ModuleRequestV1) -> ModuleResultV1: ...


@dataclass(frozen=True)
class HttpJsonResponseV1:
    status_code: int
    body: Dict[str, Any]


class InProcessModuleAdapterV1:
    """Validate the paired-runtime seam without adding an HTTP hop."""

    def __init__(
        self,
        module: ModuleV1,
        *,
        environment: ExecutionEnvironment,
        decision_records: Optional[ModuleDecisionRecordStoreV1] = None,
    ) -> None:
        self._module = module
        self._environment = parse_execution_environment(environment)
        self.decision_records = (
            InMemoryDecisionRecordStoreV1()
            if decision_records is None
            else decision_records
        )

    def invoke(self, request: ModuleRequestV1) -> ModuleResultV1:
        canonical_request = _canonical_in_process_request(request)
        blocked = _block_production_execution(
            self._module,
            canonical_request,
            self._environment,
            self.decision_records,
        )
        if blocked is not None:
            return blocked
        result = self._module.invoke(canonical_request)
        return ModuleResultV1.from_dict(result.as_dict())


class HttpJsonModuleAdapterV1:
    """Translate strict JSON objects to and from the same module interface."""

    def __init__(
        self,
        module: ModuleV1,
        *,
        environment: ExecutionEnvironment,
        decision_records: Optional[ModuleDecisionRecordStoreV1] = None,
        analysis_replay_store: AnalysisReplayStoreV1,
    ) -> None:
        self._module = module
        self._environment = parse_execution_environment(environment)
        self._analysis_replay_store = analysis_replay_store
        self._analysis_claim_token = uuid.uuid4().hex
        self._analysis_inflight: Dict[str, str] = {}
        self._analysis_replay_lock = threading.Condition()
        self.decision_records = (
            InMemoryDecisionRecordStoreV1()
            if decision_records is None
            else decision_records
        )

    @classmethod
    def for_embedded(
        cls,
        module: ModuleV1,
        *,
        environment: ExecutionEnvironment,
        decision_records: Optional[ModuleDecisionRecordStoreV1] = None,
    ) -> "HttpJsonModuleAdapterV1":
        """Compose an explicitly process-local adapter for tests/embedding."""

        return cls(
            module,
            environment=environment,
            decision_records=decision_records,
            analysis_replay_store=InMemoryAnalysisReplayStoreV1(),
        )

    @classmethod
    def for_durable_host(
        cls,
        module: ModuleV1,
        *,
        environment: ExecutionEnvironment,
        replay_path: Path,
        decision_records: Optional[ModuleDecisionRecordStoreV1] = None,
    ) -> "HttpJsonModuleAdapterV1":
        """Compose the production/reference HTTP path with durable replay."""

        return cls(
            module,
            environment=environment,
            decision_records=decision_records,
            analysis_replay_store=SqliteAnalysisReplayStoreV1(replay_path),
        )

    def handle(self, payload: Mapping[str, Any]) -> HttpJsonResponseV1:
        try:
            request = ModuleRequestV1.from_dict(payload)
        except ContractValidationError as error:
            result = ModuleResultV1.rejected_contract(
                module=self._module.identity,
                error=error,
            )
            return HttpJsonResponseV1(status_code=400, body=result.as_dict())

        if request.operation.kind == "ANALYZE":
            return self._handle_idempotent_analysis(request)
        return self._invoke(request)

    def _handle_idempotent_analysis(
        self,
        request: ModuleRequestV1,
    ) -> HttpJsonResponseV1:
        key = request.idempotency_key
        fingerprint = analysis_request_fingerprint_v1(request)
        while True:
            try:
                replay = self._analysis_replay_store.bind_or_read(
                    module_id=self._module.identity.module_id,
                    idempotency_key=key,
                    request_fingerprint=fingerprint,
                    claim_token=self._analysis_claim_token,
                )
            except AnalysisReplayConflictError:
                return self._idempotency_conflict()
            except AnalysisReplayPendingError:
                with self._analysis_replay_lock:
                    self._analysis_replay_lock.wait(timeout=0.05)
                continue
            if replay is not None:
                return HttpJsonResponseV1(
                    status_code=replay.status_code,
                    body=replay.body,
                )
            with self._analysis_replay_lock:
                inflight_fingerprint = self._analysis_inflight.get(key)
                if inflight_fingerprint is None:
                    self._analysis_inflight[key] = fingerprint
                    break
                if inflight_fingerprint != fingerprint:
                    return self._idempotency_conflict()
                self._analysis_replay_lock.wait()

        try:
            response = self._invoke(request)
        except BaseException:
            try:
                self._release_analysis_claim(
                    key=key,
                    fingerprint=fingerprint,
                )
            finally:
                self._clear_local_analysis_inflight(key)
            raise

        try:
            if _response_is_replayable(response):
                self._analysis_replay_store.store_response(
                    module_id=self._module.identity.module_id,
                    idempotency_key=key,
                    request_fingerprint=fingerprint,
                    claim_token=self._analysis_claim_token,
                    response=StoredAnalysisResponseV1(
                        status_code=response.status_code,
                        body=response.body,
                    ),
                )
            else:
                self._release_analysis_claim(
                    key=key,
                    fingerprint=fingerprint,
                )
        except BaseException:
            self._release_analysis_claim(
                key=key,
                fingerprint=fingerprint,
            )
            raise
        finally:
            self._clear_local_analysis_inflight(key)
        return response

    def _release_analysis_claim(
        self,
        *,
        key: str,
        fingerprint: str,
    ) -> None:
        self._analysis_replay_store.release_claim(
            module_id=self._module.identity.module_id,
            idempotency_key=key,
            request_fingerprint=fingerprint,
            claim_token=self._analysis_claim_token,
        )

    def _clear_local_analysis_inflight(self, key: str) -> None:
        with self._analysis_replay_lock:
            self._analysis_inflight.pop(key, None)
            self._analysis_replay_lock.notify_all()

    def _idempotency_conflict(self) -> HttpJsonResponseV1:
        result = ModuleResultV1.rejected_contract(
            module=self._module.identity,
            error=ContractValidationError(
                "idempotency_key is already bound to a different request"
            ),
        )
        return HttpJsonResponseV1(status_code=409, body=result.as_dict())

    def _invoke(self, request: ModuleRequestV1) -> HttpJsonResponseV1:
        blocked = _block_production_execution(
            self._module,
            request,
            self._environment,
            self.decision_records,
        )
        result = (
            blocked
            if blocked is not None
            else ModuleResultV1.from_dict(self._module.invoke(request).as_dict())
        )
        status_code = {
            "SUCCEEDED": 200,
            "PARTIAL": 200,
            "BLOCKED": 422,
            "REJECTED": 422,
            "FAILED": 500,
        }[result.status]
        return HttpJsonResponseV1(
            status_code=status_code,
            body=result.as_dict(),
        )


def analysis_request_fingerprint_v1(request: ModuleRequestV1) -> str:
    """Return the public canonical fingerprint used by recovery tooling."""

    canonical = json.dumps(
        request.as_dict(),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_in_process_request(request: ModuleRequestV1) -> ModuleRequestV1:
    evidence = request.external_evidence
    if evidence is None or evidence.source != "PAIRED_MODULE_RESULT":
        return ModuleRequestV1.from_dict(request.as_dict())
    payload = request.as_dict()
    payload_evidence = payload["external_evidence"]
    assert isinstance(payload_evidence, dict)
    payload_evidence["source"] = "CUSTOMER_ECOSYSTEM"
    canonical = ModuleRequestV1.from_dict(payload)
    assert canonical.external_evidence is not None
    return replace(
        canonical,
        external_evidence=replace(
            canonical.external_evidence,
            source="PAIRED_MODULE_RESULT",
        ),
    )


def _response_is_replayable(response: HttpJsonResponseV1) -> bool:
    if response.status_code < 500:
        return True
    errors = response.body.get("errors")
    if not isinstance(errors, list) or not errors:
        return False
    for item in errors:
        if not isinstance(item, Mapping):
            return False
        retryable = item.get("retryable")
        if not isinstance(retryable, bool) or retryable:
            return False
    return True


def _block_production_execution(
    module: ModuleV1,
    request: ModuleRequestV1,
    trusted_environment: ExecutionEnvironment,
    decision_records: ModuleDecisionRecordStoreV1,
) -> Optional[ModuleResultV1]:
    if request.operation.kind != "EXECUTE" or (
        trusted_environment is ExecutionEnvironment.TEST
        and request.environment == ExecutionEnvironment.TEST.value
    ):
        return None
    receipt = decision_records.record_production_write_block(
        module.identity,
        request,
        trusted_environment,
    )
    return ModuleResultV1.blocked_production_write(
        module=module.identity,
        request=request,
        decision_id=receipt.decision_id,
        decision_record_ref=receipt.reference,
    )
