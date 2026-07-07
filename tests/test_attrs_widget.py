"""Tests for AttrsWidget and ValueEditorDialog — TDD RED phase."""
from __future__ import annotations

import pytest
import fakeredis
from PyQt6.QtWidgets import (
    QListWidget,
    QPlainTextEdit,
    QTableView,
    QTableWidget,
    QTreeView,
)

from redisclient.redis_client import RedisClient
from rediswidgets.attrs_widget import AttrsWidget
from rediswidgets.value_editor_dialog import ValueEditorDialog


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def client_with_data() -> RedisClient:
    """RedisClient with seeded fakeredis data covering all types."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    fake.set("str:key", "hello world")
    fake.hset("hash:key", mapping={"field1": "val1", "field2": "val2"})
    fake.rpush("list:key", "a", "b", "c")
    fake.sadd("set:key", "m1", "m2")
    fake.zadd("zset:key", {"alpha": 1, "beta": 2})
    fake.set("ttl:key", "temp")
    fake.expire("ttl:key", 300)
    client = RedisClient()
    client.attach(fake)
    return client


# ──────────────────────────────────────────────────────────────
# AttrsWidget — Metadata display
# ──────────────────────────────────────────────────────────────

class TestAttrsWidgetMetadata:
    """Tests for metadata display in the QTreeView."""

    def test_show_metadata_string(self, qapp, client_with_data: RedisClient) -> None:
        """show_key with string key: Type='string', Size correct."""
        view = QTreeView()
        widget = AttrsWidget(view)
        widget.show_key(client_with_data, "str:key")

        assert widget.model is not None
        type_val = widget.get_property("Type")
        size_val = widget.get_property("Size")
        assert type_val == "string"
        assert size_val == "11"

    def test_show_metadata_hash(self, qapp, client_with_data: RedisClient) -> None:
        """show_key with hash key: Type='hash', Size=2."""
        view = QTreeView()
        widget = AttrsWidget(view)
        widget.show_key(client_with_data, "hash:key")

        assert widget.get_property("Type") == "hash"
        assert widget.get_property("Size") == "2"

    def test_show_metadata_ttl(self, qapp, client_with_data: RedisClient) -> None:
        """Key with TTL: TTL row shows positive number."""
        view = QTreeView()
        widget = AttrsWidget(view)
        widget.show_key(client_with_data, "ttl:key")

        ttl_val = widget.get_property("TTL")
        assert int(ttl_val) > 0

    def test_show_metadata_none_key(self, qapp, client_with_data: RedisClient) -> None:
        """Nonexistent key: Type='none'."""
        view = QTreeView()
        widget = AttrsWidget(view)
        widget.show_key(client_with_data, "nonexistent:key")

        assert widget.get_property("Type") == "none"


class TestAttrsWidgetManagement:
    """Tests for clear() and reload()."""

    def test_attrs_clear(self, qapp, client_with_data: RedisClient) -> None:
        """clear() removes all rows from the model."""
        view = QTreeView()
        widget = AttrsWidget(view)
        widget.show_key(client_with_data, "str:key")

        assert widget.model is not None
        assert widget.model.rowCount() > 0

        widget.clear()

        assert widget.model.rowCount() == 0

    def test_attrs_reload(self, qapp, client_with_data: RedisClient) -> None:
        """reload() refreshes current key data."""
        view = QTreeView()
        widget = AttrsWidget(view)
        widget.show_key(client_with_data, "str:key")

        # Modify value behind the scenes
        client_with_data.set_value("str:key", "changed value")

        widget.reload()

        size_val = widget.get_property("Size")
        assert size_val == str(len("changed value"))


# ──────────────────────────────────────────────────────────────
# ValueEditorDialog — per-type editors
# ──────────────────────────────────────────────────────────────

class TestValueEditorString:
    """Tests for string value editor."""

    def test_value_editor_string_displays_text(
        self, qapp, client_with_data: RedisClient
    ) -> None:
        """ValueEditorDialog for string shows editable text with current value."""
        value = client_with_data.get_value("str:key")
        dialog = ValueEditorDialog(client_with_data, "str:key", value, "string")

        text_edit = dialog.findChild(QPlainTextEdit)
        assert text_edit is not None
        assert text_edit.toPlainText() == "hello world"

    def test_value_editor_string_save_calls_set_value(
        self, qapp, client_with_data: RedisClient
    ) -> None:
        """Editing text and accepting calls client.set_value."""
        value = client_with_data.get_value("str:key")
        dialog = ValueEditorDialog(client_with_data, "str:key", value, "string")

        text_edit = dialog.findChild(QPlainTextEdit)
        text_edit.setPlainText("edited value")

        calls: list[tuple[str, str]] = []

        def spy(key: str, val: object) -> None:
            calls.append((key, val))

        client_with_data.set_value = spy  # type: ignore[method-assign]
        dialog.accept()

        assert len(calls) == 1
        assert calls[0][0] == "str:key"
        assert calls[0][1] == "edited value"

    def test_value_editor_string_property(
        self, qapp, client_with_data: RedisClient
    ) -> None:
        """value property returns edited text."""
        value = client_with_data.get_value("str:key")
        dialog = ValueEditorDialog(client_with_data, "str:key", value, "string")

        assert dialog.key_name == "str:key"
        assert dialog.value == "hello world"


class TestValueEditorHash:
    """Tests for hash value editor."""

    def test_value_editor_hash_shows_table(
        self, qapp, client_with_data: RedisClient
    ) -> None:
        """ValueEditorDialog for hash shows field-value table with 2 rows."""
        value = client_with_data.get_value("hash:key")
        dialog = ValueEditorDialog(client_with_data, "hash:key", value, "hash")

        table = dialog.findChild(QTableView)
        assert isinstance(table, QTableWidget)
        assert table.columnCount() == 2
        assert table.rowCount() == 2

        fields = {table.item(row, 0).text() for row in range(table.rowCount())}
        assert fields == {"field1", "field2"}


class TestValueEditorList:
    """Tests for list value editor."""

    def test_value_editor_list_shows_items(
        self, qapp, client_with_data: RedisClient
    ) -> None:
        """ValueEditorDialog for list shows all items."""
        value = client_with_data.get_value("list:key")
        dialog = ValueEditorDialog(client_with_data, "list:key", value, "list")

        table = dialog.findChild(QTableView)
        assert isinstance(table, QTableWidget)
        assert table.rowCount() == 3

        values = {table.item(row, 1).text() for row in range(table.rowCount())}
        assert values == {"a", "b", "c"}


class TestValueEditorSet:
    """Tests for set value editor."""

    def test_value_editor_set_shows_members(
        self, qapp, client_with_data: RedisClient
    ) -> None:
        """ValueEditorDialog for set shows all members."""
        value = client_with_data.get_value("set:key")
        dialog = ValueEditorDialog(client_with_data, "set:key", value, "set")

        list_widget = dialog.findChild(QListWidget)
        assert list_widget is not None
        assert list_widget.count() == 2

        members = {
            list_widget.item(i).text() for i in range(list_widget.count())
        }
        assert members == {"m1", "m2"}


class TestValueEditorZset:
    """Tests for sorted set value editor."""

    def test_value_editor_zset_shows_member_score(
        self, qapp, client_with_data: RedisClient
    ) -> None:
        """ValueEditorDialog for zset shows member+score table."""
        value = client_with_data.get_value("zset:key")
        dialog = ValueEditorDialog(client_with_data, "zset:key", value, "zset")

        table = dialog.findChild(QTableView)
        assert isinstance(table, QTableWidget)
        assert table.columnCount() == 2
        assert table.rowCount() == 2

        members = {table.item(row, 0).text() for row in range(table.rowCount())}
        assert members == {"alpha", "beta"}
