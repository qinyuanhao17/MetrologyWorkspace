"""Independent Help reader: topic tree, local pages, navigation and reload."""
from pathlib import Path

from PyQt6.QtCore import QSignalBlocker, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QTextDocument
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton, QSplitter,
    QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .appearance import fit_window_to_screen, style_titlebar
from .help_content import help_directory, load_help_contents, resolve_help_file
from .settings import apply_theme, get_settings


class HelpWindow(QMainWindow):
    def __init__(self, parent=None, *, directory=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.directory = Path(directory if directory is not None else help_directory()).resolve()
        self.contents = None
        self._page_items = {}
        self.setWindowTitle("Help")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._build_ui()
        fit_window_to_screen(self, (1120, 800), minimum=(780, 520))
        self.apply_help_theme()
        self.reload_help()

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)
        actions = QHBoxLayout()
        actions.addWidget(QLabel("Help", objectName="panelTitle"))
        actions.addStretch()
        self.back_button = QPushButton("Back")
        self.forward_button = QPushButton("Forward")
        self.home_button = QPushButton("Home")
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setToolTip("Reload the topic tree and current page after editing the files (F5).")
        self.refresh_button.setShortcut("F5")
        self.folder_button = QPushButton("Open help folder")
        self.folder_button.setToolTip(str(self.directory))
        for button in (self.back_button, self.forward_button, self.home_button,
                       self.refresh_button, self.folder_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.error_label = QLabel(objectName="hint")
        self.error_label.setWordWrap(True)
        self.error_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        navigation = QFrame(objectName="componentCard")
        navigation_layout = QVBoxLayout(navigation)
        navigation_layout.setContentsMargins(12, 12, 12, 12)
        navigation_layout.addWidget(QLabel("Contents", objectName="panelTitle"))
        self.topic_filter = QLineEdit()
        self.topic_filter.setPlaceholderText("Filter topic titles…")
        self.topic_filter.setClearButtonEnabled(True)
        navigation_layout.addWidget(self.topic_filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(190)
        navigation_layout.addWidget(self.tree, 1)
        splitter.addWidget(navigation)

        self.browser = QTextBrowser(objectName="helpBrowser")
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.setSearchPaths([str(self.directory)])
        self.browser.document().setDocumentMargin(22)
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 800])
        layout.addWidget(splitter, 1)
        self.setCentralWidget(root)
        self.back_button.setEnabled(False)
        self.forward_button.setEnabled(False)
        self.back_button.clicked.connect(self.browser.backward)
        self.forward_button.clicked.connect(self.browser.forward)
        self.browser.backwardAvailable.connect(self.back_button.setEnabled)
        self.browser.forwardAvailable.connect(self.forward_button.setEnabled)
        self.browser.anchorClicked.connect(self._follow_link)
        self.browser.sourceChanged.connect(self._source_changed)
        self.home_button.clicked.connect(self.go_home)
        self.refresh_button.clicked.connect(self.reload_help)
        self.folder_button.clicked.connect(self.open_help_folder)
        self.tree.currentItemChanged.connect(self._topic_selected)
        self.topic_filter.textChanged.connect(self._filter_topics)

    def apply_help_theme(self, theme=None):
        theme = theme or get_settings()["theme"]
        apply_theme(self, theme)
        style_titlebar(self, theme)
        light = theme == "light"
        foreground = "#18181b" if light else "#e7e0eb"
        background = "#ffffff" if light else "#0d0814"
        border = "#d9d9de" if light else "#302538"
        accent = "#2563eb" if light else "#c99bea"
        self.browser.setStyleSheet(
            f"QTextBrowser#helpBrowser {{ color: {foreground}; background: {background}; "
            f"border: 1px solid {border}; border-radius: 8px; }}")
        self.browser.document().setDefaultStyleSheet(
            f"body {{ color: {foreground}; }} a {{ color: {accent}; }} "
            f"th, td {{ border: 1px solid {border}; padding: 6px; }} "
            "h1 { font-size: 24px; } h2 { font-size: 19px; } h3 { font-size: 16px; } "
            "p, li { line-height: 1.5; } code, pre { font-family: Consolas, monospace; }")
        if self.browser.source().isLocalFile():
            scroll = self.browser.verticalScrollBar().value()
            self.browser.reload()
            self.browser.verticalScrollBar().setValue(scroll)

    def _error(self, message):
        self.error_label.setText(message)
        self.error_label.show()
        self.statusBar().showMessage("Help content could not be loaded. Edit the files and click Refresh.")

    def reload_help(self):
        previous = Path(self.browser.source().toLocalFile()) if self.browser.source().isLocalFile() else None
        selected = self.tree.currentItem()
        if selected is not None and selected.data(0, Qt.ItemDataRole.UserRole):
            previous = Path(selected.data(0, Qt.ItemDataRole.UserRole))
        try:
            contents = load_help_contents(self.directory)
        except ValueError as error:
            self._error(str(error))
            if self.contents is None:
                self.browser.setPlainText("Help content is unavailable.\n\n" + str(error))
            return
        self.contents = contents
        self.error_label.hide()
        self._page_items.clear()
        with QSignalBlocker(self.tree):
            self.tree.clear()
            def add(parent, topics):
                for topic in topics:
                    item = QTreeWidgetItem(parent, [topic.title])
                    if topic.file is not None:
                        item.setData(0, Qt.ItemDataRole.UserRole, str(topic.file))
                        item.setToolTip(0, str(topic.file.relative_to(self.directory)))
                        self._page_items.setdefault(topic.file, item)
                    add(item, topic.children)
            add(self.tree, contents.topics)
            self.tree.expandToDepth(0)
        self._filter_topics(self.topic_filter.text())
        target = previous if previous is not None and (previous in self._page_items or previous.is_file()) else contents.home
        self._load_page(target)

    def _load_page(self, path, fragment=""):
        try:
            path = Path(path).resolve()
            relative = path.relative_to(self.directory).as_posix()
            path = resolve_help_file(self.directory, relative)
            # Surface missing/unreadable pages in the window, rather than Qt's stderr.
            path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError, ValueError) as error:
            self._error(f"Cannot open Help page: {path}\n{error}")
            return
        self.error_label.hide()
        url = QUrl.fromLocalFile(str(path))
        url.setFragment(fragment)
        same_source = self.browser.source() == url
        kind = (QTextDocument.ResourceType.MarkdownResource
                if path.suffix.lower() in {".md", ".markdown", ".mkd"}
                else QTextDocument.ResourceType.HtmlResource)
        self.browser.setSource(url, kind)
        if same_source:
            self.browser.reload()
        self._source_changed(url)
        self.statusBar().showMessage(relative)

    def _topic_selected(self, item, _previous):
        if item is None:
            return
        filename = item.data(0, Qt.ItemDataRole.UserRole)
        if filename:
            self._load_page(filename)
        else:
            item.setExpanded(True)

    def _source_changed(self, url):
        if not url.isLocalFile():
            return
        path = Path(url.toLocalFile()).resolve()
        try:
            relative = path.relative_to(self.directory).as_posix()
        except ValueError:
            return
        self.statusBar().showMessage(relative)
        item = self._page_items.get(path)
        if item is not None:
            with QSignalBlocker(self.tree):
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)

    def _follow_link(self, url):
        if url.scheme() in {"http", "https", "mailto"}:
            QDesktopServices.openUrl(url)
            return
        target = self.browser.source().resolved(url)
        if target.isLocalFile():
            self._load_page(target.toLocalFile(), target.fragment())
        else:
            self._error("This Help link is not a local page or a web link.")

    def go_home(self):
        if self.contents is not None:
            self._load_page(self.contents.home)

    def open_help_folder(self):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.directory))):
            self._error(f"Cannot open Help folder: {self.directory}")

    def _filter_topics(self, text):
        query = text.strip().casefold()
        def visit(item, parent_matches=False):
            matches = parent_matches or bool(query and query in item.text(0).casefold())
            children = [visit(item.child(i), matches) for i in range(item.childCount())]
            visible = not query or matches or any(children)
            item.setHidden(not visible)
            if query and visible and children:
                item.setExpanded(True)
            return visible
        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))
