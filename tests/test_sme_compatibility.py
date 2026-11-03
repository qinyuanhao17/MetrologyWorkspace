"""Compatibility at the public SME reader without changing source bytes."""
import hashlib
import base64
import struct
from pathlib import Path
import tempfile
import unittest

import numpy as np

from metrology_app.sme_spectra import parse_sme_file, parse_spectrum_filename, UnsupportedSME
from tests.test_sme_spectra import SAMPLE_ROOT

ROOT = Path(r"C:\Users\Yuanhao Qin\OneDrive\Desktop\JC1913")
DPC = ROOT / "DPC00703.10_DH0912.003-OCD_NAN-ANA_PAD-E-45_Die1_C-1_R4_20260909141623387.sme"
IRSE_E = ROOT / "spectra_all_IRSE/20260923_102340/AZI0/LP100005.21_SPC_NAN-ANA_AZI0_Die1_C-2_R4_20260923102355127.sme"
LEGACY = ROOT / "OCD_RP01_OFFSETLTO_JC_FM.rcp/20211231_110043/LP100001.05_EFP43202_NA_NA_Die1_R2_C4_20211231110054097.sme"
LDSR = ROOT / "LP300005.23_GK-PadN-PLDSR-Dynamic_A13-048_PAD N_Die1_C-5_R0_20261016111859433.sme"


def qstring(value):
    encoded = value.encode("utf-16be")
    return struct.pack(">I", len(encoded)) + encoded


def reflectance_payload(*, expanded, global_word, points=3):
    def array(values=()):
        return struct.pack(">I", len(values)) + np.asarray(values, dtype=">f8").tobytes()
    header = (struct.pack(">I", 2) + qstring("sample") + qstring("Unlisted head") + qstring("UVSE")
              + struct.pack(">3d", 65, 0, 45) + qstring("label") + bytes(40) + struct.pack(">I", 0))
    channel = (header + array() + (struct.pack(">5I", 0, 100, 3500, 1078198272, 0) if expanded else b"")
               + array(11000. + np.arange(points)) + array() * 6
               + array(np.resize((0.1, 0.4, 0.2), points)) + array() * 3 + bytes(40))
    return (qstring("SE9.1") + struct.pack(">I", 2) + qstring("W_L_T_P_Die1_C0_R0.sme")
            + (struct.pack(">I", 0) if global_word else b"") + channel * 2)


