from __future__ import annotations

import json
import socket
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest import mock

from mox_adv.e2e_evidence import (
    CAPABILITY_EVIDENCE_PATHS,
    REQUIRED_CAPABILITIES,
    ExternalEgressBlocked,
    ReadOnlyEgressRecorder,
    final_capability_evidence,
    verify_e2e_artifact_manifest,
    write_final_e2e_artifacts,
)
from mox_adv.egress import CredentialProfile, EgressAuthority

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "config" / "gate0-policy.json"


def load_policy() -> dict[str, Any]:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def sample_artifacts() -> dict[str, dict[str, Any]]:
    return {
        "proposal.json": {
            "schema_version": "proposal-v1",
            "proposal_id": "simulated-proposal",
        },
        "approval.json": {
            "schema_version": "approval-v1",
            "approval_id": "simulated-approval",
            "proposal_id": "simulated-proposal",
            "used_at": "2026-07-30T12:00:00+00:00",
        },
        "change_diff.json": {
            "approval_required": {
                "proposal_id": "simulated-proposal",
                "before": 100,
                "after": 90,
                "readback": 90,
            },
        },
        "impact_report.json": {
            "schema_version": "impact-report-v1",
            "status": "OBSERVED_POST_CHANGE",
        },
        "observe-evidence.json": {
            "source": "LOCAL_FIXTURE",
            "snapshot_id": "snapshot-1",
        },
        "monitoring-evidence.json": {
            "status": "POLLED",
        },
        "lifecycle-evidence.json": {
            "campaign_status": "APPLIED",
            "goal_technical_status": "VERIFIED",
        },
    }


def sample_run_summary() -> dict[str, Any]:
    return {
        "source": "LOCAL_FIXTURE",
        "snapshot_id": "snapshot-1",
        "period_start": "2026-07-01",
        "period_end": "2026-07-07",
        "provenance": {"direct": "fixture", "metrika": "fixture"},
        "metrics": {"clicks": 10, "conversions": 2},
        "provider": "deterministic-fake",
        "model_id": "fixture-model-v1",
        "input_tokens": 10,
        "output_tokens": 5,
        "cost_rub": "0",
        "duration_ms": 12,
        "stage_durations_ms": {"observe": 7, "recommend": 5},
        "proposal_id": "simulated-proposal",
        "policy_decision": {"approval_required": "APPLIED"},
        "execution": {
            "technical_command": "SEALED_FAKE_ONLY",
            "before": {"budget": 100},
            "after": {"budget": 90},
            "readback": {"budget": 90},
            "final_object_state": {"budget": 90},
        },
    }


