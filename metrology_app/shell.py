"""Application shell that supervises independent analysis components."""

from datetime import datetime
import logging
import platform
from pathlib import Path
import sys
import traceback

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import (
    QAction, QColor, QFont, QFontDatabase, QIcon, QPainter, QPen, QPixmap,
    QTextCharFormat, QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget,
    QFileDialog, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QScrollArea, QSizePolicy, QSplitter,
    QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from .appearance import (
    fit_window_to_screen, help_title_label, set_theme_palette, style_titlebar,
)
from .module_button import ModuleButton
from .module_registry import create_default_registry
from .diagnostics import get_logger
from .settings import apply_theme, get_settings, load_settings, save_settings, recent_wkb_paths
from .workspace_store import EXTENSIONS, WORKSPACE_FILTER, WORKSPACE_LABELS, load_workspace
from .settings_dialog import SettingsDialog


APPLICATION_NAME = "Metrology Workspace"
TERMINAL_FONT_FAMILIES = (
    "Cascadia Mono", "Cascadia Code", "JetBrains Mono", "Consolas",
)
LOG_COLOURS = {
    "light": {
        "timestamp": "#6b6b70",
        "INFO": "#1d5fbf",
        "WARNING": "#8a5a00",
        "ERROR": "#b42318",
        "source": "#6941c6",
        "message": "#24212a",
    },
    "dark": {
        "timestamp": "#93869f",
        "INFO": "#79b8ff",
        "WARNING": "#f5b942",
        "ERROR": "#ff7b86",
        "source": "#d6b5ff",
        "message": "#e7e0eb",
    },
}


def _terminal_font():
    available = set(QFontDatabase.families())
    fallback = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    family = next(
        (candidate for candidate in TERMINAL_FONT_FAMILIES if candidate in available),
        fallback.family(),
    )
    font = QFont(family, 10)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    return font


class _DiagnosticHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__(logging.INFO)
        self.callback = callback

    def emit(self, record):
        try:
            self.callback(record.levelname, "Application", self.format(record))
        except RuntimeError:
            pass


def _label(text, role):
    widget = QLabel(text)
    widget.setObjectName(role)
    return widget


class MainWindow(QMainWindow):
    """Open multiple independent analysis workspaces."""

    def __init__(self, registry=None, parent=None):
        super().__init__(parent)
        load_settings()
        self.registry = registry or create_default_registry()
        self.loaded_components = {}
        self._instance_serial = {}
        self.module_buttons = {}
        self._diagnostic_handler = None
        self._log_entries = []
        self._log_theme = get_settings()["theme"]
        self.setObjectName("applicationShell")
        self.setWindowTitle(APPLICATION_NAME)
        # A modest window centred on the display: the shell only holds two
        # module cards, so there is no reason to take the whole screen. The
        # size still shrinks automatically on smaller / high-DPI displays.
        fit_window_to_screen(self, (1180, 820), minimum=(900, 600))
        self._apply_theme()
        self._build_toolbar()
        self._build_content()
        self._install_diagnostic_log()
        self._populate_modules()
        self.record("App", "Metrology Workspace is ready")
        self._append_log("INFO", "Runtime", f"Python {platform.python_version()} · {sys.executable}")
        self._append_log("INFO", "Runtime", f"Platform {platform.platform()}")
        self._append_log("INFO", "Runtime", f"Working directory: {Path.cwd()}")
        self.update_overview()
        self.setAcceptDrops(True)

    @property
    def loaded_component_ids(self):
        return tuple(component_id for component_id, instances in self.loaded_components.items() if instances)

    @property
    def wafer_component(self):
        instances = self.loaded_components.get("wafer_map")
        return instances[-1] if instances else None

    @property
    def correlation_component(self):
        instances = self.loaded_components.get("correlation_analysis")
        return instances[-1] if instances else None

    def instance_count(self, component_id):
        return len(self.loaded_components.get(component_id, []))

    def _apply_theme(self):
        apply_theme(self)

    def _build_toolbar(self):
        toolbar = QToolBar("Application toolbar", objectName="mainToolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        menu_button = QToolButton(objectName="toolbarMenu")
        self.menu_button = menu_button
        menu_button.setIconSize(QSize(16, 16))
        self._update_menu_icon(get_settings()["theme"])
        menu_button.setToolTip("Open the application menu")
        menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(menu_button)
        open_action = menu.addAction("Open Workspace…")
        open_action.setShortcut("Ctrl+O")
        open_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        open_action.triggered.connect(self.open_workspace_dialog)
        self.recent_workspace_menu = menu.addMenu("Open Recent Workspace")
        self.recent_workspace_menu.aboutToShow.connect(self.refresh_recent_workspaces)
        settings = QAction("Settings…", self)
        settings.triggered.connect(self.open_settings)
        menu.addAction(settings)
        menu_button.setMenu(menu)
        toolbar.addWidget(menu_button)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

    def _update_menu_icon(self, theme):
        colour = QColor("#18181b" if theme == "light" else "#e7e0eb")
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        pen = QPen(colour)
        pen.setWidthF(1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        for y in (4.0, 8.0, 12.0):
            painter.drawLine(2, int(y), 14, int(y))
        painter.end()
        self.menu_button.setIcon(QIcon(pixmap))

    def _build_content(self):
        upper = QWidget(objectName="shellRoot")
        layout = QHBoxLayout(upper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar(), 23)
        layout.addWidget(self._build_overview(), 47)
        layout.addWidget(self._build_activity(), 30)
        # Compressed panels stay reachable: the shell scrolls instead of hiding
        # whatever does not fit into the window.
        scroll = QScrollArea(objectName="shellScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(upper)
        self.shell_scroll = scroll

        splitter = QSplitter(Qt.Orientation.Vertical, objectName="shellSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)
        splitter.addWidget(scroll)
        splitter.addWidget(self._build_log())
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([590, 190])
        self.shell_splitter = splitter
        self._shell_splitter_moved = False
        splitter.splitterMoved.connect(self._shell_splitter_was_moved)
        self.setCentralWidget(splitter)
        saved_sizes = get_settings().get("shell_splitter_sizes")
        self._restore_shell_splitter(saved_sizes)
        if saved_sizes is not None:
            QTimer.singleShot(
                0, lambda sizes=tuple(saved_sizes):
                self._restore_shell_splitter(sizes)
            )

    def _shell_splitter_was_moved(self, *_args):
        self._shell_splitter_moved = True

    def _restore_shell_splitter(self, sizes):
        if (
            isinstance(sizes, (list, tuple))
            and len(sizes) == 2
            and all(isinstance(size, (int, float)) and size >= 0 for size in sizes)
            and sum(sizes) > 0
        ):
            self.shell_splitter.setSizes([int(size) for size in sizes])

    def _build_sidebar(self):
        panel = QFrame(objectName="sidebar")
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(345)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 24, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(_label("ANALYSIS TOOLS", "navigationLabel"))
        self.module_layout = QVBoxLayout()
        self.module_layout.setSpacing(9)
        layout.addLayout(self.module_layout)
        layout.addStretch()
        return panel

    def _build_overview(self):
        page = QWidget(objectName="overviewPage")
        page.setMinimumWidth(360)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 26, 30, 28)
        layout.setSpacing(10)
        layout.addWidget(help_title_label(
            "Workspace", "Open a tool in its own analysis window.", "pageTitle"
        ))
        layout.addSpacing(18)
        card = QFrame(objectName="overviewCard")
        grid = QGridLayout(card)
        grid.setContentsMargins(22, 20, 22, 20)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(14)
        grid.addWidget(_label("CURRENT SESSION", "sectionTitle"), 0, 0, 1, 2)
        self.available_value = _label("0", "detailValue")
        self.loaded_value = _label("0", "detailValue")
        self.last_loaded_value = _label("—", "accentValue")
        for row, (name, value) in enumerate((
            ("Available tools", self.available_value),
            ("Open windows", self.loaded_value),
            ("Last opened", self.last_loaded_value),
        ), start=1):
            grid.addWidget(_label(name, "detailLabel"), row, 0)
            grid.addWidget(value, row, 1)
        grid.setColumnStretch(1, 1)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _build_activity(self):
        panel = QFrame(objectName="activityPanel")
        panel.setMinimumWidth(360)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 24, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(help_title_label(
            "Activity", "Windows and files opened in this session."
        ))
        self.activity = QListWidget(objectName="activityLog")
        self.activity.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self.activity, 1)
        return panel

    def _build_log(self):
        panel = QFrame(objectName="diagnosticPanel")
        panel.setMinimumHeight(150)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 10, 18, 14)
        layout.setSpacing(8)
        layout.addWidget(help_title_label(
            "Log", "Runtime, file paths, and errors for debugging."
        ))
        self.log_output = QPlainTextEdit(objectName="diagnosticLog")
        self.log_output.setFont(_terminal_font())
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_output.document().setMaximumBlockCount(1000)
        layout.addWidget(self.log_output, 1)
        return panel

    def _install_diagnostic_log(self):
        self._diagnostic_handler = _DiagnosticHandler(self._append_log)
        get_logger().addHandler(self._diagnostic_handler)

    def _populate_modules(self):
        for spec in self.registry:
            button = ModuleButton()
            button.set_content(spec.title, 0)
            button.setToolTip(f"{spec.description}\n\nOpen another {spec.title} window.")
            button.clicked.connect(
                lambda _=False, component_id=spec.component_id:
                self.launch_match_workbook() if component_id == "card_matching" else self.open_component(component_id)
            )
            self.module_buttons[spec.component_id] = button
            self.module_layout.addWidget(button)

    def launch_match_workbook(self, path=None):
        from .workbook_startup import WorkbookStartupDialog
        if path is not None:
            # Existing workbooks open exactly as saved; only New asks first.
            return self.open_component(
                "card_matching",
                initialize=lambda window: window.load_workbook(path),
            )
        dialog = WorkbookStartupDialog(self)
        try:
            if dialog.exec() != dialog.DialogCode.Accepted:
                return None
            if dialog.path is not None:
                chosen = dialog.path
                return self.open_component(
                    "card_matching",
                    initialize=lambda window: window.load_workbook(chosen),
                )
            settings = dialog.settings()
            def initialize(window):
                window.apply_analysis_settings(settings, refresh=False)
                window.document.mark_clean()
            return self.open_component("card_matching", initialize=initialize)
        except Exception as error:
            QMessageBox.warning(self, "Cannot open Workbook", str(error))
            return None
        finally:
            dialog.deleteLater()

    def open_component(self, component_id, *, initialize=None):
        spec = self.registry.get(component_id)
        try:
            widget = self.registry.create(component_id)
            if initialize is not None:
                try:
                    initialize(widget)
                except Exception:
                    widget.deleteLater()
                    raise
        except Exception as error:
            self.record("Error", f"Could not open {spec.title}: {error}\n{traceback.format_exc()}")
            raise
        self._instance_serial[component_id] = self._instance_serial.get(component_id, 0) + 1
        serial = self._instance_serial[component_id]
        label = spec.title if serial == 1 else f"{spec.title} #{serial}"
        if hasattr(widget, "document"):
            widget.document.refresh_identity()
        else:
            widget.setWindowTitle(f"{APPLICATION_NAME} — {label}")
        widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        apply_theme(widget)
        widget.destroyed.connect(
            lambda _=None, key=component_id, instance=widget: self.forget_instance(key, instance)
        )
        self.loaded_components.setdefault(component_id, []).append(widget)
        self.set_module_state(component_id)
        self.last_loaded_value.setText(label)
        widget.show()
        self.place_component(widget, serial)
        style_titlebar(widget, get_settings()["theme"])
        widget.raise_()
        widget.activateWindow()
        self.record("Window", f"Opened {label}")
        self.update_overview()
        return widget

    def place_component(self, widget, serial):
        """Cascade a component window inside the screen area the taskbar leaves free."""
        self.cascade_component(widget, serial)
        # The frame is added while the window is shown, so clamp once more after.
        QTimer.singleShot(0, lambda: self.cascade_component(widget, serial))

    def cascade_component(self, widget, serial):
        screen = widget.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        frame = widget.frameGeometry()
        step = 26 * (serial - 1)
        # Keep the whole frame (title bar included) inside the free area, so the
        # window never slips behind the taskbar or off the edge of the display.
        x = min(max(area.left(), self.x() + 44 + step),
                max(area.left(), area.right() - frame.width() + 1))
        y = min(max(area.top(), self.y() + 44 + step),
                max(area.top(), area.bottom() - frame.height() + 1))
        widget.move(x, y)

    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            self.apply_settings()

    def apply_settings(self):
        theme = get_settings()["theme"]
        apply_theme(self, theme)
        set_theme_palette(theme)
        style_titlebar(self, theme)
        self._update_menu_icon(theme)
        self._refresh_log_output(theme)
        for instances in self.loaded_components.values():
            for widget in instances:
                apply_theme(widget, theme)
                style_titlebar(widget, theme)

    def unload_component(self, component_id):
        instances = list(self.loaded_components.get(component_id, []))
        if not instances:
            self.set_module_state(component_id)
            return True
        refused = [widget for widget in instances if not widget.close()]
        if refused:
            self.loaded_components[component_id] = refused
            self.record("Warning", f"Could not close {self.registry.get(component_id).title}")
        else:
            self.loaded_components.pop(component_id, None)
            self.record("Window", f"Closed all {self.registry.get(component_id).title} windows")
        self.set_module_state(component_id)
        self.update_overview()
        return not refused

    def unload_all_components(self):
        windows = [widget for items in tuple(self.loaded_components.values()) for widget in tuple(items)]
        decisions = []
        for widget in windows:
            document = getattr(widget, "document", None)
            if document is None:
                continue
            choice = document.close_choice()
            if choice == QMessageBox.StandardButton.Cancel:
                return False
            decisions.append((widget, document, choice))
        # Do not discard or destroy anything until all necessary saves succeed.
        for widget, document, choice in decisions:
            if choice == QMessageBox.StandardButton.Save and not widget.save_wkb():
                self.record("Warning", "Exit cancelled: a document could not be saved. All windows remain open.")
                return False
        for widget, document, choice in decisions:
            if choice == QMessageBox.StandardButton.Discard:
                document.discard()
            document.force_close = True
        return all(self.unload_component(key) for key in tuple(self.loaded_components))

    def open_workspace_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Workspace", "", WORKSPACE_FILTER)
        if path:
            try:
                self.load_path(path)
            except Exception as error:
                QMessageBox.warning(self, "Cannot open workspace", str(error))

    def refresh_recent_workspaces(self):
        self.recent_workspace_menu.clear()
        for path in recent_wkb_paths():
            try:
                kind = load_workspace(path).workspace_type
            except (OSError, ValueError):
                continue
            action = self.recent_workspace_menu.addAction(f"{WORKSPACE_LABELS[kind]} · {path.name}")
            action.setToolTip(str(path))
            action.triggered.connect(lambda _=False, target=path: self.open_recent_workspace(target))

    def open_recent_workspace(self, path):
        try:
            return self.load_path(path)
        except Exception as error:
            QMessageBox.warning(self, "Cannot open workspace", str(error))

    def dragEnterEvent(self, event):
        if any(Path(url.toLocalFile()).suffix.lower() in EXTENSIONS.values() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in EXTENSIONS.values():
                self.open_recent_workspace(url.toLocalFile())
        event.acceptProposedAction()

    def forget_instance(self, component_id, widget):
        instances = self.loaded_components.get(component_id)
        if instances is not None and widget in instances:
            instances.remove(widget)
            if not instances:
                self.loaded_components.pop(component_id, None)
            self.record("Window", f"Closed a {self.registry.get(component_id).title} window")
        self.set_module_state(component_id)
        self.update_overview()

    def set_module_state(self, component_id):
        count = self.instance_count(component_id)
        button = self.module_buttons.get(component_id)
        if button is not None:
            button.set_content(self.registry.get(component_id).title, count)

    def update_overview(self):
        total = sum(len(instances) for instances in self.loaded_components.values())
        self.available_value.setText(str(len(self.registry)))
        self.loaded_value.setText(str(total))

    def _append_log(self, level, source, message):
        stamp = datetime.now().strftime("%H:%M:%S")
        entry = (stamp, str(level).upper(), str(source), str(message))
        self._log_entries.append(entry)
        del self._log_entries[:-1000]
        self._render_log_entry(entry)
        self._scroll_log_to_end()

    @staticmethod
    def _log_text_format(colour, emphasized=False):
        text_format = QTextCharFormat()
        text_format.setForeground(QColor(colour))
        if emphasized:
            text_format.setFontWeight(int(QFont.Weight.DemiBold))
        return text_format

    def _render_log_entry(self, entry):
        stamp, level, source, message = entry
        colours = LOG_COLOURS.get(self._log_theme, LOG_COLOURS["dark"])
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.log_output.document().isEmpty():
            cursor.insertBlock()
        cursor.insertText(
            f"{stamp}  ", self._log_text_format(colours["timestamp"])
        )
        cursor.insertText(
            f"[{level}]",
            self._log_text_format(colours.get(level, colours["INFO"]), True),
        )
        cursor.insertText("  ", self._log_text_format(colours["message"]))
        cursor.insertText(
            f"{source}:", self._log_text_format(colours["source"], True)
        )
        cursor.insertText(
            f" {message}", self._log_text_format(colours["message"])
        )

    def _refresh_log_output(self, theme):
        self._log_theme = theme if theme in LOG_COLOURS else "dark"
        self.log_output.clear()
        for entry in self._log_entries:
            self._render_log_entry(entry)
        self._scroll_log_to_end()

    def _scroll_log_to_end(self):
        vertical = self.log_output.verticalScrollBar()
        vertical.setValue(vertical.maximum())
        self.log_output.horizontalScrollBar().setValue(0)

    def record(self, source, message):
        normalized = str(source).strip().lower()
        level = "ERROR" if normalized == "error" else (
            "WARNING" if normalized == "warning" else "INFO"
        )
        summary = str(message).splitlines()[0]
        self.activity.insertItem(
            0, f"{datetime.now():%H:%M:%S}   {source}\n{summary}"
        )
        while self.activity.count() > 100:
            self.activity.takeItem(self.activity.count() - 1)
        self._append_log(level, source, message)

    def load_path(self, path):
        """Route a typed WKB to its owner; measurement imports use Wafer Map."""
        if Path(path).suffix.lower() in EXTENSIONS.values():
            snapshot = load_workspace(path)
            suffix = Path(path).suffix.lower()
            if suffix != EXTENSIONS[snapshot.workspace_type] and not (suffix == ".wkb" and snapshot.workspace_type != "match_workbook"):
                if QMessageBox.question(self, "Workspace type mismatch",
                                        f"The {suffix} extension does not match {WORKSPACE_LABELS[snapshot.workspace_type]}.\n"
                                        "Open using its actual type? Saving will require the correct extension.",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                    return None
            component_id = {"match_workbook": "card_matching", "wafer_map": "wafer_map",
                            "dynamic": "dynamic_analysis", "correlation_trend": "correlation_analysis"}[snapshot.workspace_type]
            if snapshot.workspace_type == "match_workbook":
                component = self.launch_match_workbook(path)
                if component is None:
                    return None
            else:
                component = self.open_component(component_id)
                component.load_workspace(path)
        else:
            component = self.open_component("wafer_map")
            component.load_path(path)
        self.record("Data", f"Opened {Path(path).name}")
        return component

    def closeEvent(self, event):
        if self.unload_all_components():
            if self._shell_splitter_moved:
                try:
                    save_settings({
                        "shell_splitter_sizes": self.shell_splitter.sizes(),
                    })
                except OSError as error:
                    self.record("Warning", f"Could not save Log layout: {error}")
            if self._diagnostic_handler is not None:
                get_logger().removeHandler(self._diagnostic_handler)
                self._diagnostic_handler = None
            event.accept()
        else:
            event.ignore()


__all__ = ["APPLICATION_NAME", "MainWindow"]
