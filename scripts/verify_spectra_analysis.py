"""Verify residual/GRR modes against independent calculations on real SME files."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_tests import isolate_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--grr10", action="store_true", help="Use ten spectra of the first wafer/channel as a GRR-sized fixture.")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="spectra-analysis-") as scratch:
        isolate_settings(scratch)
        import numpy as np
        from PyQt6.QtCore import QPointF, Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from metrology_app.appearance import configure_fonts, set_theme_palette
        from metrology_app.sme_spectra import load_folder, LoadResult
        from metrology_app.spectra_viewer import ROLE_KEY, SpectraViewerWindow

        app = QApplication([])
        configure_fonts(app)
        set_theme_palette("light")
        app.setStyleSheet(Path("metrology_app/theme_light.qss").read_text(encoding="utf-8"))
        result = load_folder(args.folder)
        if args.grr10:
            first = result.spectra[0]
            result = LoadResult(tuple(s for s in result.spectra if (s.identity.wafer, s.identity.lot, s.identity.pad) == (first.identity.wafer, first.identity.lot, first.identity.pad)
                                      and first.channels[0].key in s.channel_keys)[:10], ())
        window = SpectraViewerWindow()
        window.resize(1800, 1000)
        window.show()
        window.apply_load_result(result, replace=True)

        def digest():
            h = hashlib.sha256()
            for s in result.spectra:
                for c in s.channels:
                    h.update(c.numeric.tobytes())
            return h.hexdigest()

        before = digest()
        def settle():
            deadline = time.monotonic() + 90
            for _ in range(4):
                QTest.qWait(5)
            while window.plot_render_pending and time.monotonic() < deadline:
                QTest.qWait(5)
            assert not window.plot_render_pending

        window.check_all_spectra()
        settle()
        baseline = result.spectra[0]
        start = time.perf_counter()
        window.set_baseline(baseline.key)
        residual_submit = time.perf_counter() - start
        settle()
        residual_complete = time.perf_counter() - start
        panel = window.plot_panels["S"]
        checks = 0
        for group in panel.groups:
            matches = [c for c in baseline.channels if c.key == group.key.channel]
            if len(matches) != 1:
                continue
            bc = matches[0]
            lookup = dict(zip(bc.wavelength, bc.series("S")))
            for segment in group.segments:
                source = next(s for s in result.spectra if s.key == segment.spectrum_key)
                sc = next(c for c in source.channels if c.key == group.key.channel)
                expected = [y - lookup[x] if x in lookup else np.nan
                            for x, y in zip(sc.wavelength, sc.series("S"))]
                np.testing.assert_allclose(segment.y, expected, rtol=1e-12, atol=1e-12, equal_nan=True)
                checks += 1
        assert checks
        window.grab().save("qa_spectra_residual_grr10.png" if args.grr10 else "qa_spectra_residual.png")
        start = time.perf_counter()
        window.set_analysis_mode("3sigma")
        sigma_submit = time.perf_counter() - start
        settle()
        sigma_complete = time.perf_counter() - start
        panels = [(window.plot_panels[m], [(m, "groups")]) for m in ("N", "C", "S", "reflectance")]
        panels += [(window.plot_panels["psi_delta"], [("psi", "groups"), ("delta", "secondary_groups")])]
        panels += [(p, [(m, "groups")]) for m, p in window.mueller_panel.mij_plots.items()]
        sigma_checks = 0
        for target, metrics in panels:
            for metric, attribute in metrics:
                for group in getattr(target, attribute):
                    segment = group.segments[0]
                    samples = [c for s in result.spectra if (s.identity.wafer, s.identity.lot, s.identity.pad) == (group.key.wafer, group.key.lot, group.key.pad)
                               for c in s.channels if c.key == group.key.channel and c.series(metric) is not None]
                    matrix = np.full((len(samples), len(segment.x)), np.nan)
                    for row, c in enumerate(samples):
                        valid = np.isfinite(c.wavelength)
                        matrix[row, np.searchsorted(segment.x, c.wavelength[valid])] = c.series(metric)[valid]
                    counts = np.isfinite(matrix).sum(axis=0)
                    expected = np.full(len(segment.x), np.nan)
                    enough = counts >= 2
                    expected[enough] = 3 * np.nanstd(matrix[:, enough], axis=0, ddof=1)
                    np.testing.assert_allclose(segment.y, expected, atol=1e-10, rtol=1e-10, equal_nan=True)
                    sigma_checks += 1
        identities = tuple(map(id, panel.plot.listDataItems()))
        window.toggle_channel(panel.groups[0].key)
        window.build_legend_menu("NCS").actions()[0].trigger()
        settle()
        assert tuple(map(id, panel.plot.listDataItems())) == identities
        window.grab().save("qa_spectra_3sigma_grr10.png" if args.grr10 else "qa_spectra_3sigma.png")
        floating = window.open_plot_window(panel)
        assert "3σ" in floating.windowTitle()
        after = digest()
        assert before == after
        checked_before = {s.key for s in window.checked_spectra()}
        window.set_analysis_mode("residual")
        clear_menu = window.build_tree_menu()
        next(a for a in clear_menu.actions() if a.text() == "Clear BSL").trigger()
        assert window.baseline_spectrum is None and window.analysis_mode == "original"
        assert {s.key for s in window.checked_spectra()} == checked_before
        settle()
        mapping = window.open_wafer_map()
        mapping.resize(1500, 900)
        for _ in range(5):
            QTest.qWait(20)
        wafer = (baseline.identity.wafer, baseline.identity.lot, baseline.identity.pad)
        point_plot = mapping.wafer_plots[wafer]
        view = point_plot.plot.getViewBox()
        ranges = view.viewRange()
        px, py = point_plot.scatter.getData()
        a = point_plot.plot.mapFromScene(view.mapViewToScene(QPointF(float(min(px) - 3), float(min(py) - 3))))
        b = point_plot.plot.mapFromScene(view.mapViewToScene(QPointF(float(max(px) + 3), float(max(py) + 3))))
        QTest.mousePress(point_plot.plot.viewport(), Qt.MouseButton.LeftButton, pos=a)
        QTest.mouseMove(point_plot.plot.viewport(), ((QPointF(a) + QPointF(b)) / 2).toPoint())
        QTest.qWait(30)
        QTest.mouseMove(point_plot.plot.viewport(), b)
        QTest.qWait(30)
        QTest.mouseRelease(point_plot.plot.viewport(), Qt.MouseButton.LeftButton, pos=b)
        settle()
        expected_keys = {s.key for s in result.spectra
                         if (s.identity.wafer, s.identity.lot, s.identity.pad) == wafer and s.has_map_point}
        assert panel.selected_keys == expected_keys
        assert {i.data(0, ROLE_KEY) for i in window.tree.selectedItems()} == expected_keys
        assert view.viewRange() == ranges
        assert not any(b.text() == "Show All" for b in window.findChildren(type(window.open_map_button)))
        mapping.grab().save("qa_spectra_map_box_grr10.png" if args.grr10 else "qa_spectra_map_box.png")
        report = {"spectra": len(result.spectra), "load_issues": len(result.issues),
                  "baseline": str(baseline.path), "qt_platform": app.platformName(),
                  "residual": {"S_spectra_verified": checks, "submit_seconds": residual_submit,
                               "complete_seconds": residual_complete},
                  "three_sigma": {"curves_verified": sigma_checks, "submit_seconds": sigma_submit,
                                  "complete_seconds": sigma_complete, "ddof": 1,
                                  "grouping": "Wafer ID and channel", "wavelength_alignment": "exact"},
                  "source_arrays_sha256": before, "source_arrays_unchanged": before == after,
                  "legend_restore_keeps_curve_items": True,
                  "clear_bsl_keeps_checked_sources": True,
                  "map_box_selected_spectra": len(expected_keys),
                  "map_box_syncs_tree_and_curves_without_zoom": True,
                  "show_all_buttons_removed": True}
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
        window.close()
        window.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    main()
