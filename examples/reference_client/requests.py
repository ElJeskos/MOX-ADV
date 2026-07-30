"""Pure-JSON request examples generated without provider implementation imports."""

from __future__ import annotations

from typing import Any, Dict


def metrika_provider_read() -> Dict[str, Any]:
    """Request one provider-owned Metrika read from a stored connection."""

    return {
        "schema_version": "module-request-v1",
        "connection_ref": {"connection_id": "customer-metrika-primary"},
        "environment": "PRODUCTION",
        "scope": {
            "organization_id": "customer-42",
            "campaign_id": "campaign-7",
            "counter_id": "counter-9",
            "goal_id": "goal-3",
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
        "operation": {
            "kind": "ANALYZE",
            "operation_type": "ANALYZE_PERFORMANCE",
        },
        "idempotency_key": "reference-metrika-read-1",
    }


def direct_provider_read() -> Dict[str, Any]:
    """Request one provider-owned Direct report and campaign-state read."""

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
        "operation": {
            "kind": "ANALYZE",
            "operation_type": "ANALYZE_PERFORMANCE",
        },
        "idempotency_key": "reference-direct-read-1",
    }


def direct_customer_evidence() -> Dict[str, Any]:
    """Submit normalized Direct observations owned by the customer ecosystem."""

    payload = direct_provider_read()
    payload["external_evidence"] = {
        "schema_version": "normalized-metrics-evidence-v1",
        "evidence_id": "reference-direct-evidence-1",
        "source": "CUSTOMER_ECOSYSTEM",
        "observed_at": "2026-07-30T11:55:00+00:00",
        "watermark": "2026-07-30T11:50:00+00:00",
        "metrics": [
            {"name": "impressions", "value": 10_000, "unit": "COUNT"},
            {"name": "clicks", "value": 200, "unit": "COUNT"},
            {
                "name": "cost_micros",
                "value": 4_000_000_000,
                "unit": "MICROS_RUB",
            },
            {"name": "conversions", "value": 20, "unit": "COUNT"},
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
                "value": 2_000_000_000,
                "unit": "MICROS_RUB",
            },
            {
                "name": "current_search_bid_micros",
                "value": 100_000_000,
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
    }
    payload["idempotency_key"] = "reference-direct-evidence-1"
    return payload


def invalid_direct_customer_evidence() -> Dict[str, Any]:
    """Demonstrate a typed validation error without sending unsafe fields."""

    payload = direct_customer_evidence()
    evidence = payload["external_evidence"]
    assert isinstance(evidence, dict)
    evidence["source"] = "UNSUPPORTED_SOURCE"
    payload["idempotency_key"] = "reference-direct-invalid-evidence-1"
    return payload


def direct_plan_intent(*, environment: str) -> Dict[str, Any]:
    """Ask Direct to plan one bounded high-level budget intent."""

    if environment not in {"PRODUCTION", "TEST"}:
        raise ValueError("environment must be PRODUCTION or TEST.")
    payload = direct_customer_evidence()
    payload["connection_ref"] = {"connection_id": "sim-connection"}
    payload["environment"] = environment
    payload["scope"] = {
        "organization_id": "sim-organization",
        "account_id": "sim-direct-account",
        "campaign_id": "campaign-7",
    }
    payload["operation"] = {
        "kind": "PLAN",
        "operation_type": "PLAN_OPTIMIZATION",
    }
    payload["direct_action_command"] = {
        "schema_version": "direct-action-command-v1",
        "command": "PLAN_INTENT",
        "action": "INCREASE_WEEKLY_BUDGET",
        "relative_step_percent": 10,
    }
    payload["idempotency_key"] = (
        "reference-direct-plan-" + environment.lower() + "-1"
    )
    return payload


def direct_execute_proposal(
    *,
    proposal_id: str,
    environment: str,
) -> Dict[str, Any]:
    """Request execution of an immutable proposal by identifier."""

    if not proposal_id:
        raise ValueError("proposal_id must not be empty.")
    payload = direct_plan_intent(environment=environment)
    payload["operation"] = {
        "kind": "EXECUTE",
        "operation_type": "APPLY_OPTIMIZATION",
    }
    payload["direct_action_command"] = {
        "schema_version": "direct-action-command-v1",
        "command": "EXECUTE_PROPOSAL",
        "proposal_id": proposal_id,
    }
    payload["idempotency_key"] = (
        "reference-direct-execute-" + environment.lower() + "-1"
    )
    return payload
