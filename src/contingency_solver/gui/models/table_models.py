from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class ObjectTableModel(QAbstractTableModel):
    def __init__(self, rows: list[Any], columns: list[tuple[str, Callable[[Any], Any]]]) -> None:
        super().__init__()
        self._rows = rows
        self._columns = columns

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        value = self._columns[index.column()][1](self._rows[index.row()])
        if role in (Qt.DisplayRole, Qt.EditRole):
            if isinstance(value, float):
                return f"{value:.2f}"
            return str(value)
        if role == Qt.UserRole:
            return value
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._columns[section][0]
        return None

    def set_rows(self, rows: list[Any]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def row_object(self, row: int) -> Any:
        return self._rows[row]
