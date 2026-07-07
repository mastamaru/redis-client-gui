"""Tree Widget — Redis key tree browser with prefix-based hierarchy.

Displays Redis keys in a QTreeView grouped by ':' delimiter.
HASH keys are flattened inline: their fields appear directly as children
of the parent folder, skipping the intermediate hash-key node.

    ▶ ots-pim
      ● LIC1003A_PV    float
      ● LIC1003A_SP    float
      ● A107JA_RUN     bool
      ▶ other-folder
        ● status       string
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QMimeData, QModelIndex, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QTreeView

from redisclient.redis_client import RedisClient

logger = logging.getLogger(__name__)

_DELIMITER = ":"


class RedisTreeModel(QStandardItemModel):
    """Lazy-loading tree model for Redis keys.

    HASH keys are expanded inline: field names appear directly under the
    parent folder, not under an intermediate key node.

    Columns: ["Name", "Type", "Size"]

    Roles:
        ROLE_IS_FOLDER   — True for folder nodes
        ROLE_KEY_NAME    — full Redis key (for regular leaf nodes)
        ROLE_PREFIX      — prefix path (for folder nodes)
        ROLE_FETCHED     — whether children have been fetched
        ROLE_HASH_KEY    — parent hash key (for hash field leaf nodes)
        ROLE_FIELD_NAME  — field name within hash (for hash field leaf nodes)
    """

    ROLE_IS_FOLDER = Qt.ItemDataRole.UserRole + 1
    ROLE_KEY_NAME = Qt.ItemDataRole.UserRole + 2
    ROLE_PREFIX = Qt.ItemDataRole.UserRole + 3
    ROLE_FETCHED = Qt.ItemDataRole.UserRole + 4
    ROLE_HASH_KEY = Qt.ItemDataRole.UserRole + 5
    ROLE_FIELD_NAME = Qt.ItemDataRole.UserRole + 6

    HEADERS = ["Name", "Type", "Size"]

    def __init__(
        self,
        client: RedisClient,
        tagtypes: dict[str, str] | None = None,
        skip_keys: set[str] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._tagtypes: dict[str, str] = tagtypes or {}
        self._skip_keys: set[str] = skip_keys or set()
        self.setHorizontalHeaderLabels(self.HEADERS)

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    def populate_root(self) -> None:
        """Scan all keys and build the first level of the hierarchy."""
        self.clear_headers()
        keys = self._client.scan_keys("*")
        for row in self._build_child_rows(keys, ""):
            self.appendRow(row)

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if not parent.isValid():
            return True
        item = self.itemFromIndex(parent)
        if item is None:
            return False
        return bool(item.data(self.ROLE_IS_FOLDER))

    def canFetchMore(self, parent: QModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if not parent.isValid():
            return False
        item = self.itemFromIndex(parent)
        if item is None:
            return False
        is_folder = item.data(self.ROLE_IS_FOLDER)
        fetched = item.data(self.ROLE_FETCHED)
        return bool(is_folder and not fetched)

    def fetchMore(self, parent: QModelIndex = QModelIndex()) -> None:  # noqa: N802
        if not parent.isValid():
            return
        item = self.itemFromIndex(parent)
        if item is None:
            return
        if not item.data(self.ROLE_IS_FOLDER):
            return
        if item.data(self.ROLE_FETCHED):
            return

        prefix: str = item.data(self.ROLE_PREFIX) or ""
        keys = self._client.scan_keys(f"{prefix}:*")
        for row in self._build_child_rows(keys, prefix):
            item.appendRow(row)
        item.setData(True, self.ROLE_FETCHED)

    # ──────────────────────────────────────────────
    # Child-row building (shared by populate_root and fetchMore)
    # ──────────────────────────────────────────────

    def _build_child_rows(
        self, keys: list[str], prefix: str
    ) -> list[list[QStandardItem]]:
        """Build QStandardItem rows for keys under *prefix*, expanding hashes inline."""
        rows: list[list[QStandardItem]] = []
        segments = self._parse_keys(keys, prefix)

        for name, is_folder, matching_keys in segments:
            if is_folder:
                child_prefix = f"{prefix}{_DELIMITER}{name}" if prefix else name
                rows.append(self._make_folder_row(name, child_prefix))
            else:
                full_key = matching_keys[0]
                if full_key in self._skip_keys:
                    continue
                key_type = self._safe_type(full_key)
                if key_type == "hash":
                    rows.extend(self._expand_hash_fields(full_key))
                else:
                    rows.append(self._make_leaf_row(name, full_key))
        return rows

    def _expand_hash_fields(self, hash_key: str) -> list[list[QStandardItem]]:
        """Return leaf rows for every field in *hash_key*, sorted alphabetically."""
        try:
            field_names = self._client.hkeys(hash_key)
        except Exception:
            logger.exception("Failed to HKEYS %s", hash_key)
            return []
        rows: list[list[QStandardItem]] = []
        for name in sorted(field_names):
            tag_type = self._tagtypes.get(name, "")
            rows.append(self._make_hash_field_row(name, hash_key, tag_type))
        return rows

    # ──────────────────────────────────────────────
    # Item factories
    # ──────────────────────────────────────────────

    def _make_folder_row(self, name: str, prefix: str) -> list[QStandardItem]:
        item = QStandardItem(name)
        item.setData(True, self.ROLE_IS_FOLDER)
        item.setData(prefix, self.ROLE_PREFIX)
        item.setData(False, self.ROLE_FETCHED)
        item.setEditable(False)
        return [item, self._blank_cell(), self._blank_cell()]

    def _make_leaf_row(self, name: str, full_key: str) -> list[QStandardItem]:
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

    def _make_hash_field_row(
        self, field_name: str, hash_key: str, tag_type: str
    ) -> list[QStandardItem]:
        item = QStandardItem(field_name)
        item.setData(False, self.ROLE_IS_FOLDER)
        item.setData(hash_key, self.ROLE_HASH_KEY)
        item.setData(field_name, self.ROLE_FIELD_NAME)
        item.setEditable(False)

        type_cell = QStandardItem(tag_type)
        type_cell.setEditable(False)
        size_cell = self._blank_cell()
        return [item, type_cell, size_cell]

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    def _safe_type(self, key: str) -> str:
        try:
            return self._client.get_key_metadata(key).get("type", "none")
        except Exception:
            return "none"

    def _fetch_metadata_text(self, full_key: str) -> tuple[str, str]:
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

    @staticmethod
    def _parse_keys(
        keys: list[str], prefix: str
    ) -> list[tuple[str, bool, list[str]]]:
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

    def clear(self) -> None:  # type: ignore[override]
        super().clear()
        self.setHorizontalHeaderLabels(self.HEADERS)

    def clear_headers(self) -> None:
        self.setHorizontalHeaderLabels(self.HEADERS)

    def mimeData(self, idxs: Any) -> QMimeData:  # noqa: N802
        """Return mime data with field/key names for drag operations."""
        mdata = QMimeData()
        names: list[str] = []
        for idx in idxs:
            if idx.column() != 0:
                continue
            item = self.itemFromIndex(idx)
            if item is None:
                continue
            field_name = item.data(self.ROLE_FIELD_NAME)
            if field_name:
                names.append(field_name)
            else:
                key_name = item.data(self.ROLE_KEY_NAME)
                if key_name:
                    names.append(key_name)
        mdata.setText("\n".join(names))
        return mdata


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
        return self._model

    @property
    def view(self) -> QTreeView:
        return self._view

    def set_client(self, client: RedisClient) -> None:
        self._client = client
        self.set_root(client)

    def set_root(self, client: RedisClient) -> None:
        """Build tree model with tagtypes + skip metadata keys."""
        self._client = client
        tagtypes: dict[str, str] = {}
        try:
            tagtypes = client.hgetall_hash("ots-pim:tagtypes")
        except Exception:
            pass
        skip_keys = {"ots-pim:tagtypes"}
        self._model = RedisTreeModel(client, tagtypes=tagtypes, skip_keys=skip_keys)
        self._view.setModel(self._model)
        try:
            self._model.populate_root()
        except Exception as ex:
            self.error.emit(ex)

    def clear(self) -> None:
        if self._model is not None:
            self._model.clear()

    def get_current_key(self) -> str | None:
        """Return full Redis key name of the selected regular leaf, or None."""
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
        if item.data(RedisTreeModel.ROLE_HASH_KEY):
            return None
        return item.data(RedisTreeModel.ROLE_KEY_NAME)

    def get_current_hash_field(self) -> tuple[str, str] | None:
        """Return (hash_key, field_name) if a hash field is selected, else None."""
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
        hash_key = item.data(RedisTreeModel.ROLE_HASH_KEY)
        if not hash_key:
            return None
        field_name = item.data(RedisTreeModel.ROLE_FIELD_NAME)
        return (hash_key, field_name)

    def get_current_field_type(self) -> str | None:
        """Return the data type text of the currently selected item's Type column."""
        if self._model is None:
            return None
        index = self._view.currentIndex()
        if not index.isValid():
            return None
        col1 = index.siblingAtColumn(1)
        item = self._model.itemFromIndex(col1)
        if item is None:
            return None
        return item.text()

    def get_current_prefix(self) -> str | None:
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
