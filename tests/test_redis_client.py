"""Tests for RedisClient — TDD RED phase."""
from __future__ import annotations

import threading
import time
from typing import Any

import fakeredis
import pytest

from redisclient.redis_client import RedisClient


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def client_with_fake() -> tuple[RedisClient, fakeredis.FakeRedis]:
    """Create a RedisClient attached to a fakeredis instance."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    client = RedisClient()
    client.attach(fake)
    return client, fake


# ──────────────────────────────────────────────────────────────
# Connect / Disconnect / Ping
# ──────────────────────────────────────────────────────────────

class TestConnect:
    def test_connect_non_tls_emits_connected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        states: list[str] = []
        client = RedisClient()
        client.connection_state_changed.connect(lambda s: states.append(s))

        def _fake_redis_factory(**kwargs: Any) -> fakeredis.FakeRedis:
            return fakeredis.FakeRedis(decode_responses=True)

        monkeypatch.setattr("redis.Redis", _fake_redis_factory)
        client.connect(host="localhost", port=6379)

        assert client.is_connected
        assert "connected" in states

    def test_connect_tls_sets_ssl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_redis_factory(**kwargs: Any) -> fakeredis.FakeRedis:
            captured.update(kwargs)
            return fakeredis.FakeRedis(decode_responses=True)

        monkeypatch.setattr("redis.Redis", _fake_redis_factory)
        client = RedisClient()
        client.connect(
            host="localhost",
            port=6380,
            use_tls=True,
            tls_cert="/path/cert.pem",
            tls_key="/path/key.pem",
            tls_ca_cert="/path/ca.pem",
        )

        assert captured.get("ssl") is True
        assert captured.get("ssl_certfile") == "/path/cert.pem"
        assert captured.get("ssl_keyfile") == "/path/key.pem"
        assert captured.get("ssl_ca_certs") == "/path/ca.pem"

    def test_connect_failure_emits_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        states: list[str] = []
        client = RedisClient()
        client.connection_state_changed.connect(lambda s: states.append(s))

        def _failing_redis_factory(**kwargs: Any) -> Any:
            raise ConnectionError("Connection refused")

        monkeypatch.setattr("redis.Redis", _failing_redis_factory)

        with pytest.raises(ConnectionError):
            client.connect(host="bad-host", port=9999)

        assert "error" in states
        assert not client.is_connected


class TestPing:
    def test_ping_returns_true_when_connected(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, _ = client_with_fake
        assert client.ping() is True

    def test_ping_raises_when_not_connected(self) -> None:
        client = RedisClient()
        with pytest.raises(ConnectionError, match="Not connected"):
            client.ping()


class TestDisconnect:
    def test_disconnect_emits_disconnected(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, _ = client_with_fake
        states: list[str] = []
        client.connection_state_changed.connect(lambda s: states.append(s))

        client.disconnect()

        assert "disconnected" in states
        assert not client.is_connected

    def test_disconnect_when_already_disconnected_is_noop(self) -> None:
        client = RedisClient()
        client.disconnect()
        assert not client.is_connected


# ──────────────────────────────────────────────────────────────
# scan_keys
# ──────────────────────────────────────────────────────────────

class TestScanKeys:
    def test_scan_keys_returns_all_keys(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        fake.set("sensors:temp:01", "25.5")
        fake.set("devices:ctrl:status", "online")

        keys = client.scan_keys()
        assert "sensors:temp:01" in keys
        assert "devices:ctrl:status" in keys

    def test_scan_keys_with_prefix_pattern(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        fake.set("sensors:temp:01", "25.5")
        fake.set("sensors:temp:02", "26.0")
        fake.set("sensors:humidity:01", "70")
        fake.set("devices:status", "ok")

        keys = client.scan_keys(pattern="sensors:temp:*")
        assert sorted(keys) == ["sensors:temp:01", "sensors:temp:02"]

    def test_scan_keys_empty_keyspace(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, _ = client_with_fake
        assert client.scan_keys() == []

    def test_scan_keys_with_exact_match(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        fake.set("mykey", "val")

        keys = client.scan_keys(pattern="mykey")
        assert keys == ["mykey"]


# ──────────────────────────────────────────────────────────────
# get_key_metadata
# ──────────────────────────────────────────────────────────────

class TestGetKeyMetadata:
    def test_metadata_string_key(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        fake.set("test:string", "hello")

        meta = client.get_key_metadata("test:string")

        assert meta["type"] == "string"
        assert meta["size"] == 5
        assert meta["ttl"] == -1

    def test_metadata_hash_key(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        fake.hset("test:hash", mapping={"field1": "val1", "field2": "val2"})

        meta = client.get_key_metadata("test:hash")

        assert meta["type"] == "hash"
        assert meta["size"] == 2

    def test_metadata_list_key(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        fake.lpush("test:list", "a", "b", "c")

        meta = client.get_key_metadata("test:list")

        assert meta["type"] == "list"
        assert meta["size"] == 3

    def test_metadata_set_key(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        fake.sadd("test:set", "x", "y")

        meta = client.get_key_metadata("test:set")

        assert meta["type"] == "set"
        assert meta["size"] == 2

    def test_metadata_zset_key(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        fake.zadd("test:zset", {"alpha": 1, "beta": 2})

        meta = client.get_key_metadata("test:zset")

        assert meta["type"] == "zset"
        assert meta["size"] == 2

    def test_metadata_with_ttl(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        fake.set("test:ttl", "temp")
        fake.expire("test:ttl", 120)

        meta = client.get_key_metadata("test:ttl")

        assert meta["ttl"] > 0
        assert meta["ttl"] <= 120

    def test_metadata_nonexistent_key(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, _ = client_with_fake
        meta = client.get_key_metadata("does:not:exist")
        assert meta["type"] == "none"


# ──────────────────────────────────────────────────────────────
# get_value (multi-type)
# ──────────────────────────────────────────────────────────────

class TestGetValue:
    def test_get_value_string(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        fake.set("str:key", "hello world")
        assert client.get_value("str:key") == "hello world"

    def test_get_value_hash(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        fake.hset("hash:key", mapping={"a": "1", "b": "2"})
        assert client.get_value("hash:key") == {"a": "1", "b": "2"}

    def test_get_value_list(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        fake.rpush("list:key", "x", "y", "z")
        assert client.get_value("list:key") == ["x", "y", "z"]

    def test_get_value_set(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        fake.sadd("set:key", "m1", "m2")
        assert client.get_value("set:key") == {"m1", "m2"}

    def test_get_value_zset(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        fake.zadd("zset:key", {"low": 1, "high": 10})
        result = client.get_value("zset:key")
        assert isinstance(result, list)
        assert ("low", 1.0) in result
        assert ("high", 10.0) in result


# ──────────────────────────────────────────────────────────────
# set_value
# ──────────────────────────────────────────────────────────────

class TestSetValue:
    def test_set_value_string(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        client.set_value("new:str", "test123")
        assert fake.get("new:str") == "test123"

    def test_set_value_hash(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        client.set_value("new:hash", {"field1": "val1"})
        assert fake.hgetall("new:hash") == {"field1": "val1"}

    def test_set_value_list(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        client.set_value("new:list", ["a", "b", "c"])
        assert fake.lrange("new:list", 0, -1) == ["a", "b", "c"]

    def test_set_value_set(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        client.set_value("new:set", {"x", "y"})
        assert fake.smembers("new:set") == {"x", "y"}


# ──────────────────────────────────────────────────────────────
# delete_key
# ──────────────────────────────────────────────────────────────

class TestDeleteKey:
    def test_delete_existing_key(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        fake.set("to:delete", "bye")
        client.delete_key("to:delete")
        assert not fake.exists("to:delete")

    def test_delete_nonexistent_key_no_error(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, _ = client_with_fake
        client.delete_key("no:such:key")


# ──────────────────────────────────────────────────────────────
# Pub/Sub
# ──────────────────────────────────────────────────────────────

class TestPubSub:
    def test_publish_and_subscribe(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, fake = client_with_fake
        received: list[str] = []

        def handler(channel: str, message: str) -> None:
            received.append(message)

        client.subscribe("test:channel", handler)
        client.publish("test:channel", "hello")

        client._process_pubsub(timeout=1.0)

        assert "hello" in received

    def test_unsubscribe_stops_receiving(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, _ = client_with_fake
        received: list[str] = []

        def handler(channel: str, message: str) -> None:
            received.append(message)

        client.subscribe("test:ch2", handler)
        client.unsubscribe("test:ch2")
        client.publish("test:ch2", "should-not-arrive")

        assert received == []


# ──────────────────────────────────────────────────────────────
# execute_command & eval_script
# ──────────────────────────────────────────────────────────────

class TestExecuteCommand:
    def test_execute_ping(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, _ = client_with_fake
        result = client.execute_command("PING")
        assert result is True or result == "PONG" or result == b"PONG" or result == True

    def test_execute_set_get(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, _ = client_with_fake
        client.execute_command("SET", "cmd:test", "value")
        result = client.execute_command("GET", "cmd:test")
        assert result == "value"

    def test_eval_simple_script(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, _ = client_with_fake
        client.execute_command("SET", "evalkey", "42")
        result = client.eval_script("return redis.call('GET', KEYS[1])", keys=["evalkey"])
        assert result == "42"

    def test_eval_return_type_number(self, client_with_fake: tuple[RedisClient, Any]) -> None:
        client, _ = client_with_fake
        result = client.eval_script("return 100", keys=[])
        assert result == 100
