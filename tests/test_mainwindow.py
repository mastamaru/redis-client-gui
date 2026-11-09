"""Tests for MainWindow integration — verifies all widgets are wired correctly."""
from __future__ import annotations

import fakeredis
import pytest
from unittest.mock import patch
from PyQt6.QtCore import QCoreApplication, QSettings, Qt, QModelIndex
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


def test_search_finds_unloaded_tags_and_restores_tree(connected_window, qapp):
    w = connected_window
    w.uaclient._redis.hset('ots-pim:tags', mapping={'Alpha': '1', 'deep.Tag': '2'})
    w.uaclient._redis.hset('ots-pim:tagtypes', mapping={'deep.Tag': 'bool'})
    model = w.tree_view.model()
    w.search_edit.setText('DEEP.')
    qapp.processEvents()
    assert w.search_results.count() == 1
    with patch.object(w.attrs_ui, 'show_hash_field') as show:
        w.search_results.setCurrentRow(0)
        show.assert_called_with(w.uaclient, 'ots-pim:tags', 'deep.Tag', 'bool')
    w.search_edit.clear()
    assert w.tree_view.model() is model
    assert not w.tree_view.isHidden()


def test_search_empty_and_refresh(connected_window, qapp):
    w = connected_window
    w.search_edit.setText('missing')
    assert w.search_empty_label.text() == 'No matching tags'
    w.uaclient._redis.hset('ots-pim:tags', 'missing', '1')
    w._invalidate_tag_cache()
    w._refresh_search()
    assert w.search_results.count() == 1
    w.disconnect()
    assert w.search_results.count() == 0


def test_search_keyboard_selection_and_default_type(connected_window, qtbot):
    from PyQt6.QtCore import Qt
    w = connected_window
    w.uaclient._redis.hset('ots-pim:tags', mapping={'first': '1', 'second': '2'})
    w.search_edit.setText('s')
    with patch.object(w.attrs_ui, 'show_hash_field') as show:
        w.search_results.setFocus()
        qtbot.keyClick(w.search_results, Qt.Key.Key_Down)
        show.assert_called_with(w.uaclient, 'ots-pim:tags', 'second', 'float')


def test_search_failure_clears_old_results_and_actions(connected_window):
    w = connected_window
    w.uaclient._redis.hset('ots-pim:tags', 'tag', '1')
    w.search_edit.setText('tag')
    w._invalidate_tag_cache()
    with patch.object(w.uaclient, 'hkeys', side_effect=RuntimeError('failed')), \
         patch.object(w, 'show_error') as error, \
         patch.object(w.tree_ui, 'get_current_key') as current:
        w._refresh_search()
        w._copy_key()
        assert w.search_results.count() == 0
        error.assert_called_once()
        current.assert_not_called()


def test_search_cache_and_reconnect(connected_window, qapp):
    w = connected_window
    w.uaclient._redis.hset('ots-pim:tags', 'alpha', '1')
    with patch.object(w.uaclient, 'hkeys', wraps=w.uaclient.hkeys) as hkeys:
        w.search_edit.setText('a')
        w.search_edit.setText('al')
        w.search_edit.clear()
        w.search_edit.setText('alpha')
        assert hkeys.call_count == 2
        w.disconnect()
        replacement = fakeredis.FakeRedis(decode_responses=True)
        replacement.hset('ots-pim:tags', 'alphabet', '2')
        w.uaclient.attach(replacement)
        qapp.processEvents()
        assert hkeys.call_count == 3
        assert w.search_results.item(0).text() == 'alphabet'


def test_search_whitespace_and_action_state(connected_window):
    w = connected_window
    actions = [w.action_copy_key, w.action_copy_prefix, w.action_subscribe,
               w.action_unsubscribe, w.action_add_to_graph, w.action_remove_from_graph]
    w.search_edit.setText('abc')
    assert all(not action.isEnabled() for action in actions)
    assert w.action_execute_command.isEnabled()
    w.search_edit.setText('   ')
    assert not w.tree_view.isHidden()
    assert all(action.isEnabled() for action in actions)


