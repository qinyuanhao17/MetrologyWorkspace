"""Desktop shell: editable data and wafer/parameter selection."""
from copy import deepcopy
from pathlib import Path

import pandas as pd
from PyQt6.QtCore import QEvent, QSignalBlocker, Qt, QTimer, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLayout, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QMenu, QScrollArea, QSpinBox, QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)
from PyQt6.QtWidgets import QApplication

from .data import inspect_table, read_table
from .diagnostics import get_logger
from .sheet import (
    DuplicateHeaderBanner, SheetModel, SheetView, clipboard_rows, column_letter,
)
from .plot_page import PlotPage
from .radius_page import RadiusPage
from .measurements import default_identity_columns, detect_measurements
from .appearance import fit_window_to_screen, help_title_label
from .settings import apply_theme, recent_wkb_paths
from .workspace_store import EXTENSIONS, WORKSPACE_FILTER, WORKSPACE_LABELS, WorkspaceSnapshot, file_revision, load_workspace
from .workspace_document import WkbDocument, analysis_state, restore_analysis_state, recovery_decision, recovery_directory


DEFAULT_UNCHECKED_PARAMETERS = {"mse", "gof", "ngof", "lbh", "regiter", "reglter", "cindex"}
LOGGER = get_logger()


def parameter_checked_by_default(name):
    normalized = "".join(character.lower() for character in str(name) if character.isalnum())
    return normalized not in DEFAULT_UNCHECKED_PARAMETERS


def label(text, role="muted"):
    widget = QLabel(text)
    widget.setObjectName(role)
    return widget


def button(text, callback, role=""):
    widget = QPushButton(text)
    widget.setObjectName(role)
    widget.clicked.connect(callback)
    return widget


class ChoiceTree(QTreeWidget):
    """Treat the full visible row as the checkbox hit area."""

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self.refresh_row_heights()

    def refresh_row_heights(self):
        """Multi-line rows follow the current font; stale hints hide them."""
        metrics = self.fontMetrics()
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            lines = max(1, len(item.text(0).splitlines()))
            item.setSizeHint(0, QSize(0, metrics.lineSpacing() * lines + 12))

    def mousePressEvent(self, event):
        self._pressed_item = self.itemAt(event.position().toPoint()) if event.button() == Qt.MouseButton.LeftButton else None
        self._pressed_state = self._pressed_item.checkState(0) if self._pressed_item else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        pressed, before = getattr(self, "_pressed_item", None), getattr(self, "_pressed_state", None)
        super().mouseReleaseEvent(event)
        if (event.button() == Qt.MouseButton.LeftButton and item is pressed
                and item is not None and item.flags() & Qt.ItemFlag.ItemIsUserCheckable
                and item.checkState(0) == before):
            state = Qt.CheckState.Unchecked if before == Qt.CheckState.Checked else Qt.CheckState.Checked
            item.setCheckState(0, state)
        self._pressed_item = None


def choices(headers):
    widget = ChoiceTree()
    widget.setColumnCount(len(headers))
    widget.setHeaderLabels(headers)
    widget.setRootIsDecorated(False)
    widget.setUniformRowHeights(True)
    widget.setAlternatingRowColors(False)
    widget.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
    widget.header().setStretchLastSection(False)
    widget.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    widget.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    return widget


