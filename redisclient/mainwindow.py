"""MainWindow — main application window integrating all widgets.

Forked layout from opcua-client-gui's mainwindow, adapted for Redis:
  - Top dock: connection bar (Host, Port, DB, TLS, Connect/Disconnect)
  - Central: TreeView for keyspace browsing
  - Right-top dock: key attributes/metadata
  - Right-bottom tabbed docks: Pub/Sub + Graph
  - Bottom dock: log output
"""
from __future__ import annotations

import logging
import sys
from typing import Any

from PyQt6.QtCore import (
    QCoreApplication,
    QPoint,
    QSettings,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QAction, QCloseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDockWidget,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableView,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from redisclient.command_dialog import CommandDialog
from redisclient.connection_dialog import ConnectionDialog
from redisclient.graphwidget import GraphUI
from redisclient.redis_client import RedisClient
from rediswidgets.attrs_widget import AttrsWidget
from rediswidgets.logger import QtHandler
from rediswidgets.tag_monitor import TagMonitorUI
from rediswidgets.tree_widget import TreeWidget
from rediswidgets.utils import trycatchslot

logger = logging.getLogger(__name__)


class Window(QMainWindow):
    """Main application window for redis-client-gui."""

    def __init__(self) -> None:
        QMainWindow.__init__(self)
        self.setWindowTitle("Redis Client GUI")
        self.resize(1000, 700)

        QCoreApplication.setOrganizationName("RedisClientGUI")
        QCoreApplication.setApplicationName("redis-client-gui")
        self.settings = QSettings()

        self.uaclient = RedisClient()

        self._build_central()
        self._build_addr_dock()
        self._build_attr_dock()
        self._build_sub_dock()
        self._build_graph_dock()
        self._build_log_dock()
        self._build_menus()
        self._wire_signals()

        self._restore_state()
        self._apply_ui_state("idle")

    # ──────────────────────────────────────────────────────────
    # UI Construction
    # ──────────────────────────────────────────────────────────

    def _build_central(self) -> None:
        """Central widget: QTreeView inside a splitter."""
        self.tree_view = QTreeView()
        self.tree_view.setDragEnabled(True)
        self.tree_view.setDragDropMode(QTreeView.DragDropMode.DragOnly)
        self.tree_view.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.tree_view.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.tree_view)
        splitter.setStretchFactor(0, 1)
        self.setCentralWidget(splitter)

        self.tree_ui = TreeWidget(self.tree_view)
        self.tree_ui.error.connect(self.show_error)

    def _build_addr_dock(self) -> None:
        """Top dock: connection bar with host/port/db/tls + buttons."""
        dock = QDockWidget(self)
        dock.setWindowTitle("Connection")
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        dock.setAllowedAreas(Qt.DockWidgetArea.TopDockWidgetArea)

        container = QWidget()
        from PyQt6.QtWidgets import QHBoxLayout

        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)

        layout.addWidget(QLabel("Host:"))
        self.host_edit = QLineEdit("localhost")
        layout.addWidget(self.host_edit)

        layout.addWidget(QLabel("Port:"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(6379)
        layout.addWidget(self.port_spin)

        layout.addWidget(QLabel("DB:"))
        self.db_spin = QSpinBox()
        self.db_spin.setRange(0, 15)
        layout.addWidget(self.db_spin)

        self.tls_checkbox = QCheckBox("TLS")
        layout.addWidget(self.tls_checkbox)

        layout.addStretch()

        self.connect_button = QPushButton("Connect")
        self.disconnect_button = QPushButton("Disconnect")
        layout.addWidget(self.connect_button)
        layout.addWidget(self.disconnect_button)

        dock.setWidget(container)
        self.addr_dock = dock
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, dock)

    def _build_attr_dock(self) -> None:
        """Right-top dock: key attributes."""
        dock = QDockWidget("&Attributes", self)
        self.attr_view = QTreeView()
        self.attr_view.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.attr_view.setWordWrap(True)
        header = self.attr_view.header()
        if header is not None:
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            header.setStretchLastSection(True)
        dock.setWidget(self.attr_view)
        self.attr_dock = dock
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

        self.attrs_ui = AttrsWidget(self.attr_view)
        self.attrs_ui.error.connect(self.show_error)

    def _build_sub_dock(self) -> None:
        """Right-bottom dock: Tag Monitor (polling-based)."""
        dock = QDockWidget("&Tag Monitor", self)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)

        self.tag_monitor = TagMonitorUI()
        layout.addWidget(self.tag_monitor.build_controls())

        self.sub_view = QTableView()
        self.sub_view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.sub_view.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.sub_view)
        self.sub_view.setModel(self.tag_monitor.model)

        dock.setWidget(container)
        self.sub_dock = dock
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _build_graph_dock(self) -> None:
        """Right-bottom dock: live graph."""
        dock = QDockWidget("&Graph", self)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        dock.setWidget(container)
        self.graph_dock = dock
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

        self.graph_ui = GraphUI()
        self.graph_ui.setup_ui(layout)
        self.graph_ui.error.connect(self.show_error)

        self.tabifyDockWidget(self.sub_dock, self.graph_dock)

    def _build_log_dock(self) -> None:
        """Bottom dock: log output."""
        dock = QDockWidget("Log", self)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        dock.setWidget(self.log_text)
        self.log_dock = dock
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

    def _build_menus(self) -> None:
        """Menu bar actions."""
        menubar = self.menuBar()

        menu_actions = menubar.addMenu("&Actions")
        self.action_connect = QAction("&Connect", self)
        self.action_disconnect = QAction("&Disconnect", self)
        self.action_copy_key = QAction("Copy &Key", self)
        self.action_copy_prefix = QAction("Copy &Prefix", self)
        self.action_subscribe = QAction("&Monitor Tag", self)
        self.action_unsubscribe = QAction("&Unmonitor Tag", self)
        self.action_add_to_graph = QAction("Add to &Graph", self)
        self.action_add_to_graph.setShortcut("Ctrl+G")
        self.action_remove_from_graph = QAction("Remove from Graph", self)
        self.action_remove_from_graph.setShortcut("Ctrl+Shift+G")
        self.action_execute_command = QAction("Execute &Command", self)

        menu_actions.addAction(self.action_connect)
        menu_actions.addAction(self.action_disconnect)
        menu_actions.addSeparator()
        menu_actions.addAction(self.action_copy_key)
        menu_actions.addAction(self.action_copy_prefix)
        menu_actions.addSeparator()
        menu_actions.addAction(self.action_subscribe)
        menu_actions.addAction(self.action_unsubscribe)
        menu_actions.addSeparator()
        menu_actions.addAction(self.action_add_to_graph)
        menu_actions.addAction(self.action_remove_from_graph)
        menu_actions.addSeparator()
        menu_actions.addAction(self.action_execute_command)

        menu_settings = menubar.addMenu("&Settings")
        self.action_dark_mode = QAction("&Dark Mode", self)
        self.action_dark_mode.setCheckable(True)
        menu_settings.addAction(self.action_dark_mode)

        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    # ──────────────────────────────────────────────────────────
    # Signal wiring
    # ──────────────────────────────────────────────────────────

    def _wire_signals(self) -> None:
        self.connect_button.clicked.connect(self.show_connection_dialog)
        self.disconnect_button.clicked.connect(self.disconnect)
        self.action_connect.triggered.connect(self.show_connection_dialog)
        self.action_disconnect.triggered.connect(self.disconnect)
        self.action_copy_key.triggered.connect(self._copy_key)
        self.action_copy_prefix.triggered.connect(self._copy_prefix)
        self.action_subscribe.triggered.connect(self._subscribe_current)
        self.action_unsubscribe.triggered.connect(self._unsubscribe_current)
        self.action_add_to_graph.triggered.connect(self._add_to_graph)
        self.action_remove_from_graph.triggered.connect(self._remove_from_graph)
        self.action_execute_command.triggered.connect(self._execute_command)
        self.action_dark_mode.toggled.connect(self._toggle_dark_mode)

        sel_model = self.tree_view.selectionModel()
        if sel_model is not None:
            sel_model.currentChanged.connect(self._on_tree_selection_changed)

        self.tree_view.customContextMenuRequested.connect(self._show_tree_context_menu)

        self.uaclient.connection_state_changed.connect(
            self._on_connection_state_changed,
            type=Qt.ConnectionType.QueuedConnection,
        )

    # ──────────────────────────────────────────────────────────
    # Connect / Disconnect
    # ──────────────────────────────────────────────────────────

    @trycatchslot
    def show_connection_dialog(self) -> None:
        dia = ConnectionDialog(self)
        if not dia.exec():
            return

        params = dia.get_connection_params()
        self.host_edit.setText(params.get("host", "localhost"))
        self.port_spin.setValue(params.get("port", 6379))
        self.db_spin.setValue(params.get("db", 0))
        self.tls_checkbox.setChecked(params.get("use_tls", False))
        self._connect_with_params(params)

    def _connect_with_params(self, params: dict[str, Any]) -> None:
        try:
            self.uaclient.connect(**params)
        except Exception as ex:
            self.show_error(ex)
            return

        self.tree_ui.set_root(self.uaclient)
        self.tag_monitor.set_client(self.uaclient)
        self.tag_monitor.start()
        self.tree_view.setFocus()
        self._apply_ui_state("connected")

    @trycatchslot
    def disconnect(self) -> None:
        try:
            self.tag_monitor.stop()
            self.tag_monitor.clear()
        except Exception:
            pass
        try:
            self.graph_ui.clear()
        except Exception:
            pass
        try:
            self.uaclient.disconnect()
        except Exception as ex:
            self.show_error(ex)
        finally:
            self.tree_ui.clear()
            self.attrs_ui.clear()
            self._apply_ui_state("idle")

    # ──────────────────────────────────────────────────────────
    # Tree selection
    # ──────────────────────────────────────────────────────────

    @trycatchslot
    def _on_tree_selection_changed(self, current: Any, previous: Any) -> None:
        hash_field = self.tree_ui.get_current_hash_field()
        if hash_field:
            hash_key, field_name = hash_field
            field_type = self.tree_ui.get_current_field_type()
            self.attrs_ui.show_hash_field(self.uaclient, hash_key, field_name, field_type)
            return
        key = self.tree_ui.get_current_key()
        if key:
            self.attrs_ui.show_key(self.uaclient, key)

    def _show_tree_context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction(self.action_copy_key)
        menu.addAction(self.action_copy_prefix)
        menu.addSeparator()
        menu.addAction(self.action_subscribe)
        menu.addAction(self.action_add_to_graph)
        menu.addSeparator()
        menu.addAction(self.action_execute_command)
        viewport = self.tree_view.viewport()
        if viewport is not None:
            menu.exec(viewport.mapToGlobal(pos))

    # ──────────────────────────────────────────────────────────
    # Action handlers
    # ──────────────────────────────────────────────────────────

    def _copy_key(self) -> None:
        key = self.tree_ui.get_current_key()
        if key:
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(key)

    def _copy_prefix(self) -> None:
        prefix = self.tree_ui.get_current_prefix()
        if prefix:
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(prefix)

    @trycatchslot
    def _subscribe_current(self) -> None:
        hash_field = self.tree_ui.get_current_hash_field()
        if hash_field:
            _, field_name = hash_field
            self.tag_monitor.add_tag(field_name)
            self.sub_dock.raise_()
            return
        key = self.tree_ui.get_current_key()
        if not key:
            QMessageBox.information(self, "Monitor Tag", "Select a tag first.")
            return
        self.tag_monitor.add_tag(key)
        self.sub_dock.raise_()

    @trycatchslot
    def _unsubscribe_current(self) -> None:
        key = self.tree_ui.get_current_key()
        if key and key in self.tag_monitor.get_monitored_tags():
            self.tag_monitor.remove_tag(key)

    @trycatchslot
    def _add_to_graph(self) -> None:
        key = self.tree_ui.get_current_key()
        if not key:
            QMessageBox.information(self, "Add to Graph", "Select a key first.")
            return
        self.graph_ui.add_key(self.uaclient, key)
        self.graph_dock.raise_()

    @trycatchslot
    def _remove_from_graph(self) -> None:
        key = self.tree_ui.get_current_key()
        if key:
            self.graph_ui.remove_key(key)

    @trycatchslot
    def _execute_command(self) -> None:
        dia = CommandDialog(self.uaclient, self)
        dia.show()

    # ──────────────────────────────────────────────────────────
    # Connection state / UI state
    # ──────────────────────────────────────────────────────────

    def _on_connection_state_changed(self, state: str) -> None:
        if state == "connected":
            self._apply_ui_state("connected")
        else:
            self._apply_ui_state("reconnecting")

    def _apply_ui_state(self, state: str) -> None:
        """Enable/disable widgets based on connection state."""
        connected = state == "connected"
        has_session = state in ("connected", "reconnecting")

        self.connect_button.setEnabled(not has_session)
        self.action_connect.setEnabled(not has_session)
        self.disconnect_button.setEnabled(has_session)
        self.action_disconnect.setEnabled(has_session)

        for view in (
            self.tree_view,
            self.attr_view,
            self.sub_view,
            self.graph_dock,
        ):
            view.setEnabled(connected)

        for action in (
            self.action_copy_key,
            self.action_copy_prefix,
            self.action_subscribe,
            self.action_unsubscribe,
            self.action_add_to_graph,
            self.action_remove_from_graph,
            self.action_execute_command,
        ):
            action.setEnabled(connected)

        self.statusBar().showMessage(
            "Connected" if connected else ("Reconnecting…" if state == "reconnecting" else "Disconnected")
        )

    # ──────────────────────────────────────────────────────────
    # Dark mode
    # ──────────────────────────────────────────────────────────

    def _toggle_dark_mode(self, checked: bool) -> None:
        self.settings.setValue("dark_mode", checked)
        QMessageBox.information(self, "Dark Mode", "Restart for changes to take effect.")

    # ──────────────────────────────────────────────────────────
    # Error display
    # ──────────────────────────────────────────────────────────

    def show_error(self, msg: Any) -> None:
        logger.warning("Error: %s", msg)
        self.statusBar().showMessage(f"Error: {msg}", 3000)

    # ──────────────────────────────────────────────────────────
    # Persistence
    # ──────────────────────────────────────────────────────────

    def _restore_state(self) -> None:
        w = int(self.settings.value("main_window_width", 1000))
        h = int(self.settings.value("main_window_height", 700))
        self.resize(w, h)

        state = self.settings.value("main_window_state")
        if state:
            self.restoreState(state)

        if self.settings.value("dark_mode", False, type=bool):
            self.action_dark_mode.setChecked(True)

    def _save_state(self) -> None:
        self.settings.setValue("main_window_width", self.size().width())
        self.settings.setValue("main_window_height", self.size().height())
        self.settings.setValue("main_window_state", self.saveState())

    def closeEvent(self, event: QCloseEvent | None) -> None:
        assert event is not None
        self._save_state()
        self.disconnect()
        self.uaclient.shutdown()
        event.accept()


def main() -> None:
    app = QApplication(sys.argv)
    window = Window()
    handler = QtHandler(window.log_text)
    logging.getLogger().addHandler(handler)
    logging.getLogger("redisclient").setLevel(logging.INFO)
    logging.getLogger("rediswidgets").setLevel(logging.INFO)

    if QSettings().value("dark_mode", False, type=bool):
        app.setStyleSheet(
            "QMainWindow { background-color: #2b2b2b; color: #dedede; }"
            " QDockWidget { background-color: #2b2b2b; color: #dedede; }"
            " QTreeView, QTableView, QPlainTextEdit { background-color: #1e1e1e; color: #dedede; }"
        )

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
