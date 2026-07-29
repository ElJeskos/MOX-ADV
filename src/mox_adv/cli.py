"""Command-line interface for the safe local bootstrap."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from mox_adv.contracts import RunOutcome
from mox_adv.observe import run_observe_fixture
from mox_adv.pipeline import run_fixture


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
    return parser


def _print_outcome(outcome: RunOutcome) -> int:
    location = (
        "" if outcome.run_directory is None else " (" + outcome.run_directory + ")"
    )
    detail = "" if outcome.error_code is None else " [" + outcome.error_code + "]"
    print("Run " + outcome.run_id + ": " + outcome.status + detail + location)
    return outcome.exit_code


def main(argv: Optional[Sequence[str]] = None) -> int:
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
    parser.error("Unsupported command.")
    return 2
