"""Tree Widget — Redis key tree browser with prefix-based hierarchy.

Displays Redis keys in a QTreeView grouped by ':' delimiter:
    ▶ sensors
      ▶ temperature
        ● room-01   (leaf: string key)
    ▶ devices
      ● status     (leaf: string key)
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QModelIndex, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QTreeView

from redisclient.redis_client import RedisClient

_DELIMITER = ":"


class RedisTreeModel(QStandardItemModel):
    """Lazy-loading tree model for Redis keys, grouped by ':' delimiter.

    Columns: ["Key", "Type", "Size"]

    Folder nodes store their prefix path in ROLE_PREFIX.
    Leaf nodes store their full key name in ROLE_KEY_NAME.
    Both store a boolean in ROLE_IS_FOLDER.
    Folder nodes track fetch state in ROLE_FETCHED.
    """

    ROLE_IS_FOLDER = Qt.ItemDataRole.UserRole + 1
    ROLE_KEY_NAME = Qt.ItemDataRole.UserRole + 2
    ROLE_PREFIX = Qt.ItemDataRole.UserRole + 3
    ROLE_FETCHED = Qt.ItemDataRole.UserRole + 4

    HEADERS = ["Key", "Type", "Size"]

    def __init__(self, client: RedisClient, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self.setHorizontalHeaderLabels(self.HEADERS)

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    def populate_root(self) -> None:
        """Scan all keys and build the first level of the hierarchy."""
        self.clear_headers()
        keys = self._client.scan_keys("*")
        segments = self._parse_keys(keys, "")
        for name, is_folder, matching_keys in segments:
            if is_folder:
                row = self._make_folder_row(name, name)
            else:
                row = self._make_leaf_row(name, matching_keys[0])
            self.appendRow(row)

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:  # noqa: N802
        """Return True for folder nodes so Qt shows the expand arrow."""
        if not parent.isValid():
            return True
        item = self.itemFromIndex(parent)
        if item is None:
            return False
        is_folder = item.data(self.ROLE_IS_FOLDER)
        return bool(is_folder)

    def canFetchMore(self, parent: QModelIndex = QModelIndex()) -> bool:  # noqa: N802
        """Return True if the parent index is an unfetched folder."""
        if not parent.isValid():
            return False
        item = self.itemFromIndex(parent)
        if item is None:
            return False
        is_folder = item.data(self.ROLE_IS_FOLDER)
        fetched = item.data(self.ROLE_FETCHED)
        return bool(is_folder and not fetched)

    def fetchMore(self, parent: QModelIndex = QModelIndex()) -> None:  # noqa: N802
        """Populate children of the folder at *parent*."""
        if not parent.isValid():
            return
        item = self.itemFromIndex(parent)
        if item is None:
            return

        is_folder = item.data(self.ROLE_IS_FOLDER)
        if not is_folder:
            return
        if item.data(self.ROLE_FETCHED):
            return

        prefix: str = item.data(self.ROLE_PREFIX) or ""
        keys = self._client.scan_keys(f"{prefix}:*")
        segments = self._parse_keys(keys, prefix)

        for name, is_folder_child, matching_keys in segments:
            if is_folder_child:
                child_prefix = f"{prefix}{_DELIMITER}{name}"
                row = self._make_folder_row(name, child_prefix)
            else:
                row = self._make_leaf_row(name, matching_keys[0])
            item.appendRow(row)

        item.setData(True, self.ROLE_FETCHED)

    # ──────────────────────────────────────────────
    # Internal helpers — item creation
    # ──────────────────────────────────────────────

    def _make_folder_row(self, name: str, prefix: str) -> list[QStandardItem]:
        """Create a row of items representing a folder node."""
        item = QStandardItem(name)
        item.setData(True, self.ROLE_IS_FOLDER)
        item.setData(prefix, self.ROLE_PREFIX)
        item.setData(False, self.ROLE_FETCHED)
        item.setEditable(False)
        return [item, self._blank_cell(), self._blank_cell()]

    def _make_leaf_row(self, name: str, full_key: str) -> list[QStandardItem]:
        """Create a row of items representing a leaf key, with metadata."""
        item = QStandardItem(name)
        item.setData(False, self.ROLE_IS_FOLDER)
        item.setData(full_key, self.ROLE_KEY_NAME)
        item.setEditable(False)

        type_text, size_text = self._fetch_metadata_text(full_key)

        type_cell = QStandardItem(type_text)
        type_cell.setEditable(False)
        size_cell = QStandardItem(size_text)
        size_cell.setEditable(False)
        return [item, type_cell, size_cell]

    def _fetch_metadata_text(self, full_key: str) -> tuple[str, str]:
        """Fetch key metadata and return (type_text, size_text)."""
        try:
            meta = self._client.get_key_metadata(full_key)
            return str(meta.get("type", "none")), str(meta.get("size", 0))
        except Exception:
            return "none", "?"

    @staticmethod
    def _blank_cell() -> QStandardItem:
        cell = QStandardItem("")
        cell.setEditable(False)
        return cell

    # ──────────────────────────────────────────────
    # Internal helpers — parsing
    # ──────────────────────────────────────────────

    @staticmethod
    def _parse_keys(
        keys: list[str], prefix: str
    ) -> list[tuple[str, bool, list[str]]]:
        """Group *keys* into segments relative to *prefix*.

        Returns a list of ``(segment_name, is_folder, matching_keys)``
        sorted alphabetically by segment name.

        A segment is a **leaf** when exactly one key maps to it and that
        key has no further ':' after the prefix.  Otherwise it is a
        **folder**.
        """
        segments: dict[str, list[str]] = {}

        for key in keys:
            if prefix:
                if not key.startswith(prefix + _DELIMITER):
                    continue
                suffix = key[len(prefix) + 1:]
            else:
                suffix = key

            delim_pos = suffix.find(_DELIMITER)
            seg = suffix[:delim_pos] if delim_pos != -1 else suffix
            segments.setdefault(seg, []).append(key)

        result: list[tuple[str, bool, list[str]]] = []
        for seg in sorted(segments):
            seg_keys = segments[seg]
            expected_full = f"{prefix}{_DELIMITER}{seg}" if prefix else seg
            is_leaf = len(seg_keys) == 1 and seg_keys[0] == expected_full
            result.append((seg, not is_leaf, seg_keys))
        return result

    # ──────────────────────────────────────────────
    # Overrides
    # ──────────────────────────────────────────────

    def clear(self) -> None:  # type: ignore[override]
        """Clear all items and restore header labels."""
        super().clear()
        self.setHorizontalHeaderLabels(self.HEADERS)

    def clear_headers(self) -> None:
        """Re-apply header labels (use after super().clear() in populate)."""
        self.setHorizontalHeaderLabels(self.HEADERS)


class TreeWidget(QObject):
    """Controller that wires a QTreeView to a RedisTreeModel."""

    error = pyqtSignal(Exception)

    def __init__(self, view: QTreeView) -> None:
        QObject.__init__(self)
        self._view = view
        self._client: RedisClient | None = None
        self._model: RedisTreeModel | None = None

    @property
    def model(self) -> RedisTreeModel | None:
        """The active tree model, or None before ``set_client``."""
        return self._model

    @property
    def view(self) -> QTreeView:
        return self._view

    def set_client(self, client: RedisClient) -> None:
        """Store client reference and populate root."""
        self._client = client
        self.set_root(client)

    def set_root(self, client: RedisClient) -> None:
        """Clear the model and (re)populate from *client*."""
        self._client = client
        self._model = RedisTreeModel(client)
        self._view.setModel(self._model)
        try:
            self._model.populate_root()
        except Exception as ex:
            self.error.emit(ex)

    def clear(self) -> None:
        """Clear all rows from the model."""
        if self._model is not None:
            self._model.clear()

    def get_current_key(self) -> str | None:
        """Return full key name of the selected leaf, or None."""
        if self._model is None:
            return None
        index = self._view.currentIndex()
        if not index.isValid():
            return None
        col0 = index.siblingAtColumn(0)
        item = self._model.itemFromIndex(col0)
        if item is None:
            return None
        if item.data(RedisTreeModel.ROLE_IS_FOLDER):
            return None
        return item.data(RedisTreeModel.ROLE_KEY_NAME)

    def get_current_prefix(self) -> str | None:
        """Return prefix path of the selected folder, or None."""
        if self._model is None:
            return None
        index = self._view.currentIndex()
        if not index.isValid():
            return None
        col0 = index.siblingAtColumn(0)
        item = self._model.itemFromIndex(col0)
        if item is None:
            return None
        if not item.data(RedisTreeModel.ROLE_IS_FOLDER):
            return None
        return item.data(RedisTreeModel.ROLE_PREFIX)
