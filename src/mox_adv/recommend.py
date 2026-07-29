"""Stable public API for schema-safe RECOMMEND mode."""

from mox_adv.model_provider import DeterministicFakeModelProvider
from mox_adv.proposal_store import ImmutableProposalStore, StoredProposal
from mox_adv.recommend_contracts import (
    CampaignDraftV1,
    GoalCandidate,
    ModelProvider,
    ModelResponse,
    OptimizationProposalV1,
    ProposalConflictError,
    ProviderMetadata,
    SchemaValidationError,
)
from mox_adv.recommend_projection import build_sanitized_projection
from mox_adv.recommend_service import RecommendationOutcome, RecommendationService

__all__ = [
    "CampaignDraftV1",
    "DeterministicFakeModelProvider",
    "GoalCandidate",
    "ImmutableProposalStore",
    "ModelProvider",
    "ModelResponse",
    "OptimizationProposalV1",
    "ProposalConflictError",
    "ProviderMetadata",
    "RecommendationOutcome",
    "RecommendationService",
    "SchemaValidationError",
    "StoredProposal",
    "build_sanitized_projection",
]
