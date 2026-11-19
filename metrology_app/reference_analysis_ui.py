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
    """Reuse the standard Data page and plot pages with one derived source."""

    derived_table = True

    def __init__(self, tabs, alignment):
        self.reference_values = pd.DataFrame()
        self.reference_parameters = ()
        self._loaded_results = None
        super().__init__()
        self.setParent(tabs)
        self.hide()
        self.alignment = alignment
        alignment.trend_page.data_point_edits = self._chart_edits
        self.measurement_floating_editor.owner = tabs.window()
        self.data_page = self.tabs.widget(1)
        controls = self.measurement_panel.layout().itemAt(0).layout()
        selection = QPushButton('Data selection…')
        selection.clicked.connect(self.open_data_selection)
        controls.insertWidget(2, selection)
        self.copy_reference_button = QPushButton('Copy Reference')
        self.copy_reference_button.setEnabled(False)
        self.copy_reference_button.clicked.connect(self.choose_reference_columns)
        controls.insertWidget(3, self.copy_reference_button)
        for page, title in (
            (self.data_page, '4. Data'), (self.correlation_page, '5. Correlation'),
            (self.sequence_page, '6. Trend'), (self.plot_page, '7. WaferMap'),
            (self.radius_page, '8. Radius Plot'),
        ):
            tabs.addTab(page, title)
        alignment.alignment_changed.connect(self.refresh_alignment)
        self.refresh_alignment()
        self.document.timer.stop()

    def _change_chart_checks(self, rows, checked):
        changed = super()._change_chart_checks(rows, checked)
        if changed:
            self.alignment.trend_page.refresh_point_checks(self.participating_positions(self._frame))
        return changed

    def default_parameters(self, metrics):
        return [name for name in super().default_parameters(metrics) if name in self.reference_parameters]

    def is_parameter_selectable(self, column, numeric):
        return numeric and column in self.reference_parameters

    def refresh_alignment(self):
        results = self.alignment.results or None
        if results is self._loaded_results:
            return
        self._loaded_results = results
        try:
            if not self.alignment.results:
                raise ValueError('Link the wafers and plot XY Bias in Wafer Alignment.')
            frame, values, axes = self.alignment.reference_data()
            source = 'Aligned Reference' if len(frame) else 'No matched rows in the linked wafers.'
        except ValueError as error:
            frame, values, axes = pd.DataFrame(), pd.DataFrame(), ()
            source = str(error)
        self.reference_values = values
        columns = self.alignment.ref.columns()
        identity = {columns.wafer, columns.lot, columns.pad, columns.field_x,
                    columns.field_y, columns.x, columns.y}
        self.reference_parameters = tuple(
            display for name, display in zip(values.columns, frame.columns[-len(values.columns):])
            if name not in identity and not is_metadata_column(name)
        )
        self.set_table(frame, 'Aligned Reference', keep_local_selection=True)
        if len(frame):
            self.alignment.trend_page.refresh_point_checks(self.participating_positions(self._frame))
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
        if self._point_edit_target is not None and isinstance(self._point_edit_target[0], tuple):
            self.correlation_page.set_point_selection(selection)
            self.sequence_page.set_point_selection(selection)
            DataWorkspaceWindow._publish_plot_inputs(self, frame, selection)
            return
        super()._publish_plot_inputs(frame, selection)
        if self._point_edit_target is None:
            DataWorkspaceWindow._publish_plot_inputs(self, frame, selection)
        else:
            self.plot_page.selection = selection.copy()
            self.radius_page.selection = selection.copy()

    def choose_reference_columns(self):
        dialog = QDialog(self.data_page)
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
