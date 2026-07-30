from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.validate_modular_scope import validate_scope


ROOT = Path(__file__).resolve().parents[1]
SCOPE_PATH = ROOT / "requirements-modularization-v1.md"
SOURCE_AUTHORITY_PATH = ROOT / "okf" / "project" / "source-authority.md"


class ModularScopeValidationTests(unittest.TestCase):
    def validate_text(self, text: str) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary:
            scope_path = Path(temporary) / "requirements-modularization-v1.md"
            scope_path.write_text(text, encoding="utf-8")
            return validate_scope(scope_path, SOURCE_AUTHORITY_PATH)

    def test_approved_modular_scope_is_consistent(self) -> None:
        self.assertEqual(
            [],
            validate_scope(SCOPE_PATH, SOURCE_AUTHORITY_PATH),
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


if __name__ == "__main__":
    unittest.main()
