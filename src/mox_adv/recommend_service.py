"""RECOMMEND orchestration without any execution authority."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from mox_adv.model_cost import (
    DurableModelCostLedger,
    ModelCostRejected,
)
from mox_adv.proposal_store import (
    ImmutableProposalStore,
    normalized_reason_key,
)
from mox_adv.recommend_contracts import (
    ModelProvider,
    OptimizationProposalV1,
    ProviderMetadata,
    SchemaValidationError,
    _canonical,
    _validate_model_payload,
)
from mox_adv.recommend_projection import SanitizedProjection, validate_projection


@dataclass(frozen=True)
class RecommendationOutcome:
    status: str
    execution_status: str
    reason_code: Optional[str]
    proposal: Optional[OptimizationProposalV1]
    provider: ProviderMetadata
    canonical_hash: str
    deduplicated: bool
    cost_warning: bool

    @property
    def decision_status(self) -> str:
        if self.proposal is not None:
            return self.proposal.status
        if self.reason_code == "UNSUPPORTED_STATE":
            return "NEEDS_HUMAN"
        return "BLOCKED"

    @property
    def decision_action(self) -> Optional[str]:
        if self.proposal is not None:
            return str(self.proposal.actions[0]["action"])
        if self.reason_code == "UNSUPPORTED_STATE":
            return "REQUEST_HUMAN_HELP"
        return None


class RecommendationService:
    """Generate, validate, enrich, and persist one RECOMMEND proposal."""

    def __init__(
        self,
        provider: ModelProvider,
        store: ImmutableProposalStore,
        policy: Optional[Mapping[str, Any]] = None,
        cost_ledger: Optional[DurableModelCostLedger] = None,
    ) -> None:
        self.provider = provider
        self.store = store
        if (
            policy is not None
            and type(cost_ledger) is not DurableModelCostLedger
        ):
            raise ModelCostRejected("APPLICATION_MODEL_COST_LEDGER_REQUIRED")
        self.cost_ledger = cost_ledger

    def recommend(
        self,
        projection: Mapping[str, Any],
        run_id: str,
        snapshot_id: str,
        expected_fingerprint: str,
        created_at: str,
        expires_at: str,
    ) -> RecommendationOutcome:
        try:
            if not isinstance(projection, SanitizedProjection):
                raise SchemaValidationError(
                    "The provider input must come from the trusted projection builder."
                )
            validate_projection(projection)
        except SchemaValidationError:
            return RecommendationOutcome(
                status="BLOCKED",
                execution_status="BLOCKED",
                reason_code="INVALID_INPUT",
                proposal=None,
                provider=ProviderMetadata(
                    provider="not-invoked",
                    model_id="not-invoked",
                    input_tokens=0,
                    output_tokens=0,
                    cost_rub="0",
                    duration_ms=0,
                ),
                canonical_hash="",
                deduplicated=False,
                cost_warning=False,
            )
        try:
            if not isinstance(created_at, str) or not isinstance(expires_at, str):
                raise ValueError("Recommendation timestamps must be strings.")
            parsed_evaluation_at = datetime.fromisoformat(
                created_at.replace("Z", "+00:00")
            )
            parsed_expiry = datetime.fromisoformat(
                expires_at.replace("Z", "+00:00")
            )
            if (
                parsed_evaluation_at.tzinfo is None
                or parsed_expiry.tzinfo is None
                or parsed_expiry <= parsed_evaluation_at
            ):
                raise ValueError("Recommendation evaluation time must be aware.")
            evaluation_at = parsed_evaluation_at.astimezone(timezone.utc)
            if projection["campaign_state"] not in {"ON", "SUSPENDED"}:
                return RecommendationOutcome(
                    status="NEEDS_HUMAN",
                    execution_status="BLOCKED",
                    reason_code="UNSUPPORTED_STATE",
                    proposal=None,
                    provider=self._not_invoked_metadata(),
                    canonical_hash="",
                    deduplicated=False,
                    cost_warning=False,
                )
            reason_key = normalized_reason_key(projection["observed_facts"])
            active = self.store.load_active_by_reason(
                snapshot_id,
                reason_key,
                projection,
                evaluation_at,
            )
        except (ValueError, SchemaValidationError):
            return RecommendationOutcome(
                status="BLOCKED",
                execution_status="BLOCKED",
                reason_code="INVALID_INPUT",
                proposal=None,
                provider=self._not_invoked_metadata(),
                canonical_hash="",
                deduplicated=False,
                cost_warning=False,
            )
        if active is not None:
            warning = (
                False
                if self.cost_ledger is None
                else self.cost_ledger.usage().warning
            )
            return RecommendationOutcome(
                status="READY",
                execution_status="NOT_STARTED",
                reason_code=None,
                proposal=active.proposal,
                provider=active.provider,
                canonical_hash=active.canonical_hash,
                deduplicated=True,
                cost_warning=warning,
            )
        if self.cost_ledger is None:
            return RecommendationOutcome(
                status="BLOCKED",
                execution_status="BLOCKED",
                reason_code="MODEL_COST_CONFIGURATION_INVALID",
                proposal=None,
                provider=self._not_invoked_metadata(),
                canonical_hash="",
                deduplicated=False,
                cost_warning=False,
            )
        try:
            reservation = self.cost_ledger.reserve(
                str(self.provider.provider_id),
                str(self.provider.model_id),
                self.provider.maximum_input_tokens,
                self.provider.maximum_output_tokens,
            )
        except (AttributeError, TypeError, ValueError, ModelCostRejected) as error:
            reason = (
                error.reason_code
                if isinstance(error, ModelCostRejected)
                else "MODEL_COST_PROFILE_MISSING"
            )
            return RecommendationOutcome(
                status="BLOCKED",
                execution_status="BLOCKED",
                reason_code=reason,
                proposal=None,
                provider=self._not_invoked_metadata(),
                canonical_hash="",
                deduplicated=False,
                cost_warning=self.cost_ledger.usage().warning,
            )
        try:
            response = self.provider.generate(deepcopy(dict(projection)))
        except BaseException:
            self.cost_ledger.fail(reservation, "MODEL_PROVIDER_FAILED")
            raise
        try:
            raw_metadata = response.metadata()
        except Exception:
            self.cost_ledger.fail(reservation, "MODEL_USAGE_METADATA_INVALID")
            return RecommendationOutcome(
                status="BLOCKED",
                execution_status="BLOCKED",
                reason_code="MODEL_USAGE_METADATA_INVALID",
                proposal=None,
                provider=self._reservation_metadata(reservation),
                canonical_hash="",
                deduplicated=False,
                cost_warning=self.cost_ledger.usage().warning,
            )
        try:
            metadata = self.cost_ledger.settle(reservation, raw_metadata)
            proposal = self.compose_proposal(
                model_payload=response.payload,
                projection=projection,
                run_id=run_id,
                snapshot_id=snapshot_id,
                expected_fingerprint=expected_fingerprint,
                created_at=created_at,
                expires_at=expires_at,
            )
        except ModelCostRejected as error:
            return RecommendationOutcome(
                status="BLOCKED",
                execution_status="BLOCKED",
                reason_code=error.reason_code,
                proposal=None,
                provider=self._reservation_metadata(reservation),
                canonical_hash="",
                deduplicated=False,
                cost_warning=self.cost_ledger.usage().warning,
            )
        except (AttributeError, SchemaValidationError, TypeError, ValueError):
            return RecommendationOutcome(
                status="BLOCKED",
                execution_status="BLOCKED",
                reason_code="INVALID_INPUT",
                proposal=None,
                provider=metadata,
                canonical_hash="",
                deduplicated=False,
                cost_warning=self.cost_ledger.usage().warning,
            )
        stored = self.store.save(
            proposal,
            metadata,
            reason_facts=projection["observed_facts"],
            at=evaluation_at,
        )
        if stored.proposal_id != proposal.proposal_id:
            existing = self.store.load_active(
                stored.proposal_id,
                projection,
                evaluation_at,
            )
            if existing is None:
                raise RuntimeError("Active proposal disappeared during deduplication.")
            proposal = existing
        return RecommendationOutcome(
            status="READY",
            execution_status="NOT_STARTED",
            reason_code=None,
            proposal=proposal,
            provider=metadata,
            canonical_hash=stored.canonical_hash,
            deduplicated=stored.deduplicated,
            cost_warning=(
                reservation.warning or self.cost_ledger.usage().warning
            ),
        )

    @staticmethod
    def _not_invoked_metadata() -> ProviderMetadata:
        return ProviderMetadata(
            provider="not-invoked",
            model_id="not-invoked",
            input_tokens=0,
            output_tokens=0,
            cost_rub="0",
            duration_ms=0,
        )

    @staticmethod
    def _reservation_metadata(reservation: Any) -> ProviderMetadata:
        return ProviderMetadata(
            provider=str(reservation.provider),
            model_id=str(reservation.model_id),
            input_tokens=0,
            output_tokens=0,
            cost_rub=str(reservation.reserved_cost_rub),
            duration_ms=0,
        )

    @staticmethod
    def compose_proposal(
        model_payload: Mapping[str, Any],
        projection: Mapping[str, Any],
        run_id: str,
        snapshot_id: str,
        expected_fingerprint: str,
        created_at: str,
        expires_at: str,
    ) -> OptimizationProposalV1:
        if not isinstance(projection, SanitizedProjection):
            raise SchemaValidationError(
                "The proposal must use a trusted sanitized projection."
            )
        validate_projection(projection)
        validated = _validate_model_payload(model_payload, projection)
        identity = {
            "proposal_version": "optimization-proposal-v1",
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "created_at": created_at,
            "expires_at": expires_at,
            "expected_fingerprint": expected_fingerprint,
            **validated,
        }
        proposal_digest = hashlib.sha256(_canonical(identity)).hexdigest()
        proposal_id = "proposal-" + proposal_digest[:24]
        return OptimizationProposalV1.from_mapping(
            {"proposal_id": proposal_id, **identity},
            projection,
        )
