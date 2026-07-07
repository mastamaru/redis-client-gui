"""Tests for PubSubUI — TDD RED phase."""
from __future__ import annotations

import pytest
import fakeredis

from redisclient.redis_client import RedisClient
from rediswidgets.pubsub_widget import PubSubUI


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def client_with_fake() -> RedisClient:
    """RedisClient backed by fakeredis."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    client = RedisClient()
    client.attach(fake)
    return client


# ──────────────────────────────────────────────────────────────
# Subscribe
# ──────────────────────────────────────────────────────────────

class TestSubscribe:
    """Tests for subscribing to channels."""

    def test_subscribe_adds_channel(self, qapp, client_with_fake: RedisClient) -> None:
        """Subscribing to 'test:ch' → model has 1 row with correct channel name."""
        ui = PubSubUI()
        ui.subscribe(client_with_fake, "test:ch")

        assert ui.model.rowCount() == 1
        assert ui.model.item(0, 0).text() == "test:ch"

    def test_subscribe_multiple_channels(self, qapp, client_with_fake: RedisClient) -> None:
        """Subscribing to 3 channels → model has 3 rows."""
        ui = PubSubUI()
        ui.subscribe(client_with_fake, "ch1")
        ui.subscribe(client_with_fake, "ch2")
        ui.subscribe(client_with_fake, "ch3")

        assert ui.model.rowCount() == 3

    def test_subscribe_message_updates_model(
        self, qapp, client_with_fake: RedisClient
    ) -> None:
        """Publishing a message → model row updates with message and timestamp."""
        client = client_with_fake
        ui = PubSubUI()
        ui.subscribe(client, "test:ch")

        client.publish("test:ch", "hello")
        client._process_pubsub(timeout=1.0)

        msg_item = ui.model.item(0, 1)
        ts_item = ui.model.item(0, 2)

        assert msg_item.text() == "hello"
        assert ts_item.text() != ""


# ──────────────────────────────────────────────────────────────
# Unsubscribe
# ──────────────────────────────────────────────────────────────

class TestUnsubscribe:
    """Tests for unsubscribing from channels."""

    def test_unsubscribe_removes_channel(
        self, qapp, client_with_fake: RedisClient
    ) -> None:
        """Unsubscribing → model row is removed."""
        client = client_with_fake
        ui = PubSubUI()
        ui.subscribe(client, "test:ch")

        assert ui.model.rowCount() == 1

        ui.unsubscribe(client, "test:ch")

        assert ui.model.rowCount() == 0

    def test_unsubscribe_stops_receiving(
        self, qapp, client_with_fake: RedisClient
    ) -> None:
        """After unsubscribing, messages no longer update the model."""
        client = client_with_fake
        ui = PubSubUI()
        ui.subscribe(client, "test:ch")
        ui.unsubscribe(client, "test:ch")

        client.publish("test:ch", "should-not-arrive")
        client._process_pubsub(timeout=1.0)

        assert ui.model.rowCount() == 0


# ──────────────────────────────────────────────────────────────
# Publish
# ──────────────────────────────────────────────────────────────

class TestPublish:
    """Tests for publishing messages."""

    def test_publish_returns_subscriber_count(
        self, qapp, client_with_fake: RedisClient
    ) -> None:
        """Publishing to a channel with 1 subscriber returns >= 1."""
        client = client_with_fake
        ui = PubSubUI()
        ui.subscribe(client, "test:ch")

        count = ui.publish(client, "test:ch", "hello")

        assert count >= 1


# ──────────────────────────────────────────────────────────────
# Signal
# ──────────────────────────────────────────────────────────────

class TestSignal:
    """Tests for the message_received signal."""

    def test_message_received_signal(
        self, qapp, client_with_fake: RedisClient
    ) -> None:
        """message_received emits with (channel, message, timestamp)."""
        client = client_with_fake
        ui = PubSubUI()

        received: list[tuple[str, str, str]] = []
        ui.message_received.connect(
            lambda ch, msg, ts: received.append((ch, msg, ts))
        )

        ui.subscribe(client, "test:ch")
        client.publish("test:ch", "hello")
        client._process_pubsub(timeout=1.0)

        assert len(received) == 1
        ch, msg, ts = received[0]
        assert ch == "test:ch"
        assert msg == "hello"
        assert ts != ""


# ──────────────────────────────────────────────────────────────
# Clear and Query
# ──────────────────────────────────────────────────────────────

class TestClearAndQuery:
    """Tests for clear() and get_subscribed_channels()."""

    def test_clear_unsubscribes_all(self, qapp, client_with_fake: RedisClient) -> None:
        """clear() removes all channels and model rows."""
        client = client_with_fake
        ui = PubSubUI()
        ui.subscribe(client, "ch1")
        ui.subscribe(client, "ch2")
        ui.subscribe(client, "ch3")

        assert ui.model.rowCount() == 3

        ui.clear(client)

        assert ui.model.rowCount() == 0
        assert ui.get_subscribed_channels() == []

    def test_get_subscribed_channels(self, qapp, client_with_fake: RedisClient) -> None:
        """get_subscribed_channels returns list of active channel names."""
        client = client_with_fake
        ui = PubSubUI()
        ui.subscribe(client, "alpha")
        ui.subscribe(client, "beta")

        channels = ui.get_subscribed_channels()

        assert "alpha" in channels
        assert "beta" in channels
        assert len(channels) == 2
