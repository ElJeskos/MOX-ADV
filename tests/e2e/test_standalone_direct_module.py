from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from unittest import mock

from mox_adv.contracts import (
    DirectCampaignStateBlock,
    DirectCampaignStateReadQuery,
    DirectReportBlock,
    DirectReportRow,
    DirectReportsReadQuery,
)
from mox_adv.environment import ExecutionEnvironment
from mox_adv.module_api.v1 import (
    ContractValidationError,
    HttpJsonModuleAdapterV1,
    InMemoryDecisionRecordStoreV1,
    ModuleRequestV1,
    ModuleResultV1,
)
from mox_adv.modules.direct import (
    BoundDirectReadProviderV1,
    DirectModuleV1,
)

ROOT = Path(__file__).resolve().parents[2]


def customer_evidence_request() -> dict[str, Any]:
    return {
        "schema_version": "module-request-v1",
        "connection_ref": {"connection_id": "customer-direct-primary"},
        "environment": "PRODUCTION",
        "scope": {
            "organization_id": "customer-42",
            "account_id": "account-8",
            "campaign_id": "campaign-7",
        },
        "period": {
            "start_date": "2026-07-23",
            "end_date": "2026-07-29",
            "timezone": "UTC",
        },
        "objective": {
            "code": "REDUCE_CPA",
            "description": "Reduce CPA without losing qualified conversions.",
        },
        "external_evidence": {
            "schema_version": "normalized-metrics-evidence-v1",
            "evidence_id": "customer-direct-evidence-17",
            "source": "CUSTOMER_ECOSYSTEM",
            "observed_at": "2026-07-30T11:55:00+00:00",
            "watermark": "2026-07-30T11:50:00+00:00",
            "metrics": [
                {"name": "impressions", "value": 10000, "unit": "COUNT"},
                {"name": "clicks", "value": 200, "unit": "COUNT"},
                {
                    "name": "cost_micros",
                    "value": 5000000000,
                    "unit": "MICROS_RUB",
                },
                {"name": "campaign_state", "value": "ON", "unit": "CODE"},
                {"name": "group_state", "value": "ON", "unit": "CODE"},
                {"name": "ad_state", "value": "ON", "unit": "CODE"},
                {
                    "name": "strategy",
                    "value": "HIGHEST_POSITION",
                    "unit": "CODE",
                },
                {
                    "name": "current_weekly_budget_micros",
                    "value": 10000000000,
                    "unit": "MICROS_RUB",
                },
                {
                    "name": "current_search_bid_micros",
                    "value": 100000000,
                    "unit": "MICROS_RUB",
                },
                {"name": "ad_variant", "value": "A", "unit": "CODE"},
                {
                    "name": "object_config_version",
                    "value": "campaign-config-v1",
                    "unit": "CODE",
                },
                {
                    "name": "budget_period_start",
                    "value": "2026-07-23T12:00:00+00:00",
                    "unit": "ISO_8601",
                },
                {
                    "name": "budget_period_end",
                    "value": "2026-07-30T12:00:00+00:00",
                    "unit": "ISO_8601",
                },
            ],
        },
        "operation": {
            "kind": "ANALYZE",
            "operation_type": "ANALYZE_PERFORMANCE",
        },
        "idempotency_key": "customer-direct-run-2026-07-30-001",
    }


def direct_action_plan_request() -> dict[str, Any]:
    request = customer_evidence_request()
    request["connection_ref"] = {"connection_id": "sim-connection"}
    request["environment"] = "TEST"
    request["scope"] = {
        "organization_id": "sim-organization",
        "account_id": "sim-direct-account",
        "campaign_id": "campaign-7",
    }
    evidence = request["external_evidence"]
    assert isinstance(evidence, dict)
    metrics = evidence["metrics"]
    assert isinstance(metrics, list)
    for metric in metrics:
        assert isinstance(metric, dict)
        if metric["name"] == "current_weekly_budget_micros":
            metric["value"] = 2_000_000_000
        elif metric["name"] == "cost_micros":
            metric["value"] = 4_000_000_000
    metrics.append({"name": "conversions", "value": 20, "unit": "COUNT"})
    request["operation"] = {
        "kind": "PLAN",
        "operation_type": "PLAN_OPTIMIZATION",
    }
    request["direct_action_command"] = {
        "schema_version": "direct-action-command-v1",
        "command": "PLAN_INTENT",
        "action": "INCREASE_WEEKLY_BUDGET",
        "relative_step_percent": 10,
    }
    request["idempotency_key"] = "direct-action-plan-17"
    return request


def campaign_draft_payload() -> dict[str, Any]:
    return {
        "schema_version": "campaign-draft-v1",
        "draft_id": "draft-headless-direct-1",
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
            "days": ["MONDAY", "TUESDAY"],
            "start": "09:00",
            "end": "18:00",
        },
        "budget": {"currency": "RUB", "weekly_micros": 500_000_000},
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
                        "landing_page": "https://allowlisted.example/lead",
                        "utm": "utm_source=yandex&utm_content=a",
                        "media_reference": "prepared-media-1",
                    },
                    {
                        "variant_id": "B",
                        "title": "Lead service alternative",
                        "text": "Request a consultation",
                        "landing_page": "https://allowlisted.example/lead",
                        "utm": "utm_source=yandex&utm_content=b",
                        "media_reference": "prepared-media-2",
                    },
                ],
            }
        ],
        "landing_page": "https://allowlisted.example/lead",
        "media_references": ["prepared-media-1", "prepared-media-2"],
    }


def campaign_creation_module_request(
    *,
    environment: str = "TEST",
    execution_key: str = "execution-headless-create-1",
) -> dict[str, Any]:
    request = customer_evidence_request()
    request["connection_ref"] = {"connection_id": "stored-test-direct"}
    request["environment"] = environment
    request["scope"] = {
        "organization_id": "sim-organization",
        "account_id": "sim-direct-account",
    }
    request.pop("external_evidence")
    request["operation"] = {
        "kind": "EXECUTE",
        "operation_type": "CREATE_CAMPAIGN",
    }
    request["idempotency_key"] = execution_key
    request["campaign_creation_command"] = {
        "schema_version": "campaign-creation-command-v1",
        "command": "CREATE_CAMPAIGN",
        "run_id": "run-headless-create-1",
        "execution_key": execution_key,
        "proposal_id": "proposal-headless-create-1",
        "approval_id": "approval-headless-create-1",
        "reservation_id": "reservation-headless-create-1",
        "draft": campaign_draft_payload(),
    }
    return request


def record_prior_applied_action(
    state: Any,
    policy: dict[str, Any],
    occurred_at: datetime,
    proposal_id: str,
) -> None:
    from mox_adv.commands import OptimizationAction
    from mox_adv.control_state import (
        AuthenticatedPrincipal,
        ExecutionStatus,
        PreparedChange,
        TrustedScope,
    )

    prepared = PreparedChange(
        proposal_id=proposal_id,
        proposal_hash="sha256:" + "1" * 64,
        scope=TrustedScope(
            organization="sim-organization",
            connection="sim-connection",
            account="sim-direct-account",
            campaign="campaign-7",
            writer="sim-executor",
        ),
        action=OptimizationAction.INCREASE_WEEKLY_BUDGET,
        current_value=1_000_000_000,
        target_value=1_100_000_000,
        expected_diff={
            "operation": "INCREASE_WEEKLY_BUDGET",
            "relative_step_percent": 10,
        },
        snapshot_id="snapshot-prior",
        snapshot_generated_at=occurred_at.isoformat(),
        direct_watermark=occurred_at.isoformat(),
        metrika_watermark=occurred_at.isoformat(),
        policy_version=str(policy["policy_id"]),
        expected_fingerprint="sha256:" + "2" * 64,
        risk="WEEKLY_BUDGET_INCREASE",
    )
    state.register_prepared_change(prepared)
    approval = state.grant_approval(
        proposal_id=prepared.proposal_id,
        expires_at=occurred_at + timedelta(minutes=15),
        reason="Seed one prior durable Direct execution.",
        principal=AuthenticatedPrincipal(
            identity="sviridov",
            authentication="authenticated_macos_user",
        ),
        now=occurred_at,
    )
    state.reserve_execution(prepared, occurred_at)
    state.begin_execution(prepared, approval, occurred_at)
    state.finish_execution(
        prepared.execution_key(),
        ExecutionStatus.APPLIED,
        None,
        occurred_at,
    )


