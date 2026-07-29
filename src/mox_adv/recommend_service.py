"""RECOMMEND orchestration without any execution authority."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from mox_adv.proposal_store import ImmutableProposalStore
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


class RecommendationService:
    """Generate, validate, enrich, and persist one RECOMMEND proposal."""

    def __init__(
        self,
        provider: ModelProvider,
        store: ImmutableProposalStore,
    ) -> None:
        self.provider = provider
        self.store = store

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
            )
        try:
            response = self.provider.generate(deepcopy(dict(projection)))
            metadata = response.metadata()
            proposal = self.compose_proposal(
                model_payload=response.payload,
                projection=projection,
                run_id=run_id,
                snapshot_id=snapshot_id,
                expected_fingerprint=expected_fingerprint,
                created_at=created_at,
                expires_at=expires_at,
            )
        except SchemaValidationError:
            return RecommendationOutcome(
                status="BLOCKED",
                execution_status="BLOCKED",
                reason_code="INVALID_INPUT",
                proposal=None,
                provider=ProviderMetadata(
                    provider="invalid-provider-response",
                    model_id="invalid-provider-response",
                    input_tokens=0,
                    output_tokens=0,
                    cost_rub="0",
                    duration_ms=0,
                ),
                canonical_hash="",
                deduplicated=False,
            )
        stored = self.store.save(proposal, metadata)
        return RecommendationOutcome(
            status="READY",
            execution_status="NOT_STARTED",
            reason_code=None,
            proposal=proposal,
            provider=metadata,
            canonical_hash=stored.canonical_hash,
            deduplicated=stored.deduplicated,
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
