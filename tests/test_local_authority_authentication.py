from __future__ import annotations

import os
import platform
import pwd
import unittest
from unittest.mock import patch

from mox_adv.control_state import (
    AuthenticatedPrincipal,
    ControlRejected,
    LocalOSPrincipalAuthenticatorV1,
    authenticate_exact_local_principal_v1,
)


class _WrongAuthenticator:
    def authenticate(self) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            identity="wrong-local-user",
            authentication="authenticated_macos_user",
        )


class LocalAuthorityAuthenticationTests(unittest.TestCase):
    def test_environment_identity_variables_cannot_spoof_the_uid_account(
        self,
    ) -> None:
        identity = pwd.getpwuid(os.getuid()).pw_name
        authentication = {
            "Darwin": "authenticated_macos_user",
            "Linux": "authenticated_linux_user",
        }[platform.system()]
        with patch.dict(
            os.environ,
            {
                "LOGNAME": "spoofed-user",
                "USER": "spoofed-user",
                "LNAME": "spoofed-user",
                "USERNAME": "spoofed-user",
            },
        ):
            principal = LocalOSPrincipalAuthenticatorV1(
                identity
            ).authenticate()

        self.assertEqual(
            AuthenticatedPrincipal(
                identity=identity,
                authentication=authentication,
            ),
            principal,
        )

    def test_injected_wrong_principal_is_rejected(self) -> None:
        expected = AuthenticatedPrincipal(
            identity="expected-local-user",
            authentication="authenticated_macos_user",
        )

        with self.assertRaisesRegex(
            ControlRejected,
            "UNAUTHENTICATED_PRINCIPAL",
        ):
            authenticate_exact_local_principal_v1(
                expected,
                _WrongAuthenticator(),
            )


if __name__ == "__main__":
    unittest.main()
