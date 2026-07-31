#!/usr/bin/env python3
"""Validate the MOX-ADV Gate 0 record without contacting external services."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Optional


DIRECT_METHODS = {
    "Campaigns": {
        "add", "get", "update", "suspend", "resume", "archive", "unarchive", "delete"
    },
    "AdGroups": {"add", "get", "update", "delete"},
    "Ads": {
        "add", "get", "update", "suspend", "resume", "archive", "unarchive",
        "moderate", "delete",
    },
    "Keywords": {"add", "get", "update", "suspend", "resume", "delete"},
    "KeywordBids": {"get", "set"},
}

OTHER_API = {
    ("DIRECT_REPORTS", "v501", "Reports", "get"): (
        "api.direct.yandex.com", "/json/v501/reports", "POST", "READ_ONLY",
        "DOCUMENTED_NOT_EXECUTED",
    ),
    ("METRIKA", "v1", "Statistics", "get"): (
        "api-metrika.yandex.net", "/stat/v1/data", "GET", "READ_ONLY",
        "DOCUMENTED_NOT_EXECUTED",
    ),
    ("METRIKA", "v1", "Goals", "getGoals"): (
        "api-metrika.yandex.net", "/management/v1/counter/{counter_id}/goals",
        "GET", "GOAL_READBACK", "DOCUMENTED_NOT_EXECUTED",
    ),
    ("METRIKA", "v1", "Goals", "addGoal"): (
        "api-metrika.yandex.net", "/management/v1/counter/{counter_id}/goals",
        "POST", "GOAL_LIFECYCLE_WRITE", "DOCUMENTED_NOT_EXECUTED",
    ),
    ("METRIKA", "v1", "Goals", "getGoal"): (
        "api-metrika.yandex.net",
        "/management/v1/counter/{counter_id}/goal/{goal_id}", "GET",
        "GOAL_READBACK", "DOCUMENTED_NOT_EXECUTED",
    ),
    ("METRIKA", "v1", "Goals", "deleteGoal"): (
        "api-metrika.yandex.net",
        "/management/v1/counter/{counter_id}/goal/{goal_id}", "DELETE",
        "GOAL_LIFECYCLE_WRITE", "DOCUMENTED_NOT_EXECUTED",
    ),
    ("METRIKA_BROWSER", "tag-v1", "BrowserTag", "reachGoal"): (
        "mc.yandex.ru", "/watch/{counter_id}", "POST", "SITE_EVENT_WRITE",
        "PLAYWRIGHT_REQUIRED",
    ),
}

BINDING_TYPES = {
    "organization": "organization",
    "connection": "connection",
    "direct_account": "direct_account",
    "campaign_creation_reservation": "creation_reservation",
    "readonly_baseline_campaign": "campaign",
    "test_counter": "counter",
    "pilot_counter": "counter",
    "primary_goal": "goal",
    "test_candidate_goal_reservation": "creation_reservation",
    "pilot_candidate_goal_reservation": "creation_reservation",
    "test_site_zone": "site_zone",
    "pilot_site_zone": "site_zone",
    "single_writer": "writer",
}

TOP_FIELDS = {
    "schema_version", "policy_id", "record", "environment", "conversion",
    "attribution", "campaign", "principals", "commands", "credentials", "bindings",
    "limits", "timing", "monitoring", "actions", "mandate", "kill_switch", "impact",
    "llm", "governance", "api_matrix",
}
CREDENTIAL_PROFILES = {
    "DIRECT_PROD_READ", "METRIKA_PROD_READ", "METRIKA_TEST_WRITE",
    "TEST_SITE_PUBLISH",
    "DIRECT_PILOT_WRITE", "METRIKA_PILOT_WRITE", "PILOT_SITE_PUBLISH",
}
LIMIT_FIELDS = {
    "platform_weekly_spend_rub", "application_daily_spend_rub",
    "mandate_total_exposure_rub", "mandate_daily_exposure_rub",
    "no_conversion_stop_spend_rub", "mandate_ttl_hours",
    "mandate_actions_per_24h", "maximum_step_percent",
    "maximum_daily_cumulative_change_percent", "llm_total_cost_rub",
    "llm_warning_percent",
}
TIMING_FIELDS = {
    "read_poll_minutes", "direct_freshness_minutes", "metrika_freshness_hours",
    "maximum_watermark_skew_hours", "late_conversion_cutoff_hours",
    "observation_window_hours", "cooldown_hours",
    "goal_verification_timeout_minutes", "goal_verification_poll_minutes",
    "kill_switch_blocking_sla_seconds",
}
MONITORING_FIELDS = {
    "budget_pressure_usage_percent", "pacing_ahead_percent",
    "spend_growth_without_conversion_rub", "high_cpa_rub",
    "cpc_deviation_from_baseline_percent", "low_ctr_percent",
    "ctr_deviation_from_baseline_percent", "low_ctr_minimum_impressions",
    "conversion_rate_deviation_from_baseline_percent",
    "no_conversion_goal_visits", "no_conversion_spend_rub",
    "goal_cessation_hours", "goal_cessation_minimum_visits",
    "source_mismatch_percent", "direct_freshness_minutes",
    "metrika_freshness_hours",
}
LLM_FIXTURES = {
    "LLM_EFFECTIVE_BUDGET_PRESSURE", "LLM_INEFFECTIVE_NO_CONVERSION",
    "LLM_INSUFFICIENT_SAMPLE", "LLM_AMBIGUOUS_TRACKING",
}
LLM_FIXTURE_EXPECTATIONS = {
    "LLM_EFFECTIVE_BUDGET_PRESSURE": "EFFECTIVE",
    "LLM_INEFFECTIVE_NO_CONVERSION": "INEFFECTIVE",
    "LLM_INSUFFICIENT_SAMPLE": "INSUFFICIENT_DATA",
    "LLM_AMBIGUOUS_TRACKING": "NEEDS_HUMAN",
}
API_FIELDS = {
    "system", "environment", "host", "path", "version", "service", "method",
    "http_verb", "access_class", "verification_status",
}
APPROVED_POLICY_SHA256 = (
    "a17ff1959ed1e93cef3b33c9b163288361615f8e0c097b3d288690de595a3fe4"
)


def load_policy(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("Gate 0 policy must be a JSON object")
    return value


def _exact_fields(
    value: Any,
    expected: set[str],
    path: str,
    errors: list[str],
) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{path}: expected an object")
        return False
    for name in sorted(set(value) - expected):
        errors.append(f"{path}.{name}: unknown field")
    for name in sorted(expected - set(value)):
        errors.append(f"{path}.{name}: missing required field")
    return set(value) == expected


def _positive(
    values: dict[str, Any],
    path: str,
    errors: list[str],
    allow_zero: set[str] = set(),
) -> None:
    for name, value in values.items():
        number = isinstance(value, (int, float)) and not isinstance(value, bool)
        if not number or value < (0 if name in allow_zero else 0.0000001):
            errors.append(f"{path}.{name}: invalid numeric limit")


def _validate_structure(policy: dict[str, Any], errors: list[str]) -> None:
    _exact_fields(policy, TOP_FIELDS, "policy", errors)
    _exact_fields(policy.get("limits"), LIMIT_FIELDS, "limits", errors)
    _exact_fields(policy.get("timing"), TIMING_FIELDS, "timing", errors)
    monitoring = policy.get("monitoring")
    if _exact_fields(monitoring, {"poll_minutes", "anomaly_thresholds"}, "monitoring", errors):
        _exact_fields(
            monitoring["anomaly_thresholds"],
            MONITORING_FIELDS,
            "monitoring.anomaly_thresholds",
            errors,
        )
    conversion = policy.get("conversion")
    if _exact_fields(conversion, {"primary", "microconversions"}, "conversion", errors):
        _exact_fields(
            conversion["primary"],
            {"event", "classification", "business_meaning"},
            "conversion.primary",
            errors,
        )
        for index, item in enumerate(conversion["microconversions"]):
            _exact_fields(
                item,
                {"event", "classification", "business_meaning"},
                f"conversion.microconversions[{index}]",
                errors,
            )
    mandate = policy.get("mandate")
    if _exact_fields(
        mandate,
        {
            "object_type", "allowed_action_classes", "prohibited_action_classes",
            "kpi", "minimum_sample", "stop_conditions", "canonical_fields",
            "hash_algorithm", "signature", "activation_versioned",
            "revocation_versioned", "durable_after_restart",
            "quota_reservation_atomic_with_execution_key",
        },
        "mandate",
        errors,
    ):
        _exact_fields(mandate["kpi"], {"name", "target_maximum"}, "mandate.kpi", errors)
        _exact_fields(
            mandate["minimum_sample"],
            {"clicks", "conversions"},
            "mandate.minimum_sample",
            errors,
        )
    for index, item in enumerate(policy.get("api_matrix", [])):
        _exact_fields(item, API_FIELDS, f"api_matrix[{index}]", errors)


def _validate_record_and_authority(
    policy: dict[str, Any],
    errors: list[str],
) -> None:
    record = policy.get("record", {})
    expected_status = {
        "language": "English",
        "normative_requirements_source": "requirements-v2-prototype.md",
        "policy_decisions_status": "APPROVED",
        "simulation_status": "READY",
        "controlled_pilot_status": "BLOCKED_UNTIL_TRUSTED_BINDINGS",
        "production_write_authorized": False,
    }
    if policy.get("schema_version") != "gate0-policy-v1" or any(
        record.get(name) != value for name, value in expected_status.items()
    ):
        errors.append("record: Gate 0 status mismatch")
    if policy.get("environment") != {
        "direct": "production_only",
        "metrika": "production_api",
        "simulation_write_egress": False,
    }:
        errors.append("environment: unsupported environment policy")
    if policy.get("campaign") != {
        "type": "UNIFIED_CAMPAIGN",
        "placement": "SEARCH",
        "search_strategy": "HIGHEST_POSITION",
        "network_strategy": "SERVING_OFF",
    }:
        errors.append("campaign: approved configuration mismatch")
    conversion = policy.get("conversion", {})
    primary = conversion.get("primary", {})
    micro = conversion.get("microconversions", [])
    if primary.get("classification") != "PRIMARY" or not primary.get("event"):
        errors.append("conversion.primary: invalid")
    if len({
        item.get("event")
        for item in micro
        if item.get("classification") == "MICRO" and item.get("business_meaning")
    }) != 2:
        errors.append("conversion.microconversions: expected two unique values")
    if any(
        not isinstance(command, str) or not command.startswith("mox-adv ")
        for command in policy.get("commands", {}).values()
    ):
        errors.append("commands: exact CLI commands are required")
    principals = policy.get("principals", {})
    owner = principals.get("owner", {}).get("identity")
    for role, item in principals.items():
        if (
            item.get("identity") != owner
            or item.get("authentication") != "authenticated_macos_user"
        ):
            errors.append(f"principals.{role}: role mismatch")
    credentials = policy.get("credentials", {})
    forbidden = {
        "source", "environment_variables", "argv", "logs", "artifacts",
        "exceptions", "docker_metadata", "unprotected_files",
    }
    if (
        credentials.get("storage") != "macos_keychain"
        or set(credentials.get("forbidden_channels", [])) != forbidden
    ):
        errors.append("credentials: isolation mismatch")
    if credentials.get("local_read_only_override") != {
        "surface": "dashboard",
        "storage": "protected_dotenv_file",
        "path": ".env",
        "required_file_access": "owner_only_0600_or_stricter",
        "process_environment_import": False,
        "write_profiles_allowed": False,
        "bindings": {
            "DIRECT_PROD_READ": "YANDEX_DIRECT_OAUTH_TOKEN",
            "METRIKA_PROD_READ": "YANDEX_METRICA_OAUTH_TOKEN",
        },
        "configuration_bindings": {
            "direct_client_login": "YANDEX_DIRECT_CLIENT_LOGIN",
            "metrika_counter_ids": "YANDEX_METRICA_COUNTER_IDS",
        },
    }:
        errors.append("credentials: local read-only override mismatch")
    profiles = credentials.get("profiles", [])
    if {item.get("name") for item in profiles} != CREDENTIAL_PROFILES:
        errors.append("credentials.profiles: profile set mismatch")
    for index, item in enumerate(profiles):
        if item.get("principal") != f"{owner}:{item.get('name')}":
            errors.append(f"credentials.profiles[{index}]: principal mismatch")
    governance = policy.get("governance", {})
    if any(value != owner for value in governance.get("raci", {}).values()):
        errors.append("governance.raci: role mismatch")
    gates = governance.get("gates", [])
    if (
        [item.get("gate") for item in gates] != [0, 1, 2, 3, 4]
        or any(item.get("evidence_owner") != owner for item in gates)
        or governance.get("gate_order") != [0, 1, 2, 3, 4]
    ):
        errors.append("governance.gates: order or owner mismatch")
    if (
        set(governance.get("preliminary_signoff", {}).values()) != {"APPROVED"}
        or set(governance.get("final_signoff", {}).values()) != {"PENDING"}
        or governance.get("residual_risk_owner") != owner
    ):
        errors.append("governance: sign-off mismatch")


def _validate_bindings(
    policy: dict[str, Any],
    profile: str,
    manifest: Optional[dict[str, Any]],
    validation_time: dt.datetime,
    errors: list[str],
) -> None:
    bindings = policy.get("bindings", {})
    maximum_age = bindings.get("trusted_manifest_max_age_minutes")
    if (
        bindings.get("source") != "trusted_runtime_binding"
        or bindings.get("manifest_verification") != "READBACK_ATTESTED"
        or not isinstance(maximum_age, int)
        or maximum_age <= 0
    ):
        errors.append("bindings: trusted-manifest policy mismatch")
    if any(
        not isinstance(value, str) or not value.startswith("sim-")
        for value in bindings.get("simulation", {}).values()
    ):
        errors.append("simulation bindings must use fixed sim- identifiers")
    if any(value is not None for value in bindings.get("pilot", {}).values()):
        errors.append("pilot production identifiers must not be committed")
    if profile != "pilot":
        return
    if manifest is None:
        errors.append("pilot bindings are unresolved")
        return
    fields = {"manifest_version", "issuer", "issued_at", "bindings"}
    if not _exact_fields(manifest, fields, "trusted_manifest", errors):
        return
    owner = policy.get("principals", {}).get("owner", {}).get("identity")
    if (
        manifest.get("manifest_version") != "trusted-binding-manifest-v1"
        or manifest.get("issuer") != owner
    ):
        errors.append("trusted binding manifest: authority mismatch")
    issued_at = None
    try:
        issued_at = dt.datetime.fromisoformat(
            str(manifest.get("issued_at")).replace("Z", "+00:00")
        )
        if issued_at.tzinfo is None:
            raise ValueError
    except ValueError:
        errors.append("trusted binding manifest: invalid issued_at")
    if issued_at is not None and (
        issued_at > validation_time
        or validation_time - issued_at
        > dt.timedelta(minutes=maximum_age)
    ):
        errors.append("trusted binding manifest: stale or future issued_at")
    resolved = manifest.get("bindings")
    if not isinstance(resolved, dict) or set(resolved) != set(BINDING_TYPES):
        errors.append("pilot bindings are unresolved")
        return
    item_fields = {
        "value", "binding_type", "source", "allowlisted", "ownership_verified",
        "verification_status", "readback_evidence",
    }
    placeholders = ("sim-", "test-", "trusted-", "example", "<")
    for name, binding_type in BINDING_TYPES.items():
        item = resolved[name]
        expected_item_fields = set(item_fields)
        if binding_type == "creation_reservation":
            expected_item_fields.add("reservation")
        if not _exact_fields(
            item,
            expected_item_fields,
            f"trusted_binding.{name}",
            errors,
        ):
            continue
        value = item.get("value")
        if (
            not isinstance(value, str)
            or not value.strip()
            or value.lower().startswith(placeholders)
        ):
            errors.append(f"trusted binding {name}: unresolved value")
        if item.get("binding_type") != binding_type:
            errors.append(f"trusted binding {name}: type mismatch")
        if (
            item.get("source") != "trusted_run_context"
            or item.get("allowlisted") is not True
            or item.get("ownership_verified") is not True
            or item.get("verification_status") != "VERIFIED"
        ):
            errors.append(f"trusted binding {name}: unverified authority")
        evidence = item.get("readback_evidence")
        evidence_fields = {"evidence_type", "evidence_id", "observed_at"}
        if _exact_fields(
            evidence,
            evidence_fields,
            f"trusted_binding.{name}.readback_evidence",
            errors,
        ):
            expected_type = (
                "LOCAL_RESERVATION"
                if binding_type == "creation_reservation"
                else "API_OR_SITE_READBACK"
            )
            if evidence.get("evidence_type") != expected_type or not evidence.get(
                "evidence_id"
            ):
                errors.append(f"trusted binding {name}: invalid readback evidence")
            observed = None
            try:
                observed = dt.datetime.fromisoformat(
                    str(evidence.get("observed_at")).replace("Z", "+00:00")
                )
                if observed.tzinfo is None:
                    raise ValueError
            except ValueError:
                errors.append(f"trusted binding {name}: invalid readback time")
            if observed is not None and (
                observed > validation_time
                or validation_time - observed
                > dt.timedelta(minutes=maximum_age)
            ):
                errors.append(f"trusted binding {name}: stale or future readback")
        if binding_type == "creation_reservation":
            contract = bindings["creation_reservation_contract"]
            required = set(contract["required_fields"])
            reservation = item.get("reservation")
            if not _exact_fields(
                reservation,
                required,
                f"trusted_binding.{name}.reservation",
                errors,
            ):
                continue
            expected = contract["bindings"][name]
            if (
                reservation.get("status") != "UNUSED"
                or reservation.get("scope_binding") != expected["scope_binding"]
                or reservation.get("object_type") != expected["object_type"]
                or reservation.get("credential_profile")
                != expected["credential_profile"]
                or not reservation.get("proposal_id")
            ):
                errors.append(f"trusted binding {name}: reservation mismatch")
            try:
                expiry = dt.datetime.fromisoformat(
                    str(reservation.get("expires_at")).replace("Z", "+00:00")
                )
                if expiry.tzinfo is None or expiry <= validation_time:
                    raise ValueError
            except ValueError:
                errors.append(f"trusted binding {name}: invalid reservation expiry")


def _validate_limits_and_controls(
    policy: dict[str, Any],
    errors: list[str],
) -> None:
    limits = policy.get("limits", {})
    timing = policy.get("timing", {})
    monitoring = policy.get("monitoring", {})
    thresholds = monitoring.get("anomaly_thresholds", {})
    _positive(limits, "limits", errors)
    _positive(timing, "timing", errors)
    _positive(
        thresholds,
        "monitoring.anomaly_thresholds",
        errors,
        allow_zero={"no_conversion_goal_visits"},
    )
    if limits.get("application_daily_spend_rub", 0) > limits.get(
        "platform_weekly_spend_rub", 0
    ):
        errors.append("limits: daily spend cap exceeds weekly cap")
    if limits.get("mandate_total_exposure_rub", 0) > limits.get(
        "application_daily_spend_rub", 0
    ):
        errors.append("limits: Mandate total exceeds application daily cap")
    if limits.get("mandate_daily_exposure_rub", 0) > limits.get(
        "mandate_total_exposure_rub", 0
    ):
        errors.append("limits: Mandate daily limit exceeds total limit")
    if limits.get("maximum_step_percent", 0) > limits.get(
        "maximum_daily_cumulative_change_percent", 0
    ):
        errors.append("limits: step exceeds daily change cap")
    if not 0 < limits.get("llm_warning_percent", 0) < 100:
        errors.append("limits: invalid LLM warning threshold")
    if (
        timing.get("cooldown_hours", 0) < timing.get("observation_window_hours", 0)
        or timing.get("goal_verification_poll_minutes", 0)
        >= timing.get("goal_verification_timeout_minutes", 0)
    ):
        errors.append("timing: invalid cooldown or polling window")
    if (
        monitoring.get("poll_minutes") != timing.get("read_poll_minutes")
        or thresholds.get("direct_freshness_minutes")
        != timing.get("direct_freshness_minutes")
        or thresholds.get("metrika_freshness_hours")
        != timing.get("metrika_freshness_hours")
    ):
        errors.append("monitoring: timing mismatch")
    actions = policy.get("actions", {})
    mandate = policy.get("mandate", {})
    bounded = set(actions.get("bounded_autonomy", []))
    if (
        bounded != {"DECREASE_SEARCH_BID", "SUSPEND_CAMPAIGN"}
        or set(mandate.get("allowed_action_classes", [])) != bounded
        or bounded & set(mandate.get("prohibited_action_classes", []))
    ):
        errors.append("mandate: autonomous action scope mismatch")
    if (
        actions.get("readback_required") is not True
        or actions.get("second_change_before_observation_window") is not False
    ):
        errors.append("actions: readback or observation policy mismatch")
    canonical = {
        "organization", "connection", "account", "environment",
        "credential_profile", "targets", "allowed_action_classes",
        "prohibited_action_classes", "total_monetary_limit",
        "daily_monetary_limit", "maximum_step_change", "maximum_daily_change",
        "kpi", "minimum_sample", "cooldown", "stop_conditions", "action_quotas",
        "platform_side_spend_cap", "issuer", "policy_version", "issued_at", "expiry",
    }
    if set(mandate.get("canonical_fields", [])) != canonical:
        errors.append("mandate.canonical_fields: mismatch")
    if mandate.get("kpi", {}).get("target_maximum", 0) <= 0 or any(
        value <= 0 for value in mandate.get("minimum_sample", {}).values()
    ):
        errors.append("mandate: KPI or minimum sample is invalid")
    required_flags = {
        "activation_versioned", "revocation_versioned", "durable_after_restart",
        "quota_reservation_atomic_with_execution_key",
    }
    if any(mandate.get(name) is not True for name in required_flags):
        errors.append("mandate: durable state policy mismatch")
    kill_switch = policy.get("kill_switch", {})
    if (
        kill_switch.get("storage") != "DURABLE_SERVER_SIDE"
        or set(kill_switch.get("scopes", []))
        != {"global", "organization", "connection", "campaign"}
        or set(kill_switch.get("precedence_over", [])) != {"Approval", "Mandate"}
        or kill_switch.get("unavailable_state") != "BLOCKED"
        or kill_switch.get("already_sent_request")
        != "IN_FLIGHT_RECONCILIATION_WITHOUT_RETRY"
        or kill_switch.get("blocking_sla_seconds")
        != timing.get("kill_switch_blocking_sla_seconds")
        or set(kill_switch.get("engage_requires", []))
        != {"INCIDENT_PRINCIPAL"}
        or set(kill_switch.get("release_requires", []))
        != {"INCIDENT_PRINCIPAL", "ELEVATED_REAUTHENTICATION"}
    ):
        errors.append("kill_switch: fail-closed policy mismatch")


def _validate_api(policy: dict[str, Any], errors: list[str]) -> None:
    expected = {
        ("DIRECT", "v501", service, method)
        for service, methods in DIRECT_METHODS.items()
        for method in methods
    } | set(OTHER_API)
    seen = set()
    for index, item in enumerate(policy.get("api_matrix", [])):
        combination = (
            item.get("system"),
            item.get("version"),
            item.get("service"),
            item.get("method"),
        )
        if combination not in expected:
            errors.append(f"api_matrix[{index}]: unknown API combination")
            continue
        if combination in seen:
            errors.append(f"api_matrix[{index}]: duplicate API combination")
            continue
        seen.add(combination)
        if combination[0] == "DIRECT":
            metadata = (
                "api.direct.yandex.com",
                f"/json/v501/{combination[2].lower()}",
                "POST",
                "MANAGEMENT_READBACK"
                if combination[3] == "get"
                else "INTEGRATION_WRITE_ONLY",
                "DOCUMENTED_NOT_EXECUTED",
            )
        else:
            metadata = OTHER_API[combination]
        actual = (
            item.get("host"),
            item.get("path"),
            item.get("http_verb"),
            item.get("access_class"),
            item.get("verification_status"),
        )
        if item.get("environment") != "production" or actual != metadata:
            errors.append(f"api_matrix[{index}]: API metadata mismatch")
    for combination in sorted(expected - seen):
        errors.append(f"api_matrix: missing API combination {combination}")


def _validate_fixtures(policy: dict[str, Any], errors: list[str]) -> None:
    llm = policy.get("llm", {})
    fixtures = llm.get("reliability_fixtures", [])
    if not 0 < llm.get("retention_days", 0) <= 30:
        errors.append("llm.retention_days: invalid")
    if {item.get("name") for item in fixtures} != LLM_FIXTURES:
        errors.append("llm.reliability_fixtures: fixture set mismatch")
    for item in fixtures:
        status = item.get("expected_status")
        ambiguity = (
            "REQUEST_MISSING_DATA_OR_NEEDS_HUMAN"
            if status in {"INSUFFICIENT_DATA", "NEEDS_HUMAN"}
            else "NOT_APPLICABLE"
        )
        if item.get("ambiguity_outcome") != ambiguity:
            errors.append(f"llm fixture {item.get('name')}: ambiguity outcome mismatch")
        if status != LLM_FIXTURE_EXPECTATIONS.get(item.get("name")):
            errors.append(f"llm fixture {item.get('name')}: expected status mismatch")
        if (
            item.get("expected_schema") != "OptimizationProposalV1"
            or item.get("required_evidence") is not True
            or item.get("invocation_count") != 5
            or status
            not in {"EFFECTIVE", "INEFFECTIVE", "INSUFFICIENT_DATA", "NEEDS_HUMAN"}
        ):
            errors.append(f"llm fixture {item.get('name')}: contract mismatch")
    impact = policy.get("impact", {})
    if (
        impact.get("decision_field") != "next_decision"
        or set(impact.get("decision_values", []))
        != {
            "KEEP_CHANGE", "ROLLBACK_CHANGE", "ADJUST_CHANGE",
            "ESCALATE_TO_HUMAN",
        }
        or impact.get("fixture", {}).get("name") != "IMPACT_CPA_IMPROVED_KEEP"
        or impact.get("fixture", {}).get("expected_next_decision") != "KEEP_CHANGE"
    ):
        errors.append("impact: decision contract mismatch")


def validate_policy(
    policy: dict[str, Any],
    profile: str = "simulation",
    trusted_pilot_bindings: Optional[dict[str, Any]] = None,
    validation_time: Optional[dt.datetime] = None,
) -> list[str]:
    if profile not in {"simulation", "pilot"}:
        return [f"profile: unsupported profile {profile}"]
    effective_time = validation_time or dt.datetime.now(dt.timezone.utc)
    if effective_time.tzinfo is None:
        return ["validation_time: timezone is required"]
    errors: list[str] = []
    try:
        canonical = json.dumps(
            policy,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if hashlib.sha256(canonical).hexdigest() != APPROVED_POLICY_SHA256:
            errors.append("policy: approved record digest mismatch")
        _validate_structure(policy, errors)
        _validate_record_and_authority(policy, errors)
        _validate_bindings(
            policy,
            profile,
            trusted_pilot_bindings,
            effective_time,
            errors,
        )
        _validate_limits_and_controls(policy, errors)
        _validate_api(policy, errors)
        _validate_fixtures(policy, errors)
    except (AttributeError, KeyError, TypeError, ValueError):
        errors.append("policy: malformed value type")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "policy",
        nargs="?",
        type=Path,
        default=Path("config/gate0-policy.json"),
    )
    parser.add_argument(
        "--profile",
        choices=("simulation", "pilot"),
        default="simulation",
    )
    parser.add_argument(
        "--pilot-bindings",
        type=Path,
        help="External readback-attested trusted-binding manifest.",
    )
    args = parser.parse_args()
    try:
        policy = load_policy(args.policy)
        manifest = load_policy(args.pilot_bindings) if args.pilot_bindings else None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Gate 0 input load failed: {exc}", file=sys.stderr)
        return 2
    errors = validate_policy(
        policy,
        profile=args.profile,
        trusted_pilot_bindings=manifest,
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"Gate 0 policy is valid for {args.profile}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
