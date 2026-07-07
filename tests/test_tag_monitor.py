"""Tests for TagMonitorUI — hash field polling."""
from __future__ import annotations

import pytest
import fakeredis

from redisclient.redis_client import RedisClient
from rediswidgets.tag_monitor import TagMonitorUI


@pytest.fixture
def client_with_tags():
    fake = fakeredis.FakeRedis(decode_responses=True)
    fake.hset("ots-pim:tags", mapping={
        "LIC1003A_PV": "25.5",
        "LIC1003A_SP": "26.0",
        "A107JA_RUN": "1",
        "XV1220A": "0",
        "SimStatus": "RUNNING",
    })
    fake.hset("ots-pim:tagtypes", mapping={
        "LIC1003A_PV": "float",
        "LIC1003A_SP": "float",
        "A107JA_RUN": "bool",
        "XV1220A": "bool",
        "SimStatus": "string",
    })
    client = RedisClient()
    client.attach(fake)
    return client


class TestTagMonitorSetup:
    def test_model_has_correct_headers(self, qapp):
        ui = TagMonitorUI()
        assert ui.model.horizontalHeaderItem(0).text() == "Tag"
        assert ui.model.horizontalHeaderItem(1).text() == "Value"
        assert ui.model.horizontalHeaderItem(2).text() == "Type"
        assert ui.model.horizontalHeaderItem(3).text() == "Last Updated"

    def test_set_client_loads_tagtypes(self, qapp, client_with_tags):
        ui = TagMonitorUI()
        ui.set_client(client_with_tags)
        ui.add_tag("LIC1003A_PV")
        assert ui.model.item(0, 2).text() == "float"

    def test_add_tag_creates_row(self, qapp, client_with_tags):
        ui = TagMonitorUI()
        ui.set_client(client_with_tags)
        ui.add_tag("LIC1003A_PV")
        assert ui.model.rowCount() == 1
        assert ui.model.item(0, 0).text() == "LIC1003A_PV"

    def test_add_duplicate_ignored(self, qapp, client_with_tags):
        ui = TagMonitorUI()
        ui.set_client(client_with_tags)
        ui.add_tag("LIC1003A_PV")
        ui.add_tag("LIC1003A_PV")
        assert ui.model.rowCount() == 1


class TestTagMonitorPolling:
    def test_poll_updates_value(self, qapp, client_with_tags):
        ui = TagMonitorUI()
        ui.set_client(client_with_tags)
        ui.add_tag("LIC1003A_PV")
        ui._poll()
        assert ui.model.item(0, 1).text() == "25.500"

    def test_poll_updates_bool_display(self, qapp, client_with_tags):
        ui = TagMonitorUI()
        ui.set_client(client_with_tags)
        ui.add_tag("A107JA_RUN")
        ui._poll()
        assert ui.model.item(0, 1).text() == "ON"

    def test_poll_updates_bool_off(self, qapp, client_with_tags):
        ui = TagMonitorUI()
        ui.set_client(client_with_tags)
        ui.add_tag("XV1220A")
        ui._poll()
        assert ui.model.item(0, 1).text() == "OFF"

    def test_poll_updates_string_display(self, qapp, client_with_tags):
        ui = TagMonitorUI()
        ui.set_client(client_with_tags)
        ui.add_tag("SimStatus")
        ui._poll()
        assert ui.model.item(0, 1).text() == "RUNNING"

    def test_poll_updates_timestamp(self, qapp, client_with_tags):
        ui = TagMonitorUI()
        ui.set_client(client_with_tags)
        ui.add_tag("LIC1003A_PV")
        ui._poll()
        ts = ui.model.item(0, 3).text()
        assert len(ts) > 0

    def test_poll_detects_value_change(self, qapp, client_with_tags):
        ui = TagMonitorUI()
        ui.set_client(client_with_tags)
        ui.add_tag("LIC1003A_PV")
        ui._poll()
        assert ui.model.item(0, 1).text() == "25.500"
        # Simulate value change
        client_with_tags._redis.hset("ots-pim:tags", "LIC1003A_PV", "30.2")
        ui._poll()
        assert ui.model.item(0, 1).text() == "30.200"


class TestTagMonitorRemove:
    def test_remove_tag(self, qapp, client_with_tags):
        ui = TagMonitorUI()
        ui.set_client(client_with_tags)
        ui.add_tag("LIC1003A_PV")
        ui.add_tag("A107JA_RUN")
        assert ui.model.rowCount() == 2
        ui.remove_tag("LIC1003A_PV")
        assert ui.model.rowCount() == 1
        assert ui.model.item(0, 0).text() == "A107JA_RUN"

    def test_remove_nonexistent_no_error(self, qapp, client_with_tags):
        ui = TagMonitorUI()
        ui.set_client(client_with_tags)
        ui.remove_tag("DOES_NOT_EXIST")

    def test_clear_removes_all(self, qapp, client_with_tags):
        ui = TagMonitorUI()
        ui.set_client(client_with_tags)
        ui.add_tag("LIC1003A_PV")
        ui.add_tag("A107JA_RUN")
        ui.clear()
        assert ui.model.rowCount() == 0
        assert ui.get_monitored_tags() == []


class TestTagMonitorControls:
    def test_build_controls_returns_widget(self, qapp):
        ui = TagMonitorUI()
        w = ui.build_controls()
        assert w is not None

    def test_add_via_input(self, qapp, client_with_tags):
        ui = TagMonitorUI()
        ui.set_client(client_with_tags)
        controls = ui.build_controls()
        controls.setParent(None)  # keep alive
        ui._tag_input.setText("LIC1003A_SP")
        ui._on_add_clicked()
        assert "LIC1003A_SP" in ui.get_monitored_tags()
