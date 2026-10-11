"""Column-name cells show the protection state without a separate sidebar."""
from html import escape
from PyQt6.QtCore import QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem, QToolTip


METADATA_NAMES = {
    "waferid", "wafer", "waferno", "lotid", "lot", "lotno", "padname", "pad",
    "dieseq", "dieid", "diesequence", "diesequenceno", "toolsn", "toolid",
    "fieldx", "fieldy", "x", "y", "xmm", "ymm", "diex", "diey",
    "coordx", "coordy", "xcoordinate", "ycoordinate", "testflag", "mark", "head",
    "cursmefile", "cursmefilepath",
}


def is_metadata_column(name):
    return ("".join(ch.lower() for ch in str(name) if ch.isalnum()) in METADATA_NAMES
            or "path" in str(name).lower())


class ColumnLockDelegate(QStyledItemDelegate):
    def __init__(self, view):
        super().__init__(view)
        self.view = view

    def lock_state(self, index):
        if not index.isValid() or index.row() != 0:
            return None
        model, (row, column) = self.view.source_cell(index)
        if row != 0 or not hasattr(model, "clipboard_locks"):
            return None
        name = model.data(model.index(0, column), Qt.ItemDataRole.EditRole)
        return (name, name in model.clipboard_locks) if is_metadata_column(name) else None

    @staticmethod
    def lock_rect(rect):
        return QRect(rect.right() - 23, rect.center().y() - 10, 20, 20)

    def paint(self, painter, option, index):
        state = self.lock_state(index)
        if state is None:
            return super().paint(painter, option, index)
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        styled.text = styled.fontMetrics.elidedText(
            styled.text, Qt.TextElideMode.ElideRight, max(0, styled.rect.width() - 34))
        self.view.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, self.view)
        rect = self.lock_rect(option.rect)
        x, y = 0, 0
        color = QColor("#d1495b" if state[1] else "#008a48")
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # The smaller icon stays centered in the existing easy-to-click area.
        painter.translate(rect.x() + 5, rect.y() + 5)
        painter.scale(0.5, 0.5)
        painter.setOpacity(0.5)
        painter.setPen(QPen(color, 1.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        shackle = QPainterPath()
        left = x + (5 if state[1] else 9)
        shackle.moveTo(left, y + 9)
        shackle.lineTo(left, y + 5)
        shackle.cubicTo(left, y, left + 10, y, left + 10, y + 5)
        shackle.lineTo(left + 10, y + (9 if state[1] else 7))
        painter.drawPath(shackle)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(x + 4, y + 9, 12, 9), 2, 2)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(x + 9, y + 12, 2, 3))
        painter.restore()

    def updateEditorGeometry(self, editor, option, index):
        if self.lock_state(index) is not None:
            option = QStyleOptionViewItem(option)
            option.rect.adjust(0, 0, -27, 0)
        super().updateEditorGeometry(editor, option, index)

    def helpEvent(self, event, view, option, index):
        state = self.lock_state(index)
        if state is None:
            return super().helpEvent(event, view, option, index)
        name, locked = state
        status = "Locked" if locked else "Unlocked"
        QToolTip.showText(event.globalPos(), f"{escape(str(name))} — {status}<br>Click the lock or Ctrl+L to toggle.<br>"
                          "Locked names and values stay in this column during paste.", view)
        return True
