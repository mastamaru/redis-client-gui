"""RedisClient — core Redis connector for the GUI (replaces UaClient from opcua-client-gui)."""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

import redis
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


class RedisClient(QObject):
    """Qt-aware Redis client wrapper.

    Wraps redis-py and emits Qt signals for connection state changes.
    Designed as a drop-in replacement for the opcua-client-gui UaClient class.
    """

    connection_state_changed = pyqtSignal(str)

    def __init__(self) -> None:
        QObject.__init__(self)
        self._redis: redis.Redis | None = None
        self._connected: bool = False
        self._pubsub: redis.client.PubSub | None = None
        self._pubsub_thread: threading.Thread | None = None
        self._pubsub_handlers: dict[str, Callable[[str, str], None]] = {}
        self._pubsub_stop = threading.Event()

    @property
    def is_connected(self) -> bool:
        return self._connected

    def attach(self, redis_instance: redis.Redis) -> None:
        """Attach a pre-existing Redis connection (for testing with fakeredis)."""
        self._redis = redis_instance
        self._connected = True
        self.connection_state_changed.emit("connected")

    def connect(
        self,
        host: str = "localhost",
        port: int = 6379,
        password: str | None = None,
        db: int = 0,
        use_tls: bool = False,
        tls_cert: str | None = None,
        tls_key: str | None = None,
        tls_ca_cert: str | None = None,
        username: str | None = None,
        socket_timeout: float = 5.0,
    ) -> bool:
        """Connect to Redis server. Emits connection_state_changed."""
        self.connection_state_changed.emit("connecting")
        kwargs: dict[str, Any] = {
            "host": host,
            "port": port,
            "db": db,
            "decode_responses": True,
            "socket_timeout": socket_timeout,
        }
        if password:
            kwargs["password"] = password
        if username:
            kwargs["username"] = username
        if use_tls:
            kwargs["ssl"] = True
            if tls_cert:
                kwargs["ssl_certfile"] = tls_cert
            if tls_key:
                kwargs["ssl_keyfile"] = tls_key
            if tls_ca_cert:
                kwargs["ssl_ca_certs"] = tls_ca_cert

        try:
            self._redis = redis.Redis(**kwargs)
            self._redis.ping()
        except Exception as ex:
            logger.exception("Failed to connect to Redis at %s:%s", host, port)
            self._connected = False
            self.connection_state_changed.emit("error")
            raise ConnectionError(f"Failed to connect to Redis: {ex}") from ex

        self._connected = True
        logger.info("Connected to Redis at %s:%s db=%s tls=%s", host, port, db, use_tls)
        self.connection_state_changed.emit("connected")
        return True

    def disconnect(self) -> None:
        """Disconnect from Redis server. Emits 'disconnected'."""
        if not self._connected:
            return

        self._stop_pubsub()

        if self._redis is not None:
            try:
                self._redis.close()
            except Exception:
                logger.exception("Error closing Redis connection")

        self._redis = None
        self._connected = False
        logger.info("Disconnected from Redis")
        self.connection_state_changed.emit("disconnected")

    def ping(self) -> bool:
        """Return True if server responds to PING."""
        if not self._connected or self._redis is None:
            raise ConnectionError("Not connected to Redis")
        return bool(self._redis.ping())

    def _require_redis(self) -> redis.Redis:
        """Return the Redis instance or raise if not connected."""
        if not self._connected or self._redis is None:
            raise ConnectionError("Not connected to Redis")
        return self._redis

    def hmget_fields(self, hash_key: str, fields: list[str]) -> dict[str, str | None]:
        """HMGET specific fields from a hash. Returns {field: value_or_None}."""
        r = self._require_redis()
        if not fields:
            return {}
        values = r.hmget(hash_key, fields)
        return {f: v for f, v in zip(fields, values)}

    def hgetall_hash(self, hash_key: str) -> dict[str, str]:
        """HGETALL — return all field-value pairs of a hash."""
        r = self._require_redis()
        return r.hgetall(hash_key)

    def hkeys(self, hash_key: str) -> list[str]:
        """Return all field names in a hash (without values)."""
        r = self._require_redis()
        return r.hkeys(hash_key)

    def scan_keys(self, pattern: str = "*") -> list[str]:
        """Scan keyspace using SCAN. Returns list of key names matching pattern."""
        r = self._require_redis()
        keys: list[str] = []
        cursor: int = 0
        while True:
            cursor, batch = r.scan(cursor=cursor, match=pattern, count=100)
            keys.extend(batch)
            if cursor == 0:
                break
        return sorted(keys)

    def get_key_metadata(self, key_name: str) -> dict[str, Any]:
        """Return metadata for a key: type, ttl, size."""
        r = self._require_redis()
        key_type = r.type(key_name)
        ttl = r.ttl(key_name)

        size_map: dict[str, Callable[[], int]] = {
            "string": lambda: r.strlen(key_name),
            "hash": lambda: r.hlen(key_name),
            "list": lambda: r.llen(key_name),
            "set": lambda: r.scard(key_name),
            "zset": lambda: r.zcard(key_name),
            "stream": lambda: r.xlen(key_name),
        }
        size = size_map.get(key_type, lambda: 0)()

        return {
            "type": key_type,
            "ttl": ttl,
            "size": size,
        }

    def get_value(self, key_name: str) -> Any:
        """Get value of a key, auto-detecting type. Return depends on type:
        string -> str, hash -> dict, list -> list, set -> set, zset -> list[tuple[str, float]]
        """
        r = self._require_redis()
        key_type = r.type(key_name)

        if key_type == "string":
            return r.get(key_name)
        elif key_type == "hash":
            return r.hgetall(key_name)
        elif key_type == "list":
            return r.lrange(key_name, 0, -1)
        elif key_type == "set":
            return r.smembers(key_name)
        elif key_type == "zset":
            members = r.zrange(key_name, 0, -1, withscores=True)
            return [(member, score) for member, score in members]
        elif key_type == "stream":
            entries = r.xrange(key_name)
            return entries
        else:
            return None

    def set_value(self, key_name: str, value: Any) -> None:
        """Set value of a key. Type is inferred from Python type:
        str -> string, dict -> hash, list -> list, set -> set
        """
        r = self._require_redis()

        if isinstance(value, str):
            r.set(key_name, value)
        elif isinstance(value, dict):
            if r.exists(key_name):
                r.delete(key_name)
            r.hset(key_name, mapping=value)
        elif isinstance(value, list):
            if r.exists(key_name):
                r.delete(key_name)
            if value:
                r.rpush(key_name, *value)
        elif isinstance(value, set):
            if r.exists(key_name):
                r.delete(key_name)
            if value:
                r.sadd(key_name, *value)
        else:
            r.set(key_name, str(value))

    def delete_key(self, key_name: str) -> None:
        """Delete a key. No error if key doesn't exist."""
        r = self._require_redis()
        r.delete(key_name)

    def subscribe(self, channel: str, handler: Callable[[str, str], None]) -> None:
        """Subscribe to a Pub/Sub channel with a handler callback."""
        r = self._require_redis()
        self._pubsub_handlers[channel] = handler

        if self._pubsub is None:
            self._pubsub = r.pubsub()
            self._pubsub_stop.clear()
            self._pubsub_thread = threading.Thread(
                target=self._pubsub_loop, daemon=True
            )
            self._pubsub_thread.start()

        self._pubsub.subscribe(channel)
        logger.info("Subscribed to channel: %s", channel)

    def unsubscribe(self, channel: str) -> None:
        """Unsubscribe from a Pub/Sub channel."""
        self._pubsub_handlers.pop(channel, None)
        if self._pubsub is not None:
            self._pubsub.unsubscribe(channel)
        logger.info("Unsubscribed from channel: %s", channel)

    def publish(self, channel: str, message: str) -> int:
        """Publish a message to a channel. Returns number of subscribers reached."""
        r = self._require_redis()
        return r.publish(channel, message)

    def _pubsub_loop(self) -> None:
        """Background thread that listens for Pub/Sub messages."""
        if self._pubsub is None:
            return
        while not self._pubsub_stop.is_set():
            try:
                msg = self._pubsub.get_message(timeout=0.5)
                if msg and msg["type"] == "message":
                    channel = msg["channel"]
                    data = msg["data"]
                    handler = self._pubsub_handlers.get(channel)
                    if handler:
                        handler(channel, data)
            except Exception:
                logger.exception("Error in Pub/Sub loop")

    def _process_pubsub(self, timeout: float = 1.0) -> None:
        """Process Pub/Sub messages synchronously (for testing)."""
        if self._pubsub is None:
            return
        deadline = threading.Event()
        import time
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            msg = self._pubsub.get_message(timeout=0.1)
            if msg and msg["type"] == "message":
                channel = msg["channel"]
                data = msg["data"]
                handler = self._pubsub_handlers.get(channel)
                if handler:
                    handler(channel, data)

    def _stop_pubsub(self) -> None:
        """Stop Pub/Sub thread and clean up."""
        self._pubsub_stop.set()
        if self._pubsub_thread is not None and self._pubsub_thread.is_alive():
            self._pubsub_thread.join(timeout=2.0)
        self._pubsub_thread = None
        if self._pubsub is not None:
            try:
                self._pubsub.close()
            except Exception:
                logger.exception("Error closing Pub/Sub")
        self._pubsub = None
        self._pubsub_handlers.clear()

    def execute_command(self, command: str, *args: Any) -> Any:
        """Execute a raw Redis command."""
        r = self._require_redis()
        return r.execute_command(command, *args)

    def eval_script(self, script: str, keys: list[str] | None = None, args: list[Any] | None = None) -> Any:
        """Execute a Lua script via EVAL."""
        r = self._require_redis()
        numkeys = len(keys) if keys else 0
        full_args: list[Any] = list(keys or []) + list(args or [])
        return r.eval(script, numkeys, *full_args)

    def shutdown(self) -> None:
        """Clean shutdown. Call on application exit."""
        self.disconnect()
