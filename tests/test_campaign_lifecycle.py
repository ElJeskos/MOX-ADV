from __future__ import annotations

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mox_adv.campaign_lifecycle import (
    CampaignApproval,
    CampaignCreationRequest,
    CampaignDraftSafetyBindings,
    CampaignLifecycleService,
    CampaignSagaState,
    CampaignSagaStore,
    CreationReservation,
    LifecycleRejected,
    validate_campaign_draft,
)
from mox_adv.direct_management import (
    DirectManagementConnectorV1,
    DirectStateTransitionRejected,
    FakeDirectManagementAdapter,
    ProductionPilotAuthority,
)
from mox_adv.recommend_contracts import CampaignDraftV1

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "gate0-policy.json"
NOW = datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc)


def load_policy() -> dict[str, object]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def draft_payload() -> dict[str, object]:
    return {
        "schema_version": "campaign-draft-v1",
        "draft_id": "draft-campaign-1",
        "name": "Lead service",
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


def make_reservation(
    *,
    reservation_id: str = "sim-campaign-creation-reservation",
    proposal_id: str = "proposal-create-1",
) -> CreationReservation:
    return CreationReservation(
        reservation_id=reservation_id,
        status="AVAILABLE",
        scope_binding="sim-direct-account",
        object_type="UNIFIED_CAMPAIGN",
        proposal_id=proposal_id,
        credential_profile="DIRECT_PILOT_WRITE",
        expires_at=NOW + timedelta(minutes=30),
    )


def make_request(
    draft: CampaignDraftV1,
    *,
    proposal_id: str = "proposal-create-1",
    execution_key: str = "execution-create-1",
) -> CampaignCreationRequest:
    return CampaignCreationRequest(
        run_id="run-create-1",
        execution_key=execution_key,
        proposal_id=proposal_id,
        approval_id="approval-create-1",
        account="sim-direct-account",
        credential_profile="DIRECT_PILOT_WRITE",
        reservation_id="sim-campaign-creation-reservation",
        draft=draft,
    )


def safety_bindings() -> CampaignDraftSafetyBindings:
    return CampaignDraftSafetyBindings(
        allowed_landing_hosts=("allowlisted.example",),
        prohibited_phrases=("guaranteed results",),
        prepared_media_references=("prepared-media-1", "prepared-media-2"),
    )


class CampaignDraftValidationTests(unittest.TestCase):
    def test_approved_unified_search_shape_is_validated_deterministically(self) -> None:
        policy = load_policy()
        draft = validate_campaign_draft(draft_payload(), policy, safety_bindings())

        self.assertEqual("UNIFIED_CAMPAIGN", draft.campaign_type)
        self.assertEqual(
            ("A", "B"), tuple(ad["variant_id"] for ad in draft.groups[0]["ads"])
        )

        rejected_values = []
        wrong_campaign = draft_payload()
        wrong_campaign["campaign_type"] = "TEXT_CAMPAIGN"
        rejected_values.append(wrong_campaign)

        one_ad = draft_payload()
        one_ad["groups"][0]["ads"].pop()
        rejected_values.append(one_ad)

        duplicate_copy = draft_payload()
        duplicate_copy["groups"][0]["ads"][1]["title"] = "Lead service"
        duplicate_copy["groups"][0]["ads"][1]["text"] = "Submit a request"
        rejected_values.append(duplicate_copy)

        foreign_landing = draft_payload()
        foreign_landing["groups"][0]["ads"][1]["landing_page"] = (
            "https://other.example/lead"
        )
        rejected_values.append(foreign_landing)

        prohibited_copy = draft_payload()
        prohibited_copy["groups"][0]["ads"][1]["text"] = "Guaranteed results"
        rejected_values.append(prohibited_copy)

        unprepared_media = draft_payload()
        unprepared_media["groups"][0]["ads"][1]["media_reference"] = "unprepared-media"
        unprepared_media["media_references"].append("unprepared-media")
        rejected_values.append(unprepared_media)

        for value in rejected_values:
            with self.subTest(value=value):
                with self.assertRaises(LifecycleRejected):
                    validate_campaign_draft(value, policy, safety_bindings())


class CampaignLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = Path(self.temporary_directory.name) / "campaign.sqlite3"
        self.policy = load_policy()
        self.adapter = FakeDirectManagementAdapter()
        self.store = CampaignSagaStore(self.database)
        self.store.register_creation_reservation(make_reservation(), NOW)
        self.draft = validate_campaign_draft(
            draft_payload(),
            self.policy,
            safety_bindings(),
        )
        self.request = make_request(self.draft)
        self.store.register_campaign_approval(
            CampaignApproval(
                approval_id=self.request.approval_id,
                proposal_id=self.request.proposal_id,
                binding_hash=self.request.approval_binding(
                    str(self.policy["policy_id"])
                ),
                approver="sviridov",
                authentication="authenticated_macos_user",
                expires_at=NOW + timedelta(minutes=15),
            )
        )

    def service(self) -> CampaignLifecycleService:
        return CampaignLifecycleService(
            policy=self.policy,
            store=CampaignSagaStore(self.database),
            connector=DirectManagementConnectorV1(
                self.policy,
                self.adapter,
                CampaignSagaStore(self.database),
            ),
            safety_bindings=safety_bindings(),
        )

    def test_saga_resumes_each_ordered_step_and_repeating_key_is_idempotent(
        self,
    ) -> None:
        expected_steps = (
            "CAMPAIGN_ADD",
            "AD_GROUP_ADD",
            "ADS_ADD",
            "KEYWORD_ADD",
            "MODERATION_SUBMIT",
            "MODERATION_READBACK",
            "CAMPAIGN_LAUNCH",
            "FULL_READBACK",
        )

        for expected_completed_count in range(1, len(expected_steps) + 1):
            result = self.service().execute(self.request, NOW, max_steps=1)
            self.assertEqual(
                expected_steps[:expected_completed_count], result.completed_steps
            )
            if expected_completed_count == 1:
                self.assertEqual(
                    "USED",
                    self.store.campaign_approval_status(self.request.approval_id),
                )

        self.assertEqual(CampaignSagaState.APPLIED, result.status)
        self.assertEqual(
            ("Campaigns", "AdGroups", "Ads", "Ads", "Keywords"),
            tuple(item.service for item in result.created_objects),
        )
        self.assertEqual(
            (
                ("Campaigns", "UNIFIED_CAMPAIGN"),
                ("AdGroups", "UNIFIED_AD_GROUP"),
                ("Ads", "TEXT_AD"),
                ("Ads", "TEXT_AD"),
                ("Keywords", "KEYWORD"),
            ),
            tuple((item.service, item.actual_type) for item in result.created_objects),
        )
        calls_after_completion = tuple(self.adapter.calls)

        repeated = self.service().execute(self.request, NOW)

        self.assertEqual(CampaignSagaState.ALREADY_PROCESSED, repeated.status)
        self.assertEqual(calls_after_completion, tuple(self.adapter.calls))
        self.assertEqual(1, self.adapter.operation_count("Campaigns", "add"))

    def test_changed_canonical_plan_requires_new_proposal_and_approval(self) -> None:
        self.service().execute(self.request, NOW, max_steps=1)
        changed_payload = draft_payload()
        changed_payload["budget"]["weekly_micros"] = 400_000_000
        changed_draft = validate_campaign_draft(
            changed_payload,
            self.policy,
            safety_bindings(),
        )
        changed_request = replace(self.request, draft=changed_draft)
        calls_before = tuple(self.adapter.calls)

        with self.assertRaisesRegex(
            LifecycleRejected,
            "NEW_PROPOSAL_AND_APPROVAL_REQUIRED",
        ):
            self.service().execute(changed_request, NOW)

        self.assertEqual(calls_before, tuple(self.adapter.calls))

    def test_missing_expired_or_used_creation_reservation_blocks_before_write(
        self,
    ) -> None:
        cases = (
            replace(self.request, reservation_id="missing"),
            replace(self.request, proposal_id="different-proposal"),
        )
        for request in cases:
            with self.subTest(request=request):
                with self.assertRaises(LifecycleRejected):
                    self.service().execute(request, NOW)
        self.assertEqual([], self.adapter.calls)

        expired_database = Path(self.temporary_directory.name) / "expired.sqlite3"
        expired_store = CampaignSagaStore(expired_database)
        expired_store.register_creation_reservation(
            replace(make_reservation(), expires_at=NOW - timedelta(seconds=1)),
            NOW - timedelta(minutes=5),
        )
        expired_service = CampaignLifecycleService(
            policy=self.policy,
            store=expired_store,
            connector=DirectManagementConnectorV1(
                self.policy,
                self.adapter,
                expired_store,
            ),
            safety_bindings=safety_bindings(),
        )
        with self.assertRaises(LifecycleRejected):
            expired_service.execute(self.request, NOW)
        self.assertEqual([], self.adapter.calls)

    def test_unknown_write_result_blocks_restart_without_blind_retry(self) -> None:
        adapter = FakeDirectManagementAdapter(timeout_after=("Campaigns", "add"))
        service = CampaignLifecycleService(
            self.policy,
            self.store,
            DirectManagementConnectorV1(self.policy, adapter, self.store),
            safety_bindings(),
        )

        first = service.execute(self.request, NOW)
        calls_after_unknown = tuple(adapter.calls)
        second = service.execute(self.request, NOW)

        self.assertEqual(CampaignSagaState.UNKNOWN_RESULT, first.status)
        self.assertEqual(CampaignSagaState.UNKNOWN_RESULT, second.status)
        self.assertEqual(calls_after_unknown, tuple(adapter.calls))
        self.assertEqual(1, adapter.operation_count("Campaigns", "add"))
        self.assertEqual(
            "USED",
            self.store.campaign_approval_status(self.request.approval_id),
        )

    def test_restart_after_persisted_dispatch_never_repeats_an_unknown_write(
        self,
    ) -> None:
        canonical_plan = self.request.canonical_plan(str(self.policy["policy_id"]))
        approver = self.policy["principals"]["approver"]
        self.store.start_or_load(
            self.request,
            canonical_plan,
            NOW,
            approver["identity"],
            approver["authentication"],
        )
        self.store.begin_step(self.request.execution_key, "CAMPAIGN_ADD", NOW)

        result = self.service().execute(self.request, NOW)

        self.assertEqual(CampaignSagaState.UNKNOWN_RESULT, result.status)
        self.assertEqual([], self.adapter.calls)
        self.assertIn("CAMPAIGN_ADD", result.detail)

    def test_failed_late_step_compensates_only_objects_created_by_run(self) -> None:
        adapter = FakeDirectManagementAdapter(fail_on=("Ads", "moderate"))
        service = CampaignLifecycleService(
            self.policy,
            self.store,
            DirectManagementConnectorV1(self.policy, adapter, self.store),
            safety_bindings(),
        )

        result = service.execute(self.request, NOW)

        self.assertEqual(CampaignSagaState.PARTIALLY_APPLIED, result.status)
        self.assertEqual((), adapter.object_ids())
        self.assertEqual(
            "USED",
            self.store.campaign_approval_status(self.request.approval_id),
        )
        self.assertEqual(
            {"Campaigns", "AdGroups", "Ads", "Keywords"},
            {
                service_name
                for service_name, method, _ in adapter.calls
                if method == "delete"
            },
        )

    def test_failed_compensation_requires_reconciliation(self) -> None:
        adapter = FakeDirectManagementAdapter(
            fail_on=("Ads", "moderate"),
            fail_compensation_on=("AdGroups", "delete"),
        )
        service = CampaignLifecycleService(
            self.policy,
            self.store,
            DirectManagementConnectorV1(self.policy, adapter, self.store),
            safety_bindings(),
        )

        result = service.execute(self.request, NOW)

        self.assertEqual(CampaignSagaState.COMPENSATION_REQUIRED, result.status)
        self.assertIn("AdGroups", {item.service for item in result.created_objects})

    def test_missing_or_unbound_approval_blocks_before_first_write(self) -> None:
        other_database = Path(self.temporary_directory.name) / "approval.sqlite3"
        store = CampaignSagaStore(other_database)
        store.register_creation_reservation(make_reservation(), NOW)
        service = CampaignLifecycleService(
            self.policy,
            store,
            DirectManagementConnectorV1(self.policy, self.adapter, store),
            safety_bindings(),
        )

        with self.assertRaises(LifecycleRejected):
            service.execute(self.request, NOW)

        self.assertEqual([], self.adapter.calls)

        unbound_database = Path(self.temporary_directory.name) / "unbound.sqlite3"
        unbound_store = CampaignSagaStore(unbound_database)
        unbound_store.register_creation_reservation(make_reservation(), NOW)
        unbound_store.register_campaign_approval(
            CampaignApproval(
                approval_id=self.request.approval_id,
                proposal_id=self.request.proposal_id,
                binding_hash="sha256:" + "0" * 64,
                approver="sviridov",
                authentication="authenticated_macos_user",
                expires_at=NOW + timedelta(minutes=15),
            )
        )
        unbound_service = CampaignLifecycleService(
            self.policy,
            unbound_store,
            DirectManagementConnectorV1(
                self.policy,
                self.adapter,
                unbound_store,
            ),
            safety_bindings(),
        )
        with self.assertRaises(LifecycleRejected):
            unbound_service.execute(self.request, NOW)
        self.assertEqual([], self.adapter.calls)

    def test_full_readback_rejects_structure_that_diverges_from_canonical_plan(
        self,
    ) -> None:
        first = self.service().execute(self.request, NOW, max_steps=7)
        campaign_id = next(
            item.object_id
            for item in first.created_objects
            if item.service == "Campaigns"
        )
        self.adapter.mutate_object(
            "Campaigns",
            campaign_id,
            {"WeeklySpendLimit": 1},
        )

        result = self.service().execute(self.request, NOW)

        self.assertNotEqual(CampaignSagaState.APPLIED, result.status)
        self.assertIn("FULL_CAMPAIGN_READBACK_FAILED", result.detail)

    def test_unexpected_type_is_registered_before_compensation(self) -> None:
        adapter = FakeDirectManagementAdapter(
            actual_type_overrides={"Campaigns": "WRONG_CAMPAIGN_TYPE"}
        )
        service = CampaignLifecycleService(
            self.policy,
            self.store,
            DirectManagementConnectorV1(self.policy, adapter, self.store),
            safety_bindings(),
        )

        result = service.execute(self.request, NOW)

        self.assertEqual(CampaignSagaState.PARTIALLY_APPLIED, result.status)
        self.assertEqual((), adapter.object_ids())
        self.assertEqual(
            "USED",
            self.store.campaign_approval_status(self.request.approval_id),
        )


class DirectIntegrationMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_policy()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = CampaignSagaStore(
            Path(self.temporary_directory.name) / "matrix.sqlite3"
        )
        self.adapter = FakeDirectManagementAdapter()
        self.connector = DirectManagementConnectorV1(
            self.policy,
            self.adapter,
            self.store,
        )
        self.run_id = "matrix-run-1"

    def test_every_fr002_method_has_typed_fake_adapter_coverage(self) -> None:
        campaign = self.connector.campaigns_add(
            self.run_id,
            "matrix:campaign:add",
            {"type": "UNIFIED_CAMPAIGN", "state": "SUSPENDED"},
        )[0]
        self.store.register_created_objects(
            self.run_id,
            "matrix:campaign:add",
            (campaign,),
        )
        campaign_readback = self.connector.campaigns_get(
            self.run_id,
            campaign.object_id,
        )
        self.assertEqual("UNIFIED_CAMPAIGN", campaign_readback[0]["type"])
        campaign_updated = self.connector.campaigns_update(
            self.run_id,
            campaign.object_id,
            {"WeeklySpendLimit": 600_000_000},
        )
        self.assertEqual(600_000_000, campaign_updated["WeeklySpendLimit"])
        self.assertEqual(
            "ON",
            self.connector.campaigns_resume(
                self.run_id,
                campaign.object_id,
            )["state"],
        )
        self.assertEqual(
            "SUSPENDED",
            self.connector.campaigns_suspend(
                self.run_id,
                campaign.object_id,
            )["state"],
        )
        self.assertEqual(
            "ARCHIVED",
            self.connector.campaigns_archive(
                self.run_id,
                campaign.object_id,
            )["state"],
        )
        self.assertEqual(
            "SUSPENDED",
            self.connector.campaigns_unarchive(
                self.run_id,
                campaign.object_id,
            )["state"],
        )

        group = self.connector.adgroups_add(
            self.run_id,
            "matrix:group:add",
            {"campaign_id": campaign.object_id, "name": "Initial"},
        )[0]
        self.store.register_created_objects(
            self.run_id,
            "matrix:group:add",
            (group,),
        )
        self.assertEqual(
            "Initial",
            self.connector.adgroups_get(
                self.run_id,
                group.object_id,
            )[0]["name"],
        )
        group_updated = self.connector.adgroups_update(
            self.run_id,
            group.object_id,
            {"Name": "Updated"},
        )
        self.assertEqual("Updated", group_updated["Name"])

        ads = self.connector.ads_add(
            self.run_id,
            "matrix:ads:add",
            {
                "ad_group_id": group.object_id,
                "items": [
                    {"variant_id": "A", "title": "A", "text": "Text A"},
                    {"variant_id": "B", "title": "B", "text": "Text B"},
                ],
            },
        )
        self.store.register_created_objects(self.run_id, "matrix:ads:add", ads)
        ad_id = ads[0].object_id
        self.assertEqual(
            ("A", "B"),
            tuple(
                item["variant_id"]
                for item in self.connector.ads_get(
                    self.run_id,
                    (item.object_id for item in ads),
                )
            ),
        )
        ad_updated = self.connector.ads_update(
            self.run_id,
            ad_id,
            {"Title": "Prepared title", "Text": "Prepared text"},
        )
        self.assertEqual("Prepared title", ad_updated["Title"])
        self.assertEqual(
            "MODERATION",
            self.connector.ads_moderate(self.run_id, (ad_id,))[0]["state"],
        )
        self.assertEqual(
            "ON",
            self.connector.ads_resume(self.run_id, ad_id)["state"],
        )
        self.assertEqual(
            "SUSPENDED",
            self.connector.ads_suspend(self.run_id, ad_id)["state"],
        )
        self.assertEqual(
            "ARCHIVED",
            self.connector.ads_archive(self.run_id, ad_id)["state"],
        )
        self.assertEqual(
            "SUSPENDED",
            self.connector.ads_unarchive(self.run_id, ad_id)["state"],
        )

        keyword = self.connector.keywords_add(
            self.run_id,
            "matrix:keyword:add",
            {"ad_group_id": group.object_id, "keyword": "lead service"},
        )[0]
        self.store.register_created_objects(
            self.run_id,
            "matrix:keyword:add",
            (keyword,),
        )
        self.assertEqual(
            "lead service",
            self.connector.keywords_get(
                self.run_id,
                keyword.object_id,
            )[0]["keyword"],
        )
        keyword_updated = self.connector.keywords_update(
            self.run_id,
            keyword.object_id,
            {"UserParam1": "prepared"},
        )
        self.assertEqual("prepared", keyword_updated["UserParam1"])
        bid_updated = self.connector.keyword_bids_set(
            self.run_id,
            keyword.object_id,
            {"SearchBid": 90_000_000},
        )
        self.assertEqual(90_000_000, bid_updated["SearchBid"])
        self.assertEqual(
            90_000_000,
            self.connector.keyword_bids_get(
                self.run_id,
                keyword.object_id,
            )[0]["SearchBid"],
        )
        self.assertEqual(
            "ON",
            self.connector.keywords_resume(
                self.run_id,
                keyword.object_id,
            )["state"],
        )
        self.assertEqual(
            "SUSPENDED",
            self.connector.keywords_suspend(
                self.run_id,
                keyword.object_id,
            )["state"],
        )
        self.connector.keywords_delete(self.run_id, keyword.object_id)

        for item in ads:
            current = self.adapter.inspect("Ads", item.object_id)
            if current["state"] == "DRAFT":
                self.connector.ads_moderate(self.run_id, (item.object_id,))
            if self.adapter.inspect("Ads", item.object_id)["state"] == "MODERATION":
                self.adapter.set_state("Ads", item.object_id, "SUSPENDED")
            elif self.adapter.inspect("Ads", item.object_id)["state"] == "DRAFT":
                self.adapter.set_state("Ads", item.object_id, "SUSPENDED")
            self.connector.ads_delete(self.run_id, item.object_id)
        self.connector.adgroups_delete(self.run_id, group.object_id)
        self.connector.campaigns_delete(self.run_id, campaign.object_id)

        required = {
            (item["service"], item["method"])
            for item in self.policy["api_matrix"]
            if item["system"] == "DIRECT"
            and item["service"]
            in {"Campaigns", "AdGroups", "Ads", "Keywords", "KeywordBids"}
        }
        observed = {(service, method) for service, method, _ in self.adapter.calls}
        self.assertEqual(required, observed)
        self.assertEqual((), self.adapter.object_ids())

    def test_invalid_transition_and_foreign_archive_delete_are_preflight_rejected(
        self,
    ) -> None:
        foreign_campaign = self.adapter.seed_object(
            "Campaigns",
            {"type": "UNIFIED_CAMPAIGN", "state": "ON"},
        )

        with self.assertRaises(DirectStateTransitionRejected):
            self.connector.campaigns_resume(self.run_id, foreign_campaign)
        with self.assertRaises(DirectStateTransitionRejected):
            self.connector.campaigns_archive(self.run_id, foreign_campaign)
        with self.assertRaises(DirectStateTransitionRejected):
            self.connector.campaigns_delete(self.run_id, foreign_campaign)

        self.assertEqual([], self.adapter.calls)

    def test_non_fake_connector_is_disabled_without_validated_pilot_authority(
        self,
    ) -> None:
        class NonFakeAdapter:
            is_fake = False

            def invoke(self, request: object) -> object:
                raise AssertionError("Production adapter must not be called.")

            def inspect(self, service: str, object_id: str) -> object:
                raise AssertionError("Production adapter must not be called.")

        connector = DirectManagementConnectorV1(
            self.policy,
            NonFakeAdapter(),
            self.store,
            ProductionPilotAuthority(
                account="sim-direct-account",
                credential_profile="DIRECT_PILOT_WRITE",
                approval_id="approval-1",
                proposal_id="proposal-1",
                execution_key="execution-1",
                binding_hash="sha256:" + "1" * 64,
                armed=True,
            ),
        )

        with self.assertRaises(DirectStateTransitionRejected):
            connector.campaigns_add(
                self.run_id,
                "production-attempt",
                {"type": "UNIFIED_CAMPAIGN", "state": "SUSPENDED"},
            )
