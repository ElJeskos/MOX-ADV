from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_modular_scope import validate_scope


ROOT = Path(__file__).resolve().parents[1]
SCOPE_PATH = ROOT / "requirements-modularization-v1.md"
SOURCE_AUTHORITY_PATH = ROOT / "okf" / "project" / "source-authority.md"
SIGNOFF_PATH = ROOT / "config" / "modularization-signoffs-v1.json"


class ModularScopeValidationTests(unittest.TestCase):
    def validate_text(self, text: str) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary:
            scope_path = Path(temporary) / "requirements-modularization-v1.md"
            scope_path.write_text(text, encoding="utf-8")
            return validate_scope(scope_path, SOURCE_AUTHORITY_PATH)

    def test_approved_modular_scope_is_consistent(self) -> None:
        self.assertEqual(
            [],
            validate_scope(
                SCOPE_PATH,
                SOURCE_AUTHORITY_PATH,
                SIGNOFF_PATH,
            ),
        )

    def test_production_write_capability_is_rejected(self) -> None:
        text = SCOPE_PATH.read_text(encoding="utf-8").replace(
            "Read, analyze, and recommend only",
            "Read, analyze, recommend, and execute",
            1,
        )

        errors = self.validate_text(text)

        self.assertTrue(
            any("production capability" in error for error in errors),
            errors,
        )

    def test_standalone_dashboard_is_rejected(self) -> None:
        text = SCOPE_PATH.read_text(encoding="utf-8").replace(
            "None (headless)",
            "MOX-ADV Dashboard",
            1,
        )

        errors = self.validate_text(text)

        self.assertTrue(
            any("standalone UI" in error for error in errors),
            errors,
        )

    def test_controlled_pilot_evidence_is_rejected(self) -> None:
        text = SCOPE_PATH.read_text(encoding="utf-8").replace(
            "REAL_READ_ONLY + TEST_CONTOUR",
            "REAL_READ_ONLY + CONTROLLED_PILOT",
            1,
        )

        errors = self.validate_text(text)

        self.assertTrue(
            any("CONTROLLED_PILOT" in error for error in errors),
            errors,
        )

    def test_paired_legacy_capability_cannot_be_assigned_to_standalone(self) -> None:
        text = SCOPE_PATH.read_text(encoding="utf-8").replace(
            "| `SOURCE_INTEGRATION` | `DIRECT_METRIKA_PAIRED` |",
            (
                "| `SOURCE_INTEGRATION` | `METRIKA_STANDALONE` + "
                "`DIRECT_STANDALONE` + `DIRECT_METRIKA_PAIRED` |"
            ),
            1,
        )

        errors = self.validate_text(text)

        self.assertTrue(
            any("edition mapping" in error for error in errors),
            errors,
        )

    def test_signoff_artifact_must_bind_the_scope_digest(self) -> None:
        signoffs = json.loads(SIGNOFF_PATH.read_text(encoding="utf-8"))
        signoffs["scope_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temporary:
            signoff_path = Path(temporary) / "signoffs.json"
            signoff_path.write_text(
                json.dumps(signoffs),
                encoding="utf-8",
            )

            errors = validate_scope(
                SCOPE_PATH,
                SOURCE_AUTHORITY_PATH,
                signoff_path,
            )

        self.assertTrue(
            any("scope digest mismatch" in error for error in errors),
            errors,
        )


if __name__ == "__main__":
    unittest.main()
