"""TagMonitorUI — real-time tag monitor via timer-based HMGET polling.

Replaces Redis Pub/Sub subscription for the OTS-PIM use case where all
tags live in a single Redis hash. A QTimer polls the hash every 500ms
for monitored fields and updates the display model.

Columns: Tag | Value | Type | Last Updated
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from redisclient.redis_client import RedisClient

logger = logging.getLogger(__name__)

DEFAULT_POLL_MS = 500
TAGS_HASH = "ots-pim:tags"
TAGTYPES_HASH = "ots-pim:tagtypes"


class TagMonitorUI(QObject):
    """Polls Redis hash fields at a fixed interval and displays current values."""

    error = pyqtSignal(Exception)

    HEADERS = ["Tag", "Value", "Type", "Last Updated"]

    def __init__(self) -> None:
        QObject.__init__(self)
        self._model: QStandardItemModel = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(self.HEADERS)
        self._monitored: dict[str, int] = {}  # tag_name → model row index
        self._client: RedisClient | None = None
        self._tagtypes: dict[str, str] = {}
        self._timer = QTimer()
        self._timer.timeout.connect(self._poll)
        self._timer.setInterval(DEFAULT_POLL_MS)

    @property
    def model(self) -> QStandardItemModel:
        return self._model

    def set_client(self, client: RedisClient) -> None:
        """Attach a client and load tag types."""
        self._client = client
        self._load_tagtypes()

    def _load_tagtypes(self) -> None:
        """Load the tagtypes hash for display formatting."""
        if self._client is None:
            return
        try:
            self._tagtypes = self._client.hgetall_hash(TAGTYPES_HASH)
        except Exception as ex:
            logger.warning("Could not load tagtypes: %s", ex)
            self._tagtypes = {}

    def add_tag(self, tag_name: str) -> None:
        """Add a tag to the monitoring list."""
        if tag_name in self._monitored:
            return
        tag_type = self._tagtypes.get(tag_name, "float")
        row = [
            QStandardItem(tag_name),
            QStandardItem("—"),
            QStandardItem(tag_type),
            QStandardItem(""),
        ]
        for item in row:
            item.setEditable(False)
        self._model.appendRow(row)
        self._monitored[tag_name] = self._model.rowCount() - 1

    def remove_tag(self, tag_name: str) -> None:
        """Remove a tag from monitoring."""
        row = self._monitored.pop(tag_name, None)
        if row is None:
            return
        self._model.removeRow(row)
        shifted: dict[str, int] = {}
        for name, idx in self._monitored.items():
            shifted[name] = idx if idx < row else idx - 1
        self._monitored = shifted

    def get_monitored_tags(self) -> list[str]:
        return list(self._monitored.keys())

    def clear(self) -> None:
        """Remove all monitored tags."""
        self._monitored.clear()
        self._model.removeRows(0, self._model.rowCount())

    def start(self) -> None:
        """Start the polling timer."""
        self._timer.start()

    def stop(self) -> None:
        """Stop the polling timer."""
        self._timer.stop()

    def _poll(self) -> None:
        """Poll Redis for current values of all monitored tags."""
        if self._client is None or not self._monitored:
            return
        tags = list(self._monitored.keys())
        try:
            values = self._client.hmget_fields(TAGS_HASH, tags)
        except Exception as ex:
            logger.warning("Poll failed: %s", ex)
            self.error.emit(ex)
            return

        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        for tag_name, row_idx in self._monitored.items():
            raw = values.get(tag_name)
            display = self._format_value(raw, tag_name)
            val_item = self._model.item(row_idx, 1)
            ts_item = self._model.item(row_idx, 3)
            if val_item is not None:
                val_item.setText(display)
            if ts_item is not None:
                ts_item.setText(now)

    def _format_value(self, raw: str | None, tag_name: str) -> str:
        """Format a raw value based on tag type."""
        if raw is None:
            return "—"
        tag_type = self._tagtypes.get(tag_name, "float")
        if tag_type == "bool":
            try:
                return "ON" if float(raw) != 0 else "OFF"
            except (ValueError, TypeError):
                return str(raw)
        if tag_type == "float":
            try:
                return f"{float(raw):.3f}"
            except (ValueError, TypeError):
                return str(raw)
        return str(raw)

    def build_controls(self) -> QWidget:
        """Build a small control bar (Add tag input + Remove button)."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)

        layout.addWidget(QLabel("Tag:"))
        self._tag_input = QLineEdit()
        self._tag_input.setPlaceholderText("e.g. LIC1003A_PV")
        layout.addWidget(self._tag_input)

        self._add_button = QPushButton("Add")
        self._add_button.clicked.connect(self._on_add_clicked)
        layout.addWidget(self._add_button)

        self._remove_button = QPushButton("Remove")
        self._remove_button.clicked.connect(self._on_remove_clicked)
        layout.addWidget(self._remove_button)

        self._clear_button = QPushButton("Clear All")
        self._clear_button.clicked.connect(self.clear)
        layout.addWidget(self._clear_button)

        return container

    def _on_add_clicked(self) -> None:
        name = self._tag_input.text().strip()
        if name:
            self.add_tag(name)
            self._tag_input.clear()

    def _on_remove_clicked(self) -> None:
        name = self._tag_input.text().strip()
        if name:
            self.remove_tag(name)
            self._tag_input.clear()
