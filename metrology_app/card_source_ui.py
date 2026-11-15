"""Controls for choosing the overall Card in the active Match stage."""

import csv
import math
from io import StringIO

from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                             QDialogButtonBox, QHBoxLayout, QHeaderView,
                             QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)

from .appearance import help_title_label
from .card_source import manual_cards, mapping_key, mark2_values
from .table_clipboard import attach_copy_feedback


def _choices(combo, choices, selected):
    with QSignalBlocker(combo):
        if [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())] != choices:
            combo.clear()
            for text, value in choices:
                combo.addItem(text, value)
        combo.setCurrentIndex(next((i for i, (_, value) in enumerate(choices) if value == selected), 0))


class CardSourceControls(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Card setting", objectName="panelTitle"))
        row = QHBoxLayout()
        layout.addLayout(row)
        row.addWidget(help_title_label("Card source", "Choose how the overall Card is calculated for this stage.",
                                      role="muted"))
        self.mode = QComboBox()
        self.mode.setAccessibleName("Card source")
        for label, key in (("All matched rows", "all"), ("Group / label", "group"), ("Manual", "manual")):
            self.mode.addItem(label, key)
        self.scope = QComboBox()
        self.scope.setAccessibleName("Card fit group or label field")
        self.value = QComboBox()
        self.value.setAccessibleName("Card fit label value")
        self.edit = QPushButton("Edit coefficients…", objectName="subtle")
        self.status = QLabel(objectName="hint")
        for widget in (self.mode, self.scope, self.value, self.edit, self.status):
            row.addWidget(widget)
        row.addStretch()
        self.mode.currentIndexChanged.connect(lambda _: self._change(mode=self.mode.currentData()))
        self.scope.currentIndexChanged.connect(self._scope_changed)
        self.value.currentIndexChanged.connect(self._value_changed)
        self.edit.clicked.connect(self._edit_manual)
        for widget in (self.scope, self.value, self.edit, self.status):
            widget.hide()

        self.offset_controls = QWidget(self)
        layout.addWidget(self.offset_controls)
        offset_row = QHBoxLayout(self.offset_controls)
        offset_row.setContentsMargins(0, 0, 0, 0)
        self.offset_enabled = QCheckBox("By Mark2 Offset")
        self.offset_enabled.setToolTip("After applying the Card, center the mean Bias of each label on zero.")
        self.offset_field = QComboBox()
        self.offset_field.setAccessibleName("Mark2 offset field")
        self.view_offsets = QPushButton("View Offsets…", objectName="subtle")
        for widget in (self.offset_enabled, self.offset_field, self.view_offsets):
            offset_row.addWidget(widget)
        offset_row.addStretch()
        self.offset_enabled.toggled.connect(self._offset_changed)
        self.offset_field.currentIndexChanged.connect(self._offset_changed)
        self.view_offsets.clicked.connect(self._view_offsets)
        self.offset_controls.hide()

    def _source(self):
        return self.owner._card_sources[self.owner.result_mode.currentText().lower()]

    def _change(self, **settings):
        self.owner._card_source_changed({**self._source(), **settings})

    def _scope_changed(self, _index):
        scope = self.scope.currentData()
        self._change(scope=[*scope, ""] if scope and scope[0] == "mark2" else scope)

    def _value_changed(self, _index):
        scope = self.scope.currentData()
        if scope:
            self._change(scope=[*scope, self.value.currentData() or ""])

    def _mappings(self):
        try:
            return self.owner.selected_mappings()
        except ValueError:
            return ()

    def refresh(self):
        source = self._source()
        self.refresh_offset()
        mode = source["mode"]
        with QSignalBlocker(self.mode):
            self.mode.setCurrentIndex(self.mode.findData(mode))
        self.scope.setVisible(mode == "group")
        self.value.hide()
        self.edit.setVisible(mode == "manual")
        self.status.setVisible(mode == "manual")
        if mode == "manual":
            mappings = self._mappings()
            coefficients = manual_cards(source)
            configured = sum(mapping_key(mapping) in coefficients for mapping in mappings)
            self.edit.setEnabled(bool(mappings))
            self.status.setText(f"{configured} / {len(mappings)} configured" if mappings else "Select parameter mappings")
        if mode != "group":
            return
        plan = self.owner.group_controls.plan
        scope = source["scope"]
        choice = list(scope[:2]) if scope else None
        options = [("Select group or label", None)]
        if plan is not None:
            options.extend((f"Group · {plan.label(key)}", ["group", key]) for key in plan.plot_group_keys)
            if self.owner.workbook_type == "type2" and plan.mark2_enabled:
                options.extend((f"Mark2 · {field}", ["mark2", field]) for field in plan.state["mark2"]["columns"])
        if choice is not None and not any(data == choice for _, data in options):
            options.append((f"{choice[1]} (unavailable)", choice))
        _choices(self.scope, options, choice)
        if choice is not None and choice[0] == "mark2":
            self.value.show()
            values = [("Select value", ""), *((value, value) for value in mark2_values(plan, choice[1]))]
            selected = scope[2]
            if selected and not any(value == selected for _, value in values):
                values.append((f"{selected} (unavailable)", selected))
            _choices(self.value, values, selected)

    def refresh_offset(self):
        plan = self.owner.group_controls.plan
        source = self._source().get("mark2_offset")
        available = (self.owner.workbook_type == "type2" and source is not None
                     and plan is not None and plan.mark2_enabled and bool(plan.state["mark2"]["records"]))
        self.offset_controls.setVisible(available)
        if not available:
            return
        fields = plan.state["mark2"]["columns"]
        field = source["field"]
        with QSignalBlocker(self.offset_enabled):
            self.offset_enabled.setChecked(source["enabled"])
        _choices(self.offset_field, [("Select Mark2 field", ""), *((name, name) for name in fields)], field)
        self.offset_field.setEnabled(source["enabled"])
        result = self.owner.result
        self.view_offsets.setEnabled(source["enabled"] and field in fields and self.owner._analysis_current
                                     and result is not None and result.result_mode == "preview")
        self.view_offsets.setToolTip("Copy the calculated offset for each label and parameter. Run analysis after changing settings.")

    def _offset_changed(self):
        self._change(mark2_offset={"enabled": self.offset_enabled.isChecked(),
                                   "field": self.offset_field.currentData() or ""})

    def _view_offsets(self):
        if self.view_offsets.isEnabled():
            dialog = Mark2OffsetsDialog(self.offset_field.currentData(), self.owner.result.mark2_offset_table(), self)
            try:
                dialog.exec()
            finally:
                dialog.deleteLater()

    def _edit_manual(self):
        mappings = self._mappings()
        if mappings:
            dialog = ManualCardDialog(mappings, manual_cards(self._source()), self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._change(manual=[[*key, *pair] for key, pair in dialog.coefficients.items()])
            dialog.deleteLater()


class Mark2OffsetsDialog(QDialog):
    def __init__(self, field, offsets, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Mark2 Offsets · {field}")
        self.resize(580, 360)
        layout = QVBoxLayout(self)
        self.headers = [field, *offsets.columns]
        self.rows = [[label, *(f"{round(value, 5) or 0.:.5f}" if math.isfinite(value) else "—" for value in values)]
                     for label, *values in offsets.itertuples()]
        self.table = QTableWidget(len(self.rows), len(self.headers))
        self.table.setHorizontalHeaderLabels(self.headers)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ContiguousSelection)
        for row, values in enumerate(self.rows):
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        column_width = max(max(header.sectionSizeHint(column), self.table.sizeHintForColumn(column))
                           for column in range(self.table.columnCount()))
        header.setDefaultSectionSize(max(96, column_width))
        attach_copy_feedback(self.table)
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        copy_all = buttons.addButton("Copy All", QDialogButtonBox.ButtonRole.ActionRole)
        copy_all.clicked.connect(self._copy_all)
        layout.addWidget(buttons)

    def _copy_all(self):
        output = StringIO()
        csv.writer(output, delimiter="\t", lineterminator="\n").writerows([self.headers, *self.rows])
        QApplication.clipboard().setText(output.getvalue())


class ManualCardDialog(QDialog):
    def __init__(self, mappings, coefficients, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manual Card coefficients")
        self.resize(490, 340)
        self.keys = tuple(dict.fromkeys(mapping_key(mapping) for mapping in mappings))
        self.coefficients = coefficients.copy()
        layout = QVBoxLayout(self)
        self.table = QTableWidget(len(self.keys), 3)
        self.table.setHorizontalHeaderLabels(["Parameter", "Slope", "Intercept"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        for row, key in enumerate(self.keys):
            parameter = QTableWidgetItem(key[0])
            parameter.setFlags(parameter.flags() & ~Qt.ItemFlag.ItemIsEditable)
            parameter.setToolTip(f"Reference: {key[1]}\nRaw Data: {key[2]}")
            self.table.setItem(row, 0, parameter)
            for column, value in enumerate(coefficients.get(key, ("", "")), 1):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        coefficients = self.coefficients.copy()
        for row, key in enumerate(self.keys):
            slope, intercept = (self.table.item(row, column).text().strip() for column in (1, 2))
            if not (slope or intercept):
                coefficients.pop(key, None)
                continue
            try:
                pair = float(slope), float(intercept)
                if not all(map(math.isfinite, pair)):
                    raise ValueError
            except ValueError:
                QMessageBox.warning(self, "Invalid manual Card", f"Enter finite Slope and Intercept values for {key[0]}.")
                return
            coefficients[key] = pair
        self.coefficients = coefficients
        super().accept()
