"""Tests for TreeWidget and RedisTreeModel — TDD RED phase."""
from __future__ import annotations

import pytest
import fakeredis
from PyQt6.QtWidgets import QTreeView

from redisclient.redis_client import RedisClient
from rediswidgets.tree_widget import RedisTreeModel, TreeWidget


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def client_with_data() -> RedisClient:
    """RedisClient with seeded fakeredis data."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    fake.set("sensors:temperature:room-01", "25.5")
    fake.set("sensors:temperature:room-02", "26.0")
    fake.set("sensors:humidity:room-01", "70")
    fake.set("devices:status", "online")
    client = RedisClient()
    client.attach(fake)
    return client


@pytest.fixture
def empty_client() -> RedisClient:
    """RedisClient with no keys."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    client = RedisClient()
    client.attach(fake)
    return client


# ──────────────────────────────────────────────────────────────
# RedisTreeModel — Hierarchy building
# ──────────────────────────────────────────────────────────────

class TestRedisTreeModelRoot:
    """Tests for root-level hierarchy construction."""

    def test_model_root_has_folders(self, qapp, client_with_data: RedisClient) -> None:
        """Keys sensors:* and devices:* → root has 2 children: devices, sensors."""
        model = RedisTreeModel(client_with_data)
        model.populate_root()

        assert model.rowCount() == 2
        devices_item = model.item(0, 0)
        sensors_item = model.item(1, 0)
        assert devices_item.text() == "devices"
        assert sensors_item.text() == "sensors"

    def test_model_empty_keyspace(self, qapp, empty_client: RedisClient) -> None:
        """No keys → root has no children."""
        model = RedisTreeModel(empty_client)
        model.populate_root()

        assert model.rowCount() == 0

    def test_model_single_key_no_delimiter(self, qapp) -> None:
        """Key 'mykey' → single leaf at root."""
        fake = fakeredis.FakeRedis(decode_responses=True)
        fake.set("mykey", "val")
        client = RedisClient()
        client.attach(fake)

        model = RedisTreeModel(client)
        model.populate_root()

        assert model.rowCount() == 1
        item = model.item(0, 0)
        assert item.text() == "mykey"
        assert not model.canFetchMore(model.index(0, 0))


class TestRedisTreeModelExpand:
    """Tests for lazy folder expansion."""

    def test_model_expand_folder(self, qapp, client_with_data: RedisClient) -> None:
        """Expanding 'sensors' shows children: humidity (folder), temperature (folder)."""
        model = RedisTreeModel(client_with_data)
        model.populate_root()

        sensors_index = model.index(1, 0)  # "sensors" at root row 1

        # Lazy: 0 children before fetch
        assert model.rowCount(sensors_index) == 0
        assert model.canFetchMore(sensors_index)

        model.fetchMore(sensors_index)

        assert model.rowCount(sensors_index) == 2
        humidity_item = model.itemFromIndex(model.index(0, 0, sensors_index))
        temperature_item = model.itemFromIndex(model.index(1, 0, sensors_index))
        assert humidity_item.text() == "humidity"
        assert temperature_item.text() == "temperature"

    def test_model_parse_delimiter(self, qapp) -> None:
        """'a:b:c' creates 3 levels: a(folder) > b(folder) > c(leaf)."""
        fake = fakeredis.FakeRedis(decode_responses=True)
        fake.set("a:b:c", "val")
        client = RedisClient()
        client.attach(fake)

        model = RedisTreeModel(client)
        model.populate_root()

        # Level 1: a (folder)
        assert model.rowCount() == 1
        a_index = model.index(0, 0)
        assert model.itemFromIndex(a_index).text() == "a"
        assert model.canFetchMore(a_index)

        # Level 2: b (folder)
        model.fetchMore(a_index)
        assert model.rowCount(a_index) == 1
        b_index = model.index(0, 0, a_index)
        assert model.itemFromIndex(b_index).text() == "b"
        assert model.canFetchMore(b_index)

        # Level 3: c (leaf)
        model.fetchMore(b_index)
        assert model.rowCount(b_index) == 1
        c_index = model.index(0, 0, b_index)
        assert model.itemFromIndex(c_index).text() == "c"
        assert not model.canFetchMore(c_index)

    def test_model_can_fetch_more_only_once(self, qapp, client_with_data: RedisClient) -> None:
        """After fetchMore, canFetchMore returns False for that index."""
        model = RedisTreeModel(client_with_data)
        model.populate_root()

        sensors_index = model.index(1, 0)
        assert model.canFetchMore(sensors_index)

        model.fetchMore(sensors_index)
        assert not model.canFetchMore(sensors_index)


