"""Qt integration checks for the spectra review workflow."""

import os
from pathlib import Path
import time
import tempfile
import unittest
from dataclasses import replace

import numpy as np
import pyqtgraph as pg

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, QTimer, Qt
from PyQt6.QtGui import QAction, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QLineEdit,
    QMenu,
    QPushButton,
    QSplitter,
    QToolBar,
)

from metrology_app.sme_spectra import (
    LoadIssue,
    LoadResult,
    SpectrumChannel,
    SpectrumFile,
    SpectrumIdentity,
)
from metrology_app.spectra_viewer import ROLE_KEY, SpectraViewerWindow
from metrology_app.spectra_plots import CurveGroup, CurveSegment
from PyQt6.QtGui import QColor
from tests.test_sme_spectra import SAMPLE_ROOT, copy_verified_samples


APP = QApplication.instance() or QApplication([])


def make_spectrum(die, *, wafer="W1", lot="L1", pad="P1"):
    wavelength = np.array([200.0, 300.0, 400.0])
    numeric = np.full((3, 24), np.nan)
    numeric[:, 0] = wavelength
    numeric[:, 1] = [20, 21, 22]
    numeric[:, 2] = [30, 31, 32]
    numeric[:, 3] = [0.1, 0.2, 0.3]
    numeric[:, 4] = [0.4, 0.5, 0.6]
    numeric[:, 5] = [0.7, 0.8, 0.9]
    numeric[:, 8:] = np.arange(48).reshape(3, 16) / 10
    metadata = {
        "channel_id": 1,
        "channel_count": 1,
        "instrument": "UVSE_II+",
        "mode": "UVSE",
        "version": "SE3.5",
        "sample_id": "sample",
        "parse_status": "ok",
        "angle_1_deg": 65.0,
        "angle_2_deg": 45.0,
        "angle_3_deg": 45.0,
    }
    channel = SpectrumChannel(metadata, wavelength, numeric, "mueller")
    path = Path(f"C:/fixtures/{wafer}_{lot}_{pad}_Die{die}.sme")
    return SpectrumFile(
        path=path,
        key=str(path).casefold(),
        size_bytes=100,
        mtime_ns=1,
        identity=SpectrumIdentity(
            wafer=wafer,
            lot=lot,
            pad=pad,
            die_seq=die,
            timestamp=f"2026-10-31 10:00:{die:02d}",
            tool_sn="A03-090",
            field_x=-1,
            field_y=5,
            parse_status="ok",
        ),
        embedded_filename=path.name,
        channels=(channel,),
        x_mm=float(die),
        y_mm=0.0,
        coordinate_source="header",
    )