class RecordingAuthorizedDirectReader:
    def __init__(self) -> None:
        self.report_calls: list[tuple[str, DirectReportsReadQuery]] = []
        self.state_calls: list[tuple[str, DirectCampaignStateReadQuery]] = []

    def read_direct_report(
        self,
        connection_id: str,
        query: DirectReportsReadQuery,
    ) -> DirectReportBlock:
        self.report_calls.append((connection_id, query))
        return DirectReportBlock(
            source="DIRECT_REPORTS",
            retrieved_at="2026-07-30T11:55:00+00:00",
            watermark="2026-07-30T11:50:00+00:00",
            period_start="2026-07-23",
            period_end="2026-07-29",
            timezone="UTC",
            attribution="AUTO",
            currency="RUB",
            rows=tuple(
                DirectReportRow(
                    campaign="campaign-7",
                    date=f"2026-07-{day}",
                    impressions=1000 if day < 29 else 4000,
                    clicks=20 if day < 29 else 80,
                    cost_micros=500000000 if day < 29 else 2000000000,
                )
                for day in range(23, 30)
            ),
        )

    def read_direct_state(
        self,
        connection_id: str,
        query: DirectCampaignStateReadQuery,
    ) -> DirectCampaignStateBlock:
        self.state_calls.append((connection_id, query))
        return DirectCampaignStateBlock(
            source="DIRECT_CAMPAIGN_STATE",
            retrieved_at="2026-07-30T11:54:00+00:00",
            watermark="2026-07-30T11:49:00+00:00",
            campaign="campaign-7",
            campaign_state="ON",
            group_state="ON",
            ad_state="ON",
            strategy="HIGHEST_POSITION",
            current_weekly_budget_micros=10000000000,
            budget_period_start="2026-07-23T12:00:00+00:00",
            budget_period_end="2026-07-30T12:00:00+00:00",
            current_search_bid_micros=100000000,
            ad_variant="A",
            object_config_version="campaign-config-v1",
            last_change_author="customer-42",
            last_change_occurred_at="2026-07-22T12:00:00+00:00",
        )

    def authorizes_change_author(
        self,
        connection_id: str,
        author: str,
    ) -> bool:
        return connection_id == "customer-direct-primary" and author == "customer-42"


class FailingAuthorizedDirectReader(RecordingAuthorizedDirectReader):
    def read_direct_report(
        self,
        connection_id: str,
        query: DirectReportsReadQuery,
    ) -> DirectReportBlock:
        del connection_id, query
        raise RuntimeError("provider unavailable: OAuth secret")


class MalformedAuthorizedDirectReader(RecordingAuthorizedDirectReader):
    def read_direct_report(
        self,
        connection_id: str,
        query: DirectReportsReadQuery,
    ) -> DirectReportBlock:
        report = super().read_direct_report(connection_id, query)
        return DirectReportBlock(
            source=report.source,
            retrieved_at=cast(str, 123),
            watermark=report.watermark,
            period_start=report.period_start,
            period_end=report.period_end,
            timezone=report.timezone,
            attribution=report.attribution,
            currency=report.currency,
            rows=report.rows,
        )


class StaleReportAuthorizedDirectReader(RecordingAuthorizedDirectReader):
    def read_direct_report(
        self,
        connection_id: str,
        query: DirectReportsReadQuery,
    ) -> DirectReportBlock:
        report = super().read_direct_report(connection_id, query)
        return DirectReportBlock(
            source=report.source,
            retrieved_at="2026-07-30T11:29:59+00:00",
            watermark="2026-07-30T11:25:00+00:00",
            period_start=report.period_start,
            period_end=report.period_end,
            timezone=report.timezone,
            attribution=report.attribution,
            currency=report.currency,
            rows=report.rows,
        )


class RogueChangeAuthorDirectReader(RecordingAuthorizedDirectReader):
    def read_direct_state(
        self,
        connection_id: str,
        query: DirectCampaignStateReadQuery,
    ) -> DirectCampaignStateBlock:
        state = super().read_direct_state(connection_id, query)
        return DirectCampaignStateBlock(
            source=state.source,
            retrieved_at=state.retrieved_at,
            watermark=state.watermark,
            campaign=state.campaign,
            campaign_state=state.campaign_state,
            group_state=state.group_state,
            ad_state=state.ad_state,
            strategy=state.strategy,
            current_weekly_budget_micros=state.current_weekly_budget_micros,
            budget_period_start=state.budget_period_start,
            budget_period_end=state.budget_period_end,
            current_search_bid_micros=state.current_search_bid_micros,
            ad_variant=state.ad_variant,
            object_config_version=state.object_config_version,
            last_change_author="rogue-operator",
            last_change_occurred_at=state.last_change_occurred_at,
        )


class SkewedWatermarkDirectReader(RecordingAuthorizedDirectReader):
    def read_direct_state(
        self,
        connection_id: str,
        query: DirectCampaignStateReadQuery,
    ) -> DirectCampaignStateBlock:
        state = super().read_direct_state(connection_id, query)
        return DirectCampaignStateBlock(
            source=state.source,
            retrieved_at=state.retrieved_at,
            watermark="2026-07-30T05:49:00+00:00",
            campaign=state.campaign,
            campaign_state=state.campaign_state,
            group_state=state.group_state,
            ad_state=state.ad_state,
            strategy=state.strategy,
            current_weekly_budget_micros=state.current_weekly_budget_micros,
            budget_period_start=state.budget_period_start,
            budget_period_end=state.budget_period_end,
            current_search_bid_micros=state.current_search_bid_micros,
            ad_variant=state.ad_variant,
            object_config_version=state.object_config_version,
            last_change_author=state.last_change_author,
            last_change_occurred_at=state.last_change_occurred_at,
        )


class ActionAuthorizedDirectReader(RecordingAuthorizedDirectReader):
    def read_direct_state(
        self,
        connection_id: str,
        query: DirectCampaignStateReadQuery,
    ) -> DirectCampaignStateBlock:
        state = super().read_direct_state(connection_id, query)
        return DirectCampaignStateBlock(
            source=state.source,
            retrieved_at=state.retrieved_at,
            watermark=state.watermark,
            campaign=state.campaign,
            campaign_state=state.campaign_state,
            group_state=state.group_state,
            ad_state=state.ad_state,
            strategy=state.strategy,
            current_weekly_budget_micros=2_000_000_000,
            budget_period_start=state.budget_period_start,
            budget_period_end=state.budget_period_end,
            current_search_bid_micros=state.current_search_bid_micros,
            ad_variant=state.ad_variant,
            object_config_version=state.object_config_version,
            last_change_author="sim-executor",
            last_change_occurred_at=state.last_change_occurred_at,
        )

    def authorizes_change_author(
        self,
        connection_id: str,
        author: str,
    ) -> bool:
        return connection_id == "sim-connection" and author == "sim-executor"


