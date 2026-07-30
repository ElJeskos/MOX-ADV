"""Version 1 request and result contracts for standalone and paired modules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import (
    Any,
    Dict,
    Literal,
    Mapping,
    Optional,
    Tuple,
    Union,
    cast,
    get_args,
)

from mox_adv.environment import PRODUCTION_WRITE_FORBIDDEN
from mox_adv.module_api.v1.contract_validation import (
    ContractValidationError,
)
from mox_adv.module_api.v1.contract_validation import (
    array_value as _array,
)
from mox_adv.module_api.v1.contract_validation import (
    exact_fields as _exact_fields,
)
from mox_adv.module_api.v1.contract_validation import (
    iso_date as _iso_date,
)
from mox_adv.module_api.v1.contract_validation import (
    object_value as _object,
)
from mox_adv.module_api.v1.contract_validation import (
    one_of as _one_of,
)
from mox_adv.module_api.v1.contract_validation import (
    optional_text as _optional_text,
)
from mox_adv.module_api.v1.contract_validation import (
    text as _text,
)
from mox_adv.module_api.v1.contract_validation import (
    timestamp as _timestamp,
)
from mox_adv.module_api.v1.contract_validation import (
    timezone_name as _timezone,
)
from mox_adv.module_api.v1.goal_lifecycle_contracts import (
    GoalLifecycleCommandV1,
    GoalLifecycleOutcomeV1,
)

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
OperationKind = Literal["ANALYZE", "PLAN", "EXECUTE"]
ModuleStatus = Literal[
    "SUCCEEDED",
    "PARTIAL",
    "BLOCKED",
    "REJECTED",
    "FAILED",
]
MODULE_STATUSES = cast(Tuple[ModuleStatus, ...], get_args(ModuleStatus))


def _goal_lifecycle_command(
    value: Mapping[str, Any],
) -> GoalLifecycleCommandV1:
    return GoalLifecycleCommandV1.from_dict(value)


def _goal_lifecycle_outcome(
    value: Mapping[str, Any],
) -> GoalLifecycleOutcomeV1:
    return GoalLifecycleOutcomeV1.from_dict(value)


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
            metric_value is None or isinstance(metric_value, (str, int, float))
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

    def __post_init__(self) -> None:
        _one_of(
            self.schema_version,
            "external_evidence.schema_version",
            (EXTERNAL_EVIDENCE_SCHEMA_VERSION,),
        )
        _one_of(
            self.source,
            "external_evidence.source",
            ("CUSTOMER_ECOSYSTEM",),
        )

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
        schema_version = _text(
            value["schema_version"],
            "external_evidence.schema_version",
            maximum=64,
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
            raise ContractValidationError("external_evidence.metrics must not be empty")
        return cls(
            schema_version=schema_version,
            evidence_id=_text(
                value["evidence_id"],
                "external_evidence.evidence_id",
                maximum=128,
            ),
            source=_text(
                value["source"],
                "external_evidence.source",
                maximum=64,
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
    kind: OperationKind
    operation_type: str

    def __post_init__(self) -> None:
        kind = _one_of(
            self.kind,
            "operation.kind",
            tuple(OPERATION_TYPES_BY_KIND),
        )
        _one_of(
            self.operation_type,
            "operation.operation_type",
            OPERATION_TYPES_BY_KIND[kind],
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModuleOperationV1":
        _exact_fields(
            value,
            field="operation",
            required=("kind", "operation_type"),
        )
        return cls(
            kind=cast(
                OperationKind,
                _text(value["kind"], "operation.kind", maximum=32),
            ),
            operation_type=_text(
                value["operation_type"],
                "operation.operation_type",
                maximum=128,
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
    goal_lifecycle_command: Optional[GoalLifecycleCommandV1] = None

    def __post_init__(self) -> None:
        _one_of(
            self.schema_version,
            "schema_version",
            (MODULE_REQUEST_SCHEMA_VERSION,),
        )
        _one_of(
            self.environment,
            "environment",
            ("PRODUCTION", "TEST"),
        )
        _text(self.idempotency_key, "idempotency_key", maximum=128)
        nested_types = (
            ("connection_ref", self.connection_ref, StoredConnectionRefV1),
            ("scope", self.scope, ModuleScopeV1),
            ("period", self.period, ClosedPeriodV1),
            ("objective", self.objective, ModuleObjectiveV1),
            ("operation", self.operation, ModuleOperationV1),
        )
        for field, value, expected_type in nested_types:
            if not isinstance(value, expected_type):
                raise ContractValidationError(
                    f"{field} must be a {expected_type.__name__}"
                )
        if self.external_evidence is not None and not isinstance(
            self.external_evidence, ExternalEvidenceV1
        ):
            raise ContractValidationError(
                "external_evidence must be an ExternalEvidenceV1"
            )
        is_goal_lifecycle = (
            self.operation.kind == "EXECUTE"
            and self.operation.operation_type == "MANAGE_GOAL_CANDIDATE"
        )
        if is_goal_lifecycle != (self.goal_lifecycle_command is not None):
            raise ContractValidationError(
                "goal_lifecycle_command is required only for an EXECUTE "
                "MANAGE_GOAL_CANDIDATE operation"
            )
        if self.goal_lifecycle_command is not None:
            if not isinstance(
                self.goal_lifecycle_command,
                GoalLifecycleCommandV1,
            ):
                raise ContractValidationError(
                    "goal_lifecycle_command must be a GoalLifecycleCommandV1"
                )
            if self.external_evidence is not None:
                raise ContractValidationError(
                    "goal lifecycle requests cannot contain external_evidence"
                )
            if self.scope.counter_id is None:
                raise ContractValidationError(
                    "goal lifecycle requests require scope.counter_id"
                )

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
            optional=("external_evidence", "goal_lifecycle_command"),
        )
        external_evidence = value.get("external_evidence")
        goal_lifecycle_command = value.get("goal_lifecycle_command")
        if "external_evidence" in value and external_evidence is None:
            raise ContractValidationError(
                "external_evidence must be an object when present"
            )
        return cls(
            schema_version=_text(
                value["schema_version"],
                "schema_version",
                maximum=64,
            ),
            connection_ref=StoredConnectionRefV1.from_dict(
                _object(value["connection_ref"], "connection_ref")
            ),
            environment=_text(
                value["environment"],
                "environment",
                maximum=32,
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
            goal_lifecycle_command=(
                None
                if goal_lifecycle_command is None
                else _goal_lifecycle_command(
                    _object(
                        goal_lifecycle_command,
                        "goal_lifecycle_command",
                    )
                )
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
        if self.goal_lifecycle_command is not None:
            value["goal_lifecycle_command"] = self.goal_lifecycle_command.as_dict()
        return value


@dataclass(frozen=True)
class ModuleIdentityV1:
    module_id: str
    module_version: str

    def __post_init__(self) -> None:
        _one_of(
            self.module_id,
            "module.module_id",
            ("YANDEX_DIRECT", "YANDEX_METRIKA"),
        )
        _text(
            self.module_version,
            "module.module_version",
            maximum=32,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModuleIdentityV1":
        _exact_fields(
            value,
            field="module",
            required=("module_id", "module_version"),
        )
        return cls(
            module_id=_text(
                value["module_id"],
                "module.module_id",
                maximum=64,
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

    def __post_init__(self) -> None:
        _one_of(
            self.data_quality_status,
            "assessment.data_quality_status",
            ("READY", "PARTIAL", "INCOMPATIBLE"),
        )
        _one_of(
            self.confidence_status,
            "assessment.confidence_status",
            ("READY", "INSUFFICIENT_DATA", "STALE_DATA"),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModuleAssessmentV1":
        _exact_fields(
            value,
            field="assessment",
            required=("summary", "data_quality_status", "confidence_status"),
        )
        return cls(
            summary=_text(value["summary"], "assessment.summary", maximum=2_000),
            data_quality_status=_text(
                value["data_quality_status"],
                "assessment.data_quality_status",
                maximum=32,
            ),
            confidence_status=_text(
                value["confidence_status"],
                "assessment.confidence_status",
                maximum=32,
            ),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "data_quality_status": self.data_quality_status,
            "confidence_status": self.confidence_status,
        }


@dataclass(frozen=True)
class ModuleHypothesisV1:
    """One bounded hypothesis linked to normalized result metrics."""

    code: str
    summary: str
    evidence_metric_names: Tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.code, "hypothesis.code", maximum=128)
        _text(self.summary, "hypothesis.summary", maximum=1_000)
        if not self.evidence_metric_names:
            raise ContractValidationError(
                "hypothesis.evidence_metric_names must not be empty"
            )
        if len(set(self.evidence_metric_names)) != len(self.evidence_metric_names):
            raise ContractValidationError(
                "hypothesis.evidence_metric_names must not contain duplicates"
            )
        for name in self.evidence_metric_names:
            _text(name, "hypothesis.evidence_metric_names[]", maximum=128)

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        field: str = "hypothesis",
    ) -> "ModuleHypothesisV1":
        _exact_fields(
            value,
            field=field,
            required=("code", "summary", "evidence_metric_names"),
        )
        return cls(
            code=_text(value["code"], f"{field}.code", maximum=128),
            summary=_text(value["summary"], f"{field}.summary", maximum=1_000),
            evidence_metric_names=tuple(
                _text(item, f"{field}.evidence_metric_names[]", maximum=128)
                for item in _array(
                    value["evidence_metric_names"],
                    f"{field}.evidence_metric_names",
                )
            ),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "summary": self.summary,
            "evidence_metric_names": list(self.evidence_metric_names),
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

    def __post_init__(self) -> None:
        _one_of(
            self.status,
            "proposal.status",
            ("PROPOSED", "DRY_RUN"),
        )

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
            status=_text(
                value["status"],
                "proposal.status",
                maximum=32,
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

    def __post_init__(self) -> None:
        _one_of(
            self.status,
            "execution_result.status",
            (
                "APPLIED",
                "NO_CHANGE",
                "BLOCKED",
                "ALREADY_PROCESSED",
                "UNKNOWN_RESULT",
                "FAILED",
            ),
        )

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
            status=_text(
                value["status"],
                "execution_result.status",
                maximum=32,
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

    def __post_init__(self) -> None:
        _one_of(
            self.source_type,
            "provenance.source_type",
            ("PROVIDER", "CUSTOMER_EVIDENCE"),
        )

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
            source_type=_text(
                value["source_type"],
                f"{field}.source_type",
                maximum=32,
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
    status: ModuleStatus
    metrics: Tuple[MetricValueV1, ...]
    assessment: Optional[ModuleAssessmentV1]
    recommendations: Tuple[ModuleRecommendationV1, ...]
    proposal: Optional[ModuleProposalV1]
    execution_result: Optional[ModuleExecutionResultV1]
    provenance: Tuple[ModuleProvenanceV1, ...]
    warnings: Tuple[ModuleWarningV1, ...]
    errors: Tuple[ModuleErrorV1, ...]
    decision_record_ref: Optional[str]
    hypotheses: Tuple[ModuleHypothesisV1, ...] = ()
    lifecycle_outcome: Optional[GoalLifecycleOutcomeV1] = None

    def __post_init__(self) -> None:
        _one_of(
            self.schema_version,
            "result.schema_version",
            (MODULE_RESULT_SCHEMA_VERSION,),
        )
        _text(self.run_id, "result.run_id", maximum=128)
        if not isinstance(self.module, ModuleIdentityV1):
            raise ContractValidationError("result.module must be a ModuleIdentityV1")
        status = _one_of(
            self.status,
            "result.status",
            MODULE_STATUSES,
        )
        if self.proposal is not None and self.execution_result is not None:
            raise ContractValidationError(
                "result cannot contain both proposal and execution_result"
            )
        if status in ("BLOCKED", "REJECTED", "FAILED") and not self.errors:
            raise ContractValidationError(
                f"result.errors must not be empty when status is {status}"
            )
        if len(self.hypotheses) > 3:
            raise ContractValidationError(
                "result must contain at most three hypotheses"
            )
        metric_names = {metric.name for metric in self.metrics}
        for hypothesis in self.hypotheses:
            if not isinstance(hypothesis, ModuleHypothesisV1):
                raise ContractValidationError(
                    "result.hypotheses must contain ModuleHypothesisV1 values"
                )
            unknown = set(hypothesis.evidence_metric_names) - metric_names
            if unknown:
                raise ContractValidationError(
                    "hypothesis references an unknown metric: " + sorted(unknown)[0]
                )

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
                "provenance",
                "warnings",
                "errors",
                "decision_record_ref",
            ),
            optional=(
                "proposal",
                "execution_result",
                "hypotheses",
                "lifecycle_outcome",
            ),
        )
        proposal_value = value.get("proposal")
        execution_value = value.get("execution_result")
        lifecycle_outcome = value.get("lifecycle_outcome")
        errors = tuple(
            ModuleErrorV1.from_dict(
                _object(item, f"errors[{index}]"),
                field=f"errors[{index}]",
            )
            for index, item in enumerate(_array(value["errors"], "errors"))
        )
        return cls(
            schema_version=_text(
                value["schema_version"],
                "result.schema_version",
                maximum=64,
            ),
            run_id=_text(value["run_id"], "result.run_id", maximum=128),
            module=ModuleIdentityV1.from_dict(_object(value["module"], "module")),
            status=cast(
                ModuleStatus,
                _text(value["status"], "result.status", maximum=32),
            ),
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
                else ModuleProposalV1.from_dict(_object(proposal_value, "proposal"))
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
                for index, item in enumerate(_array(value["provenance"], "provenance"))
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
            hypotheses=tuple(
                ModuleHypothesisV1.from_dict(
                    _object(item, f"hypotheses[{index}]"),
                    field=f"hypotheses[{index}]",
                )
                for index, item in enumerate(
                    _array(value.get("hypotheses", ()), "hypotheses")
                )
            ),
            lifecycle_outcome=(
                None
                if lifecycle_outcome is None
                else _goal_lifecycle_outcome(
                    _object(lifecycle_outcome, "lifecycle_outcome")
                )
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

    @classmethod
    def blocked_production_write(
        cls,
        *,
        module: ModuleIdentityV1,
        request: ModuleRequestV1,
        decision_id: str,
        decision_record_ref: str,
    ) -> "ModuleResultV1":
        return cls(
            schema_version=MODULE_RESULT_SCHEMA_VERSION,
            run_id="blocked-" + decision_id,
            module=module,
            status="BLOCKED",
            metrics=(),
            assessment=None,
            recommendations=(),
            proposal=None,
            execution_result=ModuleExecutionResultV1(
                execution_id="blocked-" + decision_id,
                operation_type=request.operation.operation_type,
                status="BLOCKED",
                applied=False,
            ),
            provenance=(),
            warnings=(),
            errors=(
                ModuleErrorV1(
                    code=PRODUCTION_WRITE_FORBIDDEN,
                    message=(
                        "Changing commands are available only in the TEST environment."
                    ),
                    field="environment",
                    retryable=False,
                ),
            ),
            decision_record_ref=decision_record_ref,
        )

    def as_dict(self) -> Dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "module": self.module.as_dict(),
            "status": self.status,
            "metrics": [item.as_dict() for item in self.metrics],
            "assessment": (
                None if self.assessment is None else self.assessment.as_dict()
            ),
            "recommendations": [item.as_dict() for item in self.recommendations],
            "hypotheses": [item.as_dict() for item in self.hypotheses],
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
        if self.lifecycle_outcome is not None:
            value["lifecycle_outcome"] = self.lifecycle_outcome.as_dict()
        return value
