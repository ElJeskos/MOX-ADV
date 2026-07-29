"""Command-line interface for the safe local bootstrap."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional, Protocol, Sequence

from mox_adv.contracts import RunOutcome
from mox_adv.control_state import (
    ControlRejected,
    DurableControlState,
    MacOSLocalPrincipalAuthenticator,
)
from mox_adv.observe import run_observe_fixture
from mox_adv.pipeline import run_fixture


class PrincipalAuthenticator(Protocol):
    def authenticate(self): ...

    def elevated_reauthenticate(self): ...


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
    return parser


def _print_outcome(outcome: RunOutcome) -> int:
    location = (
        "" if outcome.run_directory is None else " (" + outcome.run_directory + ")"
    )
    detail = "" if outcome.error_code is None else " [" + outcome.error_code + "]"
    print("Run " + outcome.run_id + ": " + outcome.status + detail + location)
    return outcome.exit_code


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


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    control_state: Optional[DurableControlState] = None,
    authenticator: Optional[PrincipalAuthenticator] = None,
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
    if arguments.command in {"approval", "kill-switch"}:
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
        except ControlRejected as error:
            print(str(error), file=sys.stderr)
            return 2
    parser.error("Unsupported command.")
    return 2
