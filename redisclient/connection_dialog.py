"""ConnectionDialog — modal dialog for configuring a Redis connection."""
from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from redisclient.redis_client import RedisClient

logger = logging.getLogger(__name__)

_DEFAULT_HOST = "localhost"
_DEFAULT_PORT = 6379
_DEFAULT_DB = 0
_PORT_MIN = 1
_PORT_MAX = 65535
_DB_MIN = 0
_DB_MAX = 15


class ConnectionDialog(QDialog):
    """Dialog for entering Redis connection parameters.

    Exposes connection parameters as read-only properties and provides
    a "Test Connection" button that validates the connection via
    ``RedisClient.connect()`` + ``ping()``.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Connect to Redis")
        self.setMinimumWidth(500)

        self.client: RedisClient = RedisClient()
        self.status_label = QLabel()

        self._build_ui()
        self._wire_signals()
        self._load_settings()
        self._update_tls_fields_enabled()

    # ──────────────────────────────────────────────────────────
    # UI Construction
    # ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # --- Connection form ---
        form = QFormLayout()

        self.host_edit = QLineEdit(_DEFAULT_HOST)
        form.addRow("Host:", self.host_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(_PORT_MIN, _PORT_MAX)
        self.port_spin.setValue(_DEFAULT_PORT)
        form.addRow("Port:", self.port_spin)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("(optional)")
        form.addRow("Password:", self.password_edit)

        self.db_spin = QSpinBox()
        self.db_spin.setRange(_DB_MIN, _DB_MAX)
        self.db_spin.setValue(_DEFAULT_DB)
        form.addRow("Database:", self.db_spin)

        layout.addLayout(form)

        # --- TLS group ---
        self.tls_group = QGroupBox("TLS / SSL")
        tls_form = QFormLayout(self.tls_group)

        self.use_tls_checkbox = QCheckBox("Use TLS")
        tls_form.addRow(self.use_tls_checkbox)

        self.client_cert_edit = QLineEdit()
        self.client_cert_edit.setPlaceholderText("Client certificate (.pem)")
        self.client_cert_browse = QPushButton("Browse…")
        cert_row = QHBoxLayout()
        cert_row.addWidget(self.client_cert_edit)
        cert_row.addWidget(self.client_cert_browse)
        cert_container = QWidget()
        cert_container.setLayout(cert_row)
        tls_form.addRow("Client cert:", cert_container)

        self.client_key_edit = QLineEdit()
        self.client_key_edit.setPlaceholderText("Client key (.pem)")
        self.client_key_browse = QPushButton("Browse…")
        key_row = QHBoxLayout()
        key_row.addWidget(self.client_key_edit)
        key_row.addWidget(self.client_key_browse)
        key_container = QWidget()
        key_container.setLayout(key_row)
        tls_form.addRow("Client key:", key_container)

        self.ca_cert_edit = QLineEdit()
        self.ca_cert_edit.setPlaceholderText("CA certificate (.pem)")
        self.ca_cert_browse = QPushButton("Browse…")
        ca_row = QHBoxLayout()
        ca_row.addWidget(self.ca_cert_edit)
        ca_row.addWidget(self.ca_cert_browse)
        ca_container = QWidget()
        ca_container.setLayout(ca_row)
        tls_form.addRow("CA cert:", ca_container)

        layout.addWidget(self.tls_group)

        # --- Status label ---
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # --- Buttons ---
        button_row = QHBoxLayout()

        self.test_connection_button = QPushButton("Test Connection")
        self.connect_button = QPushButton("Connect")
        self.connect_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel")

        button_row.addWidget(self.test_connection_button)
        button_row.addStretch()
        button_row.addWidget(self.connect_button)
        button_row.addWidget(self.cancel_button)

        layout.addLayout(button_row)

    def _wire_signals(self) -> None:
        self.use_tls_checkbox.toggled.connect(self._update_tls_fields_enabled)
        self.client_cert_browse.clicked.connect(self._browse_client_cert)
        self.client_key_browse.clicked.connect(self._browse_client_key)
        self.ca_cert_browse.clicked.connect(self._browse_ca_cert)
        self.test_connection_button.clicked.connect(self._test_connection)
        self.connect_button.clicked.connect(self._on_connect_clicked)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)

    # ──────────────────────────────────────────────────────────
    # TLS toggle
    # ──────────────────────────────────────────────────────────

    def _update_tls_fields_enabled(self) -> None:
        enabled = self.use_tls_checkbox.isChecked()
        self.client_cert_edit.setEnabled(enabled)
        self.client_cert_browse.setEnabled(enabled)
        self.client_key_edit.setEnabled(enabled)
        self.client_key_browse.setEnabled(enabled)
        self.ca_cert_edit.setEnabled(enabled)
        self.ca_cert_browse.setEnabled(enabled)

    # ──────────────────────────────────────────────────────────
    # Browse handlers
    # ──────────────────────────────────────────────────────────

    def _browse_client_cert(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Client Certificate", "", "Certificates (*.pem *.crt)"
        )
        if path:
            self.client_cert_edit.setText(path)

    def _browse_client_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Client Key", "", "Keys (*.pem *.key)"
        )
        if path:
            self.client_key_edit.setText(path)

    def _browse_ca_cert(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select CA Certificate", "", "Certificates (*.pem *.crt)"
        )
        if path:
            self.ca_cert_edit.setText(path)

    # ──────────────────────────────────────────────────────────
    # Test connection
    # ──────────────────────────────────────────────────────────

    def _test_connection(self) -> None:
        params = self.get_connection_params()
        try:
            self.client.connect(**params)
            if self.client.ping():
                self.status_label.setText("✓ Connection successful")
                self.status_label.setStyleSheet("color: green; font-weight: bold;")
            else:
                self.status_label.setText("✗ Ping failed")
                self.status_label.setStyleSheet("color: red; font-weight: bold;")
        except Exception as ex:
            logger.exception("Connection test failed")
            self.status_label.setText(f"✗ Connection failed: {ex}")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            self.client.disconnect()

    # ──────────────────────────────────────────────────────────
    # Connect / Cancel
    # ──────────────────────────────────────────────────────────

    def _on_connect_clicked(self) -> None:
        self._save_settings()
        self.accept()

    def _on_cancel_clicked(self) -> None:
        self.reject()

    # ──────────────────────────────────────────────────────────
    # Settings persistence
    # ──────────────────────────────────────────────────────────

    def _settings(self) -> QSettings:
        return QSettings()

    def _save_settings(self) -> None:
        s = self._settings()
        s.setValue("host", self.host)
        s.setValue("port", self.port)
        s.setValue("password", self.password or "")
        s.setValue("db", self.database)
        s.setValue("use_tls", self.use_tls)
        s.setValue("tls_cert", self.tls_cert or "")
        s.setValue("tls_key", self.tls_key or "")
        s.setValue("tls_ca_cert", self.tls_ca_cert or "")

    def _load_settings(self) -> None:
        s = self._settings()
        self.host_edit.setText(s.value("host", _DEFAULT_HOST, type=str))
        self.port_spin.setValue(int(s.value("port", _DEFAULT_PORT)))
        self.password_edit.setText(s.value("password", "", type=str))
        self.db_spin.setValue(int(s.value("db", _DEFAULT_DB)))
        use_tls = s.value("use_tls", False, type=bool)
        self.use_tls_checkbox.setChecked(use_tls)
        self.client_cert_edit.setText(s.value("tls_cert", "", type=str))
        self.client_key_edit.setText(s.value("tls_key", "", type=str))
        self.ca_cert_edit.setText(s.value("tls_ca_cert", "", type=str))
        self._update_tls_fields_enabled()

    # ──────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────

    @property
    def host(self) -> str:
        return self.host_edit.text()

    @property
    def port(self) -> int:
        return self.port_spin.value()

    @property
    def password(self) -> str | None:
        text = self.password_edit.text()
        return text if text else None

    @property
    def database(self) -> int:
        return self.db_spin.value()

    @property
    def use_tls(self) -> bool:
        return self.use_tls_checkbox.isChecked()

    @property
    def tls_cert(self) -> str | None:
        text = self.client_cert_edit.text()
        return text if text else None

    @property
    def tls_key(self) -> str | None:
        text = self.client_key_edit.text()
        return text if text else None

    @property
    def tls_ca_cert(self) -> str | None:
        text = self.ca_cert_edit.text()
        return text if text else None

    def get_connection_params(self) -> dict[str, Any]:
        """Return all connection parameters as a dict suitable for RedisClient.connect()."""
        return {
            "host": self.host,
            "port": self.port,
            "password": self.password,
            "db": self.database,
            "use_tls": self.use_tls,
            "tls_cert": self.tls_cert,
            "tls_key": self.tls_key,
            "tls_ca_cert": self.tls_ca_cert,
        }
