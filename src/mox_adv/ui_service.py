"""Operator-facing orchestration for the local MOX-ADV web UI."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from mox_adv.approval_execution import (
    ApprovalExecutionService,
    ExecutionFacts,
    ExecutionRequest,
)
from mox_adv.autonomy_contracts import BoundedAutonomyRequest
from mox_adv.autonomy_execution import BoundedAutonomyService
from mox_adv.commands import (
    ACTION_SPECS,
    ActionFamily,
    OptimizationAction,
    calculate_relative_target,
)
from mox_adv.control_state import (
    AuthenticatedPrincipal,
    DurableControlState,
    PreparedChange,
    TrustedScope,
)
from mox_adv.fake_write_adapter import FakeWriteAdapter
from mox_adv.mandate_store import DurableMandateAuthority
from mox_adv.model_cost import DurableModelCostLedger
from mox_adv.model_provider import DeterministicFakeModelProvider
from mox_adv.observe import run_observe_fixture
from mox_adv.proposal_store import ImmutableProposalStore
from mox_adv.recommend_contracts import OptimizationProposalV1
from mox_adv.recommend_projection import build_sanitized_projection
from mox_adv.recommend_service import RecommendationService
from mox_adv.ui_automation import (
    AutomationConfigurationError,
    AutomationStore,
    evaluate_triggers,
    recommendation_policy,
    validate_recommendation_rules,
    validate_rules,
    validate_scenario,
)
from mox_adv.ui_evidence import write_dashboard_evidence_bundle
from mox_adv.yandex_read import YandexProductionReader

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "gate0-policy.json"
TEST_FIXTURE_PATH = ROOT / "fixtures" / "ui" / "linked-budget-pressure.json"
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class UiRunRejected(RuntimeError):
    """The requested UI run cannot pass the current safety boundary."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise UiRunRejected("INVALID_CONFIGURATION", f"{path.name} must be an object.")
    return value


def _split_total(total: int, parts: int) -> list[int]:
    quotient, remainder = divmod(total, parts)
    return [quotient + (1 if index < remainder else 0) for index in range(parts)]


def _scenario_fixture(
    scenario: Mapping[str, Any],
    destination: Path,
) -> Path:
    """Create one coherent linked fixture from operator-entered raw facts."""

    fixture = deepcopy(_read_json(TEST_FIXTURE_PATH))
    direct_rows = fixture["direct_report"]["rows"]
    metrika_rows = fixture["metrika_report"]["rows"]
    impressions = _split_total(scenario["impressions"], len(direct_rows))
    clicks = _split_total(scenario["clicks"], len(direct_rows))
    cost_micros = _split_total(
        scenario["spend_rub"] * 1_000_000,
        len(direct_rows),
    )
    visits = _split_total(scenario["visits"], len(metrika_rows))
    conversions = _split_total(
        scenario["conversions"],
        len(metrika_rows),
    )
    for index, row in enumerate(direct_rows):
        row["impressions"] = impressions[index]
        row["clicks"] = clicks[index]
        row["cost_micros"] = cost_micros[index]
    for index, row in enumerate(metrika_rows):
        row["visits"] = visits[index]
        row["goal_visits"] = conversions[index]
    fixture["direct_state"]["current_weekly_budget_micros"] = (
        scenario["weekly_budget_rub"] * 1_000_000
    )
    fixture["direct_state"]["campaign_state"] = scenario["campaign_state"]
    fixture["baseline"] = {
        "campaign": fixture["baseline"]["campaign"],
        "impressions": scenario["baseline_impressions"],
        "clicks": scenario["baseline_clicks"],
        "cost_micros": scenario["baseline_spend_rub"] * 1_000_000,
        "visits": scenario["baseline_visits"],
        "goal_visits": scenario["baseline_conversions"],
    }
    destination.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def production_readiness(
    policy: Mapping[str, Any],
    production_reader: Any | None = None,
) -> dict[str, Any]:
    """Return readiness for the local read-only main mode."""

    reader = production_reader or YandexProductionReader()
    reader_readiness = reader.readiness(policy)
    write_egress_disabled = (
        policy["environment"].get("simulation_write_egress") is False
        and policy["record"].get("production_write_authorized") is False
    )
    checks = [
        *reader_readiness["checks"],
        {
            "id": "write_egress",
            "label": "Внешние изменяющие запросы отключены политикой",
            "ready": write_egress_disabled,
        },
    ]
    blockers = [item["label"] for item in checks if not item["ready"]]
    return {
        "ready": not blockers,
        "checks": checks,
        "blockers": blockers,
        "access": "READ_ONLY",
        "data_source": "YANDEX_PRODUCTION_API",
        "external_reads_enabled": True,
        "write_requests_allowed": False,
        "write_flow": "DISABLED",
    }


