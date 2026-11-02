"""Behavior checks for SME source identity and catalog ordering."""

from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

from metrology_app.sme_spectra import (
    METADATA_COLUMNS,
    LoadResult,
    SpectrumChannel,
    SpectrumCatalog,
    SpectrumFile,
    SpectrumIdentity,
    base_metadata,
    load_folder,
    parse_spectrum_filename,
    scan_sme_files,
    spectrum_identity,
    parse_sme_file,
    write_metadata_csv,
)


SAMPLE_ROOT = Path(
    r"C:\Users\Yuanhao Qin\OneDrive\Desktop\all_uploaded_SME_spectra_42_files"
)


def copy_verified_samples(destination):
    """Isolate the original fixture from later user additions to its parent."""
    root = Path(destination)
    for name in ("01_AIT_UVSE_20_Die", "02_wafer01_IMSE_20_Die", "03_BBSE_multichannel", "04_DTS_reflectance"):
        shutil.copytree(SAMPLE_ROOT / name, root / name)
    return root


class SpectrumIdentityTests(unittest.TestCase):
    def test_encrypted_files_are_reported_with_recovery_instructions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "encrypted.sme"
            path.write_bytes(b"%TSD-Header-###%" + bytes(range(256)))
            result = load_folder(Path(directory))
        self.assertEqual(result.spectra, ())
        self.assertEqual(result.issues[0].status, "encrypted")
        self.assertIn("TSD", result.issues[0].message)
        self.assertIn("decrypted", result.issues[0].message)

    def test_repeated_add_does_not_duplicate_encrypted_file_issues(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("first", "second"):
                (root / name).mkdir()
                (root / name / "same.sme").write_bytes(b"%TSD-Header-###%" + bytes(64))
            result = load_folder(root)
        catalog = SpectrumCatalog()
        catalog.merge(result)
        catalog.merge(result)
        self.assertEqual(len(catalog.issues), 2)

    def test_embedded_filename_separates_tool_sn_from_pad_and_field_coordinates(self):
        parsed = parse_spectrum_filename(
            "AIT0200.00-01_AIT0200.15_A03-090_CELL-45_Die1_C-1_R5_"
            "X-46.4132_Y135.2253_Rz315.9661_L1_D1_S1_"
            "20260826090931417_d4115cd0376d459f967de269930e394d.sme"
        )

        self.assertEqual(parsed.wafer_id, "AIT0200.00-01")
        self.assertEqual(parsed.lot_id, "AIT0200.15")
        self.assertEqual(parsed.tool_sn, "A03-090")
        self.assertEqual(parsed.pad_name, "CELL-45")
        self.assertEqual(parsed.die_seq, 1)
        self.assertEqual(parsed.field_x, -1)
        self.assertEqual(parsed.field_y, 5)
        self.assertEqual(parsed.time, "2026-08-26 09:09:31.417")
        self.assertEqual(parsed.parse_status, "ok")

    def test_legacy_date_token_is_used_as_pad_when_no_named_pad_exists(self):
        parsed = parse_spectrum_filename(
            "AIT0080.00-22_AIT0080.42_A03-090_2026-8-21-10-53-55_"
            "Die1_C-3_R4_20261001205124524.sme"
        )

        self.assertEqual(parsed.tool_sn, "A03-090")
        self.assertEqual(parsed.pad_name, "2026-8-21-10-53-55")
        self.assertEqual(parsed.field_x, -3)
        self.assertEqual(parsed.field_y, 4)

    def test_named_pad_precedes_date_and_angle_labels_keep_full_precision_identity(self):
        parsed = parse_spectrum_filename(
            "W1_L1_A03-090_CELL-45_2026-8-21-10-53-55_Die1_C0_R0_20261001205124524.sme"
        )
        self.assertEqual(parsed.pad_name, "CELL-45")
        channel = SpectrumChannel(
            {"channel_id": 1, "instrument": "UVSE_II+",
             "angle_1_deg": 65.0002, "angle_3_deg": 44.9999},
            np.array([200.0]), np.zeros((1, 24)), "mueller",
        )
        self.assertEqual(channel.key.legend_label, "UVSE_II+ · CH1 · AOI 65° · AZI 45°")
        self.assertEqual(channel.key.aoi_deg, 65.0002)
        self.assertEqual(channel.key.azi_deg, 44.9999)

    def test_unrecognized_name_is_preserved_without_guessing_identity(self):
        parsed = parse_spectrum_filename("customer_export.sme")

        self.assertEqual(parsed.raw_filename, "customer_export.sme")
        self.assertEqual(parsed.wafer_id, "")
        self.assertEqual(parsed.lot_id, "")
        self.assertEqual(parsed.tool_sn, "")
        self.assertEqual(parsed.pad_name, "")
        self.assertEqual(parsed.parse_status, "unrecognized")

    def test_ait_name_separates_wafer_lot_pad_and_ignores_tool_timestamp(self):
        identity = spectrum_identity({
            "instrument": "UVSE_II+",
            "embedded_filename":
                "AIT0080.00-22_AIT0080.42_A03-090_2026-8-21-10-53-55_"
                "Die1_C1_R0_20261001205124524.sme",
            "die": 1,
            "filename_timestamp_raw": "20261001205124524",
        })

        self.assertEqual(identity.wafer, "AIT0080.00-22")
        self.assertEqual(identity.lot, "AIT0080.42")
        self.assertEqual(identity.tool_sn, "A03-090")
        self.assertEqual(identity.pad, "2026-8-21-10-53-55")
        self.assertEqual(identity.die_seq, 1)

    def test_metadata_dataframe_and_csv_keep_one_row_per_channel(self):
        metadata = {
            "channel_id": 2,
            "channel_count": 2,
            "instrument": "UVSE_II+",
            "mode": "UVSE",
            "version": "SE3.5",
            "sample_id": "sample",
            "parse_status": "ok",
        }
        numeric = np.zeros((2, 24), dtype=float)
        numeric[:, 0] = [200.0, 300.0]
        channel = SpectrumChannel(metadata, numeric[:, 0], numeric, "mueller")
        identity = SpectrumIdentity(
            wafer="AIT0200.00-01",
            lot="AIT0200.15",
            pad="CELL-45",
            die_seq=1,
            timestamp="2026-08-26 09:09:31.417",
            tool_sn="A03-090",
            field_x=-1,
            field_y=5,
            parse_status="ok",
        )
        path = Path("C:/fixtures") / (
            "AIT0200.00-01_AIT0200.15_A03-090_CELL-45_Die1_C-1_R5.sme"
        )
        spectrum = SpectrumFile(
            path=path,
            key=str(path).casefold(),
            size_bytes=100,
            mtime_ns=1,
            identity=identity,
            embedded_filename=path.name,
            channels=(channel,),
            x_mm=-46.4132,
            y_mm=135.2253,
            coordinate_source="filename",
        )
        catalog = SpectrumCatalog()
        catalog.replace(LoadResult((spectrum,), ()))

        frame = catalog.metadata_dataframe()

        self.assertEqual(tuple(frame.columns), METADATA_COLUMNS)
        self.assertEqual(len(frame), 1)
        row = frame.iloc[0]
        self.assertEqual(row["Wafer ID"], "AIT0200.00-01")
        self.assertEqual(row["SME Name"], path.name)
        self.assertEqual(row["Lot ID"], "AIT0200.15")
        self.assertEqual(row["Tool SN"], "A03-090")
        self.assertEqual(row["PAD Name"], "CELL-45")
        self.assertEqual(row["Die Seq"], 1)
        self.assertEqual(row["FIELD X"], -1)
        self.assertEqual(row["FIELD Y"], 5)
        self.assertEqual(row["Time"], "2026-08-26 09:09:31.417")
        self.assertEqual(row["Folder"], str(path.parent))
        self.assertEqual(row["Instrument"], "UVSE_II+")
        self.assertEqual(row["Mode"], "UVSE")
        self.assertEqual(row["Version"], "SE3.5")
        self.assertEqual(row["Sample ID"], "sample")
        self.assertEqual(row["Channel Count"], 2)
        self.assertEqual(row["Channel ID"], 2)

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "metadata.csv"
            write_metadata_csv(frame, target)
            self.assertTrue(target.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_scan_is_cancellable_and_ignores_non_sme_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "nested").mkdir()
            (root / "nested" / "readable.sme").write_bytes(b"SE3not-base64")
            (root / "nested" / "ignored.had").write_bytes(b"not a spectrum")
            paths = scan_sme_files(root, cancelled=lambda: False)
            self.assertEqual([path.name for path in paths], ["readable.sme"])
            cancelled = load_folder(root, cancelled=lambda: True)
            self.assertTrue(cancelled.cancelled)

    def test_bad_sme_is_reported_without_stopping_the_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "broken.sme").write_bytes(b"not an SME")
            result = load_folder(root)
            self.assertEqual(result.spectra, ())
            self.assertEqual(len(result.issues), 1)
            self.assertIn("SE3", result.issues[0].message)


