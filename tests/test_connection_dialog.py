"""Tests for ConnectionDialog — TDD RED phase."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QCoreApplication, QSettings
from PyQt6.QtWidgets import QDialog, QLineEdit, QSpinBox, QCheckBox

from redisclient.connection_dialog import ConnectionDialog


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def dialog(qtbot: pytest.QtBot) -> ConnectionDialog:
    """Create a ConnectionDialog for testing."""
    QCoreApplication.setOrganizationName("TestRedis")
    QCoreApplication.setApplicationName("ConnDlg")
    QSettings("TestRedis", "ConnDlg").clear()
    dlg = ConnectionDialog()
    qtbot.addWidget(dlg)
    yield dlg
    QSettings("TestRedis", "ConnDlg").clear()


# ──────────────────────────────────────────────────────────────
# UI Rendering
# ──────────────────────────────────────────────────────────────

class TestDialogRendersAllFields:
    def test_dialog_renders_all_fields(self, dialog: ConnectionDialog) -> None:
        assert dialog.host_edit is not None
        assert isinstance(dialog.host_edit, QLineEdit)

        assert dialog.port_spin is not None
        assert isinstance(dialog.port_spin, QSpinBox)

        assert dialog.password_edit is not None
        assert isinstance(dialog.password_edit, QLineEdit)

        assert dialog.db_spin is not None
        assert isinstance(dialog.db_spin, QSpinBox)

        assert dialog.tls_group is not None
        assert dialog.use_tls_checkbox is not None
        assert isinstance(dialog.use_tls_checkbox, QCheckBox)

        assert dialog.client_cert_edit is not None
        assert dialog.client_key_edit is not None
        assert dialog.ca_cert_edit is not None

        assert dialog.test_connection_button is not None
        assert dialog.connect_button is not None
        assert dialog.cancel_button is not None


# ──────────────────────────────────────────────────────────────
# Default Values
# ──────────────────────────────────────────────────────────────

class TestDefaultValues:
    def test_default_values(self, dialog: ConnectionDialog) -> None:
        assert dialog.host == "localhost"
        assert dialog.port == 6379
        assert dialog.password is None
        assert dialog.database == 0
        assert dialog.use_tls is False
        assert dialog.tls_cert is None
        assert dialog.tls_key is None
        assert dialog.tls_ca_cert is None

    def test_password_echo_mode(self, dialog: ConnectionDialog) -> None:
        assert dialog.password_edit.echoMode() == QLineEdit.EchoMode.Password

    def test_port_spin_range(self, dialog: ConnectionDialog) -> None:
        assert dialog.port_spin.minimum() == 1
        assert dialog.port_spin.maximum() == 65535

    def test_db_spin_range(self, dialog: ConnectionDialog) -> None:
        assert dialog.db_spin.minimum() == 0
        assert dialog.db_spin.maximum() == 15


# ──────────────────────────────────────────────────────────────
# TLS Checkbox Toggle
# ──────────────────────────────────────────────────────────────

class TestTlsCheckboxToggle:
    def test_tls_fields_disabled_when_unchecked(self, dialog: ConnectionDialog) -> None:
        assert dialog.use_tls_checkbox.isChecked() is False
        assert not dialog.client_cert_edit.isEnabled()
        assert not dialog.client_key_edit.isEnabled()
        assert not dialog.ca_cert_edit.isEnabled()

    def test_tls_fields_enabled_when_checked(self, dialog: ConnectionDialog) -> None:
        dialog.use_tls_checkbox.setChecked(True)
        assert dialog.client_cert_edit.isEnabled()
        assert dialog.client_key_edit.isEnabled()
        assert dialog.ca_cert_edit.isEnabled()

    def test_tls_fields_disabled_again_when_unchecked(self, dialog: ConnectionDialog) -> None:
        dialog.use_tls_checkbox.setChecked(True)
        dialog.use_tls_checkbox.setChecked(False)
        assert not dialog.client_cert_edit.isEnabled()
        assert not dialog.client_key_edit.isEnabled()
        assert not dialog.ca_cert_edit.isEnabled()


# ──────────────────────────────────────────────────────────────
# Properties
# ──────────────────────────────────────────────────────────────

class TestPropertiesReturnValues:
    def test_properties_return_values(self, dialog: ConnectionDialog) -> None:
        dialog.host_edit.setText("redis.example.com")
        dialog.port_spin.setValue(6380)
        dialog.password_edit.setText("s3cr3t")
        dialog.db_spin.setValue(3)

        assert dialog.host == "redis.example.com"
        assert dialog.port == 6380
        assert dialog.password == "s3cr3t"
        assert dialog.database == 3

    def test_password_property_returns_none_when_empty(self, dialog: ConnectionDialog) -> None:
        dialog.password_edit.setText("")
        assert dialog.password is None

    def test_tls_properties(self, dialog: ConnectionDialog) -> None:
        dialog.use_tls_checkbox.setChecked(True)
        dialog.client_cert_edit.setText("/path/cert.pem")
        dialog.client_key_edit.setText("/path/key.pem")
        dialog.ca_cert_edit.setText("/path/ca.pem")

        assert dialog.use_tls is True
        assert dialog.tls_cert == "/path/cert.pem"
        assert dialog.tls_key == "/path/key.pem"
        assert dialog.tls_ca_cert == "/path/ca.pem"

    def test_tls_cert_properties_return_none_when_empty(self, dialog: ConnectionDialog) -> None:
        dialog.client_cert_edit.setText("")
        dialog.client_key_edit.setText("")
        dialog.ca_cert_edit.setText("")
        assert dialog.tls_cert is None
        assert dialog.tls_key is None
        assert dialog.tls_ca_cert is None


# ──────────────────────────────────────────────────────────────
# Test Connection Button
# ──────────────────────────────────────────────────────────────

class TestTestConnectionButton:
    def test_test_connection_button_calls_connect(self, dialog: ConnectionDialog) -> None:
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.ping.return_value = True

        dialog.client = mock_client
        dialog._test_connection()

        mock_client.connect.assert_called_once()
        mock_client.ping.assert_called_once()

    def test_test_connection_shows_success(self, dialog: ConnectionDialog) -> None:
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.ping.return_value = True

        dialog.client = mock_client
        dialog._test_connection()

        assert "success" in dialog.status_label.text().lower() or \
               "ok" in dialog.status_label.text().lower() or \
               "connected" in dialog.status_label.text().lower()

    def test_test_connection_shows_failure(self, dialog: ConnectionDialog) -> None:
        mock_client = MagicMock()
        mock_client.connect.side_effect = ConnectionError("Connection refused")

        dialog.client = mock_client
        dialog._test_connection()

        assert "fail" in dialog.status_label.text().lower() or \
               "error" in dialog.status_label.text().lower()

    def test_test_connection_passes_dialog_values(self, dialog: ConnectionDialog) -> None:
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.ping.return_value = True

        dialog.host_edit.setText("prod.redis.local")
        dialog.port_spin.setValue(6380)
        dialog.password_edit.setText("hunter2")
        dialog.db_spin.setValue(2)
        dialog.use_tls_checkbox.setChecked(True)
        dialog.client_cert_edit.setText("/cert.pem")
        dialog.client_key_edit.setText("/key.pem")
        dialog.ca_cert_edit.setText("/ca.pem")

        dialog.client = mock_client
        dialog._test_connection()

        call_kwargs = mock_client.connect.call_args
        assert call_kwargs.kwargs["host"] == "prod.redis.local"
        assert call_kwargs.kwargs["port"] == 6380
        assert call_kwargs.kwargs["password"] == "hunter2"
        assert call_kwargs.kwargs["db"] == 2
        assert call_kwargs.kwargs["use_tls"] is True
        assert call_kwargs.kwargs["tls_cert"] == "/cert.pem"
        assert call_kwargs.kwargs["tls_key"] == "/key.pem"
        assert call_kwargs.kwargs["tls_ca_cert"] == "/ca.pem"


# ──────────────────────────────────────────────────────────────
# Connection History (QSettings persistence)
# ──────────────────────────────────────────────────────────────

class TestConnectionHistoryPersist:
    def test_save_settings_persists_values(self, dialog: ConnectionDialog) -> None:
        dialog.host_edit.setText("saved.host.com")
        dialog.port_spin.setValue(6390)
        dialog.password_edit.setText("savedpass")
        dialog.db_spin.setValue(5)
        dialog.use_tls_checkbox.setChecked(True)
        dialog.client_cert_edit.setText("/saved/cert.pem")

        dialog._save_settings()

        settings = QSettings("TestRedis", "ConnDlg")
        assert settings.value("host") == "saved.host.com"
        assert int(settings.value("port")) == 6390
        assert settings.value("password") == "savedpass"
        assert int(settings.value("db")) == 5
        assert settings.value("use_tls", type=bool) is True
        assert settings.value("tls_cert") == "/saved/cert.pem"

    def test_load_settings_restores_values(self, dialog: ConnectionDialog) -> None:
        settings = QSettings("TestRedis", "ConnDlg")
        settings.setValue("host", "restored.host")
        settings.setValue("port", 6400)
        settings.setValue("password", "restore123")
        settings.setValue("db", 7)
        settings.setValue("use_tls", True)
        settings.setValue("tls_cert", "/restored/cert.pem")

        dialog2 = ConnectionDialog()
        try:
            assert dialog2.host == "restored.host"
            assert dialog2.port == 6400
            assert dialog2.password == "restore123"
            assert dialog2.database == 7
            assert dialog2.use_tls is True
            assert dialog2.tls_cert == "/restored/cert.pem"
            assert dialog2.client_cert_edit.isEnabled()
        finally:
            dialog2.deleteLater()

    def test_load_settings_falls_back_to_defaults(self, dialog: ConnectionDialog) -> None:
        # Settings cleared by fixture, so should use defaults
        assert dialog.host == "localhost"
        assert dialog.port == 6379
        assert dialog.database == 0


# ──────────────────────────────────────────────────────────────
# Dialog accept/reject
# ──────────────────────────────────────────────────────────────

class TestDialogAcceptReject:
    def test_connect_button_accepts_dialog(self, dialog: ConnectionDialog) -> None:
        with patch.object(dialog, "accept") as mock_accept:
            dialog._on_connect_clicked()
            mock_accept.assert_called_once()

    def test_cancel_button_rejects_dialog(self, dialog: ConnectionDialog) -> None:
        with patch.object(dialog, "reject") as mock_reject:
            dialog._on_cancel_clicked()
            mock_reject.assert_called_once()

    def test_get_connection_params(self, dialog: ConnectionDialog) -> None:
        dialog.host_edit.setText("params.host")
        dialog.port_spin.setValue(6381)
        dialog.password_edit.setText("pw")
        dialog.db_spin.setValue(4)
        dialog.use_tls_checkbox.setChecked(True)
        dialog.client_cert_edit.setText("/c.pem")
        dialog.client_key_edit.setText("/k.pem")
        dialog.ca_cert_edit.setText("/a.pem")

        params = dialog.get_connection_params()
        assert params["host"] == "params.host"
        assert params["port"] == 6381
        assert params["password"] == "pw"
        assert params["db"] == 4
        assert params["use_tls"] is True
        assert params["tls_cert"] == "/c.pem"
        assert params["tls_key"] == "/k.pem"
        assert params["tls_ca_cert"] == "/a.pem"
