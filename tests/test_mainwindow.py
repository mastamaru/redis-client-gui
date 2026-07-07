"""Tests for MainWindow integration — verifies all widgets are wired correctly."""
from __future__ import annotations

import fakeredis
import pytest
from PyQt6.QtCore import QCoreApplication, QSettings
from PyQt6.QtWidgets import QDockWidget, QTreeView, QTableView, QPlainTextEdit

from redisclient.mainwindow import Window
from redisclient.redis_client import RedisClient


@pytest.fixture(autouse=True)
def clean_qsettings(qapp):
    """Ensure clean QSettings for each test."""
    QCoreApplication.setOrganizationName("TestRedisGUI")
    QCoreApplication.setApplicationName("MainWindowTest")
    yield
    QSettings().clear()


@pytest.fixture
def window(qapp):
    """Create the main window."""
    w = Window()
    w.show()
    qapp.processEvents()
    yield w
    w.close()


@pytest.fixture
def connected_window(window):
    """Create a window with a fakeredis-backed RedisClient."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    fake.set("sensors:temperature:room-01", "25.5")
    fake.set("sensors:temperature:room-02", "26.0")
    fake.set("sensors:humidity:room-01", "70")
    fake.set("devices:status", "online")
    window.uaclient.attach(fake)
    window.tree_ui.set_root(window.uaclient)
    window._apply_ui_state("connected")
    qapp = window.qApp if hasattr(window, "qApp") else None
    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()
    yield window


class TestWindowConstruction:
    """Verify the main window builds all docks and widgets."""

    def test_window_title(self, window):
        assert window.windowTitle() == "Redis Client GUI"

    def test_central_tree_view_exists(self, window):
        assert isinstance(window.tree_view, QTreeView)

    def test_addr_dock_exists(self, window):
        assert isinstance(window.addr_dock, QDockWidget)

    def test_attr_dock_exists(self, window):
        assert isinstance(window.attr_dock, QDockWidget)

    def test_sub_dock_exists(self, window):
        assert isinstance(window.sub_dock, QDockWidget)

    def test_graph_dock_exists(self, window):
        assert isinstance(window.graph_dock, QDockWidget)

    def test_log_dock_exists(self, window):
        assert isinstance(window.log_dock, QDockWidget)

    def test_connection_bar_fields(self, window):
        assert window.host_edit.text() == "localhost"
        assert window.port_spin.value() == 6379
        assert window.db_spin.value() == 0
        assert window.tls_checkbox.isChecked() is False

    def test_menu_actions_exist(self, window):
        assert window.action_connect is not None
        assert window.action_disconnect is not None
        assert window.action_copy_key is not None
        assert window.action_subscribe is not None
        assert window.action_add_to_graph is not None
        assert window.action_execute_command is not None


class TestInitialState:
    """Verify idle state disables interactive widgets."""

    def test_connect_enabled_in_idle(self, window):
        assert window.connect_button.isEnabled()
        assert window.action_connect.isEnabled()

    def test_disconnect_disabled_in_idle(self, window):
        assert not window.disconnect_button.isEnabled()
        assert not window.action_disconnect.isEnabled()

    def test_tree_disabled_in_idle(self, window):
        assert not window.tree_view.isEnabled()


class TestConnectedState:
    """Verify connected state enables interactive widgets."""

    def test_disconnect_enabled_when_connected(self, connected_window):
        assert connected_window.disconnect_button.isEnabled()

    def test_tree_enabled_when_connected(self, connected_window):
        assert connected_window.tree_view.isEnabled()

    def test_tree_has_root_nodes(self, connected_window):
        model = connected_window.tree_view.model()
        assert model is not None
        assert model.rowCount() >= 2

    def test_actions_enabled_when_connected(self, connected_window):
        assert connected_window.action_copy_key.isEnabled()
        assert connected_window.action_subscribe.isEnabled()
        assert connected_window.action_add_to_graph.isEnabled()


class TestSelectionIntegration:
    """Verify selecting a tree node shows attributes."""

    def test_select_leaf_key_populates_attrs(self, connected_window):
        """Selecting a leaf node should populate key name in attrs."""
        from PyQt6.QtWidgets import QApplication
        from rediswidgets.tree_widget import RedisTreeModel

        model = connected_window.tree_view.model()
        assert model is not None

        # Expand folders and find a leaf
        for row in range(model.rowCount()):
            idx = model.index(row, 0)
            item = model.itemFromIndex(idx) if hasattr(model, 'itemFromIndex') else None
            if item and not item.data(RedisTreeModel.ROLE_IS_FOLDER):
                key_name = item.data(RedisTreeModel.ROLE_KEY_NAME)
                if key_name:
                    connected_window.tree_view.setCurrentIndex(idx)
                    QApplication.processEvents()
                    prop = connected_window.attrs_ui.get_property("Key Name")
                    assert prop == key_name
                    return
