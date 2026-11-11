"""Independent editor for local notes and their linked WKB-style tables."""

from html import escape
import sqlite3
from uuid import uuid4

import pandas as pd
from PyQt6.QtCore import QDate, QDateTime, QLocale, QRect, QSize, QSignalBlocker, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFont, QIcon, QKeySequence, QPainter, QPainterPath, QPalette, QPen, QPixmap, QShortcut,
    QTextCharFormat, QTextCursor, QTextDocumentFragment,
)
from PyQt6.QtWidgets import (
    QApplication, QColorDialog, QFontComboBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton,
    QSizePolicy, QSpinBox, QSplitter, QStyle, QStyledItemDelegate, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from .appearance import fit_window_to_screen, style_titlebar
from .notes import NoteStore
from .settings import apply_theme, get_settings
from .sheet import SheetModel, SheetView
from .workspace_document import commit_editors


TABLE_LINK = "note-table:"
UNTITLED_NOTE = "Untitled Note"


def _trash_icon(color):
    pixmap = QPixmap(36, 36)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color, 1.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    path = QPainterPath()
    path.moveTo(3, 5)
    path.lineTo(15, 5)
    path.moveTo(7, 5)
    path.lineTo(7, 3)
    path.lineTo(11, 3)
    path.lineTo(11, 5)
    path.moveTo(5, 7.5)
    path.lineTo(5.7, 14.5)
    path.quadTo(5.8, 15.5, 7, 15.5)
    path.lineTo(11, 15.5)
    path.quadTo(12.2, 15.5, 12.3, 14.5)
    path.lineTo(13, 7.5)
    painter.drawPath(path)
    painter.end()
    return QIcon(pixmap)


class NoteListDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        view = self.parent()
        width = max(0, view.viewport().width() - 2 * view.spacing())
        line_height = option.fontMetrics.height()
        if index.data(Qt.ItemDataRole.UserRole) is None:
            return QSize(width, line_height + 18)
        return QSize(width, 2 * line_height + 19)

    def paint(self, painter, option, index):
        note = index.data(Qt.ItemDataRole.UserRole)
        palette = option.palette
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.save()
        painter.setClipRect(option.rect)
        if note is not None and (selected or hovered):
            background = palette.color(QPalette.ColorRole.Highlight)
            if not selected:
                background.setAlpha(26)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(background)
            painter.drawRoundedRect(option.rect.adjusted(0, 0, -1, -1), 12, 12)

        foreground = palette.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text)
        rect = option.rect.adjusted(12, 0, -12, 0)
        title_font = QFont(option.font)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        if note is None:
            self._draw_line(painter, rect.adjusted(0, 6, 0, 0), index.data(), foreground)
        else:
            line_height = option.fontMetrics.height()
            title_rect = QRect(rect.x(), rect.y() + 8, rect.width(), line_height)
            self._draw_line(painter, title_rect, note["title"], foreground)
            metadata_font = QFont(option.font)
            if metadata_font.pointSizeF() > 1:
                metadata_font.setPointSizeF(metadata_font.pointSizeF() - 1)
            painter.setFont(metadata_font)
            foreground.setAlpha(215 if selected else 175)
            summary_rect = title_rect.translated(0, line_height + 1)
            self._draw_line(painter, summary_rect, index.data(Qt.ItemDataRole.AccessibleDescriptionRole), foreground)
        painter.restore()

    @staticmethod
    def _draw_line(painter, rect, text, color):
        painter.setPen(color)
        label = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)


