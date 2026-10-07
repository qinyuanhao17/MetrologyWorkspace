"""Persistent application-setting behavior tests."""

from pathlib import Path
import tempfile
import unittest

import yaml

from metrology_app.settings import (
    forget_recent_wkb,
    load_settings,
    recent_wkb_paths,
    remember_recent_wkb,
    save_settings,
)


class RecentWkbSettingsTests(unittest.TestCase):
    def test_invalid_stored_recovery_intervals_fall_back_to_a_safe_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.yaml"
            for value in ("null", "true", "'bad'", "0", "29", "1801", "1.5"):
                with self.subTest(value=value):
                    path.write_text(f"recovery_interval_seconds: {value}\n", encoding="utf-8")
                    self.assertEqual(load_settings(path)["recovery_interval_seconds"], 120)

    def test_recovery_interval_defaults_to_two_minutes_and_persists_without_losing_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.yaml"
            path.write_text("theme: light\nrecent_wkbs:\n- C:\\data\\kept.wkb\n", encoding="utf-8")
            self.assertEqual(load_settings(path)["recovery_interval_seconds"], 120)
            save_settings({"recovery_interval_seconds": 300}, path)
            stored = load_settings(path)
            self.assertEqual(stored["recovery_interval_seconds"], 300)
            self.assertEqual(stored["theme"], "light")
            self.assertEqual(stored["recent_wkbs"], ["C:\\data\\kept.wkb"])

    def test_recent_wkbs_persist_newest_first_without_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            settings_path = root / "settings.yaml"
            first = root / "first.wkb"
            second = root / "second.wkb"
            first.touch()
            second.touch()

            remember_recent_wkb(first, settings_path=settings_path)
            remember_recent_wkb(second, settings_path=settings_path)
            remember_recent_wkb(first, settings_path=settings_path)
            load_settings(settings_path)

            self.assertEqual(
                recent_wkb_paths(settings_path=settings_path),
                (first.resolve(), second.resolve()),
            )

            forget_recent_wkb(first, settings_path=settings_path)
            self.assertEqual(
                recent_wkb_paths(settings_path=settings_path),
                (second.resolve(),),
            )

    def test_saving_without_loading_keeps_the_stored_settings(self):
        """A script or test that saves first must not replace the user's file.

        ``save_settings`` writes the whole in-memory mapping, so a process that
        never loaded the file used to drop the saved theme and recent WKB list
        back to their defaults.
        """
        with tempfile.TemporaryDirectory() as folder:
            settings_path = Path(folder) / "settings.yaml"
            settings_path.write_text(
                "theme: light\nrecent_wkbs:\n- C:\\data\\kept.wkb\n", encoding="utf-8"
            )

            save_settings({"trend_overlay": {"A": "B"}}, settings_path)

            stored = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["theme"], "light")
            self.assertEqual(stored["recent_wkbs"], ["C:\\data\\kept.wkb"])
            self.assertEqual(stored["trend_overlay"], {"A": "B"})


if __name__ == "__main__":
    unittest.main()
