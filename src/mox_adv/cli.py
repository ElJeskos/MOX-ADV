"""Command-line interface for the safe local bootstrap."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from mox_adv.autonomy import (
    DurableMandateAuthority,
    MacOSKeychainMandateSigner,
)
from mox_adv.contracts import RunOutcome
from mox_adv.control_state import (
    ControlRejected,
    DurableControlState,
    MacOSLocalPrincipalAuthenticator,
)
from mox_adv.observe import run_observe_fixture
from mox_adv.pipeline import run_fixture
from mox_adv.runtime_resources import runtime_resource


class PrincipalAuthenticator(Protocol):
    def authenticate(self) -> Any: ...

    def elevated_reauthenticate(self) -> Any: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mox-adv")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser(
        "run-fixture",
        help="run the local no-write bootstrap fixture",
    )
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    run_parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("fixtures/safe-bootstrap.json"),
    )
    run_parser.add_argument(
        "--policy",
        type=Path,
        default=Path("config/gate0-policy.json"),
    )
    run_parser.add_argument(
        "--credential-stdin",
        action="store_true",
        help="read one ephemeral credential from standard input without persisting it",
    )
    run_parser.add_argument(
        "--credential-profile",
        help="bind credential stdin to one exact Gate 0 profile",
    )
    observe_parser = subparsers.add_parser(
        "observe-fixture",
        help="run linked read-only OBSERVE analytics from a local fixture",
    )
    observe_parser.add_argument("--run-id", required=True)
    observe_parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    observe_parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("fixtures/linked-observe.json"),
    )
    observe_parser.add_argument(
        "--policy",
        type=Path,
        default=Path("config/gate0-policy.json"),
    )
    approval_parser = subparsers.add_parser(
        "approval",
        help="manage immutable approval authority",
    )
    approval_operations = approval_parser.add_subparsers(
        dest="operation",
        required=True,
    )
    approval_grant = approval_operations.add_parser("grant")
    approval_grant.add_argument("--proposal-id", required=True)
    approval_grant.add_argument("--expires-in", required=True)
    approval_grant.add_argument("--reason", required=True)
    approval_revoke = approval_operations.add_parser("revoke")
    approval_revoke.add_argument("--approval-id", required=True)
    approval_revoke.add_argument("--reason", required=True)
    kill_switch_parser = subparsers.add_parser(
        "kill-switch",
        help="manage the durable fail-closed kill switch",
    )
    kill_switch_operations = kill_switch_parser.add_subparsers(
        dest="operation",
        required=True,
    )
    kill_switch_engage = kill_switch_operations.add_parser("engage")
    kill_switch_engage.add_argument("--scope", required=True)
    kill_switch_engage.add_argument("--reason", required=True)
    kill_switch_release = kill_switch_operations.add_parser("release")
    kill_switch_release.add_argument("--scope", required=True)
    kill_switch_release.add_argument("--reason", required=True)
    kill_switch_release.add_argument("--reauth", action="store_true", required=True)
    mandate_parser = subparsers.add_parser(
        "mandate",
        help="manage immutable signed bounded-autonomy authority",
    )
    mandate_operations = mandate_parser.add_subparsers(
        dest="operation",
        required=True,
    )
    mandate_issue = mandate_operations.add_parser("issue")
    mandate_issue.add_argument("--file", required=True, type=Path)
    mandate_activate = mandate_operations.add_parser("activate")
    mandate_activate.add_argument("--mandate-id", required=True)
    mandate_revoke = mandate_operations.add_parser("revoke")
    mandate_revoke.add_argument("--mandate-id", required=True)
    mandate_revoke.add_argument("--reason", required=True)
    e2e_parser = subparsers.add_parser(
        "readonly-e2e",
        help="run both prototype modules with sealed writes and local interception",
    )
    e2e_parser.add_argument("--run-id", required=True)
    e2e_parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    ui_parser = subparsers.add_parser(
        "ui",
        help="run the local operator UI for linked analytics and control",
    )
    ui_parser.add_argument("--port", type=int, default=8878)
    ui_parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    ui_parser.add_argument(
        "--paired-production-configuration",
        type=Path,
        help="customer-owned paired production read configuration",
    )
    ui_parser.add_argument(
        "--direct-production-configuration",
        type=Path,
        help="customer-owned Direct production read configuration",
    )
    ui_parser.add_argument(
        "--metrika-production-configuration",
        type=Path,
        help="customer-owned Metrika production read configuration",
    )
    ui_parser.add_argument(
        "--direct-production-environment-file",
        type=Path,
        help="customer-owned Direct read credential environment file",
    )
    ui_parser.add_argument(
        "--metrika-production-environment-file",
        type=Path,
        help="customer-owned Metrika read credential environment file",
    )
    ui_parser.add_argument(
        "--no-open",
        action="store_true",
        help="do not open the UI in the default browser",
    )
    return parser


def _print_outcome(outcome: RunOutcome) -> int:
    location = (
        "" if outcome.run_directory is None else " (" + outcome.run_directory + ")"
    )
    detail = "" if outcome.error_code is None else " [" + outcome.error_code + "]"
    print("Run " + outcome.run_id + ": " + outcome.status + detail + location)
    return int(outcome.exit_code)


def _default_control_state() -> DurableControlState:
    return DurableControlState(
        Path.home() / "Library" / "Application Support" / "MOX-ADV" / "control.sqlite3"
    )


def _approval_duration(value: str) -> timedelta:
    if value != "15m":
        raise ControlRejected(
            "INVALID_INPUT",
            "Gate 0 approval expiry must be exactly 15m.",
        )
    return timedelta(minutes=15)


def _load_gate0_policy() -> Mapping[str, Any]:
    policy_path = runtime_resource("config", "gate0-policy.json")
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ControlRejected(
            "CONTROL_STATE_UNAVAILABLE",
            "Gate 0 policy cannot be loaded.",
        ) from error
    if not isinstance(policy, Mapping):
        raise ControlRejected("INVALID_INPUT", "Gate 0 policy must be an object.")
    return policy


def _default_mandate_authority(
    state: DurableControlState,
) -> DurableMandateAuthority:
    return DurableMandateAuthority(
        state.path,
        _load_gate0_policy(),
        MacOSKeychainMandateSigner(),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    control_state: DurableControlState | None = None,
    mandate_authority: DurableMandateAuthority | None = None,
    authenticator: PrincipalAuthenticator | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "run-fixture":
        outcome = run_fixture(
            run_id=arguments.run_id,
            runs_root=arguments.runs_dir,
            fixture_path=arguments.fixture,
            policy_path=arguments.policy,
            credential_stream=(
                sys.stdin.buffer if arguments.credential_stdin else None
            ),
            credential_profile=arguments.credential_profile,
        )
        return _print_outcome(outcome)
    if arguments.command == "observe-fixture":
        outcome = run_observe_fixture(
            run_id=arguments.run_id,
            runs_root=arguments.runs_dir,
            fixture_path=arguments.fixture,
            policy_path=arguments.policy,
        )
        return _print_outcome(outcome)
    if arguments.command == "readonly-e2e":
        from mox_adv.e2e_runner import run_readonly_e2e

        run_directory = run_readonly_e2e(arguments.runs_dir, arguments.run_id)
        print(run_directory)
        return 0
    if arguments.command == "ui":
        from mox_adv.paired_production import PairedYandexProductionReaderV1
        from mox_adv.ui_server import serve_ui

        if not 1 <= arguments.port <= 65535:
            parser.error("UI port must be between 1 and 65535.")
        production_paths = (
            arguments.paired_production_configuration,
            arguments.direct_production_configuration,
            arguments.metrika_production_configuration,
            arguments.direct_production_environment_file,
            arguments.metrika_production_environment_file,
        )
        if any(path is not None for path in production_paths) and not all(
            path is not None for path in production_paths
        ):
            parser.error(
                "paired production reads require all five production paths"
            )
        production_reader = (
            None
            if not all(path is not None for path in production_paths)
            else PairedYandexProductionReaderV1(
                paired_configuration_path=arguments.paired_production_configuration,
                direct_configuration_path=arguments.direct_production_configuration,
                metrika_configuration_path=arguments.metrika_production_configuration,
                direct_environment_path=arguments.direct_production_environment_file,
                metrika_environment_path=(
                    arguments.metrika_production_environment_file
                ),
            )
        )
        serve_ui(
            port=arguments.port,
            runs_root=arguments.runs_dir,
            open_browser=not arguments.no_open,
            production_reader=production_reader,
        )
        return 0
    if arguments.command in {"approval", "kill-switch", "mandate"}:
        state = _default_control_state() if control_state is None else control_state
        identity = (
            MacOSLocalPrincipalAuthenticator()
            if authenticator is None
            else authenticator
        )
        try:
            if arguments.command == "approval" and arguments.operation == "grant":
                principal = identity.authenticate()
                now = clock()
                prepared = state.load_prepared_change(arguments.proposal_id)
                expires_at = now + _approval_duration(arguments.expires_in)
                print("Target: " + prepared.target_key())
                print(
                    "Values: "
                    + repr(prepared.current_value)
                    + " -> "
                    + repr(prepared.target_value)
                )
                print(
                    "Diff: "
                    + json.dumps(
                        dict(prepared.expected_diff),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                print("Risk: " + prepared.risk)
                print("Expiry: " + expires_at.astimezone(timezone.utc).isoformat())
                approval = state.grant_approval(
                    proposal_id=prepared.proposal_id,
                    expires_at=expires_at,
                    reason=arguments.reason,
                    principal=principal,
                    now=now,
                )
                print("Approval: " + approval.approval_id)
                return 0
            if arguments.command == "approval" and arguments.operation == "revoke":
                state.revoke_approval(
                    arguments.approval_id,
                    identity.authenticate(),
                    clock(),
                )
                print("Approval revoked: " + arguments.approval_id)
                return 0
            if arguments.command == "kill-switch" and arguments.operation == "engage":
                state.engage_kill_switch(
                    arguments.scope,
                    arguments.reason,
                    identity.authenticate(),
                    clock(),
                )
                print("Kill switch engaged: " + arguments.scope)
                return 0
            if arguments.command == "kill-switch" and arguments.operation == "release":
                state.release_kill_switch(
                    arguments.scope,
                    arguments.reason,
                    identity.elevated_reauthenticate(),
                    clock(),
                )
                print("Kill switch released: " + arguments.scope)
                return 0
            if arguments.command == "mandate":
                authority = (
                    _default_mandate_authority(state)
                    if mandate_authority is None
                    else mandate_authority
                )
                principal = identity.authenticate()
                now = clock()
                if arguments.operation == "issue":
                    try:
                        payload = json.loads(arguments.file.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as error:
                        raise ControlRejected(
                            "INVALID_INPUT",
                            "Mandate file must contain valid JSON.",
                        ) from error
                    if not isinstance(payload, Mapping):
                        raise ControlRejected(
                            "INVALID_INPUT",
                            "Mandate file must contain one object.",
                        )
                    mandate = authority.issue(payload, principal, now)
                    print("Mandate: " + mandate.mandate_id)
                    print("Canonical hash: " + mandate.canonical_hash)
                    print("Expiry: " + str(mandate.canonical["expiry"]))
                    return 0
                if arguments.operation == "activate":
                    mandate = authority.activate(
                        arguments.mandate_id,
                        principal,
                        now,
                    )
                    print("Mandate activated: " + mandate.mandate_id)
                    return 0
                if arguments.operation == "revoke":
                    mandate = authority.revoke(
                        arguments.mandate_id,
                        arguments.reason,
                        principal,
                        now,
                    )
                    print("Mandate revoked: " + mandate.mandate_id)
                    return 0
        except ControlRejected as error:
            print(str(error), file=sys.stderr)
            return 2
    parser.error("Unsupported command.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