class NoteEditor(QTextEdit):
    table_clicked = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._pressed_link = ""
        self.viewport().setMouseTracking(True)

    @staticmethod
    def _table_link_fragments(document, start, end):
        if start >= end:
            return
        block = document.findBlock(max(0, start))
        while block.isValid() and block.position() < end:
            part = block.begin()
            while not part.atEnd():
                fragment = part.fragment()
                href = fragment.charFormat().anchorHref()
                if href.startswith(TABLE_LINK):
                    yield fragment, href
                part += 1
            block = block.next()

    def _table_links(self, start, end):
        """Find whole link spans, including anchors split into several format runs."""
        links = []
        for fragment, href in self._table_link_fragments(self.document(), start, end):
            left = fragment.position()
            right = left + fragment.length()
            if links and links[-1][1:] == (left, href):
                left = links.pop()[0]
            links.append((left, right, href))
        return [(left, right, href) for left, right, href in links if left < end and right > start]

    @classmethod
    def unlink_table(cls, document, table_id):
        target = TABLE_LINK + table_id
        changes = []
        for fragment, href in cls._table_link_fragments(document, 0, document.characterCount()):
            if href == target:
                fmt = fragment.charFormat()
                fmt.setAnchor(False)
                fmt.setAnchorHref("")
                fmt.setAnchorNames([])
                fmt.setFontUnderline(False)
                fmt.clearForeground()
                changes.append((fragment.position(), fragment.length(), fmt))
        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        for start, length, fmt in changes:
            cursor.setPosition(start)
            cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
            cursor.setCharFormat(fmt)
        cursor.endEditBlock()

    def _selected_links(self, cursor):
        return self._table_links(cursor.selectionStart(), cursor.selectionEnd())

    def _link_at(self, position, href=None):
        for left, right, link in self._table_links(position - 1, position + 1):
            if (href is None and left < position < right) or (href == link and left <= position <= right):
                return left, right
        return None

    def _snap_cursor(self, direction=0):
        cursor = self.textCursor()
        position, anchor = cursor.position(), cursor.anchor()
        snapped_position, snapped_anchor = position, anchor
        outward = 1 if position >= anchor else -1
        link = self._link_at(position)
        if link is not None:
            # Follow the direction of keyboard movement so Shift can shrink the selection too.
            snapped_position = link[1] if (direction or outward) > 0 else link[0]
        if position == anchor:
            snapped_anchor = snapped_position
        else:
            link = self._link_at(anchor)
            if link is not None:
                snapped_anchor = link[0] if outward > 0 else link[1]
        if (snapped_position, snapped_anchor) != (position, anchor):
            cursor.setPosition(snapped_anchor)
            cursor.setPosition(snapped_position, QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)

    def _select_link(self, point, href):
        cursor = self.cursorForPosition(point)
        bounds = self._link_at(cursor.position(), href)
        if bounds is not None:
            cursor.setPosition(bounds[0])
            cursor.setPosition(bounds[1], QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)

    def format_at_cursor(self):
        # Qt inherits the preceding character's format at the end of a link.
        fmt = self.currentCharFormat()
        cursor = self.textCursor()
        if cursor.hasSelection() or not fmt.anchorHref().startswith(TABLE_LINK):
            return fmt
        if cursor.movePosition(QTextCursor.MoveOperation.NextCharacter):
            following = cursor.charFormat()
            if not following.isAnchor():
                return following
        return QTextCharFormat()

    def _plain_typing_format(self):
        if self.currentCharFormat().anchorHref().startswith(TABLE_LINK):
            self.setCurrentCharFormat(self.format_at_cursor())

    def only_table_links_selected(self):
        cursor = self.textCursor()
        length = cursor.selectionEnd() - cursor.selectionStart()
        linked_length = sum(right - left for left, right, _ in self._selected_links(cursor))
        return length > 0 and length == linked_length

    def apply_text_format(self, fmt, *, include_links=False):
        self._snap_cursor()
        selection = self.textCursor()
        links = self._selected_links(selection)
        if not selection.hasSelection():
            self._plain_typing_format()
        if include_links or not links:
            self.mergeCurrentCharFormat(fmt)
            return

        cursor = QTextCursor(selection)
        start = selection.selectionStart()
        cursor.beginEditBlock()
        for left, right, _ in links:
            if start < left:
                cursor.setPosition(start)
                cursor.setPosition(left, QTextCursor.MoveMode.KeepAnchor)
                cursor.mergeCharFormat(fmt)
            start = right
        if start < selection.selectionEnd():
            cursor.setPosition(start)
            cursor.setPosition(selection.selectionEnd(), QTextCursor.MoveMode.KeepAnchor)
            cursor.mergeCharFormat(fmt)
        cursor.endEditBlock()

    def _delete_across_link(self, event):
        cursor = self.textCursor()
        key = QKeySequence.StandardKey
        move = QTextCursor.MoveOperation
        shift_backspace = (event.key() == Qt.Key.Key_Backspace
                           and event.modifiers() == Qt.KeyboardModifier.ShiftModifier)
        if event.matches(key.DeleteEndOfLine):
            block = cursor.block()
            before_last_char = cursor.position() == block.position() + block.length() - 2
            operation = move.Right if before_last_char else move.EndOfBlock
        elif cursor.hasSelection() or event.matches(key.Cut):
            return False
        elif event.matches(key.DeleteStartOfWord):
            operation = move.PreviousWord
        elif event.matches(key.DeleteEndOfWord):
            operation = move.NextWord
        elif event.matches(key.Backspace) or shift_backspace:
            operation = move.PreviousCharacter
        elif event.matches(key.Delete):
            operation = move.NextCharacter
        else:
            return False
        cursor.movePosition(operation, QTextCursor.MoveMode.KeepAnchor)
        links = self._selected_links(cursor)
        if not links:
            return False
        start = min(cursor.selectionStart(), links[0][0])
        end = max(cursor.selectionEnd(), links[-1][1])
        if (start, end) == (cursor.selectionStart(), cursor.selectionEnd()):
            return False
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self.setTextCursor(cursor)
        return True

    def keyPressEvent(self, event):
        self._snap_cursor()
        if self._delete_across_link(event):
            event.accept()
            return
        key = QKeySequence.StandardKey
        inserts_text = (any(char.isprintable() for char in event.text()) or event.key() == Qt.Key.Key_Tab
                        or event.matches(key.InsertParagraphSeparator) or event.matches(key.InsertLineSeparator))
        if inserts_text:
            shortcuts = (key.Copy, key.Cut, key.Paste, key.Undo, key.Redo, key.SelectAll)
            if not any(event.matches(shortcut) for shortcut in shortcuts):
                cursor = self.textCursor()
                if self._selected_links(cursor):
                    event.accept()
                    return
                if not cursor.hasSelection():
                    self._plain_typing_format()
        before = self.textCursor().position()
        super().keyPressEvent(event)
        after = self.textCursor().position()
        self._snap_cursor((after > before) - (after < before))

    def inputMethodEvent(self, event):
        self._snap_cursor()
        cursor = self.textCursor()
        start = cursor.position() + event.replacementStart()
        end = start + event.replacementLength()
        if self._selected_links(cursor) or self._table_links(start, end) or self._link_at(start):
            event.accept()
            return
        if not cursor.hasSelection():
            self._plain_typing_format()
        super().inputMethodEvent(event)
        self._snap_cursor()

    def insertFromMimeData(self, source):
        self._snap_cursor()
        cursor = self.textCursor()
        if not self._selected_links(cursor):
            if not cursor.hasSelection():
                self._plain_typing_format()
            super().insertFromMimeData(source)
            self._snap_cursor()

    def dropEvent(self, event):
        if self._link_at(self.cursorForPosition(event.position().toPoint()).position()):
            event.ignore()
            return
        super().dropEvent(event)
        self._snap_cursor()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._snap_cursor()
        link = self.anchorAt(event.position().toPoint()).startswith(TABLE_LINK)
        shape = Qt.CursorShape.PointingHandCursor if link else Qt.CursorShape.IBeamCursor
        self.viewport().setCursor(shape)

    def mousePressEvent(self, event):
        self._pressed_link = ""
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_position = event.position().toPoint()
            self._pressed_link = self.anchorAt(self._press_position)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        position = event.position().toPoint()
        link = self._pressed_link
        self._pressed_link = ""
        super().mouseReleaseEvent(event)
        if (event.button() == Qt.MouseButton.LeftButton and link.startswith(TABLE_LINK)
                and self.anchorAt(position) == link
                and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                and (position - self._press_position).manhattanLength() < QApplication.startDragDistance()):
            self._select_link(position, link)
            self.table_clicked.emit(link[len(TABLE_LINK):])
        else:
            self._snap_cursor()

    def mouseDoubleClickEvent(self, event):
        point = event.position().toPoint()
        href = self.anchorAt(point)
        if event.button() == Qt.MouseButton.LeftButton and href.startswith(TABLE_LINK):
            self._select_link(point, href)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)
            self._snap_cursor()

    def insert_table_link(self, table_id, title):
        self._snap_cursor()
        cursor = self.textCursor()
        cursor.setPosition(cursor.selectionEnd())
        normal = cursor.charFormat()
        if normal.isAnchor():
            normal = QTextCharFormat()
        link = QTextCharFormat()
        if normal.fontPointSize() > 0:
            link.setFontPointSize(normal.fontPointSize())
        link.setAnchor(True)
        link.setAnchorHref(TABLE_LINK + table_id)
        link.setForeground(QColor("#5677c2"))
        link.setFontUnderline(True)
        cursor.beginEditBlock()
        cursor.insertText(title, link)
        cursor.insertText(" ", normal)
        cursor.endEditBlock()
        self.setTextCursor(cursor)