class SpectraViewerTreeTests(unittest.TestCase):
    def test_hiding_and_restoring_a_batched_channel_retains_its_source_buffers(self):
        spectra = tuple(make_spectrum(1, wafer=f"W{i:02}") for i in range(40))
        self.window.apply_load_result(LoadResult(spectra, ()), replace=True)
        self.window.check_all_spectra()
        panel = self.window.plot_panels["S"]
        items = tuple(panel._curve_items)
        buffers = [(item.xData, item.yData) for item in items]
        channel = spectra[0].channels[0].key
        self.window.set_channel_visible(channel, False)
        self.assertFalse(panel.groups)
        self.window.set_channel_visible(channel, True)
        self.assertEqual(tuple(panel._curve_items), items)
        for item, (x, y) in zip(items, buffers):
            self.assertIs(item.xData, x)
            self.assertIs(item.yData, y)

    def test_legend_select_channel_controls_all_wafers_without_rebuilding_curves(self):
        first = make_spectrum(1)
        second_channel = replace(first.channels[0], metadata={**first.channels[0].metadata,
                                                               "channel_id": 2, "angle_3_deg": 90.0})
        first = replace(first, channels=(*first.channels, second_channel))
        second = replace(make_spectrum(2, wafer="W2"), channels=first.channels)
        self.window.apply_load_result(LoadResult((first, second), ()), replace=True)
        self.window.check_all_spectra()
        self.window.select_spectrum_keys({first.key})
        panel = self.window.plot_panels["S"]
        floating = self.window.open_plot_window(panel)
        panel.plot.setXRange(250, 350, padding=0)
        items = tuple(panel._curve_items)
        checked = self.window.checked_spectra()
        menu = self.window.build_legend_menu("Mueller")
        actions = {a.text(): a for a in menu.actions()}
        self.assertIn("Select Channel", actions)
        channels = actions["Select Channel"].menu()
        entries = channels.actions()
        self.assertEqual([a.text() for a in entries], [c.key.legend_label for c in first.channels])
        self.assertTrue(all(a.isCheckable() and a.isChecked() for a in entries))
        entries[0].trigger()
        self.assertFalse(entries[0].isChecked())
        self.assertTrue(entries[1].isChecked())
        for target in (panel, floating.panel, self.window.mueller_panel.mij_plots["M01"]):
            self.assertEqual({g.key.channel for g in target.groups}, {second_channel.key})
        self.assertTrue(actions["Show All"].isEnabled())
        self.assertEqual(tuple(panel._curve_items), items)
        self.assertEqual(self.window.checked_spectra(), checked)
        self.assertEqual(panel.selected_keys, {first.key})
        self.assertEqual(panel.plot.getViewBox().viewRange()[0], [250, 350])
        entries[1].trigger()
        self.assertFalse(panel.groups)
        self.assertFalse(actions["Hide All"].isEnabled())
        actions["Show All"].trigger()
        self.assertTrue(all(a.isChecked() for a in entries))
        self.assertEqual(len(panel.groups), 4)
        # Individual legend choices can leave a channel partly visible.
        self.window.toggle_channel(panel.groups[0].key)
        channels.aboutToShow.emit()
        self.assertTrue(entries[0].isChecked())
        entries[0].trigger()
        self.assertTrue(self.window.channel_hidden(first.channels[0].key))
        entries[0].trigger()
        self.assertFalse(self.window.channel_hidden(first.channels[0].key))
        self.window.color_by_combo.setCurrentIndex(self.window.color_by_combo.findData("sme"))
        regrouped = self.window.build_legend_menu("Mueller")
        submenu = next(a.menu() for a in regrouped.actions() if a.text() == "Select Channel")
        self.assertEqual(len(submenu.actions()), 2)

    def test_channel_checkboxes_remain_open_and_restore_hidden_checked_sources(self):
        first = make_spectrum(1)
        second_channel = replace(first.channels[0], metadata={**first.channels[0].metadata, "channel_id": 2})
        first = replace(first, channels=(*first.channels, second_channel))
        unchecked = make_spectrum(2, wafer="Unchecked")
        self.window.apply_load_result(LoadResult((first, unchecked), ()), replace=True)
        self.window.set_spectrum_checks({first.key: True})
        self.window.hide_all_channels("Mueller")
        self.window.show()
        APP.processEvents()
        menu = self.window.build_legend_menu("Mueller")
        submenu = next(a.menu() for a in menu.actions() if a.text() == "Select Channel")
        submenu.popup(QPoint(100, 100))
        APP.processEvents()
        first_action, second_action = submenu.actions()
        self.assertFalse(first_action.isChecked())
        QTest.mouseClick(submenu, Qt.MouseButton.LeftButton, pos=submenu.actionGeometry(first_action).center())
        self.assertTrue(submenu.isVisible())
        self.assertTrue(first_action.isChecked())
        self.assertEqual({g.key.channel for g in self.window.plot_panels["S"].groups}, {first.channels[0].key})
        submenu.setActiveAction(second_action)
        QTest.keyClick(submenu, Qt.Key.Key_Space)
        self.assertTrue(submenu.isVisible())
        self.assertTrue(second_action.isChecked())
        self.assertEqual(self.window.checked_spectra(), (first,))
        submenu.close()

    def test_map_and_enlarged_plot_support_application_scoped_pinning(self):
        from unittest.mock import patch
        from PyQt6.QtCore import QEvent
        self.window.check_all_spectra()
        maps = self.window.open_wafer_map()
        enlarged = self.window.open_plot_window(self.window.plot_panels["N"])
        for target in (maps, enlarged):
            self.assertFalse(target.findChildren(QToolBar))
            self.assertIn(target.window_pin.action, target.actions())
            self.assertEqual(target.window_pin.action.shortcut().toString(), "Alt+P")
            self.assertFalse(target.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
            self.assertFalse(target.window_pin.action.isChecked())
            target.window_pin.action.trigger()
            self.assertTrue(target.window_pin.pinned)
            self.assertFalse(target.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
            target.window_pin.action.trigger()
            self.assertFalse(target.window_pin.pinned)
            peer = enlarged if target is maps else maps
            with patch.object(target, "raise_") as raised, \
                    patch.object(QApplication, "applicationState", return_value=Qt.ApplicationState.ApplicationActive), \
                    patch.object(QApplication, "activeWindow", return_value=peer):
                APP.sendEvent(peer, QEvent(QEvent.Type.WindowActivate))
                APP.processEvents()
                raised.assert_not_called()
                target.window_pin.action.trigger()
                APP.processEvents()
                raised.assert_called_once()
                raised.reset_mock()
                with patch.object(QApplication, "activeModalWidget", return_value=peer):
                    APP.sendEvent(peer, QEvent(QEvent.Type.WindowActivate))
                    APP.processEvents()
                raised.assert_not_called()
            target.window_pin.set_pinned(False)

    def test_resizing_dense_plots_keeps_curves_and_coalesces_paint_batches(self):
        from unittest.mock import patch
        source = self.spectra[0]
        x = np.linspace(200, 900, 3000)
        numeric = np.tile(source.channels[0].numeric[:1], (len(x), 1))
        numeric[:, 0] = x
        channel = replace(source.channels[0], wavelength=x, numeric=numeric)
        self.window.apply_load_result(LoadResult((replace(source, channels=(channel,)),), ()), replace=True)
        self.window.check_all_spectra()
        self.window.show()
        QTest.qWait(100)
        panel = self.window.plot_panels["N"]
        items = tuple(panel._curve_items)
        with patch.object(self.window, "_schedule_plot_paints", wraps=self.window._schedule_plot_paints) as forced:
            self.window.resize(1500, 850)
            APP.processEvents()
            self.assertLessEqual(forced.call_count, 1)
            self.assertTrue(panel.plot.updatesEnabled())
            self.assertTrue(panel.plot.viewport().updatesEnabled())
        self.assertEqual(tuple(panel._curve_items), items)

    def test_die_map_apply_to_similar_wafer_updates_checks_once_and_retains_maps(self):
        spectra = tuple(replace(make_spectrum(die, wafer=wafer), x_mm=float(die)+(5 if wafer == "Far" else 0))
                        for wafer in ("W1", "Near", "Far") for die in (1, 2))
        self.window.apply_load_result(LoadResult(spectra, ()), replace=True)
        self.window.check_all_spectra()
        self.window.set_spectrum_checks({spectra[1].key: False})
        maps = self.window.open_wafer_map()
        QTest.qWait(100)
        original = dict(maps.wafer_plots)
        action = next(a for a in maps.build_selection_menu(("W1", "L1", "P1")).actions()
                      if a.text() == "Apply Check To Similar Wafer")
        action.trigger()
        self.assertEqual({s.key for s in self.window.checked_spectra()},
                         {spectra[i].key for i in (0, 2, 4, 5)})
        self.assertEqual(maps.wafer_plots, original)
        self.assertIn("Applied to 1", maps.statusBar().currentMessage())

    def test_die_map_double_click_toggles_checks_without_recreating_plots(self):
        self.window.uncheck_all_spectra()
        self.window.show()
        maps = self.window.open_wafer_map()
        QTest.qWait(100)
        plot = next(iter(maps.wafer_plots.values()))
        self.assertEqual(self.window.open_map_button.text(), "Open Die Map")
        self.assertEqual(maps.windowTitle(), "Spectrum Die Map")
        spectrum = self.window.catalog.spectra[0]
        for expected in (True, False):
            # Qt lays out axes when paint updates resume. Target the current
            # marker position after that event turn, as an actual user would.
            QTest.qWait(20)
            position = plot.plot.mapFromScene(plot.plot.getViewBox().mapViewToScene(QPointF(spectrum.x_mm, spectrum.y_mm)))
            QTest.mouseDClick(plot.plot.viewport(), Qt.MouseButton.LeftButton, pos=position)
            QTest.mouseRelease(plot.plot.viewport(), Qt.MouseButton.LeftButton, pos=position)
            APP.processEvents()
            self.assertEqual(spectrum.key in {s.key for s in self.window.checked_spectra()}, expected)
            self.assertIs(next(iter(maps.wafer_plots.values())), plot)

    def setUp(self):
        self.window = SpectraViewerWindow()
        self.spectra = (
            make_spectrum(10),
            make_spectrum(2),
        )
        self.window.apply_load_result(
            LoadResult(self.spectra, ()),
            replace=True,
        )

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def test_legend_hide_all_preserves_checks_selection_axes_and_other_sections(self):
        reference = make_spectrum(3, wafer="Reflectance")
        channel = replace(reference.channels[0], spectrum_type="reflectance", numeric=reference.channels[0].numeric[:, :2])
        reference = replace(reference, channels=(channel,))
        self.window.apply_load_result(LoadResult((*self.spectra, reference), ()), replace=True)
        self.window.check_all_spectra()
        self.window.select_spectrum_keys({self.spectra[0].key})
        panel = self.window.plot_panels["S"]
        panel.plot.setXRange(250, 350, padding=0)
        checked = tuple(s.key for s in self.window.checked_spectra())
        reference_key = self.window.plot_panels["reflectance"].groups[0].key
        self.window.toggle_channel(reference_key)
        menu = self.window.build_legend_menu("Mueller")
        actions = {action.text(): action for action in menu.actions()}
        self.assertIn("Hide All", actions)
        self.assertTrue(actions["Hide All"].isEnabled())
        actions["Hide All"].trigger()
        self.assertFalse(panel.groups)
        self.assertEqual(tuple(s.key for s in self.window.checked_spectra()), checked)
        self.assertEqual(panel.selected_keys, {self.spectra[0].key})
        self.assertEqual(panel.plot.getViewBox().viewRange()[0], [250, 350])
        actions = {action.text(): action for action in self.window.build_legend_menu("Mueller").actions()}
        self.assertFalse(actions["Hide All"].isEnabled())
        self.assertTrue(actions["Show All"].isEnabled())
        actions["Show All"].trigger()
        self.assertTrue(panel.groups)
        self.assertFalse(self.window.plot_panels["reflectance"].groups)
        self.assertEqual(panel.plot.getViewBox().viewRange()[0], [250, 350])

    def test_legend_selection_follows_wafer_and_sme_groups_without_changing_checks(self):
        other_channel = replace(self.spectra[0].channels[0], metadata={
            **self.spectra[0].channels[0].metadata, "channel_id": 2, "angle_3_deg": 90})
        first = replace(self.spectra[0], channels=(*self.spectra[0].channels, other_channel))
        other_wafer = make_spectrum(1, wafer="W2")
        self.window.apply_load_result(LoadResult((first, self.spectra[1], other_wafer), ()), replace=True)
        self.window.check_all_spectra()
        checked = {s.key for s in self.window.checked_spectra()}
        panel = self.window.plot_panels["S"]
        panel.plot.setXRange(250, 350, padding=0)
        for mode in ("wafer", "sme"):
            self.window.set_color_mode(mode)
            self.window.select_spectrum_keys({first.key})
            for family in ("NCS", "Psi Delta", "Mueller"):
                legend = self.window.legends[family]
                selected = legend.selectedItems()
                self.assertEqual(len(selected), 2, (mode, family))
                self.assertEqual({item.data(Qt.ItemDataRole.UserRole).channel.channel_id for item in selected}, {1, 2})
                self.assertTrue(all(item.font().bold() for item in selected))
                self.assertTrue(all(item.data(Qt.ItemDataRole.UserRole).wafer == "W1" for item in selected))
                if mode == "sme":
                    self.assertTrue(all(item.data(Qt.ItemDataRole.UserRole).spectrum_key == first.key for item in selected))
            self.window.select_spectrum_keys({first.key, other_wafer.key})
            self.assertEqual(len(self.window.legends["NCS"].selectedItems()), 3)
            selected_item = self.window.legends["NCS"].selectedItems()[0]
            hidden_key = selected_item.data(Qt.ItemDataRole.UserRole)
            self.window.toggle_channel(hidden_key)
            self.assertTrue(selected_item.isSelected())
            self.assertTrue(selected_item.font().bold())
            self.assertTrue(selected_item.font().strikeOut())
            self.assertTrue(self.window.channel_hidden(hidden_key))
            self.window.toggle_channel(hidden_key)
            self.window.select_spectrum_keys(set())
            self.assertFalse(self.window.legends["NCS"].selectedItems())
            self.assertTrue(all(not self.window.legends["NCS"].item(i).font().bold()
                                for i in range(self.window.legends["NCS"].count())))
            self.assertEqual({s.key for s in self.window.checked_spectra()}, checked)
            self.assertEqual(panel.plot.getViewBox().viewRange()[0], [250, 350])

    def test_tree_groups_wafer_lot_pad_and_orders_die_numerically(self):
        tree = self.window.tree
        self.assertEqual(tree.topLevelItemCount(), 1)
        wafer = tree.topLevelItem(0)
        self.assertEqual(wafer.text(0), "W1")
        self.assertEqual(wafer.childCount(), 1)
        lot = wafer.child(0)
        self.assertEqual(lot.text(0), "L1")
        pad = lot.child(0)
        pad.setExpanded(True)
        self.assertEqual(pad.text(0), "P1")
        self.assertEqual(
            [pad.child(index).text(0) for index in range(pad.childCount())],
            ["Die 2", "Die 10"],
        )
        self.assertNotIn("Files", [
            self.window.tree.headerItem().text(index)
            for index in range(self.window.tree.columnCount())
        ])
        leaf = pad.child(0)
        by_header = {
            self.window.tree.headerItem().text(index): leaf.text(index)
            for index in range(self.window.tree.columnCount())
        }
        self.assertEqual(by_header["SME Name"], leaf.toolTip(1).splitlines()[0])
        self.assertEqual(by_header["Lot ID"], "L1")
        self.assertEqual(by_header["Tool SN"], "A03-090")
        self.assertEqual(by_header["PAD Name"], "P1")
        self.assertEqual(by_header["Die Seq"], "2")
        self.assertEqual(by_header["FIELD X"], "-1")
        self.assertEqual(by_header["FIELD Y"], "5")
        self.assertEqual(by_header["Time"], "2026-10-31 10:00:02")
        self.assertEqual(by_header["Instrument"], "UVSE_II+")
        self.assertEqual(self.window.checked_spectra(), ())

    def test_spectrum_leaves_are_created_only_when_the_pad_opens(self):
        pad = self.window.tree.topLevelItem(0).child(0).child(0)
        self.assertEqual(pad.childCount(), 0)
        self.assertEqual(self.window.spectrum_items, {})
        pad.setExpanded(True)
        self.assertEqual(pad.childCount(), 2)
        self.assertEqual(len(self.window.spectrum_items), 2)

    def test_pad_arrow_opens_lazy_spectra_with_a_mouse_click(self):
        self.window.show()
        tree = self.window.tree
        wafer = tree.topLevelItem(0)
        lot = wafer.child(0)
        pad = lot.child(0)
        wafer.setExpanded(True)
        lot.setExpanded(True)
        APP.processEvents()
        self.assertAlmostEqual(self.window.main_splitter.sizes()[0] /
                               sum(self.window.main_splitter.sizes()), .25, delta=.03)
        self.assertEqual(pad.childCount(), 0)
        rect = tree.visualItemRect(pad)
        arrow = QPoint(rect.left() - tree.indentation() // 2, rect.center().y())
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=arrow)
        APP.processEvents()
        self.assertTrue(pad.isExpanded())
        self.assertEqual([pad.child(i).text(0) for i in range(pad.childCount())],
                         ["Die 2", "Die 10"])
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=arrow)
        APP.processEvents()
        self.assertFalse(pad.isExpanded())
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=arrow)
        APP.processEvents()
        self.assertTrue(pad.isExpanded())
        self.assertEqual(pad.childCount(), 2)

    def test_channel_summary_counts_instrument_angle_pairs_without_duplicate_footer(self):
        first, second = self.spectra
        channel = first.channels[0]
        duplicate = replace(channel, metadata={**channel.metadata, "channel_id": 7})
        other_angle = replace(channel, metadata={**channel.metadata, "angle_3_deg": 90})
        other_instrument = replace(channel, metadata={**channel.metadata, "instrument": "Other"})
        unknown = replace(channel, metadata={**channel.metadata, "angle_1_deg": None,
                                             "angle_3_deg": None})
        unknown_two = replace(unknown, metadata={**unknown.metadata, "channel_id": 2})
        first = replace(first, channels=(channel, duplicate, other_angle, other_instrument, unknown, unknown_two))
        self.window.apply_load_result(LoadResult((first, second), ()), replace=True)
        self.assertEqual(self.window.catalog.channel_count, 5)
        self.assertIn("2 spectra · 5 channels", self.window.tree_summary.text())
        self.assertEqual(self.window.status.text(), "")

    def test_filter_by_reclassifies_tree_without_changing_participation_selection_or_plots(self):
        spectra = (make_spectrum(10, wafer="W1", lot="L2", pad="P2"),
                   make_spectrum(2, wafer="W2", lot="L1", pad="P2"),
                   make_spectrum(1, wafer="W1", lot="L1", pad="P1"))
        self.window.apply_load_result(LoadResult(spectra, ()), replace=True)
        self.window.resize(1800, 1000)
        self.window.show()
        self.window.check_all_spectra()
        self.window.select_spectrum_keys({spectra[0].key})
        panel = self.window.plot_panels["S"]
        panel.plot.setXRange(250, 300, padding=0)
        curves = panel.groups
        for index, labels in enumerate((("W1", "W2"), ("L1", "L2"), ("P1", "P2"),
                                         ("Die 1", "Die 2", "Die 10"))):
            with self.subTest(group=index):
                self.window.group_by_combo.setCurrentIndex(index)
                APP.processEvents()
                tree = self.window.tree
                self.assertEqual(tuple(tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())), labels)
                self.assertEqual({s.key for s in self.window.checked_spectra()}, {s.key for s in spectra})
                self.assertEqual({item.data(0, ROLE_KEY) for item in tree.selectedItems()}, {spectra[0].key})
                self.assertEqual(panel.selected_keys, {spectra[0].key})
                self.assertEqual(panel.plot.getPlotItem().vb.viewRange()[0], [250, 300])
                self.assertIs(panel.groups, curves)
        self.window.tree.topLevelItem(2).setCheckState(0, Qt.CheckState.Unchecked)
        self.assertEqual({s.key for s in self.window.checked_spectra()}, {s.key for s in spectra[1:]})

    def test_delete_tree_removes_only_selected_folded_branch_and_keeps_disk_files(self):
        with tempfile.TemporaryDirectory() as folder:
            spectra = []
            paths = []
            for index, source in enumerate((make_spectrum(1), make_spectrum(2), make_spectrum(1, wafer="W2"))):
                path = Path(folder) / f"source-{index}.sme"
                path.write_bytes(b"original SME bytes")
                paths.append(path)
                spectra.append(replace(source, path=path, key=str(path).casefold()))
            self.window.apply_load_result(LoadResult(tuple(spectra), ()), replace=True)
            self.window.check_all_spectra()
            maps = self.window.open_wafer_map()
            self.window.group_by_combo.setCurrentIndex(1)
            branch = self.window.tree.topLevelItem(0).child(0)
            self.assertEqual(branch.text(0), "W1")
            self.assertFalse(branch.isExpanded())
            branch.setSelected(True)
            actions = {action.text(): action for action in self.window.build_tree_menu().actions()}
            self.assertTrue(actions["Delete Tree"].isEnabled())
            actions["Delete Tree"].trigger()
            self.assertEqual(self.window.catalog.spectra, (spectra[2],))
            self.assertEqual(self.window.checked_spectra(), (spectra[2],))
            self.assertEqual(maps.wafer_count, 1)
            actions = {action.text(): action for action in self.window.build_tree_menu().actions()}
            self.assertFalse(actions["Delete Tree"].isEnabled())
            self.window.tree.topLevelItem(0).setSelected(True)
            {action.text(): action for action in self.window.build_tree_menu().actions()}["Delete Tree"].trigger()
            self.assertEqual(self.window.catalog.spectra, ())
            self.assertEqual(self.window.tree.topLevelItemCount(), 0)
            self.assertEqual(maps.point_count, 0)
            self.assertTrue(all(path.read_bytes() == b"original SME bytes" for path in paths))

    def test_views_menu_allows_multiple_checks_without_closing(self):
        menu = self.window.views_menu
        menu.popup(self.window.mapToGlobal(self.window.rect().center()))
        APP.processEvents()
        for key in ("N", "C"):
            action = self.window.view_actions[key]
            QTest.mouseClick(menu, Qt.MouseButton.LeftButton,
                             pos=menu.actionGeometry(action).center())
            self.assertFalse(action.isChecked())
            self.assertTrue(menu.isVisible())
        menu.close()

    def test_legend_sections_follow_view_choices_and_reclaim_the_space(self):
        self.window.check_all_spectra()
        self.window.show()
        APP.processEvents()
        for key in ("N", "C"):
            self.window.view_actions[key].setChecked(False)
        self.assertTrue(self.window.legends["NCS"].isVisible())
        self.window.view_actions["S"].setChecked(False)
        self.assertFalse(self.window.legends["NCS"].isVisible())
        self.assertTrue(self.window.legends["Mueller"].isVisible())
        for key, section in (("psi_delta", "Psi Delta"), ("reflectance", "Reflectance"),
                             ("mueller", "Mueller")):
            self.window.view_actions[key].setChecked(False)
            self.assertFalse(self.window.legends[section].isVisible())
        self.window.view_actions["S"].setChecked(True)
        APP.processEvents()
        self.assertTrue(self.window.legends["NCS"].isVisible())
        self.assertGreater(self.window.legends["NCS"].width(), self.window.tree.width() / 2)

    def test_tree_ctrl_and_shift_selection_can_check_and_uncheck_only_selected_spectra(self):
        spectra = tuple(make_spectrum(index) for index in range(1, 5))
        self.window.apply_load_result(LoadResult(spectra, ()), replace=True)
        self.window.unfold_tree()
        self.window.show()
        for _ in range(5):
            APP.processEvents()
        tree = self.window.tree

        def click(index, modifiers=Qt.KeyboardModifier.NoModifier):
            item = self.window.spectrum_items[spectra[index].key]
            rect = tree.visualItemRect(item)
            QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, modifiers,
                             pos=QPoint(min(180, tree.viewport().width() - 6), rect.center().y()))
            APP.processEvents()

        click(0)
        click(2, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual({item.data(0, ROLE_KEY) for item in tree.selectedItems()},
                         {spectra[0].key, spectra[2].key})
        menu = self.window.build_tree_menu()
        actions = {action.text(): action for action in menu.actions()}
        actions["Check Selected"].trigger()
        self.assertEqual({s.key for s in self.window.checked_spectra()},
                         {spectra[0].key, spectra[2].key})
        actions["Uncheck Selected"].trigger()
        self.assertEqual(self.window.checked_spectra(), ())
        self.assertEqual(len(tree.selectedItems()), 2)
        click(0)
        click(2, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual({item.data(0, ROLE_KEY) for item in tree.selectedItems()},
                         {s.key for s in spectra[:3]})
        self.window.check_selected_spectra()
        self.assertEqual({s.key for s in self.window.checked_spectra()},
                         {s.key for s in spectra[:3]})

    def test_map_ctrl_selection_across_wafers_and_context_check_actions_sync_tree(self):
        spectra = tuple(make_spectrum(1, wafer=f"W{index}") for index in range(1, 4))
        self.window.apply_load_result(LoadResult(spectra, ()), replace=True)
        self.window.check_all_spectra()
        mapping = self.window.open_wafer_map()
        mapping.resize(1600, 850)
        for _ in range(10):
            APP.processEvents()

        def click(wafer, modifiers=Qt.KeyboardModifier.NoModifier):
            plot = mapping.wafer_plots[(wafer, "L1", "P1")].plot
            position = plot.getPlotItem().vb.mapViewToScene(QPointF(1, 0))
            QTest.mouseClick(plot.viewport(), Qt.MouseButton.LeftButton, modifiers,
                             pos=plot.mapFromScene(position))
            APP.processEvents()

        click("W1")
        click("W2", Qt.KeyboardModifier.ControlModifier)
        self.assertEqual({item.data(0, ROLE_KEY) for item in self.window.tree.selectedItems()},
                         {s.key for s in spectra[:2]})
        self.assertEqual(sum(len(plot.selection.data) for plot in mapping.wafer_plots.values()), 2)
        click("W1", Qt.KeyboardModifier.ControlModifier)
        self.assertEqual({item.data(0, ROLE_KEY) for item in self.window.tree.selectedItems()},
                         {spectra[1].key})
        click("W1", Qt.KeyboardModifier.ShiftModifier)
        menu = mapping.build_selection_menu()
        actions = {action.text(): action for action in menu.actions()}
        actions["Uncheck Selected"].trigger()
        APP.processEvents()
        self.assertEqual({s.key for s in self.window.checked_spectra()}, {spectra[2].key})
        self.assertEqual(mapping.point_count, 3)
        actions["Check Selected"].trigger()
        APP.processEvents()
        self.assertEqual({s.key for s in self.window.checked_spectra()}, {s.key for s in spectra})
        self.assertEqual(mapping.point_count, 3)

    def test_selected_collapsed_wafer_checks_all_its_spectra_without_checking_others(self):
        other = make_spectrum(1, wafer="W2")
        self.window.apply_load_result(LoadResult((*self.spectra, other), ()), replace=True)
        wafer = self.window.tree.topLevelItem(0)
        wafer.setSelected(True)
        self.window.check_selected_spectra()
        self.assertEqual({s.key for s in self.window.checked_spectra()}, {s.key for s in self.spectra})
        self.assertEqual(wafer.checkState(0), Qt.CheckState.Checked)
        self.assertEqual(self.window.tree.topLevelItem(1).checkState(0), Qt.CheckState.Unchecked)
        self.assertEqual(wafer.child(0).child(0).childCount(), 0)
        self.window.uncheck_selected_spectra()
        self.assertEqual(self.window.checked_spectra(), ())

    def test_ctrl_curve_clicks_add_and_remove_spectra_from_the_selection(self):
        first, second = make_spectrum(1), make_spectrum(2)
        numeric = second.channels[0].numeric.copy()
        numeric[:, 3] *= -1
        second = replace(second, channels=(replace(second.channels[0], numeric=numeric),))
        self.window.apply_load_result(LoadResult((first, second), ()), replace=True)
        self.window.check_all_spectra()
        self.window.show()
        APP.processEvents()
        panel = self.window.plot_panels["N"]

        def click(y, modifiers=Qt.KeyboardModifier.NoModifier):
            position = panel.plot.getPlotItem().vb.mapViewToScene(QPointF(300, y))
            QTest.mouseClick(panel.plot.viewport(), Qt.MouseButton.LeftButton, modifiers,
                             pos=panel.plot.mapFromScene(position))
            APP.processEvents()

        click(0.2)
        click(-0.2, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(panel.selected_keys, {first.key, second.key})
        click(0.2, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(panel.selected_keys, {second.key})

    def test_legends_are_grouped_by_plot_family_and_scroll_with_the_wheel(self):
        spectrum = make_spectrum(1)
        channels = tuple(replace(spectrum.channels[0], metadata={
            **spectrum.channels[0].metadata, "channel_id": index,
        }) for index in range(1, 21))
        mueller = replace(spectrum, channels=channels)
        imse = make_spectrum(2)
        imse = replace(imse, channels=(replace(imse.channels[0], spectrum_type="ellipsometry",
                       metadata={**imse.channels[0].metadata, "instrument": "IMSE"}),))
        dts = make_spectrum(3)
        dts = replace(dts, channels=(replace(dts.channels[0], spectrum_type="reflectance",
                      metadata={**dts.channels[0].metadata, "instrument": "DTS"}),))
        self.window.apply_load_result(LoadResult((mueller, imse, dts), ()), replace=True)
        self.window.check_all_spectra()
        self.window.show()
        APP.processEvents()
        self.assertEqual({name: legend.count() for name, legend in self.window.legends.items()},
                         {"NCS": 21, "Psi Delta": 21, "Mueller": 20, "Reflectance": 1})
        legend = self.window.legends["NCS"]
        self.assertGreater(legend.verticalScrollBar().maximum(), 0)
        position = QPointF(legend.viewport().rect().center())
        wheel = QWheelEvent(position, QPointF(legend.viewport().mapToGlobal(position.toPoint())),
                            QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        APP.sendEvent(legend.viewport(), wheel)
        self.assertGreater(legend.verticalScrollBar().value(), 0)

    def test_curve_and_blank_clicks_sync_selection_with_map_and_floating_plot(self):
        spectrum = make_spectrum(1)
        numeric = spectrum.channels[0].numeric.copy()
        numeric[:, 3] = [0.1, 0.9, 0.2]
        channel = replace(spectrum.channels[0], numeric=numeric)
        spectrum = replace(spectrum, channels=(channel,))
        self.window.apply_load_result(LoadResult((spectrum,), ()), replace=True)
        self.window.check_all_spectra()
        self.window.show()
        map_window = self.window.open_wafer_map()
        panel = self.window.plot_panels["N"]
        floating = self.window.open_plot_window(panel)
        for _ in range(5):
            APP.processEvents()

        def click(plot, x, y):
            scene = plot.getPlotItem().vb.mapViewToScene(QPointF(x, y))
            QTest.mouseClick(plot.viewport(), Qt.MouseButton.LeftButton,
                             pos=plot.mapFromScene(scene))
            APP.processEvents()

        # Select halfway along a segment, rather than only at a sample vertex.
        click(floating.panel.plot, 250, 0.5)
        self.assertEqual(panel.selected_keys, {spectrum.key})
        self.assertTrue(self.window.spectrum_items[spectrum.key].isSelected())
        self.assertEqual(len(self.window.legends["NCS"].selectedItems()), 1)
        self.assertTrue(self.window.legends["NCS"].selectedItems()[0].font().bold())
        wafer_plot = next(iter(map_window.wafer_plots.values()))
        self.assertEqual(len(wafer_plot.selection.data), 1)
        click(panel.plot, 300, 0.15)
        self.assertEqual(panel.selected_keys, set())
        self.assertEqual(floating.panel.selected_keys, set())
        self.assertEqual(self.window.tree.selectedItems(), [])
        self.assertEqual(len(wafer_plot.selection.data), 0)
        self.assertTrue(all(not legend.selectedItems() for legend in self.window.legends.values()))

    def test_blank_map_and_main_plot_background_clear_the_linked_selection(self):
        self.window.resize(1800, 1000)
        self.window.check_all_spectra()
        self.window.show()
        maps = self.window.open_wafer_map()
        panel = self.window.mueller_panel.mij_plots["M00"]
        floating = self.window.open_plot_window(panel)
        for _ in range(5):
            APP.processEvents()
        wafer = next(iter(maps.wafer_plots.values()))
        checked = self.window.checked_spectra()
        main_frame = self.window.plot_panel_layout.parentWidget()

        def click_view(plot, point):
            scene = plot.getPlotItem().vb.mapViewToScene(point)
            QTest.mouseClick(plot.viewport(), Qt.MouseButton.LeftButton,
                             pos=plot.mapFromScene(scene))

        # Point clicks must select rather than immediately count as blank clicks.
        spectrum = self.spectra[0]
        click_view(wafer.plot, QPointF(spectrum.x_mm, spectrum.y_mm))
        APP.processEvents()
        self.assertEqual(panel.selected_keys, {spectrum.key})

        for area in ("wafer", "wafer_margin", "mueller", "main_margin", "floating_margin"):
            with self.subTest(area=area):
                self.window.select_spectrum_keys({s.key for s in self.spectra})
                ranges = panel.plot.getPlotItem().vb.viewRange()
                if area == "wafer":
                    click_view(wafer.plot, QPointF(0, -30))
                elif area == "wafer_margin":
                    QTest.mouseClick(maps.centralWidget(), Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
                elif area == "mueller":
                    (left, right), (bottom, top) = ranges
                    click_view(panel.plot, QPointF(left + (right - left) * .1,
                                                   bottom + (top - bottom) * .9))
                elif area == "main_margin":
                    QTest.mouseClick(main_frame, Qt.MouseButton.LeftButton,
                                     pos=QPoint(2, main_frame.height() // 2))
                else:
                    QTest.mouseClick(floating.panel.plot.viewport(), Qt.MouseButton.LeftButton,
                                     pos=QPoint(1, 1))
                APP.processEvents()
                self.assertEqual(panel.selected_keys, set())
                self.assertEqual(floating.panel.selected_keys, set())
                self.assertEqual(self.window.tree.selectedItems(), [])
                self.assertEqual(len(wafer.selection.data), 0)
                self.assertEqual(self.window.checked_spectra(), checked)
                self.assertEqual(panel.plot.getPlotItem().vb.viewRange(), ranges)

    def test_plot_background_is_white_and_x_limits_are_tight_after_auto_range(self):
        self.window.check_all_spectra()
        self.window.show()
        APP.processEvents()
        for panel in (*self.window.plot_panels.values(),
                      *self.window.mueller_panel.mij_plots.values()):
            self.assertEqual(panel.plot.backgroundBrush().color().name(), "#ffffff")
        panel = self.window.plot_panels["N"]
        self.assertEqual(panel.plot.getPlotItem().vb.viewRange()[0], [200.0, 400.0])
        panel.plot.setXRange(250, 300, padding=0)
        floating = self.window.open_plot_window(panel)
        self.window.select_spectrum_keys({self.spectra[0].key})
        self.assertEqual(panel.plot.getPlotItem().vb.viewRange()[0], [250.0, 300.0])
        panel.plot.getPlotItem().autoBtn.clicked.emit(None)
        APP.processEvents()
        self.assertEqual(panel.plot.getPlotItem().vb.viewRange()[0], [200.0, 400.0])
        self.assertEqual(floating.panel.plot.backgroundBrush().color().name(), "#ffffff")

    def test_unchanged_selection_and_added_duplicates_keep_existing_plot_zoom(self):
        self.window.check_all_spectra()
        self.window.show()
        APP.processEvents()
        panel = self.window.plot_panels["S"]
        panel.plot.setXRange(250, 300, padding=0)
        self.window.check_all_spectra()
        self.assertEqual(panel.plot.getPlotItem().vb.viewRange()[0], [250, 300])
        self.window.view_actions["N"].setChecked(False)
        self.assertEqual(panel.plot.getPlotItem().vb.viewRange()[0], [250, 300])
        self.window.apply_load_result(LoadResult(self.spectra, ()), replace=False)
        self.assertEqual(panel.plot.getPlotItem().vb.viewRange()[0], [250, 300])

    def test_highlighting_spectra_does_not_change_axis_ranges(self):
        self.window.check_all_spectra()
        self.window.show()
        APP.processEvents()
        panel = self.window.plot_panels["S"]
        before = panel.plot.getPlotItem().vb.viewRange()
        self.window.select_spectrum_keys({s.key for s in self.spectra})
        APP.processEvents()
        self.assertEqual(panel.plot.getPlotItem().vb.viewRange(), before)

    def test_check_changes_reuse_other_wafer_curves_and_preserve_manual_axes(self):
        other = make_spectrum(1, wafer="W2")
        self.window.apply_load_result(LoadResult((*self.spectra, other), ()), replace=True)
        self.window.check_all_spectra()
        panel = self.window.plot_panels["S"]
        floating = self.window.open_plot_window(panel)
        dual = self.window.plot_panels["psi_delta"]
        dual.secondary.setYRange(25, 35, padding=0)
        for target in (panel, floating.panel):
            target.plot.setXRange(250, 350, padding=0)
            target.plot.setYRange(.72, .85, padding=0)
        unaffected = panel.plot.listDataItems()[1]
        floating_unaffected = floating.panel.plot.listDataItems()[1]
        self.window.select_spectrum_keys({self.spectra[0].key})
        self.window.uncheck_selected_spectra()
        self.assertEqual(dual.secondary.viewRange()[1], [25, 35])
        self.assertIn(unaffected, panel.plot.listDataItems())
        self.assertIn(floating_unaffected, floating.panel.plot.listDataItems())
        self.assertEqual({s.spectrum_key for g in panel.groups for s in g.segments},
                         {self.spectra[1].key, other.key})
        for target in (panel, floating.panel):
            self.assertEqual(target.plot.getViewBox().viewRange(), [[250, 350], [.72, .85]])

    def test_incremental_changes_recompute_enabled_auto_axes_from_visible_data(self):
        other = make_spectrum(1, wafer="W2")
        numeric = other.channels[0].numeric.copy()
        numeric[:, 0] = [500, 600, 700]
        numeric[:, 5] = [10, 20, 30]
        other = replace(other, channels=(replace(other.channels[0], wavelength=numeric[:, 0], numeric=numeric),))
        self.window.apply_load_result(LoadResult((*self.spectra, other), ()), replace=True)
        self.window.check_all_spectra()
        self.window.show()
        QTest.qWait(30)
        panel = self.window.plot_panels["S"]
        self.assertEqual(panel.plot.getViewBox().viewRange()[0], [200, 700])
        key = self.window.legends["NCS"].item(1).data(Qt.ItemDataRole.UserRole)
        self.window.toggle_channel(key)
        QTest.qWait(30)
        self.assertEqual(panel.plot.getViewBox().viewRange()[0], [200, 400])
        self.assertLess(panel.plot.getViewBox().viewRange()[1][1], 2)
        self.window.toggle_channel(key)
        QTest.qWait(30)
        self.assertEqual(panel.plot.getViewBox().viewRange()[0], [200, 700])
        self.assertGreater(panel.plot.getViewBox().viewRange()[1][1], 30)

    def test_dense_spectrum_background_render_matches_native_pixels_after_resize(self):
        self.window.check_all_spectra()
        self.window.show()
        APP.processEvents()
        panel = self.window.plot_panels["S"]
        x = np.arange(6000, dtype=float)
        y = np.sin(x / 40)
        y[1200:1300] = np.nan
        y[2200] = 5
        group = CurveGroup(self.spectra[0].channels[0].key, QColor("blue"),
                           (CurveSegment(self.spectra[0].key, x, y),))
        panel.set_curves([group], selected_keys={self.spectra[0].key})
        self.assertTrue(panel.render_pending)
        for width in (1550, 1250):
            self.window.resize(width, 850)
            panel.plot.grab()
            deadline = time.monotonic() + 20
            while panel.render_pending and time.monotonic() < deadline:
                QTest.qWait(10)
            self.assertFalse(panel.render_pending)
            cached = panel.plot.grab().toImage()
            curves = panel.plot.listDataItems()
            for curve in curves:
                curve.setCacheMode(curve.CacheMode.NoCache)
                curve.setExportMode(True, {"antialias": curve.opts["antialias"]})
            native = panel.plot.grab().toImage()
            for curve in curves:
                curve.setExportMode(False)
            self.assertEqual(cached, native)
            np.testing.assert_equal(group.segments[0].y, y)

    def test_legend_visibility_reuses_dense_curves_and_their_cached_images(self):
        for name, action in self.window.view_actions.items():
            action.setChecked(name == "S")
        spectra = []
        for wafer in ("W1", "W2"):
            source = make_spectrum(1, wafer=wafer)
            x = np.linspace(200, 900, 6000)
            numeric = np.tile(source.channels[0].numeric[0], (len(x), 1))
            numeric[:, 0] = x
            numeric[:, 5] = np.sin(x / 50)
            spectra.append(replace(source, channels=(replace(source.channels[0], wavelength=x, numeric=numeric),)))
        self.window.apply_load_result(LoadResult(tuple(spectra), ()), replace=True)
        self.window.check_all_spectra()
        self.window.show()
        self.window.select_spectrum_keys({spectra[0].key})
        panel = self.window.plot_panels["S"]
        floating = self.window.open_plot_window(panel)
        floating.show()
        for target in (panel, floating.panel):
            target.plot.setXRange(400, 600, padding=0)
            target.plot.setYRange(-1, 1, padding=0)

        def settle():
            deadline = time.monotonic() + 20
            QTest.qWait(30)
            while self.window.plot_render_pending and time.monotonic() < deadline:
                QTest.qWait(10)
            self.assertFalse(self.window.plot_render_pending)

        settle()
        curves = [target.plot.listDataItems() for target in (panel, floating.panel)]
        changes = []
        for items in curves:
            for item in items:
                item.sigPlotChanged.connect(lambda *_: changes.append(1))
        key = self.window.legends["NCS"].item(0).data(Qt.ItemDataRole.UserRole)
        self.window.toggle_channel(key)
        settle()
        for target, original in zip((panel, floating.panel), curves):
            self.assertFalse(original[0].isVisible())
            self.assertEqual(len(target.groups), 1)
            cached = target.plot.grab().toImage()
            for item in target.plot.listDataItems():
                item.setExportMode(True, {"antialias": item.opts["antialias"]})
            self.assertEqual(cached, target.plot.grab().toImage())
            for item in target.plot.listDataItems():
                item.setExportMode(False)
        self.window.toggle_channel(key)
        settle()
        for target, original in zip((panel, floating.panel), curves):
            self.assertEqual(target.plot.listDataItems(), original)
            self.assertTrue(all(item.isVisible() for item in original))
            self.assertEqual(target.plot.getViewBox().viewRange(), [[400, 600], [-1, 1]])
        self.assertEqual(changes, [])
        self.window.select_spectrum_keys(set())
        settle()
        before = [target.plot.grab().toImage() for target in (panel, floating.panel)]
        self.window.select_spectrum_keys({spectra[0].key})
        self.window.uncheck_selected_spectra()
        settle()
        self.window.check_selected_spectra()
        self.window.select_spectrum_keys(set())
        settle()
        for target, expected in zip((panel, floating.panel), before):
            self.assertEqual(target.plot.grab().toImage(), expected)

    def test_large_selection_paints_in_cancellable_steps(self):
        spectrum = make_spectrum(1)
        x = np.arange(50001, dtype=float)
        numeric = np.tile(spectrum.channels[0].numeric[0], (len(x), 1))
        numeric[:, 0] = x
        channel = replace(spectrum.channels[0], numeric=numeric, wavelength=x)
        spectrum = replace(spectrum, channels=(channel,))
        self.window.apply_load_result(LoadResult((spectrum,), ()), replace=True)
        self.window.show()
        APP.processEvents()
        self.window.check_all_spectra()
        self.assertTrue(self.window.plot_render_pending)
        APP.processEvents()
        self.window.uncheck_all_spectra()
        self.assertFalse(self.window.plot_render_pending)
        APP.processEvents()
        self.assertEqual(self.window.checked_spectra(), ())
        self.assertTrue(all(not panel.groups for panel in self.window.plot_panels.values()))
        self.window.check_all_spectra()
        deadline = time.monotonic() + 15
        turns = 0
        while self.window.plot_render_pending and time.monotonic() < deadline:
            APP.processEvents()
            turns += 1
        self.assertFalse(self.window.plot_render_pending)
        self.assertGreater(turns, 1)

    def test_rapid_dense_check_changes_keep_only_the_latest_spectra(self):
        spectra = []
        x = np.arange(50001, dtype=float)
        for source in self.spectra:
            numeric = np.tile(source.channels[0].numeric[0], (len(x), 1))
            numeric[:, 0] = x
            channel = replace(source.channels[0], numeric=numeric, wavelength=x)
            spectra.append(replace(source, channels=(channel,)))
        self.window.apply_load_result(LoadResult(tuple(spectra), ()), replace=True)
        self.window.show()
        floating = self.window.open_plot_window(self.window.plot_panels["S"])
        self.window.check_all_spectra()
        QTest.qWait(5)
        self.window.select_spectrum_keys({spectra[0].key})
        self.window.uncheck_selected_spectra()
        deadline = time.monotonic() + 20
        while self.window.plot_render_pending and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertFalse(self.window.plot_render_pending)
        self.assertEqual(self.window.checked_spectra(), (spectra[1],))
        panel = self.window.plot_panels["S"]
        self.assertEqual({segment.spectrum_key for group in panel.groups for segment in group.segments},
                         {spectra[1].key})
        self.assertEqual({segment.spectrum_key for group in floating.panel.groups for segment in group.segments},
                         {spectra[1].key})
        cached = panel.plot.grab().toImage()
        for curve in panel.plot.listDataItems():
            curve.setExportMode(True, {"antialias": curve.opts["antialias"]})
        native = panel.plot.grab().toImage()
        self.assertEqual(cached, native)

    def test_many_individual_colors_are_batched_and_match_native_rendering(self):
        self.window.check_all_spectra()
        self.window.resize(1800, 1000)
        self.window.show()
        APP.processEvents()
        panel = self.window.plot_panels["S"]
        x = np.linspace(200, 900, 400)
        groups = []
        for index in range(40):
            y = np.sin(x / (40 + index)) + index / 20
            y[80:90] = np.nan
            groups.append(CurveGroup(f"file-{index}", QColor.fromHsv(index * 9, 210, 200),
                                     (CurveSegment(f"file-{index}", x, y),)))
        panel.set_curves(groups, selected_keys={"file-1", "file-20"})
        self.assertLessEqual(len(panel.plot.listDataItems()), 17)
        for limits in ((200, 900), (350, 370)):
            panel.plot.setXRange(*limits, padding=0)
            deadline = time.monotonic() + 20
            QTest.qWait(30)
            while panel.render_pending and time.monotonic() < deadline:
                QTest.qWait(10)
            self.assertFalse(panel.render_pending)
            cached = panel.plot.grab().toImage()
            for item in panel.plot.listDataItems():
                item.setExportMode(True, {"antialias": item.opts["antialias"]})
            native = panel.plot.grab().toImage()
            a = np.frombuffer(cached.constBits().asstring(cached.sizeInBytes()), dtype=np.uint8).astype(int)
            b = np.frombuffer(native.constBits().asstring(native.sizeInBytes()), dtype=np.uint8).astype(int)
            # Five base and two highlight rasters round at separate 8-bit
            # alpha-compositing steps; retain a strict mean-error check too.
            self.assertLessEqual(np.abs(a - b).max(), 4)
            self.assertLess(np.abs(a-b).mean(), .05)
            for item in panel.plot.listDataItems():
                item.setExportMode(False)

    def test_many_color_edits_retain_unaffected_curve_batches(self):
        panel = self.window.plot_panels["S"]
        x = np.linspace(200, 900, 400)
        groups = [CurveGroup(f"file-{i}", QColor.fromHsv(i * 7 % 360, 210, 200),
                            (CurveSegment(f"file-{i}", x, np.sin(x / (40 + i))),))
                  for i in range(90)]
        panel.set_curves(groups)
        original = set(panel.plot.listDataItems())
        original_arrays = {item: item.xData for item in original}
        # A file or legend change must retain the other batches' geometry/cache.
        panel.set_curves(groups[1:])
        unchanged = original & set(panel.plot.listDataItems())
        self.assertGreater(len(unchanged), 1)
        self.assertEqual(sum(item.xData is not original_arrays[item] for item in unchanged), 1)
        panel.set_hidden_keys({"file-10"})
        self.assertEqual(set(panel.plot.listDataItems()), unchanged)
        panel.set_curves(groups, hidden_keys={"file-10"})
        self.assertEqual(set(panel.plot.listDataItems()), original)
        self.assertEqual([g.key for g in panel.groups], [g.key for g in groups if g.key != "file-10"])

    def test_spectrum_screen_curves_use_antialiasing_in_main_and_floating_plots(self):
        self.window.check_all_spectra()
        floating = self.window.open_plot_window(self.window.plot_panels["S"])
        panels = (*self.window.plot_panels.values(), *self.window.mueller_panel.mij_plots.values(), floating.panel)
        for panel in panels:
            for curve in panel.plot.listDataItems():
                self.assertTrue(curve.opts["antialias"])

    def test_dense_screen_geometry_preserves_peaks_gaps_and_full_detail_on_zoom(self):
        from scipy.ndimage import binary_dilation
        self.window.check_all_spectra()
        self.window.resize(1800, 1000)
        self.window.show()
        panel = self.window.plot_panels["S"]
        x = np.linspace(200, 900, 5001)
        y = np.sin(x / 70) + 1.5 * np.exp(-((x-410) / .4) ** 2)
        y[(x > 600) & (x < 620)] = np.nan
        groups = [CurveGroup(f"file-{i}", QColor.fromHsv(i * 9, 220, 180),
                            (CurveSegment(f"file-{i}", x, y + i * .008),)) for i in range(40)]
        original = [(g.segments[0].x.tobytes(), g.segments[0].y.tobytes()) for g in groups]
        panel.set_curves(groups)
        for limits in ((200, 900), (400, 420)):
            panel.plot.setXRange(*limits, padding=0)
            QTest.qWait(30)
            deadline = time.monotonic() + 20
            while panel.render_pending and time.monotonic() < deadline:
                QTest.qWait(5)
            self.assertFalse(panel.render_pending)
            screen = panel.plot.grab().toImage()
            for curve in panel.plot.listDataItems():
                curve.setExportMode(True, {"antialias": True})
            native = panel.plot.grab().toImage()
            def pixels(image):
                return np.frombuffer(image.constBits().asstring(image.sizeInBytes()), dtype=np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4).astype(int)
            a, b = pixels(screen), pixels(native)
            error = np.abs(a-b)
            self.assertLess(error.mean(), .6)
            mask_a = np.ptp(a[:, :, :3], axis=2) > 40
            mask_b = np.ptp(b[:, :, :3], axis=2) > 40
            self.assertFalse(np.any(mask_a & ~binary_dilation(mask_b)))
            self.assertFalse(np.any(mask_b & ~binary_dilation(mask_a)))
            if limits == (400, 420):
                self.assertLessEqual(error.max(), 4)
            for curve in panel.plot.listDataItems():
                curve.setExportMode(False)
        self.assertEqual([(g.segments[0].x.tobytes(), g.segments[0].y.tobytes()) for g in groups], original)

    def test_closing_a_dense_plot_cancels_its_background_work(self):
        self.window.check_all_spectra()
        self.window.show()
        panel = self.window.plot_panels["S"]
        x = np.arange(6000, dtype=float)
        panel.set_curves([CurveGroup(self.spectra[0].channels[0].key, QColor("blue"),
                          (CurveSegment(self.spectra[0].key, x, np.sin(x)),))])
        self.assertTrue(panel.render_pending)
        self.window.close()
        self.assertFalse(panel.render_pending)

    def test_loading_long_filename_does_not_resize_existing_plot_views(self):
        self.window.check_all_spectra()
        self.window.show()
        APP.processEvents()
        before = self.window.size()
        plot_size = self.window.plot_panels["S"].plot.viewport().size()
        self.window.progress.setVisible(True)
        self.window.cancel_load.setVisible(True)
        self.window._show_progress(1, 354, "A" * 250 + ".sme")
        for _ in range(4):
            APP.processEvents()
        self.assertEqual(self.window.size(), before)
        self.assertEqual(self.window.plot_panels["S"].plot.viewport().size(), plot_size)

    def test_wafer_channel_colours_are_distinct_stable_and_match_legends(self):
        spectra = []
        for index in range(6):
            source = make_spectrum(1, wafer=f"W{index + 1}")
            other = replace(source.channels[0], metadata={**source.channels[0].metadata,
                                                          "channel_id": 2, "angle_3_deg": 90})
            spectra.append(replace(source, channels=(*source.channels, other)))
        self.window.apply_load_result(LoadResult(tuple(spectra), ()), replace=True)
        self.window.check_all_spectra()
        panel = self.window.plot_panels["S"]
        self.assertEqual(len(panel.groups), 12)
        colors = {group.key: group.color.name() for group in panel.groups}
        self.assertEqual(len(set(colors.values())), 12)
        legend = self.window.legends["NCS"]
        for index, group in enumerate(panel.groups):
            item = legend.item(index)
            self.assertIn(group.key.wafer, item.text())
            self.assertEqual(item.icon().pixmap(24, 14).toImage().pixelColor(10, 7).name(), group.color.name())
        self.window.toggle_channel(panel.groups[0].key)
        self.assertEqual(len(panel.groups), 11)
        self.window.toggle_channel(next(iter(colors)))
        self.window.uncheck_all_spectra()
        self.window.check_all_spectra()
        self.window.group_by_combo.setCurrentIndex(1)
        self.assertEqual({group.key: group.color.name() for group in panel.groups}, colors)
        self.assertEqual(self.window.catalog.channel_count, 2)

    def test_color_by_wafer_identity_or_sme_keeps_channels_distinct_and_state_stable(self):
        spectra = []
        for source in (make_spectrum(1), make_spectrum(2), make_spectrum(1, lot="L2"), make_spectrum(1, pad="P2")):
            other = replace(source.channels[0], metadata={**source.channels[0].metadata,
                            "channel_id": 2, "angle_3_deg": 90})
            spectra.append(replace(source, channels=(*source.channels, other)))
        self.window.apply_load_result(LoadResult(tuple(spectra), ()), replace=True)
        self.window.check_all_spectra()
        combo = self.window.color_by_combo
        self.assertEqual([combo.itemText(i) for i in range(combo.count())], ["Wafer", "SME Name"])
        panel = self.window.plot_panels["S"]
        self.assertEqual(len(panel.groups), 6)
        wafer_colors = {g.key: g.color.name() for g in panel.groups}
        self.assertEqual(len(set(wafer_colors.values())), 6)
        panel.plot.setXRange(250, 350, padding=0)
        panel.plot.setYRange(.7, .9, padding=0)
        combo.setCurrentIndex(1)
        self.assertEqual(len(panel.groups), 8)
        sme_colors = {g.key: g.color.name() for g in panel.groups}
        self.assertEqual(len(set(sme_colors.values())), 8)
        self.assertEqual({g.key.spectrum_key for g in panel.groups}, {s.key for s in spectra})
        self.assertEqual(panel.plot.getViewBox().viewRange(), [[250, 350], [.7, .9]])
        legend = self.window.legends["NCS"]
        kept_legend_item = legend.item(legend.count() - 1)
        for g in panel.groups:
            self.assertEqual(len(g.segments), 1)
        self.window.select_spectrum_keys({spectra[0].key})
        self.window.uncheck_selected_spectra()
        self.window.check_selected_spectra()
        self.assertIs(legend.item(legend.count() - 1), kept_legend_item)
        self.assertEqual({g.key: g.color.name() for g in panel.groups}, sme_colors)
        combo.setCurrentIndex(0)
        self.assertEqual({g.key: g.color.name() for g in panel.groups}, wafer_colors)

    def test_ten_channel_colours_are_distinct_and_match_legend_icons_and_plots(self):
        spectrum = make_spectrum(1)
        channels = tuple(replace(spectrum.channels[0], metadata={
            **spectrum.channels[0].metadata, "channel_id": index,
        }) for index in range(1, 11))
        spectrum = replace(spectrum, channels=channels)
        self.window.apply_load_result(LoadResult((spectrum,), ()), replace=True)
        self.window.check_all_spectra()
        groups = self.window.plot_panels["N"].groups
        self.assertEqual(len({group.color.name() for group in groups}), 10)
        legend_colours = [self.window.legends["NCS"].item(index).icon().pixmap(24, 14)
                          .toImage().pixelColor(10, 7).name() for index in range(10)]
        self.assertEqual([group.color.name() for group in groups], legend_colours)
        for panel in (self.window.plot_panels["psi_delta"],
                      *self.window.mueller_panel.mij_plots.values()):
            self.assertEqual([group.color.name() for group in panel.groups], legend_colours)
        self.window.toggle_channel(groups[0].key)
        self.window.toggle_channel(groups[0].key)
        self.assertEqual([group.color.name() for group in self.window.plot_panels["N"].groups],
                         legend_colours)

    def test_three_sigma_preserves_wafer_statistics_and_restores_sme_color_choice(self):
        self.window.check_all_spectra()
        self.window.color_by_combo.setCurrentIndex(1)
        panel = self.window.plot_panels["S"]
        colors = {g.key: g.color.name() for g in panel.groups}
        self.assertEqual(len(colors), 2)
        self.window.analysis_actions["3sigma"].trigger()
        self.assertFalse(self.window.color_by_combo.isEnabled())
        self.assertEqual(self.window.color_by_combo.currentText(), "Wafer")
        self.assertEqual(len(panel.groups), 1)
        np.testing.assert_allclose(panel.groups[0].segments[0].y, [0, 0, 0])
        self.window.analysis_actions["original"].trigger()
        self.assertTrue(self.window.color_by_combo.isEnabled())
        self.assertEqual(self.window.color_by_combo.currentText(), "SME Name")
        self.assertEqual({g.key: g.color.name() for g in panel.groups}, colors)

    def test_clearing_checked_spectra_removes_curves_from_plot_data(self):
        for _ in range(3):
            self.window.check_all_spectra()
            self.window.select_spectrum_keys({self.spectra[0].key})
            self.window.uncheck_all_spectra()
        for panel in (*self.window.plot_panels.values(),
                      *self.window.mueller_panel.mij_plots.values()):
            self.assertEqual(panel.plot.getPlotItem().listDataItems(), [])

    def test_checking_one_spectrum_selects_only_that_file(self):
        wafer = self.window.tree.topLevelItem(0)
        pad = wafer.child(0).child(0)
        pad.setExpanded(True)
        die_two = pad.child(0)
        die_two.setCheckState(0, Qt.CheckState.Checked)
        APP.processEvents()

        self.assertEqual(
            [spectrum.identity.die_seq for spectrum in self.window.checked_spectra()],
            [2],
        )
        self.assertEqual(
            pad.checkState(0),
            Qt.CheckState.PartiallyChecked,
        )
        self.assertEqual(
            wafer.child(0).checkState(0),
            Qt.CheckState.PartiallyChecked,
        )
        self.assertEqual(
            wafer.checkState(0),
            Qt.CheckState.PartiallyChecked,
        )

    def test_legend_groups_channel_and_double_click_toggles_all_curves(self):
        wafer = self.window.tree.topLevelItem(0)
        pad = wafer.child(0).child(0)
        pad.setExpanded(True)
        pad.child(0).setCheckState(0, Qt.CheckState.Checked)
        pad.child(1).setCheckState(0, Qt.CheckState.Checked)
        APP.processEvents()

        self.assertEqual(self.window.legends["NCS"].count(), 1)
        legend_item = self.window.legends["NCS"].item(0)
        self.assertEqual(
            legend_item.text(),
            "W1 · L1 · P1 · UVSE_II+ · CH1 · AOI 65° · AZI 45°",
        )
        self.assertEqual(
            self.window.legends["NCS"].selectionMode(),
            QAbstractItemView.SelectionMode.NoSelection,
        )
        self.assertEqual(legend_item.sizeHint().width(), 320)
        key = legend_item.data(Qt.ItemDataRole.UserRole)
        self.assertFalse(self.window.channel_hidden(key))

        self.window._legend_double_clicked(legend_item)
        self.assertTrue(self.window.channel_hidden(key))
        self.window._legend_double_clicked(legend_item)
        self.assertFalse(self.window.channel_hidden(key))

    def test_legend_show_all_restores_its_section_without_rechecking_spectra(self):
        source = make_spectrum(1, wafer="Reflectance")
        source = replace(source, channels=(replace(source.channels[0], spectrum_type="reflectance"),))
        self.window.apply_load_result(LoadResult((*self.spectra, source), ()), replace=True)
        self.window.check_all_spectra()
        ncs = self.window.legends["NCS"].item(0).data(Qt.ItemDataRole.UserRole)
        reflectance = self.window.legends["Reflectance"].item(0).data(Qt.ItemDataRole.UserRole)
        self.window.toggle_channel(ncs)
        self.window.toggle_channel(reflectance)
        checked = self.window.checked_spectra()
        self.window.show()
        APP.processEvents()
        popup_actions = []
        def choose_show_all():
            menu = APP.activePopupWidget()
            if isinstance(menu, QMenu):
                popup_actions.extend(a.text() for a in menu.actions())
                menu.actions()[0].trigger()
                menu.close()
        QTimer.singleShot(0, choose_show_all)
        self.window.legends["NCS"].customContextMenuRequested.emit(QPoint(15, 15))
        self.assertEqual(popup_actions, ["Show All", "Hide All", "Select Channel"])
        self.assertFalse(any(b.text() == "Show All" for b in self.window.findChildren(QPushButton)))
        self.assertFalse(self.window.channel_hidden(ncs))
        self.assertTrue(self.window.channel_hidden(reflectance))
        self.assertEqual(self.window.checked_spectra(), checked)

    def test_set_as_bsl_uses_one_selected_spectrum_without_checking_it(self):
        self.window.select_spectrum_keys({self.spectra[0].key, self.spectra[1].key})
        action = next(a for a in self.window.build_tree_menu().actions() if a.text() == "Set as BSL")
        self.assertFalse(action.isEnabled())
        self.window.select_spectrum_keys({self.spectra[0].key})
        menu = self.window.build_tree_menu()
        action = next(a for a in menu.actions() if a.text() == "Set as BSL")
        self.assertTrue(action.isEnabled())
        action.trigger()
        self.assertEqual(self.window.baseline_spectrum.key, self.spectra[0].key)
        self.assertEqual(self.window.checked_spectra(), ())
        self.assertIn("W1", self.window.baseline_label.text())
        self.assertIn("Die 10", self.window.baseline_label.text())
        self.assertTrue(self.window.spectrum_items[self.spectra[0].key].font(0).bold())
        self.window.select_spectrum_keys({self.spectra[1].key})
        self.window.delete_selected_tree()
        self.assertEqual(self.window.baseline_spectrum.key, self.spectra[0].key)
        self.window.select_spectrum_keys({self.spectra[0].key})
        self.window.delete_selected_tree()
        self.assertIsNone(self.window.baseline_spectrum)
        self.assertEqual(self.window.baseline_label.text(), "BSL: —")

    def test_baseline_mode_subtracts_exact_wavelengths_and_syncs_floating_plot(self):
        baseline, source = self.spectra
        numeric = source.channels[0].numeric.copy()
        numeric[:, 0] = [250, 300, 400]
        numeric[:, 5] += [.1, -.2, .3]
        source = replace(source, channels=(replace(source.channels[0], numeric=numeric, wavelength=numeric[:, 0]),))
        self.window.apply_load_result(LoadResult((baseline, source), ()), replace=True)
        self.assertFalse(self.window.analysis_actions["residual"].isEnabled())

        self.window.select_spectrum_keys({source.key})
        self.window.check_selected_spectra()
        self.window.set_baseline(baseline.key)
        panel = self.window.plot_panels["S"]
        self.assertEqual(self.window.analysis_mode, "residual")
        self.assertNotIn(baseline, self.window.checked_spectra())
        np.testing.assert_allclose(panel.groups[0].segments[0].y, [np.nan, -.2, .3], equal_nan=True)
        floating = self.window.open_plot_window(panel)
        self.assertIn("Residual", floating.windowTitle())
        np.testing.assert_allclose(floating.panel.groups[0].segments[0].y, [np.nan, -.2, .3], equal_nan=True)
        item = panel.plot.listDataItems()[0]
        key = panel.groups[0].key
        self.window.toggle_channel(key)
        self.window.build_legend_menu("NCS").actions()[0].trigger()
        self.assertIn(item, panel.plot.listDataItems())
        self.window.analysis_actions["original"].trigger()
        np.testing.assert_allclose(panel.groups[0].segments[0].y, numeric[:, 5])
        self.assertNotIn("Residual", floating.windowTitle())
        self.window.set_baseline(baseline.key)
        self.window.select_spectrum_keys({baseline.key})
        self.window.delete_selected_tree()
        self.assertEqual(self.window.analysis_mode, "original")
        self.assertFalse(self.window.analysis_actions["residual"].isEnabled())

    def test_three_sigma_groups_checked_samples_by_wafer_and_channel_without_a_baseline(self):
        spectra = []
        for wafer, count, offset, step in (("W1", 3, 1, 2), ("W2", 2, 100, 10)):
            for die in range(count):
                source = make_spectrum(die + 1, wafer=wafer)
                numeric = source.channels[0].numeric.copy()
                numeric[:, 5] = np.array([0, 1, 2]) + offset + step * die
                ch1 = replace(source.channels[0], numeric=numeric)
                ch2_numeric = numeric.copy()
                ch2_numeric[:, 5] *= 2
                ch2 = replace(ch1, metadata={**ch1.metadata, "channel_id": 2, "angle_3_deg": 90}, numeric=ch2_numeric)
                spectra.append(replace(source, channels=(ch1, ch2)))
        self.window.apply_load_result(LoadResult(tuple(spectra), ()), replace=True)
        self.window.check_all_spectra()
        self.window.analysis_actions["3sigma"].trigger()
        panel = self.window.plot_panels["S"]
        self.assertIsNone(self.window.baseline_spectrum)
        self.assertEqual(len(panel.groups), 4)
        for group in panel.groups:
            self.assertEqual(len(group.segments), 1)
            expected = (6 if group.key.wafer == "W1" else 3 * np.sqrt(50)) * group.key.channel.channel_id
            np.testing.assert_allclose(group.segments[0].y, [expected] * 3)
        self.window.show()
        APP.processEvents()
        panel.plot.setYRange(0, 50, padding=0)
        position = panel.plot.getViewBox().mapViewToScene(QPointF(300, 6))
        QTest.mouseClick(panel.plot.viewport(), Qt.MouseButton.LeftButton,
                         pos=panel.plot.mapFromScene(position))
        self.assertEqual(panel.selected_keys, {s.key for s in spectra if s.identity.wafer == "W1"})
        unaffected = panel.plot.listDataItems()[2]
        self.window.select_spectrum_keys({spectra[0].key})
        self.window.uncheck_selected_spectra()
        self.assertIn(unaffected, panel.plot.listDataItems())
        for group in panel.groups[:2]:
            np.testing.assert_allclose(group.segments[0].y, [3 * np.sqrt(2) * group.key.channel.channel_id] * 3)

    def test_analysis_reports_insufficient_samples_and_no_common_wavelengths(self):
        self.window.select_spectrum_keys({self.spectra[0].key})
        self.window.check_selected_spectra()
        self.window.analysis_actions["3sigma"].trigger()
        self.assertEqual(self.window.plot_panels["S"].groups, [])
        self.assertIn("at least two", self.window.status.toolTip())
        source, baseline = self.spectra
        numeric = baseline.channels[0].numeric.copy()
        numeric[:, 0] += .001
        baseline = replace(baseline, channels=(replace(baseline.channels[0], numeric=numeric, wavelength=numeric[:, 0]),))
        self.window.apply_load_result(LoadResult((source, baseline), ()), replace=True)
        self.window.select_spectrum_keys({source.key})
        self.window.check_selected_spectra()
        self.window.set_baseline(baseline.key)
        self.assertEqual(self.window.plot_panels["S"].groups, [])
        self.assertIn("No exactly matching", self.window.status.toolTip())
        self.window.analysis_actions["original"].trigger()
        self.assertTrue(self.window.plot_panels["S"].groups)
        self.assertFalse(self.window.status.text().startswith("Analysis:"))

    def test_clear_bsl_exits_residual_and_keeps_checked_sources(self):
        self.window.check_all_spectra()
        self.window.select_spectrum_keys({self.spectra[0].key})
        self.window.set_baseline(self.spectra[0].key)
        checked = self.window.checked_spectra()
        self.window.select_spectrum_keys(set())
        menu = self.window.build_tree_menu()
        action = next(a for a in menu.actions() if a.text() == "Clear BSL")
        self.assertTrue(action.isEnabled())
        action.trigger()
        self.assertIsNone(self.window.baseline_spectrum)
        self.assertEqual(self.window.baseline_label.text(), "BSL: —")
        self.assertEqual(self.window.analysis_mode, "original")
        self.assertEqual(self.window.checked_spectra(), checked)
        self.assertFalse(self.window.spectrum_items[self.spectra[0].key].font(0).bold())
        self.assertFalse(self.window.analysis_actions["residual"].isEnabled())
        menu = self.window.build_tree_menu()
        self.assertFalse(next(a for a in menu.actions() if a.text() == "Clear BSL").isEnabled())

    def test_all_view_blocks_are_available_with_a_complete_mueller_grid(self):
        self.assertEqual(
            tuple(self.window.view_actions),
            ("mueller", "N", "C", "S", "psi_delta", "reflectance"),
        )
        self.assertEqual(
            sorted(self.window.mueller_panel.mij_plots),
            [f"M{row}{column}" for row in range(4) for column in range(4)],
        )
        self.window.view_actions["N"].setChecked(False)
        self.assertFalse(self.window.view_actions["N"].isChecked())
        self.assertNotIn("N", self.window.visible_view_keys())

    def test_file_and_options_menus_own_loading_and_view_actions(self):
        self.assertIsNone(self.window.findChild(QToolBar))
        self.assertIsInstance(self.window.load_spectra_action, QAction)
        self.assertIsInstance(self.window.add_spectra_action, QAction)
        self.assertEqual(
            [action.text() for action in self.window.file_menu.actions() if not action.isSeparator()],
            ["Open Spectra File…", "Save Spectra", "Save Spectra As…", "Load Spectra…", "Add Spectra…"],
        )
        self.assertEqual(self.window.options_menu.title(), "Options")
        self.assertEqual(self.window.views_menu.title(), "Views")
        self.assertEqual(
            [action.text() for action in self.window.views_menu.actions()],
            ["Mueller", "N", "C", "S", "Psi Delta", "Reflectance"],
        )
        self.assertTrue(all(
            action.isCheckable() for action in self.window.views_menu.actions()
        ))
        self.window.view_actions["N"].setChecked(False)
        self.assertNotIn("N", self.window.visible_view_keys())
        self.window.view_actions["N"].setChecked(True)
        for action in self.window.view_actions.values():
            action.setChecked(False)
        APP.processEvents()
        self.assertEqual(self.window.plot_splitter.count(), 0)
        for action in self.window.view_actions.values():
            action.setChecked(True)

    def test_tree_menu_checks_and_unchecks_every_spectrum(self):
        menu = self.window.build_tree_menu()
        actions = menu.actions()
        self.assertEqual([actions[i + 1].text() for i, a in enumerate(actions) if a.isSeparator()],
                         ["Check Selected", "Set as BSL", "Fold Tree", "Export Checked Spectra…"])
        self.assertEqual(
            [action.text() for action in menu.actions() if action.text()],
            [
                "Check All Spectra",
                "Uncheck All Spectra",
                "Check Selected",
                "Uncheck Selected",
                "Set as BSL",
                "Clear BSL",
                "Fold Tree",
                "Unfold Tree",
                "Delete Tree",
                "Export Checked Spectra…",
            ],
        )
        self.window.check_all_spectra()
        self.assertEqual(
            {spectrum.key for spectrum in self.window.checked_spectra()},
            {spectrum.key for spectrum in self.spectra},
        )
        self.window.uncheck_all_spectra()
        self.assertEqual(self.window.checked_spectra(), ())
        button_texts = {
            button.text() for button in self.window.findChildren(QPushButton)
        }
        self.assertNotIn("Fold Tree", button_texts)
        self.assertNotIn("Unfold Tree", button_texts)

    def test_fold_and_unfold_tree_buttons_change_branch_visibility(self):
        wafer = self.window.tree.topLevelItem(0)
        wafer.setExpanded(True)
        wafer.child(0).setExpanded(True)
        self.window.fold_tree()
        self.assertFalse(wafer.isExpanded())
        self.window.unfold_tree()
        deadline = time.monotonic() + 2
        while not wafer.isExpanded() and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.005)
        self.assertTrue(wafer.isExpanded())
        self.assertTrue(wafer.child(0).isExpanded())

    def test_clicking_actual_view_all_button_keeps_selection_and_highlight(self):
        self.window.apply_load_result(LoadResult((make_spectrum(2, wafer="W2"),), ()), replace=False)
        self.window.check_all_spectra()
        self.window.resize(1800, 1000)
        self.window.show()
        self.window.select_spectrum_keys({self.spectra[0].key})
        matrix = self.window.mueller_panel.mij_plots["M01"]
        floating = self.window.open_plot_window(matrix)
        for panel in (self.window.plot_panels["S"], self.window.plot_panels["psi_delta"], matrix, floating.panel):
            with self.subTest(plot=panel.title, floating=panel is floating.panel):
                colors = [group.color.name() for group in panel.groups]
                self.assertEqual(len(set(colors)), 2)
                highlights = tuple(panel._highlight_items)
                item = panel.plot.getPlotItem()
                panel.plot.setXRange(250, 350, padding=0)
                item.mouseHovering = True
                item.updateButtons()
                APP.processEvents()
                self.assertTrue(item.autoBtn.isVisible())
                position = panel.plot.mapFromScene(item.autoBtn.sceneBoundingRect().center())
                QTest.mouseClick(panel.plot.viewport(), Qt.MouseButton.LeftButton, pos=position)
                APP.processEvents()
                self.assertEqual(panel.selected_keys, {self.spectra[0].key})
                self.assertEqual({i.data(0, ROLE_KEY) for i in self.window.tree.selectedItems()}, {self.spectra[0].key})
                self.assertEqual(panel.plot.getViewBox().viewRange()[0], [200, 400])
                self.assertTrue(highlights)
                self.assertEqual(tuple(panel._highlight_items), highlights)
                self.assertEqual([group.color.name() for group in panel.groups], colors)

    def test_plot_navigation_uses_box_zoom_native_axis_menu_and_auto_button(self):
        pad = self.window.tree.topLevelItem(0).child(0).child(0)
        pad.setExpanded(True)
        pad.child(0).setCheckState(0, Qt.CheckState.Checked)
        APP.processEvents()
        panel = self.window.plot_panels["N"]
        self.assertEqual(
            panel.plot.getPlotItem().getViewBox().state["mouseMode"],
            pg.ViewBox.RectMode,
        )
        self.assertFalse(panel.plot.getPlotItem().buttonsHidden)
        self.assertEqual(
            panel.plot.contextMenuPolicy(),
            Qt.ContextMenuPolicy.DefaultContextMenu,
        )
        self.assertFalse(panel.plot.getPlotItem().menuEnabled())
        self.assertTrue(panel.plot.getPlotItem().vb.menuEnabled())
        self.assertIsNotNone(panel.plot.getPlotItem().autoBtn)
        self.assertEqual(panel.plot.getPlotItem().titleLabel.text, "N")
        self.assertEqual(panel.plot.getAxis("bottom").labelText, "Wavelength (nm)")
        self.assertEqual(panel.plot.getAxis("left").labelText, "")
        self.assertTrue(panel.plot.getAxis("top").isVisible())
        self.assertTrue(panel.plot.getAxis("right").isVisible())
        self.window.resize(1800, 1000)
        self.window.show()
        APP.processEvents()
        widths = [
            widget.plot.getPlotItem().getViewBox().sceneBoundingRect().width()
            for widget in self.window.plot_panels.values()
        ]
        self.assertLessEqual(max(widths) - min(widths), 1.0)
        panel.plot.getPlotItem().getViewBox().setRange(
            xRange=(0, 1),
            yRange=(0, 1),
        )
        panel.plot.getPlotItem().mouseHovering = True
        panel.plot.getPlotItem().updateButtons()
        APP.processEvents()
        self.assertTrue(panel.plot.getPlotItem().autoBtn.isVisible())

    def test_native_axis_menu_edits_ranges_in_matrix_and_floating_plots(self):
        self.window.resize(1800, 1000)
        self.window.show()
        self.window.check_all_spectra()
        matrix = self.window.mueller_panel.mij_plots["M00"]
        floating = self.window.open_plot_window(matrix)
        APP.processEvents()
        for panel in (matrix, floating.panel):
            view = panel.plot.getPlotItem().vb
            menu = view.getMenu(None)
            QTest.mouseClick(panel.plot.viewport(), Qt.MouseButton.RightButton,
                             pos=panel.plot.viewport().rect().center())
            APP.processEvents()
            self.assertTrue(menu.isVisible())
            actions = {action.text(): action for action in menu.actions()}
            self.assertIn("View All", actions)
            self.assertIn("Mouse Mode", actions)
            x_axis = actions["X axis"].menu()
            widget = x_axis.actions()[0].defaultWidget()
            minimum = widget.findChild(QLineEdit, "minText")
            maximum = widget.findChild(QLineEdit, "maxText")
            minimum.setText("240")
            maximum.setText("360")
            QTest.keyClick(maximum, Qt.Key.Key_Return)
            APP.processEvents()
            self.assertEqual(view.viewRange()[0], [240, 360])
            actions["View All"].trigger()
            APP.processEvents()
            self.assertEqual(view.viewRange()[0], [200, 400])
            menu.close()

    def test_plot_boundaries_are_resizable_splitters(self):
        self.assertIsInstance(self.window.plot_splitter, QSplitter)
        self.assertIsInstance(self.window.left_plot_splitter, QSplitter)
        self.assertGreater(self.window.plot_splitter.handleWidth(), 0)
        self.assertGreater(self.window.left_plot_splitter.handleWidth(), 0)
        self.assertIsInstance(self.window.mueller_panel.plot_splitter, QSplitter)

    def test_mueller_wavelength_major_labels_are_uniform_at_full_and_zoomed_ranges(self):
        axis = self.window.mueller_panel.mij_plots["M00"].plot.getAxis("bottom")
        self.assertEqual(axis.style["maxTextLevel"], 0)
        for low, high in ((163, 925), (520, 540)):
            spacing, values = axis.tickValues(low, high, 300)[0]
            labels = axis.tickStrings(values, 1, spacing)
            self.assertTrue(all(labels))
            np.testing.assert_allclose(np.diff([float(label) for label in labels]), spacing)

    def test_all_spectrum_splitters_can_collapse_and_double_click_restore_defaults(self):
        self.window.check_all_spectra()
        self.window.resize(1800, 1000)
        self.window.show()
        APP.processEvents()
        main = self.window.main_splitter
        self.assertAlmostEqual(main.sizes()[0] / sum(main.sizes()), .25, delta=.03)

        handle = main.handle(1)
        center = handle.rect().center()
        target = handle.mapFromGlobal(main.mapToGlobal(QPoint(-20, main.height() // 2)))
        QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseMove(handle, target)
        QTest.qWait(30)
        QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=target)
        APP.processEvents()
        self.assertEqual(main.sizes()[0], 0)
        QTest.mouseDClick(handle, Qt.MouseButton.LeftButton, pos=handle.rect().center())
        APP.processEvents()
        self.assertAlmostEqual(main.sizes()[0] / sum(main.sizes()), .25, delta=.03)
        splitters = (main, self.window.plot_splitter, self.window.left_plot_splitter,
                     self.window.legend_splitter, self.window.mueller_panel.plot_splitter,
                     *self.window.mueller_panel.row_splitters)
        for splitter in splitters:
            with self.subTest(splitter=splitter.objectName() or type(splitter).__name__):
                splitter.setSizes([0] + [500] * (splitter.count() - 1))
                APP.processEvents()
                self.assertEqual(splitter.sizes()[0], 0)
                handle = splitter.handle(1)
                QTest.mouseDClick(handle, Qt.MouseButton.LeftButton, pos=handle.rect().center())
                APP.processEvents()
                self.assertTrue(all(s > 0 for s in splitter.sizes()))
        self.assertAlmostEqual(main.sizes()[0] / sum(main.sizes()), .25, delta=.03)

    def test_zoom_clips_each_spectrum_without_changing_gaps_bounds_or_source_samples(self):
        self.window.check_all_spectra()
        self.window.show()
        APP.processEvents()
        panel = self.window.plot_panels["N"]
        x = np.arange(1000, dtype=float)
        y = np.sin(x / 30)
        y[450:455] = np.nan
        original_y = y.copy()
        segments = (CurveSegment(self.spectra[0].key, x, y),
                    CurveSegment(self.spectra[1].key, x, y - 10))
        panel.set_curves([CurveGroup(self.spectra[0].channels[0].key, QColor("blue"), segments)])
        APP.processEvents()
        curve = panel.plot.getPlotItem().listDataItems()[0]
        all_x, all_y = (array.copy() for array in curve.getData())
        bounds = curve.dataBounds(1)
        panel.plot.setXRange(440, 460, padding=0)
        APP.processEvents()
        clipped_x, clipped_y = curve.getData()
        self.assertLess(len(clipped_x), 70)
        self.assertEqual(np.count_nonzero(np.isnan(clipped_y)), 12)
        self.assertEqual(curve.dataBounds(1), bounds)
        for source in segments:
            values = source.y[440:461]
            self.assertTrue(np.all(np.isin(values[np.isfinite(values)], clipped_y)))
        panel.plot.getPlotItem().autoBtn.clicked.emit(None)
        APP.processEvents()
        np.testing.assert_array_equal(curve.getData()[0], all_x)
        np.testing.assert_array_equal(curve.getData()[1], all_y)
        np.testing.assert_array_equal(y, original_y)

    def test_viewport_clipping_preserves_thick_strokes_at_dense_view_edges(self):
        self.window.check_all_spectra()
        self.window.show()
        APP.processEvents()
        panel = self.window.plot_panels["N"]
        spectrum = self.spectra[0]
        x = np.linspace(0, 100, 50001)
        segment = CurveSegment(spectrum.key, x, np.sin(x * 500))
        panel.set_curves([CurveGroup(spectrum.channels[0].key, QColor("blue"), (segment,))],
                         selected_keys={spectrum.key})
        panel.plot.setXRange(50, 60, padding=0)
        frames = []
        for enabled in (False, True):
            for curve in panel.plot.getPlotItem().listDataItems():
                curve.setClipToView(enabled)
            for _ in range(3):
                APP.processEvents()
            image = panel.plot.grab().toImage()
            frames.append(bytes(image.constBits().asstring(image.sizeInBytes())))
        self.assertEqual(frames[0], frames[1])

    def test_double_click_opens_one_floating_copy_per_plot(self):
        panel = self.window.plot_panels["N"]
        self.window.show()
        APP.processEvents()
        QTest.mouseDClick(
            panel.plot.viewport(),
            Qt.MouseButton.LeftButton,
        )
        APP.processEvents()
        first = self.window.floating_plot_windows[panel]
        QTest.mouseDClick(
            panel.plot.viewport(),
            Qt.MouseButton.LeftButton,
        )
        APP.processEvents()
        self.assertIs(self.window.floating_plot_windows[panel], first)
        self.assertTrue(first.isVisible())

    def test_open_map_reuses_one_window_and_tracks_checked_spectra(self):
        wafer = self.window.tree.topLevelItem(0)
        pad = wafer.child(0).child(0)
        pad.setExpanded(True)
        pad.child(0).setCheckState(0, Qt.CheckState.Checked)
        APP.processEvents()

        first = self.window.open_wafer_map()
        self.assertIs(self.window.open_wafer_map(), first)
        self.assertEqual(first.point_count, 2)

        pad.child(1).setCheckState(0, Qt.CheckState.Checked)
        APP.processEvents()
        self.assertEqual(first.point_count, 2)

    def test_encrypted_file_rows_show_source_and_decryption_guidance(self):
        path = Path("C:/fixtures/encrypted/same.sme")
        message = "TSD encrypted file: export a decrypted SME copy from an authorized environment."
        self.window.apply_load_result(
            LoadResult(self.spectra, (LoadIssue(path, "encrypted", message),)), replace=True,
        )
        self.assertIn("1 encrypted", self.window.tree_summary.text())
        self.assertIn("decrypted SME", self.window.tree_summary.text())
        self.assertEqual(self.window.status.text(), "")
        errors = self.window.tree.topLevelItem(self.window.tree.topLevelItemCount() - 1)
        row = errors.child(0)
        self.assertEqual(row.text(1), "encrypted")
        self.assertEqual(row.text(9), str(path.parent))
        self.assertIn(str(path), row.toolTip(0))
        self.assertIn(message, row.toolTip(0))
        self.assertEqual(len(self.window.catalog.spectra), len(self.spectra))

    def test_failed_replacement_keeps_existing_spectra(self):
        original = self.window.catalog.spectra
        self.window.apply_load_result(
            LoadResult(
                (),
                (LoadIssue(Path("C:/fixtures/broken.sme"), "error", "bad payload"),),
            ),
            replace=True,
        )
        self.assertEqual(self.window.catalog.spectra, original)
        self.assertEqual(len(self.window.catalog.issues), 1)

    def test_add_spectra_merges_wafers_and_preserves_existing_checks(self):
        wafer = self.window.tree.topLevelItem(0)
        pad = wafer.child(0).child(0)
        pad.setExpanded(True)
        checked = pad.child(0)
        checked_key = checked.data(0, ROLE_KEY)
        checked.setCheckState(0, Qt.CheckState.Checked)
        APP.processEvents()

        added = make_spectrum(1, wafer="W2")
        self.window.apply_load_result(
            LoadResult((added,), ()),
            replace=False,
        )
        self.assertEqual(self.window.tree.topLevelItemCount(), 2)
        self.assertEqual(
            self.window.spectrum_items[checked_key].checkState(0),
            Qt.CheckState.Checked,
        )
        added_pad = self.window.tree.topLevelItem(1).child(0).child(0)
        added_pad.setExpanded(True)
        self.assertEqual(
            self.window.spectrum_items[added.key].checkState(0),
            Qt.CheckState.Unchecked,
        )

        self.window.apply_load_result(
            LoadResult((added,), ()),
            replace=False,
        )
        self.assertEqual(len(self.window.catalog.spectra), 3)

    def test_map_selection_highlights_the_spectrum_tree_entry(self):
        wafer = self.window.tree.topLevelItem(0)
        pad = wafer.child(0).child(0)
        pad.setExpanded(True)
        pad.child(0).setCheckState(0, Qt.CheckState.Checked)
        pad.child(1).setCheckState(0, Qt.CheckState.Checked)
        APP.processEvents()
        selected_key = self.spectra[0].key

        map_window = self.window.open_wafer_map()
        map_window.spectra_selected.emit({selected_key})
        APP.processEvents()

        selected_items = [
            item
            for item in self.window.spectrum_items.values()
            if item.isSelected()
        ]
        self.assertEqual(len(selected_items), 1)
        self.assertEqual(selected_items[0].data(0, ROLE_KEY), selected_key)

    def test_multichannel_file_is_one_tree_leaf_and_one_map_point(self):
        spectrum = make_spectrum(1)
        second_channel = replace(
            spectrum.channels[0],
            metadata={
                **spectrum.channels[0].metadata,
                "channel_id": 2,
                "angle_3_deg": 0.0,
            },
        )
        multichannel = replace(
            spectrum,
            channels=(spectrum.channels[0], second_channel),
        )
        self.window.apply_load_result(
            LoadResult((multichannel,), ()),
            replace=True,
        )
        pad = self.window.tree.topLevelItem(0).child(0).child(0)
        pad.setExpanded(True)
        self.assertEqual(pad.childCount(), 1)
        channel_count_column = next(
            index
            for index in range(self.window.tree.columnCount())
            if self.window.tree.headerItem().text(index) == "Channel Count"
        )
        self.assertEqual(pad.child(0).text(channel_count_column), "2")
        pad.child(0).setCheckState(0, Qt.CheckState.Checked)
        APP.processEvents()
        self.assertEqual(self.window.legends["NCS"].count(), 2)
        self.assertEqual(self.window.open_wafer_map().point_count, 1)

    @unittest.skipUnless(SAMPLE_ROOT.is_dir(), "supplied SME regression folder is unavailable")
    def test_loading_runs_in_a_worker_and_populates_the_real_catalog(self):
        window = SpectraViewerWindow()
        samples = tempfile.TemporaryDirectory(prefix="verified-sme-worker-")
        try:
            window.start_loading(copy_verified_samples(samples.name), replace=True)
            self.assertIsNotNone(window._loader)
            self.assertTrue(window._loader.isRunning())
            deadline = time.monotonic() + 10
            while window._loader is not None and time.monotonic() < deadline:
                APP.processEvents()
                time.sleep(0.01)
            self.assertIsNone(window._loader)
            self.assertEqual(len(window.catalog.spectra), 42)
            self.assertEqual(window.catalog.channel_count, 9)
        finally:
            window.close()
            window.deleteLater()
            APP.processEvents()
            samples.cleanup()


if __name__ == "__main__":
    unittest.main()

