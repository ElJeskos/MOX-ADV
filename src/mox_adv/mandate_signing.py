"""Issuer-backed signing for immutable canonical Mandates."""

from __future__ import annotations

import hashlib
import hmac
import subprocess
from typing import Protocol

from mox_adv.control_state import ControlRejected


class MandateSigner(Protocol):
    def sign(self, canonical: bytes) -> str: ...

    def verify(self, canonical: bytes, signature: str) -> bool: ...


class HMACMandateSigner:
    """HMAC implementation used by deterministic tests and injected runtimes."""

    def __init__(self, key: bytes) -> None:
        if not key:
            raise ValueError("Mandate signing key cannot be empty.")
        self._key = bytes(key)

    def sign(self, canonical: bytes) -> str:
        digest = hmac.new(self._key, canonical, hashlib.sha256).hexdigest()
        return "hmac-sha256:" + digest

    def verify(self, canonical: bytes, signature: str) -> bool:
        return hmac.compare_digest(self.sign(canonical), signature)


class MacOSKeychainMandateSigner:
    """Load the issuer signing key from macOS Keychain for one operation."""

    def __init__(
        self,
        *,
        service: str = "MOX_ADV_MANDATE_SIGNING_KEY",
        account: str = "sviridov",
    ) -> None:
        self.service = service
        self.account = account

    def _key(self) -> bytes:
        try:
            completed = subprocess.run(
                [
                    "/usr/bin/security",
                    "find-generic-password",
                    "-w",
                    "-s",
                    self.service,
                    "-a",
                    self.account,
                ],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ControlRejected(
                "MANDATE_SIGNING_UNAVAILABLE",
                "macOS Keychain signing material is unavailable.",
            ) from error
        key = completed.stdout.rstrip(b"\r\n")
        if completed.returncode != 0 or not key:
            raise ControlRejected(
                "MANDATE_SIGNING_UNAVAILABLE",
                "macOS Keychain signing material is unavailable.",
            )
        return key

    def sign(self, canonical: bytes) -> str:
        return HMACMandateSigner(self._key()).sign(canonical)

    def verify(self, canonical: bytes, signature: str) -> bool:
        return HMACMandateSigner(self._key()).verify(canonical, signature)