@unittest.skipUnless(SAMPLE_ROOT.is_dir(), "supplied SME regression folder is unavailable")
class SuppliedSpectrumBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="verified-sme-")
        cls.addClassCleanup(cls.scratch.cleanup)
        cls.result = load_folder(copy_verified_samples(cls.scratch.name))
        cls.catalog = SpectrumCatalog()
        cls.catalog.replace(cls.result)

    def test_supplied_batch_preserves_all_verified_channels(self):
        self.assertEqual(len(self.result.spectra), 42)
        self.assertEqual(len(self.result.issues), 0)
        self.assertEqual(sum(len(s.channels) for s in self.result.spectra), 47)
        self.assertEqual(self.catalog.channel_count, 9)

        type_counts = {}
        for spectrum in self.result.spectra:
            for channel in spectrum.channels:
                type_counts[channel.spectrum_type] = (
                    type_counts.get(channel.spectrum_type, 0) + 1
                )
        self.assertEqual(
            type_counts,
            {"mueller": 26, "ellipsometry": 20, "reflectance": 1},
        )
        self.assertEqual(
            sum(
                len(channel.numeric)
                for spectrum in self.result.spectra
                for channel in spectrum.channels
                if channel.spectrum_type == "mueller"
            ),
            18_660,
        )
        self.assertEqual(
            sum(
                len(channel.numeric)
                for spectrum in self.result.spectra
                for channel in spectrum.channels
                if channel.spectrum_type == "reflectance"
            ),
            2_947,
        )
        self.assertEqual(
            sum(
                len(channel.numeric)
                for spectrum in self.result.spectra
                for channel in spectrum.channels
                if channel.spectrum_type == "ellipsometry"
            ),
            20_200,
        )

    def test_batch_groups_by_declared_wafer_and_orders_die_numerically(self):
        groups = self.catalog.grouped()
        self.assertEqual(
            set(groups),
            {"AIT0080.00-22", "wafer01", "Simulation", "LP300005.14"},
        )
        ait_pad = groups["AIT0080.00-22"]["AIT0080.42"]["2026-8-21-10-53-55"]
        self.assertEqual(
            [spectrum.identity.die_seq for spectrum in ait_pad],
            list(range(1, 21)),
        )
        self.assertTrue(all(item.identity.pad == "2026-8-21-10-53-55" for item in ait_pad))
        self.assertTrue(all(item.identity.tool_sn == "A03-090" for item in ait_pad))
        bbse = groups["Simulation"]["Unknown lot"]["test_sme"]
        self.assertEqual(len(bbse), 1)
        self.assertFalse(bbse[0].has_map_point)

    def test_dts_uses_filename_coordinates_when_header_is_placeholder(self):
        dts = next(
            spectrum
            for spectrum in self.result.spectra
            if spectrum.identity.wafer == "LP300005.14"
        )
        self.assertEqual(dts.coordinate_source, "filename")
        self.assertAlmostEqual(dts.x_mm, -5.7837)
        self.assertAlmostEqual(dts.y_mm, 123.1641)
        self.assertTrue(dts.has_map_point)

    def test_catalog_can_regroup_by_lot_and_die_without_changing_sources(self):
        before = self.catalog.spectra
        groups = self.catalog.grouped("lot")
        self.assertEqual(len(groups["AIT0080.42"]["AIT0080.00-22"]["2026-8-21-10-53-55"]), 20)
        dies = self.catalog.grouped("die")
        self.assertEqual([key for key in dies if key is not None], list(range(1, 21)))
        self.assertEqual(self.catalog.spectra, before)
        with self.assertRaises(ValueError):
            self.catalog.grouped("unsupported")

    def test_catalog_removes_selected_records_without_touching_source_files(self):
        catalog = SpectrumCatalog()
        catalog.replace(self.result)
        first = catalog.spectra[0]
        before = first.path.read_bytes()
        self.assertEqual(catalog.remove({first.key, "unknown"}), 1)
        self.assertEqual(len(catalog.spectra), 41)
        self.assertNotIn(first.key, {s.key for s in catalog.spectra})
        self.assertEqual(first.path.read_bytes(), before)
        self.assertEqual(catalog.remove({first.key}), 0)

    def test_reflectance_is_only_read_from_dts_not_from_other_instruments(self):
        dts = next(
            spectrum
            for spectrum in self.result.spectra
            if spectrum.identity.wafer == "LP300005.14"
        )
        dts_channel = dts.channels[0]
        self.assertEqual(dts_channel.spectrum_type, "reflectance")
        self.assertAlmostEqual(float(dts_channel.series("reflectance")[0]), 0.404299514318)
        self.assertIsNone(dts_channel.series("psi"))

        ait = next(
            spectrum
            for spectrum in self.result.spectra
            if spectrum.identity.wafer == "AIT0080.00-22"
        )
        ait_channel = ait.channels[0]
        self.assertIsNotNone(ait_channel.series("psi"))
        self.assertIsNone(ait_channel.series("reflectance"))

    def test_business_metadata_is_present_for_every_verified_channel(self):
        frame = self.catalog.metadata_dataframe()

        self.assertEqual(len(frame), 47)
        bbse = frame[frame["SME Name"] == "test_sme.sme"]
        self.assertEqual(len(bbse), 6)
        self.assertTrue((bbse["Channel Count"] == 6).all())
        ait = frame[frame["Wafer ID"] == "AIT0080.00-22"]
        self.assertEqual(len(ait), 20)
        self.assertTrue((ait["Tool SN"] == "A03-090").all())
        self.assertTrue((ait["Instrument"] == "UVSE_II+").all())
        self.assertTrue((ait["Mode"] == "UVSE").all())
        self.assertTrue((ait["Version"] == "SE3.3").all())
        self.assertTrue((ait["PAD Name"] == "2026-8-21-10-53-55").all())
        self.assertEqual(set(ait["Die Seq"]), set(range(1, 21)))
        dts = frame[frame["Wafer ID"] == "LP300005.14"].iloc[0]
        self.assertEqual(dts["Lot ID"], "SPC")
        self.assertEqual(dts["Tool SN"], "NAN-ANA")
        self.assertEqual(dts["PAD Name"], "AZI45")
        self.assertEqual(dts["Instrument"], "DTS")

    def test_external_filename_only_fills_missing_internal_identity(self):
        path = self.result.spectra[0].path
        metadata = base_metadata(path, "SE3.3", "unrecognized.sme", 1, None)

        self.assertEqual(metadata["wafer_id_filename"], "AIT0080.00-22")
        self.assertEqual(metadata["lot_id_filename"], "AIT0080.42")
        self.assertEqual(metadata["tool_sn_filename"], "A03-090")
        self.assertEqual(metadata["metadata_source"], "external")
        self.assertEqual(metadata["metadata_parse_status"], "ok")


class RealJC1913Tests(unittest.TestCase):
    @unittest.skipUnless(Path(r"C:\Users\Yuanhao Qin\OneDrive\Desktop\JC1913").is_dir(), "JC1913 unavailable")
    def test_every_real_file_is_readable_or_identified_as_encrypted(self):
        root = Path(r"C:\Users\Yuanhao Qin\OneDrive\Desktop\JC1913")
        paths = scan_sme_files(root)
        encrypted = set()
        for path in paths:
            with path.open("rb") as stream:
                if stream.read(16) == b"%TSD-Header-###%":
                    encrypted.add(path)
        result = load_folder(root)
        self.assertEqual({issue.path for issue in result.issues}, encrypted)
        self.assertTrue(all(issue.status == "encrypted" for issue in result.issues))
        self.assertEqual(len(result.spectra) + len(result.issues), len(paths))


if __name__ == "__main__":
    unittest.main()
