from __future__ import annotations

import pytest
import fakeredis


@pytest.fixture
def fake_redis_server() -> fakeredis.FakeRedis:
    """In-memory Redis server for testing."""
    server = fakeredis.FakeRedis()
    yield server
    server.flushall()


@pytest.fixture
def sample_keys() -> dict[str, object]:
    """Sample keys to seed into fakeredis for tests."""
    return {
        "sensors:temperature:room-01": "25.5",
        "sensors:temperature:room-02": "26.1",
        "sensors:humidity:room-01": "70.2",
        "devices:controller-01:status": "online",
    }