class SMECompatibilityTests(unittest.TestCase):
    def test_unknown_metadata_and_short_infrared_series_accept_only_complete_layouts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.sme"
            for expanded, global_word in ((False, False), (True, True)):
                for points in (1, 2, 17, 1200):
                    with self.subTest(expanded=expanded, points=points):
                        payload = reflectance_payload(expanded=expanded, global_word=global_word, points=points)
                        path.write_bytes(b"SE3" + base64.b64encode(payload))
                        spectrum = parse_sme_file(path)
                        self.assertEqual(len(spectrum.channels), 2)
                        for channel in spectrum.channels:
                            self.assertEqual(channel.metadata["version"], "SE9.1")
                            self.assertEqual(channel.metadata["mode"], "UVSE")
                            np.testing.assert_array_equal(channel.wavelength, 11000 + np.arange(points))
                            np.testing.assert_array_equal(channel.series("reflectance"), np.resize((0.1, 0.4, 0.2), points))

    def test_corrupt_channel_count_lengths_and_footer_fail_without_partial_spectra(self):
        payload = reflectance_payload(expanded=True, global_word=True)
        channel_count_at = len(qstring("SE9.1"))
        wave_count_at = payload.index(struct.pack(">I3d", 3, 11000, 11001, 11002))
        corruptions = (
            payload[:-1], payload + b"unexpected",
            payload[:channel_count_at] + struct.pack(">I", 1) + payload[channel_count_at + 4:],
            payload[:wave_count_at] + struct.pack(">I", 4) + payload[wave_count_at + 4:],
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "corrupt.sme"
            for index, broken in enumerate(corruptions):
                with self.subTest(corruption=index):
                    path.write_bytes(b"SE3" + base64.b64encode(broken))
                    with self.assertRaises(UnsupportedSME):
                        parse_sme_file(path)

    @unittest.skipUnless(LDSR.is_file(), "supplied multichannel reflectance unavailable")
    def test_reflectance_channels_keep_their_own_sampling_and_source_identity(self):
        before = hashlib.sha256(LDSR.read_bytes()).hexdigest()
        spectrum = parse_sme_file(LDSR)
        self.assertEqual(len(spectrum.channels), 2)
        self.assertEqual((spectrum.identity.wafer, spectrum.identity.lot, spectrum.identity.pad),
                         ("LP300005.23", "GK-PadN-PLDSR-Dynamic", "PAD N"))
        self.assertAlmostEqual(spectrum.x_mm, -114.2600)
        self.assertAlmostEqual(spectrum.y_mm, -3.4922)
        for channel, points, label, start, reflectance in zip(
            spectrum.channels, (902, 903), ("0R", "90R"),
            (189.79424187451713, 189.00819645095802),
            (0.050498233058672605, 0.05940285244547118),
        ):
            self.assertEqual((channel.instrument, channel.metadata["mode"]), ("LDSR-P", "PSR"))
            self.assertEqual(channel.metadata["header_label"], label)
            self.assertEqual(channel.numeric.shape, (points, 2))
            self.assertAlmostEqual(channel.wavelength[0], start)
            self.assertAlmostEqual(channel.series("reflectance")[0], reflectance)
            for metric in ("psi", "delta", "N", "M00"):
                self.assertIsNone(channel.series(metric))
        self.assertEqual(hashlib.sha256(LDSR.read_bytes()).hexdigest(), before)

    @unittest.skipUnless(SAMPLE_ROOT.is_dir() and DPC.is_file() and LDSR.is_file(), "supplied spectra unavailable")
    def test_instrument_and_mode_are_metadata_for_all_supported_series(self):
        examples = [next((SAMPLE_ROOT / folder).glob("*.sme")) for folder in (
            "01_AIT_UVSE_20_Die", "02_wafer01_IMSE_20_Die", "03_BBSE_multichannel", "04_DTS_reflectance")]
        examples.extend((DPC, LDSR))
        with tempfile.TemporaryDirectory() as folder:
            for index, original in enumerate(examples):
                reference = parse_sme_file(original)
                payload = base64.b64decode(original.read_bytes()[3:])
                replacements = {(channel.instrument, channel.metadata["mode"]) for channel in reference.channels}
                for instrument, mode in replacements:
                    payload = payload.replace(qstring(instrument) + qstring(mode),
                                              qstring("Unlisted measurement head") + qstring("Unlisted mode"))
                target = Path(folder) / str(index) / original.name
                target.parent.mkdir()
                target.write_bytes(b"SE3" + base64.b64encode(payload))
                spectrum = parse_sme_file(target)
                self.assertEqual(spectrum.identity, reference.identity)
                self.assertEqual(len(spectrum.channels), len(reference.channels))
                for channel, expected in zip(spectrum.channels, reference.channels):
                    self.assertEqual(channel.instrument, "Unlisted measurement head")
                    self.assertEqual(channel.metadata["mode"], "Unlisted mode")
                    self.assertEqual(channel.spectrum_type, expected.spectrum_type)
                    np.testing.assert_array_equal(channel.numeric, expected.numeric)

    @unittest.skipUnless(DPC.is_file() and SAMPLE_ROOT.is_dir(), "supplied spectra unavailable")
    def test_unknown_internal_version_does_not_change_supported_numeric_layouts(self):
        compact = next((SAMPLE_ROOT / "01_AIT_UVSE_20_Die").glob("*.sme"))
        with tempfile.TemporaryDirectory() as folder:
            for index, original in enumerate((compact, DPC)):
                reference = parse_sme_file(original)
                payload = base64.b64decode(original.read_bytes()[3:])
                changed = payload[:4] + "SE9.1".encode("utf-16be") + payload[14:]
                target = Path(folder) / f"different-name-{index}.sme"
                target.write_bytes(b"SE3" + base64.b64encode(changed))
                spectrum = parse_sme_file(target)
                self.assertEqual(spectrum.channels[0].metadata["version"], "SE9.1")
                self.assertEqual(spectrum.identity, reference.identity)
                np.testing.assert_array_equal(spectrum.channels[0].numeric, reference.channels[0].numeric)

    @unittest.skipUnless(LEGACY.is_file(), "supplied compressed legacy spectrum unavailable")
    def test_compressed_legacy_keeps_stored_values_and_does_not_invent_missing_ncs(self):
        before = hashlib.sha256(LEGACY.read_bytes()).hexdigest()
        spectrum = parse_sme_file(LEGACY)
        channel = spectrum.channels[0]
        self.assertEqual(channel.metadata["version"], "SE2.8")
        self.assertEqual((spectrum.identity.wafer, spectrum.identity.lot, spectrum.identity.pad),
                         ("LP100001.05", "EFP43202", "NA"))
        self.assertEqual((spectrum.identity.die_seq, spectrum.identity.field_x, spectrum.identity.field_y), (1, 4, 2))
        self.assertEqual(channel.numeric.shape, (916, 24))
        np.testing.assert_allclose(channel.wavelength[[0, -1]], [210.2803955078125, 899.7052001953125])
        self.assertAlmostEqual(channel.series("M01")[0], -0.2497396320104599)
        np.testing.assert_allclose(channel.series("psi")[[0, -1]], [34.81912612915039, 23.184377670288086])
        np.testing.assert_allclose(channel.series("delta")[[0, -1]], [11.160208702087402, 93.63890838623047])
        self.assertIsNone(channel.series("N"))
        self.assertIsNone(channel.series("reflectance"))
        self.assertAlmostEqual(spectrum.x_mm, -64.2296)
        self.assertAlmostEqual(spectrum.y_mm, 125.3360)
        self.assertEqual(hashlib.sha256(LEGACY.read_bytes()).hexdigest(), before)

    def test_legacy_filename_keeps_named_row_and_column_when_r_precedes_c(self):
        identity = parse_spectrum_filename("LP100001.05_EFP43202_NA_NA_Die1_R2_C4_20211231110054097.sme")
        self.assertEqual((identity.wafer_id, identity.lot_id, identity.pad_name), ("LP100001.05", "EFP43202", "NA"))
        self.assertEqual((identity.die_seq, identity.field_x, identity.field_y), (1, 4, 2))

    @unittest.skipUnless(DPC.is_file() and IRSE_E.is_file(), "supplied spectra unavailable")
    def test_expanded_series_accepts_both_supplied_head_names_and_keeps_metadata(self):
        for path, instrument, count, start in (
            (DPC, "UVSE_II+", 903, 190.04508408306458),
            (IRSE_E, "IRSE_II_E(1700)", 234, 949.6094199165464),
        ):
            with self.subTest(path=path.name):
                before = hashlib.sha256(path.read_bytes()).hexdigest()
                spectrum = parse_sme_file(path)
                channel = spectrum.channels[0]
                self.assertEqual(channel.instrument, instrument)
                self.assertEqual(channel.metadata["version"], "SE3.5")
                self.assertEqual(len(channel.wavelength), count)
                self.assertAlmostEqual(channel.wavelength[0], start)
                np.testing.assert_array_equal(channel.series("M00"), np.ones(count))
                self.assertIsNotNone(channel.series("psi"))
                self.assertIsNotNone(channel.series("N"))
                self.assertIsNone(channel.series("reflectance"))
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
