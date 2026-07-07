"""CommandDialog — Redis command and Lua script execution dialog.

Provides a tabbed interface for executing raw Redis commands or Lua scripts
and displaying formatted results. Command history persists via QSettings.
"""
from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from redisclient.redis_client import RedisClient

logger = logging.getLogger(__name__)

MAX_HISTORY = 20


class CommandDialog(QDialog):
    """Dialog for executing Redis commands and Lua scripts."""

    def __init__(
        self,
        client: RedisClient | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client: RedisClient | None = client
        self.setWindowTitle("Execute Redis Command")
        self.resize(700, 500)
        self._build_ui()
        self._load_history()

    # ──────────────────────────────────────────────────────────
    # UI construction
    # ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Mode tabs (Command / Lua Script)
        self.mode_tabs = QTabWidget()

        # --- Command tab ---
        cmd_tab = QWidget()
        cmd_layout = QVBoxLayout(cmd_tab)
        cmd_layout.addWidget(QLabel("Command (e.g. SET mykey value):"))
        self.command_combo = QComboBox()
        self.command_combo.setEditable(True)
        self.command_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        cmd_layout.addWidget(self.command_combo)
        cmd_layout.addStretch(1)
        self.mode_tabs.addTab(cmd_tab, "Command")

        # --- Lua Script tab ---
        lua_tab = QWidget()
        lua_layout = QFormLayout(lua_tab)
        self.script_edit = QPlainTextEdit()
        self.script_edit.setPlaceholderText(
            "return redis.call('GET', KEYS[1])"
        )
        lua_layout.addRow("Lua script:", self.script_edit)

        self.keys_edit = QLineEdit()
        self.keys_edit.setPlaceholderText("key1,key2")
        lua_layout.addRow("Keys:", self.keys_edit)

        self.args_edit = QLineEdit()
        self.args_edit.setPlaceholderText("arg1,arg2")
        lua_layout.addRow("Args:", self.args_edit)
        self.mode_tabs.addTab(lua_tab, "Lua Script")

        layout.addWidget(self.mode_tabs)

        # --- Buttons ---
        btn_layout = QHBoxLayout()
        self.execute_button = QPushButton("Execute")
        self.clear_button = QPushButton("Clear")
        self.close_button = QPushButton("Close")
        btn_layout.addWidget(self.execute_button)
        btn_layout.addWidget(self.clear_button)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.close_button)
        layout.addLayout(btn_layout)

        # --- Output ---
        layout.addWidget(QLabel("Output:"))
        self.output_edit = QPlainTextEdit()
        self.output_edit.setReadOnly(True)
        layout.addWidget(self.output_edit, 1)

        # --- Connections ---
        self.execute_button.clicked.connect(self._on_execute_clicked)
        self.clear_button.clicked.connect(self._on_clear_clicked)
        self.close_button.clicked.connect(self.reject)

    # ──────────────────────────────────────────────────────────
    # Slots
    # ──────────────────────────────────────────────────────────

    def _on_execute_clicked(self) -> None:
        """Route execute to the active tab."""
        if self.mode_tabs.currentIndex() == 0:
            self._execute_command()
        else:
            self._execute_lua()

    def _on_clear_clicked(self) -> None:
        """Clear the output area."""
        self.output_edit.clear()

    # ──────────────────────────────────────────────────────────
    # Command mode
    # ──────────────────────────────────────────────────────────

    def _parse_command(self, text: str) -> tuple[str, list[str]]:
        """Split raw command text into (command, args)."""
        parts = text.split()
        if not parts:
            return "", []
        return parts[0], parts[1:]

    def _execute_command(self) -> None:
        """Parse the command input, execute it, and show formatted output."""
        text = self.command_combo.currentText().strip()
        if not text:
            self._append_output("(empty command)")
            return

        command, args = self._parse_command(text)
        if not command:
            self._append_output("(empty command)")
            return

        try:
            if self._client is None:
                raise RuntimeError("No Redis client attached")
            result = self._client.execute_command(command, *args)
            self._append_output(self._format_result(result))
        except Exception as ex:
            logger.exception("Command execution failed: %s", text)
            self._append_output(f"ERROR: {ex}")
        finally:
            self._add_history(text)
            self._save_history()

    # ──────────────────────────────────────────────────────────
    # Lua mode
    # ──────────────────────────────────────────────────────────

    def _execute_lua(self) -> None:
        """Execute the Lua script with provided keys/args and show output."""
        script = self.script_edit.toPlainText().strip()
        if not script:
            self._append_output("(empty script)")
            return

        keys = [k.strip() for k in self.keys_edit.text().split(",") if k.strip()]
        args = [a.strip() for a in self.args_edit.text().split(",") if a.strip()]

        try:
            if self._client is None:
                raise RuntimeError("No Redis client attached")
            result = self._client.eval_script(script, keys=keys, args=args)
            self._append_output(self._format_result(result))
        except Exception as ex:
            logger.exception("Lua script execution failed")
            self._append_output(f"ERROR: {ex}")

    # ──────────────────────────────────────────────────────────
    # Result formatting
    # ──────────────────────────────────────────────────────────

    def _format_result(self, result: Any) -> str:
        """Format a Redis result value into a display string."""
        if result is None:
            return "(nil)"
        if isinstance(result, bool):
            return "true" if result else "false"
        if isinstance(result, (bytes, bytearray)):
            try:
                return result.decode("utf-8")
            except Exception:
                return repr(result)
        if isinstance(result, str):
            return result
        if isinstance(result, list):
            if not result:
                return "(empty list)"
            lines = [
                f"{i}) {self._format_scalar(item)}"
                for i, item in enumerate(result, start=1)
            ]
            return "\n".join(lines)
        if isinstance(result, (int, float)):
            return str(result)
        return str(result)

    @staticmethod
    def _format_scalar(value: Any) -> str:
        """Format a single scalar value within a list."""
        if isinstance(value, (bytes, bytearray)):
            try:
                return value.decode("utf-8")
            except Exception:
                return repr(value)
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _append_output(self, text: str) -> None:
        """Append text to the output area, separated by a newline."""
        current = self.output_edit.toPlainText()
        if current:
            self.output_edit.setPlainText(current + "\n" + text)
        else:
            self.output_edit.setPlainText(text)

    # ──────────────────────────────────────────────────────────
    # History (QSettings)
    # ──────────────────────────────────────────────────────────

    def _settings(self) -> QSettings:
        """Return the QSettings store for command history."""
        return QSettings()

    def _add_history(self, command: str) -> None:
        """Add a command to history (most-recent first, deduped, capped)."""
        existing = [
            self.command_combo.itemText(i)
            for i in range(self.command_combo.count())
        ]
        if command in existing:
            existing.remove(command)
        existing.insert(0, command)
        existing = existing[:MAX_HISTORY]
        self.command_combo.clear()
        self.command_combo.addItems(existing)
        self.command_combo.setEditText(command)

    def _save_history(self) -> None:
        """Persist command history to QSettings."""
        items = [
            self.command_combo.itemText(i)
            for i in range(self.command_combo.count())
        ]
        self._settings().setValue("command_history", items)

    def _load_history(self) -> None:
        """Restore command history from QSettings into the combo dropdown."""
        items = self._settings().value("command_history", []) or []
        if isinstance(items, str):
            items = [items]
        self.command_combo.clear()
        self.command_combo.addItems(items)