class FingerprintDriftDirectReader(ActionAuthorizedDirectReader):
    def __init__(self) -> None:
        super().__init__()
        self._trusted_state_reads = 0

    def read_direct_state(
        self,
        connection_id: str,
        query: DirectCampaignStateReadQuery,
    ) -> DirectCampaignStateBlock:
        state = super().read_direct_state(connection_id, query)
        self._trusted_state_reads += 1
        if self._trusted_state_reads == 1:
            return state
        return DirectCampaignStateBlock(
            source=state.source,
            retrieved_at=state.retrieved_at,
            watermark=state.watermark,
            campaign=state.campaign,
            campaign_state=state.campaign_state,
            group_state=state.group_state,
            ad_state=state.ad_state,
            strategy=state.strategy,
            current_weekly_budget_micros=state.current_weekly_budget_micros,
            budget_period_start=state.budget_period_start,
            budget_period_end=state.budget_period_end,
            current_search_bid_micros=state.current_search_bid_micros,
            ad_variant=state.ad_variant,
            object_config_version="campaign-config-v2",
            last_change_author=state.last_change_author,
            last_change_occurred_at=state.last_change_occurred_at,
        )


class RecordingDirectReportReader:
    def __init__(self) -> None:
        self.queries: list[DirectReportsReadQuery] = []

    def read_report(self, query: DirectReportsReadQuery) -> DirectReportBlock:
        self.queries.append(query)
        return RecordingAuthorizedDirectReader().read_direct_report(
            "bound-connection",
            query,
        )


class RecordingDirectStateReader:
    def __init__(self) -> None:
        self.queries: list[DirectCampaignStateReadQuery] = []

    def read_campaign_state(
        self,
        query: DirectCampaignStateReadQuery,
    ) -> DirectCampaignStateBlock:
        self.queries.append(query)
        return RecordingAuthorizedDirectReader().read_direct_state(
            "bound-connection",
            query,
        )


