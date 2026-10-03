"""Recent-workbook chooser and the launch settings of a new Match Workbook."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from .matching import MatchWorkbook
from .matching.analysis import _normalized_trend_axis_settings
from .settings import apply_theme, recent_wkb_paths
from .workspace_store import load_workspace


AXIS_MODE_LABELS = {
    "auto": "Auto (median ratio)",
    "dual": "Always two Y axes",
    "single": "Always one Y axis",
}


class _PathLabel(QLabel):
    """Keep the tail of a long folder path readable inside the list row."""

    def __init__(self, text="", parent=None, **kwargs):
        super().__init__("", parent, **kwargs)
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self._elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        metrics = QFontMetrics(self.font())
        self.setText(metrics.elidedText(
            self._full_text, Qt.TextElideMode.ElideLeft, max(0, self.width())
        ))


def saved_time_text(path):
    """The workbook's own timestamp, or blank when it cannot be read."""
    try:
        stamp = datetime.fromtimestamp(Path(path).stat().st_mtime)
    except OSError:
        return ""
    return f"{stamp:%Y-%m-%d %H:%M}"


def recent_workbook_row(path):
    """One recent workbook: name and saved time above the folder path."""
    row = QFrame(objectName="recentRow")
    layout = QVBoxLayout(row)
    layout.setContentsMargins(12, 9, 12, 9)
    layout.setSpacing(3)
    top = QHBoxLayout()
    top.setSpacing(12)
    top.addWidget(QLabel(str(Path(path).name), objectName="recentName"), 1)
    stamp = saved_time_text(path)
    if stamp:
        time_label = QLabel(stamp, objectName="recentTime")
        time_label.setToolTip(f"Last saved {stamp}")
        top.addWidget(time_label, 0, Qt.AlignmentFlag.AlignRight)
    layout.addLayout(top)
    layout.addWidget(_PathLabel(str(Path(path).parent), objectName="recentFolder"))
    # Let the list itself own the click so keyboard and mouse behave alike.
    row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return row


def analysis_settings(state=None, *, allow_empty_bias=False):
    """Normalize only launch settings, retaining older workbook axis policies."""
    state = state or {}
    match_type = state.get("match_type", "KLA")
    result_mode = state.get("result_mode", "preview")
    views = tuple(state.get("bias_views", [state.get("bias_mode", "absolute")]))
    primary = state.get("bias_mode", "absolute")
    if primary not in views and views:
        primary = views[0]
    if match_type not in ("KLA", "NOVA", "TEM") or result_mode not in ("preview", "final"):
        raise ValueError("Choose a valid Match Type and Preview or Final.")
    if (not views and not allow_empty_bias) or len(set(views)) != len(views) or any(view not in ("absolute", "percent") for view in views):
        raise ValueError("Select Bias, Bias %, or both.")
    return {"match_type": match_type, "result_mode": result_mode,
            "bias_views": [view for view in ("absolute", "percent") if view in views], "bias_mode": primary,
            "trend_axis_settings": deepcopy(_normalized_trend_axis_settings(
                state.get("trend_axis_settings"), state.get("correlation_selections", {}), result_mode))}


