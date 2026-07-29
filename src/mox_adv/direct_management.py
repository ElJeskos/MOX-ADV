"""Typed Yandex Direct management boundary with a socket-free fake adapter."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple


class DirectStateTransitionRejected(RuntimeError):
    """A management request failed before reaching the adapter."""


class DirectAdapterFailure(RuntimeError):
    """The fake adapter injected a definite operation failure."""


class DirectOutcomeUnknown(RuntimeError):
    """The adapter outcome cannot be determined without reconciliation."""


@dataclass(frozen=True)
class CreatedDirectObject:
    service: str
    object_id: str
    actual_type: str


@dataclass(frozen=True)
class DirectMethodRequest:
    run_id: str
    operation_key: str
    service: str
    method: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class DirectMethodResult:
    service: str
    method: str
    created_objects: Tuple[CreatedDirectObject, ...]
    readback: Tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class ProductionPilotAuthority:
    account: str
    credential_profile: str
    approval_id: str
    armed: bool


class DirectManagementAdapter(Protocol):
    is_fake: bool

    def invoke(self, request: DirectMethodRequest) -> DirectMethodResult: ...

    def inspect(self, service: str, object_id: str) -> Mapping[str, Any]: ...


class RunObjectRegistry(Protocol):
    def object_belongs_to_run(
        self,
        run_id: str,
        service: str,
        object_id: str,
    ) -> bool: ...


class DirectManagementConnectorV1:
    """Expose every FR-002 Direct operation as an explicit typed method."""

    def __init__(
        self,
        policy: Mapping[str, Any],
        adapter: DirectManagementAdapter,
        registry: RunObjectRegistry,
        authority: Optional[ProductionPilotAuthority] = None,
    ) -> None:
        self._policy = policy
        self._adapter = adapter
        self._registry = registry
        self._authority = authority
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
        self._require_state("Campaigns", object_id, {"ON"}, "suspend")
        return self._single_write(run_id, "Campaigns", "suspend", object_id, {})

    def campaigns_resume(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_state("Campaigns", object_id, {"SUSPENDED"}, "resume")
        return self._single_write(run_id, "Campaigns", "resume", object_id, {})

    def campaigns_archive(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_owned(run_id, "Campaigns", object_id, "archive")
        self._require_state("Campaigns", object_id, {"SUSPENDED"}, "archive")
        return self._single_write(run_id, "Campaigns", "archive", object_id, {})

    def campaigns_unarchive(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_state("Campaigns", object_id, {"ARCHIVED"}, "unarchive")
        return self._single_write(run_id, "Campaigns", "unarchive", object_id, {})

    def campaigns_delete(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_owned(run_id, "Campaigns", object_id, "delete")
        self._require_state(
            "Campaigns",
            object_id,
            {"SUSPENDED", "ARCHIVED"},
            "delete",
        )
        return self._single_write(run_id, "Campaigns", "delete", object_id, {})

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

    def adgroups_delete(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_owned(run_id, "AdGroups", object_id, "delete")
        return self._single_write(run_id, "AdGroups", "delete", object_id, {})

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
        self._require_state("Ads", object_id, {"ON"}, "suspend")
        return self._single_write(run_id, "Ads", "suspend", object_id, {})

    def ads_resume(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_state("Ads", object_id, {"SUSPENDED", "MODERATION"}, "resume")
        return self._single_write(run_id, "Ads", "resume", object_id, {})

    def ads_archive(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_owned(run_id, "Ads", object_id, "archive")
        self._require_state("Ads", object_id, {"SUSPENDED"}, "archive")
        return self._single_write(run_id, "Ads", "archive", object_id, {})

    def ads_unarchive(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_state("Ads", object_id, {"ARCHIVED"}, "unarchive")
        return self._single_write(run_id, "Ads", "unarchive", object_id, {})

    def ads_moderate(
        self,
        run_id: str,
        object_ids: Iterable[str],
    ) -> Tuple[Mapping[str, Any], ...]:
        ids = self._normalize_ids(object_ids)
        for object_id in ids:
            self._require_state("Ads", object_id, {"DRAFT"}, "moderate")
        result = self._invoke(
            run_id,
            self._operation_key(run_id, "Ads", "moderate", ids),
            "Ads",
            "moderate",
            {"ids": list(ids)},
        )
        return result.readback

    def ads_delete(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_owned(run_id, "Ads", object_id, "delete")
        self._require_state(
            "Ads",
            object_id,
            {"DRAFT", "MODERATION", "SUSPENDED", "ARCHIVED"},
            "delete",
        )
        return self._single_write(run_id, "Ads", "delete", object_id, {})

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
        self._require_state("Keywords", object_id, {"ON"}, "suspend")
        return self._single_write(run_id, "Keywords", "suspend", object_id, {})

    def keywords_resume(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_state("Keywords", object_id, {"SUSPENDED"}, "resume")
        return self._single_write(run_id, "Keywords", "resume", object_id, {})

    def keywords_delete(self, run_id: str, object_id: str) -> Mapping[str, Any]:
        self._require_owned(run_id, "Keywords", object_id, "delete")
        self._require_state("Keywords", object_id, {"SUSPENDED"}, "delete")
        return self._single_write(run_id, "Keywords", "delete", object_id, {})

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
    ) -> Mapping[str, Any]:
        result = self._invoke(
            run_id,
            self._operation_key(run_id, service, method, (object_id,)),
            service,
            method,
            {"id": object_id, "changes": copy.deepcopy(dict(changes))},
        )
        if not result.readback:
            return {}
        return result.readback[0]

    def _invoke(
        self,
        run_id: str,
        operation_key: str,
        service: str,
        method: str,
        payload: Mapping[str, Any],
    ) -> DirectMethodResult:
        if (service, method) not in self._allowed:
            raise DirectStateTransitionRejected(
                "DIRECT_METHOD_NOT_ALLOWLISTED: " + service + "." + method
            )
        self._require_adapter_authority()
        result = self._adapter.invoke(
            DirectMethodRequest(
                run_id=run_id,
                operation_key=operation_key,
                service=service,
                method=method,
                payload=copy.deepcopy(dict(payload)),
            )
        )
        if result.service != service or result.method != method:
            raise DirectStateTransitionRejected("DIRECT_RESPONSE_TYPE_MISMATCH")
        return result

    def _require_adapter_authority(self) -> None:
        if getattr(self._adapter, "is_fake", False) is True:
            return
        pilot = self._policy["bindings"]["pilot"]
        record = self._policy["record"]
        authority = self._authority
        if (
            record.get("production_write_authorized") is not True
            or authority is None
            or not authority.armed
            or not authority.approval_id
            or authority.credential_profile != "DIRECT_PILOT_WRITE"
            or pilot.get("direct_account") != authority.account
            or pilot.get("single_writer") is None
        ):
            raise DirectStateTransitionRejected(
                "PRODUCTION_CONNECTOR_DISABLED: validated pilot authority is absent."
            )

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
        service: str,
        object_id: str,
        allowed_states: set[str],
        operation: str,
    ) -> None:
        self._require_adapter_authority()
        state = self._adapter.inspect(service, object_id).get("state")
        if state not in allowed_states:
            raise DirectStateTransitionRejected(
                "INVALID_DIRECT_STATE_TRANSITION: "
                + service
                + "."
                + operation
                + " from "
                + str(state)
            )

    @staticmethod
    def _normalize_ids(value: Any) -> Tuple[str, ...]:
        if isinstance(value, str):
            ids = (value,)
        else:
            ids = tuple(value)
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
    ) -> None:
        self.fail_on = fail_on
        self.fail_compensation_on = fail_compensation_on
        self.timeout_after = timeout_after
        self.calls: List[Tuple[str, str, Mapping[str, Any]]] = []
        self._objects: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._sequence: Dict[str, int] = {}
        self._idempotent_results: Dict[str, DirectMethodResult] = {}
        self._timed_out_keys: set[str] = set()

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
        operation = (request.service, request.method)
        if operation == self.fail_on:
            raise DirectAdapterFailure(
                "FAKE_DIRECT_OPERATION_FAILED: "
                + request.service
                + "."
                + request.method
            )
        if operation == self.fail_compensation_on and request.method == "delete":
            raise DirectAdapterFailure(
                "FAKE_DIRECT_COMPENSATION_FAILED: " + request.service
            )
        result = self._apply(request)
        if request.method == "add":
            self._idempotent_results[request.operation_key] = result
        if operation == self.timeout_after and request.operation_key not in self._timed_out_keys:
            self._timed_out_keys.add(request.operation_key)
            raise DirectOutcomeUnknown(
                "FAKE_DIRECT_OUTCOME_UNKNOWN: "
                + request.service
                + "."
                + request.method
            )
        return result

    def inspect(self, service: str, object_id: str) -> Mapping[str, Any]:
        effective_service = "Keywords" if service == "KeywordBids" else service
        try:
            return copy.deepcopy(self._objects[(effective_service, object_id)])
        except KeyError as error:
            raise DirectStateTransitionRejected(
                "DIRECT_OBJECT_NOT_FOUND: " + service + ":" + object_id
            ) from error

    def seed_object(self, service: str, value: Mapping[str, Any]) -> str:
        object_id = self._next_id(service)
        stored = copy.deepcopy(dict(value))
        stored["id"] = object_id
        self._objects[(service, object_id)] = stored
        return object_id

    def set_state(self, service: str, object_id: str, state: str) -> None:
        self._objects[(service, object_id)]["state"] = state

    def operation_count(self, service: str, method: str) -> int:
        return sum(1 for called_service, called_method, _ in self.calls if (
            called_service,
            called_method,
        ) == (service, method))

    def object_ids(self) -> Tuple[str, ...]:
        return tuple(sorted(object_id for _, object_id in self._objects))

    def _apply(self, request: DirectMethodRequest) -> DirectMethodResult:
        if request.method == "add":
            return self._add(request)
        if request.method == "get":
            return self._read(request)
        if request.method == "delete":
            object_id = str(request.payload["id"])
            effective_service = (
                "Keywords" if request.service == "KeywordBids" else request.service
            )
            self._objects.pop((effective_service, object_id), None)
            return self._result(request, readback=())
        if request.method in {"update", "set"}:
            return self._update(request)
        if request.method in {
            "suspend",
            "resume",
            "archive",
            "unarchive",
            "moderate",
        }:
            return self._transition(request)
        raise DirectAdapterFailure("Unsupported fake Direct operation.")

    def _add(self, request: DirectMethodRequest) -> DirectMethodResult:
        if request.service == "Ads":
            raw_items = request.payload.get("items")
            if not isinstance(raw_items, list):
                raw_items = [request.payload]
        else:
            raw_items = [request.payload]
        created = []
        for raw in raw_items:
            object_id = self._next_id(request.service)
            if request.service == "Campaigns":
                actual_type = str(raw.get("type", "UNIFIED_CAMPAIGN"))
                state = str(raw.get("state", "SUSPENDED"))
            elif request.service == "AdGroups":
                actual_type = "UNIFIED_AD_GROUP"
                state = "ON"
            elif request.service == "Ads":
                actual_type = "TEXT_AD"
                state = "DRAFT"
            elif request.service == "Keywords":
                actual_type = "KEYWORD"
                state = "SUSPENDED"
            else:
                raise DirectAdapterFailure("Unsupported fake add service.")
            stored = copy.deepcopy(dict(raw))
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
        return self._result(request, created=tuple(created))

    def _read(self, request: DirectMethodRequest) -> DirectMethodResult:
        readback = tuple(
            self.inspect(request.service, str(object_id))
            for object_id in request.payload["ids"]
        )
        return self._result(request, readback=readback)

    def _update(self, request: DirectMethodRequest) -> DirectMethodResult:
        object_id = str(request.payload["id"])
        effective_service = (
            "Keywords" if request.service == "KeywordBids" else request.service
        )
        value = self._objects[(effective_service, object_id)]
        value.update(copy.deepcopy(dict(request.payload["changes"])))
        return self._result(request, readback=(copy.deepcopy(value),))

    def _transition(self, request: DirectMethodRequest) -> DirectMethodResult:
        ids = (
            tuple(str(item) for item in request.payload["ids"])
            if request.method == "moderate"
            else (str(request.payload["id"]),)
        )
        states = {
            "suspend": "SUSPENDED",
            "resume": "ON",
            "archive": "ARCHIVED",
            "unarchive": "SUSPENDED",
            "moderate": "MODERATION",
        }
        readback = []
        for object_id in ids:
            value = self._objects[(request.service, object_id)]
            value["state"] = states[request.method]
            readback.append(copy.deepcopy(value))
        return self._result(request, readback=tuple(readback))

    def _next_id(self, service: str) -> str:
        next_value = self._sequence.get(service, 0) + 1
        self._sequence[service] = next_value
        return service.lower() + "-" + str(next_value)

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