def _minutes_between(later: str, earlier: str) -> int:
    later_value = datetime.fromisoformat(later).astimezone(timezone.utc)
    earlier_value = datetime.fromisoformat(earlier).astimezone(timezone.utc)
    return max(0, int((later_value - earlier_value).total_seconds() // 60))


def _projection_source(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    metrics = snapshot["metrics"]
    campaign = snapshot["campaign"]
    provenance = snapshot["provenance"]
    generated_at = str(snapshot["generated_at"])
    direct_watermark = str(provenance["direct_report"]["watermark"])
    metrika_watermark = str(provenance["metrika_report"]["watermark"])
    watermark_skew = abs(_minutes_between(direct_watermark, metrika_watermark))
    return {
        "schema_version": "llm-projection-v1",
        "period_start": snapshot["period_start"],
        "period_end": snapshot["period_end"],
        "timezone": snapshot["timezone"],
        "attribution": dict(snapshot["attribution"]),
        "campaign_state": campaign["state"],
        "campaign_strategy": campaign["strategy"],
        "current_budget": campaign["current_weekly_budget_micros"],
        "current_bid": campaign["current_search_bid_micros"],
        "current_ad_variant": campaign["current_ad_variant"],
        "impressions": metrics["impressions"],
        "clicks": metrics["clicks"],
        "cost_micros": metrics["cost_micros"],
        "visits": metrics["visits"],
        "goal_visits": metrics["goal_visits"],
        "ctr": metrics["ctr_percent"],
        "cpc": metrics["cpc_rub"],
        "conversion_rate": metrics["conversion_rate_percent"],
        "cpa": metrics["cpa_rub"],
        "budget_utilization": metrics["budget_utilization_percent"],
        "freshness": {
            "direct_minutes": _minutes_between(
                generated_at,
                str(provenance["direct_report"]["retrieved_at"]),
            ),
            "metrika_minutes": _minutes_between(
                generated_at,
                str(provenance["metrika_report"]["retrieved_at"]),
            ),
            "watermark_skew_minutes": watermark_skew,
        },
        "comparability": {
            "status": snapshot["comparability_status"],
            "confidence": snapshot["confidence_status"],
            "financial_recommendations_allowed": snapshot[
                "financial_recommendations_allowed"
            ],
        },
        "observed_facts": [],
        "business_goal": dict(snapshot["business_goal"]),
        "allowed_change_history": [],
        "policy_limits": {},
    }


def _campaign_goal_report(
    snapshot: Mapping[str, Any],
    recommendation_rules: Mapping[str, Any],
) -> dict[str, Any]:
    business_goal = snapshot["business_goal"]
    target_kpi = snapshot["target_kpi"]
    target = int(recommendation_rules["target_cpa_rub"])
    actual = str(snapshot["display_metrics"]["cpa_rub"])
    confidence = str(snapshot["confidence_status"])
    comparability = str(snapshot["comparability_status"])
    if actual == "NOT_APPLICABLE":
        status = "NOT_EVALUABLE"
    elif confidence == "INSUFFICIENT_DATA":
        status = "INSUFFICIENT_DATA"
    elif confidence == "STALE_DATA" or comparability != "COMPARABLE":
        status = "NEEDS_REVIEW"
    else:
        try:
            status = (
                "ACHIEVED"
                if Decimal(actual) <= Decimal(target)
                else "NOT_ACHIEVED"
            )
        except InvalidOperation:
            status = "NOT_EVALUABLE"
    return {
        "business_goal": {
            "event": str(business_goal["event"]),
            "meaning": str(business_goal["meaning"]),
        },
        "target_kpi": {
            "name": str(target_kpi["name"]),
            "target_maximum": target,
            "actual": actual,
        },
        "achievement_status": status,
        "used_in_decision": True,
    }


def _prepare_simulated_change(
    *,
    policy: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    proposal: Any,
    proposal_hash: str,
) -> tuple[PreparedChange, int]:
    operation = str(proposal.expected_diff["operation"])
    try:
        action = OptimizationAction(operation)
    except ValueError as error:
        raise UiRunRejected(
            "UNSUPPORTED_TEST_ACTION",
            "The test scenario produced an unsupported action.",
        ) from error
    action_spec = ACTION_SPECS[action]
    step = int(proposal.expected_diff.get("relative_step_percent", 0))
    if action_spec.family == ActionFamily.WEEKLY_BUDGET:
        current_value: Any = int(snapshot["campaign"]["current_weekly_budget_micros"])
        relative_percent = (
            step if int(action_spec.relative_percent or 0) > 0 else -step
        )
        target_value: Any = calculate_relative_target(
            current_value,
            relative_percent,
        )
    elif action_spec.family == ActionFamily.SEARCH_BID:
        current_value = int(snapshot["campaign"]["current_search_bid_micros"])
        relative_percent = (
            step if int(action_spec.relative_percent or 0) > 0 else -step
        )
        target_value = calculate_relative_target(
            current_value,
            relative_percent,
        )
    elif action_spec.family == ActionFamily.CAMPAIGN_STATE:
        current_value = str(snapshot["campaign"]["state"])
        target_value = str(proposal.expected_diff["target_state"])
    elif action_spec.family == ActionFamily.AD_VARIANT:
        current_value = str(snapshot["campaign"]["current_ad_variant"])
        target_value = str(proposal.expected_diff["variant_id"])
    else:
        raise UiRunRejected(
            "UNSUPPORTED_TEST_ACTION",
            "The test scenario produced an unsupported action family.",
        )
    scope_value = snapshot["scope"]
    scope = TrustedScope(
        organization=str(scope_value["organization"]),
        connection=str(scope_value["connection"]),
        account=str(scope_value["account"]),
        campaign=str(scope_value["campaign"]),
        writer=str(policy["bindings"]["simulation"]["single_writer"]),
    )
    provenance = snapshot["provenance"]
    prepared = PreparedChange(
        proposal_id=proposal.proposal_id,
        proposal_hash=proposal_hash,
        scope=scope,
        action=action,
        current_value=current_value,
        target_value=target_value,
        expected_diff=dict(proposal.expected_diff),
        snapshot_id=str(snapshot["snapshot_id"]),
        snapshot_generated_at=str(snapshot["generated_at"]),
        direct_watermark=str(provenance["direct_report"]["watermark"]),
        metrika_watermark=str(provenance["metrika_report"]["watermark"]),
        policy_version=str(policy["policy_id"]),
        expected_fingerprint=str(snapshot["snapshot_id"]),
        risk=str(proposal.risks[0]),
    )
    return prepared, step


def _execute_simulated_change(
    *,
    run_directory: Path,
    policy: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    proposal: Any,
    proposal_hash: str,
    now: datetime,
    control_state: DurableControlState | None = None,
    grant_approval: bool = True,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    operation = str(proposal.expected_diff["operation"])
    if operation == "NO_CHANGE":
        return (
            {
                "status": "NO_CHANGE",
                "reason_code": "NO_CHANGE_RECOMMENDED",
                "approval_id": None,
                "action": operation,
                "before_micros": None,
                "after_micros": None,
                "readback_micros": None,
                "relative_step_percent": 0,
                "write_calls": 0,
                "external_write_sent": False,
                "adapter": "NONE",
                "executor_invoked": False,
            },
            None,
        )
    prepared, step = _prepare_simulated_change(
        policy=policy,
        snapshot=snapshot,
        proposal=proposal,
        proposal_hash=proposal_hash,
    )
    action = prepared.action
    current_value = prepared.current_value
    target_value = prepared.target_value
    state = control_state or DurableControlState(run_directory / "control.sqlite3")
    state.register_prepared_change(prepared)
    if grant_approval:
        approval = state.grant_approval(
            proposal_id=prepared.proposal_id,
            expires_at=now + timedelta(minutes=15),
            reason="UI test mode approval for the exact simulated change.",
            principal=AuthenticatedPrincipal(
                identity="sviridov",
                authentication="authenticated_macos_user",
            ),
            now=now,
        )
    else:
        approval = state.load_bound_approval(
            prepared.proposal_id,
            prepared.binding_hash(),
        )
    adapter = FakeWriteAdapter(
        initial_state={prepared.target_key(): prepared.current_value}
    )
    metrics = snapshot["metrics"]
    freshness = _projection_source(snapshot)["freshness"]
    request = ExecutionRequest(
        proposal_id=prepared.proposal_id,
        execution_key=prepared.execution_key(),
        scope=prepared.scope,
        facts=ExecutionFacts(
            mode="APPROVAL_REQUIRED",
            automation_enabled=True,
            comparability_status=str(snapshot["comparability_status"]),
            confidence_status=str(snapshot["confidence_status"]),
            financial_recommendations_allowed=bool(
                snapshot["financial_recommendations_allowed"]
            ),
            direct_age_minutes=int(freshness["direct_minutes"]),
            metrika_age_minutes=int(freshness["metrika_minutes"]),
            watermark_skew_minutes=int(freshness["watermark_skew_minutes"]),
            clicks=int(metrics["clicks"]),
            conversions=int(metrics["goal_visits"]),
            impressions=int(metrics["impressions"]),
            spend_rub=int(metrics["cost_micros"]) // 1_000_000,
            cpa_rub=str(metrics["cpa_rub"]),
            budget_utilization_percent=str(metrics["budget_utilization_percent"]),
            ctr_percent=str(metrics["ctr_percent"]),
            campaign_state=str(snapshot["campaign"]["state"]),
            campaign_strategy=str(snapshot["campaign"]["strategy"]),
            current_fingerprint=prepared.expected_fingerprint,
            cooldown_active=False,
            actions_in_last_24h=0,
            cumulative_daily_change_percent=0,
            monetary_exposure_rub=(
                abs(target_value - current_value) // 1_000_000
                if isinstance(target_value, int) and isinstance(current_value, int)
                else 0
            ),
            kill_switch_available=True,
        ),
    )
    outcome = ApprovalExecutionService(
        policy,
        state,
        adapter,
        clock=lambda: now,
    ).execute(request)
    return (
        {
            "status": outcome.status.value,
            "reason_code": outcome.reason_code,
            "approval_id": approval.approval_id,
            "action": action.value,
            "before_micros": current_value,
            "after_micros": target_value,
            "readback_micros": outcome.observed_value,
            "relative_step_percent": step,
            "write_calls": adapter.write_calls,
            "external_write_sent": False,
            "adapter": "SEALED_FAKE",
            "executor_invoked": True,
        },
        asdict(state.load_approval(approval.approval_id)),
    )


def _execute_bounded_simulated_change(
    *,
    policy: Mapping[str, Any],
    state: DurableControlState,
    mandate_authority: DurableMandateAuthority,
    snapshot: Mapping[str, Any],
    proposal: Any,
    proposal_hash: str,
    mandate_id: str,
    now: datetime,
) -> dict[str, Any]:
    operation = str(proposal.expected_diff["operation"])
    if operation == "NO_CHANGE":
        return {
            "status": "NO_CHANGE",
            "reason_code": "NO_CHANGE_RECOMMENDED",
            "approval_id": None,
            "action": operation,
            "before_micros": None,
            "after_micros": None,
            "readback_micros": None,
            "relative_step_percent": 0,
            "write_calls": 0,
            "external_write_sent": False,
            "adapter": "NONE",
            "executor_invoked": False,
        }
    prepared, step = _prepare_simulated_change(
        policy=policy,
        snapshot=snapshot,
        proposal=proposal,
        proposal_hash=proposal_hash,
    )
    state.register_prepared_change(prepared)
    adapter = FakeWriteAdapter(
        initial_state={prepared.target_key(): prepared.current_value}
    )
    metrics = snapshot["metrics"]
    freshness = _projection_source(snapshot)["freshness"]
    request = BoundedAutonomyRequest(
        mandate_id=mandate_id,
        proposal_id=prepared.proposal_id,
        execution_key=prepared.execution_key(),
        scope=prepared.scope,
        mode="BOUNDED_AUTONOMY",
        automation_enabled=True,
        comparability_status=str(snapshot["comparability_status"]),
        confidence_status=str(snapshot["confidence_status"]),
        financial_recommendations_allowed=bool(
            snapshot["financial_recommendations_allowed"]
        ),
        direct_age_minutes=int(freshness["direct_minutes"]),
        metrika_age_minutes=int(freshness["metrika_minutes"]),
        watermark_skew_minutes=int(freshness["watermark_skew_minutes"]),
        clicks=int(metrics["clicks"]),
        conversions=int(metrics["goal_visits"]),
        spend_rub=int(metrics["cost_micros"]) // 1_000_000,
        cpa_rub=str(metrics["cpa_rub"]),
        budget_utilization_percent=str(metrics["budget_utilization_percent"]),
        campaign_state=str(snapshot["campaign"]["state"]),
        campaign_strategy=str(snapshot["campaign"]["strategy"]),
        current_fingerprint=prepared.expected_fingerprint,
    )
    outcome = BoundedAutonomyService(
        policy,
        state,
        mandate_authority,
        adapter,
        clock=lambda: now,
    ).execute(request)
    return {
        "status": outcome.status.value,
        "reason_code": outcome.reason_code,
        "approval_id": None,
        "mandate_id": mandate_id,
        "action": prepared.action.value,
        "before_micros": prepared.current_value,
        "after_micros": prepared.target_value,
        "readback_micros": outcome.observed_value,
        "relative_step_percent": step,
        "write_calls": adapter.write_calls,
        "external_write_sent": False,
        "adapter": "SEALED_FAKE",
        "executor_invoked": True,
    }


def _not_triggered_execution(
    snapshot: Mapping[str, Any],
    proposal: Any,
) -> dict[str, Any]:
    return {
        "status": "NOT_STARTED",
        "reason_code": "NO_TRIGGER_MATCH",
        "approval_id": None,
        "action": str(proposal.expected_diff["operation"]),
        "before_micros": int(snapshot["campaign"]["current_weekly_budget_micros"]),
        "after_micros": None,
        "readback_micros": None,
        "relative_step_percent": int(
            proposal.expected_diff.get("relative_step_percent", 0)
        ),
        "write_calls": 0,
        "external_write_sent": False,
        "adapter": "NONE",
        "executor_invoked": False,
    }


def _unsafe_signal_execution(
    snapshot: Mapping[str, Any],
    proposal: Any,
    reason_code: str,
) -> dict[str, Any]:
    return {
        "status": "BLOCKED",
        "reason_code": reason_code,
        "approval_id": None,
        "action": str(proposal.expected_diff["operation"]),
        "before_micros": int(snapshot["campaign"]["current_weekly_budget_micros"]),
        "after_micros": None,
        "readback_micros": None,
        "relative_step_percent": int(
            proposal.expected_diff.get("relative_step_percent", 0)
        ),
        "write_calls": 0,
        "external_write_sent": False,
        "adapter": "NONE",
        "executor_invoked": False,
    }


def _read_only_execution(
    snapshot: Mapping[str, Any],
    proposal: Any,
) -> dict[str, Any]:
    return {
        "status": "NOT_STARTED",
        "reason_code": "READ_ONLY_MODE",
        "approval_id": None,
        "action": str(proposal.expected_diff["operation"]),
        "before_micros": int(snapshot["campaign"]["current_weekly_budget_micros"]),
        "after_micros": None,
        "readback_micros": None,
        "relative_step_percent": int(
            proposal.expected_diff.get("relative_step_percent", 0)
        ),
        "write_calls": 0,
        "external_write_sent": False,
        "adapter": "NONE",
        "executor_invoked": False,
    }


def _observe_only_execution(
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "status": "NOT_STARTED",
        "reason_code": "OBSERVE_ONLY",
        "approval_id": None,
        "action": "NO_CHANGE",
        "before_micros": int(snapshot["campaign"]["current_weekly_budget_micros"]),
        "after_micros": None,
        "readback_micros": None,
        "relative_step_percent": 0,
        "write_calls": 0,
        "external_write_sent": False,
        "adapter": "NONE",
        "executor_invoked": False,
    }


def _pending_authority_execution(
    proposal: Any,
    prepared: PreparedChange,
    step: int,
    *,
    status: str,
    reason_code: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason_code": reason_code,
        "approval_id": None,
        "action": str(proposal.expected_diff["operation"]),
        "before_micros": prepared.current_value,
        "after_micros": prepared.target_value,
        "readback_micros": None,
        "relative_step_percent": step,
        "write_calls": 0,
        "external_write_sent": False,
        "adapter": "NONE",
        "executor_invoked": False,
    }


def _rubles(micros: Any) -> str:
    if micros is None:
        return "—"
    return f"{int(micros) / 1_000_000:,.0f}".replace(",", " ")


def _execution_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return _rubles(value) + " ₽"
    labels = {
        "ON": "Кампания включена",
        "SUSPENDED": "Кампания приостановлена",
        "A": "Вариант A",
        "B": "Вариант B",
    }
    return labels.get(str(value), str(value))


def _report_html(report: Mapping[str, Any]) -> str:
    metrics = report["metrics"]
    proposal = report["recommendation"]
    execution = report["execution"]
    run_id = escape(str(report["run_id"]))
    mode = escape(str(report["mode"]))
    period_start = escape(str(report["period"]["start"]))
    period_end = escape(str(report["period"]["end"]))
    explanation = escape(str(proposal["explanation_ru"]))
    action = escape(str(proposal["action"]))
    recommendation_status = escape(str(proposal["status"]))
    execution_status = escape(str(execution["status"]))
    comparability = escape(str(report["data_quality"]["comparability"]))
    confidence = escape(str(report["data_quality"]["confidence"]))
    campaign_goal = report["campaign_goal"]
    goal_meaning = escape(str(campaign_goal["business_goal"]["meaning"]))
    goal_target = escape(str(campaign_goal["target_kpi"]["target_maximum"]))
    goal_actual_value = str(campaign_goal["target_kpi"]["actual"])
    goal_actual = (
        "Недоступно"
        if goal_actual_value == "NOT_APPLICABLE"
        else escape(goal_actual_value) + " ₽"
    )
    goal_status = escape(
        {
            "ACHIEVED": "Достигнута",
            "NOT_ACHIEVED": "Не достигнута",
            "INSUFFICIENT_DATA": "Недостаточно данных",
            "NEEDS_REVIEW": "Нужна проверка",
            "NOT_EVALUABLE": "Нельзя оценить",
        }.get(
            str(campaign_goal["achievement_status"]),
            str(campaign_goal["achievement_status"]),
        )
    )
    quality_gaps = (
        ", ".join(escape(str(item)) for item in report["data_quality"].get("gaps", []))
        or "нет"
    )
    read_only = report["mode"] == "PRODUCTION_READ_ONLY"
    action_labels = {
        "INCREASE_WEEKLY_BUDGET": "Увеличить недельный бюджет",
        "DECREASE_WEEKLY_BUDGET": "Уменьшить недельный бюджет",
        "INCREASE_SEARCH_BID": "Увеличить поисковую ставку",
        "DECREASE_SEARCH_BID": "Уменьшить поисковую ставку",
        "SET_AD_VARIANT": "Сменить вариант объявления",
        "SUSPEND_CAMPAIGN": "Приостановить кампанию",
        "RESUME_CAMPAIGN": "Возобновить кампанию",
        "NO_CHANGE": "Сохранить текущие настройки",
    }
    action_title = escape(action_labels.get(proposal["action"], proposal["action"]))
    report_title = (
        "Отчёт<br>read-only анализа" if read_only else "Отчёт<br>тестового цикла"
    )
    step = int(proposal.get("relative_step_percent", 0))
    change_label = (
        f"{'-' if action.startswith('DECREASE') else '+'}{step}%"
        if step > 0
        else ("Без изменения" if step == 0 else f"{step}%")
    )
    decision = report.get(
        "decision",
        {
            "matched_triggers": [],
            "reason": "Основной режим формирует отдельный read-only результат.",
        },
    )
    trigger_items = "".join(
        "<li><strong>"
        + escape(str(item["label"]))
        + "</strong><span>"
        + escape(str(item["reason"]))
        + "</span></li>"
        for item in decision["matched_triggers"]
    )
    if not trigger_items:
        trigger_items = (
            "<li><strong>Без автоматического совпадения</strong>"
            "<span>Цикл запущен вручную или активные правила не сработали.</span>"
            "</li>"
        )
    if read_only:
        evidence_section = f"""
    <section class="evidence">
      <p class="label">Класс доказательств</p>
      <h2>Реальные read-only данные Яндекса</h2>
      <p class="copy">
        Три разрешённых запроса чтения получили данные Директа и Метрики.
        Другие внешние операции и любые write-запросы запрещены.
        Сопоставимость: {comparability}; доверие: {confidence};
        ограничения данных: {quality_gaps}.
      </p>
    </section>
"""
        decision_section = f"""
    <section>
      <p class="label">Контур рекомендации</p>
      <p class="copy">
        Рекомендация сформирована локальным deterministic provider.
        Правила тестового автопилота в основном режиме не оценивались.
        Статус рекомендации: {recommendation_status}.
      </p>
    </section>
"""
        execution_section = f"""
    <section>
      <p class="label">Граница исполнения</p>
      <div class="execution">
        <dl>
          <div><dt>Рекомендованное действие</dt><dd>{action}</dd></div>
          <div><dt>Статус исполнения</dt><dd>{execution_status}</dd></div>
          <div><dt>Результат</dt><dd>Не применено</dd></div>
        </dl>
        <dl>
          <div><dt>Executor</dt><dd>Отключён</dd></div>
          <div><dt>Credentials</dt><dd>Защищённый локальный .env</dd></div>
          <div><dt>External write</dt><dd class="safe">Запрещён</dd></div>
        </dl>
      </div>
    </section>
"""
    elif execution["status"] == "APPLIED":
        evidence_section = ""
        decision_section = f"""
    <section>
      <p class="label">Почему принято это решение</p>
      <p class="copy">{escape(str(decision["reason"]))}</p>
      <ul class="triggers">{trigger_items}</ul>
    </section>
"""
        execution_section = f"""
    <section>
      <p class="label">Применение и readback</p>
      <div class="execution">
        <dl>
          <div><dt>Действие</dt><dd>{action}</dd></div>
          <div><dt>Статус</dt><dd>{execution_status}</dd></div>
          <div><dt>До</dt><dd>{escape(_execution_value(execution["before_micros"]))}</dd></div>
          <div><dt>После</dt><dd>{escape(_execution_value(execution["after_micros"]))}</dd></div>
          <div><dt>Readback</dt><dd>{escape(_execution_value(execution["readback_micros"]))}</dd></div>
        </dl>
        <dl>
          <div><dt>Адаптер</dt><dd>SEALED_FAKE</dd></div>
          <div><dt>Credentials</dt><dd>Не загружались</dd></div>
          <div><dt>External write</dt><dd class="safe">Не выполнялся</dd></div>
        </dl>
      </div>
    </section>
"""
    else:
        evidence_section = ""
        decision_section = f"""
    <section>
      <p class="label">Почему принято это решение</p>
      <p class="copy">{escape(str(decision["reason"]))}</p>
      <ul class="triggers">{trigger_items}</ul>
    </section>
"""
        execution_section = f"""
    <section>
      <p class="label">Результат policy и исполнения</p>
      <div class="execution">
        <dl>
          <div><dt>Действие</dt><dd>{action}</dd></div>
          <div><dt>Статус</dt><dd>{execution_status}</dd></div>
          <div><dt>Причина</dt><dd>{escape(str(execution["reason_code"]))}</dd></div>
        </dl>
        <dl>
          <div><dt>Write-вызовов</dt><dd>{int(execution["write_calls"])}</dd></div>
          <div><dt>Credentials</dt><dd>Не загружались</dd></div>
          <div><dt>External write</dt><dd class="safe">Не выполнялся</dd></div>
        </dl>
      </div>
    </section>
"""
    safety_footer = (
        "Executor не вызывался, любые внешние write-запросы запрещены."
        if read_only
        else "Внешний write-запрос не отправлялся."
    )
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Отчёт MOX-ADV</title>
  <style>
    :root {{
      color: #171b18;
      background: #f1f0ea;
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 48px 28px; }}
    main {{ width: min(960px, 100%); margin: 0 auto; }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 32px;
      padding-bottom: 38px;
      border-bottom: 1px solid #171b18;
    }}
    .brand {{ margin: 0 0 12px; font-size: 12px; font-weight: 800; letter-spacing: .12em; }}
    h1 {{ margin: 0; font-size: clamp(38px, 7vw, 72px); line-height: .95; letter-spacing: -.055em; }}
    .meta {{ color: #69716c; font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; text-align: right; }}
    .meta p {{ margin: 0 0 8px; }}
    section {{ padding: 38px 0; border-bottom: 1px solid #cdd1cb; }}
    .label {{ margin: 0 0 18px; color: #69716c; font-size: 11px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }}
    .metrics {{ display: grid; grid-template-columns: repeat(5, 1fr); }}
    .goal-context {{ display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap: 24px; }}
    .goal-context div {{ min-width: 0; }}
    .goal-context span {{ display: block; margin-bottom: 8px; color: #69716c; font-size: 11px; }}
    .goal-context strong {{ font-size: 18px; line-height: 1.35; }}
    .metric {{ min-width: 0; padding-right: 20px; }}
    .metric + .metric {{ padding-left: 20px; border-left: 1px solid #cdd1cb; }}
    .metric span {{ display: block; margin-bottom: 14px; color: #69716c; font-size: 11px; }}
    .metric strong {{ font-size: 30px; letter-spacing: -.04em; }}
    .decision {{ display: grid; grid-template-columns: 1fr auto; gap: 44px; align-items: end; }}
    h2 {{ margin: 0 0 12px; font-size: 30px; letter-spacing: -.035em; }}
    .copy {{ max-width: 620px; margin: 0; color: #69716c; line-height: 1.6; }}
    .change {{ color: #176c4f; font-size: 48px; font-weight: 760; letter-spacing: -.04em; }}
    .triggers {{ margin: 22px 0 0; padding: 0; list-style: none; }}
    .triggers li {{ display: grid; grid-template-columns: minmax(180px, .4fr) 1fr; gap: 24px; padding: 14px 0; border-top: 1px solid #cdd1cb; }}
    .triggers span {{ color: #69716c; line-height: 1.5; }}
    .execution {{ display: grid; grid-template-columns: 1fr 1fr; gap: 32px; }}
    dl {{ margin: 0; }}
    dl div {{ display: flex; justify-content: space-between; gap: 24px; padding: 12px 0; border-top: 1px solid #cdd1cb; }}
    dt {{ color: #69716c; }}
    dd {{ margin: 0; font-weight: 700; }}
    .safe {{ color: #176c4f; }}
    .evidence {{
      margin-top: 28px;
      padding: 28px;
      border: 1px solid #d5aa5d;
      background: #fff8e9;
    }}
    .evidence + section {{ border-top: 0; }}
    footer {{ padding-top: 24px; color: #69716c; font-size: 11px; }}
    @media (max-width: 720px) {{
      body {{ padding: 28px 18px; }}
      header, .decision {{ grid-template-columns: 1fr; flex-direction: column; }}
      .meta {{ text-align: left; }}
      .metrics {{ grid-template-columns: 1fr 1fr; gap: 24px 0; }}
      .metric + .metric {{ border-left: 0; padding-left: 0; }}
      .execution {{ grid-template-columns: 1fr; }}
      .triggers li {{ grid-template-columns: 1fr; gap: 6px; }}
    }}
    @media print {{
      body {{ padding: 0; background: white; }}
      main {{ width: 100%; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <p class="brand">MOX-ADV · CONTROL</p>
        <h1>{report_title}</h1>
      </div>
      <div class="meta">
        <p>{run_id}</p>
        <p>Режим: {mode}</p>
        <p>{period_start} — {period_end}</p>
      </div>
    </header>

{evidence_section}

    <section>
      <p class="label">Цель рекламной кампании</p>
      <div class="goal-context">
        <div><span>Бизнес-цель</span><strong>{goal_meaning}</strong></div>
        <div><span>Целевой CPA</span><strong>≤ {goal_target} ₽</strong></div>
        <div><span>Фактический CPA</span><strong>{goal_actual}</strong></div>
        <div><span>Достижение</span><strong>{goal_status}</strong></div>
      </div>
    </section>

    <section>
      <p class="label">Связанные показатели Директа и Метрики</p>
      <div class="metrics">
        <div class="metric"><span>CTR</span><strong>{escape(str(metrics["ctr_percent"]))}%</strong></div>
        <div class="metric"><span>CPC</span><strong>{escape(str(metrics["cpc_rub"]))} ₽</strong></div>
        <div class="metric"><span>Конверсия</span><strong>{escape(str(metrics["conversion_rate_percent"]))}%</strong></div>
        <div class="metric"><span>CPA</span><strong>{escape(str(metrics["cpa_rub"]))} ₽</strong></div>
        <div class="metric"><span>Использование бюджета</span><strong>{escape(str(metrics["budget_utilization_percent"]))}%</strong></div>
      </div>
    </section>

    <section class="decision">
      <div>
        <p class="label">Рекомендация</p>
        <h2>{action_title}</h2>
        <p class="copy">{explanation}</p>
      </div>
      <div class="change">{escape(change_label)}</div>
    </section>

{decision_section}

{execution_section}

    <footer>
      {safety_footer}
      Отчёт сформирован локальным операторским интерфейсом MOX-ADV.
    </footer>
  </main>
</body>
</html>
"""


class UiRunService:
    """Execute one UI run and persist a compact operator report."""

    def __init__(
        self,
        runs_root: Path,
        *,
        production_reader: Any | None = None,
    ) -> None:
        self.runs_root = runs_root
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.policy = _read_json(POLICY_PATH)
        self.model_cost_ledger = DurableModelCostLedger.for_application(
            self.runs_root,
            self.policy,
        )
        self.production_reader = production_reader or YandexProductionReader()
        self.automation_store = AutomationStore(
            self.runs_root / "ui-test-automation.sqlite3",
            self.policy,
        )
        self.autonomy_control_state: DurableControlState | None = None
        self.autonomy_mandate_authority: DurableMandateAuthority | None = None
        self.operating_mode_provider: Callable[[], str] | None = None
        self.campaign_context_provider: (
            Callable[[], Mapping[str, Any]] | None
        ) = None
        self._test_run_lock = threading.Lock()

    def configure_bounded_autonomy(
        self,
        control_state: DurableControlState,
        mandate_authority: DurableMandateAuthority,
    ) -> None:
        """Bind the monitoring cycle to the Dashboard Mandate authority."""

        if Path(control_state.path).resolve() != Path(mandate_authority.path).resolve():
            raise UiRunRejected(
                "CONTROL_STATE_MISMATCH",
                "Bounded-autonomy authorities must share one durable store.",
            )
        self.autonomy_control_state = control_state
        self.autonomy_mandate_authority = mandate_authority

    def configure_operating_mode_provider(
        self,
        provider: Callable[[], str],
    ) -> None:
        """Use the durable Dashboard mode as scheduler source of truth."""

        self.operating_mode_provider = provider

    def configure_campaign_context_provider(
        self,
        provider: Callable[[], Mapping[str, Any]],
    ) -> None:
        """Bind runs to the current local campaign goal and target KPI."""

        self.campaign_context_provider = provider

    def _effective_policy(self) -> dict[str, Any]:
        policy = deepcopy(self.policy)
        if self.campaign_context_provider is None:
            return policy
        context = self.campaign_context_provider()
        if (
            not isinstance(context, Mapping)
            or set(context) != {"business_goal", "target_kpi"}
            or not isinstance(context["business_goal"], Mapping)
            or set(context["business_goal"]) != {"event", "meaning"}
            or not isinstance(context["target_kpi"], Mapping)
            or set(context["target_kpi"]) != {"name", "target_maximum"}
            or context["business_goal"]["event"]
            != policy["conversion"]["primary"]["event"]
            or context["target_kpi"]["name"] != "CPA_RUB"
        ):
            raise UiRunRejected(
                "CAMPAIGN_CONTEXT_INVALID",
                "Контекст рекламной кампании не прошёл проверку.",
            )
        target = context["target_kpi"]["target_maximum"]
        if (
            isinstance(target, bool)
            or not isinstance(target, int)
            or not 1 <= target <= int(policy["mandate"]["kpi"]["target_maximum"])
        ):
            raise UiRunRejected(
                "CAMPAIGN_CONTEXT_INVALID",
                "Целевой KPI рекламной кампании выходит за Gate 0.",
            )
        meaning = context["business_goal"]["meaning"]
        if not isinstance(meaning, str) or not 1 <= len(meaning) <= 500:
            raise UiRunRejected(
                "CAMPAIGN_CONTEXT_INVALID",
                "Бизнес-цель рекламной кампании некорректна.",
            )
        policy["conversion"]["primary"]["business_meaning"] = meaning
        policy["mandate"]["kpi"]["target_maximum"] = target
        return policy

    def status(self) -> dict[str, Any]:
        return {
            "service": "MOX-ADV",
            "test_mode": {
                "ready": True,
                "sources": ["YANDEX_DIRECT_FIXTURE", "YANDEX_METRIKA_FIXTURE"],
                "writes": "SEALED_FAKE",
            },
            "production_mode": production_readiness(
                self.policy,
                self.production_reader,
            ),
            "test_automation": self.automation(),
        }

    def production_campaign_catalog(self) -> dict[str, Any]:
        """Fetch the live Direct campaign catalog without write authority."""

        readiness = self.production_reader.campaign_catalog_readiness(self.policy)
        if not readiness["ready"]:
            raise UiRunRejected(
                "DIRECT_CAMPAIGN_CATALOG_NOT_READY",
                "; ".join(readiness["blockers"]),
            )
        try:
            return self.production_reader.list_campaigns(policy=self.policy)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise UiRunRejected(
                "DIRECT_CAMPAIGN_CATALOG_FAILED",
                str(error),
            ) from error

    def automation(self) -> dict[str, Any]:
        return self.automation_store.settings()

    def configure_automation(
        self,
        value: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            if value.get("mode") != "test":
                raise AutomationConfigurationError(
                    "TEST_AUTOMATION_ONLY",
                    "Автопилот в этом интерфейсе доступен только для тестового режима.",
                )
            return self.automation_store.configure(
                value,
                datetime.now(timezone.utc),
            )
        except AutomationConfigurationError as error:
            raise UiRunRejected(error.reason_code, str(error)) from error

    def decision_history(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.automation_store.history(limit)

    def decision_history_page(
        self,
        *,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        try:
            return self.automation_store.history_page(
                page=page,
                page_size=page_size,
            )
        except AutomationConfigurationError as error:
            raise UiRunRejected(error.reason_code, str(error)) from error

    def record_decision_outcome(
        self,
        *,
        source_run_id: str,
        outcome_run_id: str,
        created_at: str,
        payload: Mapping[str, Any],
    ) -> None:
        try:
            self.automation_store.record_decision_outcome(
                source_run_id=source_run_id,
                outcome_run_id=outcome_run_id,
                created_at=created_at,
                payload=payload,
            )
        except AutomationConfigurationError as error:
            raise UiRunRejected(error.reason_code, str(error)) from error

    def decision_outcome(self, source_run_id: str) -> dict[str, Any]:
        if _RUN_ID.fullmatch(source_run_id) is None:
            raise UiRunRejected(
                "INVALID_RUN_ID",
                "Decision run ID is invalid.",
            )
        outcome = self.automation_store.decision_outcome(source_run_id)
        if outcome is None:
            return {
                "source_run_id": source_run_id,
                "outcome_run_id": None,
                "created_at": None,
                "outcome": None,
            }
        return outcome

    def run_due_automation(self) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        settings = self.automation_store.claim_due(now)
        if settings is None:
            return None
        try:
            operating_mode = (
                self.operating_mode_provider()
                if self.operating_mode_provider is not None
                else str(settings["operating_mode"])
            )
            mandate_id = None
            if (
                operating_mode == "BOUNDED_AUTONOMY"
                and self.autonomy_mandate_authority is not None
            ):
                mandate_id = next(
                    (
                        record.mandate_id
                        for record in reversed(
                            self.autonomy_mandate_authority.list_records()
                        )
                        if record.status == "ACTIVE"
                    ),
                    None,
                )
            return self.run(
                "test",
                scenario=settings["scenario"],
                origin="SCHEDULED",
                rules=settings["rules"],
                recommendation_rules=settings["recommendation_rules"],
                operating_mode=operating_mode,
                mandate_id=mandate_id,
            )
        except Exception as error:
            self.automation_store.record_failure(
                occurred_at=now,
                reason_code=str(getattr(error, "reason_code", type(error).__name__)),
                message=str(error),
            )
            raise

    def run(
        self,
        mode: str,
        *,
        scenario: Mapping[str, Any] | None = None,
        origin: str = "MANUAL",
        rules: Mapping[str, Any] | None = None,
        recommendation_rules: Mapping[str, Any] | None = None,
        operating_mode: str | None = None,
        mandate_id: str | None = None,
        progress_callback: Callable[[dict[str, str]], None] | None = None,
    ) -> dict[str, Any]:
        if mode != "test":
            return self._run(
                mode,
                scenario=scenario,
                origin=origin,
                rules=rules,
                recommendation_rules=recommendation_rules,
                operating_mode=operating_mode,
                mandate_id=mandate_id,
                progress_callback=progress_callback,
            )
        if not self._test_run_lock.acquire(blocking=False):
            raise UiRunRejected(
                "TEST_RUN_IN_PROGRESS",
                "Другой тестовый цикл уже выполняется.",
            )
        try:
            return self._run(
                mode,
                scenario=scenario,
                origin=origin,
                rules=rules,
                recommendation_rules=recommendation_rules,
                operating_mode=operating_mode,
                mandate_id=mandate_id,
                progress_callback=progress_callback,
            )
        finally:
            self._test_run_lock.release()

    def _run(
        self,
        mode: str,
        *,
        scenario: Mapping[str, Any] | None,
        origin: str,
        rules: Mapping[str, Any] | None,
        recommendation_rules: Mapping[str, Any] | None,
        operating_mode: str | None,
        mandate_id: str | None,
        progress_callback: Callable[[dict[str, str]], None] | None,
    ) -> dict[str, Any]:
        if mode not in {"test", "production"}:
            raise UiRunRejected("INVALID_MODE", "Unknown UI run mode.")
        if origin not in {"MANUAL", "SCHEDULED"}:
            raise UiRunRejected("INVALID_ORIGIN", "Unknown UI run origin.")
        if operating_mode is not None and operating_mode not in {
            "OBSERVE",
            "RECOMMEND",
            "APPROVAL_REQUIRED",
            "BOUNDED_AUTONOMY",
        }:
            raise UiRunRejected(
                "INVALID_OPERATING_MODE",
                "Unknown operating mode.",
            )
        if operating_mode is not None:
            effective_operating_mode = operating_mode
        elif mode == "test" and origin == "MANUAL":
            effective_operating_mode = "APPROVAL_REQUIRED"
        else:
            effective_operating_mode = (
                "LEGACY_PRODUCTION" if mode == "production" else "LEGACY_TEST"
            )
        if effective_operating_mode == "BOUNDED_AUTONOMY" and not mandate_id:
            raise UiRunRejected(
                "MANDATE_REQUIRED",
                "Mandate is required for bounded autonomy.",
            )
        read_only = mode == "production"
        run_policy = self._effective_policy()
        if mode == "production":
            readiness = production_readiness(
                run_policy,
                self.production_reader,
            )
            if not readiness["ready"]:
                raise UiRunRejected(
                    "PRODUCTION_NOT_READY",
                    "Основной read-only режим заблокирован: "
                    + "; ".join(readiness["blockers"]),
                )
        try:
            scenario_value = validate_scenario(None if read_only else scenario)
            rules_value = validate_rules(
                run_policy,
                None if read_only else rules,
            )
            recommendation_rules_value = validate_recommendation_rules(
                run_policy,
                None if read_only else recommendation_rules,
            )
        except AutomationConfigurationError as error:
            raise UiRunRejected(error.reason_code, str(error)) from error
        now = datetime.now(timezone.utc)
        run_id = "ui-" + now.strftime("%Y%m%dT%H%M%S%fZ")
        if _RUN_ID.fullmatch(run_id) is None:
            raise UiRunRejected("INVALID_RUN_ID", "Generated run ID is invalid.")
        run_directory = self.runs_root / run_id
        run_directory.mkdir(parents=True, exist_ok=False)
        effective_policy_path = run_directory / "effective-policy.json"
        effective_policy_path.write_text(
            json.dumps(run_policy, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        fixture_path = TEST_FIXTURE_PATH
        scenario_source = "DEFAULT"
        if not read_only and scenario is not None:
            fixture_path = _scenario_fixture(
                scenario_value,
                run_directory / "scenario-fixture.json",
            )
            scenario_source = (
                "AUTOMATION_SETTINGS" if origin == "SCHEDULED" else "CUSTOM"
            )
        if read_only:
            try:
                if progress_callback is None:
                    collected = self.production_reader.collect_snapshot(
                        policy=run_policy,
                        observation_id=run_id,
                        generated_at=now,
                    )
                else:
                    collected = self.production_reader.collect_snapshot(
                        policy=run_policy,
                        observation_id=run_id,
                        generated_at=now,
                        progress_callback=progress_callback,
                    )
                snapshot = collected.as_dict()
            except (OSError, RuntimeError, ValueError) as error:
                raise UiRunRejected(
                    "ANALYTICS_FAILED",
                    "Read-only чтение данных Яндекса остановлено: " + str(error),
                ) from error
        else:
            components = run_directory / "components"
            observe_outcome = run_observe_fixture(
                run_id="observe",
                runs_root=components,
                fixture_path=fixture_path,
                policy_path=effective_policy_path,
            )
            if observe_outcome.status != "SUCCEEDED":
                raise UiRunRejected(
                    "ANALYTICS_FAILED",
                    "The linked Direct and Metrika analytics run failed.",
                )
            observe_result = _read_json(components / "observe" / "result.json")
            snapshot = observe_result["snapshot"]
        matched_triggers = (
            []
            if read_only
            else evaluate_triggers(snapshot, scenario_value, rules_value)
        )
        approval_record = None
        proposal = None
        provider = {
            "provider": "not-invoked",
            "model_id": "not-invoked",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_rub": "0",
            "duration_ms": 0,
        }
        if read_only and progress_callback is not None:
            progress_callback(
                {
                    "step": "recommend",
                    "status": (
                        "SKIPPED"
                        if effective_operating_mode == "OBSERVE"
                        else "RUNNING"
                    ),
                }
            )
        recommendation_report: dict[str, Any]
        if effective_operating_mode == "OBSERVE":
            recommendation_report = {
                "proposal_id": None,
                "status": "OBSERVED",
                "action": "NO_CHANGE",
                "relative_step_percent": 0,
                "explanation_ru": (
                    "Связанные показатели собраны без применения изменений."
                ),
                "expected_direction": "NO_CHANGE",
                "risks": [],
                "rollback_condition": "NOT_APPLICABLE",
            }
            execution = _observe_only_execution(snapshot)
        else:
            unsafe_trigger = next(
                (
                    item
                    for item in matched_triggers
                    if item["reason_code"]
                    in {
                        "SOURCE_MISMATCH",
                        "UNKNOWN_EXTERNAL_CHANGE",
                        "DIRECT_DATA_STALE",
                        "METRIKA_DATA_STALE",
                        "WATERMARK_SKEW_EXCEEDED",
                    }
                ),
                None,
            )
            projection_source = _projection_source(snapshot)
            if unsafe_trigger is not None:
                projection_source["comparability"]["status"] = "INCOMPATIBLE"
                projection_source["comparability"][
                    "financial_recommendations_allowed"
                ] = False
                projection_source["observed_facts"] = [
                    (
                        "SOURCE_MISMATCH"
                        if unsafe_trigger["reason_code"] == "SOURCE_MISMATCH"
                        else "ANALYTICS_CONTEXT_INCOMPLETE"
                    )
                ]
            projection = build_sanitized_projection(
                projection_source,
                recommendation_policy(
                    run_policy,
                    recommendation_rules_value,
                ),
            )
            recommendation = RecommendationService(
                DeterministicFakeModelProvider(),
                ImmutableProposalStore(run_directory / "proposals"),
                run_policy,
                self.model_cost_ledger,
            ).recommend(
                projection=projection,
                run_id=run_id,
                snapshot_id=str(snapshot["snapshot_id"]),
                expected_fingerprint=str(snapshot["snapshot_id"]),
                created_at=now.isoformat(),
                expires_at=(now + timedelta(minutes=30)).isoformat(),
            )
            if recommendation.status != "READY" or recommendation.proposal is None:
                raise UiRunRejected(
                    "RECOMMENDATION_FAILED",
                    "The recommendation did not pass the trusted schema boundary.",
                )
            proposal = recommendation.proposal
            provider = asdict(recommendation.provider)
            proposal_action = str(proposal.actions[0]["action"])
            primary_action = (
                str(proposal.expected_diff["operation"])
                if proposal_action == "KEEP"
                else proposal_action
            )
            recommendation_report = {
                "proposal_id": proposal.proposal_id,
                "status": proposal.status,
                "action": str(proposal.expected_diff["operation"]),
                "primary_action": primary_action,
                "relative_step_percent": int(
                    proposal.expected_diff.get("relative_step_percent", 0)
                ),
                "explanation_ru": proposal.explanation_ru,
                "expected_direction": proposal.expected_effect_direction,
                "risks": list(proposal.risks),
                "rollback_condition": proposal.rollback_condition,
            }
            if origin == "SCHEDULED" and not matched_triggers:
                execution = _not_triggered_execution(snapshot, proposal)
            elif (
                effective_operating_mode in {"APPROVAL_REQUIRED", "BOUNDED_AUTONOMY"}
                and unsafe_trigger is not None
            ):
                execution = _unsafe_signal_execution(
                    snapshot,
                    proposal,
                    str(unsafe_trigger["reason_code"]),
                )
            elif read_only or effective_operating_mode == "RECOMMEND":
                execution = _read_only_execution(snapshot, proposal)
            elif proposal.expected_diff["operation"] == "NO_CHANGE":
                execution, _ = _execute_simulated_change(
                    run_directory=run_directory,
                    policy=run_policy,
                    snapshot=snapshot,
                    proposal=proposal,
                    proposal_hash=recommendation.canonical_hash,
                    now=now,
                )
            elif effective_operating_mode == "APPROVAL_REQUIRED":
                prepared, step = _prepare_simulated_change(
                    policy=run_policy,
                    snapshot=snapshot,
                    proposal=proposal,
                    proposal_hash=recommendation.canonical_hash,
                )
                execution = _pending_authority_execution(
                    proposal,
                    prepared,
                    step,
                    status="PENDING_APPROVAL",
                    reason_code="EXACT_APPROVAL_REQUIRED",
                )
            elif effective_operating_mode == "BOUNDED_AUTONOMY":
                if (
                    self.autonomy_control_state is None
                    or self.autonomy_mandate_authority is None
                ):
                    raise UiRunRejected(
                        "AUTONOMY_CONTROL_PLANE_UNAVAILABLE",
                        "The Dashboard Mandate authority is unavailable.",
                    )
                execution = _execute_bounded_simulated_change(
                    policy=run_policy,
                    state=self.autonomy_control_state,
                    mandate_authority=self.autonomy_mandate_authority,
                    snapshot=snapshot,
                    proposal=proposal,
                    proposal_hash=recommendation.canonical_hash,
                    mandate_id=str(mandate_id),
                    now=now,
                )
            else:
                execution, approval_record = _execute_simulated_change(
                    run_directory=run_directory,
                    policy=run_policy,
                    snapshot=snapshot,
                    proposal=proposal,
                    proposal_hash=recommendation.canonical_hash,
                    now=now,
                )
        if read_only and progress_callback is not None:
            if effective_operating_mode != "OBSERVE":
                progress_callback({"step": "recommend", "status": "PASSED"})
            progress_callback({"step": "apply", "status": "SKIPPED"})
        report = {
            "schema_version": "ui-run-report-v1",
            "run_id": run_id,
            "mode": "PRODUCTION_READ_ONLY" if read_only else "TEST",
            "operating_mode": effective_operating_mode,
            "status": "SUCCEEDED",
            "created_at": now.isoformat(),
            "sources": {
                "direct": ("YANDEX_DIRECT_API" if read_only else "LOCAL_FIXTURE"),
                "metrika": ("YANDEX_METRIKA_API" if read_only else "LOCAL_FIXTURE"),
            },
            "period": {
                "start": snapshot["period_start"],
                "end": snapshot["period_end"],
            },
            "scope": dict(snapshot["scope"]),
            "metrics": dict(snapshot["display_metrics"]),
            "campaign_goal": _campaign_goal_report(
                snapshot,
                recommendation_rules_value,
            ),
            "data_quality": {
                "comparability": snapshot["comparability_status"],
                "confidence": snapshot["confidence_status"],
                "gaps": list(snapshot["data_quality_gaps"]),
            },
            "recommendation": recommendation_report,
            "execution": execution,
            "steps": [
                {"id": "direct", "label": "Директ", "status": "PASSED"},
                {"id": "metrika", "label": "Метрика", "status": "PASSED"},
                {"id": "analytics", "label": "Анализ", "status": "PASSED"},
                {
                    "id": "recommend",
                    "label": "Решение",
                    "status": (
                        "SKIPPED" if effective_operating_mode == "OBSERVE" else "PASSED"
                    ),
                },
                {
                    "id": "apply",
                    "label": "Применение",
                    "status": (
                        "SKIPPED"
                        if (
                            read_only
                            or effective_operating_mode in {"OBSERVE", "RECOMMEND"}
                            or not execution["executor_invoked"]
                        )
                        else (
                            "PASSED" if execution["status"] == "APPLIED" else "BLOCKED"
                        )
                    ),
                },
            ],
            "safety": {
                "external_write_sent": False,
                "credential_loaded": read_only,
                "read_requests": (
                    list(self.production_reader.last_records) if read_only else []
                ),
                "adapter": "NONE" if read_only else "SEALED_FAKE",
                "approval": (
                    "DISABLED"
                    if read_only
                    else (
                        "SIMULATED_EXACT_APPROVAL"
                        if approval_record is not None
                        else (
                            "PENDING"
                            if effective_operating_mode == "APPROVAL_REQUIRED"
                            else (
                                "ACTIVE_MANDATE"
                                if effective_operating_mode == "BOUNDED_AUTONOMY"
                                else "NOT_REQUIRED"
                            )
                        )
                    )
                ),
                "write_requests_allowed": False,
                "executor_invoked": execution["executor_invoked"],
            },
            "artifacts": {
                "json": f"/api/runs/{run_id}",
                "html": f"/api/runs/{run_id}/report",
            },
        }
        if not read_only:
            if proposal is None:
                decision_reason = recommendation_report["explanation_ru"]
            elif proposal.status == "INSUFFICIENT_DATA":
                decision_reason = (
                    "Недостаточно данных для финансового изменения. "
                    + proposal.explanation_ru
                )
            elif origin == "SCHEDULED" and not matched_triggers:
                decision_reason = (
                    "Ни один активный триггер не сработал. "
                    "Предложение сохранено без изменения кампании."
                )
            elif matched_triggers:
                decision_reason = (
                    proposal.explanation_ru
                    + " "
                    + " ".join(item["reason"] for item in matched_triggers)
                )
            else:
                decision_reason = (
                    "Цикл запущен оператором вручную. " + proposal.explanation_ru
                )
            report.update(
                {
                    "origin": origin,
                    "scenario": {
                        "source": scenario_source,
                        "values": dict(scenario_value),
                    },
                    "decision": {
                        "reason": decision_reason,
                        "matched_triggers": matched_triggers,
                        "rules": rules_value,
                        "recommendation_rules": recommendation_rules_value,
                    },
                }
            )
        (run_directory / "ui-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (run_directory / "ui-report.html").write_text(
            _report_html(report),
            encoding="utf-8",
        )
        if proposal is not None:
            (run_directory / "proposal.json").write_text(
                json.dumps(
                    proposal.as_dict(),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        if approval_record is not None:
            (run_directory / "approval.json").write_text(
                json.dumps(
                    approval_record,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        self._write_normative_evidence(
            run_directory=run_directory,
            report=report,
            snapshot=snapshot,
            provider=provider,
        )
        if not read_only:
            self.automation_store.record_report(report)
        return report

    def _write_normative_evidence(
        self,
        *,
        run_directory: Path,
        report: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        provider: Mapping[str, Any],
    ) -> None:
        execution = report["execution"]
        operating_mode = str(report["operating_mode"])
        normative_mode = (
            "APPROVAL_REQUIRED" if operating_mode == "LEGACY_TEST" else operating_mode
        )
        references: dict[str, str] = {}
        proposal_path = run_directory / "proposal.json"
        approval_path = run_directory / "approval.json"
        if proposal_path.is_file():
            references["proposal"] = "proposal.json"
        if approval_path.is_file():
            references["approval"] = "approval.json"
        if execution["status"] == "APPLIED" or approval_path.is_file():
            change_diff = {
                "proposal_id": report["recommendation"]["proposal_id"],
                "operation": report["recommendation"]["action"],
                "before": execution["before_micros"],
                "after": execution["after_micros"],
                "readback": execution["readback_micros"],
                "status": execution["status"],
            }
            (run_directory / "change_diff.json").write_text(
                json.dumps(
                    change_diff,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            references["change_diff"] = "change_diff.json"
        capability_evidence: dict[str, Any] = {
            "SOURCE_INTEGRATION": {
                "status": "NOT_PROVEN",
                "evidence_type": (
                    "REAL_READ_ONLY"
                    if report["mode"] == "PRODUCTION_READ_ONLY"
                    else "SIMULATED"
                ),
                "evidence_paths": ["result.json", "events.jsonl"],
                "limitations": [
                    "Dashboard evidence does not replace controlled-pilot evidence."
                ],
            },
            "INTEGRATED_ANALYTICS": {
                "status": "NOT_PROVEN",
                "evidence_type": (
                    "REAL_READ_ONLY"
                    if report["mode"] == "PRODUCTION_READ_ONLY"
                    else "SIMULATED"
                ),
                "evidence_paths": ["result.json", "events.jsonl"],
                "limitations": ["One Dashboard run is not final capability sign-off."],
            },
            "OPERATIONAL_MODES": {
                "status": "NOT_PROVEN",
                "evidence_type": "SIMULATED",
                "evidence_paths": ["result.json", "events.jsonl"],
                "limitations": ["Controlled-pilot authority is not configured."],
            },
        }
        if proposal_path.is_file():
            capability_evidence["LLM_ANALYSIS"] = {
                "status": "NOT_PROVEN",
                "evidence_type": "SIMULATED",
                "evidence_paths": ["proposal.json", "events.jsonl"],
                "limitations": ["The Dashboard used the deterministic local provider."],
            }
        if approval_path.is_file():
            capability_evidence["APPROVAL_REQUIRED"] = {
                "status": "NOT_PROVEN",
                "evidence_type": "SIMULATED",
                "evidence_paths": [
                    "approval.json",
                    *(["change_diff.json"] if "change_diff" in references else []),
                    "events.jsonl",
                ],
                "limitations": [
                    "The exact approval authorized only a sealed fake target."
                ],
            }
        if (
            operating_mode == "BOUNDED_AUTONOMY"
            and execution.get("mandate_id") is not None
        ):
            capability_evidence["BOUNDED_AUTONOMY"] = {
                "status": "NOT_PROVEN",
                "evidence_type": "SIMULATED",
                "evidence_paths": [
                    *(["change_diff.json"] if "change_diff" in references else []),
                    "events.jsonl",
                ],
                "limitations": [
                    "The active Mandate authorized only a sealed fake target."
                ],
            }
        evidence_type = (
            "REAL_READ_ONLY"
            if report["mode"] == "PRODUCTION_READ_ONLY"
            else "SIMULATED"
        )
        execution_status = str(execution["status"])
        if execution_status.startswith("PENDING_"):
            execution_status = "NOT_STARTED"
        record = {
            "run_id": report["run_id"],
            "policy_version": self.policy["policy_id"],
            "mode": normative_mode,
            "evidence_type": evidence_type,
            "status": report["status"],
            "execution_status": execution_status,
            "source": (
                "YANDEX_PRODUCTION_API"
                if report["mode"] == "PRODUCTION_READ_ONLY"
                else "LOCAL_FIXTURE"
            ),
            "snapshot_id": snapshot["snapshot_id"],
            "period_start": snapshot["period_start"],
            "period_end": snapshot["period_end"],
            "provenance": snapshot["provenance"],
            "original_metrics": snapshot["metrics"],
            "metrics": report["metrics"],
            "validation_results": [
                {
                    "code": snapshot["comparability_status"],
                    "status": "PASSED",
                }
            ],
            "blocking_code": execution["reason_code"],
            "policy_decision": {
                "status": execution["status"],
                "reason_code": execution["reason_code"],
            },
            "technical_command": {
                "action": execution["action"],
                "adapter": execution["adapter"],
            },
            "before": {"value": execution["before_micros"]},
            "after": {"value": execution["after_micros"]},
            "readback": {"value": execution["readback_micros"]},
            "final_object_state": execution["status"],
            "provider": provider["provider"],
            "model_id": provider["model_id"],
            "input_tokens": provider["input_tokens"],
            "output_tokens": provider["output_tokens"],
            "cost_rub": provider["cost_rub"],
            "cost_limit_rub": "2000.00",
            "duration_ms": provider["duration_ms"],
            "stage_durations_ms": {
                "analysis": provider["duration_ms"],
            },
            "capability_evidence": capability_evidence,
            "gates": {
                "GATE_0": {
                    "status": "READY",
                    "evidence_paths": ["result.json"],
                    "limitations": [],
                },
                "GATE_1": {
                    "status": "NOT_READY",
                    "evidence_paths": [],
                    "limitations": [
                        "Controlled-pilot bindings and sign-off are not configured."
                    ],
                },
            },
            "limitations": [
                "Production write remains disabled by Gate 0.",
            ],
            "artifact_references": references,
        }
        write_dashboard_evidence_bundle(run_directory, record)

    def _pending_approval_context(
        self,
        run_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], Mapping[str, Any], Any, str]:
        pending = self.load_report(run_id)
        if (
            pending.get("operating_mode") != "APPROVAL_REQUIRED"
            or pending["execution"]["status"] != "PENDING_APPROVAL"
            or pending["mode"] != "TEST"
        ):
            raise UiRunRejected(
                "APPROVAL_NOT_PENDING",
                "The selected Dashboard proposal is not awaiting Approval.",
            )
        source_directory = self.runs_root / run_id
        proposal_value = _read_json(source_directory / "proposal.json")
        observe_result = _read_json(
            source_directory / "components" / "observe" / "result.json"
        )
        snapshot = observe_result["snapshot"]
        proposal = SimpleNamespace(
            proposal_id=proposal_value["proposal_id"],
            expected_diff=proposal_value["expected_diff"],
            risks=proposal_value["risks"],
        )
        canonical = json.dumps(
            proposal_value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        proposal_hash = "sha256:" + hashlib.sha256(canonical).hexdigest()
        return pending, proposal_value, snapshot, proposal, proposal_hash

    def prepare_pending_approval(self, run_id: str) -> PreparedChange:
        """Register the exact pending proposal in the durable Dashboard state."""

        if self.autonomy_control_state is None:
            raise UiRunRejected(
                "CONTROL_STATE_UNAVAILABLE",
                "The Dashboard Approval authority is unavailable.",
            )
        _, _, snapshot, proposal, proposal_hash = self._pending_approval_context(run_id)
        prepared, _ = _prepare_simulated_change(
            policy=self.policy,
            snapshot=snapshot,
            proposal=proposal,
            proposal_hash=proposal_hash,
        )
        self.autonomy_control_state.register_prepared_change(prepared)
        return prepared

    def revise_pending_run(
        self,
        run_id: str,
        *,
        relative_step_percent: int,
    ) -> dict[str, Any]:
        """Create a new immutable pending proposal with an operator-edited step."""

        (
            pending,
            proposal_value,
            snapshot,
            _,
            _,
        ) = self._pending_approval_context(run_id)
        maximum_step = int(self.policy["limits"]["maximum_step_percent"])
        if (
            isinstance(relative_step_percent, bool)
            or not isinstance(relative_step_percent, int)
            or not 1 <= relative_step_percent <= maximum_step
        ):
            raise UiRunRejected(
                "PROPOSAL_REVISION_OUTSIDE_POLICY",
                f"Размер изменения должен быть от 1% до {maximum_step}%.",
            )
        expected_diff = proposal_value.get("expected_diff")
        if (
            not isinstance(expected_diff, Mapping)
            or "relative_step_percent" not in expected_diff
        ):
            raise UiRunRejected(
                "PROPOSAL_REVISION_UNSUPPORTED",
                "Для этого предложения размер изменения не редактируется.",
            )
        now = datetime.now(timezone.utc)
        revision_run_id = "ui-revision-" + now.strftime("%Y%m%dT%H%M%S%fZ")
        revised_value = deepcopy(proposal_value)
        revised_value.update(
            {
                "proposal_id": "proposal-" + revision_run_id,
                "run_id": revision_run_id,
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=30)).isoformat(),
                "explanation_ru": (
                    str(proposal_value["explanation_ru"])
                    + f" Оператор изменил размер корректировки до {relative_step_percent}%."
                ),
            }
        )
        revised_value["expected_diff"] = {
            **dict(expected_diff),
            "relative_step_percent": relative_step_percent,
        }
        recommendation_rules = pending["decision"]["recommendation_rules"]
        projection = build_sanitized_projection(
            _projection_source(snapshot),
            recommendation_policy(self.policy, recommendation_rules),
        )
        revised_proposal = OptimizationProposalV1.from_mapping(
            revised_value,
            projection,
        )
        revised_value = revised_proposal.as_dict()
        proposal_hash = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    revised_value,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
        )
        prepared, step = _prepare_simulated_change(
            policy=self.policy,
            snapshot=snapshot,
            proposal=revised_proposal,
            proposal_hash=proposal_hash,
        )
        execution = _pending_authority_execution(
            revised_proposal,
            prepared,
            step,
            status="PENDING_APPROVAL",
            reason_code="EXACT_APPROVAL_REQUIRED",
        )
        source_directory = self.runs_root / run_id
        run_directory = self.runs_root / revision_run_id
        run_directory.mkdir(parents=True, exist_ok=False)
        shutil.copytree(
            source_directory / "components",
            run_directory / "components",
        )
        report = deepcopy(pending)
        report.update(
            {
                "run_id": revision_run_id,
                "source_run_id": run_id,
                "created_at": now.isoformat(),
                "recommendation": {
                    **pending["recommendation"],
                    "proposal_id": revised_proposal.proposal_id,
                    "relative_step_percent": relative_step_percent,
                    "explanation_ru": revised_proposal.explanation_ru,
                },
                "execution": execution,
                "safety": {
                    **pending["safety"],
                    "approval": "PENDING",
                    "executor_invoked": False,
                },
                "artifacts": {
                    "json": f"/api/runs/{revision_run_id}",
                    "html": f"/api/runs/{revision_run_id}/report",
                },
            }
        )
        report["decision"] = {
            **pending["decision"],
            "reason": (
                f"Оператор изменил размер корректировки с "
                f"{pending['recommendation']['relative_step_percent']}% "
                f"до {relative_step_percent}%. "
                + str(pending["recommendation"]["explanation_ru"])
            ),
            "operator_revision": {
                "source_run_id": run_id,
                "relative_step_percent": relative_step_percent,
            },
        }
        (run_directory / "ui-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (run_directory / "ui-report.html").write_text(
            _report_html(report),
            encoding="utf-8",
        )
        (run_directory / "proposal.json").write_text(
            json.dumps(
                revised_value,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        source_result = _read_json(source_directory / "result.json")
        self._write_normative_evidence(
            run_directory=run_directory,
            report=report,
            snapshot=snapshot,
            provider={
                "provider": source_result["provider"],
                "model_id": source_result["model_id"],
                "input_tokens": source_result["input_tokens"],
                "output_tokens": source_result["output_tokens"],
                "cost_rub": source_result["cost_rub"],
                "duration_ms": source_result["duration_ms"],
            },
        )
        self.automation_store.record_report(report)
        return report

    def approve_pending_run(self, run_id: str) -> dict[str, Any]:
        """Consume an existing exact Approval and execute it in a new run."""

        if self.autonomy_control_state is None:
            raise UiRunRejected(
                "CONTROL_STATE_UNAVAILABLE",
                "The Dashboard Approval authority is unavailable.",
            )
        (
            pending,
            proposal_value,
            snapshot,
            proposal,
            proposal_hash,
        ) = self._pending_approval_context(run_id)
        prepared, _ = _prepare_simulated_change(
            policy=self.policy,
            snapshot=snapshot,
            proposal=proposal,
            proposal_hash=proposal_hash,
        )
        self.autonomy_control_state.register_prepared_change(prepared)
        source_directory = self.runs_root / run_id
        now = datetime.now(timezone.utc)
        execution_run_id = "ui-approval-" + now.strftime("%Y%m%dT%H%M%S%fZ")
        run_directory = self.runs_root / execution_run_id
        run_directory.mkdir(parents=True, exist_ok=False)
        execution, approval_record = _execute_simulated_change(
            run_directory=run_directory,
            policy=self.policy,
            snapshot=snapshot,
            proposal=proposal,
            proposal_hash=proposal_hash,
            now=now,
            control_state=self.autonomy_control_state,
            grant_approval=False,
        )
        report = deepcopy(pending)
        report.update(
            {
                "run_id": execution_run_id,
                "source_run_id": run_id,
                "created_at": now.isoformat(),
                "execution": execution,
                "steps": [
                    {
                        **step,
                        "status": (
                            "PASSED"
                            if step["id"] == "apply"
                            and execution["status"] in {"APPLIED", "NO_CHANGE"}
                            else step["status"]
                        ),
                    }
                    for step in pending["steps"]
                ],
                "safety": {
                    **pending["safety"],
                    "approval": "SIMULATED_EXACT_APPROVAL",
                    "adapter": execution["adapter"],
                    "executor_invoked": execution["executor_invoked"],
                },
                "artifacts": {
                    "json": f"/api/runs/{execution_run_id}",
                    "html": f"/api/runs/{execution_run_id}/report",
                },
            }
        )
        report["decision"] = {
            **pending.get("decision", {}),
            "reason": (
                "Предложение подтверждено пользователем. "
                + str(pending["recommendation"]["explanation_ru"])
            ),
        }
        (run_directory / "ui-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (run_directory / "ui-report.html").write_text(
            _report_html(report),
            encoding="utf-8",
        )
        (run_directory / "proposal.json").write_text(
            json.dumps(
                proposal_value,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        if approval_record is not None:
            (run_directory / "approval.json").write_text(
                json.dumps(
                    approval_record,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        source_result = _read_json(source_directory / "result.json")
        self._write_normative_evidence(
            run_directory=run_directory,
            report=report,
            snapshot=snapshot,
            provider={
                "provider": source_result["provider"],
                "model_id": source_result["model_id"],
                "input_tokens": source_result["input_tokens"],
                "output_tokens": source_result["output_tokens"],
                "cost_rub": source_result["cost_rub"],
                "duration_ms": source_result["duration_ms"],
            },
        )
        self.automation_store.record_report(report)
        return report

    def load_report(self, run_id: str) -> dict[str, Any]:
        if _RUN_ID.fullmatch(run_id) is None:
            raise UiRunRejected("INVALID_RUN_ID", "Run ID is invalid.")
        path = self.runs_root / run_id / "ui-report.json"
        if not path.is_file():
            raise UiRunRejected("RUN_NOT_FOUND", "UI run does not exist.")
        return _read_json(path)

    def html_report_path(self, run_id: str) -> Path:
        if _RUN_ID.fullmatch(run_id) is None:
            raise UiRunRejected("INVALID_RUN_ID", "Run ID is invalid.")
        path = self.runs_root / run_id / "ui-report.html"
        if not path.is_file():
            raise UiRunRejected("RUN_NOT_FOUND", "UI run report does not exist.")
        return path
