"""Version 1 request and result contracts for standalone and paired modules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


MODULE_REQUEST_SCHEMA_VERSION = "module-request-v1"
MODULE_RESULT_SCHEMA_VERSION = "module-result-v1"
EXTERNAL_EVIDENCE_SCHEMA_VERSION = "normalized-metrics-evidence-v1"
OPERATION_TYPES_BY_KIND = {
    "ANALYZE": (
        "ANALYZE_PERFORMANCE",
        "EVALUATE_IMPACT",
    ),
    "PLAN": (
        "PLAN_OPTIMIZATION",
        "CREATE_CAMPAIGN",
        "MANAGE_GOAL_CANDIDATE",
    ),
    "EXECUTE": (
        "APPLY_OPTIMIZATION",
        "CREATE_CAMPAIGN",
        "MANAGE_GOAL_CANDIDATE",
    ),
}

JsonScalar = Union[str, int, float, None]


class ContractValidationError(ValueError):
    """Raised when an object cannot cross the public module boundary."""


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field} must be an object")
    return value


def _array(value: Any, field: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractValidationError(f"{field} must be an array")
    return value


def _exact_fields(
    value: Mapping[str, Any],
    *,
    field: str,
    required: Sequence[str],
    optional: Sequence[str] = (),
) -> None:
    allowed = set(required) | set(optional)
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise ContractValidationError(
            f"{field} has unexpected field: {unexpected[0]}"
        )
    missing = sorted(set(required) - set(value))
    if missing:
        raise ContractValidationError(f"{field} is missing field: {missing[0]}")


def _text(
    value: Any,
    field: str,
    *,
    minimum: int = 1,
    maximum: int = 500,
) -> str:
    if not isinstance(value, str):
        raise ContractValidationError(f"{field} must be a string")
    if not minimum <= len(value) <= maximum:
        raise ContractValidationError(
            f"{field} length must be between {minimum} and {maximum}"
        )
    return value


def _optional_text(
    value: Any,
    field: str,
    *,
    maximum: int = 500,
) -> Optional[str]:
    if value is None:
        return None
    return _text(value, field, maximum=maximum)


def _one_of(value: Any, field: str, allowed: Sequence[str]) -> str:
    parsed = _text(value, field)
    if parsed not in allowed:
        raise ContractValidationError(
            f"{field} must be one of: {', '.join(allowed)}"
        )
    return parsed


def _iso_date(value: Any, field: str) -> str:
    parsed = _text(value, field)
    try:
        date.fromisoformat(parsed)
    except ValueError as error:
        raise ContractValidationError(f"{field} must be an ISO date") from error
    return parsed


def _timestamp(value: Any, field: str) -> str:
    parsed = _text(value, field)
    try:
        timestamp = datetime.fromisoformat(parsed.replace("Z", "+00:00"))
    except ValueError as error:
        raise ContractValidationError(
            f"{field} must be an ISO-8601 timestamp"
        ) from error
    if timestamp.tzinfo is None:
        raise ContractValidationError(f"{field} must include a UTC offset")
    return parsed


def _timezone(value: Any, field: str) -> str:
    parsed = _text(value, field)
    try:
        ZoneInfo(parsed)
    except ZoneInfoNotFoundError as error:
        raise ContractValidationError(
            f"{field} must name an IANA timezone"
        ) from error
    return parsed


@dataclass(frozen=True)
class StoredConnectionRefV1:
    connection_id: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StoredConnectionRefV1":
        _exact_fields(value, field="connection_ref", required=("connection_id",))
        return cls(
            connection_id=_text(
                value["connection_id"],
                "connection_ref.connection_id",
                maximum=128,
            )
        )

    def as_dict(self) -> Dict[str, Any]:
        return {"connection_id": self.connection_id}


@dataclass(frozen=True)
class ModuleScopeV1:
    organization_id: str
    account_id: Optional[str] = None
    campaign_id: Optional[str] = None
    counter_id: Optional[str] = None
    goal_id: Optional[str] = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModuleScopeV1":
        fields = (
            "account_id",
            "campaign_id",
            "counter_id",
            "goal_id",
        )
        _exact_fields(
            value,
            field="scope",
            required=("organization_id",),
            optional=fields,
        )
        resources = {
            name: _optional_text(value.get(name), f"scope.{name}", maximum=128)
            for name in fields
        }
        if not any(resources.values()):
            raise ContractValidationError(
                "scope must reference at least one provider resource"
            )
        return cls(
            organization_id=_text(
                value["organization_id"],
                "scope.organization_id",
                maximum=128,
            ),
            **resources,
        )

    def as_dict(self) -> Dict[str, Any]:
        value: Dict[str, Any] = {"organization_id": self.organization_id}
        for field in ("account_id", "campaign_id", "counter_id", "goal_id"):
            item = getattr(self, field)
            if item is not None:
                value[field] = item
        return value


@dataclass(frozen=True)
class ClosedPeriodV1:
    start_date: str
    end_date: str
    timezone: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClosedPeriodV1":
        _exact_fields(
            value,
            field="period",
            required=("start_date", "end_date", "timezone"),
        )
        start_date = _iso_date(value["start_date"], "period.start_date")
        end_date = _iso_date(value["end_date"], "period.end_date")
        if date.fromisoformat(end_date) < date.fromisoformat(start_date):
            raise ContractValidationError(
                "period.end_date must be on or after period.start_date"
            )
        return cls(
            start_date=start_date,
            end_date=end_date,
            timezone=_timezone(value["timezone"], "period.timezone"),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "timezone": self.timezone,
        }


@dataclass(frozen=True)
class ModuleObjectiveV1:
    code: str
    description: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModuleObjectiveV1":
        _exact_fields(
            value,
            field="objective",
            required=("code", "description"),
        )
        return cls(
            code=_text(value["code"], "objective.code", maximum=64),
            description=_text(
                value["description"],
                "objective.description",
                maximum=500,
            ),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "description": self.description}


@dataclass(frozen=True)
class MetricValueV1:
    name: str
    value: JsonScalar
    unit: str

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        field: str = "metric",
    ) -> "MetricValueV1":
        _exact_fields(
            value,
            field=field,
            required=("name", "value", "unit"),
        )
        metric_value = value["value"]
        if isinstance(metric_value, bool) or not (
            metric_value is None
            or isinstance(metric_value, (str, int, float))
        ):
            raise ContractValidationError(f"{field}.value must be a JSON scalar")
        return cls(
            name=_text(value["name"], f"{field}.name", maximum=128),
            value=metric_value,
            unit=_text(value["unit"], f"{field}.unit", maximum=32),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "value": self.value, "unit": self.unit}


@dataclass(frozen=True)
class ExternalEvidenceV1:
    schema_version: str
    evidence_id: str
    source: str
    observed_at: str
    watermark: str
    metrics: Tuple[MetricValueV1, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExternalEvidenceV1":
        _exact_fields(
            value,
            field="external_evidence",
            required=(
                "schema_version",
                "evidence_id",
                "source",
                "observed_at",
                "watermark",
                "metrics",
            ),
        )
        schema_version = _one_of(
            value["schema_version"],
            "external_evidence.schema_version",
            (EXTERNAL_EVIDENCE_SCHEMA_VERSION,),
        )
        metrics = tuple(
            MetricValueV1.from_dict(
                _object(item, f"external_evidence.metrics[{index}]"),
                field=f"external_evidence.metrics[{index}]",
            )
            for index, item in enumerate(
                _array(value["metrics"], "external_evidence.metrics")
            )
        )
        if not metrics:
            raise ContractValidationError(
                "external_evidence.metrics must not be empty"
            )
        return cls(
            schema_version=schema_version,
            evidence_id=_text(
                value["evidence_id"],
                "external_evidence.evidence_id",
                maximum=128,
            ),
            source=_one_of(
                value["source"],
                "external_evidence.source",
                ("CUSTOMER_ECOSYSTEM",),
            ),
            observed_at=_timestamp(
                value["observed_at"],
                "external_evidence.observed_at",
            ),
            watermark=_timestamp(
                value["watermark"],
                "external_evidence.watermark",
            ),
            metrics=metrics,
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "source": self.source,
            "observed_at": self.observed_at,
            "watermark": self.watermark,
            "metrics": [item.as_dict() for item in self.metrics],
        }


@dataclass(frozen=True)
class ModuleOperationV1:
    kind: str
    operation_type: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModuleOperationV1":
        _exact_fields(
            value,
            field="operation",
            required=("kind", "operation_type"),
        )
        kind = _one_of(
            value["kind"],
            "operation.kind",
            tuple(OPERATION_TYPES_BY_KIND),
        )
        return cls(
            kind=kind,
            operation_type=_one_of(
                value["operation_type"],
                "operation.operation_type",
                OPERATION_TYPES_BY_KIND[kind],
            ),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "operation_type": self.operation_type}


@dataclass(frozen=True)
class ModuleRequestV1:
    schema_version: str
    connection_ref: StoredConnectionRefV1
    environment: str
    scope: ModuleScopeV1
    period: ClosedPeriodV1
    objective: ModuleObjectiveV1
    external_evidence: Optional[ExternalEvidenceV1]
    operation: ModuleOperationV1
    idempotency_key: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModuleRequestV1":
        value = _object(value, "request")
        _exact_fields(
            value,
            field="request",
            required=(
                "schema_version",
                "connection_ref",
                "environment",
                "scope",
                "period",
                "objective",
                "operation",
                "idempotency_key",
            ),
            optional=("external_evidence",),
        )
        external_evidence = value.get("external_evidence")
        if "external_evidence" in value and external_evidence is None:
            raise ContractValidationError(
                "external_evidence must be an object when present"
            )
        return cls(
            schema_version=_one_of(
                value["schema_version"],
                "schema_version",
                (MODULE_REQUEST_SCHEMA_VERSION,),
            ),
            connection_ref=StoredConnectionRefV1.from_dict(
                _object(value["connection_ref"], "connection_ref")
            ),
            environment=_one_of(
                value["environment"],
                "environment",
                ("PRODUCTION", "TEST"),
            ),
            scope=ModuleScopeV1.from_dict(_object(value["scope"], "scope")),
            period=ClosedPeriodV1.from_dict(_object(value["period"], "period")),
            objective=ModuleObjectiveV1.from_dict(
                _object(value["objective"], "objective")
            ),
            external_evidence=(
                None
                if external_evidence is None
                else ExternalEvidenceV1.from_dict(
                    _object(external_evidence, "external_evidence")
                )
            ),
            operation=ModuleOperationV1.from_dict(
                _object(value["operation"], "operation")
            ),
            idempotency_key=_text(
                value["idempotency_key"],
                "idempotency_key",
                maximum=128,
            ),
        )

    def as_dict(self) -> Dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "connection_ref": self.connection_ref.as_dict(),
            "environment": self.environment,
            "scope": self.scope.as_dict(),
            "period": self.period.as_dict(),
            "objective": self.objective.as_dict(),
            "operation": self.operation.as_dict(),
            "idempotency_key": self.idempotency_key,
        }
        if self.external_evidence is not None:
            value["external_evidence"] = self.external_evidence.as_dict()
        return value


@dataclass(frozen=True)
class ModuleIdentityV1:
    module_id: str
    module_version: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModuleIdentityV1":
        _exact_fields(
            value,
            field="module",
            required=("module_id", "module_version"),
        )
        return cls(
            module_id=_one_of(
                value["module_id"],
                "module.module_id",
                ("YANDEX_DIRECT", "YANDEX_METRIKA"),
            ),
            module_version=_text(
                value["module_version"],
                "module.module_version",
                maximum=32,
            ),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "module_id": self.module_id,
            "module_version": self.module_version,
        }


@dataclass(frozen=True)
class ModuleAssessmentV1:
    summary: str
    data_quality_status: str
    confidence_status: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModuleAssessmentV1":
        _exact_fields(
            value,
            field="assessment",
            required=("summary", "data_quality_status", "confidence_status"),
        )
        return cls(
            summary=_text(value["summary"], "assessment.summary", maximum=2_000),
            data_quality_status=_one_of(
                value["data_quality_status"],
                "assessment.data_quality_status",
                ("READY", "PARTIAL", "INCOMPATIBLE"),
            ),
            confidence_status=_one_of(
                value["confidence_status"],
                "assessment.confidence_status",
                ("READY", "INSUFFICIENT_DATA", "STALE_DATA"),
            ),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "data_quality_status": self.data_quality_status,
            "confidence_status": self.confidence_status,
        }


@dataclass(frozen=True)
class ModuleRecommendationV1:
    code: str
    summary: str
    rationale: str
    executable: bool

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        field: str = "recommendation",
    ) -> "ModuleRecommendationV1":
        _exact_fields(
            value,
            field=field,
            required=("code", "summary", "rationale", "executable"),
        )
        executable = value["executable"]
        if not isinstance(executable, bool):
            raise ContractValidationError(f"{field}.executable must be boolean")
        return cls(
            code=_text(value["code"], f"{field}.code", maximum=128),
            summary=_text(value["summary"], f"{field}.summary", maximum=1_000),
            rationale=_text(
                value["rationale"],
                f"{field}.rationale",
                maximum=2_000,
            ),
            executable=executable,
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "summary": self.summary,
            "rationale": self.rationale,
            "executable": self.executable,
        }


@dataclass(frozen=True)
class ModuleProposalV1:
    proposal_id: str
    operation_type: str
    status: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModuleProposalV1":
        _exact_fields(
            value,
            field="proposal",
            required=("proposal_id", "operation_type", "status"),
        )
        return cls(
            proposal_id=_text(
                value["proposal_id"],
                "proposal.proposal_id",
                maximum=128,
            ),
            operation_type=_text(
                value["operation_type"],
                "proposal.operation_type",
                maximum=128,
            ),
            status=_one_of(
                value["status"],
                "proposal.status",
                ("PROPOSED", "DRY_RUN"),
            ),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "operation_type": self.operation_type,
            "status": self.status,
        }


@dataclass(frozen=True)
class ModuleExecutionResultV1:
    execution_id: str
    operation_type: str
    status: str
    applied: bool
    provider_reference: Optional[str] = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModuleExecutionResultV1":
        _exact_fields(
            value,
            field="execution_result",
            required=("execution_id", "operation_type", "status", "applied"),
            optional=("provider_reference",),
        )
        applied = value["applied"]
        if not isinstance(applied, bool):
            raise ContractValidationError("execution_result.applied must be boolean")
        return cls(
            execution_id=_text(
                value["execution_id"],
                "execution_result.execution_id",
                maximum=128,
            ),
            operation_type=_text(
                value["operation_type"],
                "execution_result.operation_type",
                maximum=128,
            ),
            status=_one_of(
                value["status"],
                "execution_result.status",
                (
                    "APPLIED",
                    "NO_CHANGE",
                    "BLOCKED",
                    "ALREADY_PROCESSED",
                    "UNKNOWN_RESULT",
                    "FAILED",
                ),
            ),
            applied=applied,
            provider_reference=_optional_text(
                value.get("provider_reference"),
                "execution_result.provider_reference",
                maximum=256,
            ),
        )

    def as_dict(self) -> Dict[str, Any]:
        value: Dict[str, Any] = {
            "execution_id": self.execution_id,
            "operation_type": self.operation_type,
            "status": self.status,
            "applied": self.applied,
        }
        if self.provider_reference is not None:
            value["provider_reference"] = self.provider_reference
        return value


@dataclass(frozen=True)
class ModuleProvenanceV1:
    source_type: str
    source: str
    retrieved_at: str
    watermark: str
    evidence_id: Optional[str] = None

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        field: str = "provenance",
    ) -> "ModuleProvenanceV1":
        _exact_fields(
            value,
            field=field,
            required=("source_type", "source", "retrieved_at", "watermark"),
            optional=("evidence_id",),
        )
        return cls(
            source_type=_one_of(
                value["source_type"],
                f"{field}.source_type",
                ("PROVIDER", "CUSTOMER_EVIDENCE"),
            ),
            source=_text(value["source"], f"{field}.source", maximum=128),
            retrieved_at=_timestamp(
                value["retrieved_at"],
                f"{field}.retrieved_at",
            ),
            watermark=_timestamp(value["watermark"], f"{field}.watermark"),
            evidence_id=_optional_text(
                value.get("evidence_id"),
                f"{field}.evidence_id",
                maximum=128,
            ),
        )

    def as_dict(self) -> Dict[str, Any]:
        value: Dict[str, Any] = {
            "source_type": self.source_type,
            "source": self.source,
            "retrieved_at": self.retrieved_at,
            "watermark": self.watermark,
        }
        if self.evidence_id is not None:
            value["evidence_id"] = self.evidence_id
        return value


@dataclass(frozen=True)
class ModuleWarningV1:
    code: str
    message: str

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        field: str = "warning",
    ) -> "ModuleWarningV1":
        _exact_fields(value, field=field, required=("code", "message"))
        return cls(
            code=_text(value["code"], f"{field}.code", maximum=128),
            message=_text(value["message"], f"{field}.message", maximum=2_000),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class ModuleErrorV1:
    code: str
    message: str
    field: Optional[str]
    retryable: bool

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        field: str = "error",
    ) -> "ModuleErrorV1":
        _exact_fields(
            value,
            field=field,
            required=("code", "message", "field", "retryable"),
        )
        retryable = value["retryable"]
        if not isinstance(retryable, bool):
            raise ContractValidationError(f"{field}.retryable must be boolean")
        return cls(
            code=_text(value["code"], f"{field}.code", maximum=128),
            message=_text(value["message"], f"{field}.message", maximum=2_000),
            field=_optional_text(
                value["field"],
                f"{field}.field",
                maximum=256,
            ),
            retryable=retryable,
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "retryable": self.retryable,
        }


@dataclass(frozen=True)
class ModuleResultV1:
    schema_version: str
    run_id: str
    module: ModuleIdentityV1
    status: str
    metrics: Tuple[MetricValueV1, ...]
    assessment: Optional[ModuleAssessmentV1]
    recommendations: Tuple[ModuleRecommendationV1, ...]
    proposal: Optional[ModuleProposalV1]
    execution_result: Optional[ModuleExecutionResultV1]
    provenance: Tuple[ModuleProvenanceV1, ...]
    warnings: Tuple[ModuleWarningV1, ...]
    errors: Tuple[ModuleErrorV1, ...]
    decision_record_ref: Optional[str]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModuleResultV1":
        value = _object(value, "result")
        _exact_fields(
            value,
            field="result",
            required=(
                "schema_version",
                "run_id",
                "module",
                "status",
                "metrics",
                "assessment",
                "recommendations",
                "proposal",
                "execution_result",
                "provenance",
                "warnings",
                "errors",
                "decision_record_ref",
            ),
        )
        proposal_value = value["proposal"]
        execution_value = value["execution_result"]
        if proposal_value is not None and execution_value is not None:
            raise ContractValidationError(
                "result cannot contain both proposal and execution_result"
            )
        status = _one_of(
            value["status"],
            "result.status",
            ("SUCCEEDED", "PARTIAL", "BLOCKED", "REJECTED", "FAILED"),
        )
        errors = tuple(
            ModuleErrorV1.from_dict(
                _object(item, f"errors[{index}]"),
                field=f"errors[{index}]",
            )
            for index, item in enumerate(_array(value["errors"], "errors"))
        )
        if status in ("BLOCKED", "REJECTED", "FAILED") and not errors:
            raise ContractValidationError(
                f"result.errors must not be empty when status is {status}"
            )
        return cls(
            schema_version=_one_of(
                value["schema_version"],
                "result.schema_version",
                (MODULE_RESULT_SCHEMA_VERSION,),
            ),
            run_id=_text(value["run_id"], "result.run_id", maximum=128),
            module=ModuleIdentityV1.from_dict(
                _object(value["module"], "module")
            ),
            status=status,
            metrics=tuple(
                MetricValueV1.from_dict(
                    _object(item, f"metrics[{index}]"),
                    field=f"metrics[{index}]",
                )
                for index, item in enumerate(_array(value["metrics"], "metrics"))
            ),
            assessment=(
                None
                if value["assessment"] is None
                else ModuleAssessmentV1.from_dict(
                    _object(value["assessment"], "assessment")
                )
            ),
            recommendations=tuple(
                ModuleRecommendationV1.from_dict(
                    _object(item, f"recommendations[{index}]"),
                    field=f"recommendations[{index}]",
                )
                for index, item in enumerate(
                    _array(value["recommendations"], "recommendations")
                )
            ),
            proposal=(
                None
                if proposal_value is None
                else ModuleProposalV1.from_dict(
                    _object(proposal_value, "proposal")
                )
            ),
            execution_result=(
                None
                if execution_value is None
                else ModuleExecutionResultV1.from_dict(
                    _object(execution_value, "execution_result")
                )
            ),
            provenance=tuple(
                ModuleProvenanceV1.from_dict(
                    _object(item, f"provenance[{index}]"),
                    field=f"provenance[{index}]",
                )
                for index, item in enumerate(
                    _array(value["provenance"], "provenance")
                )
            ),
            warnings=tuple(
                ModuleWarningV1.from_dict(
                    _object(item, f"warnings[{index}]"),
                    field=f"warnings[{index}]",
                )
                for index, item in enumerate(_array(value["warnings"], "warnings"))
            ),
            errors=errors,
            decision_record_ref=_optional_text(
                value["decision_record_ref"],
                "result.decision_record_ref",
                maximum=500,
            ),
        )

    @classmethod
    def rejected_contract(
        cls,
        module: ModuleIdentityV1,
        error: ContractValidationError,
    ) -> "ModuleResultV1":
        return cls(
            schema_version=MODULE_RESULT_SCHEMA_VERSION,
            run_id="rejected-request",
            module=module,
            status="REJECTED",
            metrics=(),
            assessment=None,
            recommendations=(),
            proposal=None,
            execution_result=None,
            provenance=(),
            warnings=(),
            errors=(
                ModuleErrorV1(
                    code="CONTRACT_VALIDATION_FAILED",
                    message=str(error),
                    field=None,
                    retryable=False,
                ),
            ),
            decision_record_ref=None,
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "module": self.module.as_dict(),
            "status": self.status,
            "metrics": [item.as_dict() for item in self.metrics],
            "assessment": (
                None if self.assessment is None else self.assessment.as_dict()
            ),
            "recommendations": [
                item.as_dict() for item in self.recommendations
            ],
            "proposal": None if self.proposal is None else self.proposal.as_dict(),
            "execution_result": (
                None
                if self.execution_result is None
                else self.execution_result.as_dict()
            ),
            "provenance": [item.as_dict() for item in self.provenance],
            "warnings": [item.as_dict() for item in self.warnings],
            "errors": [item.as_dict() for item in self.errors],
            "decision_record_ref": self.decision_record_ref,
        }
