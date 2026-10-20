"""Installer wrapping verifies the exact portable hash, version and clean payload."""
import hashlib
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile


SPEC = importlib.util.spec_from_file_location(
    "metrology_installer_builder", Path(__file__).resolve().parents[1] / "packaging/build_installer.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class InstallerPackagingTests(unittest.TestCase):
    def archive(self, folder, *, version="4.0.1", extra=None):
        archive = Path(folder) / "portable.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("MetrologyWorkspace/VERSION", version)
            zipped.writestr("MetrologyWorkspace/MetrologyWorkspace.exe", b"fixture")
            if extra:
                zipped.writestr(extra, "fixture")
        return archive, hashlib.sha256(archive.read_bytes()).hexdigest()

    def test_verified_new_version_is_forwarded_to_nsis_with_exact_uninstall_manifest(self):
        with TemporaryDirectory() as folder:
            archive, digest = self.archive(folder)
            output = Path(folder) / "Setup.exe"
            def compile_fixture(command, **kwargs):
                self.assertTrue(kwargs["check"])
                self.assertIn("/DAPP_VERSION=4.0.1", command)
                manifest = Path(next(value.split("=", 1)[1] for value in command if value.startswith("/DMANIFEST=")))
                text = manifest.read_text(encoding="utf-8-sig")
                self.assertIn('Delete "$INSTDIR\\VERSION"', text)
                self.assertNotIn("/r", text.lower())
                output.write_bytes(b"fixture installer")
            with patch.object(BUILDER.subprocess, "run", side_effect=compile_fixture):
                BUILDER.build(archive, "makensis.exe", output, version="4.0.1", portable_sha256=digest)
            self.assertTrue(output.is_file())

    def test_mismatched_hash_version_and_user_data_are_rejected_before_compilation(self):
        for condition in ("hash", "version", "settings", "workbook", "mwkb", "path"):
            with self.subTest(condition=condition), TemporaryDirectory() as folder:
                extra = {"settings": "MetrologyWorkspace/settings.yaml",
                         "workbook": "MetrologyWorkspace/personal.wkb",
                         "mwkb": "MetrologyWorkspace/personal.MWKB",
                         "path": "../escape.txt"}.get(condition)
                archive, digest = self.archive(folder, extra=extra)
                with patch.object(BUILDER.subprocess, "run") as compile_payload:
                    with self.assertRaises(ValueError):
                        BUILDER.build(archive, "makensis.exe", Path(folder) / "Setup.exe",
                                      version="4.0.0" if condition == "version" else "4.0.1",
                                      portable_sha256="0" * 64 if condition == "hash" else digest)
                    compile_payload.assert_not_called()
