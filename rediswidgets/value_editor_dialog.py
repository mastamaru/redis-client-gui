"""ValueEditorDialog — per-type Redis value editor dialog.

Displays a Redis key's value in a type-appropriate editor:
    string -> QPlainTextEdit (multiline editable text)
    hash   -> QTableWidget (Field, Value)
    list   -> QTableWidget (Index, Value)
    set    -> QListWidget of members
    zset   -> QTableWidget (Member, Score)
"""
from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from redisclient.redis_client import RedisClient

logger = logging.getLogger(__name__)


class ValueEditorDialog(QDialog):
    """Dialog for editing a Redis key's value with a type-appropriate widget."""

    def __init__(
        self,
        client: RedisClient,
        key_name: str,
        value: Any,
        key_type: str,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._key_name = key_name
        self._key_type = key_type
        self._value: Any = value

        self._text_edit: QPlainTextEdit | None = None
        self._table: QTableWidget | None = None
        self._list_widget: QListWidget | None = None

        self.setWindowTitle(f"Edit Value — {key_name}")
        self._build_ui()

    @property
    def key_name(self) -> str:
        return self._key_name

    @property
    def value(self) -> Any:
        """Return the current edited value, typed per key_type."""
        if self._key_type == "string" and self._text_edit is not None:
            return self._text_edit.toPlainText()
        elif self._key_type == "hash" and self._table is not None:
            return self._collect_hash()
        elif self._key_type == "list" and self._table is not None:
            return self._collect_list()
        elif self._key_type == "set" and self._list_widget is not None:
            return self._collect_set()
        elif self._key_type == "zset" and self._table is not None:
            return self._collect_zset()
        return self._value

    # ──────────────────────────────────────────────
    # UI construction
    # ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        builder = {
            "string": self._build_string_editor,
            "hash": self._build_hash_editor,
            "list": self._build_list_editor,
            "set": self._build_set_editor,
            "zset": self._build_zset_editor,
        }.get(self._key_type)

        if builder is None:
            text = QPlainTextEdit()
            text.setPlainText(str(self._value))
            text.setReadOnly(True)
            layout.addWidget(text)
        else:
            builder()

        self._build_buttons(layout)

    def _build_string_editor(self) -> None:
        self._text_edit = QPlainTextEdit()
        self._text_edit.setPlainText(self._value if self._value is not None else "")
        self.layout().addWidget(self._text_edit)

    def _build_hash_editor(self) -> None:
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Field", "Value"])
        self.layout().addWidget(self._table)

        add_btn = QPushButton("Add Row")
        del_btn = QPushButton("Delete Row")

        button_row = QHBoxLayout()
        button_row.addWidget(add_btn)
        button_row.addWidget(del_btn)
        button_row.addStretch()

        layout = self.layout()
        layout.addLayout(button_row)

        add_btn.clicked.connect(self._add_hash_row)
        del_btn.clicked.connect(self._delete_table_row)

        data: dict[str, str] = self._value if isinstance(self._value, dict) else {}
        for field, val in data.items():
            self._add_hash_row(field, val)

    def _build_list_editor(self) -> None:
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Index", "Value"])
        self.layout().addWidget(self._table)

        add_btn = QPushButton("Add Row")
        del_btn = QPushButton("Delete Row")

        button_row = QHBoxLayout()
        button_row.addWidget(add_btn)
        button_row.addWidget(del_btn)
        button_row.addStretch()

        layout = self.layout()
        layout.addLayout(button_row)

        add_btn.clicked.connect(lambda: self._add_list_row(len(self._collect_list())))
        del_btn.clicked.connect(self._delete_table_row)

        items: list[str] = self._value if isinstance(self._value, list) else []
        for i, item in enumerate(items):
            self._add_list_row(i, item)

    def _build_set_editor(self) -> None:
        self._list_widget = QListWidget()
        self.layout().addWidget(self._list_widget)

        add_btn = QPushButton("Add Member")
        del_btn = QPushButton("Delete Member")

        button_row = QHBoxLayout()
        button_row.addWidget(add_btn)
        button_row.addWidget(del_btn)
        button_row.addStretch()

        layout = self.layout()
        layout.addLayout(button_row)

        add_btn.clicked.connect(self._add_set_member)
        del_btn.clicked.connect(self._delete_set_member)

        members: set[str] = self._value if isinstance(self._value, set) else set()
        for member in sorted(members):
            item = QListWidgetItem(member)
            self._list_widget.addItem(item)

    def _build_zset_editor(self) -> None:
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Member", "Score"])
        self.layout().addWidget(self._table)

        add_btn = QPushButton("Add Row")
        del_btn = QPushButton("Delete Row")

        button_row = QHBoxLayout()
        button_row.addWidget(add_btn)
        button_row.addWidget(del_btn)
        button_row.addStretch()

        layout = self.layout()
        layout.addLayout(button_row)

        add_btn.clicked.connect(lambda: self._add_zset_row("", 0.0))
        del_btn.clicked.connect(self._delete_table_row)

        pairs: list[tuple[str, float]] = (
            self._value if isinstance(self._value, list) else []
        )
        for member, score in pairs:
            self._add_zset_row(member, score)

    def _build_buttons(self, layout: QVBoxLayout) -> None:
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    # ──────────────────────────────────────────────
    # Row helpers
    # ──────────────────────────────────────────────

    def _add_hash_row(self, field: str = "", val: str = "") -> None:
        if self._table is None:
            return
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(field))
        self._table.setItem(row, 1, QTableWidgetItem(val))

    def _add_list_row(self, index: int = 0, val: str = "") -> None:
        if self._table is None:
            return
        row = self._table.rowCount()
        self._table.insertRow(row)
        idx_item = QTableWidgetItem(str(index))
        idx_item.setFlags(idx_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, 0, idx_item)
        self._table.setItem(row, 1, QTableWidgetItem(val))

    def _add_zset_row(self, member: str = "", score: float = 0.0) -> None:
        if self._table is None:
            return
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(member))
        self._table.setItem(row, 1, QTableWidgetItem(str(score)))

    def _add_set_member(self) -> None:
        if self._list_widget is None:
            return
        item = QListWidgetItem("")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self._list_widget.addItem(item)

    def _delete_table_row(self) -> None:
        if self._table is None:
            return
        row = self._table.currentRow()
        if row >= 0:
            self._table.removeRow(row)

    def _delete_set_member(self) -> None:
        if self._list_widget is None:
            return
        row = self._list_widget.currentRow()
        if row >= 0:
            self._list_widget.takeItem(row)

    # ──────────────────────────────────────────────
    # Value collectors
    # ──────────────────────────────────────────────

    def _collect_hash(self) -> dict[str, str]:
        if self._table is None:
            return {}
        result: dict[str, str] = {}
        for row in range(self._table.rowCount()):
            field_item = self._table.item(row, 0)
            val_item = self._table.item(row, 1)
            field = field_item.text() if field_item else ""
            val = val_item.text() if val_item else ""
            if field:
                result[field] = val
        return result

    def _collect_list(self) -> list[str]:
        if self._table is None:
            return []
        result: list[str] = []
        for row in range(self._table.rowCount()):
            val_item = self._table.item(row, 1)
            result.append(val_item.text() if val_item else "")
        return result

    def _collect_set(self) -> set[str]:
        if self._list_widget is None:
            return set()
        return {
            self._list_widget.item(i).text()
            for i in range(self._list_widget.count())
            if self._list_widget.item(i) is not None
        }

    def _collect_zset(self) -> list[tuple[str, float]]:
        if self._table is None:
            return []
        result: list[tuple[str, float]] = []
        for row in range(self._table.rowCount()):
            member_item = self._table.item(row, 0)
            score_item = self._table.item(row, 1)
            member = member_item.text() if member_item else ""
            try:
                score = float(score_item.text()) if score_item else 0.0
            except ValueError:
                score = 0.0
            result.append((member, score))
        return result

    # ──────────────────────────────────────────────
    # Save logic
    # ──────────────────────────────────────────────

    def accept(self) -> None:
        """Save the edited value to Redis, then close the dialog."""
        try:
            new_value = self.value
            if self._key_type == "zset":
                self._save_zset(new_value)
            else:
                self._client.set_value(self._key_name, new_value)
            logger.info("Saved value for key '%s'", self._key_name)
        except Exception as ex:
            logger.exception("Failed to save value for key '%s'", self._key_name)
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "Save Error", f"Failed to save: {ex}")
            return

        super().accept()

    def _save_zset(self, pairs: list[tuple[str, float]]) -> None:
        """Save sorted set using type-specific ZADD command."""
        self._client.delete_key(self._key_name)
        if pairs:
            args: list[Any] = []
            for member, score in pairs:
                args.extend([score, member])
            self._client.execute_command("ZADD", self._key_name, *args)