class ReadOnlyEgressRecorderTests(unittest.TestCase):
    def test_only_explicit_direct_reports_read_profile_can_reach_transport(
        self,
    ) -> None:
        policy = load_policy()
        policy["bindings"]["pilot"]["direct_account"] = "pilot-account"
        recorder = ReadOnlyEgressRecorder(policy)
        recorder.authorize_external(
            "POST",
            "https://api.direct.yandex.com/json/v5/reports",
            version="v5",
            service="Reports",
            operation="get",
            authority=EgressAuthority(
                CredentialProfile.DIRECT_PROD_READ,
                "pilot-account",
            ),
        )

        self.assertEqual(1, len(recorder.records))
        self.assertEqual("get", recorder.records[0].operation)
        recorder.assert_read_only()

    def test_write_and_event_send_are_hard_blocked_before_transport(self) -> None:
        policy = load_policy()
        policy["bindings"]["pilot"]["direct_account"] = "pilot-account"

        cases = (
            (
                "POST",
                "https://api.direct.yandex.com/json/v501/campaigns",
                "v501",
                "Campaigns",
                "update",
                CredentialProfile.DIRECT_PROD_READ,
                "pilot-account",
            ),
            (
                "POST",
                "https://mc.yandex.ru/watch/pilot-counter",
                "tag-v1",
                "BrowserTag",
                "reachGoal",
                CredentialProfile.TEST_SITE_PUBLISH,
                "sim-test-site-zone",
            ),
        )
        for (
            method,
            url,
            version,
            service,
            operation,
            profile,
            target,
        ) in cases:
            with self.subTest(operation=operation):
                recorder = ReadOnlyEgressRecorder(policy)
                with self.assertRaisesRegex(
                    ExternalEgressBlocked,
                    "BLOCKED_BEFORE_TRANSPORT",
                ):
                    recorder.authorize_external(
                        method,
                        url,
                        version=version,
                        service=service,
                        operation=operation,
                        authority=EgressAuthority(profile, target),
                    )
                self.assertEqual((), recorder.records)

    def test_browser_event_is_exactly_bound_and_duplicates_are_not_hidden(
        self,
    ) -> None:
        recorder = ReadOnlyEgressRecorder(load_policy())
        exact_url = "https://mc.yandex.ru/watch/sim-test-counter?event=lead_submitted"

        self.assertEqual(
            "INTERCEPTED_EVENT",
            recorder.record_browser_request(
                "POST",
                exact_url,
                expected_counter_id="sim-test-counter",
                expected_event="lead_submitted",
            ),
        )
        self.assertIsNotNone(
            recorder.browser_event("sim-test-counter", "lead_submitted")
        )
        recorder.record_browser_request(
            "POST",
            exact_url,
            expected_counter_id="sim-test-counter",
            expected_event="lead_submitted",
        )
        self.assertIsNone(recorder.browser_event("sim-test-counter", "lead_submitted"))

    def test_browser_and_python_egress_reject_unexpected_transport(self) -> None:
        cases = (
            (
                "GET",
                ("https://mc.yandex.ru/watch/sim-test-counter?event=lead_submitted"),
            ),
            (
                "POST",
                ("https://mc.yandex.ru/watch/other-counter?event=lead_submitted"),
            ),
            (
                "POST",
                "https://mc.yandex.ru/watch/sim-test-counter?event=other",
            ),
            (
                "POST",
                (
                    "https://mc.yandex.ru/watch/sim-test-counter"
                    "?event=lead_submitted&ignored="
                ),
            ),
        )
        for method, url in cases:
            with self.subTest(method=method, url=url):
                recorder = ReadOnlyEgressRecorder(load_policy())
                with self.assertRaisesRegex(
                    ExternalEgressBlocked,
                    "BLOCKED_BEFORE_TRANSPORT",
                ):
                    recorder.record_browser_request(
                        method,
                        url,
                        expected_counter_id="sim-test-counter",
                        expected_event="lead_submitted",
                    )

        recorder = ReadOnlyEgressRecorder(load_policy())
        with (
            recorder.enforce_python_sockets(),
            socket.socket() as client,
            self.assertRaisesRegex(
                ExternalEgressBlocked,
                "BLOCKED_BEFORE_TRANSPORT",
            ),
        ):
            client.connect_ex(("external.invalid", 443))

    def test_connectionless_socket_sends_are_blocked_before_transport(
        self,
    ) -> None:
        sendto_transport = mock.Mock(return_value=1)
        with mock.patch.object(socket.socket, "sendto", sendto_transport):
            recorder = ReadOnlyEgressRecorder(load_policy())
            with (
                recorder.enforce_python_sockets(),
                socket.socket(type=socket.SOCK_DGRAM) as client,
                self.assertRaisesRegex(
                    ExternalEgressBlocked,
                    "BLOCKED_BEFORE_TRANSPORT",
                ),
            ):
                client.sendto(b"blocked", ("external.invalid", 53))
        sendto_transport.assert_not_called()

        if not hasattr(socket.socket, "sendmsg"):
            return
        sendmsg_transport = mock.Mock(return_value=1)
        with mock.patch.object(socket.socket, "sendmsg", sendmsg_transport):
            recorder = ReadOnlyEgressRecorder(load_policy())
            with (
                recorder.enforce_python_sockets(),
                socket.socket(type=socket.SOCK_DGRAM) as client,
                self.assertRaisesRegex(
                    ExternalEgressBlocked,
                    "BLOCKED_BEFORE_TRANSPORT",
                ),
            ):
                client.sendmsg(
                    [b"blocked"],
                    [],
                    0,
                    ("external.invalid", 53),
                )
        sendmsg_transport.assert_not_called()

        connected_transport = mock.Mock(return_value=7)
        with mock.patch.object(socket.socket, "sendmsg", connected_transport):
            recorder = ReadOnlyEgressRecorder(load_policy())
            with (
                recorder.enforce_python_sockets(),
                socket.socket(type=socket.SOCK_DGRAM) as client,
            ):
                sent = client.sendmsg([b"local"])
        self.assertEqual(7, sent)
        connected_transport.assert_called_once_with(
            client,
            [b"local"],
            (),
            0,
        )


