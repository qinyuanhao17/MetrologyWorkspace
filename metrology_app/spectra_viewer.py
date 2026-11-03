"""Interactive SME spectra review workspace."""
from __future__ import annotations

from pathlib import Path
from time import monotonic

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QItemSelectionModel, QSize, QTimer, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPalette, QPen, QPixmap, QPixmapCache
from PyQt6.QtWidgets import (
    QAbstractScrollArea,
    QComboBox,
    QDialog,
    QFileDialog,
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .appearance import fit_window_to_screen, style_titlebar
from .settings import apply_theme as apply_window_theme, get_settings, theme_stylesheet
from .sme_spectra import (
    M_COLS,
    ChannelKey,
    LoadResult,
    SpectrumCatalog,
    SpectrumFile,
    SPECTRUM_GROUP_FIELDS,
    load_folder,
    LoadIssue,
)
from .spectra_map import SpectraMapWindow
from .spectra_analysis import SpectralSeries, residual_series, three_sigma_series
from .spectra_export_dialog import SpectraExportDialog, SpectraExportThread
from .spectra_plots import (
    CurveGroup,
    CurveSegment,
    FloatingPlotWindow,
    MuellerPanel,
    ResizablePlotSplitter,
    SpectrumPlotPanel,
    WaferChannelKey,
)


ROLE_KIND = Qt.ItemDataRole.UserRole
ROLE_KEY = Qt.ItemDataRole.UserRole + 1
ROLE_SPECTRA = Qt.ItemDataRole.UserRole + 2
ROLE_LEAF_GROUP = Qt.ItemDataRole.UserRole + 3
GROUP_KINDS = {"wafer", "lot", "pad", "die"}
GROUP_LABELS = (("wafer", "Wafer ID"), ("lot", "Lot"), ("pad", "PAD Name"), ("die", "Die"))
TREE_COLUMNS = (
    "Wafer / Spectrum",
    "SME Name",
    "Lot ID",
    "Tool SN",
    "PAD Name",
    "Die Seq",
    "FIELD X",
    "FIELD Y",
    "Time",
    "Folder",
    "Instrument",
    "Mode",
    "Version",
    "Sample ID",
    "Channel Count",
    "Channel ID",
)
VIEW_LABELS = (
    ("mueller", "Mueller"),
    ("N", "N"),
    ("C", "C"),
    ("S", "S"),
    ("psi_delta", "Psi Delta"),
    ("reflectance", "Reflectance"),
)
LEGEND_METRICS = {
    "NCS": ("N", "C", "S"),
    "Psi Delta": ("psi", "delta"),
    "Mueller": tuple(M_COLS),
    "Reflectance": ("reflectance",),
}
# Tableau Category10 (Matplotlib tab10), in its standard categorical order.
# https://matplotlib.org/stable/gallery/color/named_colors.html
CHANNEL_COLORS = (
    "#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD",
    "#8C564B", "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF",
)


def _line_icon(color: QColor, *, selected=False) -> QIcon:
    pixmap = QPixmap(24, 14)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(color, 4.4 if selected else 2.2))
    painter.drawLine(2, 7, 22, 7)
    painter.end()
    return QIcon(pixmap)


class _ViewMenu(QMenu):
    """Keep checkable view choices open for successive changes."""

    def mouseReleaseEvent(self, event):
        action = self.actionAt(event.pos())
        if (event.button() == Qt.MouseButton.LeftButton and action is not None
                and action.isEnabled() and action.isCheckable()):
            action.trigger()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        action = self.activeAction()
        if (event.key() == Qt.Key.Key_Space and action is not None
                and action.isEnabled() and action.isCheckable()):
            action.trigger()
            event.accept()
            return
        super().keyPressEvent(event)


class SpectraLoadThread(QThread):
    progress = pyqtSignal(int, int, str)
    completed = pyqtSignal(object)

    def __init__(self, folder: Path, parent=None):
        super().__init__(parent)
        self.folder = Path(folder)
        self.pack_workbook = bool(getattr(parent, "_workbook_embedded", False))
        self.workbook_samples = {}

    def run(self):
        last_progress = 0.0

        def progress(done, total, message):
            nonlocal last_progress
            now = monotonic()
            if done == 0 or done == total or now - last_progress >= 0.05:
                self.progress.emit(done, total, message)
                last_progress = now

        try:
            result = load_folder(
                self.folder,
                progress=progress,
                cancelled=self.isInterruptionRequested,
            )
            if self.pack_workbook and not result.cancelled:
                from .spectra_workbook import encode_sources
                self.progress.emit(0, 0, "Preparing embedded Workbook spectra…")
                self.workbook_samples = encode_sources(result.spectra, cancelled=self.isInterruptionRequested)
                if self.isInterruptionRequested():
                    result = LoadResult(result.spectra, result.issues, True)
        except Exception as error:
            result = LoadResult(
                (),
                (LoadIssue(self.folder, "error", str(error)),),
            )
        self.completed.emit(result)


