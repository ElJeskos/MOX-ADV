from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mox_adv.approval_execution import (
    ApprovalExecutionService,
    ExecutionFacts,
    ExecutionRequest,
)
from mox_adv.autonomy_contracts import BoundedAutonomyRequest
from mox_adv.autonomy_execution import BoundedAutonomyService
from mox_adv.control_state import DurableControlState, TrustedScope
from mox_adv.direct_management import (
    DirectManagementConnectorV1,
    DirectStateTransitionRejected,
    FakeDirectManagementAdapter,
)
from mox_adv.egress import (
    CredentialProfile,
    EgressAuthority,
    EgressDenied,
    HttpEgressGuard,
)
from mox_adv.environment import EnvironmentWriteDenied, ExecutionEnvironment
from mox_adv.fake_write_adapter import FakeWriteAdapter
from mox_adv.goal_lifecycle import (
    FakeMetrikaGoalAdapter,
    FakeSitePublishAdapter,
    GoalLifecycleRejected,
    GoalLifecycleService,
    GoalLifecycleStore,
)
from mox_adv.host_launcher import (
    CredentialProfileRejected,
    resolve_keychain_binding,
)
from mox_adv.mandate_signing import HMACMandateSigner
from mox_adv.mandate_store import DurableMandateAuthority
from mox_adv.module_api.v1 import (
    HttpJsonModuleAdapterV1,
    InMemoryDecisionRecordStoreV1,
    InProcessModuleAdapterV1,
    ModuleExecutionResultV1,
    ModuleIdentityV1,
    ModuleRequestV1,
    ModuleResultV1,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "gate0-policy.json"
PRODUCTION_WRITE_FORBIDDEN = "PRODUCTION_WRITE_FORBIDDEN"


def request_payload(
    module_id: str,
    operation_type: str,
    *,
    environment: str,
) -> dict[str, Any]:
    scope: dict[str, str] = {
        "organization_id": "customer-42",
        "campaign_id": "campaign-7",
    }
    connection_id = "customer-direct"
    if module_id == "YANDEX_METRIKA":
        scope = {
            "organization_id": "customer-42",
            "counter_id": "counter-9",
            "goal_id": "goal-3",
        }
        connection_id = "customer-metrika"
    payload: dict[str, Any] = {
        "schema_version": "module-request-v1",
        "connection_ref": {"connection_id": connection_id},
        "environment": environment,
        "scope": scope,
        "period": {
            "start_date": "2026-07-01",
            "end_date": "2026-07-29",
            "timezone": "Europe/Moscow",
        },
        "objective": {
            "code": "SAFE_CHANGE",
            "description": "Exercise one approved changing operation.",
        },
        "external_evidence": {
            "schema_version": "normalized-metrics-evidence-v1",
            "evidence_id": "customer-evidence-17",
            "source": "CUSTOMER_ECOSYSTEM",
            "observed_at": "2026-07-30T09:00:00+00:00",
            "watermark": "2026-07-30T08:55:00+00:00",
            "metrics": [
                {
                    "name": "conversions",
                    "value": 21,
                    "unit": "COUNT",
                }
            ],
        },
        "operation": {
            "kind": "EXECUTE",
            "operation_type": operation_type,
        },
        "idempotency_key": "customer-run-" + operation_type.lower(),
    }
    if operation_type == "MANAGE_GOAL_CANDIDATE":
        payload.pop("external_evidence")
        payload["goal_lifecycle_command"] = {
            "schema_version": "goal-lifecycle-command-v1",
            "action": "CREATE_CANDIDATE",
            "run_id": "safety-goal-run",
            "proposal_id": "safety-goal-proposal",
            "reservation_id": "safety-goal-reservation",
            "authority_id": "safety-goal-authority",
            "candidate": {
                "schema_version": "goal-candidate-input-v1",
                "name": "Safety candidate",
                "event": "lead_submitted",
                "site_location": "#lead-form",
                "type": "ACTION",
                "business_meaning": "Exercise the environment guard.",
                "priority": 1,
                "duplicate_signals": [],
            },
        }
    elif operation_type == "CREATE_CAMPAIGN":
        payload.pop("external_evidence")
        payload["scope"] = {
            "organization_id": "customer-42",
            "account_id": "account-8",
        }
        execution_key = "customer-run-create-campaign"
        payload["idempotency_key"] = execution_key
        payload["campaign_creation_command"] = {
            "schema_version": "campaign-creation-command-v1",
            "command": "CREATE_CAMPAIGN",
            "run_id": "safety-campaign-run",
            "execution_key": execution_key,
            "proposal_id": "safety-campaign-proposal",
            "approval_id": "safety-campaign-approval",
            "reservation_id": "safety-campaign-reservation",
            "draft": {
                "schema_version": "campaign-draft-v1",
                "draft_id": "safety-campaign-draft",
                "business_goal": {
                    "event": "lead_submitted",
                    "meaning": "A visitor submitted the lead form.",
                },
                "primary_conversion": {"event": "lead_submitted"},
                "campaign_type": "UNIFIED_CAMPAIGN",
                "strategy": {
                    "placement": "SEARCH",
                    "search": "HIGHEST_POSITION",
                    "network": "SERVING_OFF",
                },
                "geography": ["RU"],
                "schedule": {
                    "timezone": "Europe/Moscow",
                    "days": ["MONDAY"],
                    "start": "09:00",
                    "end": "18:00",
                },
                "budget": {
                    "currency": "RUB",
                    "weekly_micros": 500_000_000,
                },
                "limits": {
                    "maximum_weekly_micros": 500_000_000,
                    "maximum_bid_micros": 100_000_000,
                },
                "groups": [
                    {
                        "name": "Lead service",
                        "keywords": ["lead service"],
                        "negative_keywords": ["free"],
                        "audiences": [],
                        "ads": [
                            {
                                "variant_id": "A",
                                "title": "Lead service",
                                "text": "Submit a request",
                                "landing_page": ("https://allowlisted.example/lead"),
                                "utm": "utm_source=yandex&utm_content=a",
                                "media_reference": "prepared-media-1",
                            },
                            {
                                "variant_id": "B",
                                "title": "Lead service alternative",
                                "text": "Request a consultation",
                                "landing_page": ("https://allowlisted.example/lead"),
                                "utm": "utm_source=yandex&utm_content=b",
                                "media_reference": "prepared-media-2",
                            },
                        ],
                    }
                ],
                "landing_page": "https://allowlisted.example/lead",
                "media_references": [
                    "prepared-media-1",
                    "prepared-media-2",
                ],
            },
        }
    return payload


class RecordingWriteModule:
    def __init__(self, module_id: str) -> None:
        self.identity = ModuleIdentityV1(
            module_id=module_id,
            module_version="1.0.0",
        )
        self.credential_resolutions = 0
        self.write_http_requests = 0

    def invoke(self, request: ModuleRequestV1) -> ModuleResultV1:
        self.credential_resolutions += 1
        self.write_http_requests += 1
        return ModuleResultV1(
            schema_version="module-result-v1",
            run_id="test-execution",
            module=self.identity,
            status="SUCCEEDED",
            metrics=(),
            assessment=None,
            recommendations=(),
            proposal=None,
            execution_result=ModuleExecutionResultV1(
                execution_id="test-execution",
                operation_type=request.operation.operation_type,
                status="APPLIED",
                applied=True,
            ),
            provenance=(),
            warnings=(),
            errors=(),
            decision_record_ref="decision-records/test-execution.json",
        )


class ModuleEnvironmentSafetyE2ETests(unittest.TestCase):
    def test_public_adapter_composition_requires_a_closed_trusted_environment(
        self,
    ) -> None:
        implementation = RecordingWriteModule("YANDEX_DIRECT")
        for adapter_type in (
            HttpJsonModuleAdapterV1.for_embedded,
            InProcessModuleAdapterV1,
        ):
            adapter_factory: Any = adapter_type
            with self.subTest(adapter=adapter_type.__name__):
                with self.assertRaises(TypeError):
                    adapter_factory(implementation)
                with self.assertRaises(EnvironmentWriteDenied):
                    adapter_factory(implementation, environment="STAGING")

    def test_every_public_write_command_is_blocked_before_credentials_and_http(
        self,
    ) -> None:
        cases = (
            ("YANDEX_DIRECT", "APPLY_OPTIMIZATION"),
            ("YANDEX_DIRECT", "CREATE_CAMPAIGN"),
            ("YANDEX_METRIKA", "MANAGE_GOAL_CANDIDATE"),
        )
        for module_id, operation_type in cases:
            for adapter_kind in ("HTTP_JSON", "IN_PROCESS"):
                with self.subTest(
                    module_id=module_id,
                    operation_type=operation_type,
                    adapter_kind=adapter_kind,
                ):
                    implementation = RecordingWriteModule(module_id)
                    records = InMemoryDecisionRecordStoreV1()
                    payload = request_payload(
                        module_id,
                        operation_type,
                        environment="PRODUCTION",
                    )
                    if adapter_kind == "HTTP_JSON":
                        response = HttpJsonModuleAdapterV1.for_embedded(
                            implementation,
                            environment=ExecutionEnvironment.PRODUCTION,
                            decision_records=records,
                        ).handle(payload)
                        self.assertEqual(422, response.status_code)
                        result = response.body
                    else:
                        typed_request = ModuleRequestV1.from_dict(payload)
                        result = (
                            InProcessModuleAdapterV1(
                                implementation,
                                environment=ExecutionEnvironment.PRODUCTION,
                                decision_records=records,
                            )
                            .invoke(typed_request)
                            .as_dict()
                        )

                    self.assertEqual("BLOCKED", result["status"])
                    self.assertEqual(
                        PRODUCTION_WRITE_FORBIDDEN,
                        result["errors"][0]["code"],
                    )
                    self.assertEqual(
                        "BLOCKED",
                        result["execution_result"]["status"],
                    )
                    self.assertFalse(result["execution_result"]["applied"])
                    self.assertEqual(0, implementation.credential_resolutions)
                    self.assertEqual(0, implementation.write_http_requests)
                    reference = result["decision_record_ref"]
                    self.assertIsInstance(reference, str)
                    record = records.read(reference)
                    self.assertEqual("BLOCKED", record["outcome"])
                    self.assertEqual(
                        PRODUCTION_WRITE_FORBIDDEN,
                        record["reason_code"],
                    )
                    self.assertEqual(operation_type, record["operation_type"])
                    self.assertEqual(
                        "PRODUCTION",
                        record["trusted_environment"],
                    )

    def test_retry_restart_external_evidence_and_adapter_choice_cannot_bypass_guard(
        self,
    ) -> None:
        implementation = RecordingWriteModule("YANDEX_DIRECT")
        payload = request_payload(
            "YANDEX_DIRECT",
            "APPLY_OPTIMIZATION",
            environment="TEST",
        )
        payload["external_evidence"]["metrics"].append(
            {"name": "approval", "value": "approved", "unit": "STATE"}
        )
        for adapter_name in ("HTTP_JSON", "IN_PROCESS"):
            records = InMemoryDecisionRecordStoreV1()
            with self.subTest(adapter=adapter_name):
                if adapter_name == "HTTP_JSON":
                    http_adapter = HttpJsonModuleAdapterV1.for_embedded(
                        implementation,
                        environment=ExecutionEnvironment.PRODUCTION,
                        decision_records=records,
                    )
                    results = [
                        http_adapter.handle(copy.deepcopy(payload)).body,
                        http_adapter.handle(copy.deepcopy(payload)).body,
                        HttpJsonModuleAdapterV1.for_embedded(
                            implementation,
                            environment=ExecutionEnvironment.PRODUCTION,
                            decision_records=records,
                        )
                        .handle(copy.deepcopy(payload))
                        .body,
                    ]
                else:
                    typed_request = ModuleRequestV1.from_dict(copy.deepcopy(payload))
                    in_process_adapter = InProcessModuleAdapterV1(
                        implementation,
                        environment=ExecutionEnvironment.PRODUCTION,
                        decision_records=records,
                    )
                    results = [
                        in_process_adapter.invoke(typed_request).as_dict(),
                        in_process_adapter.invoke(typed_request).as_dict(),
                        InProcessModuleAdapterV1(
                            implementation,
                            environment=ExecutionEnvironment.PRODUCTION,
                            decision_records=records,
                        )
                        .invoke(typed_request)
                        .as_dict(),
                    ]
                for result in results:
                    self.assertEqual("BLOCKED", result["status"])
                    self.assertEqual(
                        PRODUCTION_WRITE_FORBIDDEN,
                        result["errors"][0]["code"],
                    )
                self.assertEqual(
                    1,
                    len({result["decision_record_ref"] for result in results}),
                )
        self.assertEqual(0, implementation.credential_resolutions)
        self.assertEqual(0, implementation.write_http_requests)

    def test_explicit_test_environment_reaches_the_approved_test_implementation(
        self,
    ) -> None:
        for module_id, operation_type in (
            ("YANDEX_DIRECT", "APPLY_OPTIMIZATION"),
            ("YANDEX_DIRECT", "CREATE_CAMPAIGN"),
            ("YANDEX_METRIKA", "MANAGE_GOAL_CANDIDATE"),
        ):
            with self.subTest(module_id=module_id, operation_type=operation_type):
                implementation = RecordingWriteModule(module_id)
                response = HttpJsonModuleAdapterV1.for_embedded(
                    implementation,
                    environment=ExecutionEnvironment.TEST,
                ).handle(
                    request_payload(
                        module_id,
                        operation_type,
                        environment="TEST",
                    )
                )
                self.assertEqual(200, response.status_code)
                self.assertEqual("SUCCEEDED", response.body["status"])
                self.assertEqual(1, implementation.credential_resolutions)
                self.assertEqual(1, implementation.write_http_requests)


class LegacyEnvironmentSafetyE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        record = self.policy["record"]
        record["production_write_authorized"] = True
        pilot = self.policy["bindings"]["pilot"]
        pilot["direct_account"] = "pilot-account"
        pilot["test_counter"] = "test-counter"
        pilot["test_site_zone"] = "test-site-zone"

    def test_production_http_guard_blocks_all_provider_write_classes(
        self,
    ) -> None:
        guard = HttpEgressGuard(
            self.policy,
            environment=ExecutionEnvironment.PRODUCTION,
        )
        cases = tuple(
            item
            for item in self.policy["api_matrix"]
            if not str(item["method"]).lower().startswith("get")
        )
        self.assertEqual(
            {
                ("Campaigns", "add"),
                ("Campaigns", "update"),
                ("Campaigns", "suspend"),
                ("Campaigns", "resume"),
                ("Campaigns", "archive"),
                ("Campaigns", "unarchive"),
                ("Campaigns", "delete"),
                ("AdGroups", "add"),
                ("AdGroups", "update"),
                ("AdGroups", "delete"),
                ("Ads", "add"),
                ("Ads", "update"),
                ("Ads", "suspend"),
                ("Ads", "resume"),
                ("Ads", "archive"),
                ("Ads", "unarchive"),
                ("Ads", "moderate"),
                ("Ads", "delete"),
                ("Keywords", "add"),
                ("Keywords", "update"),
                ("Keywords", "suspend"),
                ("Keywords", "resume"),
                ("Keywords", "delete"),
                ("KeywordBids", "set"),
                ("Goals", "addGoal"),
                ("Goals", "deleteGoal"),
                ("BrowserTag", "reachGoal"),
            },
            {(str(item["service"]), str(item["method"])) for item in cases},
        )
        for item in cases:
            path = (
                str(item["path"])
                .replace("{counter_id}", "test-counter")
                .replace("{goal_id}", "goal-1")
            )
            system = str(item["system"])
            if system == "DIRECT":
                authority = EgressAuthority(
                    CredentialProfile.DIRECT_PILOT_WRITE,
                    "pilot-account",
                )
            elif system == "METRIKA":
                authority = EgressAuthority(
                    CredentialProfile.METRIKA_TEST_WRITE,
                    "test-counter",
                )
            else:
                authority = EgressAuthority(
                    CredentialProfile.TEST_SITE_PUBLISH,
                    "test-site-zone",
                    counter_id="test-counter",
                )
            with (
                self.subTest(
                    system=system,
                    service=item["service"],
                    operation=item["method"],
                ),
                self.assertRaisesRegex(
                    EgressDenied,
                    PRODUCTION_WRITE_FORBIDDEN,
                ),
            ):
                guard.authorize(
                    str(item["http_verb"]),
                    "https://" + str(item["host"]) + path,
                    version=str(item["version"]),
                    service=str(item["service"]),
                    operation=str(item["method"]),
                    authority=authority,
                    pilot_armed=True,
                )

    def test_legacy_environment_capability_is_required_and_closed(self) -> None:
        guard_factory: Any = HttpEgressGuard
        with self.assertRaises(TypeError):
            guard_factory(self.policy)
        with self.assertRaises(EnvironmentWriteDenied):
            guard_factory(self.policy, environment="STAGING")

    def test_production_credential_resolver_exposes_no_write_profile(self) -> None:
        expected_read_profiles = {
            "DIRECT_PROD_READ": "MOX_ADV_DIRECT_PROD_READ",
            "METRIKA_PROD_READ": "MOX_ADV_METRIKA_PROD_READ",
        }
        for profile_name, keychain_binding in expected_read_profiles.items():
            self.assertEqual(
                keychain_binding,
                resolve_keychain_binding(self.policy, profile_name),
            )
        for profile in self.policy["credentials"]["profiles"]:
            profile_name = str(profile["name"])
            if profile_name in expected_read_profiles:
                continue
            with (
                self.subTest(profile=profile_name),
                self.assertRaises(CredentialProfileRejected),
            ):
                resolve_keychain_binding(self.policy, profile_name)

    def test_production_direct_connector_blocks_even_a_fake_adapter(self) -> None:
        adapter = FakeDirectManagementAdapter()
        connector = DirectManagementConnectorV1(
            self.policy,
            adapter,
            _PermissiveRegistry(),
            environment=ExecutionEnvironment.PRODUCTION,
        )

        with self.assertRaisesRegex(
            DirectStateTransitionRejected,
            PRODUCTION_WRITE_FORBIDDEN,
        ):
            connector.campaigns_add(
                "run-1",
                "operation-1",
                {"name": "must-not-be-created"},
            )

        self.assertEqual([], adapter.calls)

    def test_production_goal_and_site_commands_stop_before_state_or_adapter(
        self,
    ) -> None:
        simulation = self.policy["bindings"]["simulation"]
        goal_adapter = FakeMetrikaGoalAdapter(
            (simulation["test_counter"], simulation["pilot_counter"])
        )
        site_adapter = FakeSitePublishAdapter(
            {
                simulation["test_site_zone"]: "test-v1",
                simulation["pilot_site_zone"]: "pilot-v1",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            service = GoalLifecycleService(
                self.policy,
                GoalLifecycleStore(Path(directory) / "goal.sqlite3"),
                goal_adapter,
                site_adapter,
                environment=ExecutionEnvironment.PRODUCTION,
            )
            commands = (
                lambda: service.create_candidate(
                    run_id="production-create",
                    proposal_id="proposal-1",
                    reservation_id="reservation-1",
                    authority_id="authority-1",
                    counter_id=simulation["test_counter"],
                    credential_profile="METRIKA_TEST_WRITE",
                    payload={},
                    now=datetime(2026, 7, 30, tzinfo=timezone.utc),
                ),
                lambda: service.publish_candidate_event(
                    candidate_id="candidate-missing",
                    authority_id="authority-1",
                    site_zone=simulation["test_site_zone"],
                    expected_version="test-v1",
                    now=datetime(2026, 7, 30, tzinfo=timezone.utc),
                ),
                lambda: service.cleanup_rejected_candidate(
                    "candidate-missing",
                    "production-cleanup",
                ),
            )
            for command in commands:
                with self.assertRaisesRegex(
                    GoalLifecycleRejected,
                    PRODUCTION_WRITE_FORBIDDEN,
                ):
                    command()

        self.assertEqual(0, goal_adapter.add_calls)
        self.assertEqual(0, goal_adapter.delete_calls)
        self.assertEqual(0, site_adapter.publish_calls)
        self.assertEqual(0, site_adapter.rollback_calls)

    def test_approval_and_mandate_cannot_enable_production_execution(self) -> None:
        scope = TrustedScope(
            organization="customer-42",
            connection="connection-1",
            account="pilot-account",
            campaign="campaign-7",
            writer="sim-executor",
        )
        with tempfile.TemporaryDirectory() as directory:
            state = DurableControlState(Path(directory) / "control.sqlite3")
            approval_adapter = FakeWriteAdapter()
            approval = ApprovalExecutionService(
                self.policy,
                state,
                approval_adapter,
                clock=lambda: datetime(2026, 7, 30, tzinfo=timezone.utc),
                environment=ExecutionEnvironment.PRODUCTION,
            )
            approval_request = ExecutionRequest(
                proposal_id="approved-proposal",
                execution_key="approved-execution",
                scope=scope,
                facts=ExecutionFacts(
                    mode="APPROVAL_REQUIRED",
                    automation_enabled=True,
                    comparability_status="COMPARABLE",
                    confidence_status="READY",
                    financial_recommendations_allowed=True,
                    direct_age_minutes=0,
                    metrika_age_minutes=0,
                    watermark_skew_minutes=0,
                    clicks=100,
                    conversions=10,
                    impressions=1000,
                    spend_rub=1000,
                    cpa_rub="100",
                    budget_utilization_percent="80",
                    ctr_percent="10",
                    campaign_state="ON",
                    campaign_strategy="HIGHEST_POSITION",
                    current_fingerprint="sha256:" + "1" * 64,
                    cooldown_active=False,
                    observation_window_active=False,
                    actions_in_last_24h=0,
                    cumulative_daily_change_percent=0,
                    monetary_exposure_rub=100,
                    kill_switch_available=True,
                ),
            )
            restarted_approval = ApprovalExecutionService(
                self.policy,
                state,
                approval_adapter,
                clock=lambda: datetime(2026, 7, 30, tzinfo=timezone.utc),
                environment=ExecutionEnvironment.PRODUCTION,
            )
            approval_results = (
                approval.execute(approval_request),
                approval.execute(approval_request),
                restarted_approval.execute(approval_request),
            )
            for approval_result in approval_results:
                self.assertEqual("BLOCKED", approval_result.status)
                self.assertEqual(
                    PRODUCTION_WRITE_FORBIDDEN,
                    approval_result.reason_code,
                )
            reconciliation = restarted_approval.reconcile(
                approval_request.execution_key
            )
            self.assertEqual("BLOCKED", reconciliation.status)
            self.assertEqual(0, approval_adapter.write_calls)

            autonomy_adapter = FakeWriteAdapter()
            mandate_authority = DurableMandateAuthority(
                state.path,
                self.policy,
                HMACMandateSigner(b"test-only-environment-safety-key"),
            )
            autonomy = BoundedAutonomyService(
                self.policy,
                state,
                mandate_authority,
                autonomy_adapter,
                clock=lambda: datetime(2026, 7, 30, tzinfo=timezone.utc),
                environment=ExecutionEnvironment.PRODUCTION,
            )
            autonomy_request = BoundedAutonomyRequest(
                mandate_id="active-mandate",
                proposal_id="mandated-proposal",
                execution_key="mandated-execution",
                scope=scope,
                mode="BOUNDED_AUTONOMY",
                automation_enabled=True,
                comparability_status="COMPARABLE",
                confidence_status="READY",
                financial_recommendations_allowed=True,
                direct_age_minutes=0,
                metrika_age_minutes=0,
                watermark_skew_minutes=0,
                clicks=100,
                conversions=10,
                spend_rub=1000,
                cpa_rub="100",
                budget_utilization_percent="80",
                campaign_state="ON",
                campaign_strategy="HIGHEST_POSITION",
                current_fingerprint="sha256:" + "1" * 64,
            )
            restarted_autonomy = BoundedAutonomyService(
                self.policy,
                state,
                mandate_authority,
                autonomy_adapter,
                clock=lambda: datetime(2026, 7, 30, tzinfo=timezone.utc),
                environment=ExecutionEnvironment.PRODUCTION,
            )
            autonomy_results = (
                autonomy.execute(autonomy_request),
                autonomy.execute(autonomy_request),
                restarted_autonomy.execute(autonomy_request),
            )
            for autonomy_result in autonomy_results:
                self.assertEqual("BLOCKED", autonomy_result.status)
                self.assertEqual(
                    PRODUCTION_WRITE_FORBIDDEN,
                    autonomy_result.reason_code,
                )
            recheck = restarted_autonomy.recheck(autonomy_request)
            self.assertEqual("BLOCKED", recheck.status)
            autonomy_reconciliation = restarted_autonomy.reconcile(
                autonomy_request.execution_key
            )
            self.assertEqual("BLOCKED", autonomy_reconciliation.status)
            self.assertEqual(0, autonomy_adapter.write_calls)


class _PermissiveRegistry:
    def object_belongs_to_run(
        self,
        run_id: str,
        service: str,
        object_id: str,
    ) -> bool:
        del run_id, service, object_id
        return True

    def production_authority_is_valid(self, authority: object) -> bool:
        del authority
        return True


if __name__ == "__main__":
    unittest.main()
