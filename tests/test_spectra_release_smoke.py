"""The release executable can verify Spectra without running OCR/AutoWeighting."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from tests.test_sme_spectra import SAMPLE_ROOT


@unittest.skipUnless(SAMPLE_ROOT.is_dir(), "Requires supplied SME fixture")
class SpectraReleaseSmokeTests(unittest.TestCase):
    def test_source_entrypoint_checks_die_map_and_exits_without_auto_weighting(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            report = root / "spectra-smoke.json"
            environment = dict(os.environ, QT_QPA_PLATFORM="offscreen",
                               METROLOGY_SETTINGS_PATH=str(root / "settings.yaml"))
            result = subprocess.run([sys.executable, "main.py", "--spectra-smoke-test",
                                     str(SAMPLE_ROOT / "01_AIT_UVSE_20_Die"), str(report)],
                                    env=environment, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            state = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(state["ok"])
            self.assertEqual(state["title"], "Spectrum Die Map")
            self.assertTrue(state["rectangle_selection"])
            self.assertTrue(state["double_click_check"])
            self.assertFalse(state["auto_weighting_loaded"])