class WorkbookStartupDialog(QDialog):
    """Choose a document; only a new workbook asks for launch settings."""

    def __init__(self, parent=None, *, new=False):
        super().__init__(parent)
        self.setWindowTitle("Match Workbook")
        self.setMinimumWidth(560)
        self.resize(640, 510)
        self.path = None
        self.snapshot = None
        self._saved_settings = analysis_settings()
        self._setting_controls = False
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)
        root.addWidget(QLabel("Match Workbook", objectName="title"))
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self._build_choices()
        self._build_settings()
        self.error = QLabel(objectName="warning")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)
        buttons = QHBoxLayout()
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.go_back)
        buttons.addWidget(self.back_button)
        buttons.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        self.confirm_button = QPushButton("Create Workbook", objectName="primary")
        self.confirm_button.setDefault(True)
        self.confirm_button.clicked.connect(self.accept)
        buttons.addWidget(self.confirm_button)
        root.addLayout(buttons)
        apply_theme(self)
        self.go_back()
        if new:
            self.select_new()

    def _build_choices(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.new_button = QPushButton("New Workbook")
        self.open_button = QPushButton("Open Workbook…")
        for button in (self.new_button, self.open_button):
            button.setMinimumHeight(52)
            row.addWidget(button)
        self.new_button.clicked.connect(self.select_new)
        self.open_button.clicked.connect(self.choose_workbook)
        layout.addLayout(row)
        layout.addWidget(QLabel("Recent Workbooks", objectName="sectionTitle"))
        self.recent_list = QListWidget(objectName="recentWorkbooks")
        for path in recent_wkb_paths():
            if path.suffix.lower() != ".wkb" or not path.is_file():
                continue
            try:
                snapshot = load_workspace(path)
                if snapshot.workspace_type != "match_workbook" or "recovery" in snapshot.states:
                    continue
            except (OSError, ValueError):
                continue
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            row = recent_workbook_row(path)
            item.setSizeHint(row.sizeHint())
            self.recent_list.addItem(item)
            self.recent_list.setItemWidget(item, row)
        self.recent_list.itemClicked.connect(
            lambda item: self.select_workbook(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.recent_list, 1)
        if not self.recent_list.count():
            layout.addWidget(QLabel("No recent Match Workbooks", objectName="hint"))
        self.stack.addWidget(page)

    def _build_settings(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.file_label = QLabel()
        self.file_label.setWordWrap(True)
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.file_label)
        self.origin_label = QLabel(objectName="hint")
        layout.addWidget(self.origin_label)
        card = QFrame(objectName="card")
        form = QFormLayout(card)
        form.setContentsMargins(18, 16, 18, 16)
        form.setVerticalSpacing(12)
        self.match_type = QComboBox()
        self.match_type.addItems(["KLA", "NOVA", "TEM"])
        form.addRow("Match Type", self.match_type)
        bias_row = QWidget()
        bias_layout = QHBoxLayout(bias_row)
        bias_layout.setContentsMargins(0, 0, 0, 0)
        self.absolute_bias = QCheckBox("Bias")
        self.percent_bias = QCheckBox("Bias %")
        bias_layout.addWidget(self.absolute_bias)
        bias_layout.addWidget(self.percent_bias)
        bias_layout.addStretch()
        form.addRow("Show bias", bias_row)
        self.axis_mode = QComboBox()
        for mode, label in AXIS_MODE_LABELS.items():
            self.axis_mode.addItem(label, mode)
        form.addRow("Trend Y axes", self.axis_mode)
        self.axis_ratio = QDoubleSpinBox()
        self.axis_ratio.setDecimals(3)
        self.axis_ratio.setRange(1., 1_000_000.)
        self.axis_ratio.setSingleStep(.1)
        self.axis_ratio.setSuffix("×")
        form.addRow("Median ratio >", self.axis_ratio)
        help_text = QLabel("Auto: split same-unit curves above this ratio. Different units always split.", objectName="hint")
        help_text.setWordWrap(True)
        form.addRow(help_text)
        self.stage = QComboBox()
        self.stage.addItems(["Preview", "Final"])
        form.addRow("Open tab", self.stage)
        layout.addWidget(card)
        self.tem_note = QLabel("TEM: Map/Radius and Dynamic use their own independent measurements.", objectName="hint")
        self.tem_note.setWordWrap(True)
        layout.addWidget(self.tem_note)
        self.restore_button = QPushButton("Restore saved settings")
        self.restore_button.clicked.connect(lambda: self.set_settings(self._saved_settings))
        layout.addWidget(self.restore_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        for control, signal in ((self.match_type, "currentIndexChanged"), (self.axis_mode, "currentIndexChanged"),
                                (self.stage, "currentIndexChanged"), (self.axis_ratio, "valueChanged"),
                                (self.absolute_bias, "toggled"), (self.percent_bias, "toggled")):
            getattr(control, signal).connect(self._settings_changed)
        self.stack.addWidget(page)

    def go_back(self):
        self.stack.setCurrentIndex(0)
        self.back_button.hide()
        self.confirm_button.hide()
        self.error.hide()

    def select_new(self):
        self.path, self.snapshot = None, None
        self._saved_settings = analysis_settings()
        self.file_label.setText("New Workbook")
        self.restore_button.hide()
        self.confirm_button.setText("Create Workbook")
        self._show_settings()

    def choose_workbook(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Match Workbook", "", "Match Workbook (*.wkb)")
        if path:
            self.select_workbook(path)

    def select_workbook(self, path):
        """Open an existing workbook with its own settings; no confirmation."""
        if not self._read_workbook(path):
            return False
        self.accept()
        return True

    def _read_workbook(self, path):
        try:
            snapshot = load_workspace(path, expected_type="match_workbook")
            if "recovery" in snapshot.states:
                raise ValueError("Use File > Recover Workbook Draft to open a recovery file.")
            if not snapshot.states["match"].get("draft"):
                MatchWorkbook.from_snapshot(snapshot)
            settings = analysis_settings(snapshot.states["match"], allow_empty_bias=True)
        except Exception as error:
            self.error.setText(f"Cannot open Workbook: {error}")
            self.error.show()
            return False
        self.error.hide()
        self.path, self.snapshot = Path(path).resolve(), snapshot
        self._saved_settings = settings
        return True

    def _show_settings(self):
        self.stack.setCurrentIndex(1)
        self.back_button.show()
        self.confirm_button.show()
        self.set_settings(self._saved_settings)

    def set_settings(self, settings):
        self._setting_controls = True
        try:
            self.match_type.setCurrentText(settings["match_type"])
            self.absolute_bias.setChecked("absolute" in settings["bias_views"])
            self.percent_bias.setChecked("percent" in settings["bias_views"])
            self.axis_mode.setCurrentIndex(self.axis_mode.findData(settings["trend_axis_settings"]["mode"]))
            self.axis_ratio.setDecimals(max(3, len(str(settings["trend_axis_settings"]["ratio"]).partition(".")[2])))
            self.axis_ratio.setValue(settings["trend_axis_settings"]["ratio"])
            self.stage.setCurrentText(settings["result_mode"].title())
        finally:
            self._setting_controls = False
        self._settings_changed()

    def settings(self):
        views = [name for name, control in (("absolute", self.absolute_bias), ("percent", self.percent_bias))
                 if control.isChecked()]
        return analysis_settings({"match_type": self.match_type.currentText(), "bias_views": views,
                                  "bias_mode": self._saved_settings["bias_mode"],
                                  "result_mode": self.stage.currentText().lower(),
                                  "trend_axis_settings": {"mode": self.axis_mode.currentData(), "ratio": self.axis_ratio.value()}})

    def _settings_changed(self, *_):
        if self._setting_controls:
            return
        self.axis_ratio.setEnabled(self.axis_mode.currentData() == "auto")
        self.tem_note.setVisible(self.match_type.currentText() == "TEM")
        valid = self.absolute_bias.isChecked() or self.percent_bias.isChecked()
        self.confirm_button.setEnabled(valid)
        self.error.setVisible(not valid)
        self.error.setText("Select Bias, Bias %, or both." if not valid else "")
        self.origin_label.setText("New workbook settings")

    def accept(self):
        if self.path is None and (
            self.stack.currentIndex() != 1 or not self.confirm_button.isEnabled()
        ):
            return
        self.axis_ratio.interpretText()
        super().accept()
