"""Tests for CommandDialog — TDD RED phase."""
from __future__ import annotations

import pytest
import fakeredis
from PyQt6.QtCore import QCoreApplication, QSettings
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
)

from redisclient.redis_client import RedisClient
from redisclient.command_dialog import CommandDialog


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def client_with_fake() -> RedisClient:
    """Create a RedisClient attached to a fakeredis instance."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    client = RedisClient()
    client.attach(fake)
    return client


@pytest.fixture
def dialog(client_with_fake: RedisClient, qtbot: pytest.QtBot) -> CommandDialog:
    """Create a CommandDialog for testing with isolated QSettings."""
    QCoreApplication.setOrganizationName("TestRedis")
    QCoreApplication.setApplicationName("CmdDlg")
    QSettings().clear()
    dlg = CommandDialog(client=client_with_fake)
    qtbot.addWidget(dlg)
    yield dlg
    QSettings().clear()


# ──────────────────────────────────────────────────────────────
# UI Rendering
# ──────────────────────────────────────────────────────────────

class TestDialogRenders:
    def test_dialog_renders(self, dialog: CommandDialog) -> None:
        """Dialog has command input, execute button, clear button, output area, mode toggle."""
        assert isinstance(dialog, QDialog)

        assert isinstance(dialog.command_combo, QComboBox)
        assert dialog.command_combo.isEditable()

        assert isinstance(dialog.execute_button, QPushButton)
        assert isinstance(dialog.clear_button, QPushButton)

        assert isinstance(dialog.output_edit, QPlainTextEdit)
        assert dialog.output_edit.isReadOnly()

        assert isinstance(dialog.mode_tabs, QTabWidget)
        assert dialog.mode_tabs.count() == 2

        # Lua mode widgets exist
        assert isinstance(dialog.script_edit, QPlainTextEdit)
        assert isinstance(dialog.keys_edit, QLineEdit)
        assert isinstance(dialog.args_edit, QLineEdit)


# ──────────────────────────────────────────────────────────────
# Command Execution
# ──────────────────────────────────────────────────────────────

class TestExecuteCommand:
    def test_execute_ping(self, dialog: CommandDialog) -> None:
        """Execute 'PING' -> output contains 'PONG' or True."""
        dialog.command_combo.setEditText("PING")
        dialog._execute_command()
        text = dialog.output_edit.toPlainText().upper()
        assert "PONG" in text or "TRUE" in text

    def test_execute_set_get(self, dialog: CommandDialog) -> None:
        """Execute 'SET testkey hello' then 'GET testkey' -> output shows 'hello'."""
        dialog.command_combo.setEditText("SET testkey hello")
        dialog._execute_command()
        dialog.command_combo.setEditText("GET testkey")
        dialog._execute_command()
        text = dialog.output_edit.toPlainText()
        assert "hello" in text

    def test_command_with_args(self, dialog: CommandDialog) -> None:
        """Execute 'SET key value' parses into command='SET', args=['key','value']."""
        command, args = dialog._parse_command("SET key value")
        assert command == "SET"
        assert args == ["key", "value"]


# ──────────────────────────────────────────────────────────────
# Lua Script Execution
# ──────────────────────────────────────────────────────────────

class TestLuaScript:
    def test_lua_script_execution(self, dialog: CommandDialog) -> None:
        """Simple Lua script returns result."""
        dialog.script_edit.setPlainText("return 42")
        dialog._execute_lua()
        text = dialog.output_edit.toPlainText()
        assert "42" in text

    def test_lua_script_with_keys(self, dialog: CommandDialog) -> None:
        """Lua with KEYS[1] reads a key."""
        client = dialog._client
        client.execute_command("SET", "myluakey", "lua-val")
        dialog.script_edit.setPlainText("return redis.call('GET', KEYS[1])")
        dialog.keys_edit.setText("myluakey")
        dialog._execute_lua()
        text = dialog.output_edit.toPlainText()
        assert "lua-val" in text


# ──────────────────────────────────────────────────────────────
# Result Formatting
# ──────────────────────────────────────────────────────────────

class TestResultFormatting:
    def test_result_formatting_string(self, dialog: CommandDialog) -> None:
        """String result formatted correctly."""
        formatted = dialog._format_result("hello")
        assert formatted == "hello"

    def test_result_formatting_list(self, dialog: CommandDialog) -> None:
        """List result as numbered lines."""
        formatted = dialog._format_result(["a", "b", "c"])
        assert "1)" in formatted
        assert "a" in formatted
        assert "2)" in formatted
        assert "b" in formatted
        assert "3)" in formatted
        assert "c" in formatted

    def test_result_formatting_nil(self, dialog: CommandDialog) -> None:
        """None result as '(nil)'."""
        formatted = dialog._format_result(None)
        assert formatted == "(nil)"


# ──────────────────────────────────────────────────────────────
# History Persistence
# ──────────────────────────────────────────────────────────────

class TestHistoryPersistence:
    def test_command_history_persists(self, dialog: CommandDialog) -> None:
        """Commands saved and restored via QSettings."""
        dialog.command_combo.setEditText("PING")
        dialog._execute_command()
        dialog.command_combo.setEditText("SET foo bar")
        dialog._execute_command()

        # New dialog instance should restore history from QSettings
        dlg2 = CommandDialog(client=dialog._client)
        try:
            items = [dlg2.command_combo.itemText(i)
                     for i in range(dlg2.command_combo.count())]
            assert "PING" in items
            assert "SET foo bar" in items
        finally:
            dlg2.deleteLater()


# ──────────────────────────────────────────────────────────────
# Error Display
# ──────────────────────────────────────────────────────────────

class TestErrorDisplay:
    def test_error_display(self, dialog: CommandDialog) -> None:
        """Invalid command shows error message."""
        dialog.command_combo.setEditText("BOGUSCOMMAND")
        dialog._execute_command()
        text = dialog.output_edit.toPlainText()
        assert "ERROR" in text.upper()