class StandaloneDirectCustomerE2ETests(unittest.TestCase):
    def _campaign_creation_http(
        self,
        temporary: str,
        *,
        adapter_options: dict[str, Any] | None = None,
        adapter_environment: ExecutionEnvironment = ExecutionEnvironment.TEST,
    ) -> tuple[
        HttpJsonModuleAdapterV1,
        Any,
        Any,
    ]:
        from mox_adv.campaign_lifecycle import (
            CampaignApproval,
            CampaignCreationRequest,
            CampaignDraftSafetyBindings,
            CampaignSagaStore,
            CreationReservation,
            CreationReservationStatus,
        )
        from mox_adv.direct_campaign_creation import (
            DirectCampaignCreationRuntimeV1,
        )
        from mox_adv.direct_management import FakeDirectManagementAdapter
        from mox_adv.recommend_contracts import CampaignDraftV1

        now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        policy = json.loads(
            (ROOT / "config" / "gate0-policy.json").read_text(encoding="utf-8")
        )
        store = CampaignSagaStore(Path(temporary) / "campaign.sqlite3")
        adapter = FakeDirectManagementAdapter(**(adapter_options or {}))
        draft = CampaignDraftV1.from_mapping(campaign_draft_payload())
        legacy_request = CampaignCreationRequest(
            run_id="run-headless-create-1",
            execution_key="execution-headless-create-1",
            proposal_id="proposal-headless-create-1",
            approval_id="approval-headless-create-1",
            account="sim-direct-account",
            credential_profile="DIRECT_PILOT_WRITE",
            reservation_id="reservation-headless-create-1",
            draft=draft,
        )
        store.register_creation_reservation(
            CreationReservation(
                reservation_id=legacy_request.reservation_id,
                status=CreationReservationStatus.AVAILABLE,
                scope_binding=legacy_request.account,
                object_type=draft.campaign_type,
                proposal_id=legacy_request.proposal_id,
                credential_profile=legacy_request.credential_profile,
                expires_at=now + timedelta(minutes=30),
            ),
            now,
        )
        approver = policy["principals"]["approver"]
        store.register_campaign_approval(
            CampaignApproval(
                approval_id=legacy_request.approval_id,
                proposal_id=legacy_request.proposal_id,
                binding_hash=legacy_request.approval_binding(policy["policy_id"]),
                approver=approver["identity"],
                authentication=approver["authentication"],
                expires_at=now + timedelta(minutes=15),
            )
        )
        runtime = DirectCampaignCreationRuntimeV1(
            connection_id="stored-test-direct",
            account_id="sim-direct-account",
            policy=policy,
            store=store,
            safety_bindings=CampaignDraftSafetyBindings(
                allowed_landing_hosts=("allowlisted.example",),
                prohibited_phrases=("guaranteed results",),
                prepared_media_references=(
                    "prepared-media-1",
                    "prepared-media-2",
                ),
            ),
            test_adapter=adapter,
            environment=ExecutionEnvironment.TEST,
        )
        module = DirectModuleV1(
            clock=lambda: now,
            campaign_creation_runtime=runtime,
        )
        return (
            HttpJsonModuleAdapterV1(
                module,
                environment=adapter_environment,
            ),
            adapter,
            module,
        )

    def test_customer_creates_one_campaign_and_duplicate_is_no_change(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            http, adapter, module = self._campaign_creation_http(temporary)
            request = campaign_creation_module_request()

            applied = http.handle(request)
            duplicate = http.handle(request)

            self.assertEqual(200, applied.status_code)
            self.assertEqual("SUCCEEDED", applied.body["status"])
            self.assertEqual("APPLIED", applied.body["execution_result"]["status"])
            outcome = applied.body["campaign_creation_outcome"]
            self.assertEqual("APPLIED", outcome["status"])
            self.assertEqual("APPLIED", outcome["saga_status"])
            self.assertEqual(
                [
                    "CAMPAIGN_ADD",
                    "AD_GROUP_ADD",
                    "ADS_ADD",
                    "KEYWORD_ADD",
                    "MODERATION_SUBMIT",
                    "MODERATION_READBACK",
                    "CAMPAIGN_LAUNCH",
                    "FULL_READBACK",
                ],
                outcome["completed_steps"],
            )
            self.assertEqual(
                [
                    "Campaigns",
                    "AdGroups",
                    "Ads",
                    "Ads",
                    "Keywords",
                ],
                [item["service"] for item in outcome["created_objects"]],
            )
            self.assertEqual(
                [
                    "UNIFIED_CAMPAIGN",
                    "UNIFIED_AD_GROUP",
                    "TEXT_AD",
                    "TEXT_AD",
                    "KEYWORD",
                ],
                [item["actual_type"] for item in outcome["created_objects"]],
            )
            self.assertTrue(
                all(not item["compensated"] for item in outcome["created_objects"])
            )
            self.assertEqual(
                [outcome["created_objects"][0]["object_id"]],
                outcome["readback"]["campaign_ids"],
            )
            self.assertRegex(outcome["evidence_digest"], r"^[0-9a-f]{64}$")
            self.assertEqual("NO_CHANGE", duplicate.body["execution_result"]["status"])
            self.assertEqual(
                "ALREADY_PROCESSED",
                duplicate.body["campaign_creation_outcome"]["saga_status"],
            )
            self.assertEqual(
                1,
                adapter.operation_count("Campaigns", "add"),
            )
            record = module.decision_records.read(applied.body["decision_record_ref"])
            self.assertEqual(
                outcome,
                record["facts"]["campaign_creation_outcome"],
            )

    def test_campaign_creation_is_blocked_before_test_adapter_in_production(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            http, adapter, _module = self._campaign_creation_http(
                temporary,
                adapter_environment=ExecutionEnvironment.PRODUCTION,
            )
            request = campaign_creation_module_request(environment="PRODUCTION")

            response = http.handle(request)

            self.assertEqual(422, response.status_code)
            self.assertEqual("BLOCKED", response.body["status"])
            self.assertEqual(
                "PRODUCTION_WRITE_FORBIDDEN",
                response.body["errors"][0]["code"],
            )
            self.assertEqual([], adapter.calls)

    def test_campaign_creation_preserves_uncertain_and_compensation_evidence(
        self,
    ) -> None:
        cases = (
            (
                {"timeout_after": ("Campaigns", "add")},
                "UNKNOWN_RESULT",
                False,
            ),
            (
                {"fail_on": ("Ads", "moderate")},
                "PARTIALLY_APPLIED",
                True,
            ),
            (
                {
                    "fail_on": ("Ads", "moderate"),
                    "fail_compensation_on": ("AdGroups", "delete"),
                },
                "COMPENSATION_REQUIRED",
                True,
            ),
        )
        for adapter_options, expected_status, has_compensated in cases:
            with (
                self.subTest(status=expected_status),
                tempfile.TemporaryDirectory() as temporary,
            ):
                http, adapter, _module = self._campaign_creation_http(
                    temporary,
                    adapter_options=adapter_options,
                )

                response = http.handle(campaign_creation_module_request())

                self.assertEqual(500, response.status_code)
                self.assertEqual("FAILED", response.body["status"])
                self.assertEqual(
                    expected_status,
                    response.body["execution_result"]["status"],
                )
                outcome = response.body["campaign_creation_outcome"]
                self.assertEqual(expected_status, outcome["status"])
                self.assertIsNotNone(outcome["detail"])
                self.assertEqual(
                    has_compensated,
                    any(item["compensated"] for item in outcome["created_objects"]),
                )
                self.assertEqual(
                    1,
                    adapter.operation_count("Campaigns", "add"),
                )

    def test_campaign_creation_contract_is_closed_and_draft_is_immutable(
        self,
    ) -> None:
        raw_payload = campaign_creation_module_request()
        command = raw_payload["campaign_creation_command"]
        assert isinstance(command, dict)
        command["yandex_http_payload"] = {
            "method": "POST",
            "url": "https://api.direct.yandex.com/json/v5/campaigns",
        }
        with self.assertRaisesRegex(
            ContractValidationError,
            "unexpected field",
        ):
            ModuleRequestV1.from_dict(raw_payload)

        parsed = ModuleRequestV1.from_dict(campaign_creation_module_request())
        assert parsed.campaign_creation_command is not None
        with self.assertRaises(TypeError):
            cast(
                dict[str, Any],
                parsed.campaign_creation_command.draft.business_goal,
            )["event"] = "tampered"

        mismatched_key = campaign_creation_module_request()
        mismatched_key["idempotency_key"] = "different-execution-key"
        with self.assertRaisesRegex(
            ContractValidationError,
            "idempotency_key must equal",
        ):
            ModuleRequestV1.from_dict(mismatched_key)

    def test_campaign_creation_evidence_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            http, _adapter, _module = self._campaign_creation_http(temporary)
            response = http.handle(campaign_creation_module_request())
            tampered = response.body
            tampered["campaign_creation_outcome"]["created_objects"][0][
                "actual_type"
            ] = "TEXT_AD"

            with self.assertRaisesRegex(
                ContractValidationError,
                "evidence digest",
            ):
                ModuleResultV1.from_dict(tampered)

    def test_campaign_runtime_rejects_non_test_or_unsealed_adapter(
        self,
    ) -> None:
        from mox_adv.campaign_lifecycle import (
            CampaignDraftSafetyBindings,
            CampaignSagaStore,
        )
        from mox_adv.direct_campaign_creation import (
            DirectCampaignCreationRuntimeV1,
        )
        from mox_adv.direct_management import FakeDirectManagementAdapter

        class UnsafeAdapter(FakeDirectManagementAdapter):
            pass

        policy = json.loads(
            (ROOT / "config" / "gate0-policy.json").read_text(encoding="utf-8")
        )
        bindings = CampaignDraftSafetyBindings(
            allowed_landing_hosts=("allowlisted.example",),
            prohibited_phrases=(),
            prepared_media_references=(
                "prepared-media-1",
                "prepared-media-2",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            store = CampaignSagaStore(Path(temporary) / "campaign.sqlite3")
            cases = (
                (FakeDirectManagementAdapter(), ExecutionEnvironment.PRODUCTION),
                (UnsafeAdapter(), ExecutionEnvironment.TEST),
            )
            for adapter, environment in cases:
                with (
                    self.subTest(environment=environment),
                    self.assertRaises(ValueError),
                ):
                    DirectCampaignCreationRuntimeV1(
                        connection_id="stored-test-direct",
                        account_id="sim-direct-account",
                        policy=policy,
                        store=store,
                        safety_bindings=bindings,
                        test_adapter=adapter,
                        environment=environment,
                    )

    def test_customer_typed_action_is_blocked_before_direct_reads_in_production(
        self,
    ) -> None:
        reader = RecordingAuthorizedDirectReader()
        module = DirectModuleV1(
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
            provider_reader=reader,
        )
        request = customer_evidence_request()
        request["operation"] = {
            "kind": "EXECUTE",
            "operation_type": "APPLY_OPTIMIZATION",
        }
        request["direct_action_command"] = {
            "schema_version": "direct-action-command-v1",
            "command": "EXECUTE_PROPOSAL",
            "proposal_id": "proposal-customer-17",
        }

        response = HttpJsonModuleAdapterV1(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(422, response.status_code)
        self.assertEqual("BLOCKED", response.body["status"])
        self.assertEqual(
            "PRODUCTION_WRITE_FORBIDDEN",
            response.body["errors"][0]["code"],
        )
        self.assertEqual(
            {
                "proposal_id": "proposal-customer-17",
                "operation_type": "APPLY_OPTIMIZATION",
                "status": "DRY_RUN",
            },
            response.body["proposal"],
        )
        self.assertIsNone(response.body["execution_result"])
        self.assertEqual([], reader.report_calls)
        self.assertEqual([], reader.state_calls)

    def test_customer_plans_and_applies_one_approved_action_in_test(self) -> None:
        from mox_adv.control_state import (
            AuthenticatedPrincipal,
            DurableControlState,
        )
        from mox_adv.direct_action import DirectActionRuntimeV1
        from mox_adv.fake_write_adapter import FakeWriteAdapter
        from mox_adv.proposal_store import ImmutableProposalStore

        now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        reader = ActionAuthorizedDirectReader()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = DurableControlState(root / "control.sqlite3")
            adapter = FakeWriteAdapter(
                initial_state={
                    (
                        "sim-organization:sim-connection:sim-direct-account:"
                        "campaign-7:INCREASE_WEEKLY_BUDGET"
                    ): 2_000_000_000
                }
            )
            runtime = DirectActionRuntimeV1(
                policy=json.loads(
                    (ROOT / "config" / "gate0-policy.json").read_text(encoding="utf-8")
                ),
                state=state,
                proposal_store=ImmutableProposalStore(root / "proposals"),
                test_adapter=adapter,
                environment=ExecutionEnvironment.TEST,
            )
            module = DirectModuleV1(
                clock=lambda: now,
                provider_reader=reader,
                action_runtime=runtime,
            )
            http = HttpJsonModuleAdapterV1(
                module,
                environment=ExecutionEnvironment.TEST,
            )
            plan_request = direct_action_plan_request()

            planned = http.handle(plan_request)
            planned_duplicate = http.handle(plan_request)

            self.assertEqual(200, planned.status_code)
            self.assertEqual("SUCCEEDED", planned.body["status"])
            self.assertEqual("PROPOSED", planned.body["proposal"]["status"])
            proposal_id = planned.body["proposal"]["proposal_id"]
            self.assertEqual(
                proposal_id,
                planned_duplicate.body["proposal"]["proposal_id"],
            )
            state.grant_approval(
                proposal_id=proposal_id,
                expires_at=now + timedelta(minutes=15),
                reason="Approve the exact standalone Direct test action.",
                principal=AuthenticatedPrincipal(
                    identity="sviridov",
                    authentication="authenticated_macos_user",
                ),
                now=now,
            )
            execute_request = dict(plan_request)
            execute_request["operation"] = {
                "kind": "EXECUTE",
                "operation_type": "APPLY_OPTIMIZATION",
            }
            execute_request["direct_action_command"] = {
                "schema_version": "direct-action-command-v1",
                "command": "EXECUTE_PROPOSAL",
                "proposal_id": proposal_id,
            }
            execute_request["idempotency_key"] = "direct-action-execute-17"

            applied = http.handle(execute_request)
            duplicate = http.handle(execute_request)

            self.assertEqual(200, applied.status_code)
            self.assertEqual("SUCCEEDED", applied.body["status"])
            self.assertEqual("APPLIED", applied.body["execution_result"]["status"])
            self.assertTrue(applied.body["execution_result"]["applied"])
            self.assertEqual(
                "2200000000",
                applied.body["execution_result"]["provider_reference"],
            )
            self.assertEqual(
                "ALREADY_PROCESSED",
                duplicate.body["execution_result"]["status"],
            )
            self.assertEqual(1, adapter.write_calls)
            self.assertGreaterEqual(len(reader.state_calls), 3)

    def test_changed_direct_fingerprint_blocks_before_test_adapter_write(
        self,
    ) -> None:
        from mox_adv.control_state import (
            AuthenticatedPrincipal,
            DurableControlState,
        )
        from mox_adv.direct_action import DirectActionRuntimeV1
        from mox_adv.fake_write_adapter import FakeWriteAdapter
        from mox_adv.proposal_store import ImmutableProposalStore

        now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        reader = FingerprintDriftDirectReader()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = DurableControlState(root / "control.sqlite3")
            adapter = FakeWriteAdapter(
                initial_state={
                    (
                        "sim-organization:sim-connection:sim-direct-account:"
                        "campaign-7:INCREASE_WEEKLY_BUDGET"
                    ): 2_000_000_000
                }
            )
            runtime = DirectActionRuntimeV1(
                policy=json.loads(
                    (ROOT / "config" / "gate0-policy.json").read_text(encoding="utf-8")
                ),
                state=state,
                proposal_store=ImmutableProposalStore(root / "proposals"),
                test_adapter=adapter,
                environment=ExecutionEnvironment.TEST,
            )
            http = HttpJsonModuleAdapterV1(
                DirectModuleV1(
                    clock=lambda: now,
                    provider_reader=reader,
                    action_runtime=runtime,
                ),
                environment=ExecutionEnvironment.TEST,
            )
            plan_request = direct_action_plan_request()
            planned = http.handle(plan_request)
            proposal_id = planned.body["proposal"]["proposal_id"]
            state.grant_approval(
                proposal_id=proposal_id,
                expires_at=now + timedelta(minutes=15),
                reason="Approve the exact pre-drift Direct state.",
                principal=AuthenticatedPrincipal(
                    identity="sviridov",
                    authentication="authenticated_macos_user",
                ),
                now=now,
            )
            execute_request = dict(plan_request)
            execute_request["operation"] = {
                "kind": "EXECUTE",
                "operation_type": "APPLY_OPTIMIZATION",
            }
            execute_request["direct_action_command"] = {
                "schema_version": "direct-action-command-v1",
                "command": "EXECUTE_PROPOSAL",
                "proposal_id": proposal_id,
            }

            response = http.handle(execute_request)

            self.assertEqual(422, response.status_code)
            self.assertEqual("BLOCKED", response.body["status"])
            self.assertEqual(
                "FINGERPRINT_MISMATCH",
                response.body["errors"][0]["code"],
            )
            self.assertEqual(0, adapter.write_calls)

    def test_unsafe_evidence_never_creates_a_direct_proposal(self) -> None:
        from mox_adv.control_state import DurableControlState
        from mox_adv.direct_action import DirectActionRuntimeV1
        from mox_adv.fake_write_adapter import FakeWriteAdapter
        from mox_adv.proposal_store import ImmutableProposalStore

        cases = {
            "low_utilization": {
                "cost_micros": 1_000_000_000,
            },
            "insufficient_sample": {
                "clicks": 40,
                "conversions": 2,
            },
            "high_cpa": {
                "cost_micros": 5_000_000_000,
                "conversions": 4,
            },
        }
        now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        for case, overrides in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                adapter = FakeWriteAdapter()
                runtime = DirectActionRuntimeV1(
                    policy=json.loads(
                        (ROOT / "config" / "gate0-policy.json").read_text(
                            encoding="utf-8"
                        )
                    ),
                    state=DurableControlState(root / "control.sqlite3"),
                    proposal_store=ImmutableProposalStore(root / "proposals"),
                    test_adapter=adapter,
                    environment=ExecutionEnvironment.TEST,
                )
                http = HttpJsonModuleAdapterV1(
                    DirectModuleV1(
                        clock=lambda: now,
                        provider_reader=ActionAuthorizedDirectReader(),
                        action_runtime=runtime,
                    ),
                    environment=ExecutionEnvironment.TEST,
                )
                request = direct_action_plan_request()
                evidence = request["external_evidence"]
                assert isinstance(evidence, dict)
                metrics = evidence["metrics"]
                assert isinstance(metrics, list)
                for metric in metrics:
                    assert isinstance(metric, dict)
                    if metric["name"] in overrides:
                        metric["value"] = overrides[metric["name"]]

                response = http.handle(request)

                self.assertEqual(422, response.status_code)
                self.assertEqual("BLOCKED", response.body["status"])
                self.assertEqual(
                    "ACTION_POLICY_REJECTED",
                    response.body["errors"][0]["code"],
                )
                self.assertIsNone(response.body["proposal"])
                self.assertEqual([], list((root / "proposals").glob("*.json")))
                self.assertEqual(0, adapter.write_calls)

    def test_current_operational_safety_facts_fail_closed_before_write(
        self,
    ) -> None:
        from mox_adv.control_state import (
            AuthenticatedPrincipal,
            ControlRejected,
            DurableControlState,
        )
        from mox_adv.direct_action import DirectActionRuntimeV1
        from mox_adv.fake_write_adapter import FakeWriteAdapter
        from mox_adv.proposal_store import ImmutableProposalStore

        now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        cases = (
            ("cooldown", "COOLDOWN_ACTIVE"),
            ("quota", "ACTION_QUOTA_REACHED"),
            ("kill_switch", "KILL_SWITCH_ACTIVE"),
            ("unavailable", "CONTROL_STATE_UNAVAILABLE"),
        )
        for case, expected_code in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                policy = json.loads(
                    (ROOT / "config" / "gate0-policy.json").read_text(encoding="utf-8")
                )
                if case == "quota":
                    policy["timing"]["cooldown_hours"] = 1
                state = DurableControlState(root / "control.sqlite3")
                if case in {"cooldown", "quota"}:
                    record_prior_applied_action(
                        state,
                        policy,
                        (
                            now - timedelta(minutes=30)
                            if case == "cooldown"
                            else now - timedelta(hours=2)
                        ),
                        "prior-" + case,
                    )
                adapter = FakeWriteAdapter(
                    initial_state={
                        (
                            "sim-organization:sim-connection:"
                            "sim-direct-account:campaign-7:"
                            "INCREASE_WEEKLY_BUDGET"
                        ): 2_000_000_000
                    }
                )
                runtime = DirectActionRuntimeV1(
                    policy=policy,
                    state=state,
                    proposal_store=ImmutableProposalStore(root / "proposals"),
                    test_adapter=adapter,
                    environment=ExecutionEnvironment.TEST,
                )
                http = HttpJsonModuleAdapterV1(
                    DirectModuleV1(
                        clock=lambda: now,
                        provider_reader=ActionAuthorizedDirectReader(),
                        action_runtime=runtime,
                    ),
                    environment=ExecutionEnvironment.TEST,
                )
                plan_request = direct_action_plan_request()
                plan_request["idempotency_key"] = "operational-safety-" + case
                planned = http.handle(plan_request)
                proposal_id = planned.body["proposal"]["proposal_id"]
                principal = AuthenticatedPrincipal(
                    identity="sviridov",
                    authentication="authenticated_macos_user",
                )
                state.grant_approval(
                    proposal_id=proposal_id,
                    expires_at=now + timedelta(minutes=15),
                    reason="Approve the operational safety scenario.",
                    principal=principal,
                    now=now,
                )
                if case == "kill_switch":
                    state.engage_kill_switch(
                        "global",
                        "Exercise the public Direct kill switch.",
                        principal,
                        now,
                    )
                execute_request = dict(plan_request)
                execute_request["operation"] = {
                    "kind": "EXECUTE",
                    "operation_type": "APPLY_OPTIMIZATION",
                }
                execute_request["direct_action_command"] = {
                    "schema_version": "direct-action-command-v1",
                    "command": "EXECUTE_PROPOSAL",
                    "proposal_id": proposal_id,
                }
                unavailable = (
                    mock.patch.object(
                        state,
                        "load_operational_execution_facts",
                        side_effect=ControlRejected(
                            "CONTROL_STATE_UNAVAILABLE",
                            "durable facts are unavailable.",
                        ),
                    )
                    if case == "unavailable"
                    else mock.patch.object(
                        state,
                        "load_operational_execution_facts",
                        wraps=state.load_operational_execution_facts,
                    )
                )

                with unavailable:
                    response = http.handle(execute_request)

                self.assertEqual(422, response.status_code)
                self.assertEqual("BLOCKED", response.body["status"])
                self.assertEqual(
                    expected_code,
                    response.body["errors"][0]["code"],
                )
                self.assertEqual(0, adapter.write_calls)

    def test_timeout_unknown_result_retries_only_reconcile_without_second_write(
        self,
    ) -> None:
        from mox_adv.control_state import (
            AuthenticatedPrincipal,
            DurableControlState,
        )
        from mox_adv.direct_action import DirectActionRuntimeV1
        from mox_adv.fake_write_adapter import FakeWriteAdapter
        from mox_adv.proposal_store import ImmutableProposalStore

        now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = DurableControlState(root / "control.sqlite3")
            adapter = FakeWriteAdapter(
                initial_state={
                    (
                        "sim-organization:sim-connection:sim-direct-account:"
                        "campaign-7:INCREASE_WEEKLY_BUDGET"
                    ): 2_000_000_000
                },
                timeout_after_write=True,
                timeout_readback=None,
            )
            runtime = DirectActionRuntimeV1(
                policy=json.loads(
                    (ROOT / "config" / "gate0-policy.json").read_text(encoding="utf-8")
                ),
                state=state,
                proposal_store=ImmutableProposalStore(root / "proposals"),
                test_adapter=adapter,
                environment=ExecutionEnvironment.TEST,
            )
            http = HttpJsonModuleAdapterV1(
                DirectModuleV1(
                    clock=lambda: now,
                    provider_reader=ActionAuthorizedDirectReader(),
                    action_runtime=runtime,
                ),
                environment=ExecutionEnvironment.TEST,
            )
            plan_request = direct_action_plan_request()
            planned = http.handle(plan_request)
            proposal_id = planned.body["proposal"]["proposal_id"]
            state.grant_approval(
                proposal_id=proposal_id,
                expires_at=now + timedelta(minutes=15),
                reason="Approve the timeout reconciliation scenario.",
                principal=AuthenticatedPrincipal(
                    identity="sviridov",
                    authentication="authenticated_macos_user",
                ),
                now=now,
            )
            execute_request = dict(plan_request)
            execute_request["operation"] = {
                "kind": "EXECUTE",
                "operation_type": "APPLY_OPTIMIZATION",
            }
            execute_request["direct_action_command"] = {
                "schema_version": "direct-action-command-v1",
                "command": "EXECUTE_PROPOSAL",
                "proposal_id": proposal_id,
            }

            first = http.handle(execute_request)
            retry = http.handle(execute_request)

            self.assertEqual(500, first.status_code)
            self.assertEqual("FAILED", first.body["status"])
            self.assertEqual(
                "UNKNOWN_RESULT",
                first.body["execution_result"]["status"],
            )
            self.assertEqual(
                "UNKNOWN_RESULT",
                retry.body["execution_result"]["status"],
            )
            self.assertEqual(1, adapter.write_calls)

    def test_customer_evidence_returns_headless_direct_analysis(self) -> None:
        decision_records = InMemoryDecisionRecordStoreV1()
        module = DirectModuleV1(
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
            decision_records=decision_records,
        )
        adapter = HttpJsonModuleAdapterV1(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        )

        response = adapter.handle(customer_evidence_request())

        self.assertEqual(200, response.status_code)
        result = response.body
        self.assertEqual("PARTIAL", result["status"])
        metrics = {item["name"]: item for item in result["metrics"]}
        self.assertEqual(
            {"value": "2", "unit": "PERCENT"},
            {
                "value": metrics["ctr_percent"]["value"],
                "unit": metrics["ctr_percent"]["unit"],
            },
        )
        self.assertEqual("25", metrics["cpc_rub"]["value"])
        self.assertEqual("50", metrics["budget_utilization_percent"]["value"])
        self.assertEqual("50", metrics["pacing_percent"]["value"])
        self.assertEqual("ON", metrics["campaign_state"]["value"])
        self.assertEqual(
            "PARTIAL",
            result["assessment"]["data_quality_status"],
        )
        self.assertEqual(
            ["CONVERSION_CONTEXT_REQUIRED"],
            [item["code"] for item in result["recommendations"]],
        )
        self.assertEqual(
            ["DIRECT_TRAFFIC_EFFICIENCY_STABLE"],
            [item["code"] for item in result["hypotheses"]],
        )
        self.assertEqual(
            ["ctr_percent", "cpc_rub"],
            result["hypotheses"][0]["evidence_metric_names"],
        )
        self.assertLessEqual(len(result["hypotheses"]), 3)
        self.assertTrue(
            all(not item["executable"] for item in result["recommendations"])
        )
        self.assertEqual(
            ["CONVERSION_CONTEXT_UNAVAILABLE"],
            [item["code"] for item in result["warnings"]],
        )
        self.assertEqual(
            [
                {
                    "source_type": "CUSTOMER_EVIDENCE",
                    "source": "CUSTOMER_ECOSYSTEM",
                    "retrieved_at": "2026-07-30T11:55:00+00:00",
                    "watermark": "2026-07-30T11:50:00+00:00",
                    "evidence_id": "customer-direct-evidence-17",
                }
            ],
            result["provenance"],
        )
        self.assertIsNone(result["proposal"])
        self.assertIsNone(result["execution_result"])
        record = decision_records.read(result["decision_record_ref"])
        self.assertEqual("PARTIAL", record["outcome"])
        self.assertEqual(result["metrics"], record["facts"]["metrics"])
        self.assertEqual(result["hypotheses"], record["facts"]["hypotheses"])

    def test_authorized_provider_read_returns_statistics_state_and_provenance(
        self,
    ) -> None:
        reader = RecordingAuthorizedDirectReader()
        module = DirectModuleV1(
            provider_reader=reader,
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
        )
        request = customer_evidence_request()
        request.pop("external_evidence")

        response = HttpJsonModuleAdapterV1(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(200, response.status_code)
        self.assertEqual("PARTIAL", response.body["status"])
        metrics = {item["name"]: item["value"] for item in response.body["metrics"]}
        self.assertEqual(10000, metrics["impressions"])
        self.assertEqual(200, metrics["clicks"])
        self.assertEqual(5000000000, metrics["cost_micros"])
        self.assertEqual("2", metrics["ctr_percent"])
        self.assertEqual("25", metrics["cpc_rub"])
        self.assertEqual("ON", metrics["campaign_state"])
        self.assertEqual(10000000000, metrics["current_weekly_budget_micros"])
        self.assertEqual(
            [
                {
                    "source_type": "PROVIDER",
                    "source": "DIRECT_REPORTS",
                    "retrieved_at": "2026-07-30T11:55:00+00:00",
                    "watermark": "2026-07-30T11:50:00+00:00",
                },
                {
                    "source_type": "PROVIDER",
                    "source": "DIRECT_CAMPAIGN_STATE",
                    "retrieved_at": "2026-07-30T11:54:00+00:00",
                    "watermark": "2026-07-30T11:49:00+00:00",
                },
            ],
            response.body["provenance"],
        )
        self.assertEqual(
            [
                (
                    "customer-direct-primary",
                    DirectReportsReadQuery(
                        account="account-8",
                        campaign="campaign-7",
                        period_start="2026-07-23",
                        period_end="2026-07-29",
                        attribution="AUTO",
                    ),
                )
            ],
            reader.report_calls,
        )
        self.assertEqual(
            [
                (
                    "customer-direct-primary",
                    DirectCampaignStateReadQuery(
                        account="account-8",
                        campaign="campaign-7",
                    ),
                )
            ],
            reader.state_calls,
        )

    def test_valid_neutral_conversion_context_completes_the_conclusion(
        self,
    ) -> None:
        request = customer_evidence_request()
        evidence = request["external_evidence"]
        assert isinstance(evidence, dict)
        metrics = evidence["metrics"]
        assert isinstance(metrics, list)
        metrics.append({"name": "conversions", "value": 5, "unit": "COUNT"})
        module = DirectModuleV1(
            clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        )

        response = HttpJsonModuleAdapterV1(
            module,
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(200, response.status_code)
        self.assertEqual("SUCCEEDED", response.body["status"])
        values = {item["name"]: item["value"] for item in response.body["metrics"]}
        self.assertEqual(5, values["conversions"])
        self.assertEqual("1000", values["cpa_rub"])
        self.assertEqual([], response.body["warnings"])
        self.assertEqual(
            "READY",
            response.body["assessment"]["data_quality_status"],
        )
        self.assertEqual(
            ["CONTINUE_MONITORING"],
            [item["code"] for item in response.body["recommendations"]],
        )

    def test_hypotheses_are_bounded_and_linked_to_returned_metrics(self) -> None:
        request = customer_evidence_request()
        evidence = request["external_evidence"]
        assert isinstance(evidence, dict)
        metrics = evidence["metrics"]
        assert isinstance(metrics, list)
        by_name = {item["name"]: item for item in metrics}
        by_name["impressions"]["value"] = 100000
        by_name["clicks"]["value"] = 100
        by_name["cost_micros"]["value"] = 12000000000
        metrics.append({"name": "conversions", "value": 3, "unit": "COUNT"})

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                )
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(200, response.status_code)
        hypotheses = response.body["hypotheses"]
        self.assertEqual(3, len(hypotheses))
        metric_names = {item["name"] for item in response.body["metrics"]}
        for hypothesis in hypotheses:
            self.assertTrue(hypothesis["evidence_metric_names"])
            self.assertTrue(
                set(hypothesis["evidence_metric_names"]).issubset(metric_names)
            )

    def test_raw_provider_payload_is_rejected_at_the_public_contract(self) -> None:
        request = customer_evidence_request()
        evidence = request["external_evidence"]
        assert isinstance(evidence, dict)
        evidence["raw_provider_payload"] = {
            "method": "campaigns.get",
            "result": {"Campaigns": []},
        }

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(400, response.status_code)
        self.assertEqual("REJECTED", response.body["status"])
        self.assertEqual(
            "CONTRACT_VALIDATION_FAILED",
            response.body["errors"][0]["code"],
        )

    def test_unknown_normalized_metric_is_rejected_without_analysis(self) -> None:
        request = customer_evidence_request()
        evidence = request["external_evidence"]
        assert isinstance(evidence, dict)
        metrics = evidence["metrics"]
        assert isinstance(metrics, list)
        metrics.append({"name": "provider_http_body", "value": "opaque", "unit": "RAW"})

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                )
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(422, response.status_code)
        self.assertEqual("REJECTED", response.body["status"])
        self.assertEqual(
            "DIRECT_EVIDENCE_REJECTED",
            response.body["errors"][0]["code"],
        )

    def test_invalid_neutral_conversion_context_is_rejected(self) -> None:
        request = customer_evidence_request()
        evidence = request["external_evidence"]
        assert isinstance(evidence, dict)
        metrics = evidence["metrics"]
        assert isinstance(metrics, list)
        metrics.append({"name": "conversions", "value": 201, "unit": "COUNT"})

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                )
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(422, response.status_code)
        self.assertEqual(
            "DIRECT_EVIDENCE_REJECTED",
            response.body["errors"][0]["code"],
        )
        self.assertIn(
            "conversions exceed clicks",
            response.body["errors"][0]["message"],
        )

    def test_zero_weekly_budget_is_rejected_as_invalid_managed_state(
        self,
    ) -> None:
        request = customer_evidence_request()
        evidence = request["external_evidence"]
        assert isinstance(evidence, dict)
        metrics = evidence["metrics"]
        assert isinstance(metrics, list)
        by_name = {item["name"]: item for item in metrics}
        by_name["current_weekly_budget_micros"]["value"] = 0
        metrics.append({"name": "conversions", "value": 5, "unit": "COUNT"})

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                )
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(422, response.status_code)
        self.assertEqual(
            "DIRECT_EVIDENCE_REJECTED",
            response.body["errors"][0]["code"],
        )
        self.assertIn(
            "weekly budget must be positive",
            response.body["errors"][0]["message"],
        )

    def test_future_budget_period_is_incompatible_managed_state(
        self,
    ) -> None:
        request = customer_evidence_request()
        evidence = request["external_evidence"]
        assert isinstance(evidence, dict)
        metrics = evidence["metrics"]
        assert isinstance(metrics, list)
        by_name = {item["name"]: item for item in metrics}
        by_name["budget_period_start"]["value"] = "2026-07-31T12:00:00+00:00"
        by_name["budget_period_end"]["value"] = "2026-08-07T12:00:00+00:00"
        metrics.append({"name": "conversions", "value": 5, "unit": "COUNT"})

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                )
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(200, response.status_code)
        self.assertEqual("PARTIAL", response.body["status"])
        self.assertEqual(
            "INCOMPATIBLE",
            response.body["assessment"]["data_quality_status"],
        )
        self.assertEqual(
            ["BUDGET_PERIOD_MISMATCH"],
            [item["code"] for item in response.body["warnings"]],
        )
        self.assertEqual([], response.body["errors"])
        self.assertIsNone(response.body["proposal"])
        self.assertRegex(
            response.body["decision_record_ref"],
            r"^decision-records/[0-9a-f]{64}\.json$",
        )

    def test_stale_direct_evidence_is_partial_and_non_executable(self) -> None:
        request = customer_evidence_request()
        evidence = request["external_evidence"]
        assert isinstance(evidence, dict)
        evidence["observed_at"] = "2026-07-30T11:29:59+00:00"
        evidence["watermark"] = "2026-07-30T11:25:00+00:00"

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                )
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(200, response.status_code)
        self.assertEqual("PARTIAL", response.body["status"])
        self.assertEqual(
            "STALE_DATA",
            response.body["assessment"]["confidence_status"],
        )
        self.assertIn(
            "DIRECT_DATA_STALE",
            [item["code"] for item in response.body["warnings"]],
        )
        self.assertTrue(
            all(not item["executable"] for item in response.body["recommendations"])
        )
        self.assertIsNone(response.body["proposal"])

    def test_provider_failure_returns_a_retryable_error_without_secrets(
        self,
    ) -> None:
        request = customer_evidence_request()
        request.pop("external_evidence")

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                provider_reader=FailingAuthorizedDirectReader(),
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(500, response.status_code)
        self.assertEqual("FAILED", response.body["status"])
        self.assertEqual(
            "DIRECT_PROVIDER_READ_FAILED",
            response.body["errors"][0]["code"],
        )
        self.assertTrue(response.body["errors"][0]["retryable"])
        self.assertNotIn("OAuth secret", str(response.body))

    def test_stale_provider_report_makes_the_combined_result_stale(self) -> None:
        request = customer_evidence_request()
        request.pop("external_evidence")

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                provider_reader=StaleReportAuthorizedDirectReader(),
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            "STALE_DATA",
            response.body["assessment"]["confidence_status"],
        )
        self.assertIn(
            "DIRECT_DATA_STALE",
            [item["code"] for item in response.body["warnings"]],
        )

    def test_excessive_provider_watermark_skew_is_incompatible(self) -> None:
        request = customer_evidence_request()
        request.pop("external_evidence")

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                provider_reader=SkewedWatermarkDirectReader(),
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(200, response.status_code)
        self.assertEqual("PARTIAL", response.body["status"])
        self.assertEqual(
            "INCOMPATIBLE",
            response.body["assessment"]["data_quality_status"],
        )
        self.assertIn(
            "WATERMARK_SKEW_EXCEEDED",
            [item["code"] for item in response.body["warnings"]],
        )
        self.assertIsNone(response.body["proposal"])
        self.assertRegex(
            response.body["decision_record_ref"],
            r"^decision-records/[0-9a-f]{64}\.json$",
        )

    def test_malformed_provider_response_is_rejected(self) -> None:
        request = customer_evidence_request()
        request.pop("external_evidence")

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                provider_reader=MalformedAuthorizedDirectReader(),
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(422, response.status_code)
        self.assertEqual("REJECTED", response.body["status"])
        self.assertEqual(
            "DIRECT_EVIDENCE_REJECTED",
            response.body["errors"][0]["code"],
        )

    def test_bound_provider_rejects_an_untrusted_scope_before_reading(self) -> None:
        report_reader = RecordingDirectReportReader()
        state_reader = RecordingDirectStateReader()
        provider = BoundDirectReadProviderV1(
            connection_id="customer-direct-primary",
            account_id="account-8",
            campaign_id="campaign-7",
            trusted_change_author="customer-42",
            report_reader=report_reader,
            state_reader=state_reader,
        )
        request = customer_evidence_request()
        request.pop("external_evidence")
        scope = request["scope"]
        assert isinstance(scope, dict)
        scope["campaign_id"] = "rogue-campaign"

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                provider_reader=provider,
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(422, response.status_code)
        self.assertEqual(
            "DIRECT_SCOPE_REJECTED",
            response.body["errors"][0]["code"],
        )
        self.assertEqual([], report_reader.queries)
        self.assertEqual([], state_reader.queries)

    def test_bound_provider_accepts_only_the_trusted_change_author(self) -> None:
        report_reader = RecordingDirectReportReader()
        state_reader = RecordingDirectStateReader()
        provider = BoundDirectReadProviderV1(
            connection_id="customer-direct-primary",
            account_id="account-8",
            campaign_id="campaign-7",
            trusted_change_author="customer-42",
            report_reader=report_reader,
            state_reader=state_reader,
        )
        request = customer_evidence_request()
        request.pop("external_evidence")

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                provider_reader=provider,
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(200, response.status_code)
        self.assertEqual("PARTIAL", response.body["status"])
        self.assertEqual(1, len(report_reader.queries))
        self.assertEqual(1, len(state_reader.queries))

    def test_unknown_external_change_author_is_rejected(self) -> None:
        request = customer_evidence_request()
        request.pop("external_evidence")

        response = HttpJsonModuleAdapterV1(
            DirectModuleV1(
                provider_reader=RogueChangeAuthorDirectReader(),
                clock=lambda: datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
            ),
            environment=ExecutionEnvironment.PRODUCTION,
        ).handle(request)

        self.assertEqual(422, response.status_code)
        self.assertEqual(
            "DIRECT_SCOPE_REJECTED",
            response.body["errors"][0]["code"],
        )
        self.assertIn(
            "unknown external change",
            response.body["errors"][0]["message"],
        )

    def test_clean_process_needs_no_metrika_credentials_requests_or_ui(
        self,
    ) -> None:
        payload = json.dumps(customer_evidence_request())
        script = f"""
import builtins
import json
blocked = []
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    protected = (
        name == "mox_adv.modules.metrika"
        or name.startswith("mox_adv.metrika")
        or name.startswith("mox_adv.ui")
        or name in ("mox_adv.egress", "mox_adv.host_launcher")
    )
    if protected:
        blocked.append(name)
        raise AssertionError("standalone Direct imported " + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
from datetime import datetime, timezone
from mox_adv.environment import ExecutionEnvironment
from mox_adv.module_api.v1 import HttpJsonModuleAdapterV1
from mox_adv.modules.direct import DirectModuleV1
module = DirectModuleV1(
    clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
)
response = HttpJsonModuleAdapterV1(
    module,
    environment=ExecutionEnvironment.PRODUCTION,
).handle(json.loads({payload!r}))
assert response.status_code == 200, response.body
assert response.body["status"] == "PARTIAL", response.body
assert blocked == [], blocked
"""

        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            env={"PYTHONPATH": str(ROOT / "src")},
            text=True,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_standalone_wheel_contains_no_metrika_or_dashboard_and_runs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            (temporary / "egg-info").mkdir()
            build = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "packaging" / "direct" / "setup.py"),
                    "egg_info",
                    "--egg-base",
                    str(temporary / "egg-info"),
                    "build",
                    "--build-base",
                    str(temporary / "build"),
                    "bdist_wheel",
                    "--dist-dir",
                    str(temporary / "dist"),
                    "--bdist-dir",
                    str(temporary / "wheel"),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, build.returncode, build.stderr)
            wheels = tuple((temporary / "dist").glob("*.whl"))
            self.assertEqual(1, len(wheels))
            with zipfile.ZipFile(wheels[0]) as archive:
                names = set(archive.namelist())
            self.assertNotIn("mox_adv/modules/metrika.py", names)
            self.assertFalse(
                any(name.startswith("mox_adv/metrika") for name in names),
                names,
            )
            self.assertFalse(
                any(name.startswith("mox_adv/ui/") for name in names),
                names,
            )

            installed = temporary / "installed"
            install = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--quiet",
                    "--no-deps",
                    "--target",
                    str(installed),
                    str(wheels[0]),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, install.returncode, install.stderr)
            script = """
import json
from datetime import datetime, timezone
from mox_adv.direct_action import DirectActionRuntimeV1
from mox_adv.environment import ExecutionEnvironment
from mox_adv.module_api.v1 import HttpJsonModuleAdapterV1
from mox_adv.modules.direct import DirectModuleV1
request = json.loads(__import__("os").environ["DIRECT_REQUEST"])
module = DirectModuleV1(
    clock=lambda: datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
)
response = HttpJsonModuleAdapterV1(
    module,
    environment=ExecutionEnvironment.PRODUCTION,
).handle(request)
assert response.status_code == 200, response.body
assert response.body["status"] == "PARTIAL", response.body
assert response.body["module"]["module_id"] == "YANDEX_DIRECT", response.body
assert DirectActionRuntimeV1.__name__ == "DirectActionRuntimeV1"
"""
            completed = subprocess.run(
                [sys.executable, "-c", script],
                check=False,
                capture_output=True,
                env={
                    "DIRECT_REQUEST": json.dumps(customer_evidence_request()),
                    "PYTHONPATH": str(installed),
                },
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)


if __name__ == "__main__":
    unittest.main()
