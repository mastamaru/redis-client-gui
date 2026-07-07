"""AttrsWidget — Redis key metadata + value display (replaces opcua AttrsWidget).

Displays key metadata in a QTreeView with two columns:
    Property | Value
    Key Name | my:key
    Type     | string
    TTL      | 300
    Size     | 11
    Value    | (double-click to edit)

Double-clicking the Value row opens a ValueEditorDialog for inline editing.
"""
from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QModelIndex, QObject, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QTreeView

from redisclient.redis_client import RedisClient
from rediswidgets.value_editor_dialog import ValueEditorDialog

logger = logging.getLogger(__name__)

_PROPERTY_ROWS: list[tuple[str, str]] = [
    ("Key Name", ""),
    ("Type", ""),
    ("TTL", ""),
    ("Size", ""),
    ("Value", "(double-click to edit)"),
]


class AttrsWidget(QObject):
    """Controller that displays Redis key metadata in a QTreeView."""

    error = pyqtSignal(Exception)

    def __init__(self, view: QTreeView) -> None:
        QObject.__init__(self)
        self._view = view
        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(["Property", "Value"])
        self._view.setModel(self._model)

        self._client: RedisClient | None = None
        self._key_name: str | None = None
        self._value: Any = None

        self._view.doubleClicked.connect(self._on_double_click)

    @property
    def model(self) -> QStandardItemModel:
        return self._model

    @property
    def view(self) -> QTreeView:
        return self._view

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    def show_key(self, client: RedisClient, key_name: str) -> None:
        """Load metadata + value for *key_name* and populate the display."""
        self._client = client
        self._key_name = key_name
        self._load()

    def show_hash_field(
        self,
        client: RedisClient,
        hash_key: str,
        field_name: str,
        tag_type: str | None = None,
    ) -> None:
        """Show attributes for a hash field: Field, Data Type, Value."""
        self._client = client
        self._key_name = field_name
        self.clear()

        if tag_type is None:
            tag_type = "float"

        try:
            values = client.hmget_fields(hash_key, [field_name])
            raw_value = values.get(field_name)
        except Exception as ex:
            logger.exception("Failed to read hash field %s:%s", hash_key, field_name)
            self.error.emit(ex)
            return

        display_value = self._format_field_value(raw_value, tag_type)

        self._add_row("Field", field_name)
        self._add_row("Data Type", tag_type)
        self._add_row("Value", display_value)

    @staticmethod
    def _format_field_value(raw: str | None, tag_type: str) -> str:
        if raw is None:
            return "—"
        if tag_type == "bool":
            try:
                return str(int(float(raw)))
            except (ValueError, TypeError):
                return str(raw)
        if tag_type == "float":
            try:
                return f"{float(raw):.3f}"
            except (ValueError, TypeError):
                return str(raw)
        return str(raw)

    def reload(self) -> None:
        """Reload the current key's data."""
        if self._client is None or self._key_name is None:
            return
        self._load()

    def clear(self) -> None:
        """Clear all rows from the display."""
        self._model.removeRows(0, self._model.rowCount())

    def get_property(self, property_name: str) -> str | None:
        """Return the value-column text for a named property row, or None."""
        for row in range(self._model.rowCount()):
            prop_item = self._model.item(row, 0)
            if prop_item is not None and prop_item.text() == property_name:
                val_item = self._model.item(row, 1)
                return val_item.text() if val_item else None
        return None

    # ──────────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────────

    def _load(self) -> None:
        """Fetch metadata + value from the client and populate rows."""
        assert self._client is not None
        assert self._key_name is not None

        self.clear()

        try:
            meta = self._client.get_key_metadata(self._key_name)
            self._value = self._client.get_value(self._key_name)
        except Exception as ex:
            logger.exception("Failed to load key '%s'", self._key_name)
            self.error.emit(ex)
            return

        key_type = str(meta.get("type", "none"))
        ttl = meta.get("ttl", -1)
        size = meta.get("size", 0)

        self._add_row("Key Name", self._key_name)
        self._add_row("Type", key_type)
        self._add_row("TTL", str(ttl))
        self._add_row("Size", str(size))
        self._add_row("Value", "(double-click to edit)")

    def _add_row(self, property_name: str, value: str) -> None:
        """Append a (Property, Value) row to the model."""
        prop_item = QStandardItem(property_name)
        prop_item.setEditable(False)
        val_item = QStandardItem(value)
        val_item.setEditable(False)
        self._model.appendRow([prop_item, val_item])

    def _on_double_click(self, index: QModelIndex) -> None:
        """Handle double-click on the Value row — open the editor dialog."""
        if self._client is None or self._key_name is None:
            return
        if not index.isValid():
            return

        prop_item = self._model.item(index.row(), 0)
        if prop_item is None or prop_item.text() != "Value":
            return

        key_type = self.get_property("Type") or "none"
        if key_type == "none":
            return

        try:
            dialog = ValueEditorDialog(
                self._client,
                self._key_name,
                self._value,
                key_type,
                parent=self._view,
            )
            if dialog.exec():
                self._load()
        except Exception as ex:
            logger.exception("Error opening value editor")
            self.error.emit(ex)
