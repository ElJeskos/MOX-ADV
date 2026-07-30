from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mox_adv.cli import main
from mox_adv.paired_production import PairedYandexProductionReaderV1


class PairedReleaseCliTests(unittest.TestCase):
    def test_ui_wires_all_customer_owned_production_read_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {
                name: root / name
                for name in (
                    "paired.json",
                    "direct.json",
                    "metrika.json",
                    ".env.direct",
                    ".env.metrika",
                )
            }
            with patch("mox_adv.ui_server.serve_ui") as serve:
                result = main(
                    [
                        "ui",
                        "--no-open",
                        "--runs-dir",
                        str(root / "runs"),
                        "--paired-production-configuration",
                        str(paths["paired.json"]),
                        "--direct-production-configuration",
                        str(paths["direct.json"]),
                        "--metrika-production-configuration",
                        str(paths["metrika.json"]),
                        "--direct-production-environment-file",
                        str(paths[".env.direct"]),
                        "--metrika-production-environment-file",
                        str(paths[".env.metrika"]),
                    ]
                )

            self.assertEqual(0, result)
            reader = serve.call_args.kwargs["production_reader"]
            self.assertIsInstance(reader, PairedYandexProductionReaderV1)
            self.assertEqual(
                paths["paired.json"],
                reader.paired_configuration_path,
            )
            self.assertEqual(
                paths["direct.json"],
                reader._direct.configuration_path,
            )
            self.assertEqual(
                paths[".env.direct"],
                reader._direct.environment_path,
            )
            self.assertEqual(
                paths["metrika.json"],
                reader._metrika.configuration_path,
            )
            self.assertEqual(
                paths[".env.metrika"],
                reader._metrika.environment_path,
            )

    def test_ui_rejects_partial_production_path_selection(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            main(
                [
                    "ui",
                    "--paired-production-configuration",
                    "paired.json",
                ]
            )

        self.assertEqual(2, raised.exception.code)


if __name__ == "__main__":
    unittest.main()
