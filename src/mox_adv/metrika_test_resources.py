"""Explicit socket-free TEST composition for the installed Metrika edition."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mox_adv.control_state import (
    AuthenticatedPrincipal,
    PrincipalAuthenticatorV1,
    authenticate_exact_local_principal_v1,
)
from mox_adv.environment import ExecutionEnvironment
from mox_adv.goal_adapters import (
    FakeMetrikaGoalAdapter,
    FakeSitePublishAdapter,
)
from mox_adv.goal_contracts import (
    AuthorityKind,
    CreationReservation,
    GoalAuthority,
    goal_creation_binding,
    site_publish_binding,
    site_publish_diff,
    validate_candidate,
)
from mox_adv.goal_service import GoalLifecycleService
from mox_adv.goal_store import GoalLifecycleStore
from mox_adv.metrika_goal_lifecycle import (
    BoundMetrikaGoalLifecycleProviderV1,
)
from mox_adv.module_api.v1 import (
    GoalCandidateInputV1,
    ModuleDecisionRecordStoreV1,
    ModuleV1,
)
from mox_adv.module_cli import StandaloneRuntimeSettingsV1
from mox_adv.modules.metrika import MetrikaModuleV1
from mox_adv.test_resource_validation import (
    json_object_v1 as _json_object,
)
from mox_adv.test_resource_validation import (
    principal_v1 as _principal,
)
from mox_adv.test_resource_validation import (
    relative_path_v1 as _relative_path,
)
from mox_adv.test_resource_validation import (
    required_text_v1 as _text,
)
from mox_adv.test_resource_validation import (
    utc_timestamp_v1 as _timestamp,
)


@dataclass(frozen=True)
class MetrikaTestResourcesV1:
    path: Path
    policy: Mapping[str, Any]
    connection_id: str
    counter_id: str
    site_zone: str
    site_version: str
    site_publish_credential_profile: str
    mandate_issuer: AuthenticatedPrincipal
    approver: AuthenticatedPrincipal
    product_signoff: AuthenticatedPrincipal
    goal_authorizations: tuple[Mapping[str, Any], ...]

    @classmethod
    def from_path(cls, path: Path) -> MetrikaTestResourcesV1:
        value = _json_object(path)
        expected = {
            "schema_version",
            "policy_path",
            "connection_id",
            "counter_id",
            "site_zone",
            "site_version",
            "site_publish_credential_profile",
            "principals",
            "goal_authorizations",
        }
        if set(value) != expected or value["schema_version"] != (
            "metrika-test-resources-v1"
        ):
            raise ValueError("Metrika TEST resources have unexpected fields.")
        policy = _json_object(
            _relative_path(path, value["policy_path"], "policy_path")
        )
        principals = value["principals"]
        if not isinstance(principals, dict) or set(principals) != {
            "mandate_issuer",
            "approver",
            "product_signoff",
        }:
            raise ValueError("Metrika TEST principals are invalid.")
        authorizations = value["goal_authorizations"]
        if not isinstance(authorizations, list):
            raise TypeError("goal_authorizations must be an array.")
        parsed = cls(
            path=path,
            policy=policy,
            connection_id=_text(value["connection_id"], "connection_id"),
            counter_id=_text(value["counter_id"], "counter_id"),
            site_zone=_text(value["site_zone"], "site_zone"),
            site_version=_text(value["site_version"], "site_version"),
            site_publish_credential_profile=_required_profile(
                value["site_publish_credential_profile"]
            ),
            mandate_issuer=_principal(
                principals["mandate_issuer"],
                "principals.mandate_issuer",
            ),
            approver=_principal(
                principals["approver"],
                "principals.approver",
            ),
            product_signoff=_principal(
                principals["product_signoff"],
                "principals.product_signoff",
            ),
            goal_authorizations=tuple(
                _goal_authorization(item) for item in authorizations
            ),
        )
        parsed._validate_policy_bindings()
        parsed._validate_policy_principals()
        _text(parsed.policy.get("policy_id"), "policy.policy_id")
        for item in parsed.goal_authorizations:
            candidate = GoalCandidateInputV1.from_dict(item["candidate"])
            validate_candidate(candidate.as_legacy_payload(), parsed.policy)
        return parsed

    @property
    def policy_id(self) -> str:
        return _text(self.policy.get("policy_id"), "policy.policy_id")

    def _validate_policy_bindings(self) -> None:
        try:
            simulation = self.policy["bindings"]["simulation"]
            policy_counter = simulation["test_counter"]
            policy_site_zone = simulation["test_site_zone"]
        except (KeyError, TypeError) as error:
            raise ValueError("The policy lacks TEST resource bindings.") from error
        if self.counter_id != policy_counter or self.site_zone != policy_site_zone:
            raise ValueError(
                "Metrika TEST resources must match the policy TEST bindings."
            )

    def _validate_policy_principals(self) -> None:
        try:
            policy_principals = self.policy["principals"]
        except (KeyError, TypeError) as error:
            raise ValueError("The policy lacks TEST authority roles.") from error
        expected = {
            "mandate_issuer": self.mandate_issuer,
            "approver": self.approver,
            "product_signoff": self.product_signoff,
        }
        for role, configured in expected.items():
            if configured != _principal(
                policy_principals.get(role),
                "policy.principals." + role,
            ):
                raise ValueError(
                    f"Metrika TEST principal {role} does not match the policy."
                )


class _ConfiguredTestPrincipal:
    def __init__(self, principal: AuthenticatedPrincipal) -> None:
        self._principal = principal

    def authenticate(self) -> AuthenticatedPrincipal:
        return self._principal


def build_metrika_test_module_v1(
    settings: StandaloneRuntimeSettingsV1,
    decisions: ModuleDecisionRecordStoreV1,
) -> ModuleV1:
    if (
        settings.environment is not ExecutionEnvironment.TEST
        or settings.test_resources_path is None
    ):
        raise ValueError("Metrika TEST composition requires explicit TEST resources.")
    resources = MetrikaTestResourcesV1.from_path(settings.test_resources_path)
    test_root = settings.state_dir / "metrika-test"
    test_root.mkdir(parents=True, exist_ok=True)
    store = GoalLifecycleStore(test_root / "goals.sqlite3")
    _seed_goal_authority(resources, store)
    lifecycle = GoalLifecycleService(
        resources.policy,
        store,
        FakeMetrikaGoalAdapter((resources.counter_id,)),
        FakeSitePublishAdapter(
            {
                resources.site_zone: resources.site_version,
            }
        ),
        _ConfiguredTestPrincipal(resources.product_signoff),
        environment=ExecutionEnvironment.TEST,
    )
    provider = BoundMetrikaGoalLifecycleProviderV1(
        connection_id=resources.connection_id,
        counter_id=resources.counter_id,
        credential_profile="METRIKA_TEST_WRITE",
        lifecycle=lifecycle,
    )
    return MetrikaModuleV1(
        clock=lambda: datetime.now(timezone.utc),
        decision_records=decisions,
        goal_lifecycle_provider=provider,
    )


def metrika_test_diagnostics_v1(
    settings: StandaloneRuntimeSettingsV1,
) -> Mapping[str, Any]:
    try:
        assert settings.test_resources_path is not None
        resources = MetrikaTestResourcesV1.from_path(settings.test_resources_path)
    except (AssertionError, OSError, TypeError, ValueError):
        return {
            "mode": "TEST_ADAPTER",
            "configuration_ready": False,
            "resource_schema": "metrika-test-resources-v1",
            "read_credentials": [],
        }
    return {
        "mode": "TEST_ADAPTER",
        "configuration_ready": True,
        "resource_schema": "metrika-test-resources-v1",
        "bound_connection": resources.connection_id,
        "bound_counter": resources.counter_id,
        "bound_site_zone": resources.site_zone,
        "read_credentials": [],
    }


def authorize_metrika_site_publish_v1(
    *,
    state_dir: Path,
    resources_path: Path,
    candidate_id: str,
    authority_id: str,
    now: datetime,
    authenticator: PrincipalAuthenticatorV1 | None = None,
) -> str:
    """Register one explicit, short-lived TEST-site publication approval."""

    resources = MetrikaTestResourcesV1.from_path(resources_path)
    store = GoalLifecycleStore(
        state_dir / "metrika-test" / "goals.sqlite3"
    )
    candidate = store.load_candidate(candidate_id)
    if candidate.counter_id != resources.counter_id:
        raise ValueError("The candidate is outside the configured TEST counter.")
    identity = authenticate_exact_local_principal_v1(
        resources.approver,
        authenticator,
    )
    exact_diff = site_publish_diff(
        candidate,
        resources.site_zone,
        resources.site_version,
    )
    store.register_authority(
        GoalAuthority(
            authority_id=authority_id,
            kind=AuthorityKind.APPROVAL,
            principal=identity.identity,
            authentication=identity.authentication,
            proposal_id=candidate.proposal_id,
            counter_id=resources.counter_id,
            site_zone=resources.site_zone,
            allowed_actions=("SITE_PUBLISH",),
            expires_at=now.astimezone(timezone.utc) + timedelta(minutes=15),
            policy_id=resources.policy_id,
            binding_hash=site_publish_binding(
                policy_id=resources.policy_id,
                candidate=candidate,
                exact_diff=exact_diff,
                credential_profile=resources.site_publish_credential_profile,
            ),
        )
    )
    return authority_id


def _seed_goal_authority(
    resources: MetrikaTestResourcesV1,
    store: GoalLifecycleStore,
) -> None:
    for item in resources.goal_authorizations:
        candidate = dict(item["candidate"])
        legacy_candidate = {
            **candidate,
            "schema_version": "goal-candidate-v1",
        }
        expires_at = _timestamp(item["expires_at"], "expires_at")
        reservation = CreationReservation(
            reservation_id=item["reservation_id"],
            scope_binding="test_counter",
            object_type="METRIKA_GOAL",
            proposal_id=item["proposal_id"],
            credential_profile="METRIKA_TEST_WRITE",
            expires_at=expires_at,
        )
        authority = GoalAuthority(
            authority_id=item["authority_id"],
            kind=AuthorityKind.MANDATE,
            principal=resources.mandate_issuer.identity,
            authentication=resources.mandate_issuer.authentication,
            proposal_id=item["proposal_id"],
            counter_id=resources.counter_id,
            site_zone=resources.site_zone,
            allowed_actions=("GOAL_AUTHORING",),
            expires_at=expires_at,
            policy_id=resources.policy_id,
            binding_hash=goal_creation_binding(
                policy_id=resources.policy_id,
                run_id=item["run_id"],
                candidate_id="candidate-" + item["run_id"],
                proposal_id=item["proposal_id"],
                reservation_id=item["reservation_id"],
                counter_id=resources.counter_id,
                site_zone=resources.site_zone,
                credential_profile="METRIKA_TEST_WRITE",
                payload=legacy_candidate,
            ),
        )
        store.register_reservation(reservation)
        store.register_authority(authority)


def _goal_authorization(value: Any) -> Mapping[str, Any]:
    expected = {
        "run_id",
        "proposal_id",
        "reservation_id",
        "authority_id",
        "expires_at",
        "candidate",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("A goal authorization has unexpected fields.")
    for name in expected - {"candidate"}:
        _text(value[name], "goal_authorizations." + name)
    candidate = value["candidate"]
    if not isinstance(candidate, dict) or candidate.get("schema_version") != (
        "goal-candidate-input-v1"
    ):
        raise ValueError("A goal authorization candidate is invalid.")
    GoalCandidateInputV1.from_dict(candidate)
    _timestamp(value["expires_at"], "goal_authorizations.expires_at")
    return dict(value)


def _required_profile(value: Any) -> str:
    profile = _text(value, "site_publish_credential_profile")
    if profile != "TEST_SITE_PUBLISH":
        raise ValueError(
            "site_publish_credential_profile must be TEST_SITE_PUBLISH."
        )
    return profile


__all__ = [
    "MetrikaTestResourcesV1",
    "authorize_metrika_site_publish_v1",
    "build_metrika_test_module_v1",
    "metrika_test_diagnostics_v1",
]
