"""Font-aware action rows that wrap rather than crop button captions."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QLayout


class WrappingActionLayout(QLayout):
    """Pack full-size actions onto rows; keep the final confirmation right-aligned."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items = []

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation.Horizontal

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def _rows(self, width):
        left, _top, right, _bottom = self.getContentsMargins()
        available = max(1, width - left - right)
        rows = [[]]
        used = 0
        for item in self._items:
            hint = item.sizeHint().expandedTo(item.minimumSize())
            size = QSize(min(available, hint.width()), hint.height())
            next_width = used + (self.spacing() if rows[-1] else 0) + size.width()
            if rows[-1] and next_width > available:
                rows.append([])
                used = 0
            used += (self.spacing() if rows[-1] else 0) + size.width()
            rows[-1].append((item, size))
        return [row for row in rows if row]

    def heightForWidth(self, width) -> int:  # noqa: N802
        _left, top, _right, bottom = self.getContentsMargins()
        rows = self._rows(width)
        return (
            top
            + bottom
            + sum(max(size.height() for _, size in row) for row in rows)
            + max(0, len(rows) - 1) * self.spacing()
        )

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        return size + QSize(left + right, top + bottom)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def setGeometry(self, rect) -> None:  # noqa: N802
        super().setGeometry(rect)
        left, top, right, _bottom = self.getContentsMargins()
        y = rect.y() + top
        for row in self._rows(rect.width()):
            height = max(size.height() for _, size in row)
            x = rect.x() + left
            for item, size in row:
                if item is self._items[-1]:
                    x = max(x, rect.right() - right - size.width() + 1)
                item.setGeometry(QRect(x, y + (height - size.height()) // 2, size.width(), size.height()))
                x += size.width() + self.spacing()
            y += height + self.spacing()
