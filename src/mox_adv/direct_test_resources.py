"""Explicit socket-free TEST composition for the installed Direct edition."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mox_adv.campaign_lifecycle import (
    CampaignApproval,
    CampaignCreationRequest,
    CampaignDraftSafetyBindings,
    CampaignSagaStore,
    CreationReservation,
    CreationReservationStatus,
)
from mox_adv.contracts import (
    DirectCampaignStateBlock,
    DirectCampaignStateReadQuery,
    DirectReportBlock,
    DirectReportRow,
    DirectReportsReadQuery,
)
from mox_adv.control_state import (
    AuthenticatedPrincipal,
    DurableControlState,
    PrincipalAuthenticatorV1,
    authenticate_exact_local_principal_v1,
)
from mox_adv.direct_action_runtime import DirectActionRuntimeV1
from mox_adv.direct_campaign_creation import (
    DirectCampaignCreationRuntimeV1,
    SealedDirectCampaignCreationTestAdapterV1,
)
from mox_adv.direct_management import FakeDirectManagementAdapter
from mox_adv.direct_provider import DirectReadAuthorizationError
from mox_adv.environment import ExecutionEnvironment
from mox_adv.fake_write_adapter import FakeWriteAdapter
from mox_adv.module_api.v1 import ModuleDecisionRecordStoreV1, ModuleV1
from mox_adv.module_cli import StandaloneRuntimeSettingsV1
from mox_adv.modules.direct import DirectModuleV1
from mox_adv.monitoring import MonitoringStore
from mox_adv.proposal_store import ImmutableProposalStore
from mox_adv.recommend_contracts import CampaignDraftV1


@dataclass(frozen=True)
class DirectTestResourcesV1:
    path: Path
    policy: Mapping[str, Any]
    connection_id: str
    organization_id: str
    account_id: str
    campaign_id: str
    trusted_change_author: str
    initial_weekly_budget_micros: int
    allowed_landing_hosts: tuple[str, ...]
    prohibited_phrases: tuple[str, ...]
    prepared_media_references: tuple[str, ...]
    campaign_authorizations: tuple[Mapping[str, Any], ...]

    @classmethod
    def from_path(cls, path: Path) -> DirectTestResourcesV1:
        value = _json_object(path)
        expected = {
            "schema_version",
            "policy_path",
            "connection_id",
            "organization_id",
            "account_id",
            "campaign_id",
            "trusted_change_author",
            "initial_weekly_budget_micros",
            "campaign_safety",
            "campaign_authorizations",
        }
        if set(value) != expected or value["schema_version"] != (
            "direct-test-resources-v1"
        ):
            raise ValueError("Direct TEST resources have unexpected fields.")
        policy_path = _relative_path(path, value["policy_path"], "policy_path")
        policy = _json_object(policy_path)
        _validate_direct_policy(policy)
        safety = value["campaign_safety"]
        if not isinstance(safety, dict) or set(safety) != {
            "allowed_landing_hosts",
            "prohibited_phrases",
            "prepared_media_references",
        }:
            raise ValueError("Direct campaign safety bindings are invalid.")
        authorizations = value["campaign_authorizations"]
        if not isinstance(authorizations, list):
            raise TypeError("campaign_authorizations must be an array.")
        budget = value["initial_weekly_budget_micros"]
        if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
            raise ValueError("initial_weekly_budget_micros must be positive.")
        return cls(
            path=path,
            policy=policy,
            connection_id=_text(value["connection_id"], "connection_id"),
            organization_id=_text(value["organization_id"], "organization_id"),
            account_id=_text(value["account_id"], "account_id"),
            campaign_id=_text(value["campaign_id"], "campaign_id"),
            trusted_change_author=_text(
                value["trusted_change_author"],
                "trusted_change_author",
            ),
            initial_weekly_budget_micros=budget,
            allowed_landing_hosts=_texts(
                safety["allowed_landing_hosts"],
                "allowed_landing_hosts",
            ),
            prohibited_phrases=_texts(
                safety["prohibited_phrases"],
                "prohibited_phrases",
            ),
            prepared_media_references=_texts(
                safety["prepared_media_references"],
                "prepared_media_references",
            ),
            campaign_authorizations=tuple(
                _campaign_authorization(item) for item in authorizations
            ),
        )

    @property
    def policy_id(self) -> str:
        return _text(self.policy.get("policy_id"), "policy.policy_id")

    @property
    def approver(self) -> AuthenticatedPrincipal:
        value = self.policy["principals"]["approver"]
        return AuthenticatedPrincipal(
            identity=_text(value["identity"], "approver.identity"),
            authentication=_text(
                value["authentication"],
                "approver.authentication",
            ),
        )


class DirectTestReadProviderV1:
    """Generate deterministic reads only for one configured synthetic scope."""

    def __init__(
        self,
        resources: DirectTestResourcesV1,
        clock: Callable[[], datetime],
    ) -> None:
        self._resources = resources
        self._clock = clock

    def read_direct_report(
        self,
        connection_id: str,
        query: DirectReportsReadQuery,
    ) -> DirectReportBlock:
        self._authorize(connection_id, query.account, query.campaign)
        days = _dates(query.period_start, query.period_end)
        now = self._clock()
        return DirectReportBlock(
            source="DIRECT_REPORTS",
            retrieved_at=(now - timedelta(minutes=5)).isoformat(),
            watermark=(now - timedelta(minutes=10)).isoformat(),
            period_start=query.period_start,
            period_end=query.period_end,
            timezone="UTC",
            attribution="AUTO",
            currency="RUB",
            rows=tuple(
                DirectReportRow(
                    campaign=query.campaign,
                    date=day.isoformat(),
                    impressions=1_000,
                    clicks=40,
                    cost_micros=(
                        self._resources.initial_weekly_budget_micros
                        // max(len(days), 1)
                    ),
                )
                for day in days
            ),
        )

    def read_direct_state(
        self,
        connection_id: str,
        query: DirectCampaignStateReadQuery,
    ) -> DirectCampaignStateBlock:
        self._authorize(connection_id, query.account, query.campaign)
        now = self._clock()
        return DirectCampaignStateBlock(
            source="DIRECT_CAMPAIGN_STATE",
            retrieved_at=(now - timedelta(minutes=5)).isoformat(),
            watermark=(now - timedelta(minutes=10)).isoformat(),
            campaign=query.campaign,
            campaign_state="ON",
            group_state="ON",
            ad_state="ON",
            strategy="HIGHEST_POSITION",
            current_weekly_budget_micros=(
                self._resources.initial_weekly_budget_micros
            ),
            budget_period_start=(now - timedelta(days=7)).isoformat(),
            budget_period_end=now.isoformat(),
            current_search_bid_micros=100_000_000,
            ad_variant="A",
            object_config_version="direct-test-resources-v1",
            last_change_author=self._resources.trusted_change_author,
            last_change_occurred_at=(now - timedelta(days=8)).isoformat(),
        )

    def authorizes_change_author(
        self,
        connection_id: str,
        author: str,
    ) -> bool:
        if connection_id != self._resources.connection_id:
            raise DirectReadAuthorizationError(
                "The TEST connection does not authorize this Direct scope."
            )
        return author == self._resources.trusted_change_author

    def _authorize(
        self,
        connection_id: str,
        account_id: str,
        campaign_id: str,
    ) -> None:
        if (
            connection_id != self._resources.connection_id
            or account_id != self._resources.account_id
            or campaign_id != self._resources.campaign_id
        ):
            raise DirectReadAuthorizationError(
                "The TEST connection does not authorize this Direct scope."
            )


def build_direct_test_module_v1(
    settings: StandaloneRuntimeSettingsV1,
    decisions: ModuleDecisionRecordStoreV1,
) -> ModuleV1:
    if (
        settings.environment is not ExecutionEnvironment.TEST
        or settings.test_resources_path is None
    ):
        raise ValueError("Direct TEST composition requires explicit TEST resources.")
    resources = DirectTestResourcesV1.from_path(settings.test_resources_path)
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    test_root = settings.state_dir / "direct-test"
    test_root.mkdir(parents=True, exist_ok=True)
    provider = DirectTestReadProviderV1(resources, clock)
    target = (
        f"{resources.organization_id}:{resources.connection_id}:"
        f"{resources.account_id}:{resources.campaign_id}:"
        "INCREASE_WEEKLY_BUDGET"
    )
    action_runtime = DirectActionRuntimeV1(
        policy=resources.policy,
        state=DurableControlState(test_root / "control.sqlite3"),
        proposal_store=ImmutableProposalStore(test_root / "proposals"),
        trigger_store=MonitoringStore(test_root / "monitoring.sqlite3"),
        test_adapter=FakeWriteAdapter(
            initial_state={
                target: resources.initial_weekly_budget_micros,
            }
        ),
        environment=ExecutionEnvironment.TEST,
    )
    campaign_store = CampaignSagaStore(test_root / "campaigns.sqlite3")
    _seed_campaign_authority(resources, campaign_store, clock())
    campaign_adapter = SealedDirectCampaignCreationTestAdapterV1(
        policy=resources.policy,
        store=campaign_store,
        safety_bindings=CampaignDraftSafetyBindings(
            allowed_landing_hosts=resources.allowed_landing_hosts,
            prohibited_phrases=resources.prohibited_phrases,
            prepared_media_references=resources.prepared_media_references,
        ),
        provider_adapter=FakeDirectManagementAdapter(),
        environment=ExecutionEnvironment.TEST,
    )
    campaign_runtime = DirectCampaignCreationRuntimeV1(
        connection_id=resources.connection_id,
        account_id=resources.account_id,
        credential_profile="DIRECT_TEST_WRITE",
        test_adapter=campaign_adapter,
        environment=ExecutionEnvironment.TEST,
    )
    return DirectModuleV1(
        clock=clock,
        decision_records=decisions,
        provider_reader=provider,
        action_runtime=action_runtime,
        campaign_creation_runtime=campaign_runtime,
        impact_policy=resources.policy,
        environment=ExecutionEnvironment.TEST,
    )


def direct_test_diagnostics_v1(
    settings: StandaloneRuntimeSettingsV1,
) -> Mapping[str, Any]:
    try:
        assert settings.test_resources_path is not None
        resources = DirectTestResourcesV1.from_path(settings.test_resources_path)
    except (AssertionError, OSError, TypeError, ValueError):
        return {
            "mode": "TEST_ADAPTER",
            "configuration_ready": False,
            "resource_schema": "direct-test-resources-v1",
            "read_credentials": [],
        }
    return {
        "mode": "TEST_ADAPTER",
        "configuration_ready": True,
        "resource_schema": "direct-test-resources-v1",
        "bound_connection": resources.connection_id,
        "bound_account": resources.account_id,
        "bound_campaign": resources.campaign_id,
        "read_credentials": [],
    }


def approve_direct_test_proposal_v1(
    *,
    state_dir: Path,
    resources_path: Path,
    proposal_id: str,
    reason: str,
    now: datetime,
    authenticator: PrincipalAuthenticatorV1 | None = None,
) -> str:
    resources = DirectTestResourcesV1.from_path(resources_path)
    expected = resources.approver
    identity = authenticate_exact_local_principal_v1(
        expected,
        authenticator,
    )
    approval = DurableControlState(
        state_dir / "direct-test" / "control.sqlite3"
    ).grant_approval(
        proposal_id=proposal_id,
        expires_at=now + timedelta(minutes=15),
        reason=reason,
        principal=identity,
        now=now,
        expected_principal=expected,
    )
    return str(approval.approval_id)


def _seed_campaign_authority(
    resources: DirectTestResourcesV1,
    store: CampaignSagaStore,
    now: datetime,
) -> None:
    approver = resources.policy["principals"]["approver"]
    for item in resources.campaign_authorizations:
        draft = CampaignDraftV1.from_mapping(item["draft"])
        request = CampaignCreationRequest(
            run_id=item["run_id"],
            execution_key=item["execution_key"],
            proposal_id=item["proposal_id"],
            approval_id=item["approval_id"],
            account=resources.account_id,
            credential_profile="DIRECT_PILOT_WRITE",
            reservation_id=item["reservation_id"],
            draft=draft,
        )
        expires_at = _timestamp(item["expires_at"], "expires_at")
        store.register_creation_reservation(
            CreationReservation(
                reservation_id=request.reservation_id,
                status=CreationReservationStatus.AVAILABLE,
                scope_binding=resources.account_id,
                object_type=draft.campaign_type,
                proposal_id=request.proposal_id,
                credential_profile=request.credential_profile,
                expires_at=expires_at,
            ),
            now,
        )
        store.register_campaign_approval(
            CampaignApproval(
                approval_id=request.approval_id,
                proposal_id=request.proposal_id,
                binding_hash=request.approval_binding(resources.policy_id),
                approver=_text(approver["identity"], "approver.identity"),
                authentication=_text(
                    approver["authentication"],
                    "approver.authentication",
                ),
                expires_at=expires_at,
            )
        )


def _campaign_authorization(value: Any) -> Mapping[str, Any]:
    expected = {
        "run_id",
        "execution_key",
        "proposal_id",
        "approval_id",
        "reservation_id",
        "expires_at",
        "draft",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("A campaign authorization has unexpected fields.")
    for name in expected - {"draft"}:
        _text(value[name], "campaign_authorizations." + name)
    CampaignDraftV1.from_mapping(value["draft"])
    _timestamp(value["expires_at"], "campaign_authorizations.expires_at")
    return dict(value)


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("TEST resource JSON is unavailable.") from error
    if not isinstance(value, dict):
        raise TypeError("TEST resource JSON must contain one object.")
    return value


def _validate_direct_policy(policy: Mapping[str, Any]) -> None:
    _text(policy.get("policy_id"), "policy.policy_id")
    approver = _mapping(
        _mapping(policy.get("principals"), "policy.principals").get("approver"),
        "policy.principals.approver",
    )
    _text(approver.get("identity"), "policy.approver.identity")
    _text(approver.get("authentication"), "policy.approver.authentication")
    required_paths = (
        ("timing", "cooldown_hours"),
        ("timing", "observation_window_hours"),
        ("timing", "direct_freshness_minutes"),
        ("timing", "metrika_freshness_hours"),
        ("timing", "maximum_watermark_skew_hours"),
        ("limits", "maximum_step_percent"),
        ("limits", "mandate_actions_per_24h"),
        ("limits", "maximum_daily_cumulative_change_percent"),
        ("limits", "application_daily_spend_rub"),
        ("limits", "platform_weekly_spend_rub"),
        ("bindings", "simulation"),
        ("bindings", "pilot"),
        ("actions", "controlled_pilot_reversible"),
        ("campaign", "type"),
        ("campaign", "placement"),
        ("campaign", "search_strategy"),
        ("campaign", "network_strategy"),
        ("conversion", "primary"),
    )
    for parent, child in required_paths:
        container = _mapping(policy.get(parent), "policy." + parent)
        if child not in container:
            raise ValueError(f"policy.{parent}.{child} is required.")
    if not isinstance(policy.get("api_matrix"), list):
        raise TypeError("policy.api_matrix must be an array.")


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(field + " must be an object.")
    return value


def _relative_path(owner: Path, value: Any, field: str) -> Path:
    path = Path(_text(value, field))
    return path if path.is_absolute() else owner.parent / path


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(field + " must be non-empty text.")
    return value


def _texts(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(field + " must be an array.")
    return tuple(_text(item, field) for item in value)


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value, field).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(field + " must be ISO-8601.") from error
    if parsed.tzinfo is None:
        raise ValueError(field + " must be timezone-aware.")
    return parsed.astimezone(timezone.utc)


def _dates(start: str, end: str) -> tuple[date, ...]:
    first = date.fromisoformat(start)
    last = date.fromisoformat(end)
    return tuple(
        first + timedelta(days=offset)
        for offset in range((last - first).days + 1)
    )


__all__ = [
    "DirectTestResourcesV1",
    "approve_direct_test_proposal_v1",
    "build_direct_test_module_v1",
    "direct_test_diagnostics_v1",
]
