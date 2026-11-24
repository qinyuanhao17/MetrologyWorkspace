"""Analysis pages for the Ref measurements aligned to Raw data."""

import csv
from io import StringIO

import pandas as pd
from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QListWidgetItem, QPushButton, QVBoxLayout,
)

from .appearance import fit_window_to_screen
from .correlation_window import CorrelationWindow
from .metadata_locks import is_metadata_column
from .reference_alignment import aligned_raw_analysis_frame
from .widgets import CheckableListWidget
from .window import MainWindow as DataWorkspaceWindow


class ReferenceAnalysisPages(CorrelationWindow):
    """Embed the analysis pages with paired, derived Ref and Raw sources."""

    derived_table = True

    def __init__(self, tabs, owner):
        self.owner = owner
        self.reference_values = pd.DataFrame()
        self._excluded_raw_rows = frozenset()
        self.reference_parameters = ()
        self._raw_metadata = {}
        self._loaded_inputs = object()
        self._flag_source = (None, {})
        super().__init__()
        self.setParent(tabs)
        self.hide()
        self.measurement_floating_editor.owner = owner
        self.reference_floating_editor.owner = owner
        self.raw_page = self.tabs.widget(1)
        self.embedded_pages = (self.reference_page, self.raw_page, self.correlation_page,
                               self.sequence_page, self.plot_page, self.radius_page)
        self.document.force_close = True
        self.document.timer.stop()

    def _reference_follows_raw_die(self):
        return True  # Both analysis tables follow the same aligned Raw row order.

    def _measurement_frame(self, frame):
        return aligned_raw_analysis_frame(frame, self._raw_metadata)

    def participating_positions(self, frame):
        # Saved participation uses the same mapped identity as Wafer Alignment.
        if self._raw_metadata and len(frame) == self.raw_model.document_shape()[0]:
            frame = self._measurement_frame(self.raw_model._analysis_view())
        return super().participating_positions(frame)

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

    def set_alignment_inputs(self, inputs, excluded, hide_excluded, *, excluded_raw_rows=()):
        self._excluded_raw_rows = excluded_raw_rows
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
        frame, raw, values, axes, self._raw_metadata = inputs if inputs is not None else (
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), (), {},
        )
        if not raw.empty:
            self._refresh_source_flags(self._measurement_frame(raw))
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
                combo.setEnabled(False)
                combo.setToolTip("Coordinates from the paired Raw rows. Change the mapping in Wafer Alignment.")
        self.copy_reference_button.setEnabled(bool(len(frame)))
        self.copy_reference_button.setToolTip(source)
        if not len(frame):
            self.message.setText(source)
            self.message.show()
            self.warning_banner.show()
        self.document.mark_clean()

    def _refresh_source_flags(self, raw):
        from .match_groups import flag_value, normalized, row_ids

        dataset = self.owner.alignment._dataset
        previous_dataset, previous_flags = self._flag_source
        keys = list(row_ids(raw))
        column = next((name for name in raw if normalized(name) in ('testflag', 'testflags')), None)
        source_flags = [flag_value(value) for value in raw[column]] if column is not None else [''] * len(keys)
        defaults = dict(zip(keys, source_flags))
        if dataset is previous_dataset and list(previous_flags.items()) == list(defaults.items()):
            return

        options = self.display_options
        controls = options.controls
        model = controls.order_model
        applied = controls.state.get("applied", {})
        draft_flags = model.flags_frame(len(previous_flags))["TestFlag"].tolist()

        def by_identity(flags):
            # A source flag changed explicitly, so keep its new value even
            # if the previous Group table had an edit for that row.
            retained = dict(zip(previous_flags, flags)) if dataset is previous_dataset else {}
            return [retained.get(key, value) if previous_flags.get(key) == value else value
                    for key, value in defaults.items()]

        model.load(pd.DataFrame({"TestFlag": by_identity(draft_flags)}))
        if options.local_applied:
            applied["flags"] = by_identity(applied.get("flags", []))
            options.local_identities = keys
        options._context_cache = None
        self._flag_source = dataset, defaults

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

        def update_copy():
            copy.setEnabled(bool(checked_columns()))

        def set_column_checks(state):
            with QSignalBlocker(columns):
                for row in range(columns.count()):
                    columns.item(row).setCheckState(state)
            update_copy()

        actions = QHBoxLayout()
        for label, state in (('All', Qt.CheckState.Checked), ('None', Qt.CheckState.Unchecked)):
            button = QPushButton(label)
            button.setAutoDefault(False)
            button.clicked.connect(lambda _checked, state=state: set_column_checks(state))
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(buttons)
        layout.addLayout(actions)

        columns.itemChanged.connect(update_copy)
        update_copy()
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        fit_window_to_screen(dialog, (620, 490), minimum=(420, 300))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.copy_reference(checked_columns())
        dialog.deleteLater()

    def copy_reference(self, columns):
        data = self.reference_values.loc[:, columns]
        output = StringIO(newline='')
        writer = csv.writer(output, delimiter=',' if len(columns) == 1 else '\t')
        writer.writerow(data.columns)
        blank = ('',) * len(columns)
        writer.writerows(blank if row in self._excluded_raw_rows else values
                         for row, values in zip(data.index, data.itertuples(index=False, name=None)))
        QApplication.clipboard().setText(output.getvalue())
