from PySide6.QtCore import Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem


class NavigationList(QListWidget):
    page_changed = Signal(int)

    def __init__(self, page_names: list[str]) -> None:
        super().__init__()
        self.setObjectName("NavigationList")
        for name in page_names:
            item = QListWidgetItem(name)
            item.setSizeHint(item.sizeHint())
            self.addItem(item)
        self.currentRowChanged.connect(self.page_changed.emit)
        self.setCurrentRow(0)