class SpectraViewerWindow(QMainWindow):
    """A minimal source-preserving spectrum browser and plotting workspace."""
    stateChanged = pyqtSignal()
    workspace_type = "spectra_viewer"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Spectra Viewer")
        fit_window_to_screen(self, (1480, 900), minimum=(1000, 680))
        self.catalog = SpectrumCatalog()
        self._plot_revision = 0
        self._rendered_view_signatures = {}
        self._pending_plot_paints = []
        self._pending_plot_updates = {}
        self._plot_paint_timer = QTimer(self, singleShot=True, interval=0)
        self._plot_paint_timer.timeout.connect(self._paint_next_plot)
        self._resizing_panels = set()
        self._resize_paint_timer = QTimer(self, singleShot=True, interval=0)
        self._resize_paint_timer.timeout.connect(self._flush_plot_resizes)
        self._plot_status_base = ""
        # Keep dense-view caches bounded while accommodating high-DPI plot grids.
        QPixmapCache.setCacheLimit(max(QPixmapCache.cacheLimit(), 64 * 1024))
        self._checked_keys: set[str] = set()
        self._hidden_channel_keys: set[WaferChannelKey] = set()
        self.test_flags = {}
        self.spec_save_type = "embedded"
        self._unavailable_paths = {}
        self._unavailable_checked = set()
        self.test_flag_values = [0, 1, -1]
        self.test_flag_grouping = ["wafer", "lot", "pad"]
        self._spectra_info_source = None
        self.info_window = None
        self._info_refresh_timer = QTimer(self, singleShot=True, interval=0)
        self._info_refresh_timer.timeout.connect(self._refresh_spectra_info)
        self.stateChanged.connect(self._info_refresh_timer.start)
        self._channel_colors: dict[WaferChannelKey, QColor] = {}
        self._color_mode = "wafer"
        self._legend_angles = {}
        self._color_key_revision = -1
        self._color_keys = {}
        self._color_order = {}
        self._selected_keys: set[str] = set()
        self._baseline_key: str | None = None
        self._analysis_mode = "original"
        self._analysis_cache_revision = None
        self._residual_cache = {}
        self._sigma_cache = {}
        self._analysis_segments = {}
        self._analysis_notes = {}
        self.floating_plot_windows: dict[SpectrumPlotPanel, FloatingPlotWindow] = {}
        self._syncing_selection = False
        self.map_window: SpectraMapWindow | None = None
        self._map_data_signature = None
        self._loader: SpectraLoadThread | None = None
        self._exporter: SpectraExportThread | None = None
        self.export_dialog = None
        self._load_replace = True
        self._expanded_paths: set[tuple[str, ...]] = set()
        self._syncing_tree = False
        self._unfold_queue: list[QTreeWidgetItem] = []
        self._all_group_items: list[QTreeWidgetItem] = []
        self._unfold_timer = QTimer(self, interval=0, singleShot=True)
        self._unfold_timer.timeout.connect(self._unfold_next_batch)
        self.spectrum_items: dict[str, QTreeWidgetItem] = {}
        self._spectrum_groups_by_key: dict[str, QTreeWidgetItem] = {}
        self.view_actions: dict[str, QAction] = {}
        self._plot_layout_signature = None
        from .selection_script import selection_view
        self._data_selection_view = selection_view(None)
        self._workbook_selection_source = None
        apply_window_theme(self)
        self._build_view_actions()
        self._build_ui()
        self._build_menus()
        self.apply_theme(self.palette())
        from .workspace_document import WkbDocument
        self._workbook_embedded = True
        self.document = WkbDocument(self)
        self.stateChanged.connect(self.document.identity_timer.start)
        self.tree.itemSelectionChanged.connect(self.document.identity_timer.start)
        for panel in (*self.plot_panels.values(), *self.mueller_panel.mij_plots.values()):
            panel.plot.getViewBox().sigRangeChanged.connect(lambda *_: self.document.identity_timer.start())
            if panel.secondary is not None:
                panel.secondary.sigRangeChanged.connect(lambda *_: self.document.identity_timer.start())
        self.document.mark_clean()

    def workspace_snapshot(self):
        from .spectra_workbook import snapshot
        return snapshot(self)

    def showEvent(self, event):
        super().showEvent(event)
        style_titlebar(self, get_settings()["theme"])
        if getattr(self, "_spec_shown", False):
            return
        self._spec_shown = True
        document = self.document
        if document.path is not None or document.forced_dirty or self.catalog.spectra:
            return
        current = self.workspace_snapshot()
        baseline = document.baseline
        if baseline is None or not baseline.frames["spectra"].empty:
            return
        # Qt resolves initial splitter geometry on first show. Accept geometry
        # alone; explicit source or control edits made before show stay dirty.
        controls = lambda state: {key: value for key, value in state.items() if key != "splitters"}
        if controls(current.states["ui"]) == controls(baseline.states["ui"]):
            document.mark_clean(current)

    def restore_workspace(self, snapshot):
        from .spectra_workbook import restore
        restore(self, snapshot)

    def save_spec(self, path=None, *, save_as=False):
        return self.document.save(path, save_as=save_as)

    def save_wkb(self):
        try:
            return self.save_spec()
        except Exception as error:
            QMessageBox.warning(self, "Cannot save Spectra", str(error))
            return None

    def load_workspace(self, path):
        from .workspace_store import load_workspace, file_revision
        draft = load_workspace(path, expected_type=self.workspace_type)
        if not self.document.confirm_close():
            return None
        if draft.revision != file_revision(path):
            draft = load_workspace(path, expected_type=self.workspace_type)
        if "recovery" in draft.states:
            self.document.recover(path, draft)
            return draft
        self.restore_workspace(draft)
        self.document.path = Path(path).resolve()
        self.document.revision = draft.revision
        self.document.untrusted_recovery = False
        self.document.mark_clean()
        self.document.remember_recent()
        return draft

    def open_spec_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Spectra", "", "Spectra files (*.spec);;Backups (*.bak)")
        if path:
            try:
                self.load_workspace(path)
            except Exception as error:
                QMessageBox.warning(self, "Cannot open Spectra", str(error))

    def save_spec_as_dialog(self):
        try:
            return self.save_spec(save_as=True)
        except Exception as error:
            QMessageBox.warning(self, "Cannot save Spectra", str(error))
            return None

    def _build_view_actions(self):
        for key, label in VIEW_LABELS:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(self._view_visibility_changed)
            self.view_actions[key] = action

    def _build_menus(self):
        self.file_menu = self.menuBar().addMenu("File")
        self.open_spec_action = self.file_menu.addAction("Open Spectra File…")
        self.open_spec_action.setShortcut("Ctrl+O")
        self.open_spec_action.triggered.connect(self.open_spec_dialog)
        self.save_spec_action = self.file_menu.addAction("Save Spectra")
        self.save_spec_action.setShortcut("Ctrl+S")
        self.save_spec_action.triggered.connect(self.save_wkb)
        self.save_spec_as_action = self.file_menu.addAction("Save Spectra As…")
        self.save_spec_as_action.setShortcut("Ctrl+Shift+S")
        self.save_spec_as_action.triggered.connect(self.save_spec_as_dialog)
        self.file_menu.addSeparator()
        self.load_spectra_action = QAction("Load Spectra…", self)
        self.load_spectra_action.triggered.connect(
            lambda: self.choose_folder(replace=True)
        )
        self.file_menu.addAction(self.load_spectra_action)
        self.add_spectra_action = QAction("Add Spectra…", self)
        self.add_spectra_action.setEnabled(False)
        self.add_spectra_action.triggered.connect(
            lambda: self.choose_folder(replace=False)
        )
        self.file_menu.addAction(self.add_spectra_action)

        self.data_menu = self.menuBar().addMenu("Data")
        self.data_selection_action = self.data_menu.addAction("Data selection…")
        self.data_selection_action.triggered.connect(self.open_data_selection)
        self.copy_wkb_selection_action = self.data_menu.addAction("Copy WKB Selection")
        self.copy_wkb_selection_action.setEnabled(False)
        self.copy_wkb_selection_action.setToolTip("Available in a Spectra Viewer opened from Match Workbook.")
        self.copy_wkb_selection_action.triggered.connect(self.copy_wkb_selection)
        self.test_flag_action = self.data_menu.addAction("Set Test Flag…")
        self.test_flag_action.triggered.connect(self.open_test_flags)

        self.options_menu = self.menuBar().addMenu("Options")
        self.spec_save_menu = self.options_menu.addMenu("Spec Save Type")
        self.spec_save_group = QActionGroup(self)
        self.spec_save_group.setExclusive(True)
        self.spec_save_actions = {}
        for mode, label in (("embedded", "Embed Spectra Data"), ("paths", "Spectra Paths Only")):
            action = self.spec_save_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(mode == self.spec_save_type)
            self.spec_save_group.addAction(action)
            action.triggered.connect(lambda _checked, mode=mode: self.set_spec_save_type(mode))
            self.spec_save_actions[mode] = action
        self.views_menu = _ViewMenu("Views", self.options_menu)
        self.options_menu.addMenu(self.views_menu)
        for key, _label in VIEW_LABELS:
            self.views_menu.addAction(self.view_actions[key])
        self.verify_spectra_time_action = self.options_menu.addAction("Verify Spectra Info Filename Timestamp")
        self.verify_spectra_time_action.setCheckable(True)
        self.verify_spectra_time_action.setChecked(True)
        self.verify_spectra_time_action.setToolTip("Match the time at the end of the Raw Data SME filename to the time inside the spectrum.")
        self.verify_spectra_time_action.toggled.connect(lambda _checked: self.stateChanged.emit())
        self.analysis_menu = self.options_menu.addMenu("Plot Mode")
        self.analysis_action_group = QActionGroup(self)
        self.analysis_actions = {}
        for key, label in (("original", "Original"), ("residual", "Residual"), ("3sigma", "3-Sigma")):
            action = self.analysis_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(key == "original")
            self.analysis_action_group.addAction(action)
            action.triggered.connect(lambda _checked=False, mode=key: self.set_analysis_mode(mode))
            self.analysis_actions[key] = action
        self.analysis_actions["residual"].setEnabled(False)
        self.analysis_actions["residual"].setToolTip("Measured − BSL at exactly matching wavelengths; no interpolation.")
        self.analysis_actions["3sigma"].setToolTip("3 × sample SD (n−1) per Wafer/channel; at least two finite observations per exact wavelength.")

    def _build_ui(self):
        root = QWidget(objectName="spectraRoot")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        heading = QHBoxLayout()
        title = QLabel("Filter By", objectName="navigationLabel")
        heading.addWidget(title)
        self.group_by_combo = QComboBox()
        for key, label in GROUP_LABELS:
            self.group_by_combo.addItem(label, key)
        self.group_by_combo.setMinimumWidth(150)
        self.group_by_combo.currentIndexChanged.connect(self._grouping_changed)
        heading.addWidget(self.group_by_combo)
        heading.addWidget(QLabel("Color By", objectName="navigationLabel"))
        self.color_by_combo = QComboBox()
        self.color_by_combo.addItem("Wafer", "wafer")
        self.color_by_combo.addItem("SME Name", "sme")
        self.color_by_combo.setMinimumWidth(125)
        self.color_by_combo.currentIndexChanged.connect(
            lambda index: self.set_color_mode(self.color_by_combo.itemData(index)))
        heading.addWidget(self.color_by_combo)
        self.baseline_label = QLabel("BSL: —", objectName="hint")
        self.baseline_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        heading.addWidget(self.baseline_label, 1)
        self.open_map_button = QPushButton("Open Die Map", objectName="primary")
        self.open_map_button.setEnabled(False)
        self.open_map_button.clicked.connect(self.open_wafer_map)
        self.spectra_info_button = QPushButton("Spectra Info", objectName="primary")
        self.spectra_info_button.setEnabled(False)
        self.spectra_info_button.clicked.connect(self.open_spectra_info)
        heading.addWidget(self.spectra_info_button)
        heading.addWidget(self.open_map_button)
        outer.addLayout(heading)

        main = ResizablePlotSplitter(Qt.Orientation.Horizontal, default_sizes=(1, 3))
        self.main_splitter = main
        main.setObjectName("spectraSplitter")
        main.setHandleWidth(7)
        main.setOpaqueResize(False)
        main.addWidget(self._build_tree_panel())
        main.addWidget(self._build_plot_panel())
        main.reset_sizes()
        outer.addWidget(main, 1)

        footer_widget = QWidget()
        footer = QHBoxLayout(footer_widget)
        footer.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel("", objectName="hint")
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footer.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setFixedWidth(300)
        footer.addWidget(self.progress)
        self.cancel_load = QPushButton("Cancel")
        self.cancel_load.setVisible(False)
        self.cancel_load.clicked.connect(self.cancel_loading)
        footer.addWidget(self.cancel_load)
        outer.addWidget(footer_widget)
        self.setCentralWidget(root)
        self.cancel_load.ensurePolished()
        self.progress.ensurePolished()
        footer_widget.setMinimumHeight(max(self.cancel_load.sizeHint().height(), self.progress.sizeHint().height()))

    def _build_tree_panel(self):
        panel = QFrame(objectName="panel")
        panel.setMinimumWidth(0)
        panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        self.tree = QTreeWidget(objectName="spectraTree")
        self.tree.setMinimumWidth(0)
        self.tree.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.tree.setColumnCount(len(TREE_COLUMNS))
        self.tree.setHeaderLabels(TREE_COLUMNS)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.tree.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        for index, width in enumerate((
            230, 310, 150, 110, 120, 70, 80, 80, 190, 320, 120, 90, 110, 150, 100, 100,
        )):
            self.tree.setColumnWidth(index, width)
        self.tree.setAlternatingRowColors(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_context_menu)
        self.tree.itemChanged.connect(self._tree_item_changed)
        self.tree.itemSelectionChanged.connect(self._tree_selection_changed)
        self.tree.itemExpanded.connect(self._tree_item_expanded)
        self.tree.itemCollapsed.connect(lambda item: self._remember_expansion(item, False))
        layout.addWidget(self.tree, 1)
        self.tree_summary = QLabel("No spectra loaded", objectName="hint")
        layout.addWidget(self.tree_summary)
        return panel

    def _build_plot_panel(self):
        frame = QFrame(objectName="panel")
        frame.setMinimumWidth(0)
        frame.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layout = QVBoxLayout(frame)
        self.plot_panel_layout = layout
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        legend_row = ResizablePlotSplitter(Qt.Orientation.Horizontal)
        self.legend_splitter = legend_row
        legend_row.setObjectName("spectraLegendSplitter")
        legend_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.legends: dict[str, QListWidget] = {}
        self.legend_sections: dict[str, QWidget] = {}
        for name in LEGEND_METRICS:
            section_widget = QWidget()
            section_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            section = QVBoxLayout(section_widget)
            section.setContentsMargins(0, 0, 0, 0)
            section.setSpacing(4)
            section.addWidget(QLabel(name, objectName="navigationLabel"))
            section_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            section_widget.customContextMenuRequested.connect(
                lambda pos, section=name, widget=section_widget:
                self.build_legend_menu(section).exec(widget.mapToGlobal(pos)))
            legend = QListWidget(objectName="spectrumLegend")
            legend.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            legend.setAccessibleName(f"{name} channel legend")
            legend.setFlow(QListWidget.Flow.TopToBottom)
            legend.setWrapping(False)
            legend.setUniformItemSizes(True)
            legend.setWordWrap(False)
            legend.setTextElideMode(Qt.TextElideMode.ElideRight)
            legend.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            legend.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            legend.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            legend.customContextMenuRequested.connect(
                lambda pos, section=name, widget=legend:
                self.build_legend_menu(section).exec(widget.viewport().mapToGlobal(pos)))
            legend.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            legend.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            legend.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            legend.setSpacing(1)
            legend.setFixedHeight(92)
            legend.setToolTip("Scroll to browse channels. Double-click to hide or restore a channel. Right-click for Select Channel, Show All or Hide All.")
            legend.itemDoubleClicked.connect(self._legend_double_clicked)
            section.addWidget(legend)
            legend_row.addWidget(section_widget)
            self.legends[name] = legend
            self.legend_sections[name] = section_widget
        legend_row.setFixedHeight(max(section.sizeHint().height() for section in self.legend_sections.values()))
        layout.addWidget(legend_row)

        self.plot_panels = {
            "N": SpectrumPlotPanel(
                "N", context_menu=self._show_view_menu
            ),
            "C": SpectrumPlotPanel(
                "C", context_menu=self._show_view_menu
            ),
            "S": SpectrumPlotPanel(
                "S", context_menu=self._show_view_menu
            ),
            "psi_delta": SpectrumPlotPanel(
                "Psi Delta",
                dual=True,
                context_menu=self._show_view_menu,
            ),
            "reflectance": SpectrumPlotPanel(
                "Reflectance",
                context_menu=self._show_view_menu,
            ),
        }
        self.mueller_panel = MuellerPanel(context_menu=self._show_view_menu)
        self.all_plot_panels = {
            **self.plot_panels,
            "mueller": self.mueller_panel,
        }
        for plot_widget in self.all_plot_panels.values():
            if isinstance(plot_widget, SpectrumPlotPanel):
                plot_widget.sigDoubleClicked.connect(self.open_plot_window)
                plot_widget.spectraSelected.connect(self.select_spectrum_keys)
                plot_widget.resizeRequested.connect(lambda panel=plot_widget: self._queue_plot_resize(panel))
            else:
                for subplot in plot_widget.mij_plots.values():
                    subplot.sigDoubleClicked.connect(self.open_plot_window)
                    subplot.spectraSelected.connect(self.select_spectrum_keys)
                    subplot.resizeRequested.connect(lambda panel=subplot: self._queue_plot_resize(panel))
        self.left_plot_splitter = ResizablePlotSplitter(Qt.Orientation.Vertical)
        self.left_plot_splitter.setObjectName("spectraLeftPlotSplitter")
        self.plot_splitter = ResizablePlotSplitter(Qt.Orientation.Horizontal, default_sizes=(1, 2))
        self.plot_splitter.setObjectName("spectraPlotSplitter")
        self.plot_placeholder = QLabel(
            "Check one or more spectra to draw their channels.",
            objectName="subtitle",
        )
        self.plot_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.plot_placeholder, 1)
        self.plot_splitter.hide()
        layout.addWidget(self.plot_splitter, 1)
        self._refresh_plot_layout()
        return frame

    def choose_folder(self, *, replace: bool):
        if self._loader is not None:
            return
        folder = QFileDialog.getExistingDirectory(
            self,
            "Load spectra folder",
            str(Path.home()),
        )
        if folder:
            self.start_loading(Path(folder), replace=replace)

    def start_loading(self, folder: Path, *, replace: bool):
        if self._loader is not None or self._exporter is not None:
            return
        if replace and self.catalog.spectra:
            answer = QMessageBox.question(
                self,
                "Replace loaded spectra",
                "Replace the current spectrum batch with this folder?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._load_replace = replace
        self._loader = SpectraLoadThread(folder, self)
        self._loader.progress.connect(self._show_progress)
        self._loader.completed.connect(self._loading_completed)
        self._loader.finished.connect(self._loading_finished)
        self.load_spectra_action.setEnabled(False)
        self.add_spectra_action.setEnabled(False)
        self.cancel_load.setVisible(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status.setText("Scanning spectrum folders…")
        self._loader.start()

    def cancel_loading(self):
        if self._exporter is not None:
            self._exporter.requestInterruption()
        if self._loader is not None:
            self._loader.requestInterruption()
            self.status.setText("Cancelling after the current file…")

    def _show_progress(self, done: int, total: int, message: str):
        self.status.setToolTip(message)
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            self.status.setText(f"Reading {done} / {total} · {message}")
        else:
            self.status.setText(message)

    def _loading_completed(self, result: LoadResult):
        if result.cancelled:
            self.status.setText("Spectrum loading cancelled; existing data was kept.")
            return
        if self._loader is not None and self._loader.workbook_samples:
            self._workbook_samples = {**getattr(self, "_workbook_samples", {}), **self._loader.workbook_samples}
        self.apply_load_result(result, replace=self._load_replace)

    def _loading_finished(self):
        loader, self._loader = self._loader, None
        if loader is not None:
            loader.deleteLater()
        self.load_spectra_action.setEnabled(True)
        self.add_spectra_action.setEnabled(bool(self.catalog.spectra))
        self.cancel_load.setVisible(False)
        self.progress.setVisible(False)

    def apply_load_result(self, result: LoadResult, *, replace: bool, allow_empty_replace=False):
        if result.cancelled:
            return
        if replace and not result.spectra and not allow_empty_replace:
            self.catalog.issues = list(result.issues)
            self._rebuild_tree()
            self.status.setText(
                f"No readable spectra found{self._issue_summary(result.issues)}; "
                "existing spectra were kept."
            )
            return
        if replace:
            self.catalog.replace(result)
            self._unavailable_paths.clear()
            self._unavailable_checked.clear()
            self.spec_save_actions["embedded"].setEnabled(True)
            self._baseline_key = None
            self._plot_revision += 1
            self._checked_keys.clear()
            self._selected_keys.clear()
            self._hidden_channel_keys.clear()
            self.test_flags.clear()
            self._channel_colors.clear()
        else:
            report = self.catalog.merge(result)
            recovered = {source.key for source in result.spectra} & self._unavailable_paths.keys()
            self._checked_keys.update(recovered & self._unavailable_checked)
            for key in recovered:
                self._unavailable_paths.pop(key, None)
            self._unavailable_checked.difference_update(recovered)
            self.spec_save_actions["embedded"].setEnabled(not self._unavailable_paths)
            if report.added or report.replaced:
                self._plot_revision += 1
        self.status.clear()
        self._rebuild_tree()
        self.add_spectra_action.setEnabled(bool(self.catalog.spectra))
        self.open_map_button.setEnabled(
            any(spectrum.has_map_point for spectrum in self.catalog.spectra)
        )
        self._refresh_placeholder()
        self._refresh_plots()
        self._sync_map()

    def _refresh_placeholder(self):
        spectra = self.catalog.spectra
        self.spectra_info_button.setEnabled(self._spectra_info_source is not None and bool(spectra))
        self.test_flag_action.setEnabled(bool(spectra))
        self.copy_wkb_selection_action.setEnabled(self._workbook_selection_source is not None and bool(spectra))
        if not spectra:
            text = "Load a folder containing SME spectra."
        elif not self._checked_keys:
            text = "Check one or more spectra to draw their channels."
        else:
            text = f"{len(self._checked_keys)} spectra selected."
        self.plot_placeholder.setText(text)
        self.tree_summary.setText(
            f"{len(spectra)} spectra · {self.catalog.channel_count} channels"
            + self._issue_summary(self.catalog.issues)
        )

    @staticmethod
    def _issue_summary(issues):
        encrypted = sum(issue.status == "encrypted" for issue in issues)
        other = len(issues) - encrypted
        return ((f" · {encrypted} encrypted (decrypted SME copies required)" if encrypted else "")
                + (f" · {other} load issues" if other else ""))

    def apply_theme(self, palette):
        for panel in (*self.plot_panels.values(), self.mueller_panel):
            panel.apply_theme(palette)
        if self.catalog.spectra:
            self._refresh_plots()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "plot_panels"):
            style = theme_stylesheet()
            if self.styleSheet() != style:
                self.setStyleSheet(style)
            style_titlebar(self, get_settings()["theme"])
            self.apply_theme(self.palette())

    def visible_view_keys(self) -> tuple[str, ...]:
        return tuple(
            key for key, _label in VIEW_LABELS if self.view_actions[key].isChecked()
        )

    def _refresh_plot_layout(self):
        visible = self.visible_view_keys()
        legend_views = {
            "NCS": ("N", "C", "S"),
            "Psi Delta": ("psi_delta",),
            "Mueller": ("mueller",),
            "Reflectance": ("reflectance",),
        }
        for name, keys in legend_views.items():
            self.legend_sections[name].setVisible(any(key in visible for key in keys))
        if visible != self._plot_layout_signature:
            for splitter in (self.left_plot_splitter, self.plot_splitter):
                while splitter.count():
                    widget = splitter.widget(0)
                    widget.setParent(None)
            regular = [key for key in visible if key != "mueller"]
            for key in regular:
                widget = self.all_plot_panels[key]
                self.left_plot_splitter.addWidget(widget)
                widget.show()
            if regular:
                self.plot_splitter.addWidget(self.left_plot_splitter)
                self.left_plot_splitter.show()
                self.left_plot_splitter.reset_sizes()
            else:
                self.left_plot_splitter.hide()
            if "mueller" in visible:
                self.plot_splitter.addWidget(self.mueller_panel)
                self.mueller_panel.show()
            if regular and "mueller" in visible:
                self.plot_splitter.reset_sizes()
            self._plot_layout_signature = visible
        for panel in self.all_plot_panels.values():
            panel.setVisible(panel.parent() is not None)
        has_plots = bool(self.checked_spectra() and visible)
        self.plot_splitter.setVisible(has_plots)
        self.plot_placeholder.setVisible(
            not self.checked_spectra() or not visible
        )

    def checked_spectra(self) -> tuple[SpectrumFile, ...]:
        return tuple(
            spectrum
            for spectrum in self.catalog.spectra
            if spectrum.key in self._checked_keys
        )

    def _remember_expansion(self, item: QTreeWidgetItem, expanded: bool):
        path = self._item_path(item)
        if expanded:
            self._expanded_paths.add(path)
        else:
            self._expanded_paths.discard(path)

    def _tree_item_expanded(self, item: QTreeWidgetItem):
        self._remember_expansion(item, True)
        if item.data(0, ROLE_LEAF_GROUP):
            self._populate_spectrum_children(item)

    @classmethod
    def _item_path(cls, item: QTreeWidgetItem) -> tuple[str, ...]:
        parts = []
        while item is not None:
            parts.append(item.text(0))
            item = item.parent()
        return tuple(reversed(parts))

    def _new_group_item(self, text: str, kind: str, *, leaf=False):
        item = QTreeWidgetItem([text, *([""] * (len(TREE_COLUMNS) - 1))])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        item.setData(0, ROLE_KIND, kind)
        item.setData(0, ROLE_LEAF_GROUP, leaf)
        if leaf:
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        for column in range(len(TREE_COLUMNS)):
            item.setToolTip(column, text)
        return item

    def _grouping_changed(self):
        self._expanded_paths.clear()
        self._rebuild_tree(remember_expansion=False)

    def _rebuild_tree(self, *, remember_expansion=True):
        self._unfold_timer.stop()
        self._unfold_queue = []
        if remember_expansion:
            self._remember_all_expanded(self.tree.invisibleRootItem())
        self.tree.blockSignals(True)
        self.tree.clear()
        self.spectrum_items = {}
        self._spectrum_groups_by_key = {}
        self._all_group_items = []
        group_by = self.group_by_combo.currentData()
        fields = SPECTRUM_GROUP_FIELDS[group_by]
        header = {"wafer": "Wafer", "lot": "Lot", "pad": "PAD", "die": "Die"}[group_by]
        self.tree.headerItem().setText(0, f"{header} / Spectrum")

        def add_groups(parent, groups, depth=0):
            kind = fields[depth]
            leaf = depth == len(fields) - 1
            for value, members in groups.items():
                text = (f"Die {value}" if value is not None else "Unknown die") if kind == "die" else (
                    value or {"wafer": "Unknown wafer", "lot": "Unknown lot", "pad": "(No PAD)"}[kind])
                item = self._new_group_item(text, kind, leaf=leaf)
                parent.addChild(item)
                self._all_group_items.append(item)
                if leaf:
                    ordered = tuple(members)
                    item.setData(0, ROLE_SPECTRA, ordered)
                    for spectrum in ordered:
                        self._spectrum_groups_by_key[spectrum.key] = item
                else:
                    add_groups(item, members, depth + 1)
                self._set_aggregate_state(item)

        add_groups(self.tree.invisibleRootItem(), self.catalog.grouped(group_by))
        if self.catalog.issues:
            errors = self._new_group_item("Load errors", "errors")
            errors.setFlags(errors.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            for issue in self.catalog.issues:
                child = QTreeWidgetItem([
                    issue.path.name,
                    issue.status,
                    *([""] * (len(TREE_COLUMNS) - 2)),
                ])
                child.setText(TREE_COLUMNS.index("Folder"), str(issue.path.parent))
                for column in range(len(TREE_COLUMNS)):
                    child.setToolTip(column, f"{issue.path}\n{issue.message}")
                errors.addChild(child)
            self.tree.addTopLevelItem(errors)
        self._restore_expanded(self.tree.invisibleRootItem())
        self.tree.blockSignals(False)
        self._select_tree_keys()
        self._update_baseline_marker()
        self._refresh_placeholder()

    def build_tree_menu(self):
        menu = QMenu(self)
        menu.setObjectName("spectrumTreeMenu")
        menu.setStyleSheet("QMenu#spectrumTreeMenu::separator { height: 1px; background: palette(mid); margin: 5px 8px; }")
        menu.addAction("Check All Spectra", self.check_all_spectra)
        menu.addAction("Uncheck All Spectra", self.uncheck_all_spectra)
        menu.addSeparator()
        menu.addAction("Check Selected", self.check_selected_spectra).setEnabled(bool(self._selected_keys))
        menu.addAction("Uncheck Selected", self.uncheck_selected_spectra).setEnabled(bool(self._selected_keys))
        menu.addSeparator()
        menu.addAction("Set as BSL", self.set_selected_as_baseline).setEnabled(len(self._selected_keys) == 1)
        menu.addAction("Clear BSL", self.clear_baseline).setEnabled(self.baseline_spectrum is not None)
        menu.addSeparator()
        menu.addAction("Fold Tree", self.fold_tree)
        menu.addAction("Unfold Tree", self.unfold_tree)
        menu.addAction("Delete Tree", self.delete_selected_tree).setEnabled(
            bool(self._selected_keys) and self._loader is None)
        menu.addSeparator()
        menu.addAction("Export Checked Spectra…", self.choose_spectra_export).setEnabled(
            bool(self._checked_keys) and self._loader is None and self._exporter is None)
        return menu

    def choose_spectra_export(self):
        if self._exporter is not None or not self._checked_keys:
            return
        folder = QFileDialog.getExistingDirectory(self, "Export checked spectra")
        if folder:
            self.export_checked_spectra(folder)

    def export_checked_spectra(self, folder):
        if self._exporter is not None or self._loader is not None:
            return
        if self.export_dialog is not None:
            self.export_dialog.close()
            self.export_dialog.deleteLater()
        self.export_dialog = SpectraExportDialog([s.path for s in self.checked_spectra()], folder, self)
        self._exporter = self.export_dialog.worker
        self._exporter.progress.connect(self._export_progress)
        self._exporter.completed.connect(self._export_completed)
        self._exporter.finished.connect(self._export_finished)
        self.load_spectra_action.setEnabled(False)
        self.add_spectra_action.setEnabled(False)
        self.progress.setRange(0, len(self._checked_keys))
        self.progress.setValue(0)
        self.progress.show()
        self.cancel_load.show()
        self.status.setText("Exporting checked spectra…")
        self.export_dialog.show()
        self._exporter.start()

    def _export_progress(self, done, total, name):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.status.setText(f"Exporting {done} / {total} · {name}")

    def _export_completed(self, report):
        message = report["message"]
        self.status.setText(message)
        self.status.setToolTip(message)

    def _export_finished(self):
        worker, self._exporter = self._exporter, None
        if worker is not None:
            worker.deleteLater()
        self.progress.hide()
        self.cancel_load.hide()
        self.load_spectra_action.setEnabled(True)
        self.add_spectra_action.setEnabled(bool(self.catalog.spectra))

    def set_workbook_selection_source(self, source):
        """Bind a live source for explicit, one-time participation copying."""
        self._workbook_selection_source = source
        self.copy_wkb_selection_action.setToolTip(
            "Copy the Workbook Selection Script once, including checks, filters and view settings."
            if source is not None else "Available in a Spectra Viewer opened from Match Workbook.")
        self._refresh_placeholder()

    def set_spec_save_type(self, mode):
        if mode not in ("embedded", "paths"):
            raise ValueError("Unknown Spectra save type.")
        if mode == "embedded" and self._unavailable_paths:
            raise ValueError("Restore unavailable SME files before embedding spectra data.")
        self.spec_save_type = mode
        self.spec_save_actions[mode].setChecked(True)
        self.stateChanged.emit()

    def copy_wkb_selection(self):
        if self._workbook_selection_source is None or self._loader is not None or not self.catalog.spectra:
            return False
        spectra = self.catalog.spectra
        dialog = self._data_selection_dialog()
        try:
            copied = dialog.apply_selection_script(self._workbook_selection_source(), allow_partial=True)
            self._data_selection_view = dialog.view_state()
            checked = set(copied["checked"])
            self.set_spectrum_checks({spectrum.key: row in checked for row, spectrum in enumerate(spectra)})
        except ValueError as error:
            QMessageBox.warning(self, "Cannot copy WKB selection", str(error))
            return False
        finally:
            dialog.deleteLater()
        self.status.setText(f"Copied WKB selection to {copied['matched']} spectra; {copied['unmatched']} unmatched spectra kept their state.")
        return True

    def _data_selection_dialog(self):
        from .data_selection import FrameSelectionDialog
        from .sme_spectra import file_metadata_dataframe
        from .match_groups import participation_source_keys
        spectra = self.catalog.spectra
        frame = file_metadata_dataframe(spectra)
        ids = participation_source_keys(frame)
        excluded = [key for key, source in zip(ids, spectra) if source.key not in self._checked_keys]
        view = self._data_selection_view
        return FrameSelectionDialog(frame, excluded, self, prefix_raw=True,
                                      filters=view.get("filters"), row_bools=view.get("row_bools"),
                                      group_bools=view.get("group_bools"), show=view.get("show", "all"),
                                      search=view.get("search", ""), hide_excluded=view.get("hide_excluded", False),
                                      context=view.get("context"))

    def set_spectra_info_source(self, source):
        """Bind current original-order Raw Data and row-aligned Reference frames."""
        self._spectra_info_source = source
        self._refresh_placeholder()

    def spectra_info(self):
        from .spectra_info import build_spectra_info
        if self._spectra_info_source is None:
            raise ValueError("Spectra Info requires the source Match Workbook's Raw Data and Reference.")
        sources = self.catalog.spectra
        raw, reference = self._spectra_info_source()
        return build_spectra_info(raw, reference, sources, checked_keys=self._checked_keys,
                                  visible_keys=self._checked_keys, verify_timestamp=self.verify_spectra_time_action.isChecked(),
                                  flags=self.test_flags)

    def open_spectra_info(self):
        from .spectra_info_ui import SpectraInfoWindow
        if self.info_window is None or sip.isdeleted(self.info_window):
            self.info_window = SpectraInfoWindow(self)
        else:
            self.info_window.refresh()
        self.info_window.show()
        self.info_window.raise_()
        self.info_window.activateWindow()
        if self.info_window.problems:
            QMessageBox.warning(self.info_window, "Spectra Info matching issues",
                                "\n".join(self.info_window.problems[:8]) + "\nResolve these issues before exporting or copying.")
        return self.info_window

    def _refresh_spectra_info(self):
        if self.info_window is not None and not sip.isdeleted(self.info_window) and self.info_window.isVisible():
            self.info_window.refresh()

    def set_test_flags(self, updates):
        if any(type(value) is not int for value in updates.values()):
            raise ValueError("Test Flags must be integers.")
        valid = {source.key for source in self.catalog.spectra}
        for key, value in updates.items():
            if key in valid:
                if value not in self.test_flag_values:
                    self.test_flag_values.append(value)
                if value:
                    self.test_flags[key] = value
                else:
                    self.test_flags.pop(key, None)
        self._sync_map()
        self.stateChanged.emit()

    def open_test_flags(self):
        from .spectra_info_ui import TestFlagDialog
        dialog = TestFlagDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.test_flag_values = dialog.flag_values()
            self.test_flag_grouping = dialog.group_fields()
            self.set_test_flags(dialog.assignments)
        dialog.deleteLater()

    def open_data_selection(self):
        if not self.catalog.spectra or self._loader is not None:
            return
        dialog = self._data_selection_dialog()
        spectra = self.catalog.spectra
        ids = dialog.model.ids
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._checked_keys = {source.key for key, source in zip(ids, spectra) if key in dialog.model.checked}
            self._data_selection_view = dialog.view_state()
            self._rebuild_tree()
            self._refresh_selection_outputs()
        dialog.deleteLater()

    def _tree_context_menu(self, position):
        self.build_tree_menu().exec(self.tree.viewport().mapToGlobal(position))

    @property
    def baseline_spectrum(self):
        return next((s for s in self.catalog.spectra if s.key == self._baseline_key), None)

    def set_selected_as_baseline(self):
        if len(self._selected_keys) == 1:
            self.set_baseline(next(iter(self._selected_keys)))

    def set_baseline(self, key):
        if not any(s.key == key for s in self.catalog.spectra):
            raise ValueError("Unknown baseline spectrum")
        self._baseline_key = key
        self._update_baseline_marker()
        self.set_analysis_mode("residual")

    def clear_baseline(self):
        self._baseline_key = None
        self._update_baseline_marker()
        self._refresh_plots()

    @property
    def analysis_mode(self):
        return self._analysis_mode

    def set_analysis_mode(self, mode):
        if mode not in self.analysis_actions:
            raise ValueError("Unknown spectrum plot mode")
        if mode == "residual" and self.baseline_spectrum is None:
            return
        self._analysis_mode = mode
        self.analysis_actions[mode].setChecked(True)
        self._refresh_plots()

    def _update_baseline_marker(self):
        baseline = self.baseline_spectrum
        if baseline is None:
            self._baseline_key = None
            if self._analysis_mode == "residual":
                self._analysis_mode = "original"
            self.baseline_label.setText("BSL: —")
            self.baseline_label.setToolTip("")
        else:
            identity = baseline.identity
            self.baseline_label.setText(
                f"BSL: {identity.wafer} · {identity.lot} · {identity.pad} · {identity.display_name}")
            self.baseline_label.setToolTip(str(baseline.path))
        self.analysis_actions["residual"].setEnabled(baseline is not None)
        self.analysis_actions[self._analysis_mode].setChecked(True)
        for key, item in self.spectrum_items.items():
            font = item.font(0)
            font.setBold(key == self._baseline_key)
            item.setFont(0, font)

    def _refresh_selection_outputs(self):
        self._refresh_placeholder()
        self._refresh_plots()
        self._sync_map()

    def delete_selected_tree(self):
        if self._loader is not None or not self.catalog.remove(self._selected_keys):
            return
        remaining = {source.key for source in self.catalog.spectra}
        self._checked_keys.intersection_update(remaining)
        self.test_flags = {key: value for key, value in self.test_flags.items()
                           if key in remaining}
        self._selected_keys.clear()
        self._plot_revision += 1
        self._rebuild_tree()
        self.add_spectra_action.setEnabled(bool(self.catalog.spectra))
        self.open_map_button.setEnabled(any(s.has_map_point for s in self.catalog.spectra))
        self.status.clear()
        self._refresh_selection_outputs()

    def check_all_spectra(self):
        self._set_all_spectra_checked(True)

    def uncheck_all_spectra(self):
        self._set_all_spectra_checked(False)

    def check_selected_spectra(self):
        self._set_selected_spectra_checked(True)

    def uncheck_selected_spectra(self):
        self._set_selected_spectra_checked(False)

    def _set_selected_spectra_checked(self, checked):
        if not self._selected_keys:
            return
        self.set_spectrum_checks({key: checked for key in self._selected_keys})

    def set_spectrum_checks(self, updates):
        valid = {s.key for s in self.catalog.spectra}
        for key, checked in updates.items():
            if key in valid:
                self._checked_keys.add(key) if checked else self._checked_keys.discard(key)
        self._syncing_tree = True
        try:
            for key, item in self.spectrum_items.items():
                item.setCheckState(0, Qt.CheckState.Checked if key in self._checked_keys
                                   else Qt.CheckState.Unchecked)
            for index in range(self.tree.topLevelItemCount()):
                self._sync_item_tree(self.tree.topLevelItem(index))
        finally:
            self._syncing_tree = False
        self._refresh_selection_outputs()

    def _set_all_spectra_checked(self, checked: bool):
        keys = {spectrum.key for spectrum in self.catalog.spectra}
        self._checked_keys = keys if checked else set()
        self._syncing_tree = True
        try:
            for item in self._all_group_items:
                if item.data(0, ROLE_KIND) in GROUP_KINDS:
                    self._set_descendants(item, checked)
            for index in range(self.tree.topLevelItemCount()):
                top = self.tree.topLevelItem(index)
                if top.data(0, ROLE_KIND) in GROUP_KINDS:
                    self._sync_item_tree(top)
        finally:
            self._syncing_tree = False
        self._refresh_selection_outputs()

    def fold_tree(self):
        self._unfold_timer.stop()
        self._unfold_queue = []
        self.tree.collapseAll()
        self._expanded_paths.clear()

    def unfold_tree(self):
        self._unfold_queue = list(self._all_group_items)
        self._unfold_timer.start()

    def _unfold_next_batch(self):
        if self._unfold_queue:
            for _ in range(12):
                if not self._unfold_queue:
                    break
                item = self._unfold_queue.pop(0)
                if item.treeWidget() is self.tree:
                    item.setExpanded(True)
            if self._unfold_queue:
                self._unfold_timer.start()

    def _remember_all_expanded(self, parent: QTreeWidgetItem):
        for index in range(parent.childCount()):
            item = parent.child(index)
            path = self._item_path(item)
            if item.isExpanded():
                self._expanded_paths.add(path)
            self._remember_all_expanded(item)

    def _restore_expanded(self, parent: QTreeWidgetItem):
        for index in range(parent.childCount()):
            item = parent.child(index)
            path = self._item_path(item)
            expanded = path in self._expanded_paths
            item.setExpanded(expanded)
            if expanded and item.data(0, ROLE_LEAF_GROUP):
                self._populate_spectrum_children(item)
            self._restore_expanded(item)

    def _populate_spectrum_children(self, group_item: QTreeWidgetItem):
        if group_item.childCount():
            return
        spectra = group_item.data(0, ROLE_SPECTRA) or ()
        blocked = self.tree.blockSignals(True)
        try:
            for spectrum in spectra:
                identity = spectrum.identity
                channel_metadata = [channel.metadata for channel in spectrum.channels]
                leaf = QTreeWidgetItem([
                    identity.display_name,
                    spectrum.path.name,
                    identity.lot,
                    identity.tool_sn,
                    identity.pad,
                    "" if identity.die_seq is None else str(identity.die_seq),
                    "" if identity.field_x is None else str(identity.field_x),
                    "" if identity.field_y is None else str(identity.field_y),
                    identity.timestamp,
                    str(spectrum.path.parent),
                    self._unique_text(channel.instrument for channel in spectrum.channels),
                    self._unique_text(
                        metadata.get("mode") for metadata in channel_metadata
                    ),
                    self._unique_text(
                        metadata.get("version") for metadata in channel_metadata
                    ),
                    self._unique_text(
                        metadata.get("sample_id") for metadata in channel_metadata
                    ),
                    str(len(spectrum.channels)),
                    self._unique_text(channel.channel_id for channel in spectrum.channels),
                ])
                leaf.setFlags(leaf.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                leaf.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if spectrum.key in self._checked_keys
                    else Qt.CheckState.Unchecked,
                )
                leaf.setData(0, ROLE_KIND, "spectrum")
                leaf.setData(0, ROLE_KEY, spectrum.key)
                for column in range(len(TREE_COLUMNS)):
                    leaf.setToolTip(column, leaf.text(column))
                leaf.setToolTip(0, spectrum.embedded_filename)
                font = leaf.font(0)
                font.setBold(spectrum.key == self._baseline_key)
                leaf.setFont(0, font)
                group_item.addChild(leaf)
                leaf.setHidden(bool(self._data_selection_view.get("hide_excluded") and spectrum.key not in self._checked_keys))
                self.spectrum_items[spectrum.key] = leaf
        finally:
            self.tree.blockSignals(blocked)

    @staticmethod
    def _unique_text(values) -> str:
        result = []
        for value in values:
            text = "" if value is None else str(value)
            if text and text not in result:
                result.append(text)
        return ", ".join(result)

    def _tree_item_changed(self, item: QTreeWidgetItem, column: int):
        if column or self._syncing_tree:
            return
        kind = item.data(0, ROLE_KIND)
        self._syncing_tree = True
        try:
            if kind == "spectrum":
                key = item.data(0, ROLE_KEY)
                if item.checkState(0) == Qt.CheckState.Checked:
                    self._checked_keys.add(key)
                else:
                    self._checked_keys.discard(key)
                self._sync_parents(item)
            elif kind in GROUP_KINDS:
                checked = item.checkState(0) == Qt.CheckState.Checked
                self._set_descendants(item, checked)
                self._sync_parents(item)
        finally:
            self._syncing_tree = False
        self._refresh_placeholder()
        self._refresh_plots()
        self._sync_map()

    def _set_descendants(self, item: QTreeWidgetItem, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        kind = item.data(0, ROLE_KIND)
        if item.data(0, ROLE_LEAF_GROUP):
            for spectrum in item.data(0, ROLE_SPECTRA) or ():
                if checked:
                    self._checked_keys.add(spectrum.key)
                else:
                    self._checked_keys.discard(spectrum.key)
            for index in range(item.childCount()):
                item.child(index).setCheckState(0, state)
            item.setCheckState(0, state)
            return
        for index in range(item.childCount()):
            child = item.child(index)
            if child.data(0, ROLE_KIND) == "spectrum":
                child.setCheckState(0, state)
                key = child.data(0, ROLE_KEY)
                if checked:
                    self._checked_keys.add(key)
                else:
                    self._checked_keys.discard(key)
            elif child.data(0, ROLE_KIND) in GROUP_KINDS:
                self._set_descendants(child, checked)
                child.setCheckState(0, state)

    def _sync_item_tree(self, item: QTreeWidgetItem):
        for index in range(item.childCount()):
            self._sync_item_tree(item.child(index))
        self._set_aggregate_state(item)

    def _sync_parents(self, item: QTreeWidgetItem):
        parent = item.parent()
        while parent is not None:
            self._set_aggregate_state(parent)
            parent = parent.parent()

    def _set_aggregate_state(self, item: QTreeWidgetItem):
        kind = item.data(0, ROLE_KIND)
        if kind not in GROUP_KINDS:
            return
        if item.data(0, ROLE_LEAF_GROUP) and item.data(0, ROLE_SPECTRA):
            spectra = item.data(0, ROLE_SPECTRA)
            checked = sum(spectrum.key in self._checked_keys for spectrum in spectra)
            if checked == len(spectra):
                state = Qt.CheckState.Checked
            elif checked:
                state = Qt.CheckState.PartiallyChecked
            else:
                state = Qt.CheckState.Unchecked
            item.setCheckState(0, state)
            return
        states = [item.child(index).checkState(0) for index in range(item.childCount())]
        if states and all(state == Qt.CheckState.Checked for state in states):
            state = Qt.CheckState.Checked
        elif any(state != Qt.CheckState.Unchecked for state in states):
            state = Qt.CheckState.PartiallyChecked
        else:
            state = Qt.CheckState.Unchecked
        item.setCheckState(0, state)

    def _color_for(self, key: WaferChannelKey) -> QColor:
        color = self._channel_colors.get(key)
        if color is None:
            index = len(self._channel_colors)
            if index < len(CHANNEL_COLORS):
                color = QColor(CHANNEL_COLORS[index])
            else:
                used = {value.name() for value in self._channel_colors.values()}
                candidate = index
                while True:
                    hue = (0.05 + (candidate - len(CHANNEL_COLORS)) * 0.61803398875) % 1.0
                    saturation = .65 + .25 * ((candidate * .41421356237) % 1.0)
                    value = .7 + .2 * ((candidate * .73205080757) % 1.0)
                    color = QColor.fromHsvF(hue, saturation, value)
                    if color.name() not in used:
                        break
                    candidate += 1
            self._channel_colors[key] = color
        return color

    @property
    def color_mode(self):
        # A 3σ curve represents multiple files, so retain one wafer/channel key.
        return "wafer" if self._analysis_mode == "3sigma" else self._color_mode

    def set_color_mode(self, mode):
        if mode not in ("wafer", "sme"):
            raise ValueError("Unknown spectrum color mode")
        self._color_mode = mode
        self._refresh_plots()

    def _color_key(self, spectrum, channel):
        if self._color_key_revision != self._plot_revision:
            self._color_key_revision = self._plot_revision
            self._color_keys.clear()
            self._color_order.clear()
        cache_key = id(spectrum), id(channel), self.color_mode
        cached = self._color_keys.get(cache_key)
        if cached is not None:
            return cached
        identity = spectrum.identity
        individual = self.color_mode == "sme"
        key = WaferChannelKey(identity.wafer, channel.key, identity.lot, identity.pad,
                              spectrum.key if individual else "", spectrum.path.name if individual else "")
        self._color_keys[cache_key] = key
        if key not in self._color_order:
            self._color_order[key] = key.sort_key
        return key

    def _segments_for(self, metric: str) -> dict[WaferChannelKey, list[CurveSegment]]:
        revision = self._plot_revision, self._baseline_key
        if revision != self._analysis_cache_revision:
            self._analysis_cache_revision = revision
            self._residual_cache.clear()
            self._sigma_cache.clear()
            self._analysis_segments.clear()
        signature = revision, self._analysis_mode, self.color_mode, frozenset(self._checked_keys)
        cached = self._analysis_segments.get(metric)
        if self._analysis_mode != "original" and cached is not None and cached[0] == signature:
            self._analysis_notes.update(cached[2])
            return cached[1]
        groups: dict[WaferChannelKey, list[CurveSegment]] = {}
        notes = {}
        baseline = self.baseline_spectrum if self._analysis_mode == "residual" else None
        for spectrum in self.checked_spectra():
            for channel in spectrum.channels:
                values = channel.series(metric)
                if values is None:
                    continue
                x = channel.wavelength
                if self._analysis_mode == "residual":
                    cache_key = spectrum.key, id(channel), metric
                    if cache_key not in self._residual_cache:
                        try:
                            self._residual_cache[cache_key] = residual_series(channel, baseline.channels, metric)
                        except ValueError as error:
                            self._residual_cache[cache_key] = str(error)
                    result = self._residual_cache[cache_key]
                    if isinstance(result, str):
                        notes[spectrum.key, channel.key, metric] = f"{spectrum.path.name} · {metric}: {result}"
                        continue
                    x, values = result.wavelength, result.values
                groups.setdefault(self._color_key(spectrum, channel), []).append(
                    CurveSegment(
                        spectrum.key,
                        x,
                        values,
                    )
                )
        if self._analysis_mode == "3sigma":
            aggregated = {}
            for key, segments in groups.items():
                membership = tuple(s.spectrum_key for s in segments)
                cache_key = metric, key
                previous = self._sigma_cache.get(cache_key)
                if previous is None or previous[0] != membership:
                    try:
                        result = three_sigma_series(SpectralSeries(s.x, s.y) for s in segments)
                    except ValueError as error:
                        result = str(error)
                    self._sigma_cache[cache_key] = membership, result
                result = self._sigma_cache[cache_key][1]
                if isinstance(result, str):
                    notes[key, metric] = f"{key.legend_label} · {metric}: {result}"
                    continue
                aggregated[key] = [CurveSegment(f"3sigma:{key!r}", result.wavelength, result.values,
                                                frozenset(membership))]
            groups = aggregated
        if self._analysis_mode != "original":
            self._analysis_segments[metric] = signature, groups, notes
            self._analysis_notes.update(notes)
        return groups

    def _curve_groups(
        self,
        segments: dict[WaferChannelKey, list[CurveSegment]],
        colors,
    ) -> list[CurveGroup]:
        return [
            CurveGroup(key, colors(key), tuple(values))
            for key, values in sorted(
                segments.items(),
                key=lambda pair: self._color_order[pair[0]],
            )
            if values
        ]

    def _refresh_legend(self, legend: QListWidget, channel_keys: list[WaferChannelKey]):
        current = [
            legend.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(legend.count())
        ]
        if current != channel_keys:
            legend.blockSignals(True)
            desired = set(channel_keys)
            for index in range(legend.count() - 1, -1, -1):
                if legend.item(index).data(Qt.ItemDataRole.UserRole) not in desired:
                    legend.takeItem(index)
            retained = {legend.item(i).data(Qt.ItemDataRole.UserRole): legend.item(i)
                        for i in range(legend.count())}
            for index, key in enumerate(channel_keys):
                item = retained.get(key)
                if item is None:
                    item = QListWidgetItem(_line_icon(self._color_for(key)), key.legend_label)
                    item.setSizeHint(QSize(320, 22))
                    item.setData(Qt.ItemDataRole.UserRole, key)
                    legend.insertItem(index, item)
                elif legend.row(item) != index:
                    legend.takeItem(legend.row(item))
                    legend.insertItem(index, item)
            legend.blockSignals(False)
        for index, key in enumerate(channel_keys):
            item = legend.item(index)
            angle = self._angle_two(key)
            info = f"{self._analysis_mode}:{angle}"
            if item.data(Qt.ItemDataRole.UserRole + 2) != info:
                item.setToolTip(
                f"{key.legend_label}\nDouble-click to hide or restore this wafer/channel in all plots.\n"
                f"Source: {key.spectrum_key or ' · '.join((key.wafer, key.lot, key.pad))}\n"
                f"Angle 2: {angle}\n"
                + ("3σ = 3 × sample SD (n−1), per Wafer/channel; n ≥ 2 at each exact wavelength."
                   if self._analysis_mode == "3sigma" else
                   "Residual = measured − BSL at exact wavelengths; no interpolation or phase wrapping."
                   if self._analysis_mode == "residual" else "Original measured spectrum.")
                )
                item.setData(Qt.ItemDataRole.UserRole + 2, info)
            hidden = key in self._hidden_channel_keys
            foreground = QColor("#77747c") if hidden else self._foreground_color()
            style = f"{hidden}:{foreground.name()}"
            if item.data(Qt.ItemDataRole.UserRole + 1) != style:
                item.setForeground(foreground)
                font = item.font()
                font.setStrikeOut(hidden)
                item.setFont(font)
                item.setData(Qt.ItemDataRole.UserRole + 1, style)

    def _foreground_color(self) -> QColor:
        return (
            QColor("#d8d3df")
            if self.palette().color(QPalette.ColorRole.Window).lightness() < 128
            else QColor("#2b2730")
        )

    def _sync_legend_selection(self):
        selected = {
            self._color_key(spectrum, channel)
            for spectrum in self.checked_spectra()
            if spectrum.key in self._selected_keys
            for channel in spectrum.channels
        }
        for legend in self.legends.values():
            blocked = legend.blockSignals(True)
            first_new = None
            for index in range(legend.count()):
                item = legend.item(index)
                key = item.data(Qt.ItemDataRole.UserRole)
                active = key in selected
                font = item.font()
                if item.isSelected() != active or font.bold() != active:
                    legend.selectionModel().select(
                        legend.indexFromItem(item),
                        QItemSelectionModel.SelectionFlag.Select if active
                        else QItemSelectionModel.SelectionFlag.Deselect,
                    )
                    font.setBold(active)
                    item.setFont(font)
                    item.setIcon(_line_icon(self._color_for(key), selected=active))
                    if active and first_new is None:
                        first_new = item
            legend.blockSignals(blocked)
            if first_new is not None:
                legend.scrollToItem(first_new)

    def _angle_two(self, key: WaferChannelKey) -> str:
        angle = self._legend_angles.get(key)
        return "?" if angle is None else f"{float(angle):g}°"

    def _refresh_plots(self):
        self._refresh_tree_visibility()
        if self._pending_plot_updates:
            self._cancel_plot_paints()
        checked = self.checked_spectra()
        blocked = self.color_by_combo.blockSignals(True)
        self.color_by_combo.setCurrentIndex(self.color_by_combo.findData(self.color_mode))
        self.color_by_combo.blockSignals(blocked)
        self.color_by_combo.setEnabled(self._analysis_mode != "3sigma")
        self.color_by_combo.setToolTip(
            "3σ summarizes checked files per Wafer/channel; colors remain per Wafer/channel."
            if self._analysis_mode == "3sigma" else "Color by Wafer ID/Lot/PAD or by individual SME file, with distinct channel colors.")
        self._legend_angles = {}
        available = {self._color_key(s, c)
                     for s in self.catalog.spectra for c in s.channels}
        for key in sorted(available, key=lambda key: self._color_order[key]):
            self._color_for(key)
        large = self.isVisible() and sum(channel.numeric.size for spectrum in checked
                                        for channel in spectrum.channels) > 1_000_000
        visible_views = set(self.visible_view_keys())
        self._analysis_notes = {}
        channel_keys: dict[WaferChannelKey, None] = {}
        legend_keys = {name: set() for name in LEGEND_METRICS}
        for spectrum in checked:
            for channel in spectrum.channels:
                key = self._color_key(spectrum, channel)
                self._legend_angles.setdefault(key, channel.metadata.get("angle_2_deg"))
                channel_keys.setdefault(key, None)
                for name, metrics in LEGEND_METRICS.items():
                    if key not in legend_keys[name] and any(
                        channel.series(metric) is not None for metric in metrics
                    ):
                        legend_keys[name].add(key)
        if self._analysis_mode != "original":
            active_metrics = visible_views - {"psi_delta", "mueller"}
            if "psi_delta" in visible_views:
                active_metrics.update(("psi", "delta"))
            if "mueller" in visible_views:
                active_metrics.update(M_COLS)
            legend_keys = {name: {key for metric in metrics if metric in active_metrics
                                  for key in self._segments_for(metric)}
                           for name, metrics in LEGEND_METRICS.items()}
            channel_keys = {key: None for keys in legend_keys.values() for key in keys}
        ordered_keys = sorted(channel_keys, key=lambda key: self._color_order[key])
        for key in ordered_keys:
            self._color_for(key)
        for name, legend in self.legends.items():
            self._refresh_legend(legend, [key for key in ordered_keys if key in legend_keys[name]])
        self._sync_legend_selection()
        selected = set(self._selected_keys)
        colors = self._color_for
        families = {"N": "NCS", "C": "NCS", "S": "NCS", "psi_delta": "Psi Delta",
                    "mueller": "Mueller", "reflectance": "Reflectance"}
        signatures = {
            key: (self._plot_revision, frozenset(self._checked_keys), self._analysis_mode, self.color_mode,
                  self._baseline_key if self._analysis_mode == "residual" else None)
            for key, family in families.items()
        }
        changed_panels = []

        def update_panel(panel, primary, secondary=None):
            if large:
                self._pending_plot_updates[panel] = (primary, secondary)
            else:
                panel.set_curves(primary(), secondary=secondary() if secondary else None, selected_keys=selected,
                                 hidden_keys=self._hidden_channel_keys)
            changed_panels.append(panel)

        def curves_for(metric):
            return lambda: self._curve_groups(self._segments_for(metric), colors)

        for metric in ("N", "C", "S", "reflectance"):
            if metric not in visible_views or self._rendered_view_signatures.get(metric) == signatures[metric]:
                continue
            update_panel(self.plot_panels[metric], curves_for(metric))
            self._rendered_view_signatures[metric] = signatures[metric]

        if "psi_delta" in visible_views and self._rendered_view_signatures.get("psi_delta") != signatures["psi_delta"]:
            update_panel(self.plot_panels["psi_delta"],
                curves_for("psi"), curves_for("delta"),
            )
            self._rendered_view_signatures["psi_delta"] = signatures["psi_delta"]

        if "mueller" in visible_views and self._rendered_view_signatures.get("mueller") != signatures["mueller"]:
            for name, panel in self.mueller_panel.mij_plots.items():
                update_panel(panel, curves_for(name))
            self._rendered_view_signatures["mueller"] = signatures["mueller"]
        for panel in (*self.plot_panels.values(), *self.mueller_panel.mij_plots.values()):
            panel.set_analysis_mode(self._analysis_mode)
            if large and panel._hidden_keys != self._hidden_channel_keys:
                if panel not in self._pending_plot_updates:
                    self._pending_plot_updates[panel] = None
                    changed_panels.append(panel)
            elif not large:
                panel.set_hidden_keys(self._hidden_channel_keys)
        self._refresh_plot_layout()
        self._sync_floating_plots()
        if checked and not self.visible_view_keys():
            self.plot_placeholder.setText("Choose at least one view.")
        if self._loader is None:
            if self._analysis_notes:
                self.status.setText(f"Analysis: {len(self._analysis_notes)} channel/metric results unavailable (hover for details).")
                self.status.setToolTip("\n".join(list(dict.fromkeys(self._analysis_notes.values()))[:30]))
            elif self.status.text().startswith("Analysis:"):
                self.status.clear()
                self.status.setToolTip("")
        if changed_panels:
            self._schedule_plot_paints(changed_panels, large)
        self.stateChanged.emit()

    def _refresh_tree_visibility(self):
        hide = bool(self._data_selection_view.get("hide_excluded", False))
        if not hide and not getattr(self, "_tree_hiding_excluded", False):
            return
        self._tree_hiding_excluded = hide
        for key, item in self.spectrum_items.items():
            item.setHidden(hide and key not in self._checked_keys)
        for item in self._all_group_items:
            item.setHidden(hide and item.checkState(0) == Qt.CheckState.Unchecked)

    def _queue_plot_resize(self, panel):
        # Qt must keep painting the backing store while a window is exposed.
        # The curve cache coalesces geometry work and keeps its previous image.
        self._resizing_panels.add(panel)
        self._resize_paint_timer.start()

    def _flush_plot_resizes(self):
        panels = [panel for panel in self._resizing_panels if not sip.isdeleted(panel)]
        self._resizing_panels.clear()
        for panel in panels:
            panel.plot.viewport().update()

    def _schedule_plot_paints(self, panels, large):
        remaining = [panel for panel in self._pending_plot_paints if not sip.isdeleted(panel)]
        self._cancel_plot_paints(discard_updates=False)
        if self.isVisible() and large:
            self._pending_plot_paints = list(dict.fromkeys((*remaining, *panels)))
            self._plot_status_base = self.status.text()
            self._plot_paint_total = len(self._pending_plot_paints)
            for panel in self._pending_plot_paints:
                panel.plot.setUpdatesEnabled(False)
            self._plot_paint_timer.start(0)

    @property
    def plot_render_pending(self):
        return (bool(self._resizing_panels) or bool(self._pending_plot_paints) or self._plot_paint_timer.isActive()
                or any(panel.render_pending for panel in
                       (*self.plot_panels.values(), *self.mueller_panel.mij_plots.values(),
                        *(window.panel for window in self.floating_plot_windows.values()))
                       if panel.isVisible()))

    def _cancel_plot_paints(self, *, discard_updates=True):
        self._plot_paint_timer.stop()
        for panel in self._pending_plot_paints:
            if not sip.isdeleted(panel):
                panel.plot.setUpdatesEnabled(True)
        self._pending_plot_paints = []
        if discard_updates and self._pending_plot_updates:
            self._pending_plot_updates.clear()
            self._rendered_view_signatures.clear()
        if self.status.text().startswith("Drawing "):
            self.status.setText(self._plot_status_base)

    def _paint_next_plot(self):
        if not self._pending_plot_paints:
            if any(panel.render_pending for panel in
                   (*self.plot_panels.values(), *self.mueller_panel.mij_plots.values())
                   if panel.isVisible()):
                self._plot_paint_timer.start(16)
            elif self.status.text().startswith("Drawing "):
                self.status.setText(self._plot_status_base)
            return
        panel = self._pending_plot_paints.pop(0)
        if not sip.isdeleted(panel):
            if panel in self._pending_plot_updates:
                update = self._pending_plot_updates.pop(panel)
                if update is None:
                    panel.set_hidden_keys(self._hidden_channel_keys)
                    panel.set_selected_keys(self._selected_keys)
                else:
                    panel.set_curves(update[0](), secondary=update[1]() if update[1] else None, selected_keys=self._selected_keys,
                                     hidden_keys=self._hidden_channel_keys)
                floating = self.floating_plot_windows.get(panel)
                if floating is not None and not sip.isdeleted(floating):
                    floating.sync_from(panel)
            panel.plot.setUpdatesEnabled(True)
        if self._loader is None:
            done = self._plot_paint_total - len(self._pending_plot_paints)
            self.status.setText(f"Drawing {done} / {self._plot_paint_total} plots…")
        self._plot_paint_timer.start(0 if self._pending_plot_paints else 16)

    def open_plot_window(self, source: SpectrumPlotPanel):
        window = self.floating_plot_windows.get(source)
        if window is not None and not sip.isdeleted(window):
            window.sync_from(source)
            window.show()
            window.raise_()
            window.activateWindow()
            return window
        window = FloatingPlotWindow(source)
        window.panel.spectraSelected.connect(self.select_spectrum_keys)
        self.floating_plot_windows[source] = window
        window.destroyed.connect(
            lambda _=None, panel=source: self.floating_plot_windows.pop(panel, None)
        )
        window.show()
        window.raise_()
        window.activateWindow()
        return window

    def _sync_floating_plots(self):
        for source, window in list(self.floating_plot_windows.items()):
            if sip.isdeleted(source) or sip.isdeleted(window):
                self.floating_plot_windows.pop(source, None)
                continue
            if source in self._pending_plot_updates:
                continue
            window.sync_from(source)

    def _legend_double_clicked(self, item: QListWidgetItem):
        key = item.data(Qt.ItemDataRole.UserRole)
        self.toggle_channel(key)

    def show_all_channels(self, section):
        legend = self.legends[section]
        keys = {legend.item(index).data(Qt.ItemDataRole.UserRole) for index in range(legend.count())}
        if self._hidden_channel_keys & keys:
            self._hidden_channel_keys.difference_update(keys)
            self._refresh_plots()

    def build_legend_menu(self, section):
        menu = QMenu(self.legends[section])
        legend = self.legends[section]
        keys = {legend.item(index).data(Qt.ItemDataRole.UserRole) for index in range(legend.count())}
        menu.addAction("Show All", lambda: self.show_all_channels(section)).setEnabled(bool(keys & self._hidden_channel_keys))
        menu.addAction("Hide All", lambda: self.hide_all_channels(section)).setEnabled(bool(keys - self._hidden_channel_keys))
        select = _ViewMenu("Select Channel", menu)
        menu.addMenu(select).setEnabled(bool(keys))
        channel_actions = {}
        for channel in sorted({key.channel for key in keys}, key=lambda channel: channel.sort_key):
            action = select.addAction(channel.legend_label)
            action.setCheckable(True)
            action.setToolTip("Show or hide this channel across all wafers and plots. Spectrum checks stay unchanged.")
            action.triggered.connect(lambda visible, key=channel: self.set_channel_visible(key, visible))
            channel_actions[channel] = action

        def sync_actions(_checked=False):
            menu.actions()[0].setEnabled(bool(keys & self._hidden_channel_keys))
            menu.actions()[1].setEnabled(bool(keys - self._hidden_channel_keys))
            for channel, action in channel_actions.items():
                action.setChecked(any(key.channel == channel and key not in self._hidden_channel_keys for key in keys))

        for action in (*menu.actions()[:2], *channel_actions.values()):
            action.triggered.connect(sync_actions)
        menu.aboutToShow.connect(sync_actions)
        select.aboutToShow.connect(sync_actions)
        sync_actions()
        return menu

    def hide_all_channels(self, section):
        legend = self.legends[section]
        keys = {legend.item(index).data(Qt.ItemDataRole.UserRole) for index in range(legend.count())}
        if keys - self._hidden_channel_keys:
            self._hidden_channel_keys.update(keys)
            self._refresh_plots()

    def toggle_channel(self, key: ChannelKey | WaferChannelKey):
        self.set_channel_visible(key, self.channel_hidden(key))

    def set_channel_visible(self, key: ChannelKey | WaferChannelKey, visible: bool):
        keys = ({key} if isinstance(key, WaferChannelKey) else {
            self._color_key(s, c) for s in self.catalog.spectra
            for c in s.channels if c.key == key})
        if visible:
            self._hidden_channel_keys.difference_update(keys)
        else:
            self._hidden_channel_keys.update(keys)
        self._refresh_plots()

    def channel_hidden(self, key: ChannelKey | WaferChannelKey) -> bool:
        if isinstance(key, WaferChannelKey):
            return key in self._hidden_channel_keys
        keys = {self._color_key(s, c) for s in self.catalog.spectra
                for c in s.channels if c.key == key}
        return bool(keys) and keys <= self._hidden_channel_keys

    def _show_view_menu(self, global_position):
        menu = _ViewMenu(self)
        for key, _label in VIEW_LABELS:
            menu.addAction(self.view_actions[key])
        menu.exec(global_position)

    def _view_visibility_changed(self, _checked: bool):
        self._refresh_plots()

    def _tree_selection_changed(self):
        if self._syncing_selection or self._syncing_tree:
            return
        keys = set()
        for item in self.tree.selectedItems():
            self._spectrum_descendants(item, keys)
        self.select_spectrum_keys(keys, sync_tree=False)

    def _spectrum_descendants(self, item: QTreeWidgetItem, keys: set[str]):
        kind = item.data(0, ROLE_KIND)
        if kind == "spectrum":
            keys.add(item.data(0, ROLE_KEY))
            return
        if item.data(0, ROLE_LEAF_GROUP):
            for spectrum in item.data(0, ROLE_SPECTRA) or ():
                keys.add(spectrum.key)
            return
        for index in range(item.childCount()):
            child = item.child(index)
            self._spectrum_descendants(child, keys)

    def select_spectrum_keys(self, keys, *, sync_tree=True):
        valid_keys = {spectrum.key for spectrum in self.catalog.spectra}
        selected = {str(key) for key in keys} & valid_keys
        changed = selected != self._selected_keys
        self._selected_keys = selected
        if sync_tree:
            self._select_tree_keys()
        self._sync_legend_selection()
        large = sum(channel.numeric.size for spectrum in self.checked_spectra()
                    if spectrum.key in selected for channel in spectrum.channels) > 1_000_000
        for panel in (*self.plot_panels.values(), *self.mueller_panel.mij_plots.values()):
            if changed and ((large and self.isVisible()) or panel in self._pending_plot_updates):
                self._pending_plot_updates.setdefault(panel, None)
            else:
                panel.set_selected_keys(self._selected_keys)
        for window in self.floating_plot_windows.values():
            window.panel.set_selected_keys(self._selected_keys)
        if changed and (large or self.plot_render_pending):
            self._schedule_plot_paints((*self.plot_panels.values(), *self.mueller_panel.mij_plots.values()), True)
        self._sync_map()

    def _select_tree_keys(self):
        self._syncing_selection = True
        self.tree.clearSelection()
        self.tree.setCurrentItem(None)
        first = None
        for key in self._selected_keys:
            if key in self.spectrum_items:
                continue
            group_item = self._spectrum_groups_by_key.get(key)
            if group_item is None:
                continue
            ancestors = []
            parent = group_item
            while parent is not None:
                ancestors.append(parent)
                parent = parent.parent()
            for ancestor in reversed(ancestors):
                ancestor.setExpanded(True)
            self._populate_spectrum_children(group_item)
        for key, item in self.spectrum_items.items():
            item.setSelected(key in self._selected_keys)
            if key in self._selected_keys and first is None:
                first = item
        if first is not None:
            self.tree.setCurrentItem(first, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
            self.tree.scrollToItem(first)
        self._syncing_selection = False

    def open_wafer_map(self):
        if self.map_window is not None and not sip.isdeleted(self.map_window):
            self._sync_map()
            self.map_window.show()
            self.map_window.raise_()
            self.map_window.activateWindow()
            return self.map_window
        self.map_window = SpectraMapWindow(pin_owner=self)
        self.map_window.spectra_selected.connect(self.select_spectrum_keys)
        self.map_window.check_selected_requested.connect(self.check_selected_spectra)
        self.map_window.uncheck_selected_requested.connect(self.uncheck_selected_spectra)
        self.map_window.checks_changed.connect(self.set_spectrum_checks)
        self.map_window.test_flags_changed.connect(self.set_test_flags)
        self.map_window.destroyed.connect(self._map_window_destroyed)
        self._sync_map()
        self.map_window.show()
        self.map_window.raise_()
        self.map_window.activateWindow()
        return self.map_window

    def _map_window_destroyed(self, *_args):
        self.map_window = None
        self._map_data_signature = None

    def _sync_map(self):
        if self.map_window is None or sip.isdeleted(self.map_window):
            return
        self.map_window.update_test_flags(self.test_flags, flag_values=self.test_flag_values)
        signature = (
            tuple(
                (spectrum.key, id(spectrum))
                for spectrum in self.catalog.spectra
            ),
        )
        if signature == self._map_data_signature:
            self.map_window.update_checks(self._checked_keys, selected_keys=self._selected_keys)
            return
        self.map_window.set_data(
            self.catalog.spectra,
            checked_keys=self._checked_keys,
            selected_keys=self._selected_keys,
        )
        self._map_data_signature = signature

    def mousePressEvent(self, event):
        child = self.childAt(event.position().toPoint())
        while child is not None and child is not self:
            if isinstance(child, QAbstractScrollArea):
                return super().mousePressEvent(event)
            child = child.parentWidget()
        if event.button() == Qt.MouseButton.LeftButton:
            self.select_spectrum_keys(set())
        super().mousePressEvent(event)

    def closeEvent(self, event):
        if not getattr(self, "_workbook_child", False) and not self.document.confirm_close():
            event.ignore()
            return
        self._resize_paint_timer.stop()
        self._info_refresh_timer.stop()
        if self.info_window is not None and not sip.isdeleted(self.info_window):
            self.info_window.close()
        for panel in self._resizing_panels:
            if not sip.isdeleted(panel):
                panel.plot.setUpdatesEnabled(True)
        self._resizing_panels.clear()
        self._cancel_plot_paints()
        if self._exporter is not None:
            self._exporter.requestInterruption()
            self._exporter.wait()
        if self.export_dialog is not None:
            self.export_dialog.close()
        for panel in (*self.plot_panels.values(), *self.mueller_panel.mij_plots.values()):
            panel.cancel_rendering()
        if self._loader is not None:
            self._loader.requestInterruption()
            if not self._loader.wait(2000):
                self._loader.wait()
        if self.map_window is not None and not sip.isdeleted(self.map_window):
            self.map_window.close()
            self.map_window = None
        for window in tuple(self.floating_plot_windows.values()):
            if not sip.isdeleted(window):
                window.close()
        self.floating_plot_windows.clear()
        callback = getattr(self, "_workbook_on_close", None)
        if callable(callback):
            callback(self)
        self._workbook_selection_source = None
        self._spectra_workbook_owner = None
        self.document.closed()
        super().closeEvent(event)

