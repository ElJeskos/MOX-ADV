"""Typed Yandex Direct management boundary with a socket-free fake adapter."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
)

from mox_adv.application_control import ApplicationWriteBoundary
from mox_adv.audit import AuditWriteBlocked
from mox_adv.control_state import ControlRejected, TrustedScope


class DirectStateTransitionRejected(RuntimeError):
    """A management request failed before reaching the adapter."""


class DirectAdapterFailure(RuntimeError):
    """The fake adapter injected a definite operation failure."""


class DirectOutcomeUnknown(RuntimeError):
    """The adapter outcome cannot be determined without reconciliation."""


class DirectService(str, Enum):
    CAMPAIGNS = "Campaigns"
    AD_GROUPS = "AdGroups"
    ADS = "Ads"
    KEYWORDS = "Keywords"
    KEYWORD_BIDS = "KeywordBids"


class DirectMethod(str, Enum):
    ADD = "add"
    GET = "get"
    UPDATE = "update"
    SUSPEND = "suspend"
    RESUME = "resume"
    ARCHIVE = "archive"
    UNARCHIVE = "unarchive"
    MODERATE = "moderate"
    DELETE = "delete"
    SET = "set"


class DirectState(str, Enum):
    DRAFT = "DRAFT"
    MODERATION = "MODERATION"
    ON = "ON"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class DirectObjectType(str, Enum):
    UNIFIED_CAMPAIGN = "UNIFIED_CAMPAIGN"
    UNIFIED_AD_GROUP = "UNIFIED_AD_GROUP"
    TEXT_AD = "TEXT_AD"
    KEYWORD = "KEYWORD"


@dataclass(frozen=True)
class CreatedDirectObject:
    service: DirectService
    object_id: str
    actual_type: str


@dataclass(frozen=True)
class DirectMethodRequest:
    run_id: str
    operation_key: str
    service: DirectService
    method: DirectMethod
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class DirectMethodResult:
    service: DirectService
    method: DirectMethod
    created_objects: Tuple[CreatedDirectObject, ...]
    readback: Tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class DirectReconciliationResult:
    status: str
    result: Optional[DirectMethodResult]


@dataclass(frozen=True)
class ProductionPilotAuthority:
    account: str
    credential_profile: str
    approval_id: str
    proposal_id: str
    execution_key: str
    binding_hash: str
    armed: bool


class DirectManagementAdapter(Protocol):
    is_fake: bool

    def invoke(self, request: DirectMethodRequest) -> DirectMethodResult: ...

    def inspect(self, service: str, object_id: str) -> Mapping[str, Any]: ...

    def reconcile(self, operation_key: str) -> Optional[DirectMethodResult]: ...


class RunObjectRegistry(Protocol):
    def object_belongs_to_run(
        self,
        run_id: str,
        service: str,
        object_id: str,
    ) -> bool: ...

    def production_authority_is_valid(
        self,
        authority: ProductionPilotAuthority,
    ) -> bool: ...

    def operation_belongs_to_active_saga(
        self,
        run_id: str,
        operation_key: str,
    ) -> bool: ...

    def claim_direct_operation(
        self,
        request: DirectMethodRequest,
        authority: Optional[ProductionPilotAuthority],
        now: datetime,
        final_check: Callable[[], None],
    ) -> bool: ...

    def cancel_direct_operation_claim(
        self,
        request: DirectMethodRequest,
    ) -> None: ...


class DirectManagementConnectorV1:
    """Expose every FR-002 Direct operation as an explicit typed method."""

    def __init__(
        self,
        policy: Mapping[str, Any],
        adapter: DirectManagementAdapter,
        registry: RunObjectRegistry,
        authority: Optional[ProductionPilotAuthority] = None,
        write_boundary: Optional[ApplicationWriteBoundary] = None,
        trusted_scope: Optional[TrustedScope] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if type(write_boundary) is not ApplicationWriteBoundary:
            raise DirectStateTransitionRejected(
                "DURABLE_DISPATCH_GUARD_REQUIRED"
            )
        if trusted_scope is None and type(adapter) is FakeDirectManagementAdapter:
            simulation = policy["bindings"]["simulation"]
            trusted_scope = TrustedScope(
                organization=str(simulation["organization"]),
                connection=str(simulation["connection"]),
                account=str(simulation["direct_account"]),
                campaign="direct-management",
                writer=str(simulation["single_writer"]),
            )
        self._policy = policy
        self._adapter = adapter
        self._registry = registry
        self._authority = authority
        self._write_boundary = write_boundary
        self._trusted_scope = trusted_scope
        self._clock = clock
        self._allowed = {
            (str(item["service"]), str(item["method"]))
            for item in policy["api_matrix"]
            if item.get("system") == "DIRECT"
            and item.get("host") == "api.direct.yandex.com"
            and item.get("version") == "v501"
            and item.get("http_verb") == "POST"
        }

    def campaigns_add(
        self,
        run_id: str,
        operation_key: str,
        campaign: Mapping[str, Any],
    ) -> Tuple[CreatedDirectObject, ...]:
        return self._invoke(
            run_id,
            operation_key,
            "Campaigns",
            "add",
            campaign,
        ).created_objects

    def campaigns_get(
        self,
        run_id: str,
        object_ids: Any,
    ) -> Tuple[Mapping[str, Any], ...]:
        return self._get(run_id, "Campaigns", object_ids)

    def campaigns_update(
        self,
        run_id: str,
        object_id: str,
        changes: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return self._single_write(run_id, "Campaigns", "update", object_id, changes)

    def campaigns_suspend(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_state(run_id, "Campaigns", object_id, {"ON"}, "suspend")
        return self._single_write(run_id, "Campaigns", "suspend", object_id, {})

    def campaigns_resume(
        self,
        run_id: str,
        object_id: str,
        operation_key: Optional[str] = None,
    ) -> Mapping[str, Any]:
        self._require_state(run_id, "Campaigns", object_id, {"SUSPENDED"}, "resume")
        return self._single_write(
            run_id,
            "Campaigns",
            "resume",
            object_id,
            {},
            operation_key,
        )

    def campaigns_archive(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_owned(run_id, "Campaigns", object_id, "archive")
        self._require_state(run_id, "Campaigns", object_id, {"SUSPENDED"}, "archive")
        return self._single_write(run_id, "Campaigns", "archive", object_id, {})

    def campaigns_unarchive(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_state(run_id, "Campaigns", object_id, {"ARCHIVED"}, "unarchive")
        return self._single_write(run_id, "Campaigns", "unarchive", object_id, {})

    def campaigns_delete(
        self,
        run_id: str,
        object_id: str,
        operation_key: Optional[str] = None,
    ) -> Mapping[str, Any]:
        self._require_owned(run_id, "Campaigns", object_id, "delete")
        self._require_state(
            run_id,
            "Campaigns",
            object_id,
            {"SUSPENDED", "ARCHIVED"},
            "delete",
        )
        return self._single_write(
            run_id,
            "Campaigns",
            "delete",
            object_id,
            {},
            operation_key,
        )

    def adgroups_add(
        self,
        run_id: str,
        operation_key: str,
        ad_group: Mapping[str, Any],
    ) -> Tuple[CreatedDirectObject, ...]:
        return self._invoke(
            run_id,
            operation_key,
            "AdGroups",
            "add",
            ad_group,
        ).created_objects

    def adgroups_get(
        self,
        run_id: str,
        object_ids: Any,
    ) -> Tuple[Mapping[str, Any], ...]:
        return self._get(run_id, "AdGroups", object_ids)

    def adgroups_update(
        self,
        run_id: str,
        object_id: str,
        changes: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return self._single_write(run_id, "AdGroups", "update", object_id, changes)

    def adgroups_delete(
        self,
        run_id: str,
        object_id: str,
        operation_key: Optional[str] = None,
    ) -> Mapping[str, Any]:
        self._require_owned(run_id, "AdGroups", object_id, "delete")
        return self._single_write(
            run_id,
            "AdGroups",
            "delete",
            object_id,
            {},
            operation_key,
        )

    def ads_add(
        self,
        run_id: str,
        operation_key: str,
        ads: Mapping[str, Any],
    ) -> Tuple[CreatedDirectObject, ...]:
        return self._invoke(run_id, operation_key, "Ads", "add", ads).created_objects

    def ads_get(
        self,
        run_id: str,
        object_ids: Any,
    ) -> Tuple[Mapping[str, Any], ...]:
        return self._get(run_id, "Ads", object_ids)

    def ads_update(
        self,
        run_id: str,
        object_id: str,
        changes: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return self._single_write(run_id, "Ads", "update", object_id, changes)

    def ads_suspend(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_state(run_id, "Ads", object_id, {"ON"}, "suspend")
        return self._single_write(run_id, "Ads", "suspend", object_id, {})

    def ads_resume(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_state(
            run_id,
            "Ads",
            object_id,
            {"SUSPENDED", "MODERATION"},
            "resume",
        )
        return self._single_write(run_id, "Ads", "resume", object_id, {})

    def ads_archive(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_owned(run_id, "Ads", object_id, "archive")
        self._require_state(run_id, "Ads", object_id, {"SUSPENDED"}, "archive")
        return self._single_write(run_id, "Ads", "archive", object_id, {})

    def ads_unarchive(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_state(run_id, "Ads", object_id, {"ARCHIVED"}, "unarchive")
        return self._single_write(run_id, "Ads", "unarchive", object_id, {})

    def ads_moderate(
        self,
        run_id: str,
        object_ids: Iterable[str],
        operation_key: Optional[str] = None,
    ) -> Tuple[Mapping[str, Any], ...]:
        ids = self._normalize_ids(object_ids)
        for object_id in ids:
            self._require_state(run_id, "Ads", object_id, {"DRAFT"}, "moderate")
        result = self._invoke(
            run_id,
            operation_key
            or self._operation_key(run_id, "Ads", "moderate", ids),
            "Ads",
            "moderate",
            {"ids": list(ids)},
        )
        return result.readback

    def ads_delete(
        self,
        run_id: str,
        object_id: str,
        operation_key: Optional[str] = None,
    ) -> Mapping[str, Any]:
        self._require_owned(run_id, "Ads", object_id, "delete")
        self._require_state(
            run_id,
            "Ads",
            object_id,
            {"DRAFT", "MODERATION", "SUSPENDED", "ARCHIVED"},
            "delete",
        )
        return self._single_write(
            run_id,
            "Ads",
            "delete",
            object_id,
            {},
            operation_key,
        )

    def keywords_add(
        self,
        run_id: str,
        operation_key: str,
        keyword: Mapping[str, Any],
    ) -> Tuple[CreatedDirectObject, ...]:
        return self._invoke(
            run_id,
            operation_key,
            "Keywords",
            "add",
            keyword,
        ).created_objects

    def keywords_get(
        self,
        run_id: str,
        object_ids: Any,
    ) -> Tuple[Mapping[str, Any], ...]:
        return self._get(run_id, "Keywords", object_ids)

    def keywords_update(
        self,
        run_id: str,
        object_id: str,
        changes: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return self._single_write(run_id, "Keywords", "update", object_id, changes)

    def keywords_suspend(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_state(run_id, "Keywords", object_id, {"ON"}, "suspend")
        return self._single_write(run_id, "Keywords", "suspend", object_id, {})

    def keywords_resume(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_state(run_id, "Keywords", object_id, {"SUSPENDED"}, "resume")
        return self._single_write(run_id, "Keywords", "resume", object_id, {})

    def keywords_delete(
        self,
        run_id: str,
        object_id: str,
        operation_key: Optional[str] = None,
    ) -> Mapping[str, Any]:
        self._require_owned(run_id, "Keywords", object_id, "delete")
        self._require_state(run_id, "Keywords", object_id, {"SUSPENDED"}, "delete")
        return self._single_write(
            run_id,
            "Keywords",
            "delete",
            object_id,
            {},
            operation_key,
        )

    def keyword_bids_get(
        self,
        run_id: str,
        keyword_id: str,
    ) -> Tuple[Mapping[str, Any], ...]:
        return self._get(run_id, "KeywordBids", keyword_id)

    def keyword_bids_set(
        self,
        run_id: str,
        keyword_id: str,
        changes: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return self._single_write(
            run_id,
            "KeywordBids",
            "set",
            keyword_id,
            changes,
        )

    def _get(
        self,
        run_id: str,
        service: str,
        object_ids: Any,
    ) -> Tuple[Mapping[str, Any], ...]:
        ids = self._normalize_ids(object_ids)
        result = self._invoke(
            run_id,
            self._operation_key(run_id, service, "get", ids),
            service,
            "get",
            {"ids": list(ids)},
        )
        return result.readback

    def _single_write(
        self,
        run_id: str,
        service: str,
        method: str,
        object_id: str,
        changes: Mapping[str, Any],
        operation_key: Optional[str] = None,
    ) -> Mapping[str, Any]:
        payload = {"id": object_id, "changes": copy.deepcopy(dict(changes))}
        result = self._invoke(
            run_id,
            operation_key
            or self._operation_key(run_id, service, method, (object_id,)),
            service,
            method,
            payload,
        )
        if not result.readback:
            return {}
        return result.readback[0]

    def _invoke(
        self,
        run_id: str,
        operation_key: str,
        service: DirectService,
        method: DirectMethod,
        payload: Mapping[str, Any],
    ) -> DirectMethodResult:
        typed_service = DirectService(service)
        typed_method = DirectMethod(method)
        if (typed_service.value, typed_method.value) not in self._allowed:
            raise DirectStateTransitionRejected(
                "DIRECT_METHOD_NOT_ALLOWLISTED: "
                + typed_service.value
                + "."
                + typed_method.value
            )
        saga_operation = self._operation_belongs_to_active_saga(
            run_id,
            operation_key,
        )
        object_ids = self._request_object_ids(typed_method, payload)
        if typed_method != DirectMethod.ADD:
            ownership_service = (
                DirectService.KEYWORDS.value
                if typed_service == DirectService.KEYWORD_BIDS
                else typed_service.value
            )
            for object_id in object_ids:
                self._require_owned(
                    run_id,
                    ownership_service,
                    object_id,
                    typed_method.value,
                )
            if (
                not saga_operation
                and operation_key
                != self._operation_key(
                    run_id,
                    typed_service.value,
                    typed_method.value,
                    object_ids,
                )
            ):
                raise DirectStateTransitionRejected(
                    "DIRECT_OPERATION_PLAN_MISMATCH"
                )
        elif not operation_key:
            raise DirectStateTransitionRejected("DIRECT_OPERATION_PLAN_MISMATCH")
        production = self._require_adapter_authority()
        request = DirectMethodRequest(
            run_id=run_id,
            operation_key=operation_key,
            service=typed_service,
            method=typed_method,
            payload=copy.deepcopy(dict(payload)),
        )
        if typed_method != DirectMethod.GET:
            claimed = self._authorize_write(request)
            if not claimed and production:
                raise DirectStateTransitionRejected(
                    "DIRECT_OPERATION_PLAN_MISMATCH"
                )
        result = self._adapter.invoke(request)
        if result.service != typed_service or result.method != typed_method:
            raise DirectStateTransitionRejected("DIRECT_RESPONSE_TYPE_MISMATCH")
        return result

    def _require_adapter_authority(self) -> bool:
        if type(self._adapter) is FakeDirectManagementAdapter:
            return False
        pilot = self._policy["bindings"]["pilot"]
        record = self._policy["record"]
        authority = self._authority
        if (
            record.get("production_write_authorized") is not True
            or authority is None
            or not authority.armed
            or not authority.approval_id
            or not authority.proposal_id
            or not authority.execution_key
            or not authority.binding_hash.startswith("sha256:")
            or authority.credential_profile != "DIRECT_PILOT_WRITE"
            or pilot.get("direct_account") != authority.account
            or pilot.get("single_writer") is None
            or not self._registry.production_authority_is_valid(authority)
        ):
            raise DirectStateTransitionRejected(
                "PRODUCTION_CONNECTOR_DISABLED: validated pilot authority is absent."
            )
        if (
            self._write_boundary is None
            or self._trusted_scope is None
            or self._trusted_scope.account != authority.account
            or self._write_boundary.simulation_only
        ):
            raise DirectStateTransitionRejected(
                "DURABLE_DISPATCH_GUARD_REQUIRED"
            )
        return True

    def _operation_belongs_to_active_saga(
        self,
        run_id: str,
        operation_key: str,
    ) -> bool:
        checker = getattr(
            self._registry,
            "operation_belongs_to_active_saga",
            None,
        )
        return bool(
            checker is not None
            and checker(run_id, operation_key)
        )

    def _claim_direct_operation(
        self,
        request: DirectMethodRequest,
        final_check: Callable[[], None],
    ) -> bool:
        claim = getattr(self._registry, "claim_direct_operation", None)
        if claim is None:
            return False
        return bool(
            claim(
                request,
                self._authority,
                self._clock(),
                final_check,
            )
        )

    def _authorize_write(self, request: DirectMethodRequest) -> bool:
        if self._write_boundary is None or self._trusted_scope is None:
            raise DirectStateTransitionRejected(
                "DURABLE_DISPATCH_GUARD_REQUIRED"
            )
        try:
            return bool(
                self._write_boundary.authorize(
                    request.operation_key,
                    ":".join(
                        (
                            request.run_id,
                            request.service.value,
                            request.method.value,
                        )
                    ),
                    self._trusted_scope,
                    final_check=lambda: self._claim_direct_operation(
                        request,
                        lambda: self._write_boundary.require_dispatch_allowed(
                            self._trusted_scope
                        ),
                    ),
                )
            )
        except (AuditWriteBlocked, ControlRejected, RuntimeError) as error:
            cancel = getattr(
                self._registry,
                "cancel_direct_operation_claim",
                None,
            )
            if cancel is not None:
                cancel(request)
            raise DirectStateTransitionRejected(str(error)) from error

    def _require_owned(
        self,
        run_id: str,
        service: str,
        object_id: str,
        operation: str,
    ) -> None:
        if not self._registry.object_belongs_to_run(run_id, service, object_id):
            raise DirectStateTransitionRejected(
                "RUN_OWNERSHIP_REQUIRED: "
                + service
                + "."
                + operation
                + " is limited to current-run objects."
            )

    def _require_state(
        self,
        run_id: str,
        service: str,
        object_id: str,
        allowed_states: set[DirectState],
        operation: str,
    ) -> None:
        ownership_service = (
            "Keywords" if service == "KeywordBids" else service
        )
        self._require_owned(run_id, ownership_service, object_id, operation)
        self._require_adapter_authority()
        state = self._adapter.inspect(service, object_id).get("state")
        if DirectState(state) not in allowed_states:
            raise DirectStateTransitionRejected(
                "INVALID_DIRECT_STATE_TRANSITION: "
                + service
                + "."
                + operation
                + " from "
                + str(state)
            )

    def preflight_add(
        self,
        run_id: str,
        operation_key: str,
        service: str,
    ) -> None:
        typed_service = DirectService(service)
        if (typed_service.value, DirectMethod.ADD.value) not in self._allowed:
            raise DirectStateTransitionRejected(
                "DIRECT_METHOD_NOT_ALLOWLISTED: "
                + typed_service.value
                + ".add"
            )
        if not run_id or not operation_key:
            raise DirectStateTransitionRejected("DIRECT_OPERATION_PLAN_MISMATCH")
        self._require_adapter_authority()
        assert self._write_boundary is not None
        assert self._trusted_scope is not None
        try:
            self._write_boundary.require_dispatch_allowed(self._trusted_scope)
        except ControlRejected as error:
            raise DirectStateTransitionRejected(str(error)) from error

    def reconcile(
        self,
        request: DirectMethodRequest,
    ) -> DirectReconciliationResult:
        reconcile = getattr(self._adapter, "reconcile", None)
        if reconcile is None:
            return DirectReconciliationResult("UNKNOWN_RESULT", None)
        result = reconcile(request.operation_key)
        if result is None:
            return DirectReconciliationResult("UNKNOWN_RESULT", None)
        if result.service != request.service or result.method != request.method:
            raise DirectStateTransitionRejected("DIRECT_RESPONSE_TYPE_MISMATCH")
        return DirectReconciliationResult("APPLIED", result)

    @staticmethod
    def _request_object_ids(
        method: DirectMethod,
        payload: Mapping[str, Any],
    ) -> Tuple[str, ...]:
        if method == DirectMethod.ADD:
            return ()
        raw = (
            payload.get("ids")
            if method in {DirectMethod.GET, DirectMethod.MODERATE}
            else payload.get("id")
        )
        return DirectManagementConnectorV1._normalize_ids(raw)

    @staticmethod
    def _normalize_ids(value: Any) -> Tuple[str, ...]:
        if isinstance(value, str):
            ids = (value,)
        else:
            try:
                ids = tuple(value)
            except TypeError as error:
                raise DirectStateTransitionRejected(
                    "DIRECT_OBJECT_IDS_INVALID"
                ) from error
        if not ids or any(not isinstance(item, str) or not item for item in ids):
            raise DirectStateTransitionRejected("DIRECT_OBJECT_IDS_INVALID")
        return ids

    @staticmethod
    def _operation_key(
        run_id: str,
        service: str,
        method: str,
        object_ids: Sequence[str],
    ) -> str:
        return ":".join((run_id, service, method, ",".join(object_ids)))


class FakeDirectManagementAdapter:
    """In-memory Direct model used by all write-path and matrix tests."""

    is_fake = True

    def __init__(
        self,
        *,
        fail_on: Optional[Tuple[str, str]] = None,
        fail_compensation_on: Optional[Tuple[str, str]] = None,
        timeout_after: Optional[Tuple[str, str]] = None,
        actual_type_overrides: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.fail_on = fail_on
        self.fail_compensation_on = fail_compensation_on
        self.timeout_after = timeout_after
        self.actual_type_overrides = dict(actual_type_overrides or {})
        self.calls: List[Tuple[str, str, Mapping[str, Any]]] = []
        self._objects: Dict[Tuple[DirectService, str], Dict[str, Any]] = {}
        self._sequence: Dict[str, int] = {}
        self._idempotent_results: Dict[str, DirectMethodResult] = {}
        self._timed_out_keys: set[str] = set()
        self._evidence: List[Mapping[str, Any]] = []

    def invoke(self, request: DirectMethodRequest) -> DirectMethodResult:
        if request.operation_key in self._idempotent_results:
            return self._idempotent_results[request.operation_key]
        self.calls.append(
            (
                request.service,
                request.method,
                copy.deepcopy(dict(request.payload)),
            )
        )
        self.calls[-1] = (
            request.service.value,
            request.method.value,
            self.calls[-1][2],
        )
        operation = (request.service.value, request.method.value)
        if operation == self.fail_on:
            raise DirectAdapterFailure(
                "FAKE_DIRECT_OPERATION_FAILED: "
                + request.service.value
                + "."
                + request.method.value
            )
        if (
            operation == self.fail_compensation_on
            and request.method == DirectMethod.DELETE
        ):
            raise DirectAdapterFailure(
                "FAKE_DIRECT_COMPENSATION_FAILED: " + request.service.value
            )
        result = self._apply(request)
        if request.method != DirectMethod.GET:
            self._idempotent_results[request.operation_key] = result
        self._evidence.append(
            {
                "fixture_id": (
                    "DIRECT_"
                    + request.service.value.upper()
                    + "_"
                    + request.method.value.upper()
                ),
                "run_id": request.run_id,
                "operation_key": request.operation_key,
                "service": request.service.value,
                "method": request.method.value,
                "request": copy.deepcopy(dict(request.payload)),
                "response": {
                    "created_objects": [
                        {
                            "service": item.service.value,
                            "object_id": item.object_id,
                            "actual_type": item.actual_type,
                        }
                        for item in result.created_objects
                    ],
                    "readback": [
                        copy.deepcopy(dict(item)) for item in result.readback
                    ],
                },
                "deletion_confirmed": (
                    request.method == DirectMethod.DELETE
                    and not result.readback
                ),
            }
        )
        if operation == self.timeout_after and request.operation_key not in self._timed_out_keys:
            self._timed_out_keys.add(request.operation_key)
            raise DirectOutcomeUnknown(
                "FAKE_DIRECT_OUTCOME_UNKNOWN: "
                + request.service.value
                + "."
                + request.method.value
            )
        return result

    def reconcile(self, operation_key: str) -> Optional[DirectMethodResult]:
        return self._idempotent_results.get(operation_key)

    def evidence_records(self) -> Tuple[Mapping[str, Any], ...]:
        return tuple(copy.deepcopy(self._evidence))

    def inspect(self, service: str, object_id: str) -> Mapping[str, Any]:
        typed_service = DirectService(service)
        effective_service = (
            DirectService.KEYWORDS
            if typed_service == DirectService.KEYWORD_BIDS
            else typed_service
        )
        try:
            return copy.deepcopy(self._objects[(effective_service, object_id)])
        except KeyError as error:
            raise DirectStateTransitionRejected(
                "DIRECT_OBJECT_NOT_FOUND: "
                + typed_service.value
                + ":"
                + object_id
            ) from error

    def seed_object(self, service: str, value: Mapping[str, Any]) -> str:
        typed_service = DirectService(service)
        object_id = self._next_id(typed_service)
        stored = copy.deepcopy(dict(value))
        stored["id"] = object_id
        self._objects[(typed_service, object_id)] = stored
        return object_id

    def set_state(self, service: str, object_id: str, state: str) -> None:
        self._objects[(DirectService(service), object_id)]["state"] = DirectState(
            state
        ).value

    def mutate_object(
        self,
        service: str,
        object_id: str,
        changes: Mapping[str, Any],
    ) -> None:
        self._objects[(DirectService(service), object_id)].update(
            copy.deepcopy(dict(changes))
        )

    def operation_count(self, service: str, method: str) -> int:
        return sum(1 for called_service, called_method, _ in self.calls if (
            called_service,
            called_method,
        ) == (service, method))

    def object_ids(self) -> Tuple[str, ...]:
        return tuple(sorted(object_id for _, object_id in self._objects))

    def _apply(self, request: DirectMethodRequest) -> DirectMethodResult:
        handlers = {
            DirectMethod.ADD: self._add,
            DirectMethod.GET: self._read,
            DirectMethod.DELETE: self._delete,
            DirectMethod.UPDATE: self._update,
            DirectMethod.SET: self._update,
            DirectMethod.SUSPEND: self._transition,
            DirectMethod.RESUME: self._transition,
            DirectMethod.ARCHIVE: self._transition,
            DirectMethod.UNARCHIVE: self._transition,
            DirectMethod.MODERATE: self._transition,
        }
        try:
            return handlers[request.method](request)
        except KeyError as error:
            raise DirectAdapterFailure(
                "Unsupported fake Direct operation."
            ) from error

    def _delete(self, request: DirectMethodRequest) -> DirectMethodResult:
        object_id = str(request.payload["id"])
        effective_service = (
            DirectService.KEYWORDS
            if request.service == DirectService.KEYWORD_BIDS
            else request.service
        )
        self._objects.pop((effective_service, object_id), None)
        return self._result(request, readback=())

    def _add(self, request: DirectMethodRequest) -> DirectMethodResult:
        if request.service == DirectService.ADS:
            raw_items = request.payload.get("items")
            if not isinstance(raw_items, list):
                raw_items = [request.payload]
        else:
            raw_items = [request.payload]
        created = []
        for raw in raw_items:
            object_id = self._next_id(request.service)
            if request.service == DirectService.CAMPAIGNS:
                actual_type = str(
                    raw.get("type", DirectObjectType.UNIFIED_CAMPAIGN.value)
                )
                state = str(raw.get("state", "SUSPENDED"))
            elif request.service == DirectService.AD_GROUPS:
                actual_type = DirectObjectType.UNIFIED_AD_GROUP.value
                state = "ON"
            elif request.service == DirectService.ADS:
                actual_type = DirectObjectType.TEXT_AD.value
                state = "DRAFT"
            elif request.service == DirectService.KEYWORDS:
                actual_type = DirectObjectType.KEYWORD.value
                state = "SUSPENDED"
            else:
                raise DirectAdapterFailure("Unsupported fake add service.")
            actual_type = self.actual_type_overrides.get(
                request.service.value,
                actual_type,
            )
            stored = copy.deepcopy(dict(raw))
            if request.service == DirectService.ADS:
                stored["ad_group_id"] = request.payload["ad_group_id"]
            stored.update(
                {
                    "id": object_id,
                    "type": actual_type,
                    "state": state,
                }
            )
            self._objects[(request.service, object_id)] = stored
            created.append(
                CreatedDirectObject(
                    service=request.service,
                    object_id=object_id,
                    actual_type=actual_type,
                )
            )
        readback = tuple(
            self.inspect(request.service, item.object_id) for item in created
        )
        return self._result(
            request,
            created=tuple(created),
            readback=readback,
        )

    def _read(self, request: DirectMethodRequest) -> DirectMethodResult:
        readback = tuple(
            self.inspect(request.service, str(object_id))
            for object_id in request.payload["ids"]
        )
        return self._result(request, readback=readback)

    def _update(self, request: DirectMethodRequest) -> DirectMethodResult:
        object_id = str(request.payload["id"])
        effective_service = (
            DirectService.KEYWORDS
            if request.service == DirectService.KEYWORD_BIDS
            else request.service
        )
        value = self._objects[(effective_service, object_id)]
        value.update(copy.deepcopy(dict(request.payload["changes"])))
        return self._result(request, readback=(copy.deepcopy(value),))

    def _transition(self, request: DirectMethodRequest) -> DirectMethodResult:
        ids = (
            tuple(str(item) for item in request.payload["ids"])
            if request.method == DirectMethod.MODERATE
            else (str(request.payload["id"]),)
        )
        states = {
            DirectMethod.SUSPEND: DirectState.SUSPENDED.value,
            DirectMethod.RESUME: DirectState.ON.value,
            DirectMethod.ARCHIVE: DirectState.ARCHIVED.value,
            DirectMethod.UNARCHIVE: DirectState.SUSPENDED.value,
            DirectMethod.MODERATE: DirectState.MODERATION.value,
        }
        readback = []
        for object_id in ids:
            value = self._objects[(request.service, object_id)]
            value["state"] = states[request.method]
            readback.append(copy.deepcopy(value))
        return self._result(request, readback=tuple(readback))

    def _next_id(self, service: DirectService) -> str:
        next_value = self._sequence.get(service.value, 0) + 1
        self._sequence[service.value] = next_value
        return service.value.lower() + "-" + str(next_value)

    @staticmethod
    def _result(
        request: DirectMethodRequest,
        *,
        created: Tuple[CreatedDirectObject, ...] = (),
        readback: Tuple[Mapping[str, Any], ...] = (),
    ) -> DirectMethodResult:
        return DirectMethodResult(
            service=request.service,
            method=request.method,
            created_objects=created,
            readback=readback,
        )