class NoteWindow(QMainWindow):
    notes_changed = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, parent=None, *, store=None, saved_message="Saved locally"):
        if store is None:
            store = NoteStore()
        super().__init__(parent, Qt.WindowType.Window)
        self.store = store
        self._saved_message = saved_message
        self.note_id = None
        self._saved_title = ""
        self.table_id = None
        self.tables = {}
        self._dirty = False
        self._table_dirty = False
        self._note_items = {}
        self.setWindowTitle("Note")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._save_timer = QTimer(self, singleShot=True, interval=450)
        self._save_timer.timeout.connect(self._save_pending)
        self._build_ui()
        fit_window_to_screen(self, (1130, 720), minimum=(760, 440))
        self.apply_note_theme()
        self._display_note(None)
        self._refresh_list()

    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal, objectName="noteSidebarSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)
        self.setCentralWidget(splitter)

        sidebar = QWidget(objectName="noteSidebar")
        sidebar.setMinimumWidth(200)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 14, 14, 12)
        sidebar_layout.setSpacing(8)
        sidebar_bar = QHBoxLayout()
        sidebar_bar.addWidget(QLabel("Notes", objectName="noteHeading"), 1)
        new_note = QPushButton("New Note", objectName="noteAction")
        new_note.clicked.connect(self._create_note)
        sidebar_bar.addWidget(new_note)
        sidebar_layout.addLayout(sidebar_bar)
        self.note_list = QListWidget(objectName="noteList")
        self.note_list.setSpacing(3)
        self.note_list.setMouseTracking(True)
        self.note_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.note_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.note_list.setItemDelegate(NoteListDelegate(self.note_list))
        self.note_list.currentItemChanged.connect(self._select_note)
        self.note_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.note_list.customContextMenuRequested.connect(self._note_menu)
        sidebar_layout.addWidget(self.note_list)
        splitter.addWidget(sidebar)

        self.edit_panel = QWidget(objectName="noteWorkspace")
        edit_layout = QVBoxLayout(self.edit_panel)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.setSpacing(0)
        content = QSplitter(Qt.Orientation.Horizontal, objectName="noteTableSplitter")
        content.setChildrenCollapsible(False)
        content.setHandleWidth(1)
        page = QWidget()
        page.setMinimumWidth(230)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(24, 14, 24, 12)
        page_layout.setSpacing(3)
        self.title_edit = QLineEdit(objectName="noteTitle")
        self.title_edit.setAccessibleName("Note title")
        self.title_edit.setPlaceholderText("Title")
        self.title_edit.textChanged.connect(self._title_changed)
        page_layout.addWidget(self.title_edit)
        self.editor = NoteEditor()
        self.editor.setObjectName("noteEditor")
        self.editor.document().setDocumentMargin(8)
        self.editor.textChanged.connect(self._schedule_save)
        self.editor.table_clicked.connect(self._show_table)
        self.title_edit.returnPressed.connect(self.editor.setFocus)
        page_layout.addWidget(self.editor, 1)
        content.addWidget(page)
        edit_layout.addLayout(self._format_toolbar())
        self.editor.currentCharFormatChanged.connect(self._update_format)
        self.editor.selectionChanged.connect(self._update_format)
        edit_layout.addWidget(content, 1)
        splitter.addWidget(self.edit_panel)

        self.table_panel = QWidget(objectName="noteTablePanel")
        self.table_panel.setMinimumWidth(250)
        table_layout = QVBoxLayout(self.table_panel)
        table_layout.setContentsMargins(12, 8, 12, 12)
        table_bar = QHBoxLayout()
        self.table_title = QLabel()
        self.table_title.setTextFormat(Qt.TextFormat.PlainText)
        self.table_title.setObjectName("panelTitle")
        self.table_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        table_bar.addWidget(self.table_title, 1)
        close_table = QPushButton("Close table", objectName="noteAction")
        close_table.clicked.connect(self.table_panel.hide)
        table_bar.addWidget(close_table)
        self.delete_table_button = QToolButton(objectName="noteDeleteTable")
        self.delete_table_button.setIconSize(QSize(18, 18))
        self.delete_table_button.setToolTip("Delete table")
        self.delete_table_button.setAccessibleName("Delete table")
        self.delete_table_button.clicked.connect(self._delete_table)
        table_bar.addWidget(self.delete_table_button)
        table_layout.addLayout(table_bar)
        self.table_model = SheetModel()
        self.table_model.setParent(self)
        self.table_model.changed.connect(self._table_changed)
        self.sheet = SheetView(self.table_model)
        table_layout.addWidget(self.sheet)
        content.addWidget(self.table_panel)
        content.setStretchFactor(0, 3)
        content.setStretchFactor(1, 2)
        content.setSizes([520, 320])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 850])
        self.statusBar()

    def _format_toolbar(self):
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(18, 14, 18, 6)
        toolbar.setSpacing(8)
        self.font_picker = QFontComboBox(objectName="noteFontPicker")
        self.font_picker.setMinimumContentsLength(9)
        self.font_picker.setMaximumWidth(190)
        self.font_picker.setSizeAdjustPolicy(QFontComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.font_picker.setToolTip("Font family")
        self.font_picker.currentFontChanged.connect(self._set_font)
        self.font_size = QSpinBox(objectName="noteFontSize")
        self.font_size.setRange(1, 200)
        self.font_size.setSuffix(" pt")
        self.font_size.setKeyboardTracking(False)
        self.font_size.setToolTip("Font size")
        self.font_size.valueChanged.connect(self._set_font_size)
        toolbar.addWidget(self._tool_group(self.font_picker, self.font_size))
        self.bold = self._format_button("B", "Bold", self._set_bold)
        self.italic = self._format_button("I", "Italic", self._set_italic)
        self.underline = self._format_button("U", "Underline", self._set_underline)
        self.color = QPushButton("Color", objectName="noteFormatButton")
        self.color.setToolTip("Text color")
        self.color.clicked.connect(self._choose_color)
        toolbar.addWidget(self._tool_group(self.bold, self.italic, self.underline, self.color))
        insert_table = QPushButton("Insert table", objectName="noteAction")
        insert_table.clicked.connect(self._insert_table)
        toolbar.addWidget(insert_table)
        toolbar.addStretch(1)
        tables = QPushButton("Tables", objectName="noteTablesMenu")
        tables.setToolTip("Open a table in this note")
        self.tables_menu = QMenu(tables)
        tables.setMenu(self.tables_menu)
        toolbar.addWidget(tables)
        return toolbar

    @staticmethod
    def _tool_group(*controls):
        group = QFrame(objectName="noteToolGroup")
        layout = QHBoxLayout(group)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)
        for control in controls:
            layout.addWidget(control)
        return group

    def _format_button(self, text, label, callback):
        button = QToolButton(objectName="noteFormatButton")
        button.setText(text)
        keys = f"Ctrl+{text}"
        button.setToolTip(f"{label} ({keys})")
        button.setAccessibleName(label)
        button.setCheckable(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        font = button.font()
        font.setBold(label == "Bold")
        font.setItalic(label == "Italic")
        font.setUnderline(label == "Underline")
        button.setFont(font)
        button.clicked.connect(callback)
        shortcut = QShortcut(QKeySequence(keys), self.editor)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.setAutoRepeat(False)
        shortcut.activated.connect(button.click)
        return button

    def _set_font(self, font):
        fmt = QTextCharFormat()
        fmt.setFontFamilies([font.family()])
        self.editor.apply_text_format(fmt)

    def _set_font_size(self, size):
        fmt = QTextCharFormat()
        fmt.setFontPointSize(size)
        self.editor.apply_text_format(fmt, include_links=True)

    def _set_bold(self, checked):
        fmt = QTextCharFormat()
        fmt.setFontWeight(int(QFont.Weight.Bold if checked else QFont.Weight.Normal))
        self.editor.apply_text_format(fmt)

    def _set_italic(self, checked):
        fmt = QTextCharFormat()
        fmt.setFontItalic(checked)
        self.editor.apply_text_format(fmt)

    def _set_underline(self, checked):
        fmt = QTextCharFormat()
        fmt.setFontUnderline(checked)
        self.editor.apply_text_format(fmt)

    def _choose_color(self):
        color = QColorDialog.getColor(self.editor.textColor(), self, "Text color")
        if color.isValid():
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            self.editor.apply_text_format(fmt)
        self.editor.setFocus()

    def _update_format(self):
        fmt = self.editor.format_at_cursor()
        editable = not self.editor.only_table_links_selected()
        for control in (self.font_picker, self.bold, self.italic, self.underline, self.color):
            control.setEnabled(editable)
        default = self.editor.document().defaultFont()
        families = fmt.fontFamilies() or [default.family()]
        size = fmt.fontPointSize() or default.pointSizeF()
        with QSignalBlocker(self.font_picker), QSignalBlocker(self.font_size):
            self.font_picker.setCurrentFont(QFont(families[0]))
            self.font_size.setValue(round(size) if size > 0 else 10)
        self.bold.setChecked(fmt.fontWeight() >= int(QFont.Weight.Bold))
        self.italic.setChecked(fmt.fontItalic())
        self.underline.setChecked(fmt.fontUnderline())

    def apply_note_theme(self, theme=None):
        theme = theme or get_settings()["theme"]
        apply_theme(self, theme)
        self.delete_table_button.setIcon(_trash_icon(QColor("#18181b" if theme == "light" else "#f4f0f7")))
        style_titlebar(self, theme)

    def _refresh_list(self, preferred_id=None):
        try:
            notes = self.store.list_notes()
        except sqlite3.Error as error:
            self._show_error("Could not read notes", error)
            return
        preferred_id = preferred_id if preferred_id is not None else self.note_id
        today = QDate.currentDate()
        yesterday = today.addDays(-1)
        locale = QLocale.system()
        short = QLocale.FormatType.ShortFormat
        section = None
        with QSignalBlocker(self.note_list):
            self._note_items.clear()
            self.note_list.clear()
            for note in notes:
                created = QDateTime.fromMSecsSinceEpoch(note["created_at"] // 1_000_000)
                date = created.date()
                if note["pinned"]:
                    group = "Pinned"
                elif date == today:
                    group = "Today"
                elif date == yesterday:
                    group = "Yesterday"
                else:
                    group = str(date.year())
                if section != group:
                    section = group
                    heading = QListWidgetItem(section, self.note_list)
                    heading.setFlags(Qt.ItemFlag.NoItemFlags)

                when = locale.toString(created.time(), short) if date == today else locale.toString(date, short)
                item = QListWidgetItem(self.note_list)
                item.setData(Qt.ItemDataRole.UserRole, {
                    "id": note["id"], "pinned": note["pinned"], "when": when,
                })
                title = self._current_title() if note["id"] == self.note_id else note["title"]
                self._set_item_title(item, title)
                self._set_note_preview(item, QTextDocumentFragment.fromHtml(note["html"]).toPlainText())
                self._note_items[note["id"]] = item

            selected = self._note_items.get(preferred_id)
            if selected is None:
                selected = next(iter(self._note_items.values()), None)
            if selected is not None:
                self.note_list.setCurrentItem(selected)
        self._select_note(selected)

    @staticmethod
    def _set_item_title(item, title):
        note = item.data(Qt.ItemDataRole.UserRole)
        note["title"] = title
        item.setData(Qt.ItemDataRole.UserRole, note)
        item.setText(title)
        item.setToolTip(f"<span>{escape(title)}</span>")

    def _current_title(self):
        return self.title_edit.text().strip() or UNTITLED_NOTE

    def _title_changed(self):
        item = self._note_items.get(self.note_id)
        if item is not None:
            self._set_item_title(item, self._current_title())
        self._schedule_save()

    @staticmethod
    def _set_note_preview(item, text):
        when = item.data(Qt.ItemDataRole.UserRole)["when"]
        preview = " ".join(text.lstrip()[:160].split())
        summary = f"{when}  {preview}" if preview else when
        item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, summary)

    def _select_note(self, item, _previous=None):
        note = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if item is not None and note is None:
            return
        note_id = note["id"] if note is not None else None
        if note_id == self.note_id:
            return
        if self._save_pending():
            if note_id is None:
                self._display_note(None)
                return
            try:
                title, html, tables = self.store.load(note_id)
            except (sqlite3.Error, ValueError) as error:
                self._show_error("Could not open note", error)
            else:
                self._display_note(note_id, title, html, tables)
                return
        with QSignalBlocker(self.note_list):
            previous = self._note_items.get(self.note_id)
            self.note_list.setCurrentRow(self.note_list.row(previous) if previous is not None else -1)

    def _display_note(self, note_id, title="", html="", tables=None):
        self.note_id = note_id
        self._saved_title = title
        self.table_id = None
        self.tables = {} if tables is None else tables
        self._table_dirty = False
        self._refresh_table_menu()
        self.table_panel.hide()
        self.edit_panel.setEnabled(note_id is not None)
        self.editor.setPlaceholderText("Write a note…" if note_id is not None else "Create a note to get started.")
        with QSignalBlocker(self.title_edit), QSignalBlocker(self.editor):
            self.title_edit.setText("" if title == UNTITLED_NOTE else title)
            self.editor.setHtml(html)
        item = self._note_items.get(note_id)
        if item is not None and item.text() != title:
            self._set_item_title(item, title)
        self._update_format()

    def _create_note(self):
        if not self._save_pending():
            return
        try:
            note_id = self.store.create(UNTITLED_NOTE)
        except sqlite3.Error as error:
            self._show_error("Could not create note", error)
            return
        self._refresh_list(note_id)
        self.notes_changed.emit()
        if self.note_id == note_id:
            self.title_edit.setFocus()

    def _note_menu(self, position):
        item = self.note_list.itemAt(position)
        if item is None:
            return
        note = item.data(Qt.ItemDataRole.UserRole)
        if note is None:
            return
        menu = QMenu(self)
        rename = menu.addAction("Rename…")
        pin = menu.addAction("Unpin" if note["pinned"] else "Pin to top")
        delete = menu.addAction("Delete…")
        action = menu.exec(self.note_list.viewport().mapToGlobal(position))
        menu.deleteLater()
        note_id = note["id"]
        try:
            if action == rename:
                title, ok = QInputDialog.getText(self, "Rename note", "Note title", text=note["title"])
                title = title.strip()
                if not ok or not title:
                    return
                if self.note_id == note_id:
                    self.title_edit.setText("" if title == UNTITLED_NOTE else title)
                    self._save_pending()
                else:
                    self.store.rename(note_id, title)
                    self._set_item_title(item, title)
                    self.notes_changed.emit()
                return
            elif action == pin:
                self.store.set_pinned(note_id, not note["pinned"])
            elif action == delete:
                answer = QMessageBox.question(self, "Delete note", "Delete this note and its tables?",
                                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                              QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
                self.store.delete(note_id)
                if self.note_id == note_id:
                    self._save_timer.stop()
                    self._dirty = False
                    self._display_note(None)
            else:
                return
        except sqlite3.Error as error:
            self._show_error("Could not update note", error)
            return
        self._refresh_list()
        self.notes_changed.emit()

    def _refresh_table_menu(self):
        self.tables_menu.clear()
        if not self.tables:
            self.tables_menu.addAction("No tables").setEnabled(False)
        for table_id, table in self.tables.items():
            action = self.tables_menu.addAction(table["title"].replace("&", "&&"))
            action.triggered.connect(lambda _checked=False, key=table_id: self._show_table(key))

    def _insert_table(self):
        titles = {table["title"] for table in self.tables.values()}
        number = len(self.tables) + 1
        while f"Table {number}" in titles:
            number += 1
        suggested = f"Table {number}"
        title, ok = QInputDialog.getText(self, "Insert table", "Link title", text=suggested)
        if not ok:
            return
        title = title.strip() or suggested
        table_id = uuid4().hex
        self.tables[table_id] = {"title": title, "columns": [], "rows": []}
        self._refresh_table_menu()
        self.editor.insert_table_link(table_id, title)
        self._show_table(table_id)
        self.editor.setFocus()

    def _show_table(self, table_id):
        table = self.tables.get(table_id)
        if table is None:
            self.statusBar().showMessage("This table is unavailable in the current note.", 4000)
            return
        if table_id != self.table_id:
            self._capture_table()
            self.table_id = None
            self.table_model.load(pd.DataFrame(table["rows"], columns=table["columns"]))
            self.table_id = table_id
            self.table_title.setText(table["title"])
            self.table_title.setToolTip(f"<span>{escape(table['title'])}</span>")
            self.sheet.scrollToTop()
            self.sheet.horizontalScrollBar().setValue(0)
        self.table_panel.show()

    def _delete_table(self):
        table_id = self.table_id
        table = self.tables.get(table_id)
        if table is None:
            return
        dialog = QMessageBox(QMessageBox.Icon.Question, "Delete table",
                             f"Delete “{table['title']}”? Its links will become plain text. "
                             "This also clears the note’s undo history.",
                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        if dialog.exec() != QMessageBox.StandardButton.Yes:
            return

        document = self.editor.document()
        draft = document.clone()
        self.editor.unlink_table(draft, table_id)
        remaining_tables = self.tables.copy()
        del remaining_tables[table_id]
        if not self._save_note(draft.toHtml(), remaining_tables):
            return

        self.tables = remaining_tables
        self.table_id = None
        self._table_dirty = False
        self.table_panel.hide()
        self.table_model.load(pd.DataFrame())
        with QSignalBlocker(self.editor):
            self.editor.unlink_table(document, table_id)
            document.clearUndoRedoStacks()
        self._refresh_table_menu()
        self._update_format()
        self.editor.setFocus()
        self.notes_changed.emit()

    def _table_changed(self):
        if self.table_id is not None:
            self._table_dirty = True
            self._schedule_save()

    def _current_table_values(self):
        frame = self.table_model.document_frame()
        return dict(self.tables[self.table_id], columns=list(frame.columns), rows=frame.values.tolist())

    def _capture_table(self):
        if self._table_dirty:
            self.tables[self.table_id] = self._current_table_values()
            self._table_dirty = False

    def draft_note(self):
        if not self._dirty:
            return None
        tables = self.tables
        if self._table_dirty:
            tables = {**tables, self.table_id: self._current_table_values()}
        return self.note_id, self._current_title(), self.editor.toHtml(), tables

    def _schedule_save(self):
        if self.note_id is not None:
            self._dirty = True
            self._save_timer.start()
            self.notes_changed.emit()

    def _save_pending(self):
        self._save_timer.stop()
        if not self._dirty:
            return True
        self._capture_table()
        return self._save_note(self.editor.toHtml(), self.tables)

    def _save_note(self, html, tables):
        title = self._current_title()
        try:
            self.store.save(self.note_id, html, tables,
                            title=title if title != self._saved_title else None)
        except sqlite3.Error as error:
            self._show_error("Could not save note", error)
            return False
        self._save_timer.stop()
        self._dirty = False
        self._saved_title = title
        item = self._note_items.get(self.note_id)
        if item is not None:
            self._set_note_preview(item, self.editor.toPlainText())
        self.statusBar().showMessage(self._saved_message, 2000)
        return True

    def _show_error(self, message, error):
        self.statusBar().showMessage(f"{message}. {error}")

    def flush_changes(self):
        commit_editors(self)
        if self._save_pending():
            return True
        QMessageBox.warning(self, "Note", self.statusBar().currentMessage())
        return False

    def closeEvent(self, event):
        closed = self.flush_changes()
        event.setAccepted(closed)
        if closed:
            self.closed.emit()