class CheckMenu(QMenu):
    """Keep the popup open while toggling multiple grouping criteria."""

    def mouseReleaseEvent(self, event):
        action = self.actionAt(event.pos())
        if action and action.isCheckable():
            action.trigger()
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    selection_changed = pyqtSignal(dict)
    include_fit_quality = True
    workspace_type = "wafer_map"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Wafer Insight")
        # Prefer a large workspace, but never larger than the display lets us
        # show above the taskbar; the shell centres it again when it opens.
        fit_window_to_screen(self, (1520, 950), minimum=(1000, 680))
        apply_theme(self)
        self.model = SheetModel()
        self._frame = pd.DataFrame()
        self.measurements = []
        self._reset_selection = True
        self.parameter_cards = {}
        self._pending_selection_state = None
        self._managed_close_handler = None
        self._local_selection_excluded = set()
        self._local_view = {"filters": [], "row_bools": [], "group_bools": [], "show": "all"}
        self._workbook_selection_applies = True
        self.source_path = ""
        self.refresh_timer = QTimer(self, interval=250, singleShot=True)
        self.refresh_timer.timeout.connect(self.recognize)
        root = QWidget(objectName="appRoot")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 12, 20, 10)
        outer.setSpacing(8)
        self.tabs = QTabWidget(objectName="workspaceTabs")
        self.tabs.addTab(self.build_data_page(), "1. Data")
        self.plot_page = PlotPage()
        self.plot_page.document_scoped = True
        self.plot_page.draw_state_changed.connect(
            lambda _state: self.selection_changed.emit(self.selection_state())
        )
        self.tabs.addTab(self.plot_page, "2. Wafer Maps")
        self.radius_page = RadiusPage()
        self.radius_page.draw_state_changed.connect(
            lambda _state: self.selection_changed.emit(self.selection_state())
        )
        self.tabs.addTab(self.radius_page, "3. Radius Plot")
        self.tabs.currentChanged.connect(self.change_tab)
        outer.addWidget(self.tabs, 1)
        self.setCentralWidget(root)
        self.model.changed.connect(self.refresh_timer.start)
        self.model.undo.cleanChanged.connect(self.update_dirty)
        self.sheet.selectionModel().currentChanged.connect(self.current_cell)
        self.model.load(pd.DataFrame())
        self.recognize()
        self.document = WkbDocument(self)
        self.document.mark_clean()
        self.file_menu = self.menuBar().addMenu("File")
        self.file_menu.addAction(self.open_workspace_action)
        self.recent_workspace_menu = self.file_menu.addMenu("Open Recent")
        self.recent_workspace_menu.aboutToShow.connect(self.refresh_recent_workspaces)
        self.file_menu.addSeparator()
        self.data_menu = self.menuBar().addMenu("Data")
        self.selection_scope_group = QActionGroup(self)
        self.selection_scope_group.setExclusive(True)
        self.workbook_selection_action = QAction("Match Workbook selection", self, checkable=True)
        self.workbook_selection_action.setChecked(True)
        self.full_data_action = QAction("Full data (before selection)", self, checkable=True)
        for action in (self.workbook_selection_action, self.full_data_action):
            self.selection_scope_group.addAction(action)
            self.data_menu.addAction(action)
            action.setVisible(False)
        self.data_selection_action = QAction("Data selection…", self)
        self.data_selection_action.triggered.connect(self.open_data_selection)
        self.data_menu.addAction(self.data_selection_action)
        self.selection_scope_group.triggered.connect(lambda _action: self._selection_scope_changed())
        self.workspace_actions = []
        for text, handler, shortcut in (("Save", self.save_wkb, "Ctrl+S"),
                                        ("Save As…", self.save_wkb_as, "Ctrl+Shift+S"),
                                        ("Recover draft…", self.recover_draft, None)):
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
                action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            action.triggered.connect(handler)
            self.file_menu.addAction(action)
            self.workspace_actions.append(action)
        self.save_workspace_action, self.save_as_workspace_action, self.recover_workspace_action = self.workspace_actions
        self.ownership_label = QLabel()
        self.statusBar().addPermanentWidget(self.ownership_label)
        self.document.refresh_identity()

    @property
    def workspace_path(self):
        return self.document.path

    def workspace_snapshot(self, *, include_drafts=False):
        frames = {"input_data": self.model.document_frame()}
        if self.workspace_type == "correlation_trend":
            frames = {"raw_data": self.model.document_frame(),
                      "reference_data": self.reference_model.document_frame()
                      if hasattr(self, "reference_model") else pd.DataFrame()}
        states = {"ui": analysis_state(self)}
        if getattr(self, "_participation_excluded", None):
            states["workbook_participation"] = list(self._participation_excluded)
        states["data_selection"] = {
            "excluded": sorted(getattr(self, "_local_selection_excluded", set())),
            "follow_workbook": bool(getattr(self, "_workbook_selection_applies", True)),
            "view": deepcopy(getattr(self, "_local_view", {})),
        }
        return WorkspaceSnapshot(self.workspace_type, frames, states)

    def restore_workspace(self, snapshot):
        if snapshot.workspace_type != self.workspace_type:
            raise ValueError("This WKB belongs to a different tool.")
        excluded = snapshot.states.get("workbook_participation", [])
        if not isinstance(excluded, list) or any(not isinstance(key, str) for key in excluded):
            raise ValueError("Invalid Workbook participation state.")
        self._participation_excluded = set(excluded)
        local = snapshot.states.get("data_selection", {})
        if isinstance(local, dict):
            saved_excluded = local.get("excluded", [])
            if isinstance(saved_excluded, list) and all(isinstance(key, str) for key in saved_excluded):
                self._local_selection_excluded = set(saved_excluded)
            self._workbook_selection_applies = bool(local.get("follow_workbook", True))
            with QSignalBlocker(self.workbook_selection_action), QSignalBlocker(self.full_data_action):
                self.workbook_selection_action.setChecked(self._workbook_selection_applies)
                self.full_data_action.setChecked(not self._workbook_selection_applies)
            saved_view = local.get("view", {})
            if isinstance(saved_view, dict):
                self._local_view = {
                    "filters": deepcopy(saved_view.get("filters", [])),
                    "row_bools": deepcopy(saved_view.get("row_bools", [])),
                    "group_bools": deepcopy(saved_view.get("group_bools", [])),
                    "show": str(saved_view.get("show", "all")),
                }
        self._restore_workspace_tables(snapshot)
        restore_analysis_state(self, snapshot.states.get("ui", {}))

    def _restore_workspace_tables(self, snapshot):
        """Install source tables before restoring controls and drawn results."""
        if self.workspace_type == "correlation_trend":
            self.set_table(snapshot.frames["raw_data"], "WKB Raw Data")
            self.set_reference_table(snapshot.frames["reference_data"], "WKB Ref Data")
        else:
            frame = snapshot.frames["input_data"]
            if self.workspace_type == "dynamic":
                self.dynamic_page.set_baseline(frame)
            # WKB already contains the editable sheet, including invalid drafts.
            # Do not run import-time Dynamic inference over saved measurements.
            MainWindow.set_table(self, frame, "WKB workspace")

    @recovery_decision
    def load_workspace(self, path):
        snapshot = load_workspace(path, expected_type=self.workspace_type)
        owner = getattr(self, "_managed_owner", None)
        if owner is not None and "recovery" in snapshot.states:
            raise ValueError("Recover drafts from the owning Match Workbook, not an individual analysis window.")
        if not self.allow_replace():
            return None
        if snapshot.revision != file_revision(path):
            # Choosing Save may have replaced the same file we are opening.
            snapshot = load_workspace(path, expected_type=self.workspace_type)
        if owner is not None and "recovery" in snapshot.states:
            raise ValueError("Recover drafts from the owning Match Workbook, not an individual analysis window.")
        if "recovery" in snapshot.states:
            self.document.recover(path, snapshot)
            return snapshot
        self.restore_workspace(snapshot)
        if owner is not None:
            # Import a complete analysis into this scope, never silently detach it.
            self._use_workbook_data = False
            self._independent_data = True
            self.document.forced_dirty = True
            if self.workspace_type == "correlation_trend":
                owner._offer_second_axis_settings(self)
            self.document.refresh_identity()
            return snapshot
        self.document.path = Path(path).resolve()
        self.document.revision = snapshot.revision
        self.document.untrusted_recovery = False
        self.document.mark_clean()
        self.document.remember_recent()
        return snapshot

    def save_wkb(self):
        try:
            saved = self.document.save()
            if saved:
                owner = getattr(self, "_managed_owner", None)
                document = owner.document if owner else self.document
                warning = f" · Warning: {document.last_warning}" if document.last_warning else ""
                self.statusBar().showMessage(f"Saved: {document.path}{warning}", 8000)
            return saved
        except Exception as error:
            LOGGER.exception("Unable to save WKB workspace")
            QMessageBox.warning(self, "Cannot save WKB", str(error))
            return None

    def refresh_recent_workspaces(self):
        self.recent_workspace_menu.clear()
        for path in recent_wkb_paths():
            try:
                snapshot = load_workspace(path, expected_type=self.workspace_type)
            except (OSError, ValueError):
                continue
            if "recovery" in snapshot.states:
                continue  # Recovery drafts have their own explicit entry point.
            action = self.recent_workspace_menu.addAction(path.name)
            action.setToolTip(str(path))
            action.triggered.connect(lambda _=False, target=path: self.load_path(target))
        if not self.recent_workspace_menu.actions():
            self.recent_workspace_menu.addAction("No Recent Workspaces").setEnabled(False)

    def save_wkb_as(self):
        if getattr(self, "_managed_owner", None) is not None:
            return None
        try:
            return self.document.save(save_as=True)
        except Exception as error:
            QMessageBox.warning(self, "Cannot save WKB", str(error))
            return None

    def recover_draft(self):
        if getattr(self, "_managed_owner", None) is not None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Recover workspace draft", str(recovery_directory()), WORKSPACE_FILTER)
        if path and self.allow_replace():
            try:
                self.document.recover(path)
            except Exception as error:
                QMessageBox.warning(self, "Cannot recover draft", str(error))

    def export_standalone_copy(self, path=None):
        try:
            return self.document.export_copy(path)
        except Exception as error:
            QMessageBox.warning(self, "Cannot export standalone copy", str(error))
            return None

    def configure_workbook_owner(self, owner, scope):
        if getattr(self, "_managed_owner", None) is owner and getattr(self, "_managed_scope", None) == scope:
            self._update_workbook_data_action()
            self.document.refresh_identity()
            return
        self._managed_owner, self._managed_scope = owner, scope
        self.document.timer.stop()
        self.file_menu.removeAction(self.open_workspace_action)
        self.file_menu.removeAction(self.recent_workspace_menu.menuAction())
        self.file_menu.removeAction(self.save_as_workspace_action)
        self.save_as_workspace_action.setShortcut(QKeySequence())
        self.save_as_workspace_action.setEnabled(False)
        self.file_menu.removeAction(self.recover_workspace_action)
        self.recover_workspace_action.setEnabled(False)
        self.save_workspace_action.setText("Save Changes to Workbook")
        action = self.file_menu.addAction("Export Standalone Copy…")
        action.triggered.connect(lambda: self.export_standalone_copy())
        action = self.file_menu.addAction("Show Match Workbook")
        action.triggered.connect(lambda: (owner.show(), owner.raise_(), owner.activateWindow()))
        self.use_workbook_data_action = self.file_menu.addAction("Use Workbook Data…")
        self.use_workbook_data_action.triggered.connect(lambda: owner.reset_child_to_workbook(self))
        owner.match_type.currentTextChanged.connect(self._update_workbook_data_action)
        self._update_workbook_data_action()
        self.document.refresh_identity()

    def _update_workbook_data_action(self, *_):
        # TEM Map/Radius and Dynamic have no Workbook-derived input table.
        kind = self._managed_scope.split(".", 1)[0]
        available = kind == "correlation" or self._managed_owner._workspace_data_follows_workbook()
        self.use_workbook_data_action.setVisible(available)
        self.use_workbook_data_action.setEnabled(available)
        for action in (self.workbook_selection_action, self.full_data_action):
            action.setVisible(available)
        if available and not (self.workbook_selection_action.isChecked()
                              or self.full_data_action.isChecked()):
            self.workbook_selection_action.setChecked(True)

    def build_data_page(self):
        page = QWidget(objectName="dataPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)
        self.warning_banner = DuplicateHeaderBanner(self.model)
        self.warning_banner.renamed.connect(self._auto_rename_completed)
        self.message = self.warning_banner.message
        self.message.setText("")
        self.message.hide()
        self.auto_rename_button = self.warning_banner.button
        self.auto_rename_button.hide()
        self.warning_banner.hide()
        layout.addWidget(self.warning_banner)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.build_sheet_card())
        side = QWidget()
        right = QVBoxLayout(side)
        right.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(14)
        right.addWidget(self.build_wafer_card(), 2)
        right.addWidget(self.build_parameter_card(), 3)
        side.setMinimumWidth(340)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(side)
        scroll.setMinimumWidth(355)
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(12)
        sidebar_layout.addWidget(scroll, 1)
        splitter.addWidget(sidebar)
        splitter.setSizes([1080, 365])
        splitter.setStretchFactor(0, 1)
        splitter.setHandleWidth(16)
        layout.addWidget(splitter, 1)
        return page

    def default_parameters(self, metrics):
        """Wafer Map starts with no measurement parameter selected."""
        return []

    def is_parameter_selectable(self, column, numeric):
        """Allow specialized workspaces to keep derived numeric fields read-only."""
        return bool(numeric)

    def set_parameter_cards(self, cards):
        """Offer the Match Workbook's parameter Cards as a Data-tab option."""
        self.parameter_cards = dict(cards or {})
        check = getattr(self, "card_check", None)
        if check is None:
            return
        check.blockSignals(True)
        try:
            if not self.parameter_cards:
                check.setChecked(False)
            check.setEnabled(bool(self.parameter_cards))
        finally:
            check.blockSignals(False)

    def carded_frame(self, frame):
        """Return the frame the plots use: carded only when the box is ticked."""
        check = getattr(self, "card_check", None)
        if not self.parameter_cards or check is None or not check.isChecked():
            return frame
        carded = frame.copy()
        for name, card in self.parameter_cards.items():
            if name not in carded.columns:
                continue
            slope, intercept = card
            values = pd.to_numeric(carded[name], errors="coerce")
            carded[name] = slope * values + intercept
        return carded

    def card_toggled(self, *_args):
        """Re-derive the analysed values with or without the Cards."""
        self.recognize()

    def build_sheet_card(self):
        card = QFrame(objectName="sheetCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 15, 16, 12)
        layout.setSpacing(12)
        heading = QHBoxLayout()
        heading.addWidget(help_title_label(
            "Measurement table",
            "Row 1 = headers · Ctrl+V pastes cells.",
        ))
        heading.addStretch()
        for title, handler, shortcut in (
            ("New", self.new_table, "Ctrl+N"),
            ("Open file", self.open_file, "Ctrl+O"),
            ("Paste table", self.paste_table, "Ctrl+Shift+V"),
            ("Export CSV", self.save_table, ""),
        ):
            control = button(title, handler, "primary" if title == "Open file" else "subtle")
            control.setFixedSize(104, 34)
            control.setToolTip(shortcut)
            heading.addWidget(control)
            action = QAction(title, self)
            action.setShortcut(QKeySequence(shortcut))
            if title == "Open file":
                self.open_workspace_action = action
                action.setText("Open…")
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            action.triggered.connect(handler)
            self.addAction(action)
        self.file_label = label("Untitled", "muted")
        self.file_label.setMaximumWidth(260)
        layout.addLayout(heading)
        formula = QHBoxLayout()
        self.address = QLineEdit("A1")
        self.address.setReadOnly(True)
        self.address.setFixedWidth(62)
        self.address.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.formula = QLineEdit()
        self.formula.setPlaceholderText("")
        self.formula.editingFinished.connect(self.edit_formula)
        formula.addWidget(self.address)
        formula.addWidget(self.formula, 1)
        self.undo_button = button("Undo", self.model.undo.undo, "subtle")
        self.redo_button = button("Redo", self.model.undo.redo, "subtle")
        self.model.undo.canUndoChanged.connect(self.undo_button.setEnabled)
        self.model.undo.canRedoChanged.connect(self.redo_button.setEnabled)
        self.undo_button.setEnabled(False)
        self.redo_button.setEnabled(False)
        formula.addWidget(self.undo_button)
        formula.addWidget(self.redo_button)
        layout.addLayout(formula)
        self.sheet = SheetView(self.model)
        self.sheet.table_pasted.connect(self.mark_table_pasted)
        layout.addWidget(self.sheet, 1)
        footer = QHBoxLayout()
        footer.addWidget(self.file_label)
        # The window title and status bar already name the source; the footer
        # only reports the table size.
        self.file_label.hide()
        self.data_badge = label("0 rows × 0 columns", "hint")
        footer.addWidget(self.data_badge)
        self.selection_count = label("", "hint")
        footer.addWidget(self.selection_count)
        footer.addStretch()
        self.dirty_label = label("Saved", "hint")
        footer.addWidget(self.dirty_label)
        layout.addLayout(footer)
        return card

    def card_header(self, layout, title, subtitle, tree):
        heading = QHBoxLayout()
        heading.addWidget(help_title_label(title, subtitle))
        heading.addStretch()
        heading.addWidget(button("All", lambda: self.check_all(tree, True), "link"))
        heading.addWidget(button("None", lambda: self.check_all(tree, False), "link"))
        layout.addLayout(heading)

    def build_wafer_card(self):
        card = QFrame(objectName="panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        self.wafer_list = choices(["Wafer ID", "Records"])
        self.wafer_list.setUniformRowHeights(False)
        self.wafer_list.setHeaderHidden(True)
        self.wafer_list.setMinimumHeight(170)
        self.card_header(layout, "Wafers", "Checked metadata headers form one measurement identity.", self.wafer_list)
        self.group_picker = QPushButton("Select grouping columns", objectName="groupPicker")
        self.group_menu = CheckMenu(self.group_picker)
        self.group_picker.setMenu(self.group_menu)
        self.group_menu.aboutToShow.connect(lambda: self.group_menu.setMinimumWidth(self.group_picker.width()))
        self.group_checks = {}
        layout.addWidget(self.group_picker)
        record_row = QHBoxLayout()
        record_row.addWidget(label("Records >", "muted"))
        self.min_records = QSpinBox()
        self.min_records.setRange(0, 1_000_000)
        self.min_records.setToolTip(
            "Only measurement sets with more records than this stay usable; "
            "smaller sets are hidden and unchecked. 0 disables the filter.")
        self.min_records.valueChanged.connect(self.apply_record_filter)
        record_row.addWidget(self.min_records)
        record_row.addStretch(1)
        layout.addLayout(record_row)
        layout.addWidget(self.wafer_list, 1)
        self.wafer_list.itemChanged.connect(self.update_plan)
        self.wafer_count = label("No wafers detected", "hint")
        layout.addWidget(self.wafer_count)
        return card

    def build_parameter_card(self):
        card = QFrame(objectName="panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        self.parameter_list = choices(["Column header", "Type"])
        self.parameter_list.setMinimumHeight(190)
        self.card_header(layout, "Parameters", "Each selected parameter becomes one column.", self.parameter_list)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a column…")
        self.search.textChanged.connect(self.filter_parameters)
        search_row = QHBoxLayout()
        search_row.addWidget(self.search, 1)
        self.numeric_only = QCheckBox("Numeric")
        self.numeric_only.setChecked(True)
        self.numeric_only.toggled.connect(self.filter_parameters)
        search_row.addWidget(self.numeric_only)
        self.card_check = QCheckBox("Card")
        self.card_check.setToolTip(
            "Plot and analyse the mapped parameters with the Match Workbook "
            "Card (slope × value + intercept).\n"
            "The table keeps the values you loaded; only the plots and their "
            "statistics use the carded values.\n"
            "Available when this window was opened from a Match Workbook."
        )
        self.card_check.setEnabled(False)
        self.card_check.toggled.connect(self.card_toggled)
        search_row.addWidget(self.card_check)
        layout.addLayout(search_row)
        layout.addWidget(self.parameter_list, 1)
        self.parameter_list.itemChanged.connect(self.update_plan)
        self.parameter_count = label("No headers detected", "hint")
        layout.addWidget(self.parameter_count)
        return card

    def change_tab(self, index):
        if index in (1, 2):
            if self.refresh_timer.isActive():
                self.recognize()
            if (
                index == 1
                and self.plot_page.dirty
                and not self.plot_page.has_drawn_once
            ):
                self.plot_page.show_selector()

    @staticmethod
    def selected(tree):
        return [tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                for i in range(tree.topLevelItemCount())
                if tree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]

    def selection_state(self):
        """Return the user choices that remain meaningful across table reloads."""
        return {
            "wafers": tuple(self.selected(self.wafer_list)),
            "metrics": tuple(self.selected(self.parameter_list)),
            "map_draw": self.plot_page.draw_state(),
            "radius_draw": self.radius_page.draw_state(),
            "min_records": int(self.min_records.value()) if hasattr(self, "min_records") else 0,
        }

    @staticmethod
    def _set_checked_values(tree, values, *, keep_current_if_missing=False):
        desired = set(values)
        available = {
            tree.topLevelItem(index).data(0, Qt.ItemDataRole.UserRole)
            for index in range(tree.topLevelItemCount())
        }
        matched = desired & available
        if desired and not matched and keep_current_if_missing:
            return
        tree.blockSignals(True)
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                value = item.data(0, Qt.ItemDataRole.UserRole)
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if value in matched else Qt.CheckState.Unchecked,
                )
        tree.blockSignals(False)

    def _apply_selection_state(self, state):
        if not isinstance(state, dict):
            return
        self._set_checked_values(
            self.wafer_list,
            state.get("wafers", ()),
            keep_current_if_missing=True,
        )
        self._set_checked_values(
            self.parameter_list,
            state.get("metrics", ()),
        )

    def restore_selection(self, state):
        """Restore surviving wafer/parameter choices and refresh every plot page."""
        if isinstance(state, dict) and hasattr(self, "min_records"):
            threshold = state.get("min_records")
            if isinstance(threshold, int) and not isinstance(threshold, bool):
                with QSignalBlocker(self.min_records):
                    self.min_records.setValue(threshold)
        self._apply_selection_state(state)
        self.apply_record_filter()
        self.update_plan()
        if isinstance(state, dict):
            self.plot_page.restore_draw_state(state.get("map_draw"))
            self.radius_page.restore_draw_state(state.get("radius_draw"))

    def check_all(self, tree, checked):
        tree.blockSignals(True)
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            # A records-filtered row stays out of the drawing even when All is
            # pressed; the threshold has priority over the bulk selection.
            if checked and item.isHidden():
                continue
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        tree.blockSignals(False)
        self.update_plan()

    def group_columns(self):
        return [column for column, check in self.group_checks.items() if check.isChecked()]

    def update_group_picker(self):
        selected = [column for column, check in self.group_checks.items() if check.isChecked()]
        summary = " / ".join(selected) if selected else "Select grouping columns"
        self.group_picker.setText(summary)
        self.group_picker.setToolTip(summary + "\nChecked metadata fields form the measurement identity.")

    def set_group_columns(self, columns):
        self.group_menu.clear()
        self.group_checks = {}
        for column, checked in columns:
            action = QAction(column, self.group_menu)
            action.setCheckable(True)
            action.setChecked(checked)
            action.toggled.connect(self.change_group_columns)
            self.group_menu.addAction(action)
            self.group_checks[column] = action
        self.update_group_picker()
        self.group_picker.setEnabled(bool(columns))

    def recognize(self):
        self.refresh_timer.stop()
        reset = self._reset_selection
        previous_wafers = set(self.selected(self.wafer_list))
        previous_metrics = set(self.selected(self.parameter_list))
        previous_groups = [c for c, check in self.group_checks.items() if check.isChecked()]
        try:
            frame = self.model.frame()
            # The table keeps the loaded values; the Card option only changes
            # what the plots and their statistics are computed from.
            frame = self.carded_frame(frame)
            detected_wafer, counts, metrics = inspect_table(
                frame, include_fit_quality=self.include_fit_quality
            )
            normalize = lambda name: "".join(ch.lower() for ch in str(name) if ch.isalnum())
            excluded = {"fieldx", "fieldy", "x", "y", "xmm", "ymm", "diex", "diey",
                        "dieseq", "diesequence", "diesequenceno"}
            hints = ("wafer", "lot", "pad", "sample", "id", "name", "tool", "recipe", "group", "run", "batch")
            candidates = [c for c in frame if (c not in metrics or any(h in normalize(c) for h in hints))
                          and normalize(c) not in excluded and "path" not in c.lower()]
            if reset:
                defaults = {"waferid", "wafer", "waferno", "lotid", "lot", "lotno", "padname", "pad"}
                lot_column = next((c for c in candidates if normalize(c) in {"lotid", "lot", "lotno"}), None)
                pad_column = next((c for c in candidates if normalize(c) in {"padname", "pad"}), None)
                identity = default_identity_columns(frame, detected_wafer, lot_column, pad_column)
                if identity:
                    # One wafer ID is enough when PAD/Lot stay constant; PAD joins
                    # the identity only when it really splits the same wafer.
                    chosen_groups = [c for c in candidates if c in identity]
                else:
                    chosen_groups = [c for c in candidates if normalize(c) in defaults]
                if detected_wafer and detected_wafer not in chosen_groups:
                    chosen_groups.insert(0, detected_wafer)
            else:
                chosen_groups = [c for c in candidates if c in previous_groups]
            if reset or list(self.group_checks) != candidates:
                self.set_group_columns([(c, c in chosen_groups) for c in candidates])
            primary = next((c for c in chosen_groups if normalize(c) in {"waferid", "wafer", "waferno"}),
                           chosen_groups[0] if chosen_groups else None)
            if not primary:
                counts = {}
            elif primary != detected_wafer:
                _, counts, _ = inspect_table(frame, primary)
            self.measurements = detect_measurements(frame, primary, chosen_groups, use_die_seq=False)
            self._frame = frame
            self.warning_banner.hide()
            self.message.hide()
            self.auto_rename_button.hide()
            for tree in (self.wafer_list, self.parameter_list):
                tree.blockSignals(True)
                tree.clear()
            for measurement in self.measurements:
                item = QTreeWidgetItem([measurement.label, str(len(measurement.rows))])
                item.setSizeHint(0, QSize(0, 20 * len(measurement.label.splitlines()) + 12))
                item.setToolTip(0, measurement.detail)
                item.setToolTip(1, measurement.detail)
                item.setData(0, Qt.ItemDataRole.UserRole, measurement.key)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, len(measurement.rows))
                item.setCheckState(0, Qt.CheckState.Checked if self._reset_selection or measurement.key in previous_wafers else Qt.CheckState.Unchecked)
                self.wafer_list.addTopLevelItem(item)
            self.wafer_list.refresh_row_heights()
            defaults = self.default_parameters(metrics)
            chosen = set(defaults) if self._reset_selection else previous_metrics
            for column in frame:
                numeric = column in metrics
                item = QTreeWidgetItem([column, "NUMERIC" if numeric else "METADATA"])
                item.setData(0, Qt.ItemDataRole.UserRole, column)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, numeric)
                item.setToolTip(0, column)
                if self.is_parameter_selectable(column, numeric):
                    item.setCheckState(0, Qt.CheckState.Checked if column in chosen else Qt.CheckState.Unchecked)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                self.parameter_list.addTopLevelItem(item)
            self._reset_selection = False
            self._refresh_selection_badge()
            self.wafer_count.setText(f"{len(self.measurements)} measurement sets / {len(counts)} {primary or 'groups'} values")
            self.wafer_count.setToolTip(self.wafer_list.toolTip())
            self.parameter_count.setText(f"{len(metrics)} numeric / {len(frame.columns)} headers detected")
            if len(frame) and not chosen_groups:
                self.message.setText("Choose one or more grouping columns on the right to identify measurement sets.")
                self.message.show()
                self.warning_banner.show()
        except ValueError as error:
            self._frame = pd.DataFrame()
            self.measurements = []
            self.wafer_list.clear()
            self.parameter_list.clear()
            self.message.setText(str(error))
            self.message.show()
            self.auto_rename_button.setVisible(bool(self.model.duplicate_header_count()))
            self.warning_banner.show()
        finally:
            self.wafer_list.blockSignals(False)
            self.parameter_list.blockSignals(False)
        pending_selection = self._pending_selection_state
        self._pending_selection_state = None
        if pending_selection is not None:
            self._apply_selection_state(pending_selection)
        self.apply_record_filter()
        self.filter_parameters()
        if reset:
            for i in range(self.parameter_list.topLevelItemCount()):
                item = self.parameter_list.topLevelItem(i)
                if item.checkState(0) == Qt.CheckState.Checked:
                    self.parameter_list.scrollToItem(item, self.parameter_list.ScrollHint.PositionAtTop)
                    break
        self.update_plan()
        self.current_cell(self.sheet.currentIndex())
        self.update_dirty()

    def change_group_columns(self):
        self.update_group_picker()
        self._reset_selection = False
        self.recognize()
        self.check_all(self.wafer_list, True)

    def apply_record_filter(self, *_args):
        """Hide and uncheck measurement sets at or below the records threshold."""
        if not hasattr(self, "min_records"):
            return
        threshold = self.min_records.value()
        blocker = QSignalBlocker(self.wafer_list)
        for index in range(self.wafer_list.topLevelItemCount()):
            item = self.wafer_list.topLevelItem(index)
            records = int(item.data(0, Qt.ItemDataRole.UserRole + 1) or 0)
            hidden = records <= threshold
            item.setHidden(hidden)
            if hidden:
                item.setCheckState(0, Qt.CheckState.Unchecked)
        del blocker
        self.update_plan()

    def filter_parameters(self, *_args):
        query = self.search.text().strip().lower()
        for i in range(self.parameter_list.topLevelItemCount()):
            item = self.parameter_list.topLevelItem(i)
            numeric = item.data(0, Qt.ItemDataRole.UserRole + 1)
            item.setHidden(query not in item.text(0).lower() or (self.numeric_only.isChecked() and not numeric))

    def set_workbook_participation(self, book):
        """Update traceable exclusions without replacing a child's editable data."""
        from .match_groups import applied_state, participation_rows, participation_source_keys
        selection = applied_state(book.grouping_state)["data_selection"]
        source = book.final_match_raw if book.result_mode == "final" and book.final_match_raw is not None else book.raw
        allowed = set(participation_rows(source, selection)) if selection is not None else set(range(len(source)))
        self._participation_excluded = {key for row, key in enumerate(participation_source_keys(source)) if row not in allowed}
        if self.workspace_type != "correlation_trend" and not any(
                "".join(c.lower() for c in str(column) if c.isalnum()) in ("waferid", "cursmefilepath") for column in source):
            self._participation_excluded = set()
        if book.match_type == "TEM" and self.workspace_type != "correlation_trend":
            self._participation_excluded = set()  # TEM Map/Dynamic inputs have no paired-source provenance.
        self._refresh_selection_badge()
        self.update_plan()

    def participating_positions(self, frame):
        """Rows of this window's table that its plots may use."""
        from .match_groups import participation_source_keys
        excluded = set(getattr(self, "_local_selection_excluded", set()))
        if getattr(self, "_workbook_selection_applies", True):
            excluded |= getattr(self, "_participation_excluded", set())
        if not excluded:
            return set(range(len(frame)))
        return set(i for i, key in enumerate(participation_source_keys(frame)) if key not in excluded)

    def _refresh_selection_badge(self):
        if not hasattr(self, "selection_count"):
            return
        frame = self._frame
        if frame is None or frame.empty:
            self.data_badge.setText("0 rows × 0 columns")
            self.selection_count.setText("")
            return
        allowed = self.participating_positions(frame)
        self.data_badge.setText(f"{len(frame):,} rows × {len(frame.columns)} columns")
        self.selection_count.setText(
            f"{len(allowed):,} of {len(frame):,} rows used" if len(allowed) != len(frame) else "")

    def _selection_scope_changed(self, *_args):
        applies = self.workbook_selection_action.isChecked()
        if applies == self._workbook_selection_applies:
            self._refresh_selection_badge()
            return
        self._workbook_selection_applies = applies
        owner = getattr(self, "_managed_owner", None)
        apply_scope = getattr(owner, "apply_child_selection_scope", None) if owner else None
        if callable(apply_scope):
            apply_scope(self)
        else:
            self._refresh_selection_badge()
            self.update_plan()

    def open_data_selection(self):
        """Choose the rows of this window's table that feed its plots."""
        from .data_selection import FrameSelectionDialog
        frame = self.model.frame()
        if frame.empty:
            return
        owner = getattr(self, "_managed_owner", None)
        context = getattr(owner, "child_selection_context", None) if owner is not None else None
        extra_frames = context(self) if callable(context) else []
        saved_view = getattr(self, "_local_view", {}) or {}
        dialog = FrameSelectionDialog(frame, getattr(self, "_local_selection_excluded", set()),
                                      self, extra_frames=extra_frames,
                                      filters=saved_view.get("filters"),
                                      row_bools=saved_view.get("row_bools"),
                                      group_bools=saved_view.get("group_bools"),
                                      show=saved_view.get("show", "all"))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._local_selection_excluded = set(dialog.excluded)
            self._local_view = {
                "filters": dialog.saved_filters,
                "row_bools": dialog.saved_row_bools,
                "group_bools": dialog.saved_group_bools,
                "show": dialog.saved_show,
            }
            self._refresh_selection_badge()
            self.update_plan()
        dialog.deleteLater()

    def update_plan(self, *_args):
        self._refresh_selection_badge()
        wafers, metrics = self.selected(self.wafer_list), self.selected(self.parameter_list)
        groups = self.group_columns()
        aliases = {"waferid", "wafer", "waferno"}
        primary = next((c for c in groups if "".join(ch.lower() for ch in c if ch.isalnum()) in aliases),
                       groups[0] if groups else None)
        self.selection = {"wafers": wafers, "metrics": metrics, "wafer_column": primary,
                          "groups": {m.key: m.rows for m in self.measurements},
                          "labels": {m.key: m.label for m in self.measurements}}
        allowed = self.participating_positions(self._frame)
        self.selection["groups"] = {key: tuple(row for row in rows if row in allowed)
                                    for key, rows in self.selection["groups"].items()}
        self.plot_page.set_input(self._frame, self.selection)
        self.radius_page.set_input(self._frame, self.selection)
        self.statusBar().showMessage(f"{len(wafers)} measurement sets selected    ·    {len(metrics)} parameters selected")
        self.selection_changed.emit(self.selection_state())

    def current_cell(self, index, *_args):
        if index.isValid():
            self.address.setText(f"{column_letter(index.column())}{index.row() + 1}")
            self.formula.setText(self.model.cells.get((index.row(), index.column()), ""))

    def edit_formula(self):
        index = self.sheet.currentIndex()
        if index.isValid():
            self.model.setData(index, self.formula.text())

    def update_dirty(self, *_args):
        if self.sender() is not None:
            from PyQt6 import sip
            if sip.isdeleted(self.model.undo):
                return
        self.dirty_label.setText("Edited · not saved" if not self.model.undo.isClean() else "No pending edits")

    def allow_replace(self):
        if hasattr(self, "document"):
            return self.document.confirm_close()
        if self.model.undo.isClean():
            return True
        return QMessageBox.question(self, "Unsaved edits", "Discard the current unsaved table edits?",
                                    QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                    QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Discard

    def set_managed_close_handler(self, handler):
        """Let an owning workbook persist this table before the window closes."""
        self._managed_close_handler = handler

    def mark_table_pasted(self):
        """Treat the first paste into an empty sheet as a brand-new table."""
        if self._frame.empty:
            self._pending_selection_state = None
        else:
            self._pending_selection_state = self.selection_state()
        self._reset_selection = True

    def set_table(self, frame, source, *, keep_local_selection=False):
        from .match_groups import participation_source_keys
        previous_selection = self.selection_state()
        had_table = not self._frame.empty
        previous_keys = []
        if had_table:
            try:
                previous_keys = list(participation_source_keys(self.model.frame()))
            except ValueError:
                previous_keys = []
        previous_excluded = set(getattr(self, "_local_selection_excluded", set()))
        self.source_path = str(source)
        self.file_label.setText(Path(source).name or "Untitled")
        self.file_label.setToolTip(str(source))
        self._reset_selection = True
        self.model.load(frame)
        for i, column in enumerate(frame.columns):
            width = 158 if column in ("Wafer ID", "PAD Name") else 118
            self.sheet.setColumnWidth(i, width)
        self.sheet.setCurrentIndex(self.model.index(0, 0))
        self.tabs.setCurrentIndex(0)
        self.recognize()
        if keep_local_selection and previous_keys and previous_excluded:
            # Keep this window's own selection when the Workbook refreshes its
            # data: surviving identities win, otherwise the same row position does.
            try:
                keys = list(participation_source_keys(frame.reset_index(drop=True)))
            except ValueError:
                keys = []
            exclusions = set()
            for position, key in enumerate(keys):
                if key in previous_excluded:
                    exclusions.add(key)
                elif position < len(previous_keys) and previous_keys[position] in previous_excluded:
                    exclusions.add(key)
            self._local_selection_excluded = exclusions
            self._refresh_selection_badge()
            self.update_plan()
        if had_table:
            self.restore_selection(previous_selection)
        else:
            self.check_all(self.wafer_list, True)

    def new_table(self):
        if self.allow_replace():
            self.set_table(pd.DataFrame(), "Untitled")

    def open_file(self):
        kind = self.workspace_type
        file_filter = f"{WORKSPACE_LABELS[kind]} (*{EXTENSIONS[kind]} *.wkb);;Tables (*.csv *.xlsx)"
        path, _ = QFileDialog.getOpenFileName(self, "Open workspace or table", "", file_filter)
        if path:
            self.load_path(path)

    def load_path(self, path):
        if Path(path).suffix.lower() in EXTENSIONS.values():
            try:
                return self.load_workspace(path)
            except Exception as error:
                LOGGER.exception("Unable to open workspace")
                QMessageBox.warning(self, "Unable to open workspace", str(error))
                return None
        if not self.allow_replace():
            return
        try:
            sheet = 0
            if Path(path).suffix.lower() == ".xlsx":
                with pd.ExcelFile(path, engine="openpyxl") as book:
                    sheets = book.sheet_names
                if len(sheets) > 1:
                    sheet, ok = QInputDialog.getItem(self, "Select worksheet", "Worksheet", sheets, editable=False)
                    if not ok:
                        return
            self.set_table(read_table(path, sheet=sheet, dtype=str), str(path))
            LOGGER.info("Measurement table opened: %s", Path(path).resolve())
        except Exception as error:
            LOGGER.exception("Unable to open measurement table")
            QMessageBox.warning(self, "Unable to open table", str(error))

    def paste_table(self):
        matrix = clipboard_rows(QApplication.clipboard().text())
        if len(matrix) < 2:
            QMessageBox.information(self, "Paste table", "Copy a header row and at least one data row first.")
            return
        if not self.allow_replace():
            return
        width = max(map(len, matrix))
        matrix = [row + [""] * (width - len(row)) for row in matrix]
        self.set_table(pd.DataFrame(matrix[1:], columns=matrix[0]), "Clipboard")

    def save_table(self):
        try:
            frame = self.model.frame()
            path, _ = QFileDialog.getSaveFileName(self, "Save table", "measurements.csv", "CSV (*.csv)")
            if path:
                frame.to_csv(path, index=False, encoding="utf-8-sig")
                self.file_label.setText(Path(path).name)
                self.statusBar().showMessage(f"Saved: {path}")
                LOGGER.info("Measurement table saved: %s", Path(path).resolve())
        except Exception as error:
            LOGGER.exception("Unable to save measurement table")
            QMessageBox.warning(self, "Unable to save table", str(error))

    def closeEvent(self, event):
        if self.document.confirm_close():
            self.document.closed()
            self.refresh_timer.stop()
            self.plot_page.stop()
            self.radius_page.stop()
            callback = getattr(self, "_managed_after_close_handler", None)
            if callable(callback):
                callback()
            event.accept()
        else:
            event.ignore()

    def auto_rename_columns(self):
        """Number repeated row-1 headers so the table can be read again.

        The button sits next to the duplicate-name warning; renaming keeps every
        other cell untouched and is undoable with Ctrl+Z.
        """
        return self.warning_banner.rename_duplicates()

    def _auto_rename_completed(self, renames):
        if not renames:
            self.auto_rename_button.hide()
            return
        summary = ", ".join(f"{old} → {new}" for old, new in renames.values())
        self.recognize()
        if self.model.duplicate_header_count():
            self.statusBar().showMessage(f"Still duplicated after renaming: {summary}", 8000)
        else:
            self.statusBar().showMessage(f"Renamed {len(renames)} duplicate column(s): {summary}", 8000)