class FinalEvidenceTests(unittest.TestCase):
    def test_exact_14_capabilities_are_honest_and_never_claim_controlled_pilot(
        self,
    ) -> None:
        evidence = final_capability_evidence()

        self.assertEqual(14, len(evidence))
        self.assertEqual(
            REQUIRED_CAPABILITIES, tuple(item.capability for item in evidence)
        )
        self.assertNotIn("PROVEN", {item.status for item in evidence})
        self.assertNotIn("CONTROLLED_PILOT", {item.evidence_type for item in evidence})
        self.assertEqual(
            "NOT_TESTED",
            next(
                item.status
                for item in evidence
                if item.capability == "CLOSED_LOOP_CONTROL"
            ),
        )
        for item in evidence:
            self.assertEqual(
                CAPABILITY_EVIDENCE_PATHS[item.capability],
                item.evidence_paths,
            )

    def test_mandatory_artifacts_and_stability_fingerprint_are_reproducible(
        self,
    ) -> None:
        checks = (
            {"name": "analytics_optimization", "status": "PASSED"},
            {"name": "campaign_goal_lifecycle", "status": "PASSED"},
            {"name": "playwright_local_goal_event", "status": "PASSED"},
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = write_final_e2e_artifacts(
                root,
                run_id="readonly-pass-1",
                policy_version="mox-adv-gate0-2026-07-29",
                checks=checks,
                egress=ReadOnlyEgressRecorder(load_policy()),
                supplemental_artifacts=sample_artifacts(),
                run_summary=sample_run_summary(),
            )
            second = write_final_e2e_artifacts(
                root,
                run_id="readonly-pass-2",
                policy_version="mox-adv-gate0-2026-07-29",
                checks=checks,
                egress=ReadOnlyEgressRecorder(load_policy()),
                supplemental_artifacts=sample_artifacts(),
                run_summary=sample_run_summary(),
            )

            required = {
                ".audit.sqlite3",
                "result.json",
                "report.md",
                "events.jsonl",
                "capability-evidence.json",
                "external-egress.jsonl",
                "signed-audit-anchor.json",
                "stability-fingerprint.json",
                "proposal.json",
                "approval.json",
                "change_diff.json",
                "impact_report.json",
                "observe-evidence.json",
                "monitoring-evidence.json",
                "lifecycle-evidence.json",
                "artifact-manifest.json",
            }
            self.assertTrue(required.issubset({path.name for path in first.iterdir()}))
            verify_e2e_artifact_manifest(first)
            verify_e2e_artifact_manifest(second)
            self.assertEqual("", (first / "external-egress.jsonl").read_text())
            first_stability = json.loads(
                (first / "stability-fingerprint.json").read_text()
            )
            second_stability = json.loads(
                (second / "stability-fingerprint.json").read_text()
            )
            self.assertEqual(first_stability, second_stability)
            self.assertEqual(
                14,
                len(
                    json.loads((first / "capability-evidence.json").read_text())[
                        "capabilities"
                    ]
                ),
            )
            result = json.loads((first / "result.json").read_text())
            self.assertEqual("snapshot-1", result["snapshot_id"])
            self.assertEqual("deterministic-fake", result["provider"])
            self.assertEqual("SEALED_FAKE_ONLY", result["technical_command"])
            self.assertEqual({"budget": 90}, result["readback"])
            self.assertEqual(0, result["browser_websocket_block_count"])
            events = [
                json.loads(line)
                for line in (first / "events.jsonl").read_text().splitlines()
            ]
            self.assertTrue(
                {
                    "llm.proposal.recorded",
                    "policy.decision.recorded",
                    "executor.result.recorded",
                }.issubset({event["event_type"] for event in events})
            )

    def test_manifest_and_stability_detect_artifact_content_changes(self) -> None:
        checks = ({"name": "local", "status": "PASSED"},)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = write_final_e2e_artifacts(
                root,
                run_id="content-pass-1",
                policy_version="mox-adv-gate0-2026-07-29",
                checks=checks,
                egress=ReadOnlyEgressRecorder(load_policy()),
                supplemental_artifacts=sample_artifacts(),
                run_summary=sample_run_summary(),
            )
            changed = deepcopy(sample_artifacts())
            changed["monitoring-evidence.json"]["status"] = "ALERTED"
            second = write_final_e2e_artifacts(
                root,
                run_id="content-pass-2",
                policy_version="mox-adv-gate0-2026-07-29",
                checks=checks,
                egress=ReadOnlyEgressRecorder(load_policy()),
                supplemental_artifacts=changed,
                run_summary=sample_run_summary(),
            )

            first_fingerprint = json.loads(
                (first / "stability-fingerprint.json").read_text()
            )["fingerprint"]
            second_fingerprint = json.loads(
                (second / "stability-fingerprint.json").read_text()
            )["fingerprint"]
            self.assertNotEqual(first_fingerprint, second_fingerprint)
            (first / "proposal.json").write_text(
                '{"proposal_id":"tampered"}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "digest changed"):
                verify_e2e_artifact_manifest(first)


if __name__ == "__main__":
    unittest.main()
