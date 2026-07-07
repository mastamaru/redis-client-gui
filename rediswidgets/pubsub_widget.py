"""PubSubUI — Redis Pub/Sub subscription widget controller.

Manages Pub/Sub channel subscriptions and displays received messages
in a QStandardItemModel with columns: Channel, Last Message, Timestamp.
"""
from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel

from redisclient.redis_client import RedisClient

logger = logging.getLogger(__name__)


class PubSubUI(QObject):
    """Widget controller for Redis Pub/Sub subscriptions.

    Signals:
        error: emitted when an operation raises an exception.
        message_received: emitted with (channel, message, timestamp) on each message.
    """

    error = pyqtSignal(Exception)
    message_received = pyqtSignal(str, str, str)

    HEADERS = ["Channel", "Last Message", "Timestamp"]

    def __init__(self) -> None:
        QObject.__init__(self)
        self._model: QStandardItemModel = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(self.HEADERS)
        self._channels: list[str] = []
        self._client: RedisClient | None = None

    @property
    def model(self) -> QStandardItemModel:
        """The underlying item model for display."""
        return self._model

    def subscribe(self, client: RedisClient, channel: str) -> None:
        """Subscribe to a Pub/Sub channel.

        Adds a row to the model and registers a handler with the client.
        """
        try:
            self._client = client
            client.subscribe(channel, self._make_handler(channel))

            channel_item = QStandardItem(channel)
            channel_item.setEditable(False)
            msg_item = QStandardItem("")
            msg_item.setEditable(False)
            ts_item = QStandardItem("")
            ts_item.setEditable(False)

            self._model.appendRow([channel_item, msg_item, ts_item])
            self._channels.append(channel)

            logger.info("Subscribed to channel: %s", channel)
        except Exception as ex:
            logger.exception("Failed to subscribe to channel: %s", channel)
            self.error.emit(ex)

    def unsubscribe(self, client: RedisClient, channel: str) -> None:
        """Unsubscribe from a Pub/Sub channel and remove its model row."""
        try:
            client.unsubscribe(channel)

            if channel in self._channels:
                self._channels.remove(channel)

            for row in range(self._model.rowCount()):
                item = self._model.item(row, 0)
                if item is not None and item.text() == channel:
                    self._model.removeRow(row)
                    break

            logger.info("Unsubscribed from channel: %s", channel)
        except Exception as ex:
            logger.exception("Failed to unsubscribe from channel: %s", channel)
            self.error.emit(ex)

    def publish(self, client: RedisClient, channel: str, message: str) -> int:
        """Publish a message to a channel. Returns subscriber count."""
        try:
            return client.publish(channel, message)
        except Exception as ex:
            logger.exception("Failed to publish to channel: %s", channel)
            self.error.emit(ex)
            return 0

    def get_subscribed_channels(self) -> list[str]:
        """Return a list of currently subscribed channel names."""
        return list(self._channels)

    def clear(self, client: RedisClient) -> None:
        """Unsubscribe from all channels and clear the model."""
        try:
            for channel in list(self._channels):
                client.unsubscribe(channel)
            self._channels.clear()
            self._model.removeRows(0, self._model.rowCount())
            logger.info("Cleared all Pub/Sub subscriptions")
        except Exception as ex:
            logger.exception("Failed to clear Pub/Sub subscriptions")
            self.error.emit(ex)

    def _make_handler(self, channel: str):  # type: ignore[no-untyped-def]
        """Create a message handler closure for the given channel."""
        def handler(ch: str, message: str) -> None:
            timestamp = datetime.now().isoformat()
            self.message_received.emit(ch, message, timestamp)

            for row in range(self._model.rowCount()):
                item = self._model.item(row, 0)
                if item is not None and item.text() == channel:
                    msg_item = self._model.item(row, 1)
                    ts_item = self._model.item(row, 2)
                    if msg_item is not None:
                        msg_item.setText(message)
                    if ts_item is not None:
                        ts_item.setText(timestamp)
                    break

        return handler
