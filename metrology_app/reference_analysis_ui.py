"""Analysis pages for the Ref measurements aligned to Raw data."""

import csv
from io import StringIO

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QListWidgetItem, QPushButton, QVBoxLayout,
)

from .appearance import fit_window_to_screen
from .correlation_window import CorrelationWindow
from .metadata_locks import is_metadata_column
from .widgets import CheckableListWidget
from .window import MainWindow as DataWorkspaceWindow


class ReferenceAnalysisPages(CorrelationWindow):
    """Embed the analysis pages with paired, derived Ref and Raw sources."""

    derived_table = True

    def __init__(self, tabs, owner):
        self.owner = owner
        self.reference_values = pd.DataFrame()
        self.reference_parameters = ()
        self._loaded_inputs = object()
        super().__init__()
        self.setParent(tabs)
        self.hide()
        self.measurement_floating_editor.owner = owner
        self.reference_floating_editor.owner = owner
        self.raw_page = self.tabs.widget(1)
        for page, title in (
            (self.reference_page, '4. Ref Data'), (self.raw_page, '5. Raw Data'),
            (self.correlation_page, '6. Correlation'), (self.sequence_page, '7. Trend'),
            (self.plot_page, '8. Ref WaferMap'), (self.radius_page, '9. Ref Radius Plot'),
        ):
            tabs.addTab(page, title)
        self.document.force_close = True
        self.document.timer.stop()

    def _change_chart_checks(self, rows, checked):
        from .match_groups import participation_source_keys

        if self._loaded_inputs is None:
            return set()
        matched = {}
        offset = 0
        for model, source in zip((self.reference_model, self.raw_model), self._loaded_inputs[:2]):
            keys = participation_source_keys(model._analysis_view())
            originals = {key: position for position, key in enumerate(participation_source_keys(source))}
            for row in rows:
                at = row - offset
                if 0 <= at < len(keys) and keys[at] in originals:
                    matched[row] = originals[keys[at]]
            offset += len(keys)
        changed = self.owner.change_analysis_rows(set(matched.values()), checked)
        return {row for row, position in matched.items() if position in changed}

    def _write_chart_flags(self, rows, value):
        raw_rows, _reference_rows = self._chart_source_rows(rows)
        super()._write_chart_flags(rows, value)
        if not raw_rows:
            return
        controls = self.display_options.controls
        controls.set_test_flags(sorted(raw_rows), value)
        if self.display_options.local_applied:
            self.display_options._context_cache = None
            self.display_options.refresh()

    def _build_reference_sheet_card(self):
        card = super()._build_reference_sheet_card()
        controls = card.layout().itemAt(0).layout()
        self.copy_reference_button = QPushButton('Copy Reference')
        self.copy_reference_button.setEnabled(False)
        self.copy_reference_button.clicked.connect(self.choose_reference_columns)
        controls.insertWidget(2, self.copy_reference_button)
        return card

    def default_reference_parameters(self, metrics):
        return [name for name in super().default_reference_parameters(metrics) if name in self.reference_parameters]

    def set_alignment_inputs(self, inputs, excluded, hide_excluded):
        changed = (excluded != getattr(self, '_participation_excluded', set())
                   or hide_excluded != getattr(self, '_hide_workbook_excluded', False))
        self._participation_excluded = excluded
        self._hide_workbook_excluded = hide_excluded
        self._workbook_selection_applies = True
        if inputs is self._loaded_inputs:
            if changed:
                self._refresh_selection_badge()
                self.update_plan()
            return
        self._loaded_inputs = inputs
        frame, raw, values, axes = inputs if inputs is not None else (pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), ())
        flag_cells = self.display_options.controls.order_model.cells
        has_flags = any(row > 0 and column == 0 and str(value).strip()
                        for (row, column), value in flag_cells.items())
        if not has_flags and len(raw):
            flag_column = next((name for name in raw
                                if ''.join(character.lower() for character in str(name)
                                           if character.isalnum()) in ('testflag', 'testflags')),
                               None)
            if flag_column is not None:
                self.display_options.controls.order_model.load(
                    pd.DataFrame({'TestFlag': raw[flag_column].fillna('').astype(str)})
                )
        source = 'Aligned Reference' if len(frame) else 'Link the wafers and plot XY Bias in Wafer Alignment.'
        self.reference_values = values
        columns = self.owner.alignment.ref.columns()
        identity = {columns.wafer, columns.lot, columns.pad, columns.field_x,
                    columns.field_y, columns.x, columns.y}
        self.reference_parameters = tuple(
            display for name, display in zip(values.columns, frame.columns[-len(values.columns):])
            if name not in identity and not is_metadata_column(name)
        )
        self.set_sources(frame, raw, None, 'Aligned', align_reference=False)
        self._refresh_selection_badge()
        for page in (self.plot_page, self.radius_page):
            for combo, column in zip((page.x_column, page.y_column), axes):
                combo.setCurrentIndex(combo.findData(column))
        self.copy_reference_button.setEnabled(bool(len(frame)))
        self.copy_reference_button.setToolTip(source)
        if not len(frame):
            self.message.setText(source)
            self.message.show()
            self.warning_banner.show()
        self.document.mark_clean()

    def _publish_plot_inputs(self, frame, selection):
        if not hasattr(self, 'sequence_page'):
            super()._publish_plot_inputs(frame, selection)
            return
        reference = self.reference_model._analysis_view()
        wafers = [key for key in selection['wafers'] if isinstance(key, tuple) and key[0] == 'Reference']
        keys = set(wafers)
        cells = {(key, metric) for key, metric in selection.get('available_cells', ()) if key in keys}
        metrics = {metric for _, metric in cells}
        ref_selection = {**selection, 'wafers': wafers, 'available_cells': cells,
                         'groups': {key: selection['groups'][key] for key in wafers},
                         'labels': {key: selection['labels'][key] for key in wafers},
                         'metrics': [metric for metric in selection['metrics'] if metric in metrics],
                         'sources': tuple(source for source in selection.get('sources', ())
                                          if source['name'] == 'Reference')}
        if self._point_edit_target is not None and isinstance(self._point_edit_target[0], tuple):
            self.correlation_page.set_point_selection(selection)
            self.sequence_page.set_point_selection(selection)
            DataWorkspaceWindow._publish_plot_inputs(self, reference, ref_selection)
            return
        super()._publish_plot_inputs(frame, selection)
        if self._point_edit_target is None:
            DataWorkspaceWindow._publish_plot_inputs(self, reference, ref_selection)
        else:
            self.plot_page.selection = ref_selection.copy()
            self.radius_page.selection = ref_selection.copy()

    def choose_reference_columns(self):
        dialog = QDialog(self.reference_page)
        dialog.setWindowTitle('Copy Reference')
        layout = QVBoxLayout(dialog)
        columns = CheckableListWidget()
        for name in self.reference_values:
            item = QListWidgetItem(name, columns)
            item.setCheckState(Qt.CheckState.Checked)
        layout.addWidget(columns)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        copy = buttons.addButton('Copy', QDialogButtonBox.ButtonRole.AcceptRole)

        def checked_columns():
            return [columns.item(row).text() for row in range(columns.count())
                    if columns.item(row).checkState() == Qt.CheckState.Checked]

        columns.itemChanged.connect(lambda: copy.setEnabled(bool(checked_columns())))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        fit_window_to_screen(dialog, (620, 490), minimum=(420, 300))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.copy_reference(checked_columns())
        dialog.deleteLater()

    def copy_reference(self, columns):
        data = self.reference_values.loc[:, columns]
        output = StringIO(newline='')
        writer = csv.writer(output, delimiter=',' if len(columns) == 1 else '\t')
        writer.writerow(data.columns)
        writer.writerows(data.itertuples(index=False, name=None))
        QApplication.clipboard().setText(output.getvalue())