def test_monitor_click_keyboard_cross_selection_and_edit(connected_window, qtbot):
    w = connected_window
    redis = w.uaclient._redis
    redis.hset('ots-pim:tags', mapping={'alpha': '1', 'beta': '2'})
    redis.hset('ots-pim:tagtypes', 'beta', 'bool')
    w.tag_monitor.set_client(w.uaclient)
    w.tag_monitor.add_tag('alpha')
    w.tag_monitor.add_tag('beta')
    w.sub_dock.raise_()
    qtbot.waitExposed(w)
    index = w.tag_monitor.model.index(0, 1)
    qtbot.mouseClick(w.sub_view.viewport(), Qt.MouseButton.LeftButton,
                     pos=w.sub_view.visualRect(index).center())
    assert w.attrs_ui.get_property('Field') == 'alpha'
    redis.hset('ots-pim:tags', 'alpha', '3')
    qtbot.mouseClick(w.sub_view.viewport(), Qt.MouseButton.LeftButton,
                     pos=w.sub_view.visualRect(index).center())
    assert w.attrs_ui.get_property('Value') == '3.000'
    w.sub_view.setFocus()
    qtbot.keyClick(w.sub_view, Qt.Key.Key_Down)
    assert w.attrs_ui.get_property('Field') == 'beta'
    assert w.attrs_ui.get_property('Data Type') == 'bool'
    w.search_edit.setText('alpha')
    w.search_results.setCurrentRow(0)
    assert w.attrs_ui.get_property('Field') == 'alpha'
    qtbot.mouseClick(w.sub_view.viewport(), Qt.MouseButton.LeftButton,
                     pos=w.sub_view.visualRect(w.tag_monitor.model.index(1, 2)).center())
    assert w.attrs_ui.get_property('Field') == 'beta'
    w.search_results.setCurrentRow(-1)
    assert w.attrs_ui.get_property('Field') == 'beta'
    w.attrs_ui.model.item(2, 1).setText('0')
    assert redis.hget('ots-pim:tags', 'beta') == '0'


def test_search_deselection_clears_its_attributes(connected_window):
    w = connected_window
    w.uaclient._redis.hset('ots-pim:tags', 'alpha', '1')
    w.search_edit.setText('alpha')
    w.search_results.setCurrentRow(0)
    assert w.attrs_ui.get_property('Field') == 'alpha'
    w.search_results.setCurrentRow(-1)
    assert w.attrs_ui.get_property('Field') is None


def test_entering_search_clears_tree_attributes(connected_window):
    w = connected_window
    w.uaclient._redis.hset('ots-pim:tags', 'alpha', '1')
    with patch.object(w.tree_ui, 'get_current_hash_field', return_value=('ots-pim:tags', 'alpha')):
        w._on_tree_selection_changed(None, None)
        assert w.attrs_ui.get_property('Field') == 'alpha'
        w.search_edit.setText('alpha')
        assert w.attrs_ui.get_property('Field') is None
        assert w.attrs_ui.model.rowCount() == 0


def test_clearing_search_preserves_monitor_selection(connected_window):
    w = connected_window
    w.uaclient._redis.hset('ots-pim:tags', mapping={'alpha': '1', 'beta': '2'})
    with patch.object(w.tree_ui, 'get_current_hash_field', return_value=('ots-pim:tags', 'alpha')):
        w._on_tree_selection_changed(None, None)
        w.search_edit.setText('alpha')
        w._show_selected_tag('beta', 'float')
        w.search_edit.clear()
        assert w.attrs_ui.get_property('Field') == 'beta'


def test_reentering_search_refreshes_new_tags_once(connected_window):
    w = connected_window
    redis = w.uaclient._redis
    redis.hset('ots-pim:tags', 'alpha', '1')
    with patch.object(w.uaclient, 'hkeys', wraps=w.uaclient.hkeys) as hkeys:
        w.search_edit.setText('a')
        w.search_edit.setText('al')
        assert hkeys.call_count == 1
        redis.hset('ots-pim:tags', 'alpine', '2')
        w.search_edit.clear()
        w.search_edit.setText('al')
        w.search_edit.setText('alp')
        assert hkeys.call_count == 2
        assert [w.search_results.item(i).text() for i in range(w.search_results.count())] == ['alpha', 'alpine']


def test_search_results_drag_to_monitor(connected_window):
    from PyQt6.QtCore import QModelIndex, Qt
    from PyQt6.QtWidgets import QAbstractItemView

    w = connected_window
    w.uaclient._redis.hset('ots-pim:tags', 'pump:speed', '1450')
    w.search_edit.setText('pump')
    view = w.search_results
    assert view.dragEnabled()
    assert view.dragDropMode() == QAbstractItemView.DragDropMode.DragOnly
    view.setCurrentRow(0)
    payload = view.model().mimeData(view.selectedIndexes())
    assert payload.hasText()
    assert payload.text() == 'pump:speed'
    model = w.tag_monitor.model
    for _ in range(2):
        assert model.dropMimeData(payload, Qt.DropAction.CopyAction, -1, -1, QModelIndex())
    assert model.rowCount() == 1
    assert model.item(0, 0).text() == 'pump:speed'
    assert view.count() == 1


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
