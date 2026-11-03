"""Original-file export, recovery decisions and no-overwrite behavior."""
from pathlib import Path
import os
import shutil
import tempfile
import unittest

from metrology_app.spectra_export import export_spectra
from metrology_app.sme_spectra import load_folder
from tests.test_sme_spectra import SAMPLE_ROOT


class SpectrumExportTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt" and SAMPLE_ROOT.is_dir(), "Windows and supplied SME fixture")
    def test_exported_long_paths_can_be_loaded_back_without_changing_sme_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            sources = root / "source"
            deep = sources.joinpath(*[str(i) * 40 for i in range(3)])
            deep.mkdir(parents=True)
            original = next((SAMPLE_ROOT / "01_AIT_UVSE_20_Die").glob("*.sme"))
            measured = deep / "measured.sme"
            shutil.copyfile(original, measured)
            other = sources / "other.sme"
            shutil.copyfile(original, other)
            destination = root / ("destination" + "x" * 60)
            try:
                targets = export_spectra([measured, other], destination)
                self.assertGreater(len(str(targets[0])), 260)
                loaded = load_folder(destination)
                self.assertFalse(loaded.issues)
                self.assertEqual(len(loaded.spectra), 2)
            finally:
                assert destination.resolve().is_relative_to(root)
                shutil.rmtree(Path("\\\\?\\" + str(destination)), ignore_errors=True)

    @unittest.skipUnless(os.name == "nt", "Windows path-length regression")
    def test_batch_copy_keeps_working_when_retained_folders_make_target_over_260_chars(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            sources = root / "source"
            deep = sources.joinpath(*[str(i) * 40 for i in range(3)])
            deep.mkdir(parents=True)
            original = deep / ("spectrum" * 4 + ".sme")
            original.write_bytes(b"existing SME bytes")
            other = sources / "other.sme"
            other.write_bytes(b"another original")
            destination = root / ("destination" + "x" * 55)
            single = export_spectra([original], destination / "single")
            self.assertEqual(single[0].read_bytes(), original.read_bytes())
            try:
                batch = export_spectra([original, other], destination / "batch")
                self.assertGreater(len(str(batch[0])), 260)
                extended = Path("\\\\?\\" + str(batch[0]))
                self.assertEqual(extended.read_bytes(), original.read_bytes())
            finally:
                assert destination.resolve().is_relative_to(root)
                shutil.rmtree(Path("\\\\?\\" + str(destination)), ignore_errors=True)

    def test_missing_original_can_be_retried_or_skipped_without_losing_other_copies(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            sources = root / "source"
            sources.mkdir()
            available = sources / "available.sme"
            available.write_bytes(b"original file bytes")
            retry = sources / "retry.sme"
            skip = sources / "skip.sme"
            requests = []
            def decide(path, error):
                self.assertIsInstance(error, FileNotFoundError)
                requests.append(path)
                if path == retry:
                    retry.write_bytes(available.read_bytes())
                    return "retry"
                return "skip"
            targets = export_spectra([available, retry, skip], root / "output", on_error=decide)
            self.assertEqual(requests, [retry, skip])
            self.assertEqual([p.name for p in targets], ["available.sme", "retry.sme"])
            self.assertTrue(all(p.read_bytes() == available.read_bytes() for p in targets))
            self.assertFalse(list((root / "output").rglob("skip.sme")))


if __name__ == "__main__":
    unittest.main()
