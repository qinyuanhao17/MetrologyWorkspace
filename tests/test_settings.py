"""Persistent application-setting behavior tests."""

from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
from unittest.mock import patch

import yaml

from metrology_app.settings import (
    forget_recent_wkb,
    load_settings,
    recent_wkb_paths,
    remember_recent_wkb,
    save_settings,
    get_settings,
)


class RecentWkbSettingsTests(unittest.TestCase):
    def test_legacy_preferences_keep_overlay_and_color_defaults_on_partial_save(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.yaml"
            path.write_text("theme: light\ntrend_overlay: {CD: Depth}\n"
                            "trend_source_overlay: null\ncolor_range_low: 0.2\n"
                            "color_range_high: 0.8\npoint_value_decimals: bad\n"
                            "future_unknown_key: kept-out-of-active-settings\n", encoding="utf-8")
            loaded = load_settings(path)
            self.assertNotIn("future_unknown_key", loaded)
            self.assertEqual(loaded["point_value_decimals"], 2)
            save_settings({"font_size": 12}, path)
            restored = load_settings(path)
            self.assertEqual(restored["trend_overlay"], {"CD": "Depth"})
            self.assertIsNone(restored["trend_source_overlay"])
            self.assertEqual((restored["color_range_low"], restored["color_range_high"]), (.2, .8))
            self.assertEqual(restored["theme"], "light")

    def test_unreadable_settings_are_not_replaced_by_default_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.yaml"
            for content in (b"theme: [unfinished", b"- not a settings mapping", b"\xff\xfe\x00"):
                with self.subTest(content=content):
                    path.write_bytes(content)
                    self.assertEqual(load_settings(path)["theme"], "dark")
                    with self.assertRaisesRegex(OSError, "read|invalid"):
                        save_settings({"font_size": 12}, path)
                    self.assertEqual(path.read_bytes(), content)
            path.write_text("theme: light\n", encoding="utf-8")
            load_settings(path)
            self.assertEqual(save_settings({"font_size": 12}, path)["theme"], "light")

    def test_active_writer_lock_prevents_save_without_changing_preferences(self):
        from PyQt6.QtCore import QLockFile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.yaml"
            active = save_settings({"theme": "light"}, path)
            before = path.read_bytes()
            lock = QLockFile(str(path.resolve()) + ".lock")
            self.assertTrue(lock.tryLock(0))
            try:
                with self.assertRaisesRegex(OSError, "locked|busy"):
                    save_settings({"theme": "dark"}, path)
                self.assertEqual(get_settings(), active)
                self.assertEqual(path.read_bytes(), before)
            finally:
                lock.unlock()
            self.assertEqual(save_settings({"theme": "dark"}, path)["theme"], "dark")

    def test_interrupted_writer_keeps_old_yaml_and_dead_process_lock_is_recoverable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.yaml"
            save_settings({"theme": "light"}, path)
            before = path.read_bytes()
            result = subprocess.run([sys.executable, "-c",
                "import os,sys; from metrology_app.settings import save_settings; "
                "os.replace = lambda *args: os._exit(17); "
                "save_settings({'theme': 'dark'}, sys.argv[1])", str(path)])
            self.assertEqual(result.returncode, 17)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(save_settings({"font_size": 12}, path)["theme"], "light")
            self.assertEqual(load_settings(path)["font_size"], 12)
            self.assertFalse(Path(str(path) + ".lock").exists())

    def test_fsync_failure_never_publishes_or_activates_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.yaml"
            active = save_settings({"theme": "light"}, path)
            before = path.read_bytes()
            with patch("os.fsync", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    save_settings({"theme": "dark"}, path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(get_settings(), active)
            self.assertEqual({item.name for item in Path(folder).iterdir()}, {"settings.yaml"})

    def test_second_process_save_is_detected_and_can_be_reloaded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.yaml"
            save_settings({"theme": "light", "recent_wkbs": ["kept.wkb"]}, path)
            load_settings(path)
            subprocess.run([sys.executable, "-c",
                "import sys; from metrology_app.settings import save_settings; "
                "save_settings({'theme': 'dark'}, sys.argv[1])", str(path)], check=True)
            other = path.read_bytes()
            with self.assertRaisesRegex(OSError, "changed"):
                save_settings({"font_size": 12}, path)
            self.assertEqual(path.read_bytes(), other)
            self.assertEqual(get_settings()["theme"], "light")
            load_settings(path)
            save_settings({"font_size": 12}, path)
            self.assertEqual(load_settings(path)["theme"], "dark")
            self.assertEqual(load_settings(path)["recent_wkbs"], ["kept.wkb"])

    def test_failed_atomic_publish_keeps_file_and_active_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.yaml"
            path.write_text("theme: light\nrecent_wkbs: [kept.wkb]\n", encoding="utf-8")
            before = path.read_bytes()
            active = load_settings(path)
            with patch("os.replace", side_effect=OSError("disk unavailable")):
                with self.assertRaises(OSError):
                    save_settings({"theme": "dark"}, path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(get_settings(), active)
            self.assertEqual({item.name for item in Path(folder).iterdir()}, {"settings.yaml"})

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
