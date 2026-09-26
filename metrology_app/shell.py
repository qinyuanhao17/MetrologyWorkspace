"""Application shell that supervises independent analysis components."""

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QMainWindow,
    QMenu, QPushButton, QScrollArea, QSizePolicy, QToolBar, QToolButton, QVBoxLayout,
    QWidget,
)

from .appearance import fit_window_to_screen, set_theme_palette, style_titlebar
from .module_button import ModuleButton
from .module_registry import create_default_registry
from .settings import apply_theme, get_settings, load_settings
from .settings_dialog import SettingsDialog


APPLICATION_NAME = "Metrology Workspace"


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
        self.close_all_buttons = {}
        self.setObjectName("applicationShell")
        self.setWindowTitle(APPLICATION_NAME)
        # A modest window centred on the display: the shell only holds two
        # module cards, so there is no reason to take the whole screen. The
        # size still shrinks automatically on smaller / high-DPI displays.
        fit_window_to_screen(self, (1180, 820), minimum=(900, 600))
        self._apply_theme()
        self._build_toolbar()
        self._build_content()
        self._populate_modules()
        self.record("App", "Metrology Workspace is ready")
        self.update_overview()

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
        settings = QAction("Settings…", self)
        settings.triggered.connect(self.open_settings)
        menu.addAction(settings)
        menu_button.setMenu(menu)
        toolbar.addWidget(menu_button)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        unload = QAction("Close all windows", self)
        unload.triggered.connect(self.unload_all_components)
        toolbar.addAction(unload)
        state = QWidget()
        row = QHBoxLayout(state)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(8)
        dot = QFrame(objectName="readyDot")
        dot.setFixedSize(9, 9)
        self.toolbar_state = _label("Ready", "toolbarState")
        row.addWidget(dot)
        row.addWidget(self.toolbar_state)
        toolbar.addWidget(state)
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
        root = QWidget(objectName="shellRoot")
        layout = QHBoxLayout(root)
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
        scroll.setWidget(root)
        self.shell_scroll = scroll
        self.setCentralWidget(scroll)

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
        line = QFrame(objectName="sectionSeparator")
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)
        footer = QHBoxLayout()
        dot = QFrame(objectName="readyDot")
        dot.setFixedSize(9, 9)
        self.sidebar_state = _label("No tools open", "sidebarState")
        footer.addWidget(dot)
        footer.addWidget(self.sidebar_state)
        footer.addStretch()
        layout.addLayout(footer)
        return panel

    def _build_overview(self):
        page = QWidget(objectName="overviewPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 26, 30, 28)
        layout.setSpacing(10)
        layout.addWidget(_label("Workspace", "pageTitle"))
        layout.addWidget(_label("Open a tool in its own analysis window.", "pageSubtitle"))
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
        layout.addSpacing(16)
        layout.addWidget(_label("AVAILABLE TOOLS", "sectionTitle"))
        self.catalog = QVBoxLayout()
        self.catalog.setSpacing(10)
        layout.addLayout(self.catalog)
        layout.addStretch()
        return page

    def _build_activity(self):
        panel = QFrame(objectName="activityPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 24, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(_label("Activity", "panelTitle"))
        layout.addWidget(_label("Windows and files opened in this session.", "pageSubtitle"))
        self.activity = QListWidget(objectName="activityLog")
        self.activity.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self.activity, 1)
        return panel

    def _populate_modules(self):
        for spec in self.registry:
            button = ModuleButton()
            button.set_content(spec.title, 0)
            button.setToolTip(f"{spec.description}\n\nOpen another {spec.title} window.")
            button.clicked.connect(
                lambda _=False, component_id=spec.component_id: self.open_component(component_id)
            )
            self.module_buttons[spec.component_id] = button
            self.module_layout.addWidget(button)

            card = QFrame(objectName="componentCard")
            row = QHBoxLayout(card)
            row.setContentsMargins(18, 15, 14, 15)
            text = QVBoxLayout()
            text.setSpacing(4)
            text.addWidget(_label(spec.title, "componentTitle"))
            description = _label(spec.description, "componentDescription")
            description.setWordWrap(True)
            text.addWidget(description)
            text.addWidget(_label(spec.category.upper(), "eyebrow"))
            row.addLayout(text, 1)
            actions = QVBoxLayout()
            actions.setSpacing(6)
            launch = QPushButton("Open", objectName="componentLaunch")
            launch.clicked.connect(lambda _=False, component_id=spec.component_id: self.open_component(component_id))
            close_all = QPushButton("Close all", objectName="componentCloseAll")
            close_all.setEnabled(False)
            close_all.clicked.connect(lambda _=False, component_id=spec.component_id: self.unload_component(component_id))
            actions.addWidget(launch)
            actions.addWidget(close_all)
            row.addLayout(actions)
            self.close_all_buttons[spec.component_id] = close_all
            self.catalog.addWidget(card)

    def open_component(self, component_id):
        spec = self.registry.get(component_id)
        widget = self.registry.create(component_id)
        self._instance_serial[component_id] = self._instance_serial.get(component_id, 0) + 1
        serial = self._instance_serial[component_id]
        label = spec.title if serial == 1 else f"{spec.title} #{serial}"
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
        return all(self.unload_component(key) for key in tuple(self.loaded_components))

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
        close_all = self.close_all_buttons.get(component_id)
        if close_all is not None:
            close_all.setEnabled(count > 0)

    def update_overview(self):
        total = sum(len(instances) for instances in self.loaded_components.values())
        self.available_value.setText(str(len(self.registry)))
        self.loaded_value.setText(str(total))
        state = f"{total} open" if total else "Ready"
        self.toolbar_state.setText(state)
        self.sidebar_state.setText(f"{total} window{'s' if total != 1 else ''} open" if total else "No tools open")

    def record(self, source, message):
        self.activity.insertItem(0, f"{datetime.now():%H:%M:%S}   {source}\n{message}")
        while self.activity.count() > 100:
            self.activity.takeItem(self.activity.count() - 1)

    def load_path(self, path):
        """Open the wafer component and forward a command-line input file to it."""
        component = self.open_component("wafer_map")
        component.load_path(path)
        self.record("Data", f"Opened {Path(path).name}")
        return component

    def closeEvent(self, event):
        if self.unload_all_components():
            event.accept()
        else:
            event.ignore()


__all__ = ["APPLICATION_NAME", "MainWindow"]
