"""Persistent application-setting behavior tests."""

from pathlib import Path
import tempfile
import unittest

from metrology_app.settings import (
    forget_recent_wkb,
    load_settings,
    recent_wkb_paths,
    remember_recent_wkb,
)


class RecentWkbSettingsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
