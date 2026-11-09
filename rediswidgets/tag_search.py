"""Literal matching for tag names."""

from collections.abc import Iterable

from PyQt6.QtCore import QMimeData, Qt
from PyQt6.QtWidgets import QListWidget, QListWidgetItem


class TagSearchResults(QListWidget):
    """Export tag names in the plain-text format accepted by tag monitors."""

    def __init__(self) -> None:
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def mimeData(self, items: Iterable[QListWidgetItem]) -> QMimeData:
        payload = QMimeData()
        payload.setText("\n".join(item.text() for item in items))
        return payload


def matching_tags(tags: list[str], query: str) -> list[str]:
    needle = query.casefold()
    return sorted((tag for tag in tags if needle in tag.casefold()), key=str.casefold)
