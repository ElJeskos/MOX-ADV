"""Small dependency-free consumer of the published module HTTP contract."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Tuple
from urllib import error, request


class OpenApiContractError(ValueError):
    """The supplied OpenAPI document is not a compatible module API v1."""


class ModuleTransportError(RuntimeError):
    """The module endpoint did not return a usable JSON result envelope."""


@dataclass(frozen=True)
class TypedModuleErrorV1:
    code: str
    message: str
    field: Optional[str]
    retryable: bool

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TypedModuleErrorV1":
        code = value.get("code")
        message = value.get("message")
        field = value.get("field")
        retryable = value.get("retryable")
        if not isinstance(code, str) or not code:
            raise ModuleTransportError("Module error code must be a non-empty string.")
        if not isinstance(message, str) or not message:
            raise ModuleTransportError(
                "Module error message must be a non-empty string."
            )
        if field is not None and not isinstance(field, str):
            raise ModuleTransportError("Module error field must be a string or null.")
        if not isinstance(retryable, bool):
            raise ModuleTransportError("Module error retryable must be a boolean.")
        return cls(
            code=code,
            message=message,
            field=field,
            retryable=retryable,
        )


@dataclass(frozen=True)
class ModuleResultEnvelopeV1:
    schema_version: str
    run_id: str
    module_id: str
    module_version: str
    status: str
    metrics: Tuple[Mapping[str, Any], ...]
    assessment: Optional[Mapping[str, Any]]
    recommendations: Tuple[Mapping[str, Any], ...]
    provenance: Tuple[Mapping[str, Any], ...]
    warnings: Tuple[Mapping[str, Any], ...]
    errors: List[TypedModuleErrorV1]
    proposal: Optional[Mapping[str, Any]]
    execution_result: Optional[Mapping[str, Any]]
    decision_record_ref: Optional[str]
    body: Mapping[str, Any]

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        expected_schema_version: str,
    ) -> "ModuleResultEnvelopeV1":
        schema_version = value.get("schema_version")
        if schema_version != expected_schema_version:
            raise ModuleTransportError(
                "Expected result schema "
                + expected_schema_version
                + ", received "
                + repr(schema_version)
                + "."
            )
        run_id = value.get("run_id")
        module = value.get("module")
        status = value.get("status")
        metrics = _object_array(value.get("metrics"), "metrics")
        assessment = _optional_object(
            value.get("assessment"),
            "assessment",
        )
        recommendations = _object_array(
            value.get("recommendations"),
            "recommendations",
        )
        provenance = _object_array(value.get("provenance"), "provenance")
        warnings = _object_array(value.get("warnings"), "warnings")
        raw_errors = value.get("errors")
        proposal = _optional_object(value.get("proposal"), "proposal")
        execution_result = _optional_object(
            value.get("execution_result"),
            "execution_result",
        )
        decision_record_ref = value.get("decision_record_ref")
        if not isinstance(run_id, str) or not run_id:
            raise ModuleTransportError("Module result run_id is missing.")
        if not isinstance(module, Mapping):
            raise ModuleTransportError("Module result identity is missing.")
        module_id = module.get("module_id")
        module_version = module.get("module_version")
        if not isinstance(module_id, str) or not module_id:
            raise ModuleTransportError("Module result module_id is missing.")
        if not isinstance(module_version, str) or not module_version:
            raise ModuleTransportError("Module result module_version is missing.")
        if status not in {
            "SUCCEEDED",
            "PARTIAL",
            "BLOCKED",
            "REJECTED",
            "FAILED",
        }:
            raise ModuleTransportError("Module result status is unsupported.")
        if not isinstance(raw_errors, list):
            raise ModuleTransportError("Module result errors must be an array.")
        if decision_record_ref is not None and not isinstance(
            decision_record_ref,
            str,
        ):
            raise ModuleTransportError(
                "Module result decision_record_ref must be a string or null."
            )
        if proposal is not None and execution_result is not None:
            raise ModuleTransportError(
                "Module result cannot contain proposal and execution_result."
            )
        parsed_errors = [
            TypedModuleErrorV1.from_dict(item)
            for item in raw_errors
            if isinstance(item, Mapping)
        ]
        if len(parsed_errors) != len(raw_errors):
            raise ModuleTransportError(
                "Module result errors must contain JSON objects."
            )
        if status in {"BLOCKED", "REJECTED", "FAILED"} and not parsed_errors:
            raise ModuleTransportError(
                "A non-successful module result must contain a typed error."
            )
        return cls(
            schema_version=schema_version,
            run_id=run_id,
            module_id=module_id,
            module_version=module_version,
            status=status,
            metrics=metrics,
            assessment=assessment,
            recommendations=recommendations,
            provenance=provenance,
            warnings=warnings,
            errors=parsed_errors,
            proposal=proposal,
            execution_result=execution_result,
            decision_record_ref=decision_record_ref,
            body=dict(value),
        )


def _object_array(
    value: Any,
    field: str,
) -> Tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        raise ModuleTransportError("Module result " + field + " must be an array.")
    objects = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ModuleTransportError(
                "Module result " + field + " must contain JSON objects."
            )
        objects.append(dict(item))
    return tuple(objects)


def _optional_object(
    value: Any,
    field: str,
) -> Optional[Mapping[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ModuleTransportError(
            "Module result " + field + " must be an object or null."
        )
    return dict(value)


class ModuleHttpClientV1:
    """Invoke one standalone module at the path published by OpenAPI."""

    def __init__(
        self,
        *,
        endpoint: str,
        request_schema_version: str,
        result_schema_version: str,
        timeout_seconds: float = 5.0,
        max_attempts: int = 2,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one.")
        self._endpoint = endpoint
        self._request_schema_version = request_schema_version
        self._result_schema_version = result_schema_version
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts

    @classmethod
    def from_openapi(
        cls,
        *,
        base_url: str,
        document: Mapping[str, Any],
        timeout_seconds: float = 5.0,
        max_attempts: int = 2,
    ) -> "ModuleHttpClientV1":
        try:
            openapi_version = document["openapi"]
            api_version = document["info"]["version"]
            operation = document["paths"]["/v1/runs"]["post"]
            request_version = document["components"]["schemas"][
                "ModuleRequestV1"
            ]["properties"]["schema_version"]["const"]
            result_version = document["components"]["schemas"][
                "ModuleResultV1"
            ]["properties"]["schema_version"]["const"]
        except (KeyError, TypeError) as contract_error:
            raise OpenApiContractError(
                "OpenAPI does not publish the module v1 request/result seam."
            ) from contract_error
        if not isinstance(openapi_version, str) or not openapi_version.startswith(
            "3.1."
        ):
            raise OpenApiContractError("OpenAPI 3.1.x is required.")
        if not isinstance(api_version, str) or api_version.split(".", 1)[0] != "1":
            raise OpenApiContractError("Module API major version 1 is required.")
        if operation.get("operationId") != "invokeModuleV1":
            raise OpenApiContractError("The module v1 operation is unavailable.")
        if request_version != "module-request-v1":
            raise OpenApiContractError("ModuleRequestV1 is incompatible.")
        if result_version != "module-result-v1":
            raise OpenApiContractError("ModuleResultV1 is incompatible.")
        return cls(
            endpoint=base_url.rstrip("/") + "/v1/runs",
            request_schema_version=request_version,
            result_schema_version=result_version,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )

    def invoke(self, payload: Mapping[str, Any]) -> ModuleResultEnvelopeV1:
        if payload.get("schema_version") != self._request_schema_version:
            raise OpenApiContractError(
                "Request must use " + self._request_schema_version + "."
            )
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        maximum_attempts = self._maximum_attempts_for(payload)
        last_transport_error: Optional[BaseException] = None
        for attempt in range(1, maximum_attempts + 1):
            try:
                status_code, response_body = self._post(encoded)
                result = self._parse_result(response_body)
                if (
                    status_code >= 500
                    and any(item.retryable for item in result.errors)
                    and attempt < maximum_attempts
                ):
                    continue
                return result
            except (error.URLError, socket.timeout, TimeoutError) as transport_error:
                last_transport_error = transport_error
                if attempt == maximum_attempts:
                    break
        raise ModuleTransportError(
            "The module endpoint was unavailable after "
            + str(maximum_attempts)
            + " attempt(s)."
        ) from last_transport_error

    def _maximum_attempts_for(self, payload: Mapping[str, Any]) -> int:
        operation = payload.get("operation")
        if isinstance(operation, Mapping) and operation.get("kind") == "EXECUTE":
            return 1
        return self._max_attempts

    def _post(self, encoded: bytes) -> tuple[int, bytes]:
        http_request = request.Request(
            self._endpoint,
            data=encoded,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(
                http_request,
                timeout=self._timeout_seconds,
            ) as response:
                return response.status, response.read()
        except error.HTTPError as http_error:
            return http_error.code, http_error.read()

    def _parse_result(self, body: bytes) -> ModuleResultEnvelopeV1:
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as parse_error:
            raise ModuleTransportError(
                "The module endpoint did not return JSON."
            ) from parse_error
        if not isinstance(value, Mapping):
            raise ModuleTransportError(
                "The module endpoint did not return a JSON object."
            )
        return ModuleResultEnvelopeV1.from_dict(
            value,
            expected_schema_version=self._result_schema_version,
        )
