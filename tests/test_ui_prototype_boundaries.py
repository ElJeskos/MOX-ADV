import unittest
from pathlib import Path

from mox_adv.ui_dashboard import DashboardApplication
from mox_adv.ui_server import _ASSETS

UI_ROOT = Path(__file__).parents[1] / "src" / "mox_adv" / "ui"


class IntegratedPrototypeBoundaryTests(unittest.TestCase):
    def test_unaccepted_p0_is_not_integrated_into_dashboard(self) -> None:
        dashboard_html = (UI_ROOT / "index.html").read_text(encoding="utf-8")

        self.assertNotIn("/strategy", _ASSETS)
        self.assertNotIn("/assets/p0-app.js", _ASSETS)
        self.assertNotIn("p0-app.js", dashboard_html)
        self.assertNotIn("Production Module · P0", dashboard_html)
        self.assertFalse(hasattr(DashboardApplication, "p0_overview"))
        self.assertFalse(hasattr(DashboardApplication, "apply_p0_action"))

    def test_final_prototype_keeps_every_module_in_test_scenario(self) -> None:
        prototype_html = (UI_ROOT / "prototype.html").read_text(encoding="utf-8")

        self.assertIn("Test Scenario", prototype_html)
        modules = (
            "strategy",
            "campaign",
            "cycle",
            "autopilot",
            "rules",
            "history",
            "seo",
            "control",
        )
        for module in modules:
            self.assertIn(f'data-page="{module}"', prototype_html)
        self.assertNotIn("Production Module · P0", prototype_html)
        self.assertNotIn("p0-app.js", prototype_html)


if __name__ == "__main__":
    unittest.main()
