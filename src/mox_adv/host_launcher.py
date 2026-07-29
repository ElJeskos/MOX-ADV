"""Trusted host-side credential-profile resolution for the macOS launcher."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


class CredentialProfileRejected(ValueError):
    """The requested Keychain profile is not valid for a no-write run."""


def resolve_keychain_binding(
    policy: Mapping[str, Any],
    credential_profile: str,
) -> str:
    """Resolve one read-only profile to its exact Gate 0 Keychain binding."""

    try:
        profiles = policy["credentials"]["profiles"]
    except (KeyError, TypeError) as error:
        raise CredentialProfileRejected(
            "Gate 0 credential profiles are unavailable."
        ) from error
    matches = [
        item
        for item in profiles
        if isinstance(item, Mapping)
        and item.get("name") == credential_profile
        and item.get("access") == "direct_reports_read_only"
    ]
    if len(matches) != 1:
        raise CredentialProfileRejected(
            "Credential profile is not authorized for this no-write run."
        )
    binding = matches[0].get("keychain_binding")
    if not isinstance(binding, str) or not binding:
        raise CredentialProfileRejected("Credential profile has no Keychain binding.")
    return binding


def main() -> int:
    parser = argparse.ArgumentParser(prog="mox-adv-host-profile")
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--credential-profile", required=True)
    arguments = parser.parse_args()
    try:
        policy = json.loads(arguments.policy.read_text(encoding="utf-8"))
        if not isinstance(policy, Mapping):
            raise CredentialProfileRejected("Gate 0 policy must be an object.")
        binding = resolve_keychain_binding(policy, arguments.credential_profile)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        CredentialProfileRejected,
    ) as error:
        parser.exit(2, str(error) + "\n")
    print(binding)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