class TestRedisTreeModelLeaf:
    """Tests for leaf node metadata."""

    def test_model_leaf_has_type_and_size(self, qapp, client_with_data: RedisClient) -> None:
        """Leaf node 'devices:status' shows Type='string', Size in columns 1 and 2."""
        model = RedisTreeModel(client_with_data)
        model.populate_root()

        devices_index = model.index(0, 0)  # "devices" at root row 0
        model.fetchMore(devices_index)

        # status is the only child of devices, a leaf
        status_index_col0 = model.index(0, 0, devices_index)
        status_index_col1 = model.index(0, 1, devices_index)  # Type
        status_index_col2 = model.index(0, 2, devices_index)  # Size

        assert model.data(status_index_col0) == "status"
        assert model.data(status_index_col1) == "string"
        # "online" has 6 bytes
        assert model.data(status_index_col2) == "6"

    def test_model_leaf_user_role_has_full_key(self, qapp, client_with_data: RedisClient) -> None:
        """Leaf node stores full key name in UserRole data."""
        model = RedisTreeModel(client_with_data)
        model.populate_root()

        devices_index = model.index(0, 0)
        model.fetchMore(devices_index)

        status_item = model.itemFromIndex(model.index(0, 0, devices_index))
        key_data = status_item.data(RedisTreeModel.ROLE_KEY_NAME)
        assert key_data == "devices:status"

    def test_model_folder_user_role_has_prefix(self, qapp, client_with_data: RedisClient) -> None:
        """Folder node stores prefix path in UserRole data."""
        model = RedisTreeModel(client_with_data)
        model.populate_root()

        sensors_item = model.item(1, 0)  # "sensors"
        prefix_data = sensors_item.data(RedisTreeModel.ROLE_PREFIX)
        assert prefix_data == "sensors"

    def test_model_nested_folder_prefix(self, qapp, client_with_data: RedisClient) -> None:
        """Nested folder stores full prefix path (e.g. 'sensors:temperature')."""
        model = RedisTreeModel(client_with_data)
        model.populate_root()

        sensors_index = model.index(1, 0)
        model.fetchMore(sensors_index)

        temp_item = model.itemFromIndex(model.index(1, 0, sensors_index))
        prefix_data = temp_item.data(RedisTreeModel.ROLE_PREFIX)
        assert prefix_data == "sensors:temperature"


# ──────────────────────────────────────────────────────────────
# TreeWidget — Controller
# ──────────────────────────────────────────────────────────────

class TestTreeWidget:
    """Tests for the TreeWidget controller."""

    def test_widget_get_current_key(self, qapp, client_with_data: RedisClient) -> None:
        """Selecting a leaf returns its full key name."""
        view = QTreeView()
        widget = TreeWidget(view)
        widget.set_client(client_with_data)

        # Navigate: root > devices (row 0) > status (row 0)
        devices_index = widget.model.index(0, 0)
        widget.model.fetchMore(devices_index)
        status_index = widget.model.index(0, 0, devices_index)

        view.setCurrentIndex(status_index)

        assert widget.get_current_key() == "devices:status"

    def test_widget_get_current_key_folder_returns_none(
        self, qapp, client_with_data: RedisClient
    ) -> None:
        """Selecting a folder returns None from get_current_key."""
        view = QTreeView()
        widget = TreeWidget(view)
        widget.set_client(client_with_data)

        sensors_index = widget.model.index(1, 0)  # "sensors" folder
        view.setCurrentIndex(sensors_index)

        assert widget.get_current_key() is None

    def test_widget_get_current_prefix(self, qapp, client_with_data: RedisClient) -> None:
        """Selecting a folder returns its prefix path."""
        view = QTreeView()
        widget = TreeWidget(view)
        widget.set_client(client_with_data)

        sensors_index = widget.model.index(1, 0)  # "sensors" folder
        view.setCurrentIndex(sensors_index)

        assert widget.get_current_prefix() == "sensors"

    def test_widget_clear(self, qapp, client_with_data: RedisClient) -> None:
        """clear() empties the model."""
        view = QTreeView()
        widget = TreeWidget(view)
        widget.set_client(client_with_data)

        assert widget.model is not None
        assert widget.model.rowCount() == 2

        widget.clear()

        assert widget.model.rowCount() == 0

    def test_widget_error_signal_on_bad_client(self, qapp, empty_client: RedisClient) -> None:
        """error signal is emitted if populate fails."""
        view = QTreeView()
        widget = TreeWidget(view)

        errors: list[Exception] = []
        widget.error.connect(lambda ex: errors.append(ex))

        # Force an error by making scan_keys fail
        def _fail(pattern: str = "*") -> list[str]:
            raise RuntimeError("connection lost")

        empty_client.scan_keys = _fail  # type: ignore[method-assign]
        widget.set_client(empty_client)

        assert len(errors) == 1
        assert isinstance(errors[0], RuntimeError)

    def test_widget_set_root_repopulates(
        self, qapp, client_with_data: RedisClient
    ) -> None:
        """set_root clears and repopulates from scratch."""
        view = QTreeView()
        widget = TreeWidget(view)
        widget.set_client(client_with_data)

        assert widget.model.rowCount() == 2

        widget.set_root(client_with_data)

        assert widget.model.rowCount() == 2
